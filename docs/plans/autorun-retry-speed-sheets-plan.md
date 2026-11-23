# Auto Run: retry, Step 6 results, speed, Sheets quota and top bar

Status (2026-11-23): **implemented locally, not committed or deployed, not run on a real PDF.**
Decisions: D1 = no, D2 = no.

Still open from Phase 5, because each needs a valid OpenRouter key and a live comparison:
the speed baseline, `STEP2_PARALLEL=3` with a global AI-call limit, shorter Step 6 timeouts,
sending only unanswered QCMs to AI, and `STEP_RUNNER=process`.

Evidence level: the causes below come from reading the code. The live Hugging Face
logs, Space variables and Supabase rows were not inspected, so anything marked
**to confirm** must be checked on the Space before or during that phase.

## 1. Findings

### F1. Step 6 can report "done" after applying no corrections

| # | Cause | Where |
|---|---|---|
| a | **Main suspect.** Step 6 reads `step1_extraction/accepted/page_*.txt`, but its restore list only contains `step5_json` and `step6_corrections`. After a Space restart wipes the disk, Step 6 finds no pages. | `api/real_api.py:1962`, `modules/step6_corrections.py:1070` |
| b | Every "nothing found" path returns the QCMs unchanged, so the run is recorded as a success. | `modules/step6_corrections.py:735,767,1003,1063,1072,1294` |
| c | The Step 6 badge is always `success`, without counting answers. | `api/real_api.py:1388` |
| d | `str(q.get("Correct", ""))` turns `null` into `"None"`, so unanswered QCMs count as corrected. The workbook name can therefore show a false count. | `modules/step6_corrections.py:179,291` |
| e | A manual Step 6 rerun never updates the batch manifest, so the batch card keeps its old state. | `_run_step_task` has no manifest write |

**To confirm:** the file 1 rerun log should contain `No page_*.txt files found`,
`File not found`, or `No corrections found`.

### F2. Retry can skip a failed step or redo a finished one

- A step counts as done if its folder contains anything (`api/autorun_batch.py:463-470`).
  A failed step with partial files, or an empty `accepted/` folder created by
  `get_path`, therefore counts as done.
- Only badge `success` is accepted (`api/autorun_batch.py:500`). Step 2 is often
  `warning`, because `correction_pages.json` is not a list and is counted as an empty page
  (`api/real_api.py:1374-1382`). After a restart, the local fallback also fails and
  **Step 2 runs and is billed again**. This probably explains AR_01 and AR_02 in the
  screenshot (**to confirm**).
- Retry leaves the old Step 6 error chip visible while earlier steps run.
- A retry started while the batch runs uses its own semaphore, so it bypasses the 5-PDF
  limit (`api/autorun_batch.py:740`). Nothing finalises the batch when that retry ends.

### F3. Why Auto Run is slow

Ordered by expected impact. Phase 5 measures them before changing behaviour.

1. **Step 2 is sequential:** one AI call per page, because `STEP2_PARALLEL` defaults to 1.
2. **Step 6 sends almost every page to AI, one at a time.** Each prompt repeats the full
   QCM list and running answers. AI is skipped only if one page covers *all* QCMs
   (`modules/step6_corrections.py:1172-1189`). This is slow and uses many tokens.
3. **Blocking work runs on the event loop:** manifest writes, Storage and SQL calls, Drive
   download, and post-step recording (`api/autorun_batch.py:614-650`,
   `api/real_api.py:2544-2581`). Each one pauses all PDFs' coordination and the website.
4. **Repeated file copying:** Steps 1, 1.5 and 1.6 share a folder, so each archives and
   re-uploads all pages, one file at a time (`api/real_api.py:2296-2311,1931-1941`).
5. **Long stalls on bad calls:** 180 s read timeout, 3 transport attempts, inside
   Step 2's own retries and fallback.
6. **Shared thread pool:** in the default `thread` runner, long steps and post-step
   uploads share Python's default executor. Space CPU and `STEP_RUNNER` are **to confirm**.

### F4. Google Sheets error

The error is real: the connected Google account's Drive is full, so Google refuses a new
file. Code cannot bypass that. The app can explain it, offer the xlsx, and create fewer
duplicates. A new Sheet is currently created whenever the filename changes, and the
filename contains the QCM count (`api/real_api.py:4163-4164`).

## 2. Implementation plan

### Phase 1. Top bar (small)

- `frontend/src/pages/ProjectWorkspace.tsx`: delete the whole `h-14` bar, including
  **Auto Run**, plus unused `autorunUrl` and `outputsUrl` imports.
