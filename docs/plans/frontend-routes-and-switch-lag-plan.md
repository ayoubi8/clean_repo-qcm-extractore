# Plan — Split the website into real pages + fix the "Switch Project" lag

Status: PLAN ONLY (no code) · 2026-11-21 · branch `fix/run-isolation-openrouter-client`

Goal:
1. Replace the single `/pipeline` screen (with the project in hidden browser
   state and a modal on top) by **several real pages**, each with its own URL.
2. Explain and remove the lag seen when clicking **Switch Project**.

---

## 1. What happens today (verified in code)

### 1.1 One page, the project lives in browser storage

| Fact | Where |
|---|---|
| Only 4 app routes: `/`, `/pipeline`, `/batch/:batchId`, `/settings` (+ `/admin`, `/login`, `/register`). | `frontend/src/App.tsx:52-58` |
| The active project is NOT in the URL. It is a zustand value persisted in `localStorage` (`qcm-app-store`). | `store/appStore.ts` |
| "Switch Project" does not navigate: it sets `activeProject = null` and opens a full-screen modal (`ProjectLauncher`) on top of whatever page is mounted. | `components/shell/TopBar.tsx:52`, `App.tsx:62` |
| New Project / Resume Project / Auto Run are **tabs inside that modal**, not pages. | `components/launcher/ProjectLauncher.tsx` |
| Every step (1…8), its config, its logs and its outputs are inside `/pipeline`; the selected step is store state. | `pages/Pipeline.tsx`, `store/pipelineStore.ts` |
| Google Sheets OAuth returns to `/pipeline?sheets_pending=1&project=…&step=…`. | `api/real_api.py:929-933` |
| One JS bundle (≈467 kB), no route-level code splitting. | `vite build` output |

Consequences: no deep link to a project or a step, the browser Back button
does not undo "Switch Project", a refresh depends on what localStorage holds,
two tabs share/overwrite the same "active project".

### 1.2 Why Switch Project lags, and why "Auto Run" pops in after a few seconds

Sequence when you click **Switch Project**:

1. `setActiveProject(null)` → the whole shell re-renders with no project
   (TopBar shows "No Project Selected", Pipeline page effects reset).
2. `ProjectLauncher` mounts. Its tab bar shows **New Project · Resume Project**
   only.
3. On mount it calls `GET /env/step-models` (`ProjectLauncher.tsx:44-48`) just to
   read `features.autorun_batch`. The **Auto Run tab is hidden until that answer
   arrives** (`showAutorunTab = autorunEnabled === true`). This is the
   "it shows Auto mode after some seconds" effect: the tab appears late and the
   tab bar jumps.
4. The New Project tab mounts `TagSelector`, which calls `GET /env/tags`
   (`TagSelector.tsx:19`, a Supabase query). Opening Resume calls
   `GET /projects` (`ResumeProjectModal.tsx:36`).
5. Nothing is cached on the client: **every** opening of the launcher repeats
   these calls (the modal is unmounted on close, its state is lost, the tab
   resets to "New Project").

Why each of those calls is slow:

| # | Cause | Evidence | Effect |
|---|---|---|---|
| L1 | Backend is ONE uvicorn process on a Hugging Face Space (`Dockerfile`: `uvicorn real_api:app`, no workers). The pipeline (OCR images, openpyxl, JSON, LLM threads) runs **inside the same process**. | `Dockerfile:38`, `_run_step_task` threads | While any run/batch is active, every API request competes for the same CPU/GIL → even `/env/step-models` (tiny) can take seconds. |
| L2 | `get_current_user` is `async def` but calls `find_user_by_id` → a **blocking** Supabase HTTP request on cache miss (cache TTL 60 s). | `api/auth.py:302-339`, `:148-158` | Once a minute per user, a request **blocks the event loop**: every concurrent request and every log WebSocket freezes for that round-trip. |
| L3 | Network distance: browser (Vercel) → HF Space → Supabase. Every launcher open = 2-3 sequential-ish round-trips. | `VITE_API_BASE_URL=https://ayoubi8-qcm-extractor.hf.space` | 0.3-1.5 s each when idle; much more under L1. A sleeping Space adds a cold start (tens of seconds). |
| L4 | Project activation fires **one `/status` request per step** (≈10) in parallel. | `pages/Pipeline.tsx:22-33` | 10 authenticated requests per project switch, each passing through L1/L2. |
| L5 | No client cache (features, models, tags, project list). | all `useEffect` fetches | The same data is fetched again on every open. |
| L6 | Whole shell re-renders on `activeProject = null`. | `appStore.setActiveProject(null)` | Minor CPU cost, but it is what makes the screen "flash" before the modal content is ready. |

