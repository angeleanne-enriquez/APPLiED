import json
import re
from datetime import datetime, timezone
from typing import Any

from google import genai
from config import GEMINI_API_KEY, GEMINI_MODEL

# ─── helpers ──────────────────────────────────────────────────────────────────

def _json_pretty(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9_-]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return text.strip()


def _safe_json_loads(text: str) -> dict:
    return json.loads(_strip_code_fences(text))


def _match_context_block(match_context: dict | None) -> str:
    if not match_context:
        return "No stored match context was provided."

    return f"""
Match context from ranking pipeline:
- Score: {match_context.get("score", "N/A")}
- Rationale: {match_context.get("rationale", "N/A")}

Use this ranking context to guide emphasis, but do not invent facts.
""".strip()


# ─── prompt ───────────────────────────────────────────────────────────────────

def _build_prompt(profile: dict, job: dict, match_context: dict | None = None) -> str:
    return f"""
You are helping generate a draft job application packet.

Candidate profile:
- First name: {profile.get("first_name", "")}
- Last name: {profile.get("last_name", "")}
- Email: {profile.get("email", "")}

Candidate preferences:
{_json_pretty(profile.get("preferences_json", {}) or {})}

Candidate resume text:
\"\"\"
{profile.get("resume_text", "")}
\"\"\"

Target job:
{_json_pretty(job)}

{_match_context_block(match_context)}

Rules:
- Resume must remain truthful to the original.
- Do NOT invent experience, tools, or credentials.
- Use match context only for emphasis.
- Keep cover letter concise and tailored.
- Output valid JSON only (no markdown fences).
- Use markdown inside fields.

Return JSON matching schema exactly.
""".strip()


def _response_schema() -> dict:
    return {
        "type": "object",
        "required": ["resume_markdown", "cover_letter_markdown", "notes"],
        "properties": {
            "resume_markdown": {"type": "string"},
            "cover_letter_markdown": {"type": "string"},
            "notes": {
                "type": "object",
                "required": [
                    "job_title",
                    "company",
                    "match_summary",
                    "key_skills_emphasized",
                ],
                "properties": {
                    "job_title": {"type": "string"},
                    "company": {"type": "string"},
                    "match_summary": {"type": "string"},
                    "key_skills_emphasized": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "additionalProperties": False,
            },
        },
        "additionalProperties": False,
    }


# ─── main ─────────────────────────────────────────────────────────────────────

def generate_application_packet(
    profile: dict,
    job: dict,
    match_context: dict | None = None,
) -> dict:

    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not set")

    client = genai.Client(api_key=GEMINI_API_KEY)

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=_build_prompt(profile, job, match_context),
        config={
            "response_mime_type": "application/json",
            "response_json_schema": _response_schema(),
        },
    )

    if not response.text:
        raise ValueError("Empty response from Gemini")

    try:
        payload = json.loads(response.text)
    except json.JSONDecodeError:
        payload = _safe_json_loads(response.text)

    if not isinstance(payload, dict):
        raise ValueError("Response is not a JSON object")

    # validate required fields
    for key in ("resume_markdown", "cover_letter_markdown", "notes"):
        if key not in payload:
            raise ValueError(f"Missing key: {key}")

    # ── build manifest ──
    manifest = {
        "user_id": str(profile["user_id"]),
        "job_posting_id": str(job["id"]),
        "job_title": job.get("title"),
        "company": job.get("company"),
        "status": "ready_for_review",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": {
            "provider": "gemini",
            "model": GEMINI_MODEL,
        },
        "match_score": match_context.get("score") if match_context else None,
        "match_rationale": match_context.get("rationale") if match_context else None,
        "notes": payload.get("notes", {}),
    }

    return {
        "resume_markdown": payload["resume_markdown"],
        "cover_letter_markdown": payload["cover_letter_markdown"],
        "manifest": manifest,
    }