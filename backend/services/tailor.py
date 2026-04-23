import json
import re

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Blueprint, jsonify, request
from google import genai

import config

tailor_bp = Blueprint("tailor", __name__)


def _get_db():
    return psycopg2.connect(config.DATABASE_URL)


def _gemini():
    if not config.GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not set")
    return genai.Client(api_key=config.GEMINI_API_KEY)


def _strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```[a-zA-Z0-9_-]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    return text.strip()


@tailor_bp.route("/tailor/generate", methods=["POST"])
def generate():
    data        = request.get_json() or {}
    user_id     = data.get("user_id")
    job_desc    = (data.get("job_description") or "").strip()
    job_title   = (data.get("job_title") or "").strip()
    company     = (data.get("company") or "").strip()
    mode        = data.get("mode", "both")   # both | resume | cover

    if not user_id:
        return jsonify({"status": "error", "message": "user_id is required"}), 400
    if not job_desc:
        return jsonify({"status": "error", "message": "job_description is required"}), 400

    # ── fetch profile ──
    try:
        conn = _get_db()
        cur  = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT u.first_name, u.last_name, u.email,
                   p.resume_text
            FROM users u
            JOIN profiles p ON p.user_id = u.id
            WHERE u.id = %s
        """, (user_id,))
        row = cur.fetchone()
        cur.close(); conn.close()
    except Exception as e:
        return jsonify({"status": "error", "message": f"db error: {e}"}), 500

    if not row:
        return jsonify({
            "status": "error",
            "message": "profile not found — save your profile first"
        }), 404

    resume_text = (row.get("resume_text") or "").strip()
    if not resume_text:
        return jsonify({
            "status": "error",
            "message": "no resume found — add your resume on the profile page first"
        }), 400

    want_resume = mode in ("both", "resume")
    want_cover  = mode in ("both", "cover")

    prompt = f"""You are a professional resume and cover letter writer.

Candidate:
- Name: {row.get('first_name', '')} {row.get('last_name', '')}
- Email: {row.get('email', '')}

Existing resume:
\"\"\"
{resume_text[:3000]}
\"\"\"

Target role: {job_title or 'not specified'}
Company: {company or 'not specified'}

Job description:
\"\"\"
{job_desc[:2500]}
\"\"\"

Rules:
- Do NOT invent experience, tools, or credentials not in the original resume.
- Keep all content truthful to the existing resume.
- Tailor language and emphasis to match the job description keywords.
- Cover letter: 3-4 short paragraphs, warm but professional.
- match_score: integer 0-100 estimating how well the candidate fits this role.

Return a JSON object with exactly these keys:
{{
  "tailored_resume": "{('full resume text tailored for this role' if want_resume else '')}",
  "cover_letter": "{('personalized cover letter' if want_cover else '')}",
  "rationale": "brief explanation of what was changed and why",
  "match_score": 0
}}

Output valid JSON only — no markdown, no code fences."""
    try:
        client = _gemini()
        res = client.models.generate_content(
            model=config.GEMINI_MODEL,
            contents=prompt,
        )
        text = _strip_fences(res.text or "")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            m = re.search(r'\{.*\}', text, re.DOTALL)
            if not m:
                raise ValueError("no JSON in response")
            payload = json.loads(m.group())
    except Exception as e:
        return jsonify({"status": "error", "message": f"Gemini error: {e}"}), 500

    return jsonify({
        "status":         "success",
        "tailored_resume": payload.get("tailored_resume", "") if want_resume else "",
        "cover_letter":    payload.get("cover_letter", "")    if want_cover  else "",
        "rationale":       payload.get("rationale", ""),
        "match_score":     payload.get("match_score"),
    }), 200