**How to confirm before fixing (Phase 0):** browser DevTools → Network, click
Switch Project, note the duration of `/env/step-models`, `/env/tags`,
`/projects` — once with no run active, once during a run. Add a
`Server-Timing` header (auth time, handler time) so the split between network,
auth and handler is visible.

---

## 2. Target: a site of real pages

### 2.1 URL map

| URL | Page | Replaces |
|---|---|---|
| `/` | Dashboard (recent projects, running batches, costs) | same |
| `/projects` | Project list: search, tags, open, delete | Launcher → **Resume Project** tab |
| `/projects/new` | Upload a PDF / Drive link + tags | Launcher → **New Project** tab |
| `/projects/:name` | Project overview: steps with status, last outputs, quick actions | — (redirects to the first unfinished step) |
| `/projects/:name/steps/:stepId` | One step: config panel + run button + live log | `/pipeline` with `activeStepId` in the store |
| `/projects/:name/outputs` | All result files of the project + **Needs review** list + MBset import file | outputs scattered in each step |
| `/projects/:name/autorun` | Auto Run for this project (start/end step) | `AutoRunPanel` modal inside `/pipeline` |
| `/autorun/new` | Batch wizard (many PDFs) | Launcher → **Auto Run** tab |
| `/batches` | Batch history list | "Recent batches" inside the launcher |
| `/batch/:batchId` | Batch detail | same (kept) |
| `/settings/models`, `/settings/keys`, `/settings/tags` | Settings split in sub-pages | `/settings` single page |
| `/admin` | Admin | same |
| `/pipeline` | **Compatibility redirect** → `/projects/:lastProject/steps/1` (or `/projects`), keeps `?sheets_pending=…` handling | old route |

Rules:
- **The URL is the source of truth for the project and the step.** The store
  only caches data for the project in the URL. `lastActiveProject` stays, only
  to make `/pipeline` and "Continue where I left off" work.
- **Switch Project = `navigate('/projects')`.** No modal, no
  `activeProject = null`. Back returns to the project you came from.
- A project name in the URL is `encodeURIComponent`-ed. Names with `/` are
  impossible (API already keys by name).
- Two browser tabs can show two projects.

### 2.2 Layout

```
<AppShell>                      Sidebar + TopBar, never unmounted
  /projects/:name/*  → <ProjectLayout>   loads the project once, shows its name,
                                          step rail on the left
        steps/:stepId → <StepPage>       config + run + log + step outputs
        outputs       → <OutputsPage>
        autorun       → <ProjectAutoRunPage>
```
`ProjectLayout` fetches the project + **all step statuses in one call**
(see 3.2) and keeps them in a per-project cache; switching steps inside a
project makes no new status request.

### 2.3 What happens to the launcher modal

Removed as a page container. Optionally kept later as a **quick switcher**
(Ctrl/Cmd + K) that only lists cached projects and calls `navigate()` — it
never fetches on open and never clears the current project.

---

## 3. Data layer (removes L4/L5)

### 3.1 One client cache

Add TanStack Query (or a small SWR-style cache in zustand if no new
dependency is wanted). Keys and lifetimes:

| Key | Endpoint | staleTime | Invalidated by |
|---|---|---|---|
| `bootstrap` | `GET /bootstrap` (3.2) | 10 min | Settings save, login |
| `projects` | `GET /projects` | 30 s (server already caches 30 s) | create / delete / rename / batch finished |
| `project:{name}` | `GET /projects/{name}/overview` (3.2) | 5 s while a step runs, else 60 s | run start/finish, sync-from-sheets, delete file |
| `outputs:{name}:{step}` | existing output list | already `outputsCache.ts` | same as today |
| `batches` | existing | 10 s while running | batch events |

