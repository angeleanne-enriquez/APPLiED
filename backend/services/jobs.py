from flask import Blueprint, jsonify, request
import datetime
import hashlib
import json
import re
from urllib.parse import urlparse, urlunparse

import requests
import psycopg2
from psycopg2.extras import RealDictCursor

from config import DATABASE_URL, SERPAPI_API_KEY, SERPAPI_BASE_URL

jobs_bp = Blueprint("jobs", __name__)

REMOTE_TERMS = ("remote", "anywhere", "work from home", "wfh", "worldwide")
HYBRID_TERMS = ("hybrid",)


def get_db_connection():
    return psycopg2.connect(DATABASE_URL)


def now_iso() -> str:
    return datetime.datetime.now().isoformat()


def normalize_text(value: str | None) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def clean_url(url: str | None) -> str | None:
    if not url:
        return None
    try:
        parsed = urlparse(url)
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
    except Exception:
        return url


def first_non_empty(*values):
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and value.strip():
            return value.strip()
        if value:
            return value
    return None


def extract_salary_text(parts: list[str], detected: dict) -> str | None:
    salary = detected.get("salary")
    if salary:
        return str(salary).strip()

    salary_pattern = re.compile(r"(\$|€|£)|(\b\d[\d,.\-– ]*(k|/hour|/hr|/year|/month|per hour|per year|per month)\b)", re.I)
    for part in parts:
        if salary_pattern.search(part):
            return part.strip()
    return None


def extract_posted_at_text(parts: list[str], detected: dict) -> str | None:
    posted = detected.get("posted_at")
    if posted:
        return str(posted).strip()

    posted_pattern = re.compile(r"\b(\d+\s+(minute|minutes|hour|hours|day|days|week|weeks|month|months|year|years)\s+ago)\b", re.I)
    for part in parts:
        if posted_pattern.search(part):
            return part.strip()
    return None


def classify_google_remote(location_raw: str | None, extensions: list[str], detected: dict) -> tuple[bool | None, str, str]:
    location_raw = (location_raw or "").strip()
    location_lower = location_raw.lower()
    extensions_lower = [str(x).strip().lower() for x in extensions]

    if detected.get("work_from_home") is True:
        return True, "remote", "Remote"

    if any(term in location_lower for term in REMOTE_TERMS):
        return True, "remote", "Remote"

    if any(any(term in ext for term in REMOTE_TERMS) for ext in extensions_lower):
        return True, "remote", "Remote"

    if "hybrid" in location_lower or any("hybrid" in ext for ext in extensions_lower):
        return False, "hybrid", location_raw or "Hybrid"

    if location_raw:
        return False, "onsite", location_raw

    return None, "unknown", "Unknown"


def classify_remotive_remote(location_raw: str | None) -> tuple[bool, str, str]:
    # Remotive is a remote-only feed. candidate_required_location is a geo restriction,
    # not an on-site office location.
    return True, "remote", "Remote"


def build_canonical_key(title: str | None, company: str | None, location_normalized: str | None, remote_type: str | None) -> str:
    location_token = "remote" if remote_type == "remote" else "hybrid" if remote_type == "hybrid" else normalize_text(location_normalized)
    payload = f"{normalize_text(title)}|{normalize_text(company)}|{location_token}"
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


def fetch_remotive_jobs(limit: int | None = None) -> list[dict]:
    url = "https://remotive.com/api/remote-jobs"
    params = {}
    if limit:
        params["limit"] = limit

    r = requests.get(url, params=params, timeout=30)
    if r.status_code != 200:
        raise Exception(f"Remotive API returned {r.status_code}: {r.text[:200]}")

    return r.json().get("jobs", [])


def fetch_google_jobs(
    job_type: str | None = None,
    location: str | None = None,
    remote_only: bool | None = None,
    pages: int = 1,
) -> list[dict]:
    if not SERPAPI_API_KEY:
        raise ValueError("SERPAPI_API_KEY is not set")

    if not job_type and not location:
        raise ValueError("Google Jobs search needs at least job_type or location")

    pages = max(1, min(int(pages), 5))

    params = {
        "engine": "google_jobs",
        "api_key": SERPAPI_API_KEY,
    }

    if job_type and location:
        params["q"] = f"{job_type} jobs"
        params["location"] = location
    elif job_type:
        params["q"] = f"{job_type} jobs"
    elif location:
        params["q"] = "jobs"
        params["location"] = location

    # SerpApi supports work-from-home filtering via ltype.
    if remote_only is True:
        params["ltype"] = 1

    all_jobs: list[dict] = []
    next_page_token = None

    for _ in range(pages):
        page_params = dict(params)
        if next_page_token:
            page_params["next_page_token"] = next_page_token

        r = requests.get(SERPAPI_BASE_URL, params=page_params, timeout=30)
        if r.status_code != 200:
            raise Exception(f"SerpApi returned {r.status_code}: {r.text[:300]}")

        payload = r.json()
        page_jobs = payload.get("jobs_results", []) or []
        all_jobs.extend(page_jobs)

        next_page_token = payload.get("pagination", {}).get("next_page_token") or payload.get("next_page_token")
        if not next_page_token:
            break

    return all_jobs


