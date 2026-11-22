# Plan — Phase 5: run pipeline steps outside the API process

Lag plan Phase 5 / B4 (`frontend-routes-and-switch-lag-plan.md` §4, §6).
Goal: **the website answers as fast during a run as when idle.**

---

**Status 2026-11-23 — steps 5.0-5.2 implemented (uncommitted), 5.3-5.4 pending:**
- 5.0 `api/loop_lag.py` + `GET /debug/loop-lag` (admin): event-loop lag p50/p95/p99
  over the last minute, `[LOOP-LAG]` log above 200 ms. Numbers (§8) still to record.
- 5.1/5.2 `api/step_process.py`: one `core_sequence` (`_call_step` + Step 2
  cascade) run in a thread (`STEP_RUNNER=thread`, default) or a spawned child
  (`STEP_RUNNER=process`); event protocol, stop flag, cancel grace +
  terminate/kill, crash → `error`, dead-child watchdog, `MAX_STEP_PROCESSES`
  semaphore, child's AI-call costs sent back and merged. `_run_step_task`
  handles the events; everything around the core is unchanged.
  Deviation: the core still imports `_call_step` from `real_api` inside the
  child (4 s import measured locally) instead of a new `step_exec.py` — fewer
  moved lines; revisit if spawn time matters.
- Tests: `tests/test_step_process.py` (17, both modes incl. real spawn on
  Windows), `tests/test_run_step_task_runner.py` (3, `_run_step_task` end to end).
- Next: 5.3 — set `STEP_RUNNER=process` on the Space, run one PDF both ways,
  diff outputs, fill §8; then 5.4 flip the default.
- Cost recording fixed on the way (see open-items C1).

## 1. Why the site is slow during a run (verified in code)

The HF Space runs **one uvicorn process** (`Dockerfile`: `uvicorn real_api:app`,
no workers) on `cpu-basic` (2 vCPU, 16 GB, ephemeral disk). Everything shares
that process:

```
POST /steps/{id}/run ─► asyncio.ensure_future(_run_step_task)      real_api.py:2164
   _run_step_task (event loop)
     ├─ archive / restore PDF + inputs / Sheets sync   run_in_executor (I/O)
     ├─ _run_with_capture → _call_step(...)            run_in_executor  ◄── CPU heavy
     ├─ Step 2 → run_post_step2_metadata (3, 4, 5)     run_in_executor  ◄── CPU heavy
     ├─ _do_post_step: upload folder to Storage        run_in_executor (I/O)
     └─ job_manager.set_done / _record_step_result
Auto Run batch: up to AUTORUN_BATCH_CONCURRENCY (5) of these at once.
```

1. **The GIL.** Steps run in threads of the same process. Image rendering
   (PIL / PDF pages for Vision OCR), base64 encoding, `json` load/dump of
   multi-MB files, openpyxl workbooks, regex over every page are pure Python /
   GIL-holding work. While they run, the event loop thread gets the GIL in
   slices, so every request (auth, `/projects`, `/overview`, WebSocket log
   pushes) waits. A 5-PDF batch = 5 such threads.
2. **One shared default thread pool.** `run_in_executor(None, …)` uses the
   loop's default executor: `min(32, cpu + 4)` = **6 threads on 2 vCPU**.
   5 batch runs + their uploads fill it; any endpoint that also uses it queues
   behind them. (FastAPI's sync endpoints and the B1 auth dependency use
   anyio's separate pool of 40, so they're less affected, but still need the GIL.)
3. **Cancel can't really cancel.** `request_stop("cancelled")` cancels the
   asyncio task, but the worker thread keeps running until its current LLM
   call / page returns (`job_manager.py` comment). A thread can't be killed;
   a process can.
4. **One crash takes everything down.** A segfault or OOM in a native library
   during a run (PDF/image code) kills the API with it.

## 2. Constraints

- HF Spaces: one container, one public port (7860), no Redis, disk wiped on
  restart, every deploy restarts the whole container (API and any worker in it).
- Supabase (Postgres + Storage) is the only durable store.
- Must keep: per-run isolation (`run_env` overlay: the user's API key and
  model overrides), user-scoped job keys (`job_project`), live logs over
  `/ws/log/{project}/{step}`, Stop (keep partial outputs) and Cancel,
  telemetry (`call_logger` context), batch resume on startup.

## 3. Options

| | Option | Fixes 1-4? | Cost | Notes |
|---|---|---|---|---|
| **A** | **One child process per step run**, started by the API; logs/results come back over pipes; job state stays in the API's `job_manager`. | 1 ✓ 2 ✓ 3 ✓ 4 ✓ | Medium, contained in `_run_step_task` | Runs die with the container on deploy — **same as today**; batch auto-resume already handles that. |
| B | Long-lived worker process(es) + a job table (Supabase or local SQLite); API only enqueues and reads logs from the store. | 1-4 ✓, plus runs survive an API-only restart | High: `job_manager`, logs, stop flags, batch runner all move to the store | On HF every deploy restarts the worker too, so the "survives restart" benefit is mostly lost. |
| C | Separate worker Space / server consuming the job table. | 1-4 ✓, scales | Highest + a second paid machine | Only worth it when leaving HF Spaces or needing more CPUs. |

