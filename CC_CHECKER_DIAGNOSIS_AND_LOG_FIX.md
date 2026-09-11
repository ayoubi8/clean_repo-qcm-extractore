# CC Checker silence — diagnosis from HF logs + execution_log fix

## What the HF container logs proved

The Step 2 re-run (`rattrapage_gyneco_(avec_CT)`, 50 QCMs, `+0 new | 2 updated`)
fired both idempotency skips:

- `Step 3 ... skipping Step 3 (Q8 fast-path)` — Step 2 uid set unchanged from
  the previous run.
- `[CC-CHECK] Previous verification already covers this exact QCM set —
  skipping` — `step3_metadata/clinical_case_verification.json` already covers
  these 50 uids, so the checker returned `skipped` with **zero LLM calls**.

New fact from the log order: the skip message appears *after* chain-building,
so **chains exist** — some of the 50 QCMs do carry `cas` from the earlier
Step 3 run. The checker is not broken: it verified on the first run (check
OpenRouter history for that run, filtered by the CC model) and correctly
skipped the re-run.

To force a real re-verify: delete
`step3_metadata/clinical_case_verification.json` and re-run Step 2 (also
delete `step3_metadata/accepted/` to force fresh Step 3 detection too).

## Why execution_log showed nothing (root cause)

`ws_log` (`api/real_api.py:2354`) streams only `job_manager` log lines, which
come from `log_callback` and from `LogCapture` — and `LogCapture` wrapped
**only `_call_step`** (`api/real_api.py:1797-1805`).

The cascade (`run_post_step2_metadata` → hint → cas-split → Step 3 →
checker → build, `api/real_api.py:1924+`) runs **after** that capture context
exits. Its `print()`s went to container stdout (HF Space logs), never to the
UI. The only cascade lines execution_log ever received were the explicit
`log_callback` ones (`Step 2 completed`, `Auto-enrich ... completed`).

## The fix (implemented in `api/real_api.py`, uncommitted at time of writing)

Wrapped the Step 2 cascade block in `with LogCapture(log_callback)` — the
same capture used for step output. Next run, execution_log streams the full
cascade live:

- hint / cas-split summaries,
- Step 3 progress or Q8-skip notice,
- checker header with `Parallel verification: N chain(s), max 5 concurrent`,
- per-QCM verdict lines (`belongs`, `provisional NO`, `closed early —
  N calls saved`),
- the verification summary block (`Closed early`, `LLM calls made/saved`,
  `Re-checked`),
- the `[CASCADE-TRACE]` markers.

`set_done` still fires last, so the WS drains every line before closing.

## Deploy note

None of this runs on HF until the local commits are pushed to the `space`
remote and the Space rebuilds (local `main` was `[ahead 1]` of `space/main`
at diagnosis time).
