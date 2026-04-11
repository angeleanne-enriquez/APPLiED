from __future__ import annotations

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


def _gemini_json(prompt: str, schema: dict) -> dict:
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not set")

    client = genai.Client(api_key=GEMINI_API_KEY)
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config={
            "response_mime_type": "application/json",
            "response_json_schema": schema,
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

    return payload


def _source_block(research_context: dict) -> str:
    sources = research_context.get("sources", [])
    if not sources:
        return "No web sources were available. Use only the job description, company name, and candidate resume context."

    compact_sources = [
        {
            "title": source.get("title"),
            "url": source.get("url"),
            "snippet": source.get("snippet"),
            "query": source.get("query"),
        }
        for source in sources
    ]
    return _json_pretty(compact_sources)


def _brief_schema() -> dict:
    return {
        "type": "object",
        "propertyOrdering": [
            "summary",
            "role_context",
            "likely_process",
            "likely_questions",
            "company_signals",
            "candidate_positioning",
            "practice_plan",
            "research",
            "generator",
        ],
        "properties": {
            "summary": {"type": "string"},
            "role_context": {
                "type": "object",
                "properties": {
                    "job_title": {"type": "string"},
                    "company": {"type": "string"},
                    "location": {"type": "string"},
                    "core_skills": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["job_title", "company", "location", "core_skills"],
                "additionalProperties": False,
            },
            "likely_process": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "stage": {"type": "string"},
                        "what_to_expect": {"type": "string"},
                        "prep_notes": {"type": "string"},
                    },
                    "required": ["stage", "what_to_expect", "prep_notes"],
                    "additionalProperties": False,
                },
            },
            "likely_questions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "category": {"type": "string"},
                        "question": {"type": "string"},
                        "why_it_matters": {"type": "string"},
                        "strong_answer_signals": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["category", "question", "why_it_matters", "strong_answer_signals"],
                    "additionalProperties": False,
                },
            },
            "company_signals": {"type": "array", "items": {"type": "string"}},
            "candidate_positioning": {
                "type": "object",
                "properties": {
                    "strengths_to_emphasize": {"type": "array", "items": {"type": "string"}},
                    "gaps_to_prepare": {"type": "array", "items": {"type": "string"}},
                    "stories_to_prepare": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["strengths_to_emphasize", "gaps_to_prepare", "stories_to_prepare"],
                "additionalProperties": False,
            },
            "practice_plan": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "step": {"type": "string"},
                        "goal": {"type": "string"},
                        "prompt": {"type": "string"},
                    },
                    "required": ["step", "goal", "prompt"],
                    "additionalProperties": False,
                },
            },
            "research": {
                "type": "object",
                "properties": {
                    "mode": {"type": "string"},
                    "source_count": {"type": "integer"},
                    "queries": {"type": "array", "items": {"type": "string"}},
                    "notes": {"type": "string"},
                },
                "required": ["mode", "source_count", "queries", "notes"],
                "additionalProperties": False,
            },
            "generator": {
                "type": "object",
                "properties": {
                    "provider": {"type": "string"},
                    "model": {"type": "string"},
                    "generated_at": {"type": "string"},
                },
                "required": ["provider", "model", "generated_at"],
                "additionalProperties": False,
            },
        },
        "required": [
            "summary",
            "role_context",
            "likely_process",
            "likely_questions",
            "company_signals",
            "candidate_positioning",
            "practice_plan",
            "research",
            "generator",
        ],
        "additionalProperties": False,
    }


def _questions_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "questions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "category": {"type": "string"},
                        "question": {"type": "string"},
                        "follow_up": {"type": "string"},
                        "answer_signals": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["category", "question", "follow_up", "answer_signals"],
                    "additionalProperties": False,
                },
            },
            "generator": {
                "type": "object",
                "properties": {
                    "provider": {"type": "string"},
                    "model": {"type": "string"},
                    "generated_at": {"type": "string"},
                },
                "required": ["provider", "model", "generated_at"],
                "additionalProperties": False,
            },
        },
        "required": ["questions", "generator"],
        "additionalProperties": False,
    }


def _reply_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "interviewer_message": {"type": "string"},
            "feedback_snapshot": {"type": "string"},
            "suggested_focus": {"type": "string"},
            "generator": {
                "type": "object",
                "properties": {
                    "provider": {"type": "string"},
                    "model": {"type": "string"},
                    "generated_at": {"type": "string"},
                },
                "required": ["provider", "model", "generated_at"],
                "additionalProperties": False,
            },
        },
        "required": ["interviewer_message", "feedback_snapshot", "suggested_focus", "generator"],
        "additionalProperties": False,
    }


