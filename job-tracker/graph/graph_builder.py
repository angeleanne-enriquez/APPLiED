import json
import re

import psycopg2
from langgraph.graph import StateGraph, END
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from config import DATABASE_URL
from graph.state import AgentState


top_n = 5


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
        pattern = rf"\b{skill}\b"
        if re.search(pattern, lowered):
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
    """
    Composite breakdown:
    - TF-IDF cosine similarity: 40 pts
    - Skill overlap: 40 pts
    - Preference alignment: 20 pts
    """

    cleaned_resume = clean_text(resume_text)
    cleaned_job = clean_text(job_text)

    if cleaned_resume and cleaned_job:
        vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2))
        tfidf = vectorizer.fit_transform([cleaned_resume, cleaned_job])
        cos_sim = cosine_similarity(tfidf[0], tfidf[1])[0][0]
    else:
        cos_sim = 0.0

    tfidf_score = round(cos_sim * 40, 2)

    matched_skills = resume_skills & job_skills
    missing_skills = job_skills - resume_skills

    if job_skills:
        skill_ratio = len(matched_skills) / len(job_skills)
        skill_score = round(skill_ratio * 40, 2)
    else:
        skill_score = 0.0

    pref_score = 0.0
    pref_notes = []

    pref_location = (preferences.get("location") or "").lower().strip()
    job_location = (job.get("location") or "").lower().strip()

    if pref_location and job_location:
        if pref_location in job_location or job_location in pref_location:
            pref_score += 10
            pref_notes.append(f"location match ({job_location})")
        elif "remote" in job_location:
            pref_score += 5
            pref_notes.append("remote position available")

    wants_remote = preferences.get("remote")
    if wants_remote is True and "remote" in job_location:
        pref_score += 5
        pref_notes.append("remote preferred ✓")
    elif wants_remote is False and "remote" not in job_location:
        pref_score += 5
        pref_notes.append("on-site preferred ✓")

    pref_type = (preferences.get("job_type") or "").lower().strip()
    job_cat = (job.get("category") or "").lower().strip()
    if pref_type and job_cat and (pref_type in job_cat or job_cat in pref_type):
        pref_score += 5
        pref_notes.append(f"job type match ({job_cat})")

    pref_score = min(pref_score, 20)

    total = round(tfidf_score + skill_score + pref_score, 2)

    strength = (
        "strong match" if total >= 75
        else "moderate match" if total >= 50
        else "weak match"
    )

    rationale_parts = [f"[{strength} — {total}/100]"]

    if matched_skills:
        rationale_parts.append(f"matched skills: {', '.join(sorted(matched_skills))}")
    else:
        rationale_parts.append("no direct skill overlap detected")

    if missing_skills:
        top_missing = sorted(missing_skills)[:5]
        rationale_parts.append(
            f"skills to highlight or develop: {', '.join(top_missing)}"
        )

    if pref_notes:
        rationale_parts.append(f"preferences: {'; '.join(pref_notes)}")

    rationale_parts.append(
        f"(tfidf={tfidf_score}/40, skills={skill_score}/40, prefs={pref_score}/20)"
    )

    return total, " | ".join(rationale_parts)


def load_profile_node(state: AgentState) -> AgentState:
    user_id = state.get("user_id")
    if not user_id:
        state["error"] = "no user_id provided"
        return state

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT
            u.id,
            u.email,
            u.first_name,
            u.last_name,
            p.resume_text,
            p.preferences_json
        FROM users u
        JOIN profiles p ON p.user_id = u.id
        WHERE u.id = %s
        """,
        (user_id,),
    )
    row = cur.fetchone()

    cur.close()
    conn.close()

    if not row:
        state["error"] = "user not found"
        return state

    preferences = (
        row[5] if isinstance(row[5], dict)
        else (json.loads(row[5]) if row[5] else {})
    )

    state["user_profile"] = {
        "user_id": row[0],
        "email": row[1],
        "first_name": row[2],
        "last_name": row[3],
    }
    state["resume_text"] = row[4] or ""
    state["preferences"] = preferences
    state["resume_skills"] = list(extract_skills(state["resume_text"]))
    return state


def load_jobs_node(state: AgentState) -> AgentState:
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT id, title, company, location, description, url, category
        FROM job_postings
        """
    )
    rows = cur.fetchall()

    cur.close()
    conn.close()

    jobs = [
        {
            "id": row[0],
            "title": row[1],
            "company": row[2],
            "location": row[3],
            "description": row[4],
            "url": row[5],
            "category": row[6],
        }
        for row in rows
    ]

    state["candidate_jobs"] = jobs
    state["jobs_list"] = jobs
    return state


def score_jobs_node(state: AgentState) -> AgentState:
    resume_text = state.get("resume_text", "")
    preferences = state.get("preferences", {})
    candidate_jobs = state.get("candidate_jobs", [])
    resume_skills = set(state.get("resume_skills", [])) or extract_skills(resume_text)

    scored_jobs = []

    for job in candidate_jobs:
        job_text = f"{job['title']} {job['description']}"
        job_skills = extract_skills(job_text)

        score, rationale = compute_composite_score(
            resume_text=resume_text,
            job_text=job_text,
            resume_skills=resume_skills,
            job_skills=job_skills,
            preferences=preferences,
            job=job,
        )

        if score > 0:
            scored_jobs.append(
                {
                    "job_posting_id": job["id"],
                    "score": score,
                    "rationale": rationale,
                }
            )

    scored_jobs.sort(key=lambda x: x["score"], reverse=True)
    state["scored_jobs"] = scored_jobs
    state["matched_jobs"] = scored_jobs
    return state


def persist_results_node(state: AgentState) -> AgentState:
    user_id = state.get("user_id")
    scored_jobs = state.get("scored_jobs", [])

    if not user_id or not scored_jobs:
        return state

    conn = get_db_connection()
    cur = conn.cursor()

    for job in scored_jobs:
        cur.execute(
            """
            INSERT INTO job_matches (user_id, job_posting_id, score, rationale)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (user_id, job_posting_id)
            DO UPDATE SET
                score = EXCLUDED.score,
                rationale = EXCLUDED.rationale
            """,
            (
                user_id,
                job["job_posting_id"],
                float(job["score"]),
                job["rationale"],
            ),
        )

    conn.commit()
    cur.close()
    conn.close()
    return state


def response_node(state: AgentState) -> AgentState:
    scored_jobs = state.get("scored_jobs", [])
    top_jobs = scored_jobs[:top_n]

    if not top_jobs:
        state["final_response"] = "No strong job matches found."
    else:
        lines = [
            f"Job ID: {job['job_posting_id']}  |  Score: {job['score']}/100\n{job['rationale']}"
            for job in top_jobs
        ]
        state["final_response"] = "\n\n".join(lines)

    state["matched_jobs"] = scored_jobs
    return state


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