**Recommendation: A now.** It removes all four causes with the smallest
change. B/C stay documented (§9) for when the app outgrows one Space. This
deviates from the original B4 wording ("job table + worker"); the reason is
that on HF a separate worker brings almost nothing over A and costs much more.

## 4. Design (option A)

### 4.1 What moves into the child

Only the **CPU-heavy middle** of `_run_step_task`:
- `_call_step(step_id, tracker, context, config, cancel_check)`
- for Step 2: the `run_post_step2_metadata` cascade (Steps 3 → 4 → 5).

Everything else stays in the API exactly as today (it's I/O, releases the
GIL, and touches API-side caches): archive to `_history`, restore PDF/inputs
from Storage, Sheets sync-before-run, Step 8 ref-DB download, `_do_post_step`
uploads, `_record_step_result`, `step_cache` updates, telemetry row
start/finish, `job_manager` status. Child and API share the container's
disk (`/app/output`), so files written by the child are where the API expects
them.

### 4.2 New module `api/step_process.py`

```
run_in_child(spec: RunSpec, on_log, should_stop) -> RunResult      (awaitable)
  RunSpec   = {user_id, project, step_id, config, env_overlay, run_id,
               call_context, post_step2: bool}
  RunResult = {outcome: done|stopped|cancelled|error, error: str|None,
               post_step2: {...} | None, exit_code}

child_main(spec, conn)          # entry point of the spawned process
```

- **Start method `spawn`** (never `fork`: the API has threads; fork + threads
  deadlocks). The child imports the pipeline modules fresh.
- **Environment.** The child is single-run, so it applies `spec.env_overlay`
  (user's API key, model overrides) **directly to `os.environ`** and also enters
  `run_env.enter_run(overlay)`; modules reading either way see the right
  values. No cross-run leak is possible — the process is private to the run.
- **Logs.** In the child, `LogCapture` (stdout capture) forwards each line
  into a `multiprocessing.Pipe`/`Queue`. In the API, one asyncio task drains
  it (`loop.run_in_executor` on `conn.recv`, or `asyncio` reader on the pipe
  fd) and calls `job_manager.append_log(...)` — the WebSocket endpoint is
  untouched.
- **Stop.** API side `should_stop()` → sets a `multiprocessing.Event`; the
  child's `cancel_check` reads it. Stop mode stays cooperative (partial
  outputs kept, as today).
- **Cancel.** Same event, then a grace period (`STEP_CANCEL_GRACE_S`, default
  10 s); if the child is still alive → `process.terminate()`, then `kill()`
  after 5 s more. Status → `cancelled` immediately in `job_manager` (as today).
- **Crash.** Child exits non-zero without sending a result → `error`, with a
  log line `✖ Step process exited unexpectedly (code N)`; the API keeps serving.
- **Result.** The child sends one final message `{outcome, error, post_step2}`;
  the API then continues with the existing post-step code.
- **Telemetry.** `call_logger.set_call_context(user, project, run_id, step)`
  is called inside the child (today it's set inside the worker thread — same
  place, different process). The `step_run` row is still started/finished by
  the API.
- **Concurrency cap.** `MAX_STEP_PROCESSES` (default = `AUTORUN_BATCH_CONCURRENCY`,
  5) via an `asyncio.Semaphore`; extra runs wait with the log line
  `⏳ Waiting for a free runner (n running)`.
- **Flag.** `STEP_RUNNER=thread|process` (default `thread` until §7 is
  green). `thread` = today's `run_in_executor` path, unchanged.

### 4.3 Refactor needed first

`_run_with_capture` and the post-step-2 call are closures inside the 420-line
`_run_step_task` (`real_api.py:2183-2600`). Extract them into a top-level,
picklable function in a module that does **not** import `real_api`
(`api/step_exec.py`):

```
execute_step_core(spec, log_sink, cancel_check) -> CoreResult
```

Used by both runners (thread: called in the executor; process: called in
`child_main`). This keeps one implementation of "what a step run does".
Everything in it must be importable without starting the FastAPI app
(no `real_api` import at module level — same rule as `autorun_batch.py`).

### 4.4 Other runners

`autorun_batch._spawn_runtime_task` and `_autorun_task` both go through
`_run_step_task`, so batches and the per-project Auto Run get the child
process for free. Step 8 export (`8-export`) and Sheets sync stay in threads
(short, I/O-bound) — revisit only if measurements show them.

### 4.5 Measuring (needed before and after)

- **Loop-lag probe** (new, tiny): an asyncio task that sleeps 100 ms in a loop
  and records how late it wakes up; p50/p99 over the last minute exposed at
  `GET /debug/loop-lag` (admin only) and logged as `[LOOP-LAG]` when p99 > 200 ms.
