# Session Resume — Auto Run Batch (multi-PDF)

Date: 2026-09-20 · Branch `main` · Latest commits: `5930c32` (feature), `5a95cf4` (scan fix)
Plan reference: docs/plans/autorun-batch-plan.md (6 phases, all implemented)

---

## 1. What was built

**Feature**: third **Auto Run** option in the Switch Project launcher — import up to 10 PDFs
(Google Drive folder link or local folder), one shared config, run **Steps 1 → 2 → 6** per PDF
(5 PDFs in parallel, sequential steps; Steps 7–8 excluded), live batch view, per-PDF retry,
startup auto-resume, `AR_` naming + AUTO badge.

| Phase | Scope |
|---|---|
| 1 | `projects.origin` column (migration.sql) + `origin` in GET /projects + AUTO badge (rocket_launch) in Resume Project |
| 2 | `api/gdrive_import.py`: `extract_drive_folder_id`, `scan_drive_folder` (anonymous `drive.google.com/embeddedfolderview?id=` listing, top-level PDFs only, cap 10), `download_drive_file_by_id` (1:1 refactor of the downloader tail) |
| 3 | `api/autorun_batch.py` engine: 5-slot `asyncio.Semaphore` queue, per-PDF sequence `["1","1.5","1.6","2","6"]`, failure isolation, `AR_` prefix + `_2/_3` collision suffix, batch.json manifests `{uid}/_batches/{id}/` (local + Storage), `first_not_done_step` (SQL `step_results` authoritative → local FS fallback), `resolve_step6_config` (last_page = per-PDF page count via pypdfium2 / first_page / auto_search; force_overwrite always False), `retry_project`, `resume_interrupted_batches` (startup hook in `_startup`), 4 routes in `real_api.py`: POST `/autorun/batch/scan`, POST `/autorun/batch/start`, GET `/autorun/batches/{id}`, POST `/autorun/batches/{id}/retry`; `features.autorun_batch` added to GET `/env/step-models` |
| 4 | Wizard: `ProjectLauncher` third tab (flag-gated), `autorun-wizard/BatchConfigForm.tsx` (Step-1 method cards, Step-2 main/fallback models + wizard-local metadata strategy cycle table, Step-6 last/first/auto cards + matching model pair, all seeded from /env/step-models), `AutoRunWizard.tsx` (drive-link / webkitdirectory local folder → capped file list with "will run as AR_x" preview → config → start; local uploads 3-parallel via createProject + uploadProjectPdf) |
| 5 | `/batch/:batchId`: `store/batchStore.ts` (3s polling while active), `BatchFolderCard` (live step chips incl. hidden 1.5/1.6), `BatchDetailPanel` (expand-in-place `col-span-full`: OutputViewer-style `space-y-2` rows with preview/download/open-in-new/Sheets/cloud_sync/delete, Open source PDF button, per-PDF Retry, close text-[20px]), `pages/BatchView.tsx` + route in App.tsx |
| 6 | Hardening: retry-task registry cleanup, `.env.example` knobs, full regression pass |

**Resolved decisions (Q1–Q12)**: Drive = embedded file-explorer endpoint (public folders, no
auth) · concurrency 5 queue-based · `AR_` prefix (numeric suffix only on remaining collisions) ·
top-level only · expand-in-place detail · Step-6 mapping confirmed, force_overwrite off · models
editable for Steps 1/2/6, hidden cascades at Settings defaults · `projects.origin` DB column ·
per-PDF retry · local uploads 3-parallel · cap 10 · auto-resume on.

## 2. Verification

- Tests all green: `tests/test_autorun_batch.py` (F1–F10), `test_gdrive_import.py`, persistence PR-1..4; `npm run build` green.
- Live verified against a real public folder ("test auto run function") — 3 PDFs listed with correct names.

## 3. Post-push bugfixes (commit `5a95cf4`)

- Streaming httpx response must be `read()` before `.text` access (`ResponseNotRead` → 500 on scan).
- Anchor regex accepts `/view?usp=drive_web` suffix (real Drive anchors carry a query).

## 4. Where to push

| Target | How | Effect |
|---|---|---|
| **Backend / API (Hugging Face)** | `git push space main` — remote `space` = https://huggingface.co/spaces/ayoubi8/qcm-extractor | Space Docker rebuild, uvicorn :7860 — push the whole repo (branch `main`) |
| **Frontend (GitHub)** | mirror the contents of local `frontend/` to the remote repo root (git archive export, no node_modules/dist) then push to `frontend-repo` = https://github.com/ayoubi8/qcm-extractor-frontend.git | Vercel auto-deploy |
| Full repo backup (optional) | `git push origin main` — origin = https://github.com/ayoubi8/clean_repo-qcm-extractore.git | both commits already on `main` |

Frontend-repo sync procedure (for incremental edits later):
`git archive --format=tar -o fe.tar HEAD frontend` → extract into a clone of the frontend repo
with `tar -xf fe.tar -C <clone> --strip-components=1` → commit → push.
(Plain Copy-Item introduces CRLF noise — use git archive.)

## 5. Operator checklist (first real run)

- [ ] Apply the new line in api/migration.sql (`ALTER TABLE projects ADD COLUMN IF NOT EXISTS origin VARCHAR(64) DEFAULT 'manual';`) in the Supabase SQL editor
- [ ] Env knobs in .env.example / HF secrets: `AUTORUN_BATCH_ENABLED=true`, `AUTORUN_BATCH_CONCURRENCY=5`, `MAX_AUTORUN_BATCH_FILES=10`
- [ ] Manual QA pending: 12-PDF folder (cap message expected), duplicate names → `AR_x_2`, restart mid-batch → `[STARTUP] auto-resume re-launched …`, forced step failure → red card + Retry, flag off → tab hidden
