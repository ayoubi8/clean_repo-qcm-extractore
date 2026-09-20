# Auto Run Batch (Multi-PDF) — Implementation Plan

Status: **PLAN ONLY — REVISED v2 (all 12 open questions resolved — decisions baked in below)**
Date: 2026-09-19
Scope: a third **Auto Run** option in the Switch Project launcher → import N PDFs (Google Drive folder link OR local folder upload) → one shared config (Step 1 method, Step 2 metadata, Step 6 correction source, per-step main/fallback models) → run steps **1 → 2 → 6** on every PDF (**parallel between PDFs — 5 at a time, queue-based; sequential between steps**; Steps 7–8 excluded) → live per-PDF progress + per-PDF output folders in one UI (expand-in-place detail) → per-PDF retry → auto-resume of interrupted batches → `AR_` name prefix + badge in Resume Project.

---

## 1. Current Architecture Summary (audit)

### 1.1 Launcher (Switch Project modal)

| Concern | Detail |
|---|---|
| Component | `frontend/src/components/launcher/ProjectLauncher.tsx` — fixed overlay, dialog `max-w-[520px]` `bg-surface-container rounded-2xl`, `TabButton` row (`border-b-2`, active = `text-primary border-primary bg-primary/5`), body `p-10` |
| Tabs today | `new` → `NewProjectModal`, `resume` → `ResumeProjectModal`. **Type is `LauncherTab = 'new' | 'resume'`** (ProjectLauncher.tsx:8) |
| Opened by | TopBar "Switch Project" button (`btn-switch-project` → `setActiveProject(null)` → `isLauncherOpen=true`); also default-open when no active project |
| Resume list | `ResumeProjectModal.tsx` — rows `border-l-4` + selected `border-primary bg-surface-container-highest`, tokens badge `text-[10px] font-mono text-primary bg-primary/10 px-2 py-0.5 rounded border border-primary/20`, delete button, "Continue from Step X" submit |
| New project | `NewProjectModal.tsx` — mode switch (`file` / `link`) with `flex-1 py-2.5 rounded-xl text-xs font-bold border` buttons; Drive single-file import via `importPdfFromDrive()` → `POST /pdf-from-drive` |

### 1.2 Existing per-project Auto Run (drawer, NOT this feature)

- `AutoRunPanel.tsx` (right drawer `w-[560px] bg-surface-container`) triggered inside `/pipeline` — runs a step range on the **active project only**, via `startAutoRun()` → `POST /projects/{name}/autorun` (real_api.py:4115).
- Backend `_autorun_task` (real_api.py:4122): sequence `["1","1.5","1.6","2","6","7","8"]`, each step through `_run_step_task` + `job_manager` (`{project}-{step}` keys → **already collision-free across projects**), breaks on first error. **This is exactly the per-PDF engine we reuse.**
- `autorunStore` (persisted): startStep/endStep/pauseForVerification/useYaml/batchConfig.

### 1.3 Ingest & pipeline primitives (all reusable as-is)

| Primitive | Location | Note |
|---|---|---|
| `_store_pdf_bytes(user, name, content, pdf_filename)` | real_api.py:897 | local `source.pdf` + Supabase Storage + `project.json` + `projects.pdf_storage_path` + cache invalidate |
| `download_drive_pdf(link, max_bytes, on_chunk)` | api/gdrive_import.py:246 | SSRF-guarded, magic-byte-validated anonymous download; folder links are **currently rejected** (`_NON_PDF_PATTERNS`) |
| `get_or_create(name, uid)` + `create_project` route | real_api.py:581 | DB `projects` row (UNIQUE(user_id,name)) + project.json local/Storage |
| `GET /projects/{name}/pdf-pages` | real_api.py:729 | page count → Step 6 "PDF has N pages — click to use the last page (N)" hint (Step6Config.tsx:66-75) |
| `GET /projects/{name}/steps/{step_id}/status` | real_api.py:2783 | in-memory job_manager → SQL `step_results` → Storage fallback; **per-project, already parallel-safe** |
| `GET /projects/{name}/steps/{step_id}/output` | real_api.py:3053 | file manifest (name, size_bytes, created_at) per step folder |
| download / view / open-sheets / sync-from-sheets routes | real_api.py:3218-3544 | used by OutputViewer row buttons |
| `GET /env/step-models` | real_api.py:2993 | main + fallback per step from Settings (.env) — seeds the model selects |

### 1.4 Frontend output-row design (to be replicated exactly)

`OutputViewer.tsx:407-535` — the `space-y-2` rows: `p-3 rounded-xl border bg-surface-container-low border-outline-variant/10 hover:border-outline-variant/30`, icon `material-symbols-outlined text-[18px] text-outline`, name `text-xs font-bold truncate text-on-surface-variant`, size `text-[10px] text-outline tabular-nums`, action buttons `w-7 h-7 rounded-lg hover:text-primary hover:bg-primary/10` with `material-symbols-outlined text-[16px]` (`visibility` / `download` / `open_in_new` / `delete` / `cloud_sync`). "Open source PDF" button design: `StepList.tsx:257-268`. Small close icon: `material-symbols-outlined text-[20px]` (ProjectLauncher.tsx:60).

### 1.5 Projects list / DB

- `list_projects(email)` (project_manager.py:198) — SQL-driven (`projects` table: id, name, created_at, last_activity_at, pdf_storage_path, total_tokens), 30s cache, computes `last_step`. **No `origin` column today** → auto-run badge needs it (resolved: Q8 → DB column).
- `Project` type (frontend types/index.ts:2): `name, last_step, last_modified, total_tokens, pdf_path`.

