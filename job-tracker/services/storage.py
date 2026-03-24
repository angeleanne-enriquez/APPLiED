import json
from supabase import create_client
from config import SUPABASE_URL, SUPABASE_SECRET_KEY, SUPABASE_BUCKET


def get_storage_client():
    if not SUPABASE_URL or not SUPABASE_SECRET_KEY:
        raise ValueError("SUPABASE_URL and SUPABASE_SECRET_KEY must be set")
    return create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)


def build_draft_paths(user_id: str, job_posting_id: str) -> dict:
    base = f"{user_id}/{job_posting_id}"
    return {
        "resume_path": f"{base}/resume.md",
        "cover_letter_path": f"{base}/cover_letter.md",
        "manifest_path": f"{base}/application.json",
    }


def upload_text(path: str, content: str, mime_type: str) -> str:
    client = get_storage_client()
    payload = content.encode("utf-8")

    client.storage.from_(SUPABASE_BUCKET).upload(
        path=path,
        file=payload,
        file_options={
            "content-type": mime_type,
            "upsert": "true",
        },
    )
    return f"{SUPABASE_BUCKET}/{path}"


def save_application_packet(
    user_id: str,
    job_posting_id: str,
    resume_markdown: str,
    cover_letter_markdown: str,
    manifest: dict,
) -> dict:
    paths = build_draft_paths(user_id, job_posting_id)

    resume_full_path = upload_text(
        paths["resume_path"],
        resume_markdown,
        "text/markdown",
    )
    cover_letter_full_path = upload_text(
        paths["cover_letter_path"],
        cover_letter_markdown,
        "text/markdown",
    )

    manifest = {
        **manifest,
        "files": {
            "resume_path": resume_full_path,
            "cover_letter_path": cover_letter_full_path,
        },
    }

    manifest_full_path = upload_text(
        paths["manifest_path"],
        json.dumps(manifest, indent=2),
        "application/json",
    )

    return {
        "resume_path": resume_full_path,
        "cover_letter_path": cover_letter_full_path,
        "manifest_path": manifest_full_path,
        "manifest": manifest,
    }