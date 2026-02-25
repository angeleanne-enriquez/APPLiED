from langgraph.graph import StateGraph, END
from graph.state import AgentState
from mock.mock_data import MOCK_PROFILE, MOCK_JOBS

# Placeholder nodes - seher will replace these with real logic
def fetch_profile_node(state: AgentState) -> AgentState:
    state["user_profile"] = MOCK_PROFILE
    return state

def fetch_jobs_node(state: AgentState) -> AgentState:
    state["jobs_list"] = MOCK_JOBS
    return state

def match_jobs_node(state: AgentState) -> AgentState:
    return state

def generate_response_node(state: AgentState) -> AgentState:
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