Pages render cached data instantly and refresh in the background → Switch
Project shows the list immediately.

### 3.2 New backend endpoints (read-only, additive)

| Endpoint | Returns | Replaces |
|---|---|---|
| `GET /bootstrap` | user, feature flags (`autorun_batch`, cache TTL), step models, tag vocabulary | `/env/step-models` + `/env/tags` + `/auth/me` fetched separately |
| `GET /projects/{name}/overview` | project row + every step's `status` + `output_exists` + last run time | ≈10 × `/steps/{id}/status` |

Old endpoints stay (backward compatible); the frontend stops calling them on
hot paths.

---

## 4. Backend fixes for the lag (L1/L2)

| # | Fix | Risk |
|---|---|---|
| B1 | `get_current_user` and `require_admin` become plain `def` (FastAPI then runs them in the thread pool), or wrap the Supabase lookup in `await asyncio.to_thread(...)`. Same for every `async def` endpoint that does blocking Supabase/Storage/file work (`stop_step`, `step8_merge_outputs`, `autorun_*`, uploads). | Low |
| B2 | `Server-Timing` middleware (auth ms, handler ms) + a slow-request log line (> 1 s). | None |
| B3 | Keep the HF Space awake (scheduled ping) or show a "server waking up" banner when `/bootstrap` takes > 3 s. | None |
| B4 | **Move pipeline work out of the API process**: a separate worker process consuming a job table/queue (Supabase table or Redis), API only enqueues + streams logs. Logs already go through a sink → write them to the job store, WebSocket reads from there. | High — separate project, after phases 1-3 prove the gain. In-memory job state (`job_manager`) must move to the store first. |

B1-B3 remove most of the visible lag; B4 removes it during heavy runs.

---

## 5. Code splitting

- `React.lazy` per page (`Dashboard`, `ProjectLayout`, `StepPage`, `OutputsPage`,
  `BatchView`, `AutoRunWizard`, `Settings`, `AdminPanel`).
- Monaco and the Step 8 panels load only on their pages.
- Target: first load < 200 kB JS; navigation between pages never blocks on a
  network call (cached data first).

---

## 6. Phases (each shippable, old URLs keep working)

| Phase | Content | Done when |
|---|---|---|
| 0 | Measure: DevTools timings + B2 `Server-Timing`. Record before numbers (idle / during a run). | Numbers written in this file |
| 1 | Quick wins, no route change: **S1 path-traversal fix (§10.3, security — do first)**, B1 (blocking auth), launcher shows the Auto Run tab immediately (feature flag cached at app start), cache `/env/tags` + `/projects`, launcher keeps its last tab. | Switch Project opens with all 3 tabs at once; no request on the 2nd open; `../` filenames rejected with 400 |
| 2 | Routes: `/projects`, `/projects/new`, `/autorun/new`, `/batches`; Switch Project navigates; launcher modal removed (or quick switcher). `/pipeline` kept as is. | Back button works; deep link to the project list |
| 3 | Project pages: `ProjectLayout`, `/projects/:name/steps/:stepId`, `/projects/:name/outputs`, `/projects/:name/autorun`; `GET /projects/{name}/overview`; `/pipeline` becomes a redirect (keeps `sheets_pending`). Update `FRONTEND_URL` OAuth return to the step URL. | One status request per project; refresh keeps the page |
| **R** | **Results remake (§10-§11)**: results service + endpoints, Results page `/projects/:name/outputs`, QCM table with review filters, in-app xlsx preview, compact step card, shared file row for batch view. Needs Phase 3 routes. | §11.6 targets met |
| 4 | `GET /bootstrap`, TanStack Query everywhere, lazy routes, settings sub-pages. | First load and page switches meet §5 targets |
| 5 | B4 worker process (separate plan). | API latency during a run ≈ idle latency |

**Status 2026-11-21 — phases 0, 1, 2 implemented (uncommitted):**
- Phase 0: `api/server_timing.py` (pure ASGI) adds `Server-Timing: app;dur=…` +
  `Timing-Allow-Origin: *`, logs `[SLOW]` above `SLOW_REQUEST_MS` (1000). The
  before/after numbers still have to be read on the deployed site (DevTools).
