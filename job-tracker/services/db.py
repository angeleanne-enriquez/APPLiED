from flask import Blueprint, jsonify
import datetime
import psycopg2

from config import DATABASE_URL


db_bp = Blueprint('db', __name__)


@db_bp.route('/db', methods=['GET'])
@db_bp.route('/health/db', methods=['GET'])
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
