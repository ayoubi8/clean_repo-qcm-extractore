# CC Checker — parallel chain verification + early-stop — PLAN (no implementation)

## Goal

`run_clinical_case_checker` currently verifies QCMs **sequentially, one by one,
chain after chain** (`clinical_case_checker.py:288-335`). For the example doc
(4 chains: Q1-12, Q13-25, Q26-40, Q40-50 = 50 QCMs) that is 50 serial LLM calls.

New behavior:
1. **All chains verified in parallel** — each chain is an independent task.
2. **Max 5 chains in flight** (semaphore). Chains 6+ queue in document order.
3. **Early stop per chain** — the spec's boundary rule (`clinical_case_checker.md`
   §6.3): two consecutive `applies=false` verdicts close the case at the QCM
   *before* the first NO; every QCM from the first NO onward is unlinked
   **without spending LLM calls on them**, and that chain's task ends.
4. Frontend Settings inputs for main + fallback checker model — **already exist**
   (see §6), plan verifies wiring instead of rebuilding.

QCMs *within* a chain stay strictly sequential — the two-consecutive-NO rule
depends on prior verdicts, so intra-chain parallelism is impossible.

---

## 1. Current state (anchors)

| What | Where | Notes |
|---|---|---|
| Sequential verify loop | `modules/clinical_case_checker.py:288-335` | chain-by-chain, QCM-by-QCM, no early stop |
| One-call verifier (sync) | `modules/clinical_case_checker.py:186-206` | primary → fallback, `_verify_one` |
| HTTP client (sync httpx) | `modules/openrouter_client.py:78-163` | 60s timeout ×3 retries + backoff, per call |
| Chain builder | `modules/clinical_case_checker.py:89-103` | consecutive same-`cas` runs = chains |
| Cascade call site | `modules/post_step2_metadata.py:270-287` | sync call inside a `run_in_executor` thread (`api/real_api.py:1928`) — **no event loop in that thread**, so `asyncio.run()` is safe there |
| Early-stop spec | `clinical_case_checker.md` §6.1-6.3, §7 | two consecutive NOs close case; NO→YES triggers a re-check of the suspicious QCM |
| Idempotency audit | `clinical_case_checker.py:213-224, 358-385` | `clinical_case_verification.json` uid-set skip |
| Model config resolution | `clinical_case_checker.py:275-277` | `CC_CHECKER_MODEL` / `CC_CHECKER_FALLBACK_MODEL` / `CC_CHECKER_MAX_TOKENS` env |
| Env overrides from run config | `api/real_api.py:2161-2165` | step-2 run payload `clinical_case_checker{model_primary, model_fallback}` → env |
| Settings page model row | `frontend/src/components/settings/ModelConfigSection.tsx:10` | 'CC Checker (Clinical Case)' primary+fallback already editable |
| Step 2/3 config panel inputs | `frontend/src/components/pipeline/configs/Step2_3Config.tsx:67-172` | already sends `clinical_case_checker{model, model_fallback}` per run |

---

## 2. Design

### 2.1 Async strategy — new async client method (recommended)

**Option B (chosen): add `generate_completion_async` to `OpenRouterClient`**
using `httpx.AsyncClient` — same payload, headers, retry/backoff, and timeout
semantics as the sync path.

Why not Option A (`asyncio.to_thread` around the sync client): the whole
cascade already runs inside the **default** thread-pool executor
(`real_api.py:1928`). On the HF Space (2 vCPU) that pool is ~6 threads; 1 is
taken by the cascade itself, 5 chain tasks via `to_thread` would saturate it
and can deadlock any other concurrent `run_in_executor` work (another user's
step). Also `CostTracker.log_api_call` (`modules/utils/cost_tracker.py:16`)
is not thread-safe — with pure asyncio everything stays on one thread and the
tracker needs no lock.

Entry point stays **sync**: `run_clinical_case_checker(tracker, context)`
unchanged signature; internally:

```python
return asyncio.run(_run_checker_async(tracker, context, models, max_parallel))
```