- Phase 1: S1 — `api/output_paths.py` (`STEP_FOLDERS`, `safe_output_path`,
  `safe_history_path`) used by the 6 file endpoints. B1 — `get_current_user` is a
  plain `def`. Client cache `frontend/src/lib/cache.ts`: step models / feature
  flags (5 min, warmed at login), tags (10 min), project list (15 s,
  background refresh); invalidated on save / create / delete / upload,
  cleared on logout.
- Phase 2: pages `/projects`, `/projects/new`, `/autorun/new`, `/batches`
  (`pages/ProjectsPages.tsx`, `components/hub/ProjectHub.tsx`); launcher pop-up
  removed; Switch Project → `/projects` (current project kept, Back works);
  sidebar gains Projects + Batches; `/pipeline` without a project → `/projects`
  (OAuth `?project=` return still restored first).
- Tests: `tests/test_output_paths_and_timing.py`; `test_persistence_pr3` now
  also patches `output_paths.Path`.

**Status 2026-11-22 — phases 3, R, 4 implemented (uncommitted); 5 not started:**
- Phase 3: `GET /projects/{name}/overview` (every step status in one call,
  probed in parallel, one failing probe → `idle`). Routes `/projects/:name`
  (→ first unfinished step), `/steps/:stepId`, `/outputs`, `/autorun` (drawer)
  under `components/project/ProjectLayout.tsx` (resolves the project from the
  URL, one overview request per project visit, re-attaches a running step's
  live log after a refresh). Clicking a step navigates. `/pipeline` is a
  redirect (`pages/ProjectWorkspace.tsx`) that accepts the OAuth query
  (`?sheets_pending=1&project=…&step=…&filename=…`) and forwards it to the step
  page. The backend OAuth return keeps pointing at `/pipeline` so it works
  with both the old and the new frontend.
- Phase R: `api/results.py` (classify, newest count-named workbook = result,
  older ones listed apart, QCM counters/rows filtered + paged on the server,
  LRU by file version, 64 KB text chunks, openpyxl read-only xlsx table, flag
  labels) + endpoints `/results`, `/results/qcms`, `/results/{step}/files|preview|table|history`
  (ETag → 304). Frontend: Results page (summary tiles, MBset/workbook buttons,
  questions table + drawer, files per step, working files paged, history on
  demand), `StepResultsCard` under the config panel, one `ResultFileRow`
  (pipeline + Results + batch view; in-app xlsx/text preview), shared
  `lib/fileActions.ts`, global toaster. `OutputViewer` and `StepFileRow` removed.
  Not done: stable workbook names (U8) — would change the tested
  `result_xlsx_name` contract and the Sheets reuse; older copies are shown
  apart instead. Native token downloads (S4) not done; downloads still use blobs.
- Phase 4: `GET /bootstrap` (user + step models/flags + tags; frontend falls
  back to `/env/step-models` on an older backend), lazy page chunks (first
  load 512 kB → 241 kB, 72 kB gzip), `/settings/keys|models|batch`.
  Q3: kept the hand-written `lib/cache.ts` (same contract: TTL, dedupe,
  background refresh, invalidation) instead of adding TanStack Query.
- Tests: `tests/test_results_and_overview.py` (14).
- Deploy order: backend first (new endpoints), then the frontend.

---

## 7. Things that must not break

- Google Sheets OAuth return (`/pipeline?sheets_pending=1…`) — handled by the
  `/pipeline` redirect page until the backend points to the new URL.
- Batch deep links `/batch/:id` and the AUTO badge links.
- Persisted stores (`qcm-app-store`, pipeline panel configs) — add a version
  migration; panel configs stay global (not per project) unless decided.
- Running-step log WebSocket: must reconnect when you leave and come back to
  the step page (today it lives as long as `/pipeline` is mounted).
- Vercel SPA rewrite (`frontend/vercel.json`) already serves `index.html` for
  every path → nested URLs work without config change.

---

## 8. Test plan