def normalize_remotive_job(job: dict) -> dict:
    title = job.get("title")
    company = first_non_empty(job.get("company_name"))
    location_raw = first_non_empty(job.get("candidate_required_location"), job.get("location"), job.get("category"))
    is_remote, remote_type, location_normalized = classify_remotive_remote(location_raw)

    external_id = str(job.get("id"))
    url = first_non_empty(job.get("url"))
    apply_url = url
    description = job.get("description")
    category = job.get("category")
    salary_text = first_non_empty(job.get("salary"))
    schedule_type = first_non_empty(job.get("job_type"))
    posted_at_text = first_non_empty(job.get("publication_date"))

    canonical_key = build_canonical_key(title, company, location_normalized, remote_type)

    return {
        "source": "Remotive",
        "external_id": external_id,
        "source_job_key": f"remotive:{external_id}",
        "title": title,
        "company": company,
        "location": location_raw,
        "location_raw": location_raw,
        "location_normalized": location_normalized,
        "is_remote": is_remote,
        "remote_type": remote_type,
        "url": url,
        "apply_url": apply_url,
        "description": description,
        "category": category,
        "salary_text": salary_text,
        "schedule_type": schedule_type,
        "posted_at_text": posted_at_text,
        "canonical_key": canonical_key,
        "raw_json": job,
    }


def normalize_google_job(job: dict) -> dict:
    title = first_non_empty(job.get("title"))
    company = first_non_empty(job.get("company_name"))
    location_raw = first_non_empty(job.get("location"))

    detected = job.get("detected_extensions") or {}
    extensions = [str(x) for x in (job.get("extensions") or [])]
    apply_options = job.get("apply_options") or []

    is_remote, remote_type, location_normalized = classify_google_remote(location_raw, extensions, detected)

    apply_url = None
    for option in apply_options:
        link = option.get("link")
        if link:
            apply_url = link
            break

    url = first_non_empty(
        clean_url(job.get("share_link")),
        clean_url(job.get("source_link")),
        clean_url(apply_url),
    )

    external_id = first_non_empty(job.get("job_id"))
    if not external_id:
        fallback = f"{title}|{company}|{location_raw}|{url}"
        external_id = hashlib.md5(fallback.encode("utf-8")).hexdigest()

    salary_text = extract_salary_text(extensions, detected)
    schedule_type = first_non_empty(detected.get("schedule_type"))
    posted_at_text = extract_posted_at_text(extensions, detected)

    # Google Jobs usually doesn't have your internal category field.
    category = None

    canonical_key = build_canonical_key(title, company, location_normalized, remote_type)

    return {
        "source": "GoogleJobs",
        "external_id": str(external_id),
        "source_job_key": f"google_jobs:{external_id}",
        "title": title,
        "company": company,
        "location": location_raw,
        "location_raw": location_raw,
        "location_normalized": location_normalized,
        "is_remote": is_remote,
        "remote_type": remote_type,
        "url": url,
        "apply_url": apply_url,
        "description": job.get("description"),
        "category": category,
        "salary_text": salary_text,
        "schedule_type": schedule_type,
        "posted_at_text": posted_at_text,
        "canonical_key": canonical_key,
        "raw_json": job,
    }


def insert_job_posting(cur, job: dict) -> str:
    cur.execute(
        """
        insert into public.job_postings (
            external_id,
            source,
            title,
            company,
            location,
            url,
            description,
            raw_json,
            ingested_at,
            category,
            location_raw,
            location_normalized,
            is_remote,
            remote_type,
            salary_text,
            schedule_type,
            posted_at_text,
            apply_url,
            source_job_key,
            canonical_key,
            last_seen_at
        ) values (
            %s, %s, %s, %s, %s, %s, %s, %s::jsonb, now(), %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now()
        )
        returning id
        """,
        (
            job["external_id"],
            job["source"],
            job["title"],
            job["company"],
            job["location"],
            job["url"],
            job["description"],
            json.dumps(job["raw_json"]),
            job["category"],
            job["location_raw"],
            job["location_normalized"],
            job["is_remote"],
            job["remote_type"],
            job["salary_text"],
            job["schedule_type"],
            job["posted_at_text"],
            job["apply_url"],
            job["source_job_key"],
            job["canonical_key"],
        ),
    )
    row = cur.fetchone()
    return str(row["id"])
    