---

## 2. Confirmed Behavior (decisions baked in — was Open Questions)

| # | Decision (resolved) |
|---|---|
| Q1 | **Drive folder listing via the Drive file-explorer endpoint** `GET https://drive.google.com/drive/folders/{folderId}` — works anonymously for "Anyone with the link" folders (exactly the folders we target). The response embeds the folder's file list as JSON (`window['_DRIVE_ivd']`); we parse it server-side. No API key, no OAuth. |
| Q2 | **Concurrency 5, queue-based**: at most 5 PDFs run at the same time; when one finishes, the next queued PDF starts; keeps 5 workers until the queue is empty. Env-tunable `AUTORUN_BATCH_CONCURRENCY` (default 5). |
| Q3 | **Project names get the `AR_` prefix**: every auto-run project is named `AR_<sanitized-pdf-name>` — the prefix itself indicates "auto run". A remaining collision (the same PDF imported in two batches, or two PDFs with the same filename in one folder) gets the smallest free numeric suffix (`AR_math_2`). No `__2`-style suffix on non-batch names. |
| Q4 | **Top-level PDFs only** — no recursion into Drive subfolders / local subfolders. |
| Q5 | **Expand-in-place detail** inside the batch grid — no floating card, no drawer. |
| Q6 | **Step 6 mapping confirmed**: "last page" = each PDF's own last page (page count auto-detected per PDF — the automated "PDF has 9 pages → use page 9" logic); "first one" = page 1; "auto search" = full auto-detect scan of all pages. **`force_overwrite` is OFF (skip)** — auto runs never force re-extraction over existing corrections. |
| Q7 | **Models fully editable in the wizard** — main + fallback for Steps 1, 2 and 6. Hidden cascades (Step 1.5/1.6, the Step 3 metadata cascade, the Clinical Case Checker) are **not exposed** and run at Settings defaults. |
| Q8 | **`projects.origin` DB column** + badge on Resume Project rows (recommended option confirmed). |
| Q9 | **Per-PDF retry button** in the batch detail — re-runs that PDF from its first failed/incomplete step (already-done steps skipped). |
| Q10 | **Local uploads in parallel, 3 at a time** (client-side pool of 3 over the selected files). |
| Q11 | **Batch cap: 10 PDFs maximum** per batch. |
| Q12 | **Auto-resume**: on API startup, interrupted batches re-launch automatically; unfinished PDFs resume from their first not-done step. |

---

## 3. Proposed UX Flow

```
Switch Project (ProjectLauncher)
├─ New Project      (unchanged)
├─ Resume Project   (unchanged + AR_ badge on auto-run rows)
└─ Auto Run         (NEW — third tab, hidden when flag off)
     Stage 1 · Source
        [Drive folder link] input   ── or ──  [Select local folder] (webkitdirectory)
        [Import]  → backend scans Drive folder (names only) / client lists local *.pdf
     Stage 2 · Found files  (max 10 — counter + warning when the folder holds more)
        list of names (scrollable space-y-2, checkbox per file) → [Continue]
     Stage 3 · Config (one config for ALL PDFs)
        Step 1 · method cards (pypdfium2 / Vision OCR)      [Step1Config card style]
        Step 2 · models (Primary/Fallback selects) + Metadata Strategy fields
        Step 6 · source: [Last page] [First page] [Auto search]
        Models block: main+fallback per step (1, 2, 6), seeded from GET /env/step-models
        [Start Auto Run]  →  creates projects, closes launcher, navigates to batch view
     Stage 4 · Batch view (route /batch/:batchId)
        folder cards grid (one per PDF): name, per-step status chips, live progress,
        expand-in-place detail: step-titled space-y-2 rows + open-source-PDF +
        per-PDF retry + close text-[20px]
```

### 3.1 Launcher changes (ProjectLauncher.tsx)

- `LauncherTab = 'new' | 'resume' | 'autorun'`; third `TabButton` `id="tab-autorun"` label "Auto Run" (same style as siblings). **Hidden when the server flag is off** (see §4.6) — only rendered when `features.autorun_batch` is true.
- Body renders `<AutoRunWizard/>` for the new tab. **New Project / Resume Project render pixel-identical to today** (except the added badge on auto-run rows).
- On Start: `setLauncherOpen(false)`, `navigate('/batch/' + batch_id)`.

### 3.2 Wizard stages (new `components/launcher/autorun-wizard/`)

