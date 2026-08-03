# Session Resume — QCM Extractor (for next conversation)

> **Purpose:** give the next AI conversation full context about what was done, where to push, and which directories to edit vs ignore. Paste this file's content as the first message.

---

## 1. What we are building

A QCM (medical exam) extraction pipeline at `C:\Users\ayoub\OneDrive\Documents\ayoub\banque charaque\New folder\resi2016\qcm_extractor`. The app runs on HuggingFace Spaces (backend: FastAPI + Python, frontend: React + Vite + TypeScript). Data persists in Supabase (Postgres + Storage). The pipeline has steps 1 → 2 → 6 → 7 → 8 visible in the UI, plus invisible backend steps 1.5, 1.6 (run in the autorun sequence) and 3, 4, 5 (run in the Step 2 cascade).

---

## 2. What was accomplished this session

### Merge Step 2 + Step 3 (the main feature)

Step 3 (Metadata Detection) was merged into Step 2 as an invisible backend cascade. The user now sees one row "Step 2 · QCM Extraction + Metadata" instead of two. After Step 2 succeeds, the backend automatically runs Step 3 (metadata) + Step 4/5 (template + JSON build) and surfaces the final `merged_qcms.xlsx` in the Step 2 output viewer.

**Commits (in order, all on `main`):**

| Commit | Description |
|---|---|
| `3f6e185` | Cleanup: deleted dead `modules/step2_5_qcm_merger.py` + its import in `step2_qcm_extract.py` |
| `f7fd334` | Backend: new `modules/post_step2_metadata.py` + `tests/test_post_step2_metadata.py` (5 tests); cascade moved from `step_id=="3"` to `step_id=="2"` in `api/real_api.py`; autorun sequence trimmed to `[1,1.5,1.6,2,6,7,8]`; `/steps/3/run` returns HTTP 410; `step_map["3"]` removed |
| `f477a4f` | Frontend: `pipelineStore.ts` Step 2+3 rows collapsed + store key v2→v3; new `Step2_3Config.tsx` combined panel; `CONFIG_MAP['3']` removed; autorun UI drops Step 3; `StepRangeSelector` ALLOWED_STEPS=[1,2,6,7,8] |
| `4dc0aa6` | Fix: defer `set_done("2")` until after cascade completes (WebSocket was closing early, hiding cascade logs) |
| `be4ba79` | Fix: copy `merged_qcms.xlsx` + `.json` into `step2_qcm/accepted/` so Step 2 OutputViewer shows them |
| `6001299` | Fix: OCR cache cleared when user confirms overwrite (`force_overwrite` flows frontend → backend → `OCRCache.clear()`) |
| `382f76e` | Fix: `STEP2_MAX_TOKENS` 20000→40000 (80-QCM exams were truncating the last ~10); added to `EDITABLE_KEYS` |
| `683a557` | Fix: Step 6 correction page scorer now handles OCR-mangled French (`Corrigé`→`CorrigAc`) + markdown-table rows (`| 1 | ADE |`); model dropdown shows primary+fallback for all sources; `STEP6_ALL_PAGES_MAX_TOKENS` added to `EDITABLE_KEYS` |
| `d4dda42` | Fix: `STEP6_ALL_PAGES_MAX_TOKENS` 4000→40000 |
| `98d92d0` | Fix: `ProjectContext.base_path` uses `/app/output` on HuggingFace (was relative `output/`, causing "File not found" in Step 6) |

### Hide Steps 1.5 + 1.6 from the UI (this session — commit `80f5370` on `space` / `5e8cc9d` on `frontend-repo`)

Steps 1.5 (Text Fixer) and 1.6 (OCR Corrector) are now **invisible**. They no longer appear as clickable rows in the pipeline list, progress bar, or ConfigPanel — same pattern as Steps 3/4/5. They still **run as backend steps** in the autorun sequence below a Step 1→2 run; the user just can't see or trigger them manually.

**Frontend-only change (4 files, all pushed to `space` + `frontend-repo`):**

