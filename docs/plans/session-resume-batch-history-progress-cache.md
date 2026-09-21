# Session Resume — Batch History, Live Progress Fix, Step Caching, Costs

Date: 2026-09-20/21 · Branch `main` · Head at session end: `35ca0fe` (local repo, pushed to all remotes)

Plan reference: docs/plans/autorun-batch-history-progress-cache-plan.md (Phases 1–7 all DONE,
phase notes + decisions baked in; optional Phase 4b "clickable AUTO badge" NOT scheduled)

---

## 1. What was built (4 commits: `05c6275` → `9e5e354` → `2f57384` → `35ca0fe`)

### Phase 1 — Durable per-step progress (api/autorun_batch.py)
- Per-project `steps` map in `batch.json`: `{sid: {state: running|done|error|cancelled|skipped,
  updated_at, error_message?}}` recorded at every step start/success/failure/cancel.
- Steps already done before a run/retry re-entry recorded once as `skipped` (cache-hit flag;
  earlier `done` states preserved during retries).
- `write_manifest` failures no longer silent: `write_errors` counter + `last_write_error`
  written back into the manifest (best-effort re-persist).
- `merge_live_status()`: GET /autorun/batches/{id} merges in-memory job_manager OVER manifest
  steps (live wins in-process; manifest survives restarts; all BATCH_SEQUENCE keys emitted
  uniformly with `idle` fillers; response-only).
- Startup resume + `resume_batch` pop stale `running` step records on relaunch.
- Fixed latent `TypeError`: `_mutate_project(..., error_message=)` kwarg didn't exist.

### Phase 2 — Polling that cannot die (frontend)
- Poll loop owned by `batchStore` (module-level self-scheduling `setTimeout` chain):
  `startPolling(batchId)` / `stopPolling()`; BatchView only mounts/unmounts it.
- Failure backoff 3s → 6s → 12s cap + "Reconnecting…" hint; stops ONLY on terminal manifest
  state; restartable (`BatchDetailPanel` retry calls `startPolling` again).
- Chips (`stepChipStatus`) read the merged `p.steps` map; new `cached` chip style (secondary
  colors, `cached` icon) for skipped steps; hidden-helper (1.5/1.6) errors surface on chip 1.
- Header "updated Ns ago" (1s ticker); types: `BatchStepState` / `BatchSteps` on
  `BatchProjectEntry`.

### Phase 3 — Batch history backend
- `list_user_batches(uid, limit≤50)`: local `{uid}/_batches/*` + Storage fallback, summary
  rows only (no `config_snapshot` leak), newest first, preview names capped `+N more`.
- `_batch_summary` + `batch_is_live` (parent task OR any project busy) → zombie manifests
  reported `interrupted`.
- `resume_batch` guards: batch-not-found → already-running → stale-running pre-flight flip →
  nothing-to-resume → `run_batch_task`.
- Routes: `GET /autorun/batches` (60/min), `POST /autorun/batches/{id}/resume` (404/409).

### Phase 4 — Recent batches block (frontend)
- Top of the Auto Run wizard Source stage: date · N PDFs · preview names · state chip ·
  click → `/batch/:id` (via `onStarted`); interrupted rows get Resume; Load more (20-steps)
  + refresh; silent hide on fetch failure. BatchView `arrow_back` header button.
- `BatchSummary` type; `fetchBatches`, `resumeBatch` in lib/api.ts.

### Phase 5 — Server step-results cache (api/step_cache.py NEW)
- Process TTL cache keyed `(uid, project, step_id)`: `{status, output_exists, files}`.
  Single knob `STEP_CACHE_TTL` (default 180, clamp 120–300) — server and client share it
  (exposed via `GET /env/step-models → features.step_cache_ttl`); TTL is only the safety net,
  correctness comes from explicit invalidation.
- Wired: `/status`, `/output`, delete route, `_run_step_task` (invalidate at start; re-cache
  terminal in inner `finally`; invalidate in setup-cancel/error), `_sync_step_from_sheets_svc`
  (invalidates step + sibling — covers manual sync AND the pre-run hook), `retry_project`,
  `resume_batch`, `first_not_done_step` (warm = dict hits instead of SQL round-trips).
