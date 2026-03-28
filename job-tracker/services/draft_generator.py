import json
import re
from datetime import datetime, timezone
from typing import Any

from google import genai

from config import GEMINI_API_KEY, GEMINI_MODEL


def _json_pretty(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9_-]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return text.strip()


def _safe_json_loads(text: str) -> dict:
    cleaned = _strip_code_fences(text)
    return json.loads(cleaned)


def _match_context_block(match_context: dict | None) -> str:
    if not match_context:
        return "No stored match context was provided."

    score = match_context.get("score")
    rationale = match_context.get("rationale")

    return f"""
Match context from ranking pipeline:
- Score: {score if score is not None else "N/A"}
- Rationale: {rationale or "N/A"}

Use this ranking context to decide what to emphasize, but do not invent any facts.
""".strip()


def _build_prompt(profile: dict, job: dict, match_context: dict | None = None) -> str:
    resume_text = profile.get("resume_text", "")
    preferences = profile.get("preferences_json", {}) or {}

    return f"""
You are helping generate a draft job application packet.

Candidate profile:
- First name: {profile.get("first_name", "")}
- Last name: {profile.get("last_name", "")}
- Email: {profile.get("email", "")}

Candidate preferences:
{_json_pretty(preferences)}

Candidate resume text:
\"\"\"
{resume_text}
\"\"\"

Target job:
{_json_pretty(job)}

{_match_context_block(match_context)}

Rules:
- Resume output must stay truthful to the original resume.
- Do not invent experience, degrees, employers, certifications, tools, or achievements.
- Do not transform the candidate into a different profession than what the original resume supports.
- Use the match rationale only to prioritize emphasis, not to create new facts.
- Cover letter should be concise, specific to the job, and professional.
- Use markdown formatting for both outputs.
- Do not wrap the output in markdown code fences.
- Return content that matches the requested JSON schema exactly.
""".strip()


def _response_schema() -> dict:
    return {
        "type": "object",
        "propertyOrdering": [
            "resume_markdown",
            "cover_letter_markdown",
            "notes",
        ],
        "properties": {
            "resume_markdown": {
                "type": "string",
                "description": "Tailored resume in markdown, grounded only in the original resume.",
            },
            "cover_letter_markdown": {
                "type": "string",
                "description": "Concise, professional cover letter in markdown.",
            },
            "notes": {
                "type": "object",
                "propertyOrdering": [
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
                "required": [
                    "job_title",
                    "company",
                    "match_summary",
                    "key_skills_emphasized",
                ],
                "additionalProperties": False,
            },
        },
        "required": [
            "resume_markdown",
            "cover_letter_markdown",
            "notes",
        ],
        "additionalProperties": False,
    }


def generate_application_packet(
    profile: dict,
    job: dict,
    match_context: dict | None = None,
) -> dict:
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not set")

    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = _build_prompt(profile, job, match_context=match_context)

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config={
            "response_mime_type": "application/json",
            "response_json_schema": _response_schema(),
        },
    )

    if not response.text:
        raise ValueError("Gemini returned an empty response")

    try:
        payload = json.loads(response.text)
    except json.JSONDecodeError:
        payload = _safe_json_loads(response.text)

    if not isinstance(payload, dict):
        raise ValueError("Gemini response was not a JSON object")

    for key in ("resume_markdown", "cover_letter_markdown", "notes"):
        if key not in payload:
            raise ValueError(f"Gemini response missing required key: {key}")

    resume_markdown = payload["resume_markdown"]
    cover_letter_markdown = payload["cover_letter_markdown"]
    notes = payload.get("notes", {})

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
        "notes": notes,
    }

    return {
        "resume_markdown": resume_markdown,
        "cover_letter_markdown": cover_letter_markdown,
        "manifest": manifest,
    }