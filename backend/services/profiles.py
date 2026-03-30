from flask import Blueprint, jsonify, request
import datetime
import json
import psycopg2
from psycopg2.extras import RealDictCursor

from config import DATABASE_URL


profiles_bp = Blueprint("profiles", __name__)


@profiles_bp.route("/profiles", methods=["POST"])
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

        cur.execute(
            """
            INSERT INTO users (id, email, first_name, last_name, created_at)
            VALUES (gen_random_uuid(), %s, %s, %s, now())
            ON CONFLICT (email) DO UPDATE
              SET first_name = COALESCE(EXCLUDED.first_name, users.first_name),
                  last_name = COALESCE(EXCLUDED.last_name, users.last_name)
            RETURNING id;
            """,
            (email, first_name, last_name),
        )
        user_id = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO profiles (user_id, resume_text, preferences_json)
            VALUES (%s, %s, %s::jsonb)
            ON CONFLICT (user_id) DO UPDATE
              SET resume_text = EXCLUDED.resume_text,
                  preferences_json = EXCLUDED.preferences_json;
            """,
            (user_id, resume_text, json.dumps(preferences)),
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


@profiles_bp.route("/profiles/<user_id>", methods=["GET"])
def get_profile(user_id):
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT user_id, resume_text, preferences_json
            FROM profiles
            WHERE user_id = %s
            """,
            (user_id,),
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