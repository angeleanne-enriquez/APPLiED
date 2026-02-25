from flask import Blueprint, jsonify, request
import datetime
import requests
import json
import psycopg2

from config import DATABASE_URL


jobs_bp = Blueprint('jobs', __name__)


def fetch_jobs(limit=None):
    url = "https://remotive.com/api/remote-jobs"
    params = {}
    if limit:
        params["limit"] = limit

    response = requests.get(url, params=params)
    if response.status_code != 200:
        raise Exception(f"Remotive API returned {response.status_code}")

    data = response.json()
    jobs = data.get("jobs", [])

    with open("jobs.json", "w") as f:
        json.dump(jobs, f, indent=4)

    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        for job in jobs:
            cur.execute(
                """
                INSERT INTO job_postings (
                    id, external_id, source, title, company, location, url, description, raw_json, ingested_at
                ) VALUES (
                    gen_random_uuid(), %s, %s, %s, %s, %s, %s, %s, %s, NOW()
                )
                ON CONFLICT (external_id, source) DO NOTHING
                """,
                (
                    job.get("id"),
                    job.get("source_name", "Remotive"),  # example source
                    job.get("title"),
                    job.get("company_name"),
                    job.get("category"),
                    job.get("url"),
                    job.get("description"),
                    json.dumps(job)
                )
            )
        conn.commit()
        cur.close()
        conn.close()
        print(f"{len(jobs)} jobs saved to database and JSON")
    except Exception as e:
        print(f"Error saving to database: {e}")

    return len(jobs)


@jobs_bp.route('/fetch-jobs', methods=['GET'])
def fetch_jobs_endpoint():
    try:
        limit = request.args.get("limit", type=int)
        count = fetch_jobs(limit=limit)
        return jsonify({
            "status": "success",
            "message": f"Fetched and stored {count} jobs",
            'timestamp': datetime.datetime.now().isoformat()
        }), 200
    except Exception as e:
        return jsonify({
            "status": "failure",
            "message": str(e),
            'timestamp': datetime.datetime.now().isoformat()
        }), 500
