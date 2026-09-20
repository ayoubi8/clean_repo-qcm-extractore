-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- USERS table
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    is_approved BOOLEAN DEFAULT FALSE,
    is_admin BOOLEAN DEFAULT FALSE,
    api_key TEXT DEFAULT '',
    allowed_models JSONB DEFAULT '{}',
    legacy_hash BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- PROJECTS table
CREATE TABLE IF NOT EXISTS projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    pdf_storage_path TEXT DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, name)
);

-- Activity tracking (S-2)
ALTER TABLE projects ADD COLUMN IF NOT EXISTS last_activity_at TIMESTAMPTZ DEFAULT NOW();
CREATE INDEX IF NOT EXISTS projects_user_activity_idx
  ON projects (user_id, last_activity_at DESC);

-- PROJECTS LIST SPEEDUP: total_tokens now lives in the projects table so
-- GET /projects is a single SQL query (no per-project Storage downloads of
-- total_costs.json). tokens_synced marks rows already migrated from the
-- Storage total_costs.json blobs — the backend backfills unsynced rows once
-- at startup, so no old data is lost.
ALTER TABLE projects ADD COLUMN IF NOT EXISTS total_tokens BIGINT DEFAULT 0;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS tokens_synced BOOLEAN DEFAULT FALSE;

-- AUTO-RUN BATCH (Phase 1): marks how a project was created.
-- 'manual' = New Project / single-file Drive import (default);
-- 'autorun' = created by an Auto Run batch (AR_ prefix + batch manifest).
-- GET /projects returns it so Resume Project can render the AUTO badge.
-- _select_project_rows degrades gracefully (drops the column) when this
-- migration has not been applied yet.
ALTER TABLE projects ADD COLUMN IF NOT EXISTS origin VARCHAR(64) DEFAULT 'manual';


-- STEP_HISTORY table
CREATE TABLE IF NOT EXISTS step_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    step_number TEXT NOT NULL,
    run_at TIMESTAMPTZ DEFAULT NOW(),
    badge TEXT DEFAULT 'success',
    duration_seconds FLOAT DEFAULT 0,
    metadata JSONB DEFAULT '{}'
);

-- COSTS table
CREATE TABLE IF NOT EXISTS costs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    step_number TEXT NOT NULL,
    cost_usd FLOAT DEFAULT 0,
    tokens INTEGER DEFAULT 0,
    recorded_at TIMESTAMPTZ DEFAULT NOW()
);

-- REFRESH_TOKENS table
CREATE TABLE IF NOT EXISTS refresh_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    token_hash TEXT UNIQUE NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked BOOLEAN DEFAULT FALSE
);


-- STEP_RESULTS table (PERSISTENCE_FIX_PLAN PR-1)
-- Artifact metadata for each step run. Binary bytes stay in Supabase Storage
-- (storage_prefix points at {uid}/{project}/{folder}); this row stores the
-- file manifest + small payload summary so list/status are a single SELECT
-- and survive container restarts even when local FS is wiped.
CREATE TABLE IF NOT EXISTS step_results (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    step_number     TEXT NOT NULL,
    run_id          TEXT NOT NULL,
    badge           TEXT DEFAULT 'success',
    duration_seconds FLOAT DEFAULT 0,
    storage_prefix  TEXT NOT NULL,
    file_manifest   JSONB DEFAULT '[]',
    payload         JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (project_id, step_number, run_id)
);

CREATE INDEX IF NOT EXISTS step_results_proj_step_idx
    ON step_results (project_id, step_number, created_at DESC);


-- REFERENCE_DATABASES table (Step 8 — QCM reference matching)
-- Stores metadata for each user-uploaded reference database file.
-- The file bytes themselves live in Supabase Storage at storage_path
-- ({uid}/ref_dbs/{filename}); this row holds the searchable metadata
-- so list/upload/delete are single SELECTs and survive container restarts.
CREATE TABLE IF NOT EXISTS reference_databases (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    filename      TEXT NOT NULL,
    storage_path  TEXT NOT NULL,
    size_bytes    INTEGER DEFAULT 0,
    line_count    INTEGER DEFAULT 0,
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, filename)
);

CREATE INDEX IF NOT EXISTS reference_databases_user_idx
    ON reference_databases (user_id, created_at DESC);


-- Row Level Security
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE step_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE costs ENABLE ROW LEVEL SECURITY;
ALTER TABLE refresh_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE step_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE reference_databases ENABLE ROW LEVEL SECURITY;

-- Note: Frontend never touches Supabase directly, all access goes through FastAPI 
-- which uses the service role key (bypasses RLS). 
-- This keeps the backend as the single source of truth.
