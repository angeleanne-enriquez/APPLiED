from typing import TypedDict, List, Dict, Optional


class ScoredJob(TypedDict):
    job_postings_id: str
    score: float
    rationale: str


class AgentState(TypedDict, total=False):
    # required input
    user_id: str

    # loaded from DB (mocked for now)
    resume_text: str
    preferences: Dict

    # loaded from DB (mocked for now)
    candidate_jobs: List[Dict]

    # produced by scoring node
    scored_jobs: List[ScoredJob]

    # final formatted response (top N jobs)
    final_response: str