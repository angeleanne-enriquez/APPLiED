import datetime
import json

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Blueprint, jsonify, request

from config import DATABASE_URL
from services.draft_generator import generate_application_packet
from services.storage import save_application_packet

applications_bp = Blueprint("applications", __name__)

# ─── db ───────────────────────────────────────────────────────────────────────

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)


# ─── utils ────────────────────────────────────────────────────────────────────

def _serialize_record(record: dict | None) -> dict | None:
    if not record:
        return record

    return {
        k: (v.isoformat() if hasattr(v, "isoformat") else v)
        for k, v in record.items()
    }


# ─── fetch helpers ────────────────────────────────────────────────────────────

def fetch_profile(user_id: str) -> dict | None:
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("""
        SELECT
            u.id as user_id,
            u.email,
            u.first_name,
            u.last_name,
            p.resume_text,
            p.preferences_json
        FROM users u
        JOIN profiles p ON p.user_id = u.id
        WHERE u.id = %s
    """, (user_id,))

    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row:
        return None

    prefs = row.get("preferences_json")
    if isinstance(prefs, str):
        try:
            row["preferences_json"] = json.loads(prefs)
        except Exception:
            row["preferences_json"] = {}

    return dict(row)


def fetch_job(job_posting_id: str) -> dict | None:
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("""
        SELECT
            id,
            external_id,
            source,
            title,
            company,
            COALESCE(location_normalized, location) AS location,
            COALESCE(apply_url, url) AS url,
            description,
            raw_json,
            ingested_at,
            COALESCE(category, schedule_type) AS category
        FROM job_postings
        WHERE id = %s
    """, (job_posting_id,))

    row = cur.fetchone()
    cur.close()
    conn.close()

    return dict(row) if row else None


def fetch_best_match_for_user_job(user_id: str, job_posting_id: str) -> dict | None:
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("""
        SELECT user_id, job_posting_id, score, rationale, created_at
        FROM job_matches
        WHERE user_id = %s AND job_posting_id = %s
        ORDER BY score DESC, created_at DESC
        LIMIT 1
    """, (user_id, job_posting_id))

    row = cur.fetchone()
    cur.close()
    conn.close()

    return dict(row) if row else None


def fetch_top_matches_for_user(user_id: str, top_k: int = 1) -> list[dict]:
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("""
        SELECT *
        FROM (
            SELECT DISTINCT ON (jm.job_posting_id)
                jm.user_id,
                jm.job_posting_id,
                jm.score,
                jm.rationale,
                jm.created_at
            FROM job_matches jm
            WHERE jm.user_id = %s
            ORDER BY jm.job_posting_id, jm.score DESC, jm.created_at DESC
        ) ranked
        ORDER BY ranked.score DESC, ranked.created_at DESC
        LIMIT %s
    """, (user_id, top_k))

    rows = cur.fetchall()
    cur.close()
    conn.close()

    return [dict(r) for r in rows]


def upsert_application(user_id: str, job_posting_id: str, status: str, draft_path: str | None):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("""
        INSERT INTO applications (user_id, job_posting_id, status, draft_path)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (user_id, job_posting_id)
        DO UPDATE SET
            status = EXCLUDED.status,
            draft_path = EXCLUDED.draft_path
        RETURNING id, user_id, job_posting_id, status, draft_path, created_at
    """, (user_id, job_posting_id, status, draft_path))

    row = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()

    return dict(row)


# ─── core logic ───────────────────────────────────────────────────────────────

