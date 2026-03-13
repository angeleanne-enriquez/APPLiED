from typing import TypedDict, List, Dict, Optional


class ScoredJob(TypedDict):
    job_postings_id: str
    score: float        # 0–100 composite score
    rationale: str


class AgentState(TypedDict, total=False):
    # ── input ──────────────────────────────────────────────────────────────────
    user_id: str

    # ── loaded from DB ─────────────────────────────────────────────────────────
    user_profile: Dict          # id, email, first_name, last_name
    resume_text: str
    major: List[str]
    job_type: List[str]    
    location: List[str]       # replaced preferences by these three factor to parse through easier when fetching jobs
    resume_skills: List[str]    # pre-extracted skills from resume (set once, reused)

    # ── jobs ───────────────────────────────────────────────────────────────────
    candidate_jobs: List[Dict]
    jobs_list: List[Dict]       # alias kept for API compatibility

    # ── scoring ────────────────────────────────────────────────────────────────
    scored_jobs: List[ScoredJob]
    matched_jobs: List[ScoredJob]   # alias for scored_jobs (top-N + rest)

    # ── output ─────────────────────────────────────────────────────────────────
    final_response: str
    error: str