| File | What changed |
|---|---|
| `frontend/src/store/pipelineStore.ts` | `INITIAL_STEPS` drops the `1.5`/`1.6` rows. Persist `version` 6→7: `migrate()` maps any persisted `activeStepId` of `1.5`/`1.6` → `1`. `StepId` type still allows 1.5/1.6 (polling compatibility) but they're unreachable in the UI. |
| `frontend/src/components/pipeline/ConfigPanel.tsx` | `CONFIG_MAP` drops `'1.5'`/`'1.6'` (were `StepRunOnly`). `isRunDisabled` no longer special-cases 1.5. |
| `frontend/src/components/pipeline/StepList.tsx` | Removed the whole "auto-trigger Step 1.5 after Step 1 finishes" block (27 lines, called `runStep(1.5)`). Step 1 row shows badge "(+ auto 1.5/1.6)". `showRunButton` no longer excludes 1.5. |
| `frontend/src/components/dashboard/ProjectProgressCard.tsx` | Progress segments `[1,1.5,1.6,2,3,6,7,8]` → `[1,2,3,6,7,8]`. Still maps hidden last_step 4/5 → visible Step 3. |

**Backend untouched.** `api/real_api.py` autorun sequence still `["1","1.5","1.6","2","6","7","8"]`. Steps 1.5/1.6 fire invisibly like Steps 3/4/5. If the user never wants 1.5/1.6 to run at all, they must be dropped **server-side** from the autorun sequence — that's NOT done yet (left as a decision for a future session).

> ⚠️ **Known consequence:** because 1.5/1.6 are now invisible, the UI can no longer trigger them manually. If a bug in 1.5/1.6 appears, the fix is in `modules/step1_5_*.py` / `modules/step1_6_*.py` (backend), not the frontend config.

### Plans written (read these first)

| File | What it is |
|---|---|
| `MERGE_STEP2_STEP3_REPORT.md` | Full analysis + implementation plan for the Step 2+3 merge. All decisions locked. §6 has the PR breakdown. §9 has Q&A. §11 explains Q3/Q4/Q5 decisions. |
| `AI_AUTORUN_PLAN.md` | Plan for a LangGraph-based AI auto-run orchestrator (DeepSeek). PR #4–#7. Starts AFTER the merge ships. §15 has locked decisions (PostgresSaver, `_extract_page` helper, orchestrator-only). |
| `STEP6_FIXES_REPORT.md` | Explains the three Step 6 fixes (OCR scoring, model dropdown, max tokens). |
| `PUSH_STATUS_REPORT.md` | Push status for all three remotes (HF ✅, frontend-repo ✅, origin ❌ blocked by pre-existing secrets). |

---

## 3. Where to push — THE MOST IMPORTANT SECTION

There are **three** git remotes. Do NOT mix them up.

### Remote 1: `space` (HuggingFace — the deploy target)

```
git push space main --force
```

- **This is where the backend + frontend both deploy.** Always force-push here after any change.
- URL: `https://huggingface.co/spaces/ayoubi8/qcm-extractor`
- The Space rebuilds automatically on push (Docker container, ~2-5 min).
- The `.env` file is gitignored (has secrets). On container startup, `.env` is restored from Supabase Storage `config/.env`. So env var changes (like `STEP2_MAX_TOKENS`) must be set via the **Settings UI** (which writes to both live `os.environ` and Supabase `config/.env`) — not just edited in the repo `.env`.

### Remote 2: `frontend-repo` (GitHub — frontend-only mirror)

```
# Frontend-only changes must ALSO be pushed here separately.
# This repo has different history (no api/ or modules/ dirs).
# Method: use a git worktree from frontend-repo/main, copy files, commit, push.
# See the worktree method used in previous commits.
```

- URL: `https://github.com/ayoubi8/qcm-extractor-frontend.git`
- Contains ONLY frontend files (`src/`, `package.json`, `index.html`, etc.).
- Push frontend changes here using the **worktree method** (see §5 below).

### Remote 3: `origin` (GitHub — backend mirror, CURRENTLY BLOCKED)

```
git push origin main --force
# ❌ BLOCKED by GitHub Push Protection — pre-existing secrets in commit 47e9118
# (OpenRouter API key in API_KEY_SETUP.md + GCP keys in Refining QCM Extraction System Design.md)
# Unblock via: https://github.com/ayoubi8/clean_repo-qcm-extractore/security/secret-scanning/unblock-secret/...
```

- URL: `https://github.com/ayoubi8/clean_repo-qcm-extractore.git`
- **Do NOT push here** until the secrets issue is resolved (see `PUSH_STATUS_REPORT.md` §"How to unblock origin").
- This is NOT a deploy target — just a backup mirror. HuggingFace is the real deploy.

### Summary: what to push where

