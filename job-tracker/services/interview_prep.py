import datetime
import hashlib
import json
from uuid import UUID

import psycopg2
from psycopg2.extras import Json, RealDictCursor
from flask import Blueprint, jsonify, render_template, request, url_for

from config import DATABASE_URL
from services.applications import fetch_job, fetch_profile
from services.interview_generator import (
    generate_interview_brief,
    generate_interviewer_reply,
    generate_mock_questions,
    generate_session_feedback,
)
from services.interview_research import gather_interview_research
from services.schema import ensure_interview_prep_schema


interview_prep_bp = Blueprint("interview_prep", __name__)

APPLICATION_STATUS_INTERVIEWING = "interviewing"

BRIEF_STATUS_GENERATED = "generated"
BRIEF_STATUS_FAILED = "failed"
BRIEF_STATUSES = {BRIEF_STATUS_GENERATED, BRIEF_STATUS_FAILED}

SESSION_STATUS_ACTIVE = "active"
SESSION_STATUS_COMPLETED = "completed"
SESSION_STATUSES = {SESSION_STATUS_ACTIVE, SESSION_STATUS_COMPLETED}

FEEDBACK_TYPE_INTERIM = "interim"
FEEDBACK_TYPE_FINAL = "final"
FEEDBACK_TYPES = {FEEDBACK_TYPE_INTERIM, FEEDBACK_TYPE_FINAL}


def get_db_connection():
    return psycopg2.connect(DATABASE_URL)


def _timestamp() -> str:
    return datetime.datetime.now().isoformat()


def _serialize_value(value):
    if isinstance(value, UUID):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, list):
        return [_serialize_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize_value(item) for key, item in value.items()}
    return value


def _serialize_record(record: dict | None) -> dict | None:
    if record is None:
        return None
    return {key: _serialize_value(value) for key, value in dict(record).items()}


def _serialize_rows(rows: list[dict]) -> list[dict]:
    return [_serialize_record(row) for row in rows]


def _json_error(message: str, status_code: int = 400):
    return jsonify({
        "status": "error",
        "message": message,
        "timestamp": _timestamp(),
    }), status_code


def _json_success(payload: dict, status_code: int = 200):
    return jsonify({
        "status": "success",
        "timestamp": _timestamp(),
        **payload,
    }), status_code


