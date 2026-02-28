# graph_builder.py
import re
import psycopg2
import json
from langgraph.graph import StateGraph, END
from graph.state import AgentState 
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from services.db import DATABASE_URL


# toggle between mock data and real DB
'''
USE_MOCK = False  # set True if you want to test with mock data

if USE_MOCK:
    from mock.mock_data import MOCK_PROFILE, MOCK_JOBS
else:
    from services.db import DATABASE_URL
    import psycopg2
'''

top_n = 5  # number of jobs to return in response

# helper: db connection
def get_db_connection():
    # if USE_MOCK:
    #     return None  # no DB connection needed in mock mode
    return psycopg2.connect(DATABASE_URL)


# node 1: load_profile
def load_profile_node(state: AgentState) -> AgentState:
    """
    Loads resume_text and preferences for a given user_id.
    Uses mock data if USE_MOCK=True.
    
    if USE_MOCK:
        state["user_profile"] = {
            "user_id": MOCK_PROFILE["user_id"],
            "first_name": MOCK_PROFILE["first_name"],
            "last_name": MOCK_PROFILE["last_name"],
            "email": MOCK_PROFILE["email"]
        }
        state["resume_text"] = MOCK_PROFILE.get("resume_text", "")
        state["preferences"] = MOCK_PROFILE.get("preferences", {})
        return state
    """

    # real DB mode
    user_id = state.get("user_id")
    if not user_id:
        state["error"] = "no user_id provided"
        return state

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT u.id, u.email, u.first_name, u.last_name,
               p.resume_text, p.preferences_json
        FROM users u
        JOIN profiles p ON p.user_id = u.id
        WHERE u.id = %s
    """, (user_id,))

    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row:
        state["error"] = "user not found"
        return state

    state["user_profile"] = {
        "user_id": row[0],
        "email": row[1],
        "first_name": row[2],
        "last_name": row[3]
    }
    state["resume_text"] = row[4] or ""
    state["preferences"] = row[5] if isinstance(row[5], dict) else (json.loads(row[5]) if row[5] else {})

    return state


# node 2: load_jobs
def load_jobs_node(state: AgentState) -> AgentState:
    """
    Loads candidate jobs from DB or mock.
    Works with current Supabase schema (no salary/remote needed).

    if USE_MOCK:
        state["candidate_jobs"] = MOCK_JOBS
        state["jobs_list"] = MOCK_JOBS
        return state
    """

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, title, company, location, description, url, category
        FROM job_postings
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    jobs = []
    for row in rows:
        jobs.append({
            "id": row[0],
            "title": row[1],
            "company": row[2],
            "location": row[3],
            "description": row[4],
            "url": row[5],
            "category": row[6]
        })

    state["candidate_jobs"] = jobs
    state["jobs_list"] = jobs
    return state

# helper: clean resume/job text
def clean_text(text):
    if not text:
        return ""
    # remove HTML tags
    text = re.sub(r"<[^>]+>", " ", text)
    # remove common CSS/HTML words that are not relevant for matching
    noise_words = ["style", "color", "border", "box", "font", "width", "height", "div", "li", "h1", "h2", "h3", "h4", "h5"]
    for w in noise_words:
        text = re.sub(rf"\b{w}\b", " ", text, flags=re.IGNORECASE)
    # remove extra spaces
    text = re.sub(r"\s+", " ", text)
    return text.lower().strip()

TECH_SKILLS = {
    "python", "django", "javascript", "typescript", "react", "angular", "swift", "ios",
    "ml", "ai", "tensorflow", "pytorch", "nlp", "ros", "robotics", "devops",
    "docker", "kubernetes", "sql", "postgresql", "supabase", "css", "html",
    "security", "offensive", "rails", "shopware", "infrastructure", "data", "analytics"
}

'''
def generate_resume_node(state: AgentState) -> AgentState:
    """
    Generate a new resume (mock / placeholder).
    Saves path to db and outputs resume text and keywords.
    """
    import uuid
    user_id = state.get("user_id")
    
    # mock resume text + keywords
    resume_text = state.get("resume_text", "")
    keywords = ["python", "ai", "ml"]  # mock LLM output

    # mock file path
    file_path = f"/resumes/{user_id}_{uuid.uuid4()}.pdf"
    state["resume_text"] = resume_text
    state["resume_path"] = file_path
    state["llm_keywords"] = keywords

    # persist path in applications (mock, update real db later)
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO applications (user_id, draft_path)
        VALUES (%s, %s)
        RETURNING id
    """, (user_id, file_path))
    app_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    
    state["application_id"] = app_id
    return state