- Router tests (Vitest + React Testing Library): every URL renders its page,
  `/pipeline` redirects, `?sheets_pending` still triggers the Sheets flow.
- Switch Project: navigates to `/projects`, Back returns to the previous step
  URL, no `/env/step-models` request on second visit (mocked fetch counter).
- Backend: `get_current_user` no longer blocks the loop (test: a slow mocked
  Supabase + a concurrent `/health` request answers immediately);
  `/projects/{name}/overview` equals the union of the old per-step statuses.
- Manual: Phase 0 timings repeated after each phase.

---

## 9. Decisions needed

| # | Question | Default proposal |
|---|---|---|
| Q1 | Keep a quick-switch popup (Ctrl+K) or only the `/projects` page? | Page now, popup later |
| Q2 | Step config panels: one config per project, or global as today? | Global (as today) |
| Q3 | Add TanStack Query (new dependency) or hand-written cache? | TanStack Query |
| Q4 | Do B4 (worker process) now or after phases 1-4? | After |
| Q5 | Results remake: keep "Open in Google Sheets" as the main way to view an xlsx, or the in-app preview first? | In-app preview first, Sheets for editing |

---

## 10. How "show results" works today (analysis)

### 10.1 The flow

```
ConfigPanel (bottom of the selected step)            ConfigPanel.tsx:279
 └─ OutputViewer(project, step)                       OutputViewer.tsx
     ├─ mount → ensureStepOutput()  → GET /steps/{id}/output        (cached, TTL 180 s)
     ├─ mount → fetch history        → GET /steps/{id}/history       (ALWAYS, not cached)
     ├─ click 👁 on .json/.txt       → GET /steps/{id}/output/{file} → whole file as one JSON string
     ├─ click ↗ on .xlsx             → POST /open-sheets (upload to Google Drive) → new tab
     ├─ click ↗ on other files       → GET /view|/download (blob fetched into memory, then opened)
     ├─ click 🗑                      → DELETE /steps/{id}/output/{file}
     ├─ click ☁ (steps 2/6)          → POST /sync-from-sheets
     └─ tab becomes visible again    → auto sync-from-sheets (if a sheet was opened)
Batch view: BatchDetailPanel + StepFileRow — a second, hand-copied version of the same rows.
```

Backend (`api/real_api.py:3311-3700`):
- `/output` lists the step folder: local disk first, then `step_results.file_manifest`, then a recursive Storage walk. A server cache (`step_cache`) sits in front.
- `/output/{file}` returns the text content.
- `/view` and `/download` serve the file, or redirect to a Supabase signed URL.
- `/history` walks the current folder AND every `_history/step{N}/run` folder.

### 10.2 Problems for the user

| # | Problem | Where |
|---|---|---|
| U1 | Results are a **flat dump of every file** in the step folder. Step 1 shows hundreds of `page_N.txt`; Step 3 mixes per-page JSON with the merged result. The file you actually want (`*_qcms_*.xlsx`, `mbset_import_*.xlsx`) is lost in a box limited to `max-h-80`. | `get_step_output_files` (rglob), `OutputViewer` list |
| U2 | Results show **one step at a time**, at the bottom of a config panel, under the run settings. There is no project-level "what did I get?" view. | `ConfigPanel.tsx:279` |
| U3 | **An xlsx can't be viewed in the app.** The only way to open one is uploading it to Google Sheets (needs Google sign-in, creates a Drive file every time); otherwise download it. | `openInSheets` |
| U4 | JSON preview = the whole file as raw text in one `<code>` block. A 2-5 MB `all_qcms.json` freezes the tab; no search, no table, no paging. "Needs review" must parse the whole file in the browser. | `openPreview`, `flaggedQcms` |
| U5 | No numbers: how many QCMs, how many corrected, how many flagged, whether the MBset file is ready. You must open files to find out. | — |
| U6 | Errors use `window.alert`; sync messages are toasts inside one step's viewer only. | `OutputViewer.tsx` |
| U7 | "Current Output" appears twice (list + history "current"); history labels are folder names; no compare between runs. | `/history` |
| U8 | Old count-named workbooks pile up (`120_qcms_x.xlsx`, `118_qcms_x.xlsx`…) because the name changes with the count. | `output_naming.result_xlsx_name` |

