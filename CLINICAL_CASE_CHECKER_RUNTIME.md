# Clinical Case Checker — trigger gate & runtime estimate (50 QCM)

> UPDATE — parallel rewrite shipped (`CC_CHECKER_PARALLEL_PLAN.md`,
> `modules/clinical_case_checker.py`): chains now verify **in parallel
> (max 5 concurrent, `CC_CHECKER_MAX_PARALLEL`)**, QCMs sequential within a
> chain, with the two-consecutive-NO early-stop (`CC_CHECKER_EARLY_STOP=1`).
> The timing table below described the OLD sequential behavior; divide healthy
> totals by ~(#chains, capped at 5) and subtract early-stopped tails. The
> "both models down" worst case still scales with the longest chain. The gate
> (`per_group` only, never `global`) is unchanged.

## Where the checker lives and when it fires

Gate: `modules/post_step2_metadata.py:134-152` (`_clinical_case_enabled`), called at line 270:

- UI shape `fields.clinical_case.strategy == "per_group"` → runs.
- Autorun shape `config.ClinicalCase == "CC"` → runs.
- Missing/None config → defaults to `per_group` → **runs**.
- **Anything else — including `"global"` / `"G"` — returns `False` → checker is SKIPPED**
  (`[CASCADE-TRACE] stage=checker event=SKIP`, `cc_check={"status": "not_enabled"}`).

So: **the checker runs for `per_group` only, never for `global`.**
Under `global`, Step 3 pastes one `global_cas` onto every QCM
(`step3_metadata.py:644-647`) with zero verification.
If verification was expected under `global`, that's a gap — currently unverified by design.

What it verifies: only QCMs that actually carry a `cas` field, grouped into
consecutive chains (`clinical_case_checker.py:89-103`). QCMs without `cas` cost nothing.

## Runtime model (sequential, 1 call per QCM with `cas`)

Per-QCM cost from `clinical_case_checker.py:186-206` + `openrouter_client.py:124-162`:

- Happy path: 1 HTTP roundtrip to the primary model (tiny verdict, `max_tokens=500`).
  Expect ~3–8s on a fast model like Mercury.
- One retry: +60s timeout + 2–4s backoff.
- Primary dead: 3 attempts × 60s + ~6s backoff ≈ 186s, then same for fallback.
- Both dead: ≈ 372s (~6.2 min) **per QCM**, then the loop continues to the next
  QCM — no circuit breaker, no parallelism.

## Estimation for 50 QCMs

Assumes worst case all 50 carry `cas` (one big chain). Typical `per_group` docs
have fewer (only cascaded QCMs) — scale linearly down.

| Scenario | Per QCM | 50 QCM total |
|---|---|---|
| All first-try ok (~3s) | 3s | **~2.5 min** |
| All first-try ok (~8s, slow provider) | 8s | **~7 min** |
| 90% ok, 10% one retry | ~9s avg | **~8 min** |
| Primary down, fallback saves each (~190s) | ~190s | **~2.6 hours — looks "stuck"** |
| Both models down (every call exhausts retries) | ~372s | **~5.2 hours — is "stuck"** |
| `global` strategy | 0 calls | **0s (checker skipped entirely)** |
| Re-run, same uid set (idempotency file exists) | 0 calls | **~0s (`status=skipped`)** |

## Takeaways

1. With a `per_group` config and ~50 QCMs carrying cascaded cases, a healthy
   checker run is **3–8 minutes of silence** inside Step 2's task — the new
   `[CASCADE-TRACE] stage=checker` markers show exactly this window in HF logs.
2. Anything beyond ~10 min means the Mercury model is failing over to Gemini or
   timing out — check elapsed time on `checker ERROR` / `unresolved` counts in
   the audit file (`step3_metadata/clinical_case_verification.json`).
3. With a `global` config the checker never runs — 0s, but all 50 share one
   unverified case. Enabling it under `global` is a 2-line gate change
   (`strategy in ("per_group", "global")`), but it turns a 0s skip into a ~5-min
   verification pass — confirm before changing.