| Stage | UI (reusing existing design tokens) |
|---|---|
| Source | Two mode pills (NewProjectModal mode-switch style): `add_link` "Drive folder link" / `upload_file` "Local folder". Drive: url input `id="input-drive-folder-link"` + hint "Folder must be shared as 'Anyone with the link → Viewer'". Local: `<input type="file" webkitdirectory multiple hidden>`; client filters top-level `.pdf`, shows folder name + count immediately |
| Import | `Import` button (`btn-autorun-import`, primary submit style). Drive → `scanDriveFolder()` returns names (nothing downloaded yet); Local → instant client-side list |
| Files | Scrollable `space-y-2 max-h-[240px]` rows (ResumeProjectModal row style): `picture_as_pdf` icon, filename + "will run as `AR_<name>`" subtitle, size; checkbox per row (default all), "N of M selected" counter. **Cap 10**: if the folder contains more than 10 PDFs, only the first 10 are listed with an amber notice "Folder has N PDFs — a batch runs at most 10"; [Continue] disabled when 0 selected |
| Config | Sections in order (all existing component styles): ① Step 1 method — 2 cards (`method-pypdfium2` / `method-vision_ocr`, Step1Config grid; OCR guidance textarea + vision model pair appear only when OCR is selected) ② Step 2 — Primary/Fallback selects (Step2Config grid-cols-2 pattern, seeded from `useStepModels`, first option "⚙️ Use Settings default") + Metadata Strategy (Step3Config `embedded` — per-field strategy pills: Skip / Global / Per-QCM / Per-Group; hidden cascade models NOT shown — Settings defaults) ③ Step 6 — 3 cards: `Last page (auto per PDF)` / `First page` / `Auto search` (Step6Config card style; the last-page card shows the known hint "each PDF's last page is auto-detected — e.g. a 9-page PDF uses page 9") + the matching text/scan model pair ④ Models summary strip — main + fallback per step (1, 2, 6), all editable, all defaulting to Settings |
| Run | `Start Auto Run` (`btn-start-batch-autorun`, same gradient as AutoRunPanel footer). Local mode: **parallel uploads, 3 at a time** — a client-side pool of 3 runs `createProject` + `uploadProjectPdf` (existing routes, existing XHR progress) with an aggregate bar "x of y uploaded"; Drive mode: indeterminate "Downloading N PDFs from Drive…" (server-side) |

### 3.3 Batch view (new `pages/BatchView.tsx`, route `/batch/:batchId`)