Safe because the caller thread (executor worker) has no running loop. If a
loop *is* ever present (future refactor), fall back to the legacy sequential
path — guarded by `try: asyncio.get_running_loop() except RuntimeError:`.

### 2.2 Orchestration

```
_build_chains(entries)                     # unchanged
chains → asyncio.gather(*[
    _verify_chain(ci, chain, semaphore)    # each: async with sem: for qcm in items: await verify
])
semaphore = asyncio.Semaphore(CC_CHECKER_MAX_PARALLEL=5)
```

- Per-chain: sequential `for qcm in chain.items` — required by the boundary rule.
- In-flight LLM calls at any moment ≤ min(#chains, 5).
- Chains >5 wait in document order (FIFO creation order of tasks).

### 2.3 Early-stop rule (per chain) — spec §6.1-6.3

State per chain: `consecutive_no = 0`, `suspicious_qcm = None`.

| Verdict | Effect |
|---|---|
| `applies=true` | keep `cas`; `consecutive_no = 0`; if `suspicious_qcm` pending → run its §7 re-check now (case context + next YES question), overwrite its provisional decision |
| `applies=false` | `consecutive_no += 1`; **do not unlink yet** (provisional) |
| 2nd consecutive `false` | **CLOSE**: unlink every QCM from the first NO of the pair onward (`qcm.pop("cas")`), break the loop — remaining QCMs of the chain get zero LLM calls, decision rows marked `status=unlinked_by_boundary`. Record `{"last_member_index": idx_before_first_no, "closed_at_index": idx_first_no}` |
| unresolved | NEVER counts as NO (existing policy: technical failure ≠ rejection); `consecutive_no` unchanged; if ALL calls of a chain are unresolved → chain flagged error, links kept |

Spec §7 (single NO followed by YES → re-check the suspicious QCM) is included:
the NO stays provisional until either a YES resets it (then re-check) or a
second NO closes the case (then it's unlinked as part of the tail).

### 2.4 Writes stay single-threaded

File corrections (`qcm.pop`, JSON write-back at `clinical_case_checker.py:337-344`)
and the audit dump happen **after** `gather` returns, in the main entry —
no concurrent file mutation, `tracker.log_api_call` safe on the event loop.

### 2.5 Audit additions (`clinical_case_verification.json`)

Per chain: `closed_early: bool`, `early_stop_reason:
"two_consecutive_no" | null`, `last_member_index`, `closed_at_index`,
`llm_calls_saved: int`. Per decision: `provisional: bool`,
`rechecked: bool`, `after_close: bool`. Idempotency uid-set skip unchanged.

### 2.6 New env vars

| Var | Default | Purpose |
|---|---|---|
| `CC_CHECKER_MAX_PARALLEL` | `5` | semaphore size (hard cap per user request) |
| `CC_CHECKER_EARLY_STOP` | `1` | `0` disables boundary rule → old per-QCM unlink behavior |
| `CC_CHECKER_PARALLEL` | `1` | `0` = legacy fully-sequential path kept for one release as rollback |

### 2.7 CASCADE-TRACE

`[CASCADE-TRACE] stage=checker` markers in `post_step2_metadata.py:270-287`
unchanged and still correct (they bracket the whole async run). Add inside
the checker one line per chain at close/complete:
`[CC-CHECK] chain ci closed_early=… llm_calls_saved=… elapsed_ms=…`.

---

## 3. Backend file changes

| File | Change |
|---|---|
| `modules/openrouter_client.py` | add `async generate_completion_async(...)` — mirror of sync path with `httpx.AsyncClient` |
| `modules/clinical_case_checker.py` | keep `_build_chains`, `_parse_verdict`, `_verification_prompt`, idempotency; add `_verify_one_async`, `_verify_chain_async` (early-stop state machine §2.3), `_run_checker_async`; `run_clinical_case_checker` becomes thin sync wrapper (`asyncio.run` + `CC_CHECKER_PARALLEL=0` fallback to legacy loop) |
| `api/real_api.py` | no change needed (env overrides at `:2161-2165` already land before the checker runs) |
| `api/migration.sql` | **untouched** (user directive: no DB work) |

## 4. Runtime estimates (50 QCMs, 4 chains: 12/13/15/11, cap 5)

| Scenario | Today (serial 50) | New (parallel, longest chain 13) |
|---|---|---|
| Healthy, ~3s/call | ~2.5 min | **~40 s** |
| Healthy, ~8s/call | ~7 min | **~105 s** |
| Early stop saves tail (e.g. chain closes at Q+6) | same | **~20-70 s** |
| Primary down, fallback saves (~190s/call) | ~2.6 h | **~41 min** |
| Both models down (~372s/call) | ~5.2 h | **~80 min** — see hardening below |

## 5. Hardening (P2, recommended follow-up)

- **Per-chain circuit breaker**: after 3 consecutive *unresolved* calls in a
  chain, abort that chain (links kept, flagged) instead of burning 372s × N.
- **Global abort**: if every launched chain aborted on circuit breaker →
  return `status=error` early instead of waiting for the rest.
- **429 stagger**: OpenRouter free-tier models may throttle at 5 concurrent;
  the existing retry+backoff absorbs it, optionally jitter the first call of
  each chain (0/250/500/750/1000 ms).

## 6. Frontend — mostly already built

The ask "settings input for main model and fallback" **already exists twice**:

1. Settings → Model Configuration table → row "CC Checker (Clinical Case)"
   with Primary + Fallback (`ModelConfigSection.tsx:10`, keys
   `CC_CHECKER_MODEL` / `CC_CHECKER_FALLBACK_MODEL`, saved via `saveEnvKeys`).
2. Step 2 run panel → CC checker primary/fallback selects
   (`Step2_3Config.tsx:67-172`) → sent per-run → `real_api.py:2161-2165`
   env overrides.

Planned delta: **none required**. Optional polish (only if you want):
- relabel the settings row to "CC Checker (Clinical Case — parallel ×5)" so
  the new behavior is visible;
- surface per-chain `llm_calls_saved` in the run log line, not the UI.

## 7. Tests

Extend `tests/test_clinical_case_checker.py` (patch
`generate_completion_async` instead of `OpenRouterClient`):

1. Two consecutive NOs → chain closes, tail unlinked with zero extra calls
   (assert call count == index of second NO + 1).
2. NO-YES sequence → case stays open, suspicious QCM re-checked once.
3. 7 chains, semaphore 5 → assert ≤5 concurrent (track in-flight counter in
   the mock) and FIFO start order.
4. All-unresolved chain → links kept, `status=error` preserved.
5. `CC_CHECKER_PARALLEL=0` → legacy path results identical to old tests.
6. Idempotency: re-run same uid-set → skipped, no async calls.
7. Existing suites (`test_post_step2_metadata.py`, `test_hint_detector.py`,
   `test_cas_column.py`) must pass unchanged — cascade contract untouched.

## 8. Rollout

- **PR1 (core)**: async client method + `_verify_chain_async` early-stop +
  semaphore + audit fields + tests 1-4,6. Flag `CC_CHECKER_PARALLEL=1` default.
- **PR2 (hardening)**: circuit breaker + global abort + 429 jitter + test 5.
- **PR3 (optional UI)**: label polish only.
- Rollback: set `CC_CHECKER_PARALLEL=0` (env, no redeploy of code needed once
  the legacy path ships alongside for one release).

## 9. Decisions (approved — implemented)

1. §7 re-check of the suspicious QCM: **INCLUDED** per spec.
2. Early-stop default ON (`CC_CHECKER_EARLY_STOP=1`): **APPROVED** — tail
   unlinks change final xlsx output (rows after boundary lose the Cas column).
3. Legacy sequential path: **ARCHIVED, not kept in code** — the old
   `_verify_one` + `run_clinical_case_checker` are preserved verbatim in
   `CC_CHECKER_LEGACY_SEQUENTIAL.md`. Rollback = `git revert`. No
   `CC_CHECKER_PARALLEL` flag; `CC_CHECKER_EARLY_STOP=0` remains as the
   behavior-level kill switch (legacy per-QCM unlink, still parallel).
