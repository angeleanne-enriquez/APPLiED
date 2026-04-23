import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Blueprint, jsonify, request, session
from werkzeug.security import generate_password_hash, check_password_hash

from config import DATABASE_URL

auth_bp = Blueprint("auth", __name__)


def _get_db():
    return psycopg2.connect(DATABASE_URL)


def ensure_password_column():
    """Run once at startup to add password_hash column if it doesn't exist."""
    try:
        conn = _get_db()
        cur = conn.cursor()
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash TEXT;")
        conn.commit()
        cur.close()
        conn.close()
    except Exception:
        pass


def _set_session(row: dict):
    session["user_id"]    = str(row["id"])
    session["email"]      = row["email"] or ""
    session["first_name"] = row["first_name"] or ""
    session["last_name"]  = row["last_name"] or ""


# ─── routes ───────────────────────────────────────────────────────────────────

@auth_bp.route("/auth/signup", methods=["POST"])
def signup():
    data       = request.get_json() or {}
    email      = (data.get("email") or "").strip().lower()
    password   = data.get("password") or ""
    first_name = (data.get("first_name") or "").strip()
    last_name  = (data.get("last_name") or "").strip()

    if not email or not password:
        return jsonify({"status": "error", "message": "email and password are required"}), 400
    if len(password) < 6:
        return jsonify({"status": "error", "message": "password must be at least 6 characters"}), 400

    pw_hash = generate_password_hash(password)

    try:
        conn = _get_db()
        cur  = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("SELECT id FROM users WHERE email = %s", (email,))
        if cur.fetchone():
            cur.close(); conn.close()
            return jsonify({"status": "error", "message": "an account with this email already exists"}), 409

        cur.execute("""
            INSERT INTO users (id, email, first_name, last_name, password_hash, created_at)
            VALUES (gen_random_uuid(), %s, %s, %s, %s, now())
            RETURNING id, email, first_name, last_name
        """, (email, first_name, last_name, pw_hash))

        row = dict(cur.fetchone())
        conn.commit()
        cur.close(); conn.close()

        _set_session(row)

        return jsonify({
            "status":     "success",
            "user_id":    str(row["id"]),
            "email":      row["email"],
            "first_name": row["first_name"],
            "last_name":  row["last_name"],
        }), 201

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@auth_bp.route("/auth/login", methods=["POST"])
def login():
    data     = request.get_json() or {}
    email    = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not email or not password:
        return jsonify({"status": "error", "message": "email and password are required"}), 400

    try:
        conn = _get_db()
        cur  = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT id, email, first_name, last_name, password_hash
            FROM users WHERE email = %s
        """, (email,))
        row = cur.fetchone()
        cur.close(); conn.close()

        if not row:
            return jsonify({"status": "error", "message": "invalid email or password"}), 401

        pw_hash = row.get("password_hash")
        if not pw_hash or not check_password_hash(pw_hash, password):
            return jsonify({"status": "error", "message": "invalid email or password"}), 401

        row = dict(row)
        _set_session(row)

        return jsonify({
            "status":     "success",
            "user_id":    str(row["id"]),
            "email":      row["email"],
            "first_name": row["first_name"],
            "last_name":  row["last_name"],
        }), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@auth_bp.route("/auth/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"status": "success"}), 200


@auth_bp.route("/auth/me", methods=["GET"])
def me():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"status": "unauthenticated"}), 401
    return jsonify({
        "status":     "success",
        "user_id":    user_id,
        "email":      session.get("email", ""),
        "first_name": session.get("first_name", ""),
        "last_name":  session.get("last_name", ""),
    }), 200
