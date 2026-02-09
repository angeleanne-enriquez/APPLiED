from flask import Flask, jsonify, request
import datetime
import os
import psycopg2
import requests
import json
from dotenv import load_dotenv

app = Flask(__name__)

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")


@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        'status': 'success',
        'message': 'Server is running',
        'timestamp': datetime.datetime.now().isoformat()
    }), 200


@app.route('/db', methods=['GET'])
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
    name = data.get("name")
    email = data.get("email")
    resume_text = data.get("resume_text")
    jobs_wanted = data.get("jobs_wanted")

    if not all([name, email]):
        return jsonify({
            "status": "failure",
            "message": "Name and email are required",
            'timestamp': datetime.datetime.now().isoformat()
        }), 400

    # --- WRITE FILES ---
    # Save resume
    if resume_text:
        with open(f"{name.replace(' ', '_')}_resume.txt", "w") as f:
            f.write(resume_text)

    # Save jobs wanted
    if jobs_wanted:
        with open(f"{name.replace(' ', '_')}_jobs.json", "w") as f:
            import json
            # if jobs_wanted is a string, convert to list
            if isinstance(jobs_wanted, str):
                jobs_list = [job.strip() for job in jobs_wanted.split(",")]
            else:
                jobs_list = jobs_wanted
            json.dump(jobs_list, f, indent=4)

    # --- OPTIONAL: Save to DB ---
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO user_submissions (name, email, resume_text, jobs_wanted, created_at)
            VALUES (%s, %s, %s, %s, NOW())
            """,
            (name, email, resume_text, jobs_wanted)
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        return jsonify({
            "status": "failure",
            "message": f"Database insert failed: {str(e)}",
            'timestamp': datetime.datetime.now().isoformat()
        }), 500

    return jsonify({
        "status": "success",
        "message": "User info submitted and files saved",
        'timestamp': datetime.datetime.now().isoformat()
    }), 201


def fetch_jobs(limit=None):
    """Fetch remote jobs from Remotive API and store in DB + JSON"""
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
                INSERT INTO jobs (id, title, company, category, url, created_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                ON CONFLICT (id) DO NOTHING
                """,
                (job["id"], job["title"], job["company_name"], job["category"], job["url"])
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



if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)