def _feedback_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "overall": {"type": "string"},
            "strengths": {"type": "array", "items": {"type": "string"}},
            "improvements": {"type": "array", "items": {"type": "string"}},
            "scores": {
                "type": "object",
                "properties": {
                    "role_alignment": {"type": "integer"},
                    "specificity": {"type": "integer"},
                    "structure": {"type": "integer"},
                    "communication": {"type": "integer"},
                },
                "required": ["role_alignment", "specificity", "structure", "communication"],
                "additionalProperties": False,
            },
            "next_drills": {"type": "array", "items": {"type": "string"}},
            "generator": {
                "type": "object",
                "properties": {
                    "provider": {"type": "string"},
                    "model": {"type": "string"},
                    "generated_at": {"type": "string"},
                },
                "required": ["provider", "model", "generated_at"],
                "additionalProperties": False,
            },
        },
        "required": ["overall", "strengths", "improvements", "scores", "next_drills", "generator"],
        "additionalProperties": False,
    }


def _generator_metadata(provider: str) -> dict:
    return {
        "provider": provider,
        "model": GEMINI_MODEL if provider == "gemini" else "local_fallback",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _fallback_brief(profile: dict, job: dict, research_context: dict) -> dict:
    title = job.get("title") or "the role"
    company = job.get("company") or "the company"
    resume_text = profile.get("resume_text") or ""
    skills = []
    for skill in ("Python", "SQL", "APIs", "React", "Flask", "machine learning", "communication"):
        if skill.lower() in resume_text.lower() or skill.lower() in (job.get("description") or "").lower():
            skills.append(skill)

    return {
        "summary": f"Prepare for a {title} interview at {company} by connecting the job description to concrete resume stories.",
        "role_context": {
            "job_title": title,
            "company": company,
            "location": job.get("location") or "",
            "core_skills": skills[:6] or ["role fundamentals", "communication", "problem solving"],
        },
        "likely_process": [
            {
                "stage": "Recruiter screen",
                "what_to_expect": "Motivation, availability, role fit, and high-level background.",
                "prep_notes": "Prepare a concise story for why this company and role are a fit.",
            },
            {
                "stage": "Technical or role interview",
                "what_to_expect": "Questions tied to the job description and practical examples from prior work.",
                "prep_notes": "Use specific projects, tradeoffs, tools, and outcomes from the resume.",
            },
            {
                "stage": "Behavioral interview",
                "what_to_expect": "Collaboration, ownership, ambiguity, feedback, and learning moments.",
                "prep_notes": "Prepare STAR stories with measurable or concrete results.",
            },
        ],
        "likely_questions": [
            {
                "category": "Role fit",
                "question": f"What interests you about this {title} role at {company}?",
                "why_it_matters": "Tests motivation and whether the candidate understands the role.",
                "strong_answer_signals": ["Connects role needs to resume evidence", "Names specific responsibilities", "Avoids generic enthusiasm"],
            },
            {
                "category": "Experience",
                "question": "Tell me about a project that best matches this job description.",
                "why_it_matters": "Checks practical fit against the posted responsibilities.",
                "strong_answer_signals": ["Clear context", "Specific actions", "Concrete impact", "Relevant tools"],
            },
            {
                "category": "Behavioral",
                "question": "Describe a time you had to learn something quickly to deliver a result.",
                "why_it_matters": "Signals adaptability and growth under realistic constraints.",
                "strong_answer_signals": ["Honest gap", "Learning strategy", "Result", "Reflection"],
            },
        ],
        "company_signals": [
            f"Use the job posting and public company context for {company} to tailor examples.",
            "Prepare thoughtful questions about team workflow, success metrics, and onboarding.",
        ],
        "candidate_positioning": {
            "strengths_to_emphasize": ["Relevant projects", "Transferable technical skills", "Clear communication"],
            "gaps_to_prepare": ["Any required tools not strongly represented in the resume", "Company-specific interview process details if web research is unavailable"],
            "stories_to_prepare": ["A technical project", "A collaboration story", "A learning or ambiguity story"],
        },
        "practice_plan": [
            {"step": "Warm-up", "goal": "Clarify motivation", "prompt": "Why this role and company?"},
            {"step": "Evidence", "goal": "Match resume to role", "prompt": "Walk through your most relevant project."},
            {"step": "Depth", "goal": "Show technical judgment", "prompt": "Explain a tradeoff you made and why."},
            {"step": "Close", "goal": "Ask strong questions", "prompt": "What do you want to learn from the interviewer?"},
        ],
        "research": {
            "mode": research_context.get("mode", "fallback"),
            "source_count": len(research_context.get("sources", [])),
            "queries": research_context.get("queries", []),
            "notes": research_context.get("reason") or "Generated from available role, company, and candidate context.",
        },
        "generator": _generator_metadata("local_fallback"),
    }


def generate_interview_brief(profile: dict, job: dict, research_context: dict) -> dict:
    prompt = f"""
You are creating an interview prep brief for a job candidate.

Candidate profile:
{_json_pretty(profile)}

Target job:
{_json_pretty(job)}

Interview research sources:
{_source_block(research_context)}

Research metadata:
{_json_pretty({k: research_context.get(k) for k in ("mode", "reason", "queries")})}

Rules:
- Ground claims in the job description, candidate profile, or supplied source snippets.
- If exact company interview data is thin, say so in the research notes and infer conservatively from the role.
- Do not invent private interview process details.
- Return JSON matching the schema exactly.
""".strip()

    try:
        payload = _gemini_json(prompt, _brief_schema())
        payload["generator"] = _generator_metadata("gemini")
        return payload
    except Exception:
        return _fallback_brief(profile=profile, job=job, research_context=research_context)


def generate_mock_questions(
    profile: dict,
    job: dict,
    brief: dict | None,
    count: int = 5,
    focus: str | None = None,
) -> dict:
    prompt = f"""
Generate {count} interview practice questions.

Focus: {focus or "balanced technical, behavioral, and company-fit practice"}

Candidate profile:
{_json_pretty(profile)}

Target job:
{_json_pretty(job)}

Prep brief:
{_json_pretty(brief or {})}

Rules:
- Questions should be answerable without inventing experience.
- Include follow-ups that an interviewer could ask naturally.
- Return JSON matching the schema exactly.
""".strip()

    try:
        payload = _gemini_json(prompt, _questions_schema())
        payload["questions"] = payload.get("questions", [])[:count]
        payload["generator"] = _generator_metadata("gemini")
        return payload
    except Exception:
        fallback_questions = _fallback_brief(profile, job, {"mode": "fallback", "sources": [], "queries": []})["likely_questions"]
        fallback_questions.extend([
            {
                "category": "Technical judgment",
                "question": "Walk me through a technical decision you made and the tradeoffs you considered.",
                "strong_answer_signals": ["Names options", "Explains tradeoffs", "Connects decision to outcome"],
            },
            {
                "category": "Collaboration",
                "question": "Tell me about a time you worked with product, design, or another teammate to improve the result.",
                "strong_answer_signals": ["Clarifies role", "Shows communication", "Describes impact"],
            },
            {
                "category": "Closing",
                "question": "What questions do you have about this team and role?",
                "strong_answer_signals": ["Asks about success measures", "Asks about team workflow", "Shows role-specific curiosity"],
            },
        ])
        return {
            "questions": [
                {
                    "category": item["category"],
                    "question": item["question"],
                    "follow_up": "Can you give a specific example?",
                    "answer_signals": item["strong_answer_signals"],
                }
                for item in fallback_questions[:count]
            ],
            "generator": _generator_metadata("local_fallback"),
        }


def generate_interviewer_reply(
    profile: dict,
    job: dict,
    brief: dict | None,
    turns: list[dict],
    latest_user_message: str,
) -> dict:
    prompt = f"""
You are a realistic but supportive interviewer for this role.

Candidate profile:
{_json_pretty(profile)}

Target job:
{_json_pretty(job)}

Prep brief:
{_json_pretty(brief or {})}

Conversation so far:
{_json_pretty(turns[-12:])}

Latest candidate answer:
{latest_user_message}

Rules:
- Ask one concise follow-up or next interview question.
- Give one short feedback snapshot without ending the mock interview.
- Stay grounded in the role and candidate background.
- Return JSON matching the schema exactly.
""".strip()

    try:
        payload = _gemini_json(prompt, _reply_schema())
        payload["generator"] = _generator_metadata("gemini")
        return payload
    except Exception:
        return {
            "interviewer_message": "Thanks. Can you make that more specific by walking me through the situation, your action, and the result?",
            "feedback_snapshot": "Good start. Add concrete details, tools, tradeoffs, and measurable impact where you can.",
            "suggested_focus": "Use a STAR structure and connect the example back to the role.",
            "generator": _generator_metadata("local_fallback"),
        }


def generate_session_feedback(
    profile: dict,
    job: dict,
    brief: dict | None,
    turns: list[dict],
) -> dict:
    prompt = f"""
Evaluate this mock interview session.

Candidate profile:
{_json_pretty(profile)}

Target job:
{_json_pretty(job)}

Prep brief:
{_json_pretty(brief or {})}

Session turns:
{_json_pretty(turns)}

Rules:
- Be constructive and specific.
- Scores must be integers from 1 to 5.
- Do not punish the candidate for missing facts that were never provided.
- Return JSON matching the schema exactly.
""".strip()

    try:
        payload = _gemini_json(prompt, _feedback_schema())
        payload["generator"] = _generator_metadata("gemini")
        return payload
    except Exception:
        return {
            "overall": "The session has enough signal to keep practicing. Focus on sharper structure and more role-specific evidence.",
            "strengths": ["Stayed engaged with the interviewer", "Provided an initial answer to build from"],
            "improvements": ["Use clearer STAR structure", "Add specific project details", "Connect answers directly to the job description"],
            "scores": {
                "role_alignment": 3,
                "specificity": 3,
                "structure": 3,
                "communication": 3,
            },
            "next_drills": ["Practice a two-minute project walkthrough", "Prepare one conflict story", "Prepare one learning story"],
            "generator": _generator_metadata("local_fallback"),
        }
