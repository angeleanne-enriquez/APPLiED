from flask import Blueprint, jsonify, request
import datetime
import json
import requests
import psycopg2
from psycopg2.extras import RealDictCursor
from serpapi import GoogleSearch

from config import DATABASE_URL

jobs_bp = Blueprint("jobs", __name__)



def fetch_remotive_jobs(limit=None):
    """
    Fetch jobs from Remotive API.
    """
    url = "https://remotive.com/api/remote-jobs"
    params = {}
    if limit:
        params["limit"] = limit

    r = requests.get(url, params=params, timeout=30)
    if r.status_code != 200:
        raise Exception(f"Remotive API returned {r.status_code}: {r.text[:200]}")

    return r.json().get("jobs", [])

def fetch_google_jobs(job_type=None, location=None):
    """
    Fetch jobs from Google Jobs using SerpApi.
    """
    params = {
        "engine": "google_jobs",
        "api_key": "15f9f0bdf0bf63523f67b648f66d47fca921686163fd61ce792cd5d0e8eff24e"
    }

    if job_type and location:
        params["q"] = f"{job_type} jobs"
        params["location"] = location
    elif job_type:
        params["q"] = f"{job_type} jobs"
    elif location:
        params["location"] = location

    search = GoogleSearch(params)
    results = search.get_dict()

    return results.get("jobs_results", [])


def ingest_jobs(jobs, source_name="Remotive", write_json=True):
    """
    Saves jobs to jobs.json (optional) and inserts into job_postings.
    Returns (inserted_count, received_count).
    Deduped by UNIQUE(external_id, source) or ON CONFLICT (external_id, source).
    """
    if write_json:
        with open("jobs.json", "w", encoding="utf-8") as f:
            json.dump(jobs, f, indent=4)

    inserted = 0
    received = len(jobs)

    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    try:
        for job in jobs:
            external_id = str(job.get("id"))
            title = job.get("title")
            company = job.get("company_name")
            category = job.get("category")

            
            location = (
                job.get("candidate_required_location")
                or job.get("location")
                or job.get("category")
            )

            url = job.get("url")
            description = job.get("description")

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
                ) VALUES (
                    gen_random_uuid(),
                    %s, %s, %s, %s, %s, %s, %s, %s,
                    %s::jsonb,
                    NOW()
                )
                ON CONFLICT (external_id, source) DO NOTHING
                """,
                (
                    external_id,
                    source_name,
                    title,
                    company,
                    location,
                    category,
                    url,
                    description,
                    json.dumps(job),
                ),
            )

            
            if cur.rowcount == 1:
                inserted += 1

        conn.commit()
        return inserted, received

    finally:
        cur.close()
        conn.close()

@jobs_bp.route("/jobs/google/<user_id>", methods=["GET"]) #route should be by the user_id, so we can access their job_type and/or location
def fetch_google_jobs_for_user(user_id):
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # Get user preferences
        cur.execute(
            """
            select job_type, location
            from profiles
            where user_id = %s
            """,
            (user_id,)
        )

        profile = cur.fetchone()

        if not profile:
            return jsonify({
                "status": "failure",
                "message": "Profile not found",
                "timestamp": datetime.datetime.now().isoformat()
            }), 404

        job_type = profile.get("job_type")
        location = profile.get("location")

        jobs = fetch_google_jobs(job_type=job_type, location=location)

        return jsonify({
            "status": "success",
            "source": "google_jobs",
            "job_type": job_type,
            "location": location,
            "count": len(jobs),
            "jobs": jobs,
            "timestamp": datetime.datetime.now().isoformat()
        }), 200

    except Exception as e:
        return jsonify({
            "status": "failure",
            "message": str(e),
            "timestamp": datetime.datetime.now().isoformat()
        }), 500

    finally:
        cur.close()
        conn.close()

@jobs_bp.route("/jobs/ingest", methods=["POST"])
def jobs_ingest():
    """
    POST /jobs/ingest
    Body JSON:
      {
        "limit": 15,              // optional
        "write_json": true,       // optional (default true)
        "source": "Remotive"      // optional (default Remotive)
      }
    """
    data = request.get_json(silent=True) or {}

    limit = data.get("limit")
    write_json = bool(data.get("write_json", True))
    source_name = data.get("source", "Remotive")

    try:
        jobs = fetch_remotive_jobs(limit=limit)
        inserted, received = ingest_jobs(
            jobs,
            source_name=source_name,
            write_json=write_json
        )

        return jsonify({
            "status": "success",
            "source": source_name.lower(),
            "received": received,
            "inserted": inserted,
            "timestamp": datetime.datetime.now().isoformat()
        }), 200

    except Exception as e:
        return jsonify({
            "status": "failure",
            "message": str(e),
            "timestamp": datetime.datetime.now().isoformat()
        }), 500


@jobs_bp.route("/jobs", methods=["GET"])
def list_jobs():
    """
    GET /jobs?limit=25
    Quick sanity endpoint to verify jobs in DB.
    """
    limit = request.args.get("limit", default=25, type=int)
    limit = max(1, min(limit, 200))

    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute(
            """
            SELECT
                id,
                external_id,
                source,
                title,
                company,
                location,
                category,
                url,
                ingested_at
            FROM job_postings
            ORDER BY ingested_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()

        return jsonify({
            "status": "success",
            "count": len(rows),
            "jobs": rows,
            "timestamp": datetime.datetime.now().isoformat()
        }), 200

    finally:
        cur.close()
        conn.close()


# keep old route name so nobody is confused if they call it
@jobs_bp.route("/fetch-jobs", methods=["GET"])
def fetch_jobs_removed():
    return jsonify({
        "status": "failure",
        "message": "Endpoint removed. Use POST /jobs/ingest instead.",
        "timestamp": datetime.datetime.now().isoformat()
    }), 410