from flask import Blueprint, jsonify, request
import datetime
import json
import psycopg2
from psycopg2.extras import RealDictCursor

from config import DATABASE_URL


profiles_bp = Blueprint('profiles', __name__)


@profiles_bp.route('/profiles', methods=['POST'])
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


@profiles_bp.route('/profiles/<user_id>', methods=['GET'])
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
