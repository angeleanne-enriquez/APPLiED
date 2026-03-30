import json
import re

import psycopg2
from langgraph.graph import StateGraph, END
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from google import genai

from graph.state import AgentState
from services.db import DATABASE_URL
import config

# ─── config ───────────────────────────────────────────────────────────────────

top_n = 5
num_ranked_jobs = 20
GEMINI_MODEL = config.GEMINI_MODEL


def _gemini_client():
    if not config.GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not set")
    return genai.Client(api_key=config.GEMINI_API_KEY)

# ─── helpers ──────────────────────────────────────────────────────────────────

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)


def clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)

    noise = [
        "style", "color", "border", "box", "font", "width", "height",
        "div", "li", "h1", "h2", "h3", "h4", "h5"
    ]
    for word in noise:
        text = re.sub(rf"\b{word}\b", " ", text, flags=re.IGNORECASE)

    text = re.sub(r"\s+", " ", text)
    return text.lower().strip()


TECH_SKILLS = {
    "python", "javascript", "typescript", "java", "ruby", "go", "rust", "c\\+\\+", "c#",
    "swift", "kotlin", "scala", "r",
    "django", "flask", "fastapi", "react", "angular", "vue", "next\\.js", "rails",
    "spring", "tensorflow", "pytorch", "keras", "scikit", "pandas", "numpy",
    "docker", "kubernetes", "terraform", "ansible", "jenkins", "github actions",
    "aws", "gcp", "azure", "linux", "nginx",
    "sql", "postgresql", "mysql", "mongodb", "redis", "elasticsearch",
    "spark", "kafka", "airflow", "dbt", "mlflow", "nlp", "llm", "rag",
    "ml", "ai", "machine learning", "deep learning", "data engineering",
    "devops", "security", "robotics", "ros", "ios", "android",
    "agile", "scrum", "ci/cd", "rest", "graphql", "microservices", "tdd",
}


def extract_skills(text: str) -> set[str]:
    found = set()
    lowered = (text or "").lower()

    for skill in TECH_SKILLS:
        if re.search(rf"\b{skill}\b", lowered):
            found.add(re.sub(r"\\", "", skill))

    return found


def compute_composite_score(
    resume_text: str,
    job_text: str,
    resume_skills: set[str],
    job_skills: set[str],
    preferences: dict,
    job: dict,
) -> tuple[float, str]:

    # TF-IDF (40 pts)
    cleaned_resume = clean_text(resume_text)
    cleaned_job = clean_text(job_text)

    if cleaned_resume and cleaned_job:
        tfidf = TfidfVectorizer(stop_words="english", ngram_range=(1, 2)) \
            .fit_transform([cleaned_resume, cleaned_job])
        cos_sim = cosine_similarity(tfidf[0], tfidf[1])[0][0]
    else:
        cos_sim = 0.0

    tfidf_score = round(cos_sim * 40, 2)

    # Skills (40 pts)
    matched_skills = resume_skills & job_skills
    missing_skills = job_skills - resume_skills

    skill_score = round((len(matched_skills) / len(job_skills)) * 40, 2) if job_skills else 0.0

    # Preferences (20 pts)
    pref_score = 0
    pref_notes = []

    pref_location = (preferences.get("location") or "").lower()
    job_location = (job.get("location") or "").lower()

    if pref_location and job_location:
        if pref_location in job_location or job_location in pref_location:
            pref_score += 10
            pref_notes.append(f"location match ({job_location})")
        elif "remote" in job_location:
            pref_score += 5
            pref_notes.append("remote available")

    wants_remote = preferences.get("remote")
    if wants_remote is True and "remote" in job_location:
        pref_score += 5
        pref_notes.append("remote preferred ✓")
    elif wants_remote is False and "remote" not in job_location:
        pref_score += 5
        pref_notes.append("on-site preferred ✓")

    pref_type = (preferences.get("job_type") or "").lower()
    job_cat = (job.get("category") or "").lower()

    if pref_type and job_cat and (pref_type in job_cat or job_cat in pref_type):
        pref_score += 5
        pref_notes.append(f"type match ({job_cat})")

    pref_score = min(pref_score, 20)

    total = round(tfidf_score + skill_score + pref_score, 2)

    strength = (
        "strong match" if total >= 75 else
        "moderate match" if total >= 50 else
        "weak match"
    )

    rationale = [
        f"[{strength} — {total}/100]",
        f"matched skills: {', '.join(sorted(matched_skills))}" if matched_skills else "no direct skill overlap",
    ]

    if missing_skills:
        rationale.append(f"missing: {', '.join(sorted(missing_skills)[:5])}")

    if pref_notes:
        rationale.append(f"prefs: {'; '.join(pref_notes)}")

    return total, " | ".join(rationale)


# ─── nodes ────────────────────────────────────────────────────────────────────

