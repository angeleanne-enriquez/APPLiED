from typing import TypedDict, List, Optional

class AgentState(TypedDict, total=False):
    user_id: str
    user_profile: Optional[dict]
    jobs_list: Optional[List[dict]]
    matched_jobs: Optional[List[dict]]
    final_response: Optional[str]
