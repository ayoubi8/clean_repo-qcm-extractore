# Open items — November 2026

Everything still open after the deploys of 2026-11-22
(backend `a094d1c` on the HF Space, frontend `7ad448e` on Vercel).
Tick an item when it ships, with the date and commit.

## 1. Website split + lag plan (`frontend-routes-and-switch-lag-plan.md`)

| # | Item | Why it is open | Size |
|---|---|---|---|
| L1 | **Phase 5 — run steps outside the API process** | Not started. Plan: [phase5-step-runner-process-plan.md](phase5-step-runner-process-plan.md). | L |
| L2 | **Phase 0 numbers** | `Server-Timing` is live but before/after timings were never recorded (idle and during a run). Needed as the Phase 5 baseline. | S |
| L3 | **B1 for the other endpoints** | Only `get_current_user` was made sync. `async def` endpoints that still do blocking Supabase / Storage / file work on the event loop: `stop_step`, `step8_merge_outputs`, `autorun_*`, uploads. Make them `def` or wrap the blocking part in `asyncio.to_thread`. | S |
| L4 | **B3 — Space asleep** | No "server waking up" banner when `/bootstrap` takes > 3 s, and no keep-awake ping. | S |
| L5 | **Stable workbook names (U8)** | `120_qcms_x.xlsx`, `118_qcms_x.xlsx`… still pile up. Changing `result_xlsx_name` breaks `tests/test_output_naming.py` and the Google Sheets reuse (`_sheets_meta.json` keyed by filename). The Results page hides older copies instead. Needs a decision + migration of the Sheets meta. | M |
| L6 | **Native downloads (S4)** | Downloads still fetch a blob into browser memory. Needs a short-lived signed download token from the server, then a plain link. | M |
| L7 | **Frontend tests** | Plan §8: router tests (every URL renders, `/pipeline` redirects, `?sheets_pending` flow), Switch Project + Back, no second `/env/step-models` request. No Vitest setup in `frontend/` yet. | M |
| L8 | **Logged-in check of the live site** | Deployed but not clicked through: open a project, switch steps, refresh on a step, Results page (filters, drawer, xlsx preview), batch view rows, Google Sheets open + sync, Settings tabs. | S |
| L9 | **OAuth return URL** | Backend still sends `/pipeline?sheets_pending=1&project=…` (works with both frontends). Can point straight at `/projects/{p}/steps/{s}` now that the new frontend is live — optional. | XS |
| L10 | **Quick switcher (Q1)** | Ctrl/Cmd + K project switcher over the cached list — "later" in the plan. | S |
| L11 | **First-load size** | 241 kB (72 kB gzip) vs the 200 kB target. The rest is React + router + zustand; split vendor chunk or accept. | XS |
| L12 | **Project named `new`** | `/projects/new` is the New-project page, so a project literally called `new` can't be opened by URL. Block the name at creation or accept. | XS |
| L13 | **Old step-file endpoints** | `/steps/{id}/output/{file}` (whole file as one string) and `/steps/{id}/history` are no longer called by the new frontend. Keep one release, then remove (§11.2 "the old ones stay until…"). | XS |

## 1b. Done 2026-11-23 (uncommitted)

- Phase 5 steps 5.0-5.2 (see the Phase 5 plan status); L2 now has a probe (`/debug/loop-lag`).
- Auto Run: up to **20 PDFs** per batch (`MAX_AUTORUN_BATCH_FILES`, default 20), still
  **5 at a time**, the next starts when one finishes; the wizard reads both limits
  from the server. If the Space has `MAX_AUTORUN_BATCH_FILES=10` set as a variable, change it.
- "Download results" (Results page + batch view): one zip, choose steps
  (default Step 6) and files (default workbooks only), pick PDFs. `POST /results/download`.
- **C1 — cost recording fixed**: rows used the exact key `step{N}` (most modules
  log `step2_batch_p…`, `step6_all_pages_scan`, `cc_checker`…) → most steps saved as $0,
  and each re-run re-saved the running total. Now: this run's calls only, one row per
  step (Step 2 run → rows "2" + "3"). Cost file reloaded from Storage after a restart.
  Weekly chart from SQL `recorded_at`. Project / dashboard / batch views share one summary.
- **C2 — open: repair old cost rows**: Costs drawer (no project open) → "Repair cost
  history" → Check → Apply. Rebuilds rows from `step_call_logs` or the cost file.

## 2. Exam papers / MBset export (`exam-papers-sections-numbering-plan.md`)

| # | Item | Why it is open |
|---|---|---|
| E1 | **Live run on gyneco** | Phases 0-6 shipped, never run on a real PDF: the local OpenRouter key returns 401. Run with a valid key (per-course splits from `split_gyneco_2025.py`, Document type = QCM classé, Vision OCR + overwrite, Step 6 last_page) and check the MBset import file against the template. |

## 3. Run isolation / OpenRouter client (`bdb9bc6`)

| # | Item | Why it is open |
|---|---|---|
| R1 | **Local OpenRouter key invalid** | `.env` key returns 401 "User not found"; `tests/test_step7.py` fails because of it. Replace the key (Settings or `.env`). |
| R2 | **`STEP2_PARALLEL` validation** | Opt-in (default 1). Before making it the default: run one PDF sequential and parallel, diff `all_qcms.json`. |
| R3 | **Versioned prompt files / Step 3 prompt reorder** | Deliberately not done: CC characterization tests pin the Step 3 prompt text. |
| R4 | **Pre-existing failing tests** | `test_resume_loss_fixes` (3), `test_step2::test_step2_extraction`, `test_step2_fallback_promotion`, `test_step6` (+ `test_step7`, see R1). `test_llama_client` and `test_cc_v4_anchors` don't import. Baseline: `pytest tests --ignore=tests/test_llama_client.py --ignore=tests/test_cc_v4_anchors.py` → 7 failed, 170 passed, 1 skipped. |

## 4. Housekeeping

| # | Item |
|---|---|
| H1 | Branch `fix/run-isolation-openrouter-client` is merged into `origin/main` by fast-forward (`a094d1c`); delete the branch or keep working on `main`. |
| H2 | Uncommitted local files not part of any feature: `CC_MODEL_KNOBS_AND_THINKING.md`, `api/migrations/2026_09_13_step_call_logs.sql`, `docs/plans/batch-history-storage-fallback-resume-project-plan.md` (modified), plus untracked notes / PDFs / `frontend/*.tsbuildinfo`, `frontend/vite.config.js`, `frontend/vite.config.d.ts` (build artefacts — add to `.gitignore`). |
