# Auto Run — Batch History, Live-Progress Fix, Step-Results Caching

Status: **PLAN ONLY — REVISED v2 (all 5 open questions resolved — decisions baked in below)**
Date: 2026-09-20 · Branch `main` · Latest commits `5930c32` / `5a95cf4`
Predecessor plans: docs/plans/autorun-batch-plan.md (implemented), docs/plans/session-resume-autorun-batch.md (session summary)

Scope — three asks from the live session, delivered as **Phases 0 → 7** (+ optional 4b):

1. **A · Batch history** — "I ran a batch on 3 PDFs yesterday; I want to come back and open that
   old auto-run session from the Auto Run UI." Today `/batch/:id` only opens if you still know
   the URL; nothing lists past batches.
2. **B · Frozen progress** — "Auto Run works, but the batch view is stuck on *step 1 running*
   and never advances." The run itself completes (projects show up done in Resume Project);
   only the live view freezes.
3. **C · Caching system** — cache the *checking of step results* for both Auto Run batches and
   the normal project run, so status/output lookups stop re-hitting SQL/Storage, repeated
   expand/collapse of folders is free, and already-done steps are detected instantly.

---

## 1. Resolved Decisions (was Open Questions)

| # | Decision (resolved) |
|---|---|
| Q-A1 | **History entry point = a "Recent batches" block inside the Auto Run wizard** (Source stage). NO fourth launcher tab — history is secondary to starting a new run. |
| Q-A2 | **Clickable AUTO badge in Resume Project = OPTIONAL Phase 4b.** The `projects.batch_id` migration + `GET /projects` field are handled there if/when 4b is scheduled. The wizard History block already solves the core requirement. |
| Q-B1 | **Poll transport = fixed 3s polling** (HF-compatible, no new infra). SSE can be added later behind the same route if ever needed. |
| Q-C1 | **One simple cache per layer with a single TTL of ~180s** (2–5 min band, env-tunable `STEP_CACHE_TTL`, one knob for server + client). Expand-in-place semantics: cached-first on expand → no request; expired → fetch fresh; **Expand all** supported; after an XLSX Sync (automatic or manual) completes → fetch the updated version and **REPLACE** the cached entry, so future expansions show the synced version. NO extra caching mechanisms, no ETag layering, no second cache. |
| Q-C2 | **No ETag / If-None-Match.** The in-process cache + explicit invalidation is sufficient; HTTP-caching headers would only add CDN/Vercel complexity. |

**Cache correctness principle (Q-C1):** the TTL is only a *safety net*. Correctness comes from
**explicit invalidation** on every mutation path (run start/finish, output delete, sheets sync).
That is what makes a long 180s TTL safe — nothing can change on disk/SQL without the cache
hearing about it.

---

## 2. Current Architecture Audit (anchors — what exists today)

| Concern | Where | Behavior today |
|---|---|---|
| Batch manifest | `api/autorun_batch.py:84-157` | `batch.json` dual-written (local FS + Storage) at `{uid}/_batches/{id}/`; `_mutate_project` writes only `state` / `error_step` / `current_step` |
| Per-project progress | `api/autorun_batch.py:130-145` | `current_step` written **at step START only** — no per-step completion is ever recorded |
| Batch progress route | `api/real_api.py:4270-4282` | `GET /autorun/batches/{id}` → manifest + `live_status` from in-memory `job_manager` (lost on restart) |
| Batch view polling | `frontend/src/pages/BatchView.tsx:36-54` | 3s `setInterval`; **`active = batchActive(manifest) && !error`** — one failed poll clears the interval and **nothing ever restarts it** |
| Step chips / cards | `batchStore.ts:56-71`, `BatchFolderCard.tsx` | chip = live_status only; card label `Running · step ${current_step}` from manifest |
| Batch detail outputs | `BatchDetailPanel.tsx:42-55` | 3 × `fetchStepOutput` on EVERY expand — no cache; `onSynced` reloads all 3 steps |
| Normal-run status | `api/real_api.py:2804-2833` | job_manager → SQL `step_results` → Storage recursive walk; no cache |
| Normal-run outputs | `api/real_api.py:3077-3142` | local FS → SQL `file_manifest` → Storage walk; no cache |
| Normal-run frontend | `frontend/src/pages/Pipeline.tsx:23-35` | one `getStepStatus` per step on mount only |
| Done-ness (autorun) | `api/autorun_batch.py:301-326` | `first_not_done_step` = up to 5 SQL lookups + local FS fallback, per PDF, per start/retry/resume |
| Existing caches | `project_manager.py:155-170` (30s `/projects` TTL) · `modules/utils/ocr_cache.py` (vision OCR) · SQL `step_results` rows (durable, w/ `file_manifest`) | primitives to build on — nothing exists for status/output responses |
| Sheets sync | `_pre_run_sheets_sync` hook (real_api.py:2267-2272, automatic before-run) + `syncFromSheets` route (manual) | sync mutates step 2/6 outputs on disk/Storage |
| Startup auto-resume | `api/autorun_batch.py:554-574` | relaunches pending/running batches; running→pending |
| Project origin | `projects.origin` DB column + AUTO badge (`ResumeProjectModal.tsx:112-120`) | `batch_id` exists in `project.json` (`_mark_project_autorun`) but NOT in `GET /projects` |

