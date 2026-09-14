-- =====================================================================
-- TELEMETRY — step_call_logs table (apply once in the Supabase SQL Editor)
-- Idempotent (CREATE ... IF NOT EXISTS). Safe to re-run.
-- =====================================================================
--
-- WHERE TO APPLY:
--   Supabase dashboard → SQL Editor (>_ icon) → + New query
--   → paste this file → Run (▶).
--
-- WHAT IT STORES:
--   One row per unit of work, created in two phases:
--     1) a `running` row is INSERTed immediately BEFORE each unit starts
--      (a step/sub-step execution, or a single AI call incl. its retries)
--   2) the row is UPDATED with the outcome (response/error/tokens/duration)
--      immediately AFTER it finishes.
--   A row whose status stays 'running' with an old started_at is a stuck
--   unit — visible in SQL directly, no cron needed.
--
-- ROLLBACK (if ever needed):
--   DROP TABLE IF EXISTS step_call_logs;
-- =====================================================================

CREATE TABLE IF NOT EXISTS step_call_logs (
    id                 BIGSERIAL PRIMARY KEY,
    project_id         UUID REFERENCES projects(id) ON DELETE CASCADE,
    user_id            TEXT,
    project_name       TEXT,
    run_id             TEXT NOT NULL,             -- same convention as step_results: "YYYY-MM-DDThh-mm-ss"
    step_number        TEXT NOT NULL,             -- "1", "1.5", "2", "6", "7", "8", "8-export"
    sub_step           TEXT,                      -- hint | cas_split | step3 | cc_checker | build | extraction | ...
    item_ref           TEXT,                      -- page/chunk/QCM scope: "chunk_3 (pages 5-6)", "page_7", "q_12"...
    kind               TEXT NOT NULL DEFAULT 'ai_call'
                       CHECK (kind IN ('step_run', 'ai_call')),
    model              TEXT,                      -- model that ACTUALLY answered (post-fallback)
    request_payload    TEXT,                      -- prompt (truncated to ~20KB; full copy offloaded to Storage)
    response_payload   TEXT,                      -- model output (same truncation rule)
    storage_ref        TEXT,                      -- Storage path of the untruncated payload, if offloaded
    status             TEXT NOT NULL DEFAULT 'running'
                       CHECK (status IN ('running', 'success', 'error', 'cancelled', 'timeout')),
    error_message      TEXT,
    started_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at       TIMESTAMPTZ,               -- NULL while in-flight / stuck
    duration_seconds   NUMERIC(12,2),
    prompt_tokens      INTEGER,
    completion_tokens  INTEGER,
    cost_usd           NUMERIC(10,6),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Main debugging query paths:
--   per project/run/step trace:      index 1
--   "what is stuck / what failed":   index 2
CREATE INDEX IF NOT EXISTS step_call_logs_trace_idx
    ON step_call_logs (project_id, run_id, step_number, created_at DESC);

CREATE INDEX IF NOT EXISTS step_call_logs_status_idx
    ON step_call_logs (status, started_at DESC);

ALTER TABLE step_call_logs ENABLE ROW LEVEL SECURITY;
