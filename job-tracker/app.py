# app.py
from flask import Flask, request, jsonify
import config
from services import health_bp, db_bp, submit_bp, jobs_bp, profiles_bp
from services.agent import run_agent_for_user

app = Flask(__name__)

# register blueprints
app.register_blueprint(health_bp)
app.register_blueprint(db_bp)
app.register_blueprint(submit_bp)
app.register_blueprint(jobs_bp)
app.register_blueprint(profiles_bp)

@app.route('/agent', methods=['POST'])
def run_agent():
    data = request.get_json()
    user_id = data.get("user_id")
    if not user_id:
        return jsonify({"status": "error", "message": "user_id is required"}), 400
    
    result = run_agent_for_user(user_id)
    return jsonify({
        "status": "success",
        "user_id": user_id,
        **result
    })

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)