---

## 3. Problem B Diagnosis — why the view freezes on "step 1 running"

Ranked root-cause candidates (confirm in Phase 0 before fixing):

| # | Candidate | Mechanism | Likelihood |
|---|---|---|---|
| B-1 | **Polling dies permanently on one transient error** (BatchView.tsx:46-54) | HF Space cold-start / 5xx / token-refresh blip → poll throws → `error` set → `active` false → `clearInterval` → **no restart path**; UI freezes at the last good snapshot (typically "step 1 running") while the batch finishes fine on the backend | **High** |
| B-2 | **Progress state is not durable** | `current_step` advances only while the engine mutates the manifest; chips depend on in-memory `job_manager`. A container restart mid-batch (free HF Spaces sleep) empties job_manager → chips go stale/idle until resume; a silently failed manifest write (both writes are soft `try/except print`, autorun_batch.py:84-98) leaves the manifest stale | Medium |
| B-3 | Multiple uvicorn workers | Dockerfile CMD is single-process (Dockerfile:38) — **ruled out** unless the deployment changed | Low |

All three mechanisms get fixed regardless (Phases 1–2), so the fix does not depend on which one fired.

---

## 4. Phases

Dependency graph: **1 → 2** (frontend reads the new manifest fields) · **3 → 4** ·
**1 → 5/6** (skipped/cached flags come from the manifest `steps` map) · 4b needs only 3.
Phases 1–2 and 3–4 are otherwise independent and can be built/verified in parallel.

---

### Phase 0 · Diagnose (recommended, ~½ day, no code)

**Goal:** confirm which candidate freezes the view, so Phase 2's fix is provably the right one.

- Run a real batch (HF Space backend + Vercel frontend) with the batch view open and the browser
  Network tab recording `GET /autorun/batches/{id}`: do `current_step` / `live_status` actually
  advance on the wire?
- Force the B-1 repro: stop/restart the Space mid-batch (or throttle the network to make one
  poll fail) → observe the UI freeze at the last snapshot while the interval is dead.
- Record findings + screenshots at the bottom of this doc.

**Exit criteria:** root cause confirmed (expected: B-1 with B-2 as contributing factor).

---

### Phase 1 · Durable per-step progress (backend — fixes B-2 + B-3) — **DONE 2026-09-20**

**Goal:** the batch manifest becomes the single durable progress record; the live route merges
in-memory state over it.

**Changes — `api/autorun_batch.py`:**

- `_run_one_project` writes, per project entry, a `steps` map (extend `_mutate_project`):
  `{"1": {"state": "running|done|error|skipped", "updated_at": iso, "error_message"?: str}, …}`
  — written at step start, step success, and step failure.
- When `first_not_done_step` skips an already-done step, that step is recorded as
  `state: "skipped"` (the cache-hit flag the UI shows in Phase 2/6).
- `write_manifest` increments a `write_errors` counter (+ last error string) **into the manifest
  itself** when a local/Storage write fails — failures become visible instead of silent.

