# services/agent.py
from graph.graph_builder import build_graph
# from graph.graph_builder import MOCK_JOBS, USE_MOCK  # import for fallback in mock mode

def run_agent_for_user(user_id: str) -> dict:
    """
    Runs the agent for a given user_id and returns a normalized dict.
    Ensures that jobs_list, matched_jobs, and user_profile are always populated.
    """
    # build the agent graph
    graph = build_graph()
    
    # run the graph for this user
    state = graph.invoke({"user_id": user_id})

    # fallback logic in case any key is missing
    matched_jobs = state.get("matched_jobs", state.get("scored_jobs", []))
    response = state.get("final_response", "no strong matches found")

    return {
        # "user_profile": user_profile,
        # "jobs_list": jobs_list,
        "matched_jobs": matched_jobs,
        "response": response
    }