def load_profile_node(state: AgentState) -> AgentState:
    user_id = state.get("user_id")
    if not user_id:
        state["error"] = "no user_id"
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

    prefs = row[5] if isinstance(row[5], dict) else json.loads(row[5] or "{}")

    state["user_profile"] = {
        "user_id": row[0],
        "email": row[1],
        "first_name": row[2],
        "last_name": row[3],
    }
    state["resume_text"] = row[4] or ""
    state["preferences"] = prefs
    state["resume_skills"] = list(extract_skills(state["resume_text"]))

    return state


def load_jobs_node(state: AgentState) -> AgentState:
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, title, company,
               COALESCE(location_normalized, location),
               description,
               COALESCE(apply_url, url),
               COALESCE(category, schedule_type)
        FROM job_postings
    """)

    rows = cur.fetchall()
    cur.close()
    conn.close()

    jobs = [{
        "id": r[0],
        "title": r[1],
        "company": r[2],
        "location": r[3],
        "description": r[4],
        "url": r[5],
        "category": r[6],
    } for r in rows]

    state["candidate_jobs"] = jobs
    return state


def score_jobs_node(state: AgentState) -> AgentState:
    resume_text = state.get("resume_text", "")
    prefs = state.get("preferences", {})
    jobs = state.get("candidate_jobs", [])
    resume_skills = set(state.get("resume_skills", []))

    scored = []

    for job in jobs:
        job_text = f"{job['title']} {job['description']}"
        job_skills = extract_skills(job_text)

        score, rationale = compute_composite_score(
            resume_text, job_text, resume_skills, job_skills, prefs, job
        )

        if score > 0:
            scored.append({
                "job_postings_id": job["id"],
                "score": score,
                "rationale": rationale,
            })

    scored.sort(key=lambda x: x["score"], reverse=True)
    state["scored_jobs"] = scored
    return state


def llm_rerank_node(state: AgentState) -> AgentState:
    scored = state.get("scored_jobs", [])
    jobs = {j["id"]: j for j in state.get("candidate_jobs", [])}

    pool = scored[:num_ranked_jobs]
    if not pool:
        return state

    prompt_jobs = []
    for j in pool:
        job = jobs.get(j["job_postings_id"], {})
        prompt_jobs.append({
            "id": j["job_postings_id"],
            "title": job.get("title"),
            "description": (job.get("description") or "")[:800],
        })

    prompt = f"""
Resume:
{state.get("resume_text", "")[:1500]}

Jobs:
{json.dumps(prompt_jobs)}

Return JSON list of {{job_postings_id, score, rationale}}
"""

    try:
        res = _gemini_client().models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt
        )
        data = json.loads(res.text)
    except Exception as e:
        state["error"] = str(e)
        return state

    llm_map = {d["job_postings_id"]: d for d in data}

    reranked = []
    for j in pool:
        jid = j["job_postings_id"]
        if jid in llm_map:
            reranked.append({
                "job_postings_id": jid,
                "score": round(0.7 * llm_map[jid]["score"] + 0.3 * j["score"], 2),
                "rationale": llm_map[jid]["rationale"],
            })

    reranked.sort(key=lambda x: x["score"], reverse=True)
    state["scored_jobs"] = reranked + scored[num_ranked_jobs:]

    return state


def persist_results_node(state: AgentState) -> AgentState:
    conn = get_db_connection()
    cur = conn.cursor()

    for j in state.get("scored_jobs", []):
        cur.execute("""
            INSERT INTO job_matches (user_id, job_posting_id, score, rationale)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (user_id, job_posting_id)
            DO UPDATE SET score = EXCLUDED.score, rationale = EXCLUDED.rationale
        """, (
            state["user_id"],
            j["job_postings_id"],
            float(j["score"]),
            j["rationale"],
        ))

    conn.commit()
    cur.close()
    conn.close()

    return state


def response_node(state: AgentState) -> AgentState:
    top = state.get("scored_jobs", [])[:top_n]

    state["final_response"] = "\n\n".join([
        f"{j['job_postings_id']} — {j['score']}/100\n{j['rationale']}"
        for j in top
    ]) if top else "No matches found."

    return state


# ─── graph ────────────────────────────────────────────────────────────────────

def build_graph():
    g = StateGraph(AgentState)

    g.add_node("load_profile", load_profile_node)
    g.add_node("load_jobs", load_jobs_node)
    g.add_node("score_jobs", score_jobs_node)
    g.add_node("llm_rerank", llm_rerank_node)
    g.add_node("persist", persist_results_node)
    g.add_node("response", response_node)

    g.set_entry_point("load_profile")

    g.add_edge("load_profile", "load_jobs")
    g.add_edge("load_jobs", "score_jobs")
    g.add_edge("score_jobs", "llm_rerank")
    g.add_edge("llm_rerank", "persist")
    g.add_edge("persist", "response")
    g.add_edge("response", END)

    return g.compile()