| Change type | `space` (HF) | `frontend-repo` (GitHub) | `origin` (GitHub) |
|---|---|---|---|
| Backend only (`api/`, `modules/`, `tests/`) | ✅ `git push space main --force` | ❌ No | ❌ Blocked |
| Frontend only (`frontend/src/...`) | ✅ `git push space main --force` | ✅ Worktree method | ❌ Blocked |
| Both | ✅ `git push space main --force` | ✅ Worktree method | ❌ Blocked |

---

## 4. Which directories to EDIT vs IGNORE

### ✅ EDIT (these are the active codebase)

| Path | What it is |
|---|---|
| `api/` | FastAPI backend (real_api.py, auth.py, env_manager.py, project_manager.py, job_manager.py, etc.) |
| `modules/` | Pipeline step modules (step1_extraction.py, step2_qcm_extract_batch.py, step3_metadata.py, step6_corrections.py, etc.) + utils (project_context.py, cost_tracker.py, ocr_cache.py, etc.) |
| `tests/` | Python tests |
| `frontend/src/` | React frontend (components, store, types, lib, hooks) |
| `frontend/package.json` | Frontend dependencies |
| `.env` | Local env file (gitignored — has secrets). Edit directly for local testing. |
| `.env.example` | Template — committed to repo. Keep in sync with `.env` structure. |
| `suport/` | Reference databases (modules-bio-chir-med.json) + API stub |

### ❌ DO NOT EDIT / IGNORE (stale, snapshots, or irrelevant)

| Path | Why to ignore |
|---|---|
| `new-version/` | **STALE SNAPSHOT** — an older copy of the entire repo (pre-Step 4/5 merge). Its `real_api.py` still has `"4","5"` in the autorun sequence, its `types/index.ts` still lists `4|5` in StepId. **Never edit this. Never push this.** Q6 decision: leave untouched. |
| `re emgeeenr qcms extractore 2/` | Design docs (RED_LINES, SYSTEM_MIND_MAP, etc.). Reference only. |
| `exported_chats/` | Exported AI chat logs. Reference only. |
| `c.md` | An old verification report. Superseded by `MERGE_STEP2_STEP3_REPORT.md`. |
| `MERGE_STEP4_STEP5_PLAN.md` | Already shipped (commit `03ae349`). Reference only. |
| `MERGE_STEP4_STEP5_TEST_REPORT.md` | Already shipped. Reference only. |
| `implementation_plan.md` | Old Step 8 restore fix plan. Reference only. |
| `codebase_tree.md` / `clean_codebase_tree.md` | Stale codebase maps. Ignore. |
| `*.backup.gz` / `*.storage.zip` | Database backups. Ignore. |
| `tlemcen courses/` | Unrelated. Ignore. |

### ⚠️ Gitignored but important

| Path | Note |
|---|---|
| `.env` | Has secrets. Gitignored. On HuggingFace, restored from Supabase `config/.env` on startup. To change env vars on HF: use the **Settings UI** (PUT /env), not a git push. |
| `.cache/ocr/` | OCR cache. Keyed on PDF content hash + page. Cleared when `force_overwrite=true` is sent from frontend. |
| `frontend/node_modules/` | NPM deps. Ignore. |
| `frontend/dist/` | Build output. Ignore. |

---

## 5. How to push frontend changes to `frontend-repo` (worktree method)

The frontend repo has **different history** (no `api/` or `modules/`). You cannot push the main repo's commits directly. Use this method:

```powershell
# 1. Create a temp worktree from frontend-repo/main
$tmp = "C:\Users\ayoub\AppData\Local\Temp\opencode\fe-push"
if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
git worktree add $tmp frontend-repo/main
git -C $tmp checkout -b temp-branch

# 2. Copy changed frontend files from the main repo into the worktree
$files = @(
  "src\components\pipeline\configs\Step6Config.tsx",
  "src\components\pipeline\ConfigPanel.tsx"
  # ... add all changed frontend files
)
$src = "C:\Users\ayoub\OneDrive\Documents\ayoub\banque charaque\New folder\resi2016\qcm_extractor\frontend"
foreach ($f in $files) {
  Copy-Item -LiteralPath (Join-Path $src $f) -Destination (Join-Path $tmp $f) -Force
}

# 3. Commit + push
git -C $tmp add -A
git -C $tmp commit -m "fix: describe the change"
git -C $tmp push frontend-repo temp-branch:main

# 4. Clean up
git -C $tmp checkout --detach
git worktree remove $tmp --force
git worktree prune
```