- `frontend/src/components/shell/TopBar.tsx`: add `btn-open-results` with the same styling,
  before **Switch Project**. Show it only when a project is active and link it to
  `outputsUrl(activeProject.name)`.
- Keep the `/projects/:name/autorun` route for old links. New batches stay reachable from
  `/autorun/new`.

### Phase 2. Make Step 6 truthful

1. Add `("step1_extraction", "accepted")` and `("step2_qcm", "accepted")` to Step 6's
   restore list.
2. Fail clearly when page text is missing, instead of writing an unchanged result.
3. Replace the `Correct` checks with a shared helper that treats `null`, empty and `"None"`
   as unanswered.
4. Return `corrected`, `missing` and `total`. Badge: `error` for 0 corrected, `warning` for
   partial, `success` for complete.
5. Show `X/Y corrected` on the batch card and in the Step 6 result.
6. If `last_page` finds 0 corrections, retry once with Auto-Detect (**decision D2**).
7. Keep the user's existing answers and Sheet edits on every rerun.

### Phase 3. Reliable step state

1. One shared rule: the latest SQL result decides. `success` and `warning` are done;
   `error`, `stopped` and `cancelled` are not.
2. Use the folder check only when no SQL row exists, and require the step's real output
   file rather than any folder entry.
3. Stop counting `correction_pages.json` as an empty Step 2 page.
4. Manual step runs update the matching batch manifest.
5. On retry, clear chips from the re-entry step onward.

### Phase 4. "Retry failed" button

**Backend:** `POST /autorun/batches/{id}/retry-failed`

- Selects PDFs in `error`, `cancelled`, or with 0 corrections (**decision D1**).
- Never touches running or fully completed PDFs.
- Marks all selected PDFs in one manifest write, then runs them through **one shared
  5-slot queue**, including when the batch is already running.
- Each PDF restarts at its first failed step, so finished paid steps are not repeated.
- Returns `queued` and `skipped` with reasons, and finalises the batch after the last PDF.
- Double-click safe and rate-limited.

**Frontend:** in the Auto Run Batch header, add **Retry failed (N)**. Hide it at N = 0,
show progress while starting, then resume polling and refresh costs.

### Phase 5. Speed

1. **Baseline first:** time one PDF per step from `step_call_logs`, plus `/debug/loop-lag`.
2. Move all blocking batch and post-step work off the event loop.
3. Step 6: scan Step 2's answer-key pages and high-scoring pages first, stop when all QCMs
   are answered, and send only missing QCMs to AI. Fall back to all pages if answers remain
   missing.
4. Archive Step 1 once per pipeline pass and upload with a small worker pool.
5. Add a global AI-call limit, then test `STEP2_PARALLEL=3`. Enable it only if
   `all_qcms.json` matches the sequential run on the same PDF (open item R2).
6. Lower the timeout for small Step 6 calls and fail over to the fallback model sooner.
7. Test `STEP_RUNNER=process` on one 5-PDF batch, and keep it only if Space memory holds.

### Phase 6. Sheets quota

1. Detect `storageQuotaExceeded` and return a clear `DRIVE_QUOTA_EXCEEDED` error.
2. Show: "Your Google Drive is full. Free space or connect another account", with
   **Download xlsx** and **Open Drive storage** actions.
3. Add **Disconnect Google account**, since no disconnect route exists today.
4. Reuse one Sheet per project and step even when the QCM count changes in the filename.

## 3. Tests and acceptance

- Restart simulation: Step 6 restores pages and applies corrections.
- Missing pages produce a visible failure, and 0 corrections never shows as complete.
- `null` is never counted as an answer.
- Retry after a Step 6 failure does **not** rerun Steps 1 or 2.
- Retry-all with 6 PDFs never exceeds 5 running and ends in the correct batch state.
- Parallel Step 2 output matches sequential output before it is enabled.
- Compare against the known failing-test baseline in `open-items-2026-11.md`.
- Live check: rerun AR_01, AR_02, AR_04 and AR_06, then verify the answers in Results.

## 4. Decisions

- **D1. Include completed files with 0 corrections in Retry failed?** Recommended: yes.
- **D2. If `last_page` finds nothing, try Auto-Detect automatically?** Recommended: yes.
  It adds a small AI cost only for files that would otherwise have no answers.

## 5. Delivery order

Phase 1 → 2 → 3 → 4 → 5 → 6. Phases 2 to 4 should ship together, because the button is
unsafe until step state is reliable. Do not press the existing Retry on AR_04 or AR_06
before Phase 3 if avoiding another Step 2 charge matters.
