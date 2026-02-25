from langgraph.graph import StateGraph, END
from graph.state import AgentState
from mock.mock_data import MOCK_PROFILE, MOCK_JOBS

def fetch_profile_node(state: AgentState) -> AgentState:
    state["user_profile"] = MOCK_PROFILE
    return state

def fetch_jobs_node(state: AgentState) -> AgentState:
    state["jobs_list"] = MOCK_JOBS
    return state

def match_jobs_node(state: AgentState) -> AgentState:
    # get user profile and jobs list from state, use empty defaults if missing
    user_profile = state.get("user_profile") or {}
    jobs_list = state.get("jobs_list") or []

    # extract resume text and split into words longer than 3 characters
    resume_text = user_profile.get("resume_text", "").lower()
    resume_words = {w for w in resume_text.split() if len(w) > 3}

    # extract preferences from profile
    prefs = user_profile.get("preferences", {})
    pref_location = prefs.get("location", "").lower()
    pref_job_type = prefs.get("job_type", "").lower()
    pref_remote = prefs.get("remote", None)
    pref_salary = prefs.get("salary_min", None)

    # initialize list to store matched jobs
    matched_jobs = []

    # loop through each job and calculate match score
    for job in jobs_list:
        # combine job title and description for keyword matching
        job_text = f"{job.get('title', '')} {job.get('description', '')}".lower()

        # # find resume keyword matches and calculate weighted score
        resume_matches = [w for w in resume_words if w in job_text]
        score = len(resume_matches) * 2

        # # count how many preference criteria matc
        preference_matches_count = 0
        if pref_location and pref_location in job.get("location", "").lower():
            preference_matches_count += 1
        if pref_job_type and pref_job_type in job.get("title", "").lower():
            preference_matches_count += 1
        if pref_remote is not None and pref_remote == job.get("remote", False):
            preference_matches_count += 1
        if pref_salary is not None and job.get("salary", 0) >= pref_salary:
            preference_matches_count += 1

        # # add preference match count to total score
        score += preference_matches_count

        # # only include jobs with positive score
        if score > 0:
            matched_jobs.append({
                "job_id": job.get("id"),
                "title": job.get("title"),
                "company": job.get("company") or job.get("company_name"),
                "score": score,
                "rationale": (
                    f"{len(resume_matches)} resume keyword matches (weighted x2) and "
                    f"{preference_matches_count} preference matches."
                )
            })
    # sort matched jobs by score descending
    matched_jobs.sort(key=lambda x: x["score"], reverse=True)
    state["matched_jobs"] = matched_jobs
    return state

def generate_response_node(state: AgentState) -> AgentState:
    # get matched jobs from state
    matched_jobs = state.get("matched_jobs") or []

    # take only top n matches
    top_n = 5
    top_matches = matched_jobs[:top_n]

    # handle case where no jobs matched
    if not top_matches:
        state["final_response"] = "No strong job matches found."
        return state

    # build response
    response_lines = []

    for job in top_matches:
        line = (
            f"{job.get('title')} at {job.get('company')} "
            f"(score: {job.get('score')})\n"
            f"Reason: {job.get('rationale')}"
        )
        response_lines.append(line)

    # join lines into single final response string
    state["final_response"] = "\n\n".join(response_lines)

    return state

# Build the graph
def build_graph():
    graph = StateGraph(AgentState)

    # Add nodes
    graph.add_node("fetch_profile", fetch_profile_node)
    graph.add_node("fetch_jobs", fetch_jobs_node)
    graph.add_node("match_jobs", match_jobs_node)
    graph.add_node("generate_response", generate_response_node)

    # Define the flow (order of execution)
    graph.set_entry_point("fetch_profile")
    graph.add_edge("fetch_profile", "fetch_jobs")
    graph.add_edge("fetch_jobs", "match_jobs")
    graph.add_edge("match_jobs", "generate_response")
    graph.add_edge("generate_response", END)

    return graph.compile()
