from flask import Flask, request, jsonify

# load configuration (env vars etc)
import config

from services import health_bp, db_bp, submit_bp, jobs_bp, profiles_bp

app = Flask(__name__)

app.register_blueprint(health_bp)
app.register_blueprint(db_bp)
app.register_blueprint(submit_bp)
app.register_blueprint(jobs_bp)
app.register_blueprint(profiles_bp)

# agent endpoint
from graph.graph_builder import build_graph

@app.route('/agent', methods=['POST'])
def run_agent():
    data = request.get_json()
    user_id = data.get('user_id')

    if not user_id:
        return jsonify({"status": "error", "message": "user_id is required"}), 400

    graph = build_graph()
    result = graph.invoke({"user_id": user_id})

    return jsonify({
        "status": "success",
        "user_id": user_id,
        "user_profile": result.get("user_profile"),
        "jobs_list": result.get("jobs_list"),
        "matched_jobs": result.get("matched_jobs"),
        "response": result.get("final_response")
    })

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)
