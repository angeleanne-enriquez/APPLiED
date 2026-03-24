import json
import datetime
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Blueprint, jsonify, request

from config import DATABASE_URL
from services.draft_generator import generate_application_packet
from services.storage import save_application_packet

applications_bp = Blueprint("applications", __name__)


def get_db_connection():
    return psycopg2.connect(DATABASE_URL)


def fetch_profile(user_id: str) -> dict | None:
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute(
        """
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
        """,
        (user_id,),
    )
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

    cur.execute(
        """
        SELECT
            id,
            external_id,
            source,
            title,
            company,
            location,
            url,
            description,
            raw_json,
            ingested_at,
            category
        FROM job_postings
        WHERE id = %s
        """,
        (job_posting_id,),
    )
    row = cur.fetchone()

    cur.close()
    conn.close()

    return dict(row) if row else None


def upsert_application(user_id: str, job_posting_id: str, status: str, draft_path: str | None):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute(
        """
        INSERT INTO applications (user_id, job_posting_id, status, draft_path)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (user_id, job_posting_id)
        DO UPDATE SET
            status = EXCLUDED.status,
            draft_path = EXCLUDED.draft_path
        RETURNING id, user_id, job_posting_id, status, draft_path, created_at
        """,
        (user_id, job_posting_id, status, draft_path),
    )

    row = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()

    return dict(row)


@applications_bp.route("/applications/draft", methods=["POST"])
def create_application_draft():
    timestamp = datetime.datetime.now().isoformat()

    try:
        data = request.get_json() or {}
        user_id = data.get("user_id")
        job_posting_id = data.get("job_posting_id")

        if not user_id or not job_posting_id:
            return jsonify({
                "status": "error",
                "message": "user_id and job_posting_id are required",
                "timestamp": timestamp,
            }), 400

        profile = fetch_profile(user_id)
        if not profile:
            return jsonify({
                "status": "error",
                "message": "Profile not found for user_id",
                "timestamp": timestamp,
            }), 404

        job = fetch_job(job_posting_id)
        if not job:
            return jsonify({
                "status": "error",
                "message": "Job posting not found",
                "timestamp": timestamp,
            }), 404

        application_row = upsert_application(
            user_id=user_id,
            job_posting_id=job_posting_id,
            status="drafting",
            draft_path=None,
        )

        packet = generate_application_packet(profile, job)

        saved_files = save_application_packet(
            user_id=user_id,
            job_posting_id=job_posting_id,
            resume_markdown=packet["resume_markdown"],
            cover_letter_markdown=packet["cover_letter_markdown"],
            manifest=packet["manifest"],
        )

        application_row = upsert_application(
            user_id=user_id,
            job_posting_id=job_posting_id,
            status="ready_for_review",
            draft_path=saved_files["manifest_path"],
        )

        return jsonify({
            "status": "success",
            "message": "Application draft generated",
            "timestamp": timestamp,
            "application": application_row,
            "files": {
                "manifest_path": saved_files["manifest_path"],
                "resume_path": saved_files["resume_path"],
                "cover_letter_path": saved_files["cover_letter_path"],
            },
            "preview": {
                "resume_markdown": packet["resume_markdown"],
                "cover_letter_markdown": packet["cover_letter_markdown"],
            },
        }), 200

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Failed to generate application draft: {str(e)}",
            "timestamp": timestamp,
        }), 500