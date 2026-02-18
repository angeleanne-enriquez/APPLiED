from flask import Flask, jsonify, request
import datetime
import os
import psycopg2
import requests
import json
from dotenv import load_dotenv
from psycopg2.extras import RealDictCursor


app = Flask(__name__)

from pathlib import Path
load_dotenv(dotenv_path=Path(__file__).with_name(".env"))

DATABASE_URL = os.getenv("DATABASE_URL")


@app.route('/debug/dburl', methods=['GET'])
def debug_dburl():
    return jsonify({
        "DATABASE_URL": DATABASE_URL,
        "timestamp": datetime.datetime.now().isoformat()
    }), 200



@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        'status': 'success',
        'message': 'Server is running',
        'timestamp': datetime.datetime.now().isoformat()
    }), 200


@app.route('/db', methods=['GET'])
@app.route('/health/db', methods=['GET'])
def db_health():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT 1;")
        cur.close()
        conn.close()
        return jsonify({
            'status': 'success',
            'message': 'Database connected',
            'timestamp': datetime.datetime.now().isoformat()
        }), 200
    except Exception as e:
        return jsonify({
            'status': 'failure',
            'message': f'Database connection failed: {str(e)}',
            'timestamp': datetime.datetime.now().isoformat()
        }), 500


@app.route('/submit', methods=['POST'])
def submit_user_info():
    data = request.json
    first_name = data.get("first_name")
    last_name = data.get("last_name")
    email = data.get("email")
    resume_text = data.get("resume_text")
    preferences = data.get("preferences")  # e.g., job types or locations as JSON/dict

    if not all([first_name, last_name, email]):
        return jsonify({
            "status": "failure",
            "message": "First name, last name, and email are required",
            'timestamp': datetime.datetime.now().isoformat()
        }), 400

    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()

        # 1️⃣ Insert into users
        cur.execute(
            """
            INSERT INTO users (id, email, first_name, last_name, created_at)
            VALUES (gen_random_uuid(), %s, %s, %s, NOW())
            RETURNING id
            """,
            (email, first_name, last_name)
        )
        user_id = cur.fetchone()[0]

        # 2️⃣ Insert into profiles
        cur.execute(
            """
            INSERT INTO profiles (user_id, resume_text, preferences_json)
            VALUES (%s, %s, %s)
            """,
            (user_id, resume_text, json.dumps(preferences) if preferences else '{}')
        )

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({
            "status": "success",
            "message": "User and profile created successfully",
            "user_id": str(user_id),
            'timestamp': datetime.datetime.now().isoformat()
        }), 201

    except Exception as e:
        return jsonify({
            "status": "failure",
            "message": f"Database insert failed: {str(e)}",
            'timestamp': datetime.datetime.now().isoformat()
        }), 500



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



@app.route('/fetch-jobs', methods=['GET'])
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


@app.route('/profiles', methods=['POST'])
def upsert_profile():
    data = request.get_json(force=True) or {}

    email = data.get("email")
    first_name = data.get("first_name")
    last_name = data.get("last_name")
    resume_text = data.get("resume_text")
    preferences = data.get("preferences") or {}

    if not email:
        return jsonify({
            "status": "failure",
            "message": "email is required",
            "timestamp": datetime.datetime.now().isoformat()
        }), 400

    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()

        # 1) Upsert user by email (email is UNIQUE)
        cur.execute(
            """
            insert into users (id, email, first_name, last_name, created_at)
            values (gen_random_uuid(), %s, %s, %s, now())
            on conflict (email) do update
              set first_name = coalesce(excluded.first_name, users.first_name),
                  last_name  = coalesce(excluded.last_name, users.last_name)
            returning id;
            """,
            (email, first_name, last_name)
        )
        user_id = cur.fetchone()[0]

        # 2) Upsert profile (profiles PK is user_id)
        cur.execute(
            """
            insert into profiles (user_id, resume_text, preferences_json)
            values (%s, %s, %s::jsonb)
            on conflict (user_id) do update
              set resume_text = excluded.resume_text,
                  preferences_json = excluded.preferences_json;
            """,
            (user_id, resume_text, json.dumps(preferences))
        )

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({
            "status": "success",
            "message": "Profile saved",
            "user_id": str(user_id),
            "timestamp": datetime.datetime.now().isoformat()
        }), 200

    except Exception as e:
        return jsonify({
            "status": "failure",
            "message": f"Profile upsert failed: {str(e)}",
            "timestamp": datetime.datetime.now().isoformat()
        }), 500


@app.route('/profiles/<user_id>', methods=['GET'])
def get_profile(user_id):
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            select user_id, resume_text, preferences_json
            from profiles
            where user_id = %s
            """,
            (user_id,)
        )
        row = cur.fetchone()

        cur.close()
        conn.close()

        if not row:
            return jsonify({
                "status": "failure",
                "message": "Profile not found",
                "timestamp": datetime.datetime.now().isoformat()
            }), 404

        return jsonify({
            "status": "success",
            "profile": row,
            "timestamp": datetime.datetime.now().isoformat()
        }), 200

    except Exception as e:
        return jsonify({
            "status": "failure",
            "message": f"Profile fetch failed: {str(e)}",
            "timestamp": datetime.datetime.now().isoformat()
        }), 500


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)