- **Folder grid**: responsive `grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4`; one card per PDF (`bg-surface-container-low rounded-xl border`): `picture_as_pdf` icon, project name, and 3 step chips (1 / 2 / 6) with live status — `idle` outline, `running` primary + `animate-pulse` dot, `done` `check_circle` primary, `error` `error` error color. Overall state: running → spinner `progress_activity`; done → `border-primary/40` + "View results" affordance; error → red chip + failing step.
- **Polling**: `getBatchProgress(batchId)` (batch manifest + per-project states) every ~3s while anything is running; per-step detail via existing `getStepStatus(project, step)` for 1, 2, 6. When a PDF finishes, its card flips to done **immediately** while others keep spinning — inspect results while the rest still run.
- **Expand-in-place detail (resolved Q5)**: clicking a card expands a `col-span-full` panel **directly below it, inside the same grid flow** — no overlay, no portal, scrolls naturally with the page. The panel is a small `bg-surface-container rounded-2xl border border-outline-variant/20 shadow-lg` with:
  - header: PDF name + **open source PDF** button (StepList "Open source PDF" style, `picture_as_pdf` + `open_in_new`) + **per-PDF retry** button (resolved Q9 — `refresh` icon, shown only when the PDF's state is `error`/`cancelled`/`interrupted`, disabled while a retry is in flight) + close button `material-symbols-outlined text-[20px]` (`btn-close-batch-detail`) which collapses the expansion; clicking the card again also toggles it
  - body: one section per step — title `Step 1 · Text Extraction` etc. (`text-xs font-black text-on-surface-variant uppercase tracking-widest` + step icon), then the **exact OutputViewer `space-y-2` rows** with the same `w-7 h-7` icon buttons: preview (`visibility`), download (`download`), open in new tab (`open_in_new`), Sheets + `cloud_sync` for `.xlsx` — all calling the existing per-project endpoints with that PDF's project name (data via existing `fetchStepOutput(project, stepId)`)
  - only one card expanded at a time (expanding another collapses the previous)

### 3.4 Resume Project badge (resolved Q3 + Q8)

- `Project` type gains `origin?: 'manual' | 'autorun'`; `GET /projects` returns it (§5).
- Row renders next to the name a small badge: `rocket_launch` icon + "AUTO" in `text-[9px] font-black uppercase tracking-wider text-on-secondary-container bg-secondary-container/60 px-1.5 py-0.5 rounded border border-secondary/30` — same visual weight as the tokens badge, distinct color. The badge is driven by `origin` (DB), which always agrees with the `AR_` name prefix.

---

## 4. Backend Design

### 4.1 New endpoints (real_api.py, all `Depends(get_current_user)`)

| Route | Frontend fn (lib/api.ts) | Purpose |
|---|---|---|
| `POST /autorun/batch/scan` | `scanDriveFolder(folderLink)` | body `{folder_link}` → Drive file-explorer scan (§4.3) → `{files: [{file_id, name}], total_in_folder: N}` — names only, **nothing downloaded**; server caps the list at 10 and reports `total_in_folder` |
| `POST /autorun/batch/start` | `runBatch(payload)` | body `{source: "drive"\|"upload", drive_files?: [{file_id,name}], project_names?: [...], config: {...}}` → creates the batch manifest, kicks off `_autorun_batch_task`, returns `{batch_id, projects: [...]}`. For `drive`: downloads happen inside the batch task (5-worker queue). For `upload`: the frontend has ALREADY created+uploaded each project via existing `POST /projects` + `POST /projects/{name}/pdf` (3-parallel client pool) — this route registers the batch + starts pipelines |
| `GET /autorun/batches/{batch_id}` | `getBatchProgress(batchId)` | returns `{batch_id, created_at, state, config, projects: [{name, state, error_step?, current_step?}]}` (reads manifest + live states) |
| `POST /autorun/batches/{batch_id}/retry` | `retryBatchPdf(batchId, projectName)` | body `{project}` → re-enqueue **that one PDF** from its first not-done step (§4.5). 409 if it is already running/queued or not failed |

Per-step status, outputs, download/view/sync all reuse the **existing per-project routes unchanged** — the batch view just calls them per project.

### 4.2 Batch task (`api/autorun_batch.py`)

```python
BATCH_SEQUENCE = ["1", "1.5", "1.6", "2", "6"]        # hard-coded — Steps 7/8 excluded

async def _autorun_batch_task(user, batch_id, queue: list[str], config):
    sem = asyncio.Semaphore(AUTORUN_BATCH_CONCURRENCY)     # default 5 (Q2)
    async def one(project_name):
        async with sem:                                     # 5 running; next queued PDF
            start = first_not_done_step(project_name)       # resume/retry entry point
            for step_id in BATCH_SEQUENCE[BATCH_SEQUENCE.index(start):]:
                cfg = resolve_config(step_id, config, project_name)   # last_page → pages=str(N)
                task = asyncio.ensure_future(_run_step_task(project_name, user["id"], step_id, cfg))
                job_manager.set_running(project_name, step_id, task)
                try:
                    await task
                except asyncio.CancelledError:
                    mark(project_name, "cancelled"); return
                if job_manager.get_status(project_name, step_id) in ("error","stopped","cancelled"):
                    mark(project_name, "error", error_step=step_id); return
            mark(project_name, "done")
    await asyncio.gather(*[one(p) for p in queue])
```

- **Parallelism between PDFs** = one `one()` coroutine per project gated by the semaphore (5 permits; queue drains as workers free up — exactly "when one is finished the next one starts"). **Sequential between steps** = the inner loop awaits each step before the next (identical contract to the existing `_autorun_task`).
- Steps 1.5 / 1.6 stay today's invisible Step-1→2 helpers; Step 3 rides inside Step 2's cascade via `run_config.step2.step3` (exact same payload shape `AutoRunPanel.handleStart` builds today: `serializeStep3` CODE_MAP/FIELD_MAP). CC checker + cascade models = Settings defaults (Q7).
- **Per-PDF failure isolation**: one PDF's step error marks only that project red; others continue. Retry (Q9) re-enqueues just that project through `one()` with `first_not_done_step` — done steps are skipped, the failed step re-runs, later steps follow.
- `job_manager` keys are `{project}-{step}` → parallel projects coexist safely (verified: no global step lock in `_run_step_task`).

### 4.3 Drive folder scan (`api/gdrive_import.py` extension)

- `extract_drive_folder_id(link)` — accept `https://drive.google.com/drive/folders/<ID>` (+ `?usp=sharing`); everything else → existing friendly errors.
- `scan_drive_folder(link, client_factory=None) -> (files, total)` — **the resolved Q1 mechanism**:
  - `GET https://drive.google.com/drive/folders/<ID>` with the same allowlist + `_dns_guard` + https-only checks (**no new hosts**) — this is Drive's file-explorer endpoint; it answers anonymously when the folder is "Anyone with the link"
  - parse the embedded `window['_DRIVE_ivd']` JSON payload → entries with `.pdf` names (case-insensitive); **top-level only** (Q4 — ignore nested folder entries)
  - return names + IDs only; **no download, no project creation** at scan time; server caps the returned list at `MAX_AUTORUN_BATCH_FILES` (10, Q11) and reports the true total
- Download-at-run reuses the existing SSRG-guarded streamer: add `download_drive_file_by_id(file_id)` (tiny refactor extracting the post-ID part of `download_drive_pdf`) so the batch task can pass folder-scanned IDs directly. Every file still passes `%PDF-` magic validation.
- Per-user rate limit key `autorun_batch` (e.g. 3 starts / 10 min) reusing `_check_user_rate_limit` (real_api.py:959).

### 4.4 Step-6 resolution (per PDF, at run time)

| Wizard choice | Resolved per-project config |
|---|---|
| `last_page` | `source: "page_text"`, `correction_search_mode: "specific_pages"`, `pages: str(N)` where `N = page_count(source.pdf)` computed server-side via the same pypdfium2 count `/pdf-pages` uses — **the automated "PDF has 9 pages → use page (9)" logic, per PDF** |
| `first_page` | `source: "page_text"`, `correction_search_mode: "specific_pages"`, `pages: "1"` |
| `auto_search` | `source: "auto_detect"`, `correction_search_mode: "all_pages"` |

- **`force_overwrite: false` always** (resolved Q6 part two — skip).
- Model fields (`text_model` / `all_pages_model` + fallbacks) come from the wizard verbatim; empty string = Settings default (existing convention).

### 4.5 Naming, retry & auto-resume

- **Naming (Q3)**: every batch project is `AR_<sanitized-name>` (`[^A-Za-z0-9._-] → '_'`, same rule as `_derive_project_name`). Remaining collision (duplicate filename in the batch, or `AR_<name>` already exists) → smallest free numeric suffix `AR_<name>_2`. The mapping ("will run as …") is visible in the wizard file list before run.
- **Retry (Q9)**: `POST /autorun/batches/{id}/retry` guards (project in this batch ∧ state ∈ {error, cancelled, interrupted} ∧ no live job for it) → `mark(pending)` + `asyncio.ensure_future(one(project))` into the same 5-slot semaphore. `first_not_done_step` resolves via the existing status logic (job_manager → SQL `step_results` → Storage output check) so only the failed step and its successors re-run.
- **Auto-resume (Q12)**: on API startup, iterate every user's `{uid}/_batches/*/batch.json`; for each manifest holding `pending`/`running` projects, re-launch `_autorun_batch_task` in resume mode with those projects (each entering at `first_not_done_step`). Guards: an in-memory `batch_id → task` registry prevents double-starting; after a restart `job_manager` is empty so no step is falsely "running". If `source.pdf` is missing locally, `_run_step_task` already restores it from Supabase Storage (real_api.py:2213-2222) — resume survives an FS wipe. A batch whose projects were all `done`/`error` is NOT re-launched (errors await an explicit retry click).

### 4.6 Feature flag & env

| Var | Default | Purpose |
|---|---|---|
| `AUTORUN_BATCH_ENABLED` | `true` | Flag; scan/start/retry return 404 when off; the launcher hides the Auto Run tab (surfaced to the frontend via a small `features` object added to the existing `GET /env/step-models` response — same pattern the gdrive plan used) |
| `AUTORUN_BATCH_CONCURRENCY` | `5` | PDF-level parallelism (Q2) |
| `MAX_AUTORUN_BATCH_FILES` | `10` | Batch cap (Q11) — enforced in scan AND start |

---

## 5. Data Model & Persistence

| Item | Design |
|---|---|
| `projects.origin` (Q8) | `ALTER TABLE projects ADD COLUMN IF NOT EXISTS origin VARCHAR(64) DEFAULT 'manual';` appended to `api/migration.sql` + the existing resilient-select pattern (drop column on missing-column error, like `total_tokens`). `_compute_projects` selects it → `GET /projects` returns `origin` per project. |
| project.json | gains `"origin": "autorun", "batch_id": "<id>"` — written by the batch ingest for traceability |
| Batch manifest | `{uid}/_batches/{batch_id}/batch.json` (local + Supabase Storage, same dual-write as project.json): `{batch_id, created_at, source, config_snapshot, projects: [{name, drive_file_id?, state: "pending"\|"running"\|"done"\|"error"\|"cancelled", error_step?}]}`. In-memory dict mirrors it for the running session; `GET /autorun/batches/{id}` reads the file when memory is empty (post-restart) and reports `state: "interrupted"` for projects that were `running`. |
| Status per step | unchanged — `GET /steps/{id}/status` + `step_results` SQL rows already answer it per project (and power `first_not_done_step`) |
| Costs/tokens | unchanged — each project tracks its own `total_tokens` |

---

## 6. Frontend Files & Design (all reusing existing tokens)

| Action | File |
|---|---|
| CREATE | `components/launcher/autorun-wizard/AutoRunWizard.tsx` — stage machine `source → files → config` (state: `stage`, `mode: 'drive'\|'folder'`, `folderLink`, `foundFiles`, `selected`, wizard-local config) |
| CREATE | `components/launcher/autorun-wizard/BatchConfigForm.tsx` — Step 1 method cards + Step 2 models + metadata strategies + Step 6 source cards + models strip (seeded via `useStepModels`) |
| CREATE | `store/batchStore.ts` — zustand: `batchId`, `projects: [{name, state, stepStatuses}]`, `expandedProject`, poll-loop actions (`getBatchProgress` every ~3s while running) |
| CREATE | `pages/BatchView.tsx` + `components/batch/BatchFolderCard.tsx` + `components/batch/BatchDetailPanel.tsx` (the expand-in-place `col-span-full` surface-container) + `components/batch/StepFileRow.tsx` (extracted copy of the OutputViewer row, minus history). *Note: the earlier "StepRunner.tsx" list item does not exist in this repo — batch-aware step status/progress lives in these components + `batchStore.ts`.* |
| MODIFY | `ProjectLauncher.tsx` — third tab (flag-gated) |
| MODIFY | `ResumeProjectModal.tsx` — `origin === 'autorun'` badge |
| MODIFY | `types/index.ts` — `Project.origin`, `BatchManifest`, `BatchConfig`, `BatchProjectState` types |
| MODIFY | `lib/api.ts` — `scanDriveFolder()`, `runBatch()`, `getBatchProgress()`, `retryBatchPdf()` (local-folder upload reuses existing `createProject` + `uploadProjectPdf` from a 3-slot pool) |
| MODIFY | `App.tsx` — route `/batch/:batchId` |
| UNTOUCHED | in-project `AutoRunPanel.tsx` drawer, `pipelineStore`, `autorunStore`, OutputViewer, all pipeline configs |

Design contract for new components (exact classes from the audited files): rows `p-3 rounded-xl border bg-surface-container-low border-outline-variant/10`, section labels `text-[10px] font-black uppercase tracking-[0.2em] text-outline`, selectable cards `p-4 rounded-xl border-2 border-primary bg-primary/5 shadow-[0_0_15px_rgba(76,215,246,0.1)]` (selected) vs `border-outline-variant/10 bg-surface-container-low hover:border-outline-variant/30` (idle), primary buttons `bg-primary text-on-primary rounded-xl font-black uppercase tracking-tighter shadow-[0_4px_20px_rgba(76,215,246,0.3)]`, animations `animate-in fade-in slide-in-from-bottom-2 duration-300`, scrollbars `custom-scrollbar`, close icon `material-symbols-outlined text-[20px]`.

---

## 7. Security

| Threat | Mitigation |
|---|---|
| SSRF via folder link | Same allowlist + `_dns_guard` + https-only as `download_drive_pdf`; the scan fetches only `drive.google.com/drive/folders/<ID>` built server-side from a strict regex; no user URL is ever fetched |
| Untrusted folder content | Only entries with `.pdf` names are listed; every file still passes `%PDF-` magic validation at download time (existing check) |
| Resource exhaustion | `MAX_AUTORUN_BATCH_FILES` (10) + existing 200 MB per-file cap + per-user start rate-limit + semaphore-bounded concurrency (5) + 3-parallel upload pool |
| Log leakage | Log file IDs and counts only, never raw links (existing gdrive convention) |
| Auth | Every new route behind `Depends(get_current_user)`; batch manifests namespaced `{uid}/_batches/…`; retry validates the project belongs to the caller's batch |

---

## 8. Risks / Conflicts Found

| # | Finding | Fix |
|---|---|---|
| R1 | The Drive file-explorer payload (`_DRIVE_ivd`) is undocumented and its shape can change | Accepted (resolved Q1 — confirmed approach for link-public folders). Parse code isolated in `scan_drive_folder` with its own fixtures; scan failure returns the clear "Couldn't read the folder — make sure it's shared 'Anyone with the link'" message; single-file Drive import remains the fallback path |
| R2 | 5 parallel PDFs × per-step LLM threads can hit API rate limits / Space CPU | `AUTORUN_BATCH_CONCURRENCY` env (default 5, tunable down without code changes); rate-limit errors surface as per-project step failures → failure isolation marks only that PDF; retry button re-runs it later |
| R3 | `job_manager` is in-memory; a container restart kills tracking | **Auto-resume (resolved Q12)**: startup scan re-launches unfinished batches; `batch.json` persists the roster; per-step SQL status gives each PDF its resume point. Batches fully done/error are not re-launched |
| R4 | Double-starting a batch (retry spam / resume racing a still-alive task) | In-memory `batch_id → task` registry + retry endpoint's 409 guard; resume only fires for manifests not present in the registry |
| R5 | Project name collision breaks `UNIQUE(user_id,name)` | `AR_` prefix + smallest-free numeric suffix (resolved Q3); mapping shown in the wizard before run |
| R6 | `list_projects` 30s cache delays the badge right after start | Acceptable (badge corrects within 30s); `_store_pdf_bytes` already invalidates the cache per project |
| R7 | Step 6 `last_page` needs the page count before Step 6 runs | Resolved in `resolve_config` right before Step 6 dispatch via the same pypdfium2 count `/pdf-pages` uses (PDF is local by then; Step 1's `page_*.txt` outputs are NOT required) |
| R8 | Local upload of 10 files could time out the wizard | 3-parallel pool with aggregate progress; Start disabled until the pool drains; one failed upload marks only that PDF as not-imported (excluded from the run with a visible row error) |

---

## 9. Testing Strategy

**Unit (pytest, `tests/test_autorun_batch.py`)**
- `extract_drive_folder_id`: accepted shapes + rejections (file link, docs link, non-drive host)
- `scan_drive_folder`: fixture folder HTML → correct `[{id,name}]`; `.pdf` filter; **top-level only**; >10 files → capped list + true total; not-public error
- `resolve_config`: `last_page` → `pages=str(N)` with mocked page count; `first_page` → `"1"`; `auto_search` mapping; `force_overwrite` always False
- naming: `AR_` prefix; duplicate filename → `AR_<name>_2`; existing `AR_<name>` → `_3`
- `first_not_done_step`: SQL rows mocked → resume point; all-done → None

**Integration (FastAPI TestClient, Storage mocked)**
- `POST /autorun/batch/start` (drive): creates N `AR_*` projects with `origin='autorun'`, downloads via mocked `download_drive_file_by_id`, `batch.json` written, semaphore respected (patched `_run_step_task` records order: per-project sequential, across-project ≤5 parallel, queue drains)
- failure isolation: project B step 2 errors → A and C complete; B marked `error` + `error_step`
- `POST …/retry`: B re-runs from step 2 only (step 1 skipped); 409 while running
- auto-resume: manifest with `running` projects on startup → task re-launched, entry at `first_not_done_step`; fully-done batch NOT re-launched
- `GET /projects` returns `origin`; badge contract

**Manual QA**
- Real public Drive folder (12 PDFs — confirm cap-10 message; one >25 MB) end-to-end 1→2→6; local folder with 10 PDFs (3-parallel upload bar); duplicate names; Resume badge; batch view mid-run: finished folder expandable while others spin; expand-in-place detail: step sections, xlsx open-in-sheets + `cloud_sync`, open source PDF button, close `text-[20px]`; retry after forcing a step failure; restart the API mid-batch → auto-resume completes the queue.

---

## 10. Regression Checklist

- [ ] New Project / Resume Project tabs pixel-identical (except the added badge on auto-run rows)
- [ ] In-project AutoRunPanel drawer behavior unchanged (single project)
- [ ] `POST /projects/{name}/autorun` (old route) untouched
- [ ] Single-file Drive import (`POST /pdf-from-drive`) untouched
- [ ] `GET /projects` response superset-compatible (new `origin` field only)
- [ ] Upload flow (`POST /projects/{name}/pdf`) reused as-is for local folders
- [ ] Step status / output / download / sync routes unchanged — batch view only calls them
- [ ] Retry/auto-resume never re-run a `done` step for a project (SQL-badge based check)

---

## 11. Files to Create / Modify

| Action | File |
|---|---|
| CREATE | `api/autorun_batch.py` — batch task, 5-slot queue, manifest, config resolution, retry/auto-resume (pure, testable) |
| CREATE | `docs/plans/autorun-batch-plan.md` — this plan |
| CREATE | `tests/test_autorun_batch.py` |
| CREATE | `frontend/src/components/launcher/autorun-wizard/AutoRunWizard.tsx` + `BatchConfigForm.tsx` |
| CREATE | `frontend/src/pages/BatchView.tsx` (repo pages/ convention), `frontend/src/components/batch/{BatchFolderCard,BatchDetailPanel,StepFileRow}.tsx`, `frontend/src/store/batchStore.ts` |
| MODIFY | `api/real_api.py` — 4 new routes (§4.1); `origin` on batch-created projects; startup auto-resume hook; `features` object in `/env/step-models` |
| MODIFY | `api/gdrive_import.py` — `extract_drive_folder_id`, `scan_drive_folder` (file-explorer parse, top-level only, cap 10), `download_drive_file_by_id` |
| MODIFY | `api/project_manager.py` — select + return `origin` |
| MODIFY | `api/migration.sql` — `ALTER TABLE projects ADD COLUMN IF NOT EXISTS origin VARCHAR(64) DEFAULT 'manual';` |
| MODIFY | `frontend/src/lib/api.ts` — `scanDriveFolder`, `runBatch`, `getBatchProgress`, `retryBatchPdf` |
| MODIFY | `frontend/src/components/launcher/ProjectLauncher.tsx` (third tab, flag-gated) · `ResumeProjectModal.tsx` (AR badge) · `types/index.ts` · `App.tsx` (route) |

---

## 12. Rollout & Rollback

- Flag `AUTORUN_BATCH_ENABLED` (default `true`): scan/start/retry 404 when off; launcher hides the tab via the `features` object on `GET /env/step-models`.
- Rollback: flip flag off; revert frontend route/tab; `origin` column and `batch.json` files are inert for the rest of the app; `AR_` projects remain valid normal projects.

---

## 13. Phased Implementation Plan (implement phase per phase)

Rules that apply to every phase:
- One phase = one reviewable unit. **No phase starts before the previous one passes its exit criteria.**
- Every phase ends with a commit + its verification run (backend: `pytest tests/test_autorun_batch.py`; frontend: `npm run build` + manual check).
- Nothing in a phase may change existing behavior — each phase's regression item from §10 must still hold.

---

### Phase 1 — Foundation: `origin` column + Resume badge (no batch logic)

**Goal**: auto-run projects can be *marked* and *recognized* before any batch machinery exists.

| Task | File |
|---|---|
| `ALTER TABLE projects ADD COLUMN IF NOT EXISTS origin VARCHAR(64) DEFAULT 'manual';` | `api/migration.sql` |
| Resilient select + return `origin` in the projects payload (drop-column fallback like `total_tokens`) | `api/project_manager.py` |
| `Project.origin?: 'manual' \| 'autorun'` | `frontend/src/types/index.ts` |
| AUTO badge (`rocket_launch` + "AUTO", §3.4 design) when `origin === 'autorun'` | `frontend/src/components/launcher/ResumeProjectModal.tsx` |

- **Depends on**: nothing.
- **Verify**: migration applied; `GET /projects` returns `origin` (superset-compatible — §10 item); badge renders for a manually flipped row; New/Resume tabs otherwise pixel-identical.
- **Exit criteria**: `pytest` green (projects tests), `npm run build` green, badge visible in Resume list for a test row with `origin='autorun'`.

---

### Phase 2 — Drive folder scan (backend service only, no routes yet)

**Goal**: a pure, fully-tested service that turns a public folder link into `[{file_id, name}]`.

| Task | File |
|---|---|
| `extract_drive_folder_id(link)` — strict folder-link regex, existing friendly errors | `api/gdrive_import.py` |
| `scan_drive_folder(link)` — file-explorer endpoint fetch (allowlist + `_dns_guard`, §4.3), `_DRIVE_ivd` parse, `.pdf` filter, **top-level only**, cap 10 + true total | `api/gdrive_import.py` |
| `download_drive_file_by_id(file_id)` — extract the post-ID part of `download_drive_pdf` (refactor is 1:1, behavior-preserving) | `api/gdrive_import.py` |
| Unit tests: fixture folder HTML → parsed list; `.pdf` filter; top-level only; >10 → cap + total; not-public error; folder-id rejections | `tests/test_autorun_batch.py` |

- **Depends on**: nothing (independent of Phase 1).
- **Verify**: unit tests green against HTML fixtures; single-file import regression — `POST /pdf-from-drive` still works after the `download_drive_file_by_id` refactor (§10 item).
- **Exit criteria**: `pytest tests/test_gdrive_import.py tests/test_autorun_batch.py` green; real manual scan against a public test folder returns the correct 10-cap list.

---

### Phase 3 — Batch engine + routes (backend, complete API surface)

**Goal**: the whole backend feature exists and is testable headlessly (curl / pytest) — no UI yet.

| Task | File |
|---|---|
| `_autorun_batch_task` — 5-slot semaphore queue, per-PDF sequential `["1","1.5","1.6","2","6"]`, failure isolation, `resolve_config` (Step-6 last/first/auto mapping, `force_overwrite: false`), `first_not_done_step` | `api/autorun_batch.py` |
| Manifest read/write — `{uid}/_batches/{id}/batch.json` dual-write, states, in-memory registry | `api/autorun_batch.py` |
| Routes: `POST /autorun/batch/scan`, `POST /autorun/batch/start`, `GET /autorun/batches/{id}`, `POST /autorun/batches/{id}/retry` (409 guard), all auth'd + flag-gated | `api/real_api.py` |
| `AR_` naming + collision suffix; `origin='autorun'` + `batch_id` on batch-created projects | `api/autorun_batch.py` |
| Startup **auto-resume** hook (§4.5 guards) + `features.autorun_batch` in `GET /env/step-models` | `api/real_api.py` |
| Integration tests (§9): start (drive), ≤5 parallel + queue drain, failure isolation, retry-from-failed-step, auto-resume, cap 10, naming/collisions, 404 when flag off | `tests/test_autorun_batch.py` |

- **Depends on**: Phase 1 (`origin`), Phase 2 (`download_drive_file_by_id`).
- **Verify**: full integration suite green; manual headless run — start a 3-PDF batch via curl and watch `GET /autorun/batches/{id}` + `GET /steps/{id}/status` flip to done; restart API mid-batch → auto-resume completes the queue.
- **Exit criteria**: all §9 integration tests green; §10 regression items hold (old autorun route, single-file import, upload route untouched).

---

### Phase 4 — Wizard UI (Auto Run tab: source → files → config → start)

**Goal**: the user can launch a batch entirely from the launcher modal; it lands on a (not-yet-built) batch URL.

| Task | File |
|---|---|
| `scanDriveFolder()`, `runBatch()` (+ types `BatchManifest`, `BatchConfig`) | `frontend/src/lib/api.ts`, `frontend/src/types/index.ts` |
| `AutoRunWizard.tsx` — stage machine (§3.2): source pills (Drive link / local `webkitdirectory`), Import, capped file list with `AR_` preview + checkboxes, config sections | `frontend/src/components/launcher/autorun-wizard/` |
| `BatchConfigForm.tsx` — Step 1 method cards, Step 2 models + metadata strategies, Step 6 source cards (last/first/auto), models strip seeded via `useStepModels` | `frontend/src/components/launcher/autorun-wizard/` |
| Local upload: **3-parallel** `createProject` + `uploadProjectPdf` pool, aggregate "x of y" bar, per-file error marking | `AutoRunWizard.tsx` |
| Third launcher tab `tab-autorun`, **flag-gated** (hidden when `features.autorun_batch` false); navigate to `/batch/:batchId` on start | `frontend/src/components/launcher/ProjectLauncher.tsx` |

- **Depends on**: Phase 3 (real endpoints).
- **Verify**: `npm run build` green; manual — Drive folder scan shows capped names, config edits ride through, Start creates `AR_*` projects and closes the launcher; flag off → tab hidden; New/Resume tabs unchanged (§10 item).
- **Exit criteria**: a real batch can be started from the UI (verify via API/DB even though the batch page doesn't exist yet).

---

### Phase 5 — Batch view UI (grid + expand-in-place detail + retry)

**Goal**: the live batch cockpit — progress, inspectable finished folders, retry.

| Task | File |
|---|---|
| `getBatchProgress()`, `retryBatchPdf()` in `lib/api.ts`; `batchStore.ts` (poll ~3s while running, `expandedProject`) | `frontend/src/lib/api.ts`, `frontend/src/store/` |
| `/batch/:batchId` route + page | `frontend/src/App.tsx`, `frontend/src/pages/BatchView.tsx` |
| `BatchFolderCard.tsx` — per-PDF card, 3 step chips (idle/running/done/error), spinner, done flip while others run | `frontend/src/components/batch/` |
| `BatchDetailPanel.tsx` — **expand-in-place** `col-span-full` surface-container (§3.3): step-titled sections + exact OutputViewer `space-y-2` rows (preview/download/open-in-new/`cloud_sync`), **open source PDF** button, **per-PDF retry** button, close `text-[20px]`; one expansion at a time | `frontend/src/components/batch/` |
| `StepFileRow.tsx` — extracted OutputViewer row (minus history) | `frontend/src/components/batch/` |

- **Depends on**: Phase 3 (endpoints), Phase 4 (can navigate here).
- **Verify**: `npm run build` green; manual mid-run — finished PDF expandable while others spin; xlsx open-in-sheets + `cloud_sync` inside the detail; retry on a failed PDF re-runs only from the failed step; close `text-[20px]` collapses.
- **Exit criteria**: end-to-end UI run of a 10-PDF batch (local + Drive) matches §9 manual QA script.

---

### Phase 6 — Hardening, full QA & ship

**Goal**: production-ready; flag on by default.

| Task | Detail |
|---|---|
| Full regression pass | every §10 checkbox ticked |
| Manual QA script (§9) | real 12-PDF public folder (cap message), duplicate names, >25 MB file, 3-parallel local upload bar |
| Restart / auto-resume drill | kill API mid-batch → startup resume finishes the queue; fully-done batch NOT re-launched |
| Failure drill | force a step error → red folder + retry works; flag flip off/on hides/shows the tab |
| Ship | flag `AUTORUN_BATCH_ENABLED=true` default; monitor logs (`[AUTORUN-BATCH]` markers); rollback = flip flag off |

- **Depends on**: Phases 1–5 all complete.
- **Exit criteria**: every §10 box ticked; QA script passes twice (local + deployed).

---

### Phase dependency graph

```
Phase 1 (origin + badge) ─┐
                          ├─→ Phase 3 (engine + routes) ─→ Phase 4 (wizard UI) ─→ Phase 5 (batch view) ─→ Phase 6 (QA + ship)
Phase 2 (drive scan) ─────┘
```
(Phase 1 and Phase 2 are independent of each other and can be built in either order or in parallel.)
