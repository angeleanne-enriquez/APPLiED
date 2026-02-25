from flask import Blueprint, jsonify
import datetime

health_bp = Blueprint('health', __name__)


@health_bp.route('/health', methods=['GET'])
def health():
    return jsonify({
        'status': 'success',
        'message': 'Server is running',
        'timestamp': datetime.datetime.now().isoformat()
    }), 200


@health_bp.route('/debug/dburl', methods=['GET'])
def debug_dburl():
    # this endpoint really belongs to config/diagnostics
    from config import DATABASE_URL
    return jsonify({
        "DATABASE_URL": DATABASE_URL,
        "timestamp": datetime.datetime.now().isoformat()
    }), 200