**Changes — `api/real_api.py` (route `GET /autorun/batches/{id}`):**

- Merge `job_manager` live status OVER manifest `steps` (live wins while in-memory; manifest
  survives restarts). Response stays backward-compatible — `steps` is additive.

**Acceptance:**

- Restart the container mid-batch → reload `/batch/:id` → per-step progress still true.
- A scripted run where a manifest write fails → `write_errors` visible in the GET response.

_Implementation notes (2026-09-20): `merge_live_status()` emits every BATCH_SEQUENCE key per
project (uniform `{state, updated_at}` shape — `idle` filler entries), so the Phase 2 frontend
can render chips without key-guards. Also fixed a latent `TypeError` in `_run_one_project`'s
exception handler: it passed `error_message=` to `_mutate_project` before that kwarg existed —
now accepted and stored on the project entry `error_message`. Startup resume pops stale
`steps[*].state=="running"` entries when flipping projects running→pending. Tests F11 / F12 /
F15 added and green (F1–F10 unregressed)._

---

### Phase 2 · Polling that cannot die (frontend — fixes B-1) — **DONE 2026-09-20**

**Goal:** the batch view never freezes; a dead feed is visible and self-heals.

**Changes — `frontend/src/pages/BatchView.tsx` + `store/batchStore.ts`:**

- Replace `setInterval` + one-way clear with a **self-scheduling `setTimeout` chain**:
  - keep polling while `batchActive(manifest)` is true **even when `error` is set**;
  - on error, back off 3s → 6s → 12s (cap 12s) and show a small "reconnecting…" hint;
  - stop ONLY on a terminal manifest state (`done` / `done_with_errors` / all projects terminal);
  - if a later successful poll shows activity again (e.g. after a retry/resume), polling resumes.
- Chips and card labels read the **merged** step states from Phase 1 (manifest `steps` +
  `live_status`), including `skipped` → renders as a **"cached"** chip style (check icon +
  `cached` material symbol, secondary color).
- "Last updated Ns ago" indicator in the header (from each successful poll) — a stalled feed
  becomes visible to the operator.

**Acceptance:**

- Kill/restart the Space mid-batch → view shows "reconnecting…", then resumes advancing — never freezes.
- One failed poll never stops the feed (throttle the network to verify).
- Pre-done steps show `cached` chips instead of re-running silently.