### 10.3 Problems for the system

| # | Problem | Where |
|---|---|---|
| **S1** | **Security: path traversal.** `/view`, `/download`, `/history/{run}/{file}` and `/open-sheets` join the URL filename to the user's folder without any check. `/output/{file}` only checks the start of the path string, before resolving `..`, so it doesn't stop it either. A filename like `../../<other-user-id>/<project>/step6_corrections/x.json` reads another user's file. Only `DELETE` resolves and checks. | `real_api.py:3459-3700` |
| S2 | The step → folder map (`_SFMAP`) is copy-pasted in 7 endpoints; safety checks differ per endpoint. | same |
| S3 | Every viewer mount sends 2 requests (list + history). History is never cached and, on Storage, lists each run separately (N+1 calls). | `OutputViewer.loadAll`, `/history` |
| S4 | Previews ship full files; xlsx/blob opens load the whole file into browser memory before showing it. | `/output/{file}`, `fetchAuthenticatedBlobUrl` |
| S5 | The cache TTL comes from `/env/step-models` (yet another call), and only the list is cached, not history or previews. | `outputsCache.ts` |
| S6 | Two UIs (pipeline + batch) implement the same rows, Sheets flow and sync handling separately, so a bug fixed in one stays in the other. | `OutputViewer.tsx`, `StepFileRow.tsx` |
| S7 | Sorting happens twice (server, and on every client render); timestamps are server-local strings without a time zone. | both |

---

## 11. Phase R — Results remake

### 11.1 Principles

1. **Results first, files second.** The page answers "what did I get, what
   must I check, what do I upload" before showing any file.
2. **The server shapes the data.** The browser never downloads a multi-MB
   JSON to show 20 rows.
3. **One results service, one file row component**, used by the pipeline,
   the project Results page and the batch view.
4. Everything is cached by the data layer (§3), with explicit invalidation on
   run end, sync and delete.

### 11.2 Backend — `api/results.py` (new module, routes mounted in `real_api`)

| Piece | What it does |
|---|---|
| `STEP_FOLDERS` | The single step → folder map (replaces the 7 copies). |
| `safe_path(user, project, step, rel)` | Resolves the path and refuses anything outside `/app/output/{user}/{project}/{folder}` (and the matching Storage prefix). Used by EVERY file endpoint — fixes S1. |
| `classify(file)` | Tags each file as one of: |
| | • `result`: final workbook, `merged_qcms.json`, `corrected_qcms.json`, `final_qcms.json` |
| | • `mbset_import` |
| | • `mbset_report` |
| | • `intermediate`: page files, per-page JSON, caches |
| | • `internal`: hidden |

Endpoints (additive; the old ones stay until the frontend stops calling them):

