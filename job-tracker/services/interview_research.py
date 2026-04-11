from __future__ import annotations

from typing import Any

from serpapi import GoogleSearch

from config import INTERVIEW_RESEARCH_MAX_RESULTS, SERPAPI_API_KEY


def _clean(value: Any) -> str:
    return str(value or "").strip()


def build_interview_queries(job: dict) -> list[str]:
    title = _clean(job.get("title")) or "this role"
    company = _clean(job.get("company")) or "this company"

    return [
        f'"{company}" "{title}" interview questions',
        f'"{company}" "{title}" interview process',
        f'"{company}" candidate interview experience',
        f'"{company}" interview prep {title}',
    ]


def _fallback_context(profile: dict, job: dict, queries: list[str], reason: str) -> dict:
    preferences = profile.get("preferences_json") or {}

    return {
        "mode": "fallback",
        "reason": reason,
        "queries": queries,
        "sources": [],
        "context": {
            "company": job.get("company"),
            "title": job.get("title"),
            "location": job.get("location"),
            "category": job.get("category"),
            "job_description": job.get("description"),
            "candidate_resume": profile.get("resume_text"),
            "candidate_preferences": preferences,
        },
    }


def gather_interview_research(
    profile: dict,
    job: dict,
    max_results: int | None = None,
) -> dict:
    queries = build_interview_queries(job)
    max_results = max_results or INTERVIEW_RESEARCH_MAX_RESULTS

    if not SERPAPI_API_KEY:
        return _fallback_context(
            profile=profile,
            job=job,
            queries=queries,
            reason="SERPAPI_API_KEY is not set; using job/profile context only.",
        )

    sources: list[dict] = []
    seen_urls: set[str] = set()

    try:
        for query in queries:
            if len(sources) >= max_results:
                break

            search = GoogleSearch({
                "engine": "google",
                "q": query,
                "api_key": SERPAPI_API_KEY,
                "num": min(10, max_results),
            })
            results = search.get_dict()

            for rank, item in enumerate(results.get("organic_results", []), start=1):
                if len(sources) >= max_results:
                    break

                url = item.get("link")
                if not url or url in seen_urls:
                    continue

                seen_urls.add(url)
                sources.append({
                    "source_type": "web",
                    "title": item.get("title"),
                    "url": url,
                    "snippet": item.get("snippet"),
                    "query": query,
                    "rank": rank,
                    "raw_json": {
                        "position": item.get("position"),
                        "displayed_link": item.get("displayed_link"),
                        "source": item.get("source"),
                    },
                })

        return {
            "mode": "web" if sources else "web_empty",
            "reason": None if sources else "SerpAPI returned no organic results.",
            "queries": queries,
            "sources": sources,
            "context": {
                "company": job.get("company"),
                "title": job.get("title"),
                "location": job.get("location"),
                "category": job.get("category"),
                "job_description": job.get("description"),
                "candidate_resume": profile.get("resume_text"),
                "candidate_preferences": profile.get("preferences_json") or {},
            },
        }

    except Exception as exc:
        return _fallback_context(
            profile=profile,
            job=job,
            queries=queries,
            reason=f"Interview web research failed: {str(exc)}",
        )