_Implementation notes (2026-09-20): the poll loop lives in `batchStore` (`startPolling /
stopPolling` + module-owned self-scheduling `setTimeout` chain; `runTick` checks state AFTER
each fetch and re-arms only from the store, so React remounts can't spawn double loops).
The old `setInterval` + one-way clear in BatchView is gone; BatchView now only calls
`startPolling(batchId)` on mount / `stopPolling()` on unmount. Error→backoff keeps polling
unless the last-known manifest is already terminal (first-load failures keep retrying —
`manifest` is null there). "Reconnecting — showing the last received update" hint renders when
`error && manifest`; the big error box is now only for `!manifest`. Chips (`stepChipStatus`)
read the merged `p.steps` map from Phase 1 with a `cached` chip style (secondary colors,
`cached` icon) and error detection for the hidden 1.5/1.6 helpers. `BatchDetailPanel` retry
restarts polling via `startPolling(batchId)`. Header shows a 1s "updated Ns ago" ticker.
Types: `BatchStepState`/`BatchSteps` added, `steps` on `BatchProjectEntry`. `npm run build`
green; pre-existing repo-wide tsc noise unrelated (vite build remains the gate)._

---

### Phase 3 · Batch history backend (Feature A) — **DONE 2026-09-20**

**Goal:** list the user's past batches (summary shape) + relaunch interrupted ones.

**Changes — `api/autorun_batch.py`:**

- `list_user_batches(uid, limit=20) -> list[dict]` — enumerate `{uid}/_batches/*/batch.json`
  local-first, Storage fallback (`storage_client.list_files(f"{uid}/_batches/")`), same merge
  pattern as `_iterate_manifests` (autorun_batch.py:524-551) scoped to one user. Summaries only:

```json
{
  "batch_id": "batch-20260919-…-ab12cd",
  "created_at": "…ISO…",
  "updated_at": "…ISO…",
  "source": "drive" | "upload",
  "state": "done" | "running" | "done_with_errors" | "interrupted",
  "counts": {"total": 3, "done": 2, "error": 1, "pending": 0},
  "preview_names": ["AR_math", "AR_physique", "+1 more"]
}
```

- **Display-state reconciliation:** manifest `running` + no live `_BATCH_TASKS` entry + no busy
  `job_manager` keys for its projects → reported as `interrupted` (crash where startup resume
  couldn't relaunch, e.g. flag off).
- `resume_batch(uid, batch_id)` — thin wrapper over `run_batch_task` (already double-start safe).

**Changes — `api/real_api.py`:**

| Route | Behavior |
|---|---|
| `GET /autorun/batches?limit=20` | `list_user_batches(user["id"])`; flag-gated 404 like the others; light rate limit |
| `POST /autorun/batches/{batch_id}/resume` | relaunch an `interrupted` batch → `{started: bool, reason?: str}` (409 already-live / nothing pending) |

**Acceptance:** `curl GET /autorun/batches` returns yesterday's batch summary with correct counts.

_Implementation notes (2026-09-20): `list_user_batches` enumerates `{uid}/_batches/*` local +
Storage fallback (same `list_files("")` merge pattern as `_iterate_manifests`, scoped to the
user), summaries only (`config_snapshot` never leaked, preview names capped at 3 + "+N more"),
sorted newest-first, limit clamp 1–50. `interrupted` = manifest running/pending AND neither
`_BATCH_TASKS[batch_id]` live nor any of its projects busy in `job_manager` (`_batch_is_live`,
which also covers per-PDF retries). `resume_batch` guards: batch-not-found → already-running →
pre-flight flip of stale `running`→`pending` + stale step-record cleanup (same as startup
resume) → nothing-to-resume (terminal) → `run_batch_task`. Routes: `GET /autorun/batches`
(60/min rate limit, flag-gated) and `POST /autorun/batches/{id}/resume` (404 unknown, 409
already-running / nothing-to-resume). Tests F13 / F14 added and green; F1–F15 unregressed;
FastAPI route registration verified._

---

### Phase 4 · Batch history frontend — wizard block (Feature A, Q-A1) — **DONE 2026-09-20**

**Goal:** open old auto-run sessions from the Auto Run tab.

**Changes:**

- `frontend/src/lib/api.ts` — `fetchBatches(limit?)`, `resumeBatch(batchId)`; `BatchSummary`
  type in `types/index.ts` (`BatchProjectEntry` also gains `steps?: Record<string, {state, updated_at?}>`).
- **"Recent batches" block at the TOP of the Auto Run wizard's Source stage**
  (`AutoRunWizard.tsx`, stage `'source'`): compact rows — date, N PDFs, state chip (reuse
  `STATE_CHIP` styles from BatchView), preview names; click → `navigate(\`/batch/${id}\`)`.
  `interrupted` rows show a **Resume** button (calls `resumeBatch`, then navigates).
  Hidden/collapsed when empty; "Load more" when > 20.
- `/batch/:batchId` already renders non-active batches (grid works, polling stops immediately);
  add a small back affordance to the launcher.

**Acceptance:** launcher → Auto Run → see the old 3-PDF batch → click → its results render.

_Implementation notes (2026-09-20): `fetchBatches(limit)` + `resumeBatch(batchId)` in
`lib/api.ts` (fetchWithRefresh-wrapped), `BatchSummary`/`BatchSummaryCounts` types. The
"Recent batches" block sits at the top of the wizard's Source stage: rows = date + N PDFs +
preview names (`shortDate`), mini state chip mirroring BatchView's STATE_CHIP, reload /
Load-more (steps of 20), refetch on every wizard mount (tab re-selection re-renders fresh).
Rows navigate through the existing `onStarted` callback (closes launcher → `/batch/:id`);
`interrupted` rows get a **Resume** button (stopPropagation, spinner, 409/404 surfaced as an
error toast; success → open the cockpit). Failure to load history silently hides the block
(history is optional, never blocks starting a run). BatchView gained an `arrow_back` circle
header button (`navigate(-1)`). `npm run build` green._

---

### Phase 4b · (OPTIONAL, Q-A2) Clickable AUTO badge in Resume Project

**Only if/when scheduled** — the wizard block (Phase 4) already solves the core need.

- `api/migration.sql`: `ALTER TABLE projects ADD COLUMN IF NOT EXISTS batch_id VARCHAR(80);`
  (+ write it in `_mark_project_autorun`, alongside the existing `origin` update).
- `api/project_manager.py`: select + return `batch_id` (same missing-column graceful drop as
  `origin`).
- `ResumeProjectModal.tsx`: AUTO badge becomes a button → `navigate(\`/batch/${p.batch_id}\`)`
  when `batch_id` is present; badge stays static otherwise (legacy rows).

---

### Phase 5 · Server step-results cache (Feature C1 — Q-C1 semantics) — **DONE 2026-09-20**

**Goal:** *checking* results (status, output manifest, done-ness) becomes a cache hit; the
expensive SQL/Storage walks happen once per ~3 minutes at most.

**New `api/step_cache.py`** — one process-level TTL cache, key `(uid, project, step_id)`:

```python
{
  "status": "idle|running|done|error|stopped|cancelled",
  "output_exists": bool,
  "files": [...],          # /output route shape
  "badge_stats": {...},
  "expires": ts,           # now + STEP_CACHE_TTL (default 180s, band 120–300)
}
```

- **TTL = 180s default**, env `STEP_CACHE_TTL` (validated to the 120–300s band). ONE knob —
  server and client use the same value.
- **Explicit invalidation on every mutation path** (this is what makes 180s safe):
  - `_run_step_task` start (running) and its `finally` (terminal) — covers every run, incl. autorun;
  - `delete_step_output_file` route (real_api.py:3145);
  - **sheets sync** — `syncFromSheets` route (manual) AND `_pre_run_sheets_sync` (automatic
    before-run) invalidate the affected step 2/6 entries, so the *next* `/output` fetch returns
    the synced version, never the stale one;
  - per-PDF retry / batch resume invalidate that project's steps.
- **Wired into:**
  1. `GET /projects/{name}/steps/{id}/status`
  2. `GET /projects/{name}/steps/{id}/output`
  3. `first_not_done_step` (autorun engine — batch start / retry / startup resume become dict hits)
  4. `GET /autorun/batches/{id}` step-done merge (Phase 1)
- Storage-walk fallback (legacy projects, no SQL row) also lands in the cache — the most
  expensive path becomes rare.

**Acceptance:** repeat `/status` + `/output` calls within TTL are dict hits (SQL mock call count
drops to zero in tests); `first_not_done_step` warm = no SQL.

_Implementation notes (2026-09-20): new `api/step_cache.py` — process-level TTL cache keyed
`(uid, project, step_id)` with `get/put(merge)/invalidate(step|project|user)/clear` and
`ttl_seconds()` reading `STEP_CACHE_TTL` clamped to 120–300 (default 180). Wired:
`GET /status` (cache in front of SQL/Storage; mem-known results re-cache with a fresh
`step_output_exists`), `GET /output` (cached manifest via `_sort_output_file_items`), the
delete route, `_run_step_task` (invalidate at start; re-cache terminal in the inner `finally`;
invalidate in both outer setup-cancel/error handlers), `_sync_step_from_sheets_svc` success
(invalidates the synced step AND its sibling — one choke point covering the manual route and
the pre-run hook), `retry_project` + `resume_batch` (per-project wipe). `first_not_done_step`
goes through the cache (warm = dict hits per step). `GET /env/step-models` now also returns
`features.step_cache_ttl` — the single source for the Phase 6 client TTL. `.env.example`
gains `STEP_CACHE_TTL=180`. Test F16 added (TTL band, status/output/entry cache hits,
put-merge, step/project/user invalidation); F6 updated with explicit cache wipes for its
mutated fake rows; all F1–F16 green._

---

### Phase 6 · Client output cache + Expand all + sync-replace (Feature C — Q-C1 contract) — **DONE 2026-09-20**

**Goal:** the exact expand-in-place behavior requested, with ONE simple client cache.

**New `frontend/src/store/outputsCache.ts`** — zustand store, key `project|step` →
`{ files, ts }`, TTL = the same 180s (read from the env-driven value exposed by
`GET /env/step-models` or a constant mirrored from `.env.example` — one source of truth).

**Behavior contract (verbatim from the resolved decision):**

1. Expand a folder → entry fresh (< TTL) → **serve cached, send no request**.
2. Expand after expiry → fetch fresh, store.
3. **"Expand all / Collapse all" toggle** in the BatchView header — expands every PDF's detail
   panel in the grid; cached entries render instantly, only expired ones fetch (requests
   naturally spread; no extra batching machinery).
4. **After a Sync completes (manual `cloud_sync` button via `syncFromSheets`, or an automatic
   sync detected by the sync-before-run flow)** → the client **fetches the updated version and
   REPLACES the cached entry** (replace, not just invalidate — the next expand must still be
   instant AND show the synced data). `BatchDetailPanel`'s `onSynced` currently reloads all 3
   steps; it becomes: refetch only the affected step → replace its entry.
   Server-side, the sync routes already invalidated the entry (Phase 5), so the refetch is
   guaranteed fresh.
5. Future expansions of that folder → the **new synced version**, never the old one.

Also in this phase:

- `batchStore` keeps the last `BatchProgress` per batchId (`batchCache`) so revisiting
  `/batch/:id` renders instantly while the first poll is in flight.
- `BatchDetailPanel` reads from `outputsCache` (kills the 3-fetch-per-expand); `OutputViewer`
  (normal project run) uses the same store.
- "Results from a previous run (cached)" one-line note in a step section when every file's
  `created_at` predates the batch `created_at` — cheap client-side check on already-fetched data.
- Normal-run status refresh (`Pipeline.tsx`) unchanged (server cache already makes it cheap);
  refetch statuses when a project that was touched by batch activity is opened from Resume.

**Acceptance (manual):** expand/collapse a folder repeatedly → exactly ONE request per TTL
window; expand all → only expired entries fetch; sync an XLSX → the panel shows the synced
version immediately and the next expand is instant with the new data.

_Implementation notes (2026-09-20): new `frontend/src/store/outputsCache.ts` — zustand entries
`project|step → {files, ts}`, TTL bootstrapped once from `GET /env/step-models
(features.step_cache_ttl)`, default 180 until answered. API: `ensureStepOutput`
(cached-first — rule 1-2), `reloadStepOutput` (fetch + REPLACE), `reloadAfterSync` (step **and
sibling** refetch — syncs propagate edits both ways), `removeCachedFile` (delete updates the
cached entry), `getCachedOutput/useOutputsCache` for rendering. `BatchDetailPanel` now renders
straight from the cache entries (`ensureStepOutput` per step on expand → repeat
expand/collapse of the same folder sends ZERO requests within the window); `onSynced` →
`reloadAfterSync` (replaces step 2's AND step 6's entries); "previous run" note via
"cached" chip when every file's created_at predates the batch; retry re-loads all cached
output sections. `BatchView` gained an expand_all/collapse_all header toggle (sentinel
`expandedProject = 'ALL'`, only shown for batches with >1 PDF). `batchStore` gained
`batchCache` (last-good manifest snapshot per batchId, seeded on revisit so `/batch/:id`
renders instantly while the first poll replaces it). `OutputViewer` (normal run) uses the
same cache: `ensureStepOutput` on load, `reloadStepOutput` after sync and after the
running→done auto-refresh, `removeCachedFile` on delete. `npm run build` green (114 modules)._

---

### Phase 7 · Regression, build, push — **DONE 2026-09-20 (commit `05c6275`)**

- Backend tests (below) + `npm run build` green.
- Push targets (unchanged from session-resume-autorun-batch.md §4): `git push space main`
  (HF backend) · git-archive → frontend repo → Vercel.
- Operator checklist: `.env.example` / HF secrets gain `STEP_CACHE_TTL=180`; migration for 4b
  only if scheduled.

_Done 2026-09-20: tests F1–F16 green · `npm run build` green (114 modules) · committed and
pushed: `space` (HF backend `5a95cf4..05c6275`, Docker rebuild), frontend mirror commit
`e96614a` → `frontend-repo` (Vercel auto-deploy), full-repo backup `origin` synced
(`da3633d..05c6275`). HF secrets: add `STEP_CACHE_TTL=180` (deploy also works on the code
default without it)._

---

## 5. File-Change Map

| File | Phase | Change |
|---|---|---|
| `api/autorun_batch.py` | 1, 3 | per-step `steps` map + `skipped` flags + `write_errors`; `list_user_batches`, `resume_batch`, display-state reconciliation |
| `api/real_api.py` | 1, 3, 5 | merge live-over-manifest in batch GET; `GET /autorun/batches`, `POST …/resume`; wire `step_cache` into `/status`, `/output`, run start/finally, delete + sheets-sync invalidation |
| `api/step_cache.py` (new) | 5 | TTL cache + invalidation API |
| `api/migration.sql` | 4b only | `projects.batch_id` column |
| `api/project_manager.py` | 4b only | select + return `batch_id` |
| `frontend/src/pages/BatchView.tsx` | 2, 6 | self-scheduling poll + backoff + reconnect hint + "updated Ns ago"; Expand all / Collapse all toggle |
| `frontend/src/store/batchStore.ts` | 2, 6 | poll-loop ownership + `batchCache`; merged chip states incl. `cached`/`skipped` |
| `frontend/src/components/batch/BatchFolderCard.tsx` | 2 | `cached` chip style; label from merged steps |
| `frontend/src/components/batch/BatchDetailPanel.tsx` | 6 | read from `outputsCache`; sync → refetch-affected-step-and-replace; "cached results" note |
| `frontend/src/components/launcher/autorun-wizard/AutoRunWizard.tsx` | 4 | "Recent batches" block (list + Resume for interrupted) |
| `frontend/src/lib/api.ts` / `types/index.ts` | 4, 6 | `fetchBatches`, `resumeBatch`, `BatchSummary`, `steps` on `BatchProjectEntry` |
| `frontend/src/store/outputsCache.ts` (new) | 6 | client cache per Q-C1 contract |
| `.env.example` | 5, 7 | `STEP_CACHE_TTL=180` |

---

## 6. Tests

**Backend (extend `tests/test_autorun_batch.py`, F-numbering continues):**

- F11 manifest records per-step `steps` states across a scripted `_run_step_task` sequence
  (reuse the F8 fake-runner pattern), incl. `skipped` for pre-done steps;
- F12 `GET /autorun/batches/{id}` merge: live job_manager wins; empty job_manager falls back
  to manifest `steps`;
- F13 `list_user_batches`: local + Storage-only manifests, summary counts, `interrupted`
  reconciliation, ordering + limit;
- F14 resume route guards (409 already-live, 404 unknown, relaunch after interrupt);
- F15 `write_manifest` failure → `write_errors` counter increments, manifest still served;
- F16 `step_cache`: hit/miss/TTL (180s)/explicit invalidation on run-start, run-finally,
  delete, sheets sync (manual + before-run); `/status` + `/output` + `first_not_done_step`
  served from cache — SQL mock call counts drop to zero within TTL.

**Frontend:** `npm run build` (no test harness in the repo today) + manual QA checklist:

- [ ] Old batch visible in Auto Run wizard → opens → outputs render, no error state;
- [ ] Live batch: chips advance 1 → 2 → 6; pre-done steps show `cached` chips;
- [ ] Space restart mid-batch: "reconnecting…" then progress resumes; final state correct;
- [ ] One failed poll never freezes the view (throttle network);
- [ ] Expand/collapse a folder repeatedly → one request per TTL window (Network tab);
- [ ] Expand all → only expired entries fetch; all panels render;
- [ ] Sync an XLSX (manual + automatic) → panel shows synced version; next expand instant + new;
- [ ] Normal project run unchanged: statuses, outputs, WS log, stop/cancel as before;
- [ ] Flag off (`AUTORUN_BATCH_ENABLED=false`) → tab + history hidden, routes 404.

---

## 7. Phase 0 findings (fill in during diagnosis)

_Pending._
