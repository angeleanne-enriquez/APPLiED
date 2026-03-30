# services/agent.py
from graph.graph_builder import build_graph
# from graph.graph_builder import MOCK_JOBS, USE_MOCK  # import for fallback in mock mode

def run_agent_for_user(user_id: str) -> dict:
    """
    Runs the agent for a given user_id and returns a normalized dict.
    Ensures that jobs_list, matched_jobs, and user_profile are always populated.
    """
    graph = build_graph()
    state = graph.invoke({"user_id": user_id})

    scored_jobs = state.get("matched_jobs", state.get("scored_jobs", []))
    response = state.get("final_response", "no strong matches found")

    # build a lookup so we can enrich each match with title/company/location
    job_lookup = {j["id"]: j for j in state.get("candidate_jobs", [])}

    matched_jobs = []
    for j in scored_jobs:
        jid = j.get("job_postings_id") or j.get("job_posting_id", "")
        meta = job_lookup.get(jid, {})
        matched_jobs.append({
            "job_postings_id": jid,
            "title":    meta.get("title", ""),
            "company":  meta.get("company", ""),
            "location": meta.get("location", ""),
            "score":    j.get("score", 0),
            "rationale": j.get("rationale", ""),
        })

    return {
        "matched_jobs": matched_jobs,
        "response": response,
    }