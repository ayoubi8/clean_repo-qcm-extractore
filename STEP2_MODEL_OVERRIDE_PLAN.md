# Step 2 model override — stale panel stomps Settings + sticky fallback — PLAN & FIX RECORD

Status: **approved + implemented** (user: "do fix it").

## Problem 1 — run-time panel config silently overrides Settings (previous problem)

- Settings page (`ModelConfigSection` → `POST /env`) works: writes `/app/.env` +
  Supabase `config/.env` + hot-swaps the running process env
  (`real_api.py:2487-2494`).
- But every Step 2 run sends `step2Config.model_primary/model_fallback` from
  the browser store (`ConfigPanel.tsx:133-134`), and `_call_step`
  (`real_api.py:2154`) applies it unconditionally:
  `os.environ["STEP2_MODEL"] = config["model_primary"]` — stomping the fresh
  Settings value with whatever the panel holds.
- The panel value is **persisted in localStorage**
  (`pipelineStore.ts:152-155` partialize) and the seed effect only fills it
  **when empty** (`Step2Config.tsx:15-18`). A value chosen once (e.g.
  `deepseek/deepseek-v4-flash`) sticks forever → every run re-applies it →
  "ignores settings, like hardcoded".

## Problem 2 — mystery model + sticky fallback pins it (this problem)

Live log (`ratrapage_gyneco_2024-2025`, chunks 3→5):

- Chunk 3-4: `[API] Trying nvidia/nemotron-3.5-lightning (attempt 1/3)` — a
  model the user never set, present **nowhere** in the repo (grep: zero
  matches; local `.env` has gemini; `admin.env` step2 lists are gemini-only).
  Delivery path is Problem 1's stale persisted panel value (or an old
  HF-side env), sent in the run payload.
- Chunk 4: nemotron returns unusable → `[INFO] Primary response was
  unusable; promoting fallback for the rest of Step 2:
  deepseek/deepseek-v4-flash-0731` (also never set by the user — same stale
  path via `STEP2_FALLBACK_MODEL`) → chunks 5-12 pinned to it at ~7 min/call.
- Root defect: `_step2_promoted_to_fallback` latches after **one** bad chunk
  and never resets within the run (`step2_qcm_extract_batch.py:303,355`;
  only cleared per-run at `:49`). One flaky chunk condemns the remaining
  11 chunks to the fallback with no recovery detection.

## Fix (implemented)

### A. Visibility — effective-model log at Step 2 run start (`api/real_api.py`)

In `_call_step`'s step-2 branch, after applying overrides, print run-config
values vs previous env vs effective values. Runs inside `LogCapture`, so it
streams to execution_log. This one line would have diagnosed both problems
instantly:
`[STEP2] models — run-config primary=... fallback=... | effective
STEP2_MODEL=... STEP2_FALLBACK_MODEL=... (env was: .../...)`.

### B. Escape hatch — "Use Settings default" in Step 2 panel (`Step2Config.tsx`)

- Empty-valued leading option (`⚙️ Use Settings default`) in both dropdowns;
  selecting it stores `''`, which the existing seed effect refills from the
  **current** env on next load and the backend already treats as "keep env".
- "Reset models to Settings defaults" button clearing both to `''`.
- Backend precedence intentionally unchanged (`if config.get(...)`): per-run
  customization stays a feature; staleness becomes visible (fix A) and
  escapable (this fix) instead of silent.

### C. Promotion scope — 2-strike streak (`step2_qcm_extract_batch.py`)

- Each `_extract_all_qcms_batch` call (one chunk) starts on **primary**
  unless the primary failed **2+ consecutive chunks**
  (`_step2_primary_fail_streak`, reset on any primary success).
- Within a chunk, primary→fallback failover per attempt is unchanged.
- Copy updated: "promoting fallback for the rest of **this chunk**".
- Effect on the observed incident: chunk 4's flaky nemotron response would
  fail over within chunk 4 only; chunk 5 would retry primary first instead
  of inheriting deepseek for 8 chunks × 7 min.
- Recovery across runs is unchanged (fresh instance + `run()` reset).

## Tests

- New `tests/test_step2_promotion_streak.py`: (1) single bad chunk does not
  stick — next chunk starts on primary; (2) two consecutive primary-failed
  chunks promote chunk 3 to fallback-first; (3) non-consecutive failures
  never promote; (4) primary success resets the streak.
- Existing suites re-run: step2 batch/collision/retry, post_step2_metadata,
  clinical_case_checker, cas_column.

## Follow-ups (not in scope)

- Same stale-panel pattern exists for Step 3/CC-checker model pairs
  (`Step2_3Config` seed-if-empty) — same treatment if it bites.
- HF Space `.env`/secrets as a source of mystery values: after this fix the
  `[STEP2]` log line exposes the pre-run env, closing that question too.
