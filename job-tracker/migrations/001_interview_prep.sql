CREATE EXTENSION IF NOT EXISTS pgcrypto;

DO $$
DECLARE
    status_type_name TEXT;
BEGIN
    SELECT format('%I.%I', n.nspname, t.typname)
    INTO status_type_name
    FROM pg_type t
    JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE t.typname = 'application_status'
    ORDER BY CASE WHEN n.nspname = 'public' THEN 0 ELSE 1 END
    LIMIT 1;

    IF status_type_name IS NOT NULL THEN
        EXECUTE format(
            'ALTER TYPE %s ADD VALUE IF NOT EXISTS %L',
            status_type_name,
            'interviewing'
        );
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS interview_prep_briefs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    job_posting_id UUID NOT NULL REFERENCES job_postings(id) ON DELETE CASCADE,
    application_id UUID REFERENCES applications(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'generated',
    research_mode TEXT NOT NULL DEFAULT 'fallback',
    brief_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT interview_prep_briefs_status_check CHECK (status IN ('generated', 'failed')),
    UNIQUE (user_id, job_posting_id)
);

CREATE TABLE IF NOT EXISTS interview_prep_sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    job_posting_id UUID NOT NULL REFERENCES job_postings(id) ON DELETE CASCADE,
    brief_id UUID REFERENCES interview_prep_briefs(id) ON DELETE CASCADE,
    source_key TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'web',
    title TEXT,
    url TEXT,
    snippet TEXT,
    query TEXT,
    rank INTEGER,
    raw_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS interview_practice_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    job_posting_id UUID NOT NULL REFERENCES job_postings(id) ON DELETE CASCADE,
    brief_id UUID REFERENCES interview_prep_briefs(id) ON DELETE SET NULL,
    mode TEXT NOT NULL DEFAULT 'chat',
    status TEXT NOT NULL DEFAULT 'active',
    transcript_text TEXT NOT NULL DEFAULT '',
    feedback_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at TIMESTAMPTZ,
    CONSTRAINT interview_practice_sessions_status_check CHECK (status IN ('active', 'completed'))
);

CREATE TABLE IF NOT EXISTS interview_session_turns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES interview_practice_sessions(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    job_posting_id UUID NOT NULL REFERENCES job_postings(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'interviewer', 'system', 'feedback')),
    content TEXT NOT NULL,
    transcript_chunk TEXT,
    feedback_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    turn_index INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (session_id, turn_index)
);

CREATE INDEX IF NOT EXISTS idx_interview_prep_briefs_user_job
    ON interview_prep_briefs(user_id, job_posting_id);

CREATE INDEX IF NOT EXISTS idx_interview_prep_sources_user_job
    ON interview_prep_sources(user_id, job_posting_id);

CREATE INDEX IF NOT EXISTS idx_interview_practice_sessions_user_job
    ON interview_practice_sessions(user_id, job_posting_id);

CREATE INDEX IF NOT EXISTS idx_interview_session_turns_session
    ON interview_session_turns(session_id, turn_index);

ALTER TABLE interview_prep_sources
    ADD COLUMN IF NOT EXISTS source_key TEXT;

UPDATE interview_prep_sources
SET source_key = encode(
    digest(
        COALESCE(
            NULLIF(LOWER(TRIM(url)), ''),
            CONCAT_WS('|', source_type, title, snippet, query, rank::TEXT)
        ),
        'sha256'
    ),
    'hex'
)
WHERE source_key IS NULL OR source_key = '';

DELETE FROM interview_prep_sources
WHERE id IN (
    SELECT id
    FROM (
        SELECT
            id,
            ROW_NUMBER() OVER (
                PARTITION BY user_id, job_posting_id, source_key
                ORDER BY created_at DESC, id
            ) AS duplicate_rank
        FROM interview_prep_sources
    ) ranked_sources
    WHERE duplicate_rank > 1
);

ALTER TABLE interview_prep_sources
    ALTER COLUMN source_key SET NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_interview_prep_sources_source_key
    ON interview_prep_sources(user_id, job_posting_id, source_key);

ALTER TABLE interview_prep_sources
    DROP CONSTRAINT IF EXISTS interview_prep_sources_user_id_job_posting_id_url_key;

UPDATE interview_prep_briefs
SET status = 'generated'
WHERE status NOT IN ('generated', 'failed');

UPDATE interview_practice_sessions
SET status = 'active'
WHERE status NOT IN ('active', 'completed');

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'interview_prep_briefs_status_check'
          AND conrelid = 'interview_prep_briefs'::regclass
    ) THEN
        ALTER TABLE interview_prep_briefs
            ADD CONSTRAINT interview_prep_briefs_status_check
            CHECK (status IN ('generated', 'failed'));
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'interview_practice_sessions_status_check'
          AND conrelid = 'interview_practice_sessions'::regclass
    ) THEN
        ALTER TABLE interview_practice_sessions
            ADD CONSTRAINT interview_practice_sessions_status_check
            CHECK (status IN ('active', 'completed'));
    END IF;
END $$;
