from pathlib import Path
from flask import Flask, request, jsonify, render_template
import config

from services import (
    health_bp,
    db_bp,
    submit_bp,
    jobs_bp,
    profiles_bp,
    applications_bp,
    auth_bp,
    tailor_bp,
)
from services.auth import ensure_password_column
from services.agent import run_agent_for_user

# --- app setup ---

TEMPLATES_DIR = Path(__file__).parent.parent / 'frontend' / 'templates'
app = Flask(__name__, template_folder=str(TEMPLATES_DIR))
app.secret_key = config.SECRET_KEY

# --- startup migrations ---

ensure_password_column()

# --- register blueprints ---

app.register_blueprint(health_bp)
app.register_blueprint(db_bp)
app.register_blueprint(submit_bp)
app.register_blueprint(jobs_bp)
app.register_blueprint(profiles_bp)
app.register_blueprint(applications_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(tailor_bp)

# --- template routes ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login')
def login():
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    return render_template('dashboard.html')

@app.route('/onboarding')
def onboarding():
    return render_template('onboarding.html')

@app.route('/profile')
def profile():
    return render_template('profile.html')

@app.route('/browse')
def browse():
    return render_template('jobs.html')

@app.route('/tailor')
def tailor():
    return render_template('tailor.html')

@app.route('/chat')
def chat():
    return render_template('chat.html')

@app.route('/settings')
def settings():
    return render_template('settings.html')

@app.route('/about')
def about():
    return render_template('about.html')

# --- error handling ---

@app.errorhandler(404)
def not_found(_e):
    return render_template('404.html'), 404

# --- agent API ---

@app.route('/agent', methods=['POST'])
def run_agent():
    data = request.get_json()
    user_id = data.get("user_id")

    if not user_id:
        return jsonify({
            "status": "error",
            "message": "user_id is required"
        }), 400

    result = run_agent_for_user(user_id)

    return jsonify({
        "status": "success",
        "user_id": user_id,
        **result
    })

# --- run app ---

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)