'''

# node 3: score_jobs
def score_jobs_node(state: AgentState) -> AgentState:
    """
    Scoring using TF-IDF + cosine similarity between cleaned (resume + preferences) 
    and cleaned (job title + description). Rationale shows top contributing technical terms
    or top keywords if no tech terms are found.
    """
    resume_text = clean_text(state.get("resume_text", ""))
    preferences = state.get("preferences", {})
    candidate_jobs = state.get("candidate_jobs", [])

    # combine resume + preferences into one user string
    user_parts = [resume_text]
    if preferences.get("location"):
        user_parts.append(preferences["location"])
    if preferences.get("job_type"):
        user_parts.append(preferences["job_type"])
    if preferences.get("remote") is not None:
        user_parts.append("remote" if preferences["remote"] else "on-site")
    if preferences.get("salary_min") is not None:
        user_parts.append(f"salary {preferences['salary_min']}")
    
    user_text = " ".join(user_parts)
    user_text = clean_text(user_text)

    # clean job descriptions
    job_texts = [clean_text(f"{job['title']} {job['description']}") for job in candidate_jobs]
    all_texts = [user_text] + job_texts

    vectorizer = TfidfVectorizer(stop_words="english")
    tfidf_matrix = vectorizer.fit_transform(all_texts)
    user_vector = tfidf_matrix[0]

    scored_jobs = []
    feature_array = vectorizer.get_feature_names_out()

    for idx, job in enumerate(candidate_jobs):
        job_vector = tfidf_matrix[idx + 1]
        sim_score = cosine_similarity(user_vector, job_vector)[0][0]
        score = round(sim_score * 100, 2)

        # rationale: top contributing terms in job vector
        job_tfidf = job_vector.toarray()[0]
        top_indices = job_tfidf.argsort()[::-1][:10]  # check top 10
        top_keywords = [feature_array[i] for i in top_indices if job_tfidf[i] > 0]

        # filter rationale to tech keywords
        tech_keywords = [
            kw for kw in top_keywords
            if any(tech in kw.lower() for tech in TECH_SKILLS)
        ]

        # if no tech keywords, fallback to top 3 TF-IDF keywords
        rationale_keywords = ", ".join(tech_keywords) if tech_keywords else ", ".join(top_keywords[:3])

        if score > 0:
            scored_jobs.append({
                "job_postings_id": job["id"],
                "score": score,
                "rationale": f"matched on keywords: {rationale_keywords}"
            })

    scored_jobs.sort(key=lambda x: x["score"], reverse=True)
    state["scored_jobs"] = scored_jobs
    state["matched_jobs"] = scored_jobs
    return state


# node 4: persist_results
def persist_results_node(state: AgentState) -> AgentState:
    """
    Persist scored jobs to job_matches table.
    No unique constraints needed; just inserts each match.
    
    if USE_MOCK:
        return state
    """

    user_id = state.get("user_id")
    scored_jobs = state.get("scored_jobs", [])

    if not user_id or not scored_jobs:
        return state

    conn = get_db_connection()
    cur = conn.cursor()

    for job in scored_jobs:
        cur.execute("""
            INSERT INTO job_matches (user_id, job_posting_id, score, rationale)
            VALUES (%s, %s, %s, %s)
        """, (
            user_id,
            job["job_postings_id"],
            float(job["score"]),
            job["rationale"]
        ))

    conn.commit()
    cur.close()
    conn.close()
    return state


# node 5: response
def response_node(state: AgentState) -> AgentState:
    """
    Format top N scored jobs into a human-readable response.
    Only updates 'final_response' and keeps 'matched_jobs' for further processing.
    """
    scored_jobs = state.get("scored_jobs", [])

    # top N jobs for human-readable response
    top_jobs = scored_jobs[:top_n]

    if not top_jobs:
        state["final_response"] = "no strong job matches found."
    else:
        # build human-readable response
        lines = [
            f"job id: {job['job_postings_id']} (score: {job['score']})\n"
            f"reason: {job['rationale']}"
            for job in top_jobs
        ]
        state["final_response"] = "\n\n".join(lines)

    # keep all scored jobs for further processing
    state["matched_jobs"] = scored_jobs

    return state


# build graph
def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("load_profile", load_profile_node)
    graph.add_node("load_jobs", load_jobs_node)
    graph.add_node("score_jobs", score_jobs_node)
    graph.add_node("persist_results", persist_results_node)
    graph.add_node("response", response_node)

    graph.set_entry_point("load_profile")

    graph.add_edge("load_profile", "load_jobs")
    graph.add_edge("load_jobs", "score_jobs")
    graph.add_edge("score_jobs", "persist_results")
    graph.add_edge("persist_results", "response")
    graph.add_edge("response", END)

    return graph.compile()