---

## 6. Current state of the pipeline

| Step | Status | Notes |
|---|---|---|
| 1 | ✅ Working | OCR cache clear on overwrite now works. `force_overwrite` flows from frontend. Shows "(+ auto 1.5/1.6)" badge. |
| 1.5 | ✅ Working, invisible | Fires behind the scenes in the autorun sequence. **No UI row** since commit `80f5370`. Manual `runStep(1.5)` removed from frontend. |
| 1.6 | ✅ Working, invisible | Same as 1.5. No UI row. **Not removed from backend autorun sequence** — that's a future-session decision if unwanted. |
| 2 | ✅ Working | Merged with Step 3. Cascade fires after extraction. `merged_qcms.xlsx` surfaces in OutputViewer. `STEP2_MAX_TOKENS=40000`. |
| 3 | ✅ Invisible | Fires inside Step 2's cascade (`run_post_step2_metadata`). No standalone endpoint (410). Q8 fast-path: skips if `step3_metadata/accepted/*.json` exists. |
| 4 | ✅ Invisible | Fires inside Step 3's cascade (`run_post_step3_build`). |
| 5 | ✅ Invisible | Fires inside Step 3's cascade. |
| 6 | ⚠️ Partially fixed | OCR-tolerant scorer + model dropdown + max tokens fixed. `ProjectContext` path fix should resolve "File not found". **Needs end-to-end testing on HF after rebuild.** |
| 7 | ✅ Working | Categorization using modules-bio-chir-med.json. |
| 8 | ✅ Working | Similarity matcher. Reads step7 > step6 > step5. |

### Known issues remaining (what the next conversation should tackle)

1. **Step 6 end-to-end test** — after the HF rebuild, verify that Step 6 with source=Auto-Detect (or Page Text + All Pages scan) actually finds page_7.txt corrections and applies them. The path fix (`98d92d0`) + scorer fix (`683a557`) should resolve it, but it has not been verified on HF yet.
2. **Decide whether Steps 1.5/1.6 should still run at all** — they're now hidden from the UI (`80f5370`) but **still fire in the backend autorun sequence** (`api/real_api.py` → `["1","1.5","1.6","2",...]`). If the product wants them fully gone, remove them server-side. This is the one intentional loose end from this session.
3. **`origin` push blocked** — pre-existing secrets in commit `47e9118`. See `PUSH_STATUS_REPORT.md` for unblock instructions. Low priority (HF is the deploy target).
4. **Pre-existing `test_step2.py` bug** — `Step2QCMExtract.__init__` line 19 references `self.client.model` but `self.client` is never instantiated. Pre-existing, not introduced by this session. Low priority.
5. **PR #4–#7 (AI Auto-Run Orchestrator)** — the LangGraph plan in `AI_AUTORUN_PLAN.md` is ready. Decisions Q-A2 (PostgresSaver), Q-A3 (`_extract_page` helper), Q-A4 (orchestrator-only) are locked. Starts after the merge is verified end-to-end.
6. **Settings UI env override** — after any HF rebuild, env var changes (like `STEP6_ALL_PAGES_MAX_TOKENS=40000`) must be set via the Settings UI (PUT /env endpoint) to persist in Supabase `config/.env`. The repo `.env` is gitignored and won't reach HF via git.
7. **Steps 3/4/5 invisible + Step 1.5/1.6 invisible** — verify the whole autorun chain (1→1.5→1.6→2→3→4/5→6→7→8) end-to-end on HF after the last rebuild, since the UI no longer shows progress for the hidden steps.

---

## 7. Key environment variables (current values)

| Var | Value | Set where |
|---|---|---|
| `STEP2_MODEL` | `google/gemini-2.0-flash-lite-001` | `.env` + Settings UI |
| `STEP2_MAX_TOKENS` | `40000` | `.env` (local) / Settings UI (HF) |
| `STEP6_TEXT_MODEL` | `nvidia/nemotron-3-nano-30b-a3b:free` | `.env` |
| `STEP6_ALL_PAGES_MODEL` | `deepseek/deepseek-v4-flash` | `.env` |
| `STEP6_ALL_PAGES_MAX_TOKENS` | `40000` | `.env` (local) / Settings UI (HF) |
| `STEP6_AI_MODEL` | `deepseek/deepseek-r1-distill-llama-70b` | `.env` |
| `STEP1_MODEL` | `qwen/qwen3-vl-30b-a3b-instruct` | `.env` |
| `OPENROUTER_API_KEY` | `sk-or-v1-...` (masked) | `.env` + Settings UI |

