import json
import os
import sys
from pathlib import Path

import psycopg2
import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from config import DATABASE_URL  # noqa: E402
from services.schema import ensure_interview_prep_schema  # noqa: E402


BASE_URL = os.getenv("APPLIED_BASE_URL", "http://127.0.0.1:5001")


def post_json(path: str, payload: dict) -> dict:
    response = requests.post(f"{BASE_URL}{path}", json=payload, timeout=90)
    response.raise_for_status()
    return response.json()


def get_json(path: str) -> dict:
    response = requests.get(f"{BASE_URL}{path}", timeout=30)
    response.raise_for_status()
    return response.json()


def seed_demo_job(user_id: str) -> tuple[str, str]:
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is required for demo seed data")

    ensure_interview_prep_schema()

    job = {
        "id": "interview-prep-demo-001",
        "title": "Backend Software Engineer",
        "company_name": "Northstar Health",
        "candidate_required_location": "Remote",
        "category": "Software Development",
        "url": "https://example.com/jobs/backend-software-engineer",
        "description": (
            "Build Flask and Python services, design PostgreSQL data models, "
            "integrate AI-assisted workflows, and collaborate with product teams."
        ),
    }

    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    try:
        cur.execute(
            """
            INSERT INTO job_postings (
                id,
                external_id,
                source,
                title,
                company,
                location,
                category,
                url,
                description,
                raw_json,
                ingested_at
            )
            VALUES (
                gen_random_uuid(),
                %s, %s, %s, %s, %s, %s, %s, %s,
                %s::jsonb,
                NOW()
            )
            ON CONFLICT (external_id, source)
            DO UPDATE SET
                title = EXCLUDED.title,
                company = EXCLUDED.company,
                location = EXCLUDED.location,
                category = EXCLUDED.category,
                url = EXCLUDED.url,
                description = EXCLUDED.description,
                raw_json = EXCLUDED.raw_json
            RETURNING id
            """,
            (
                job["id"],
                "Demo",
                job["title"],
                job["company_name"],
                job["candidate_required_location"],
                job["category"],
                job["url"],
                job["description"],
                json.dumps(job),
            ),
        )
        job_posting_id = str(cur.fetchone()[0])

        cur.execute(
            """
            INSERT INTO job_matches (user_id, job_posting_id, score, rationale)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (user_id, job_posting_id)
            DO UPDATE SET
                score = EXCLUDED.score,
                rationale = EXCLUDED.rationale
            """,
            (
                user_id,
                job_posting_id,
                88.0,
                "Demo match: Python, Flask, PostgreSQL, APIs, and AI workflow experience.",
            ),
        )

        cur.execute(
            """
            INSERT INTO applications (user_id, job_posting_id, status, draft_path)
            VALUES (%s, %s, 'ready_for_review', NULL)
            ON CONFLICT (user_id, job_posting_id)
            DO UPDATE SET status = EXCLUDED.status
            RETURNING id
            """,
            (user_id, job_posting_id),
        )
        application_id = str(cur.fetchone()[0])

        conn.commit()
        return job_posting_id, application_id
    finally:
        cur.close()
        conn.close()


def main() -> None:
    print(f"Checking server at {BASE_URL}")
    print(get_json("/health"))

    profile = post_json("/profiles", {
        "email": "interview.demo@example.com",
        "first_name": "Avery",
        "last_name": "Stone",
        "resume_text": (
            "Backend engineer with Python, Flask, REST APIs, PostgreSQL, SQL, "
            "job automation, AI-assisted workflows, and cross-functional product collaboration."
        ),
        "preferences": {
            "location": "Remote",
            "job_type": "Backend Software Engineer",
            "remote": True,
            "salary_min": 100000,
        },
    })
    user_id = profile["user_id"]
    print(f"Seeded profile: {user_id}")

    job_posting_id, application_id = seed_demo_job(user_id)
    print(f"Seeded job: {job_posting_id}")
    print(f"Seeded application: {application_id}")

    got_interview = post_json("/applications/got-interview", {
        "user_id": user_id,
        "job_posting_id": job_posting_id,
        "application_id": application_id,
    })
    print(f"Got Interview status: {got_interview['application']['status']}")
    print(f"Application behavior: {got_interview['application_behavior']}")
    print(f"Prep URL: {BASE_URL}{got_interview['prep_url']}")

    session = post_json("/interview-prep/sessions", {
        "user_id": user_id,
        "job_posting_id": job_posting_id,
        "mode": "browser_voice_text",
    })
    session_id = session["session"]["id"]
    print(f"Started session: {session_id}")

    turn = post_json(f"/interview-prep/sessions/{session_id}/turns", {
        "message": (
            "I am interested in the role because it combines Flask service design, "
            "PostgreSQL data modeling, and AI-assisted workflow automation. In my last project, "
            "I built API endpoints, debugged data issues, and worked with product feedback."
        )
    })
    print(f"Interviewer reply: {turn['reply']['interviewer_message']}")

    feedback = post_json(f"/interview-prep/sessions/{session_id}/feedback", {
        "feedback_type": "final",
        "end_session": True,
    })
    print(f"Final feedback: {feedback['feedback']['overall']}")
    print(f"Session ended: {feedback['session_ended']}")


if __name__ == "__main__":
    main()