def _bounded_int(value, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _validate_brief_status(status: str) -> str:
    if status not in BRIEF_STATUSES:
        raise ValueError(f"Unsupported interview prep brief status: {status}")
    return status


def _validate_session_status(status: str) -> str:
    if status not in SESSION_STATUSES:
        raise ValueError(f"Unsupported interview practice session status: {status}")
    return status


def _feedback_type_from_payload(data: dict) -> str:
    feedback_type = data.get("feedback_type")
    if feedback_type is None:
        feedback_type = FEEDBACK_TYPE_FINAL if data.get("end_session", False) else FEEDBACK_TYPE_INTERIM

    if feedback_type not in FEEDBACK_TYPES:
        raise ValueError("feedback_type must be 'interim' or 'final'")

    if data.get("end_session", False) and feedback_type != FEEDBACK_TYPE_FINAL:
        raise ValueError("end_session=true requires feedback_type='final'")

    return feedback_type


def _source_key(source: dict) -> str:
    url = (source.get("url") or "").strip().lower()
    if url:
        basis = f"url:{url}"
    else:
        basis = "|".join([
            "source",
            str(source.get("source_type") or "web").strip().lower(),
            str(source.get("title") or "").strip().lower(),
            str(source.get("snippet") or "").strip().lower(),
            str(source.get("query") or "").strip().lower(),
            str(source.get("rank") or "").strip(),
        ])
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def _brief_json(record: dict | None) -> dict | None:
    if not record:
        return None

    value = record.get("brief_json")
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {}
    return value or {}


def _feedback_json(record: dict | None) -> dict:
    if not record:
        return {}

    value = record.get("feedback_json")
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {}
    return value or {}


def _fetch_profile_and_job(user_id: str, job_posting_id: str) -> tuple[dict, dict]:
    profile = fetch_profile(user_id)
    if not profile:
        raise LookupError("Profile not found for user_id")

    job = fetch_job(job_posting_id)
    if not job:
        raise LookupError("Job posting not found for job_posting_id")

    return profile, job


def _fetch_brief_record(user_id: str, job_posting_id: str) -> dict | None:
    ensure_interview_prep_schema()

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute(
            """
            SELECT *
            FROM interview_prep_briefs
            WHERE user_id = %s
              AND job_posting_id = %s
            """,
            (user_id, job_posting_id),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        cur.close()
        conn.close()


def _fetch_sources(user_id: str, job_posting_id: str) -> list[dict]:
    ensure_interview_prep_schema()

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute(
            """
            SELECT
                id,
                user_id,
                job_posting_id,
                brief_id,
                source_key,
                source_type,
                title,
                url,
                snippet,
                query,
                rank,
                raw_json,
                created_at
            FROM interview_prep_sources
            WHERE user_id = %s
              AND job_posting_id = %s
            ORDER BY created_at DESC, rank ASC
            """,
            (user_id, job_posting_id),
        )
        return [dict(row) for row in cur.fetchall()]
    finally:
        cur.close()
        conn.close()


def _upsert_interviewing_application(
    user_id: str,
    job_posting_id: str,
    application_id: str | None = None,
) -> tuple[dict, bool]:
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        application_created = False
        if application_id:
            cur.execute(
                """
                UPDATE applications
                SET status = %s
                WHERE id = %s
                  AND user_id = %s
                  AND job_posting_id = %s
                RETURNING id, user_id, job_posting_id, status, draft_path, created_at
                """,
                (APPLICATION_STATUS_INTERVIEWING, application_id, user_id, job_posting_id),
            )
            row = cur.fetchone()
            if not row:
                raise LookupError("application_id does not match user_id and job_posting_id")
        else:
            cur.execute(
                """
                SELECT id
                FROM applications
                WHERE user_id = %s
                  AND job_posting_id = %s
                """,
                (user_id, job_posting_id),
            )
            existing = cur.fetchone()

            if existing:
                cur.execute(
                    """
                    UPDATE applications
                    SET status = %s
                    WHERE id = %s
                    RETURNING id, user_id, job_posting_id, status, draft_path, created_at
                    """,
                    (APPLICATION_STATUS_INTERVIEWING, existing["id"]),
                )
                row = cur.fetchone()
            else:
                application_created = True
                cur.execute(
                    """
                    INSERT INTO applications (user_id, job_posting_id, status, draft_path)
                    VALUES (%s, %s, %s, NULL)
                    RETURNING id, user_id, job_posting_id, status, draft_path, created_at
                    """,
                    (user_id, job_posting_id, APPLICATION_STATUS_INTERVIEWING),
                )
                row = cur.fetchone()

        conn.commit()
        return dict(row), application_created
    finally:
        cur.close()
        conn.close()


def _set_session_cache(
    cur,
    session_id: str,
    turns: list[dict],
    status: str | None = None,
    feedback_json: dict | None = None,
    end_session: bool = False,
) -> dict:
    status = _validate_session_status(status) if status else None

    # interview_session_turns is the source of truth; transcript_text is a cache.
    cur.execute(
        """
        UPDATE interview_practice_sessions
        SET transcript_text = %s,
            feedback_json = COALESCE(%s, feedback_json),
            status = COALESCE(%s, status),
            updated_at = NOW(),
            ended_at = CASE WHEN %s THEN NOW() ELSE ended_at END
        WHERE id = %s
        RETURNING *
        """,
        (
            _build_transcript(turns),
            Json(feedback_json) if feedback_json is not None else None,
            status,
            end_session,
            session_id,
        ),
    )
    return dict(cur.fetchone())


def _build_application_summary(application_created: bool) -> str:
    if application_created:
        return "No application row existed for this user/job pair, so one was created with status interviewing."
    return "Existing application row was updated to status interviewing."


def _store_brief_and_sources(
    user_id: str,
    job_posting_id: str,
    application_id: str | None,
    research_context: dict,
    brief_json: dict,
) -> tuple[dict, list[dict]]:
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    brief_status = _validate_brief_status(BRIEF_STATUS_GENERATED)

    try:
        cur.execute(
            """
            INSERT INTO interview_prep_briefs (
                user_id,
                job_posting_id,
                application_id,
                status,
                research_mode,
                brief_json,
                generated_at,
                updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, NOW(), NOW())
            ON CONFLICT (user_id, job_posting_id)
            DO UPDATE SET
                application_id = COALESCE(EXCLUDED.application_id, interview_prep_briefs.application_id),
                status = EXCLUDED.status,
                research_mode = EXCLUDED.research_mode,
                brief_json = EXCLUDED.brief_json,
                generated_at = NOW(),
                updated_at = NOW()
            RETURNING *
            """,
            (
                user_id,
                job_posting_id,
                application_id,
                brief_status,
                research_context.get("mode", "fallback"),
                Json(brief_json),
            ),
        )
        brief = dict(cur.fetchone())

        cur.execute(
            """
            DELETE FROM interview_prep_sources
            WHERE user_id = %s
              AND job_posting_id = %s
            """,
            (user_id, job_posting_id),
        )

        stored_sources = []
        for source in research_context.get("sources", []):
            cur.execute(
                """
                INSERT INTO interview_prep_sources (
                    user_id,
                    job_posting_id,
                    brief_id,
                    source_key,
                    source_type,
                    title,
                    url,
                    snippet,
                    query,
                    rank,
                    raw_json
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, job_posting_id, source_key)
                DO UPDATE SET
                    brief_id = EXCLUDED.brief_id,
                    source_type = EXCLUDED.source_type,
                    title = EXCLUDED.title,
                    snippet = EXCLUDED.snippet,
                    query = EXCLUDED.query,
                    rank = EXCLUDED.rank,
                    raw_json = EXCLUDED.raw_json
                RETURNING *
                """,
                (
                    user_id,
                    job_posting_id,
                    brief["id"],
                    _source_key(source),
                    source.get("source_type", "web"),
                    source.get("title"),
                    source.get("url"),
                    source.get("snippet"),
                    source.get("query"),
                    source.get("rank"),
                    Json(source.get("raw_json") or {}),
                ),
            )
            stored_sources.append(dict(cur.fetchone()))

        conn.commit()
        return brief, stored_sources
    finally:
        cur.close()
        conn.close()


def create_or_get_interview_brief(
    user_id: str,
    job_posting_id: str,
    application_id: str | None = None,
    refresh: bool = False,
) -> dict:
    ensure_interview_prep_schema()

    if not refresh:
        existing = _fetch_brief_record(user_id, job_posting_id)
        if existing:
            if application_id:
                existing = _attach_application_to_brief(
                    user_id=user_id,
                    job_posting_id=job_posting_id,
                    application_id=application_id,
                )
            return {
                "brief": existing,
                "sources": _fetch_sources(user_id, job_posting_id),
                "generated": False,
            }

    profile, job = _fetch_profile_and_job(user_id, job_posting_id)
    research_context = gather_interview_research(profile=profile, job=job)
    brief_json = generate_interview_brief(
        profile=profile,
        job=job,
        research_context=research_context,
    )
    brief, sources = _store_brief_and_sources(
        user_id=user_id,
        job_posting_id=job_posting_id,
        application_id=application_id,
        research_context=research_context,
        brief_json=brief_json,
    )

    return {
        "brief": brief,
        "sources": sources,
        "generated": True,
        "research_context": research_context,
    }


def _attach_application_to_brief(
    user_id: str,
    job_posting_id: str,
    application_id: str,
) -> dict:
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute(
            """
            UPDATE interview_prep_briefs
            SET application_id = %s,
                updated_at = NOW()
            WHERE user_id = %s
              AND job_posting_id = %s
            RETURNING *
            """,
            (application_id, user_id, job_posting_id),
        )
        row = cur.fetchone()
        conn.commit()
        return dict(row) if row else {}
    finally:
        cur.close()
        conn.close()


def _fetch_brief_by_id(brief_id: str | None) -> dict | None:
    if not brief_id:
        return None

    ensure_interview_prep_schema()
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute(
            """
            SELECT *
            FROM interview_prep_briefs
            WHERE id = %s
            """,
            (brief_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        cur.close()
        conn.close()


def _fetch_session(session_id: str) -> dict | None:
    ensure_interview_prep_schema()

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute(
            """
            SELECT *
            FROM interview_practice_sessions
            WHERE id = %s
            """,
            (session_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        cur.close()
        conn.close()


def _fetch_turns(session_id: str) -> list[dict]:
    ensure_interview_prep_schema()

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute(
            """
            SELECT *
            FROM interview_session_turns
            WHERE session_id = %s
            ORDER BY turn_index ASC
            """,
            (session_id,),
        )
        return [dict(row) for row in cur.fetchall()]
    finally:
        cur.close()
        conn.close()


def _next_turn_index(cur, session_id: str) -> int:
    cur.execute(
        """
        SELECT COALESCE(MAX(turn_index), 0) + 1 AS next_turn_index
        FROM interview_session_turns
        WHERE session_id = %s
        """,
        (session_id,),
    )
    row = cur.fetchone()
    if isinstance(row, dict):
        return int(row["next_turn_index"])
    return int(row[0])


def _opening_question_from_payload(question_payload: dict) -> str:
    fallback = "Thanks for joining. What interests you about this role?"
    questions = question_payload.get("questions") if isinstance(question_payload, dict) else None

    if not isinstance(questions, list) or not questions:
        return fallback

    first_question = questions[0]
    if not isinstance(first_question, dict):
        return fallback

    return first_question.get("question") or fallback


def _insert_turn(
    cur,
    session_id: str,
    user_id: str,
    job_posting_id: str,
    role: str,
    content: str,
    transcript_chunk: str | None = None,
    feedback_json: dict | None = None,
) -> dict:
    turn_index = _next_turn_index(cur, session_id)
    cur.execute(
        """
        INSERT INTO interview_session_turns (
            session_id,
            user_id,
            job_posting_id,
            role,
            content,
            transcript_chunk,
            feedback_json,
            turn_index
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING *
        """,
        (
            session_id,
            user_id,
            job_posting_id,
            role,
            content,
            transcript_chunk,
            Json(feedback_json or {}),
            turn_index,
        ),
    )
    return dict(cur.fetchone())


def _build_transcript(turns: list[dict]) -> str:
    lines = []
    for turn in turns:
        role = turn.get("role", "turn")
        content = turn.get("content", "")
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


@interview_prep_bp.route("/demo/applications", methods=["GET"])
def demo_applications_page():
    ensure_interview_prep_schema()

    user_id = request.args.get("user_id") or None
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute(
            """
            SELECT
                a.id AS application_id,
                a.user_id,
                a.job_posting_id,
                a.status,
                a.draft_path,
                a.created_at,
                u.email,
                j.title,
                j.company,
                j.location,
                b.id AS brief_id
            FROM applications a
            JOIN users u ON u.id = a.user_id
            JOIN job_postings j ON j.id = a.job_posting_id
            LEFT JOIN interview_prep_briefs b
              ON b.user_id = a.user_id
             AND b.job_posting_id = a.job_posting_id
            WHERE (%s IS NULL OR a.user_id = %s)
            ORDER BY a.created_at DESC
            LIMIT 25
            """,
            (user_id, user_id),
        )
        applications = _serialize_rows([dict(row) for row in cur.fetchall()])
        return render_template(
            "demo_applications.html",
            applications=applications,
            user_id=user_id or "",
            error=None,
        )
    except Exception as exc:
        return render_template(
            "demo_applications.html",
            applications=[],
            user_id=user_id or "",
            error=str(exc),
        ), 500
    finally:
        cur.close()
        conn.close()


@interview_prep_bp.route("/interview-prep", methods=["GET"])
def interview_prep_page():
    return render_template(
        "interview_prep.html",
        user_id=request.args.get("user_id", ""),
        job_posting_id=request.args.get("job_posting_id", ""),
    )


@interview_prep_bp.route("/applications/got-interview", methods=["POST"])
def got_interview():
    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id")
    job_posting_id = data.get("job_posting_id")
    application_id = data.get("application_id")

    if not user_id or not job_posting_id:
        return _json_error("user_id and job_posting_id are required")

    try:
        ensure_interview_prep_schema()
        _fetch_profile_and_job(user_id, job_posting_id)
        application, application_created = _upsert_interviewing_application(
            user_id=user_id,
            job_posting_id=job_posting_id,
            application_id=application_id,
        )
        brief_result = create_or_get_interview_brief(
            user_id=user_id,
            job_posting_id=job_posting_id,
            application_id=str(application["id"]),
            refresh=bool(data.get("refresh", False)),
        )

        prep_url = url_for(
            "interview_prep.interview_prep_page",
            user_id=user_id,
            job_posting_id=job_posting_id,
        )

        return _json_success({
            "message": "Application marked as interviewing",
            "application": _serialize_record(application),
            "application_created": application_created,
            "application_behavior": _build_application_summary(application_created),
            "brief": _serialize_record(brief_result["brief"]),
            "sources": _serialize_rows(brief_result.get("sources", [])),
            "generated": brief_result.get("generated", False),
            "prep_url": prep_url,
        })
    except LookupError as exc:
        return _json_error(str(exc), 404)
    except Exception as exc:
        return _json_error(f"Failed to mark interview: {str(exc)}", 500)


@interview_prep_bp.route("/interview-prep/briefs", methods=["POST"])
def create_interview_brief():
    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id")
    job_posting_id = data.get("job_posting_id")

    if not user_id or not job_posting_id:
        return _json_error("user_id and job_posting_id are required")

    try:
        result = create_or_get_interview_brief(
            user_id=user_id,
            job_posting_id=job_posting_id,
            application_id=data.get("application_id"),
            refresh=bool(data.get("refresh", False)),
        )
        return _json_success({
            "brief": _serialize_record(result["brief"]),
            "sources": _serialize_rows(result.get("sources", [])),
            "generated": result.get("generated", False),
        })
    except LookupError as exc:
        return _json_error(str(exc), 404)
    except Exception as exc:
        return _json_error(f"Failed to create interview prep brief: {str(exc)}", 500)


@interview_prep_bp.route("/interview-prep/briefs", methods=["GET"])
def get_interview_brief():
    user_id = request.args.get("user_id")
    job_posting_id = request.args.get("job_posting_id")

    if not user_id or not job_posting_id:
        return _json_error("user_id and job_posting_id are required")

    try:
        brief = _fetch_brief_record(user_id, job_posting_id)
        if not brief:
            return _json_error("Interview prep brief not found", 404)

        return _json_success({
            "brief": _serialize_record(brief),
            "sources": _serialize_rows(_fetch_sources(user_id, job_posting_id)),
        })
    except Exception as exc:
        return _json_error(f"Failed to fetch interview prep brief: {str(exc)}", 500)


@interview_prep_bp.route("/interview-prep/questions", methods=["POST"])
def create_mock_questions():
    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id")
    job_posting_id = data.get("job_posting_id")
    count = _bounded_int(data.get("count"), default=5, minimum=1, maximum=10)

    if not user_id or not job_posting_id:
        return _json_error("user_id and job_posting_id are required")

    try:
        profile, job = _fetch_profile_and_job(user_id, job_posting_id)
        brief_result = create_or_get_interview_brief(user_id, job_posting_id)
        questions = generate_mock_questions(
            profile=profile,
            job=job,
            brief=_brief_json(brief_result["brief"]),
            count=count,
            focus=data.get("focus"),
        )
        return _json_success(questions)
    except LookupError as exc:
        return _json_error(str(exc), 404)
    except Exception as exc:
        return _json_error(f"Failed to generate mock questions: {str(exc)}", 500)


@interview_prep_bp.route("/interview-prep/sessions", methods=["POST"])
def create_practice_session():
    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id")
    job_posting_id = data.get("job_posting_id")
    mode = data.get("mode", "chat")

    if not user_id or not job_posting_id:
        return _json_error("user_id and job_posting_id are required")

    try:
        profile, job = _fetch_profile_and_job(user_id, job_posting_id)
        brief_result = create_or_get_interview_brief(user_id, job_posting_id)
        brief = brief_result["brief"]
        brief_json = _brief_json(brief)
        question_payload = generate_mock_questions(
            profile=profile,
            job=job,
            brief=brief_json,
            count=1,
            focus="opening interviewer question",
        )
        first_question = _opening_question_from_payload(question_payload)

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        session_status = _validate_session_status(SESSION_STATUS_ACTIVE)

        try:
            cur.execute(
                """
                INSERT INTO interview_practice_sessions (
                    user_id,
                    job_posting_id,
                    brief_id,
                    mode,
                    status
                )
                VALUES (%s, %s, %s, %s, %s)
                RETURNING *
                """,
                (user_id, job_posting_id, brief["id"], mode, session_status),
            )
            session = dict(cur.fetchone())
            turn = _insert_turn(
                cur=cur,
                session_id=session["id"],
                user_id=user_id,
                job_posting_id=job_posting_id,
                role="interviewer",
                content=first_question,
                feedback_json=question_payload,
            )
            session = _set_session_cache(
                cur=cur,
                session_id=session["id"],
                turns=[turn],
                status=SESSION_STATUS_ACTIVE,
            )
            conn.commit()

            return _json_success({
                "session": _serialize_record(session),
                "turns": _serialize_rows([turn]),
            }, 201)
        finally:
            cur.close()
            conn.close()
    except (KeyError, IndexError, TypeError) as exc:
        return _json_error(f"Failed to create practice session due to malformed session data: {str(exc)}", 500)
    except LookupError as exc:
        return _json_error(str(exc), 404)
    except Exception as exc:
        return _json_error(f"Failed to create practice session: {str(exc)}", 500)


@interview_prep_bp.route("/interview-prep/sessions", methods=["GET"])
def list_practice_sessions():
    user_id = request.args.get("user_id")
    job_posting_id = request.args.get("job_posting_id")

    if not user_id or not job_posting_id:
        return _json_error("user_id and job_posting_id are required")

    ensure_interview_prep_schema()
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute(
            """
            SELECT
                s.*,
                COALESCE(turn_counts.turn_count, 0) AS turn_count
            FROM interview_practice_sessions s
            LEFT JOIN (
                SELECT session_id, COUNT(*) AS turn_count
                FROM interview_session_turns
                GROUP BY session_id
            ) turn_counts ON turn_counts.session_id = s.id
            WHERE s.user_id = %s
              AND s.job_posting_id = %s
            ORDER BY s.created_at DESC
            LIMIT 25
            """,
            (user_id, job_posting_id),
        )
        return _json_success({
            "sessions": _serialize_rows([dict(row) for row in cur.fetchall()]),
        })
    finally:
        cur.close()
        conn.close()


@interview_prep_bp.route("/interview-prep/sessions/<session_id>", methods=["GET"])
def get_practice_session(session_id):
    session = _fetch_session(session_id)
    if not session:
        return _json_error("Practice session not found", 404)

    turns = _fetch_turns(session_id)
    return _json_success({
        "session": _serialize_record(session),
        "turns": _serialize_rows(turns),
    })


@interview_prep_bp.route("/interview-prep/sessions/<session_id>/turns", methods=["POST"])
def add_practice_turn(session_id):
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or data.get("transcript_chunk") or "").strip()

    if not message:
        return _json_error("message or transcript_chunk is required")

    session = _fetch_session(session_id)
    if not session:
        return _json_error("Practice session not found", 404)
    if session.get("status") == SESSION_STATUS_COMPLETED:
        return _json_error("Practice session is completed; start a new session to continue practicing", 409)

    try:
        user_id = str(session["user_id"])
        job_posting_id = str(session["job_posting_id"])
        profile, job = _fetch_profile_and_job(user_id, job_posting_id)
        brief_id = session.get("brief_id")
        brief = _fetch_brief_by_id(str(brief_id) if brief_id else None) or _fetch_brief_record(user_id, job_posting_id)
        existing_turns = _fetch_turns(session_id)
        reply = generate_interviewer_reply(
            profile=profile,
            job=job,
            brief=_brief_json(brief),
            turns=existing_turns,
            latest_user_message=message,
        )

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        try:
            user_turn = _insert_turn(
                cur=cur,
                session_id=session_id,
                user_id=user_id,
                job_posting_id=job_posting_id,
                role="user",
                content=message,
                transcript_chunk=data.get("transcript_chunk"),
            )
            interviewer_turn = _insert_turn(
                cur=cur,
                session_id=session_id,
                user_id=user_id,
                job_posting_id=job_posting_id,
                role="interviewer",
                content=reply.get("interviewer_message", ""),
                feedback_json=reply,
            )
            turns = existing_turns + [user_turn, interviewer_turn]
            updated_session = _set_session_cache(
                cur=cur,
                session_id=session_id,
                turns=turns,
                status=SESSION_STATUS_ACTIVE,
            )
            conn.commit()

            return _json_success({
                "session": _serialize_record(updated_session),
                "turns": _serialize_rows([user_turn, interviewer_turn]),
                "reply": reply,
            })
        finally:
            cur.close()
            conn.close()
    except LookupError as exc:
        return _json_error(str(exc), 404)
    except Exception as exc:
        return _json_error(f"Failed to add practice turn: {str(exc)}", 500)


@interview_prep_bp.route("/interview-prep/sessions/<session_id>/feedback", methods=["POST"])
def create_session_feedback(session_id):
    data = request.get_json(silent=True) or {}
    try:
        feedback_type = _feedback_type_from_payload(data)
    except ValueError as exc:
        return _json_error(str(exc), 400)

    session = _fetch_session(session_id)

    if not session:
        return _json_error("Practice session not found", 404)
    if session.get("status") == SESSION_STATUS_COMPLETED:
        return _json_error("Practice session is already completed", 409)

    try:
        user_id = str(session["user_id"])
        job_posting_id = str(session["job_posting_id"])
        profile, job = _fetch_profile_and_job(user_id, job_posting_id)
        brief_id = session.get("brief_id")
        brief = _fetch_brief_by_id(str(brief_id) if brief_id else None) or _fetch_brief_record(user_id, job_posting_id)
        turns = _fetch_turns(session_id)
        feedback = generate_session_feedback(
            profile=profile,
            job=job,
            brief=_brief_json(brief),
            turns=turns,
        )

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        is_final_feedback = feedback_type == FEEDBACK_TYPE_FINAL
        next_status = SESSION_STATUS_COMPLETED if is_final_feedback else SESSION_STATUS_ACTIVE

        try:
            feedback_turn = _insert_turn(
                cur=cur,
                session_id=session_id,
                user_id=user_id,
                job_posting_id=job_posting_id,
                role="feedback",
                content=feedback.get("overall", ""),
                feedback_json=feedback,
            )
            updated_session = _set_session_cache(
                cur=cur,
                session_id=session_id,
                turns=turns + [feedback_turn],
                status=next_status,
                feedback_json=feedback,
                end_session=is_final_feedback,
            )
            conn.commit()

            return _json_success({
                "session": _serialize_record(updated_session),
                "turn": _serialize_record(feedback_turn),
                "feedback": feedback,
                "feedback_type": feedback_type,
                "session_ended": is_final_feedback,
            })
        finally:
            cur.close()
            conn.close()
    except LookupError as exc:
        return _json_error(str(exc), 404)
    except Exception as exc:
        return _json_error(f"Failed to generate feedback: {str(exc)}", 500)