def generate_single_draft(profile: dict, user_id: str, match_row: dict) -> dict:
    job_posting_id = match_row["job_posting_id"]

    job = fetch_job(job_posting_id)
    if not job:
        raise ValueError(f"Job posting not found: {job_posting_id}")

    drafting = upsert_application(user_id, job_posting_id, "drafting", None)

    packet = generate_application_packet(
        profile=profile,
        job=job,
        match_context=match_row,
    )

    saved = save_application_packet(
        user_id=user_id,
        job_posting_id=job_posting_id,
        resume_markdown=packet["resume_markdown"],
        cover_letter_markdown=packet["cover_letter_markdown"],
        manifest=packet["manifest"],
    )

    ready = upsert_application(
        user_id,
        job_posting_id,
        "ready_for_review",
        saved["manifest_path"],
    )

    return {
        "selected_match": _serialize_record(match_row),
        "job": {
            "id": str(job["id"]),
            "title": job.get("title"),
            "company": job.get("company"),
            "location": job.get("location"),
            "url": job.get("url"),
            "category": job.get("category"),
        },
        "application": _serialize_record(ready),
        "files": {
            "manifest_path": saved["manifest_path"],
            "resume_path": saved["resume_path"],
            "cover_letter_path": saved["cover_letter_path"],
        },
        "preview": {
            "resume_markdown": packet["resume_markdown"],
            "cover_letter_markdown": packet["cover_letter_markdown"],
        },
        "drafting_row_before_finalize": _serialize_record(drafting),
    }


# ─── routes ───────────────────────────────────────────────────────────────────

@applications_bp.route("/applications", methods=["GET"])
def list_applications():
    user_id = request.args.get("user_id")
    if not user_id:
        return jsonify({"status": "error", "message": "user_id is required"}), 400

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT a.id, a.user_id, a.job_posting_id, a.status,
                   a.draft_path, a.created_at,
                   jp.title, jp.company, jp.location, jp.remote_type
            FROM applications a
            JOIN job_postings jp ON jp.id = a.job_posting_id
            WHERE a.user_id = %s
            ORDER BY a.created_at DESC
        """, (user_id,))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify({
            "status": "success",
            "applications": [_serialize_record(dict(r)) for r in rows],
            "count": len(rows),
        }), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@applications_bp.route("/applications/save", methods=["POST"])
def save_job():
    data = request.get_json() or {}
    user_id = data.get("user_id")
    job_posting_id = data.get("job_posting_id")

    if not user_id or not job_posting_id:
        return jsonify({"status": "error", "message": "user_id and job_posting_id are required"}), 400

    try:
        result = upsert_application(user_id, job_posting_id, "saved", None)
        return jsonify({"status": "success", "application": _serialize_record(result)}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@applications_bp.route("/applications/draft", methods=["POST"])
def create_application_draft():
    timestamp = datetime.datetime.now().isoformat()

    try:
        data = request.get_json() or {}

        user_id = data.get("user_id")
        job_id = data.get("job_posting_id")
        use_top = data.get("use_top_match", job_id is None)
        top_k = int(data.get("top_k", 1))

        if not user_id:
            return jsonify({"status": "error", "message": "user_id is required", "timestamp": timestamp}), 400

        if top_k < 1:
            return jsonify({"status": "error", "message": "top_k must be >= 1", "timestamp": timestamp}), 400

        profile = fetch_profile(user_id)
        if not profile:
            return jsonify({"status": "error", "message": "Profile not found", "timestamp": timestamp}), 404

        # ── select matches ──
        if job_id:
            match = fetch_best_match_for_user_job(user_id, job_id) or {
                "user_id": user_id,
                "job_posting_id": job_id,
                "score": None,
                "rationale": "No stored match found",
                "created_at": None,
            }
            matches = [match]

        else:
            if not use_top:
                return jsonify({"status": "error", "message": "Provide job_posting_id or use_top_match=true", "timestamp": timestamp}), 400

            matches = fetch_top_matches_for_user(user_id, top_k)
            if not matches:
                return jsonify({"status": "error", "message": "No matches found. Run /agent first.", "timestamp": timestamp}), 404

        # ── generate drafts ──
        results = [
            generate_single_draft(profile, user_id, m)
            for m in matches
        ]

        response = {
            "status": "success",
            "message": f"Generated {len(results)} draft(s)",
            "timestamp": timestamp,
            "count": len(results),
            "results": results,
        }

        if len(results) == 1:
            response.update(results[0])

        return jsonify(response), 200

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e),
            "timestamp": timestamp,
        }), 500