| Endpoint | Returns |
|---|---|
| `GET /projects/{name}/results` | Project summary. Per step: `{status, updated_at, results: [{kind, label, path, size, updated_at}], intermediate_count, history_count}`. Counters `{qcms, corrected, flagged, with_case, rejected_for_mbset}` read from the newest result JSON and MBset report. ETag → `304` when unchanged. |
| `GET /projects/{name}/results/qcms?step=&filter=&flag=&session=&q=&page=&size=` | Paged, normalised QCM rows (`Num, Number, page, Text, A-E, Correct, Tag, session, Cas?, review_flags, origin_line`) from the step's result JSON. Filtered server-side: `needs_review`, a given flag, no answer, has case, session, text search. Parsed JSON is kept in an LRU cache keyed by file mtime. |
| `GET /projects/{name}/results/{step}/files?group=intermediate&page=` | The full file tree, paged and grouped by folder (Step 1's pages collapse into one group). |
| `GET .../files/{path}/preview?offset=&limit=` | Text preview in chunks (default 64 KB) with the total size, for "load more". |
| `GET .../files/{path}/table?sheet=&page=&size=` | **xlsx preview**: header + rows via `openpyxl` read-only, paged. Fixes U3 without Google. |
| `GET .../files/{path}/download` | Streams the file (or redirects to a signed URL) with `Content-Disposition`. The frontend puts a short-lived download token in the URL so the browser downloads natively instead of building a blob in memory (S4). |
| `GET /projects/{name}/results/{step}/history` | Past runs only (no duplicated "current"), labelled with date and file counts. Storage listing is batched into one call and cached. Loaded only when the user opens History. |

Plus: workbook names without the count (`qcms_<pdf>.xlsx`, `corrections_<pdf>.xlsx`),
so a re-run overwrites instead of piling up (U8). Old names are still listed.

### 11.3 Frontend — Results page `/projects/:name/outputs`

```
┌ Summary ──────────────────────────────────────────────────────────────┐
│ 186 QCMs · 171 with answer · 12 need review · 9 clinical cases        │
│ [⬇ MBset import file]  [⬇ Review workbook]  [Open in Google Sheets]  │
├ Questions ─────────────────────────────────────────────────────────────┤
│ Filters: (Needs review ▾) (Flag ▾) (Session ▾) (No answer) (Has case)  │
│ Search […]                                                             │
│ #  N°  Session            Question                     Answer  Flags   │
│ 4  7   Sec 01 2021        Les signes cliniques…        AC      —       │
│ 7  7   Sec 01 Pratique…   Une hypertonie utérine…      —       ⚠ 2     │
│ … virtualised, server-paged                                            │
│ Row click → side drawer: full question, options, answer, case text,    │
│ origin line, flags explained in plain words, "page 209" link           │
├ Files ─────────────────────────────────────────────────────────────────┤
│ Step 2 · QCM extraction   ✓ 21 Nov 14:02   2 results · 214 working files▸ │
│ Step 6 · Corrections      ✓ 21 Nov 14:20   3 results                  ▸ │
│ Each row: preview (text / table) · download · Sheets · delete          │
│ History ▸ (loaded on demand)                                            │
└────────────────────────────────────────────────────────────────────────┘
```

- **Step page** (`/projects/:name/steps/:id`) keeps only a compact
  "Results of this step" card: the step's 1-3 result files, their counts, and
  "Open results page →". The full file list moves to the Results page.
- **Batch view** reuses the same `ResultFileRow` and summary counters per PDF.
- One global toaster replaces `window.alert`. Sync status is shown in the
  Summary header for the whole project.
- Flags are shown with plain labels, for example:
  - `exam_number_suspect` → "Exam number looks misread"
  - `correction_ambiguous` → "Answer not applied: two parts share this number"

### 11.4 Optimisation targets

| Item | Today | Target |
|---|---|---|
| Requests to open a step's results | 2 (list + history) | 0 when cached, 1 otherwise (history on demand) |
| Data sent to show flagged questions | whole JSON (MBs) | one page of rows (≈20-50 KB) |
| Viewing an xlsx | Drive upload + new tab | in-app table, first page < 1 s |
| Big text preview | whole file in one DOM node | 64 KB chunks, virtualised |
| File endpoints with a traversal check | 1 of 6 | all, through `safe_path` |

### 11.5 Steps inside Phase R

| Step | Content |
|---|---|
| R0 | The S1 fix ships in Phase 1 already (`safe_path` + tests), independent of the rest. |
| R1 | `api/results.py`: `STEP_FOLDERS`, `safe_path`, `classify`, `/results`, `/results/qcms`, the preview/table/download endpoints, history. Tests use a temporary output tree: traversal, paging, filters, ETag, xlsx table. |
| R2 | Frontend data hooks (`useResults`, `useResultQcms`, `useFilePreview`) on the §3 cache; the shared `ResultFileRow` component; the global toaster. |
| R3 | Results page (summary, QCM table + drawer, files, history); step card; batch view switched to the shared row. The old `OutputViewer` is removed. |
| R4 | Stable workbook names; delete/sync/run-end invalidation wired; plain-language flag labels. |

### 11.6 Done when

- The Results page shows counts and the MBset file with one request (or
  instantly from cache).
- "Needs review" lists flagged questions without downloading the result JSON.
- An xlsx can be read in the app without Google.
- Every file endpoint rejects `../` (test).
- The pipeline and the batch view render results with the same component.