- `.env.example`: `STEP_CACHE_TTL=180` (add as HF secret optionally).

### Phase 6 — Client cache + Expand all + sync-replace
- `frontend/src/store/outputsCache.ts` NEW (zustand, TTL from the server knob):
  `ensureStepOutput` (cached-first — fresh entry = NO request), `reloadStepOutput`
  (fetch + REPLACE), `reloadAfterSync` (step AND sibling — sync propagates both ways),
  `removeCachedFile`, `getCachedOutput/useOutputsCache`.
- `BatchDetailPanel` renders straight from the cache (expand/collapse of the same folder =
  zero requests within the TTL window); per-row sync → refetch+REPLACE (step 2 ↔ 6); delete
  → cache-aware; "previous run / cached" note when files predate the batch.
- BatchView: **Expand all / Collapse all** toggle (only for batches with >1 PDF).
- `batchStore.batchCache`: last-good snapshot per batchId → instant `/batch/:id` revisits.
- `OutputViewer` (normal runs) wired to the same cache.

### Phase 7 — Regression + push
- Tests F1–F16 green (added F11–F16; `tests/test_autorun_batch.py` script-runner style).
- `npm run build` green. Deploy routine (unchanged): `git push space main`; git-archive
  `frontend/` → clone of qcm-extractor-frontend → commit → push (Vercel); origin backup.

---

## 2. First real run (2026-09-21) — bugfixes in `9e5e354`

- **Endless poll flood**: zombie batch (manifest running/pending, nothing live) kept the 3s
  poll alive from every tab. Fixes:
  - `GET /autorun/batches/{id}` now reconciles: state running/pending + `batch_is_live` false
    → served as `interrupted` (`state_was` preserved) → frontend stops polling and shows an
    Interrupted banner with **Resume batch**.
  - `batchActive` treats `interrupted` as inactive; `STATE_CHIP.interrupted` added.
  - Poll loop: unchanged-response backoff 6s → 12s → 30s → 60s cap; any change snaps back
    to 3s (stuck views no longer flood the Space log).

## 3. Batch cost display (`2f57384`)

- `GET /autorun/batches/{id}/costs`: per-PDF `{cost, tokens}` + batch total (SQL `costs`
  rows first → `total_costs.json` blob fallback; shared `_cost_summary_from_rows` helper).
- BatchFolderCard: cost badge per PDF; BatchView header: aggregate chip; refetch once per
  project-set/state change (never per poll). F17 test.

## 4. Costs topbar button made work-everywhere (`35ca0fe`)

- The TopBar "Costs" button previously froze on an eternal skeleton when NO project was
  active. Now:
  - with an active project → unchanged per-model/per-step breakdown + save;
  - no active project → `GET /costs/all` (SQL projects + chunked costs query, local blob
    fallback): all-projects table with AUTO badge on `AR_` rows + grand total.

---

## 5. How to use (operator)

- **Old sessions**: Switch Project → Auto Run → "Recent batches" → click a row → `/batch/:id`;
  `expand_all` opens every folder (cached = instant); Interrupted → Resume; arrow_back back.
- **Costs**: batch header total + per-PDF badges; TopBar Costs = global usage; AR project
  pipeline = full breakdown. After a Space rebuild: Ctrl+Shift+R · wait ~2 min ·
  `STEP_CACHE_TTL=180` secret optional.

## 6. Tests & state

- `tests/test_autorun_batch.py` F1–F17 all green (scan/engine/naming/retry/resume/
  progress/merge/write-errors/history/resume/cache/batch-costs); `npm run build` green.
- Still open: **Phase 4b only** — clickable AUTO badge (needs `projects.batch_id` migration).
- If an auto-run still yields no outputs after Resume: grab the Space log section around
  `[AUTORUN-BATCH] project AR_... failed:` — it names the failing call.