- `Server-Timing` (already live) on `/projects`, `/projects/{n}/overview`,
  `/bootstrap`, read in DevTools.
- Scenarios: idle; one Step 1 Vision OCR run; one Step 2 run; a 5-PDF batch.

## 5. Steps

| Step | Content | Done when |
|---|---|---|
| 5.0 | Loop-lag probe + record baseline numbers for the 4 scenarios in this file (closes open item L2). | Table of idle vs run numbers filled in §8 |
| 5.1 | Extract `execute_step_core` into `api/step_exec.py`; thread runner calls it. No behaviour change. | Full test baseline unchanged; one real run identical to before |
| 5.2 | `api/step_process.py`: spawn, log pipe + drain task, stop event, cancel grace + terminate, crash handling, result message, semaphore; `STEP_RUNNER` flag (default `thread`). | Unit tests below pass with a fake core |
| 5.3 | Validation on the Space with `STEP_RUNNER=process` (§7). | All §7 checks pass, numbers in §8 meet §6 |
| 5.4 | Default → `process`; keep `thread` as the fallback for one release; then remove it. | One release without regressions |
| 5.5 | Close L3 leftovers that still show in the numbers (blocking `async def` endpoints). | — |

## 6. Done when

- During a 5-PDF batch: p95 of `/projects`, `/projects/{n}/overview`,
  `/bootstrap` ≤ 1.5 × idle, and loop lag p99 < 100 ms.
- Cancel ends a running step within `STEP_CANCEL_GRACE_S + 5 s`, always.
- A crashing step marks itself `error` and the API stays up.
- Outputs of a PDF run in `process` mode are identical to `thread` mode
  (diff `all_qcms.json`, `corrected_qcms.json`, MBset files).

## 7. Tests

Automated (`tests/test_step_process.py`, fake core instead of real steps):
- logs arrive in order in `job_manager`, final status `done`;
- `should_stop` → child sees it, outcome `stopped`, partial file kept;
- cancel with a child that ignores the event → terminated after the grace
  period, status `cancelled`;
- child raises → `error` + message; child `os._exit(3)` → `error`, exit code
  logged, API still answers;
- env overlay: two children with different `OPENROUTER_API_KEY` each see
  their own;
- semaphore: N+1 runs → one waits, then starts;
- `STEP_RUNNER=thread` path still passes the existing tests.

Manual on the Space:
- one PDF through Steps 1 → 7 in both modes, diff outputs;
- 5-PDF batch: watch site responsiveness + loop lag;
- Stop and Cancel during Step 1 Vision OCR and Step 2;
- refresh the step page mid-run → live log reattaches (Phase 3 code);
- memory: `MAX_STEP_PROCESSES` children at peak stay well under 16 GB
  (measure RSS per child; adjust the default if needed);
- spawn cost per run (expected a few seconds of imports) — acceptable vs
  minutes-long steps; note the number.

## 8. Numbers (fill in at 5.0 and 5.3)

| Scenario | `/projects` p95 | `/overview` p95 | loop lag p99 |
|---|---|---|---|
| Idle | | | |
| Step 1 Vision OCR (thread) | | | |
| Step 2 (thread) | | | |
| 5-PDF batch (thread) | | | |
| 5-PDF batch (process) | | | |

## 9. Later (not in this phase)

- **Option B** — durable job table (`jobs`, `job_logs` in Supabase) + long-lived
  worker: needed only if runs must survive an API-only restart or
  `job_manager`'s in-memory state becomes a problem.
- **Option C** — separate worker machine reading that table, when one Space's
  2 vCPU are not enough.
- Warm process pool (pre-imported children) if spawn time turns out to matter.

## 10. Risks

| Risk | Mitigation |
|---|---|
| Something in the step code depends on API-process state (module globals, caches) | 5.1 extraction surfaces it; anything needed is passed in `RunSpec` or re-created in the child (`get_or_create(project, uid)`). |
| Modules read `os.environ` directly instead of `run_env.getenv` | Child sets both (single-run process). |
| `terminate()` interrupts a file write → truncated output | Cancel already means "discard"; Stop stays cooperative. Write result JSON atomically (temp file + rename) where not already done. |
| Windows dev machine | `spawn` is the Windows default — same behaviour locally and on Linux. |
| Memory with 5 children | Measured in 5.3; cap via `MAX_STEP_PROCESSES`. |
| Pickling config / tracker objects | Only plain dicts cross the boundary; tracker/context are rebuilt in the child. |

## 11. Decisions needed

| # | Question | Default proposal |
|---|---|---|
| P1 | Option A (process per run) instead of the plan's original job-table worker (B)? | A |
| P2 | `MAX_STEP_PROCESSES` default | = `AUTORUN_BATCH_CONCURRENCY` (5), lowered if memory says so |
| P3 | Cancel grace period | 10 s |
| P4 | Move Step 8 export / Sheets sync into children too? | No, unless numbers show them |
| P5 | Keep the `thread` fallback how long? | One release after the default flips |
