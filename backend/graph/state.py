from typing import TypedDict, List, Dict, Any


class ScoredJob(TypedDict):
    job_posting_id: str
    score: float
    rationale: str


class AgentState(TypedDict, total=False):
    # input
    user_id: str

    # loaded from DB
    user_profile: Dict[str, Any]
    resume_text: str
    preferences: Dict[str, Any]
    resume_skills: List[str]

    # jobs
    candidate_jobs: List[Dict[str, Any]]
    jobs_list: List[Dict[str, Any]]

    # scoring
    scored_jobs: List[ScoredJob]
    matched_jobs: List[ScoredJob]

    # output
    final_response: str
    error: str