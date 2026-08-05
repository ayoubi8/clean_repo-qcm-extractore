-- =====================================================================
-- PERSISTENCE_FIX_PLAN — apply once in the Supabase SQL Editor.
-- Idempotent (CREATE ... IF NOT EXISTS). Safe to re-run.
-- =====================================================================
--
-- WHERE TO APPLY:
--   Supabase dashboard → your project → SQL Editor (>_ icon) → + New query
--   → paste this file → Run (▶).
--
-- WHAT IT DOES:
--   Adds the `step_results` table that PR-1's _record_step_result helper
--   writes to after every step run. Stores artifact metadata (file manifest
--   + small payload) so PR-2/PR-3 read endpoints + PR-4 backfill can
--   reconstruct the project/state listing without walking Storage.
--
-- ROLLBACK (if ever needed):
--   DROP TABLE IF EXISTS step_results;   -- FK cascades, drops the index+RLS too.
-- =====================================================================


-- STEP_RESULTS table (PERSISTENCE_FIX_PLAN PR-1)
-- Stores artifact metadata for each step run. Binary bytes stay in
-- Supabase Storage (storage_prefix points at {uid}/{project}/{folder});
-- this row stores the file manifest + small payload summary so list/status
-- work after a container restart even when the local FS is wiped.
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

ALTER TABLE step_results ENABLE ROW LEVEL SECURITY;