> **Remember:** `.env` is gitignored. To change vars on HuggingFace, use the Settings UI (which calls `PUT /env`) so they persist in Supabase Storage `config/.env`.

---

## 8. Quick reference: key files changed this session

| File | What changed |
|---|---|
| `modules/post_step2_metadata.py` | NEW — the Step 2→3→4/5 cascade entrypoint |
| `modules/step2_qcm_extract.py` | Removed Step2_5QCMMerger import + call |
| `modules/utils/project_context.py` | `base_path` uses `/app/output` on HuggingFace |
| `modules/utils/ocr_cache.py` | Added `clear(pdf_path)` method |
| `modules/step1_extraction.py` | Added `force_overwrite` param → clears OCR cache |
| `modules/step6_corrections.py` | Rewrote `_score_correction_page()` for OCR-tolerant scoring |
| `api/real_api.py` | Cascade block, autorun sequence, Step 3 route 410, model overrides, step-models endpoint |
| `api/env_manager.py` | Added `STEP2_MAX_TOKENS`, `STEP6_ALL_PAGES_MAX_TOKENS`, `STEP6_AI_MAX_TOKENS` to EDITABLE_KEYS |
| `frontend/src/store/pipelineStore.ts` | Step 2+3 rows collapsed, store v3, migrate() |
| `frontend/src/components/pipeline/configs/Step2_3Config.tsx` | NEW — combined panel |
| `frontend/src/components/pipeline/ConfigPanel.tsx` | CONFIG_MAP '3' removed, Step 2 forwards step3 config + force_overwrite |
| `frontend/src/components/pipeline/StepList.tsx` | Step 2 forwards step3 config + force_overwrite |
| `frontend/src/components/pipeline/configs/Step6Config.tsx` | Model dropdown shows primary + fallback |
| `frontend/src/components/autorun/StepRangeSelector.tsx` | ALLOWED_STEPS=[1,2,6,7,8] |
| `frontend/src/components/autorun/AutoRunPanel.tsx` | Step 3 pre-flight removed, step3 config travels in step2 |
| `frontend/src/store/autorunStore.ts` | ALLOWED_STEPS=[1,2,6,7,8], migrate v2 |
| `frontend/src/types/index.ts` | StepId keeps 3, AutoRunPayload.run_config.step3 removed |
| `tests/test_post_step2_metadata.py` | NEW — 5 tests for the cascade |

**This session (hide Steps 1.5/1.6 — commit `80f5370`/`5e8cc9d`):**

| File | What changed |
|---|---|
| `frontend/src/store/pipelineStore.ts` | `INITIAL_STEPS` drops 1.5/1.6 rows; persist v6→v7 migrate activeStepId 1.5/1.6→1 |
| `frontend/src/components/pipeline/ConfigPanel.tsx` | `CONFIG_MAP` drops '1.5'/'1.6' |
| `frontend/src/components/pipeline/StepList.tsx` | Removed auto-trigger Step 1.5 block; badge "(+ auto 1.5/1.6)" on Step 1 |
| `frontend/src/components/dashboard/ProjectProgressCard.tsx` | Segments `[1,2,3,6,7,8]` |

---

## 9. Instructions for the next conversation

1. **Read this file first** — it has everything you need.
2. **Read `AI_AUTORUN_PLAN.md`** if starting PR #4.
3. **Edit only the active directories** listed in §4. **Never touch `new-version/`.**
4. **Push to `space`** (HuggingFace) for all changes. **Push to `frontend-repo`** (GitHub) for frontend-only changes using the worktree method (§5). **Do NOT push to `origin`** (blocked).
5. **Test on HuggingFace** after each push — wait for the rebuild (~2-5 min), then run the relevant step.
6. **Env vars on HF** — set via Settings UI, not git.
7. **Force-push is normal** for `space` — the local main has diverged from the remote, and force-push is the standard pattern used in this session.
8. **Steps 1.5/1.6 are UI-invisible** (as of `80f5370`). To toggle whether they still run at all, edit the **backend** autorun sequence in `api/real_api.py` (`["1","1.5","1.6","2",...]`) — NOT the frontend config.