def update_job_posting(cur, job_posting_id: str, job: dict):
    cur.execute(
        """
        update public.job_postings
        set
            title = coalesce(%s, title),
            company = coalesce(%s, company),
            location = coalesce(%s, location),
            url = coalesce(%s, url),
            description = case
                when coalesce(length(%s), 0) > coalesce(length(description), 0) then %s
                else description
            end,
            raw_json = %s::jsonb,
            category = coalesce(category, %s),
            location_raw = coalesce(%s, location_raw),
            location_normalized = coalesce(%s, location_normalized),
            is_remote = coalesce(%s, is_remote),
            remote_type = coalesce(%s, remote_type),
            salary_text = coalesce(%s, salary_text),
            schedule_type = coalesce(%s, schedule_type),
            posted_at_text = coalesce(%s, posted_at_text),
            apply_url = coalesce(%s, apply_url),
            source_job_key = coalesce(%s, source_job_key),
            canonical_key = coalesce(%s, canonical_key),
            last_seen_at = now()
        where id = %s
        """,
        (
            job["title"],
            job["company"],
            job["location"],
            job["url"],
            job["description"],
            job["description"],
            json.dumps(job["raw_json"]),
            job["category"],
            job["location_raw"],
            job["location_normalized"],
            job["is_remote"],
            job["remote_type"],
            job["salary_text"],
            job["schedule_type"],
            job["posted_at_text"],
            job["apply_url"],
            job["source_job_key"],
            job["canonical_key"],
            job_posting_id,
        ),
    )


def upsert_source_row(cur, job_posting_id: str, job: dict):
    cur.execute(
        """
        insert into public.job_posting_sources (
            job_posting_id,
            source,
            external_id,
            source_job_key,
            source_url,
            apply_url,
            raw_json,
            fetched_at,
            created_at
        ) values (
            %s, %s, %s, %s, %s, %s, %s::jsonb, now(), now()
        )
        on conflict (source, external_id)
        do update set
            job_posting_id = excluded.job_posting_id,
            source_job_key = excluded.source_job_key,
            source_url = excluded.source_url,
            apply_url = excluded.apply_url,
            raw_json = excluded.raw_json,
            fetched_at = now()
        """,
        (
            job_posting_id,
            job["source"],
            job["external_id"],
            job["source_job_key"],
            job["url"],
            job["apply_url"],
            json.dumps(job["raw_json"]),
        ),
    )


def find_exact_posting(cur, job: dict):
    cur.execute(
        """
        select id
        from public.job_postings
        where source = %s and external_id = %s
        limit 1
        """,
        (job["source"], job["external_id"]),
    )
    return cur.fetchone()


def find_canonical_posting(cur, job: dict):
    cur.execute(
        """
        select id
        from public.job_postings
        where canonical_key = %s
        order by ingested_at desc nulls last
        limit 1
        """,
        (job["canonical_key"],),
    )
    return cur.fetchone()


def ingest_normalized_jobs(normalized_jobs: list[dict], write_json: bool = True) -> dict:
    if write_json:
        with open("jobs_normalized.json", "w", encoding="utf-8") as f:
            json.dump(normalized_jobs, f, indent=2)

    received = len(normalized_jobs)
    inserted = 0
    merged = 0
    refreshed = 0

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        for job in normalized_jobs:
            exact = find_exact_posting(cur, job)

            if exact:
                job_posting_id = str(exact["id"])
                update_job_posting(cur, job_posting_id, job)
                upsert_source_row(cur, job_posting_id, job)
                refreshed += 1
                continue

            canonical = find_canonical_posting(cur, job)
            if canonical:
                job_posting_id = str(canonical["id"])
                update_job_posting(cur, job_posting_id, job)
                upsert_source_row(cur, job_posting_id, job)
                merged += 1
                continue

            job_posting_id = insert_job_posting(cur, job)
            upsert_source_row(cur, job_posting_id, job)
            inserted += 1

        conn.commit()

        return {
            "received": received,
            "inserted": inserted,
            "merged": merged,
            "refreshed": refreshed,
        }

    finally:
        cur.close()
        conn.close()


