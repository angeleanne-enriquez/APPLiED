from flask import Blueprint, jsonify, request
import datetime
import json
import psycopg2

from config import DATABASE_URL


submit_bp = Blueprint('submit', __name__)


@submit_bp.route('/submit', methods=['POST'])
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