@jobs_bp.route("/jobs/google/<user_id>", methods=["GET"])
def fetch_google_jobs_for_user(user_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute(
            """
            select preferences_json
            from public.profiles
            where user_id = %s
            """,
            (user_id,),
        )
        row = cur.fetchone()

        if not row:
            return jsonify({
                "status": "failure",
                "message": "Profile not found",
                "timestamp": now_iso()
            }), 404

        prefs = row.get("preferences_json") or {}
        if isinstance(prefs, str):
            prefs = json.loads(prefs)

        job_type = prefs.get("job_type")
        location = prefs.get("location")
        remote_only = prefs.get("remote")
        pages = max(1, min(request.args.get("pages", default=1, type=int), 5))
        ingest = str(request.args.get("ingest", "false")).lower() == "true"

        raw_jobs = fetch_google_jobs(
            job_type=job_type,
            location=location,
            remote_only=remote_only,
            pages=pages,
        )
        normalized_jobs = [normalize_google_job(job) for job in raw_jobs]

        response = {
            "status": "success",
            "source": "google_jobs",
            "job_type": job_type,
            "location": location,
            "remote_only": remote_only,
            "pages": pages,
            "count": len(normalized_jobs),
            "jobs": normalized_jobs,
            "timestamp": now_iso(),
        }

        if ingest:
            summary = ingest_normalized_jobs(normalized_jobs, write_json=False)
            response["ingest_summary"] = summary

        return jsonify(response), 200

    except Exception as e:
        return jsonify({
            "status": "failure",
            "message": str(e),
            "timestamp": now_iso()
        }), 500

    finally:
        cur.close()
        conn.close()


@jobs_bp.route("/jobs/ingest", methods=["POST"])
def jobs_ingest():
    data = request.get_json(silent=True) or {}

    provider = str(data.get("provider", "remotive")).lower()
    limit = data.get("limit")
    write_json = bool(data.get("write_json", True))

    job_type = data.get("job_type")
    location = data.get("location")
    remote_only = data.get("remote_only")
    pages = max(1, min(int(data.get("pages", 1)), 5))

    if provider not in {"remotive", "google_jobs", "all"}:
        return jsonify({
            "status": "failure",
            "message": "provider must be one of: remotive, google_jobs, all",
            "timestamp": now_iso()
        }), 400

    try:
        normalized_jobs: list[dict] = []
        source_counts: dict[str, int] = {}

        if provider in {"remotive", "all"}:
            remotive_raw = fetch_remotive_jobs(limit=limit)
            remotive_jobs = [normalize_remotive_job(job) for job in remotive_raw]
            normalized_jobs.extend(remotive_jobs)
            source_counts["Remotive"] = len(remotive_jobs)

        if provider in {"google_jobs", "all"}:
            if not job_type and not location:
                return jsonify({
                    "status": "failure",
                    "message": "Google Jobs ingestion needs job_type or location",
                    "timestamp": now_iso()
                }), 400

            google_raw = fetch_google_jobs(
                job_type=job_type,
                location=location,
                remote_only=remote_only,
                pages=pages,
            )
            google_jobs = [normalize_google_job(job) for job in google_raw]
            normalized_jobs.extend(google_jobs)
            source_counts["GoogleJobs"] = len(google_jobs)

        summary = ingest_normalized_jobs(normalized_jobs, write_json=write_json)

        return jsonify({
            "status": "success",
            "provider": provider,
            "source_counts": source_counts,
            **summary,
            "timestamp": now_iso()
        }), 200

    except Exception as e:
        return jsonify({
            "status": "failure",
            "message": str(e),
            "timestamp": now_iso()
        }), 500


@jobs_bp.route("/jobs", methods=["GET"])
def list_jobs():
    limit = request.args.get("limit", default=25, type=int)
    limit = max(1, min(limit, 200))

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute(
            """
            select
                id,
                external_id,
                source,
                title,
                company,
                coalesce(location_normalized, location) as location,
                location_raw,
                is_remote,
                remote_type,
                coalesce(category, schedule_type) as category,
                coalesce(apply_url, url) as url,
                salary_text,
                posted_at_text,
                ingested_at,
                last_seen_at
            from public.job_postings
            order by ingested_at desc
            limit %s
            """,
            (limit,),
        )
        rows = cur.fetchall()

        return jsonify({
            "status": "success",
            "count": len(rows),
            "jobs": rows,
            "timestamp": now_iso()
        }), 200

    finally:
        cur.close()
        conn.close()


@jobs_bp.route("/fetch-jobs", methods=["GET"])
def fetch_jobs_removed():
    return jsonify({
        "status": "failure",
        "message": "Endpoint removed. Use POST /jobs/ingest instead.",
        "timestamp": now_iso()
    }), 410