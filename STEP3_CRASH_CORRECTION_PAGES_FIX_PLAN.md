# Fix Plan — Step 3 cascade crash on `correction_pages.json` (ratrapage_gyneco_2024-2025 run)

> Problem report from a live run (Space, 2026-09-16 13:28–13:36). Plan only —
> do not implement from this document without going through the phased process.

---

## 1. Where it broke (evidence → cause)

| Log evidence | What it means |
|---|---|
| `[SAVE] ... step2_qcm/accepted/all_qcms.json` + `[CORRECTION-PAGE] 💾 correction_pages.json → [12]` | Step 2 wrote **two files** into `step2_qcm/accepted/`: the QCM list and its sidecar `correction_pages.json` (answer-key page marker). |
| `🚀 Processing 2 file batches with Cas Clinique detection` | `Step3Metadata._process_qcms` globbed `*.json` and found **both** files. |
| `Batch 1/2: Applying metadata...` → 11 pages processed fine (63 QCMs saved to step3 accepted) | File #1 (`all_qcms.json`) fully enriched. |
| `Batch 2/2: Applying metadata...` → **`AttributeError: 'str' object has no attribute 'get'`** | File #2 (`correction_pages.json`) is `{"correction_pages": [12]}` — a **dict**, not a QCM list. `_process_qcms` iterates `for q in qcms:` which, on a dict, yields the STRING key `"correction_pages"`, then calls `q.get("page")` → **crash**. |
| `stage=step3 event=ERROR ... detail='str' object has no attribute 'get'` | The crash aborted the cascade AFTER batch 1 — so `cas` enrichment finished for the merged file, but **the build (Step 4/5) never ran**: no merged JSON/xlsx, no boundary-check run, and no CC stats. |
| Note the filename itself contains NO digits ("correction_pages"), so in the named-page branch it wouldn't even find a page file — it falls into the merged-file branch, where the crash occurs. | Crash location precisely: the merged-file page-grouping loop in `_process_qcms`. |

Also visible in the same log (secondary, non-crashing but reliability issues):

| Log evidence | Cause |
|---|---|
| Page 4: `⚠️ CC sequential detection failed: 'NoneType' object has no attribute 'strip'` — and the page is silently forfeited (`No Cas Clinique on page 4`) | `_detect_cc_sequential_page` does `content = resp["content"].strip()` — when the model returns `content: null`, `.strip()` raises. The call already SUCCEEDED (money spent, $0.0042 on p4's cousin at step 2 too), but the null-content case is only handled inside the model-call try/except, not around parsing — so the fallback model is NEVER tried and the page yields `{}` (whole-page treated as uncertain/legacy-propagate). |
| Page 5: `⚠️ No JSON array found in CC sequential detection response.` after a 4m09s call | The parser returned None (unparsable response) → again `{}` page forfeit, no retry with the fallback model. Cheap/free models (`qwen3.6-plus-preview:free`) are slow/erratic here (calls of 17s→83s→4m09s→195s). |
| Step 2 chunk 12: primary spent $0.0042 on an empty response, then fallback correctly classified the page | Step 2's retry logic already handles it; the wasted spend/2.5-min delay are noted but not fixed here (separate, already-covered path). |

**Root cause (verified in code):** Step 2 writes `correction_pages.json` as a
sidecar **into `step2_qcm/accepted/`** — the same folder `_process_qcms` globs
as `*.json`. The sidecar's JSON root is a dict `{"correction_pages": [12]}`,
so `for q in qcms` yields the string key `"correction_pages"` and `q.get("page")`
raises exactly the traced error. Filename note: "correction_pages" contains no
digits, so the named-page branch is not taken — it lands in the merged-file
branch where `q.get("page")` throws. Batch 1 (`all_qcms.json`, 63 QCMs) was
fully enriched and saved; the crash then aborted the cascade before the build.

---

## 2. Fix plan (3 fixes, smallest blast radius)

### FIX-1 (crash, must-fix) — make `_process_qcms` immune to non-QCM files

**File:** `modules/step3_metadata.py` — `_process_qcms`.

- When globbing `qcm_files`, **exclude known sidecar files** before iterating:
  `correction_pages.json` (and defensive: any file whose name starts with `_`
  or ends with `_transitions.json`/`_checks.json` — mirrors the checker's
  "not accepted/ glob-reads as QCM lists" convention).
- Defense-in-depth: after `json.load`, require the root to be a **non-empty
  list of dicts**; otherwise log a clear warn ("skipping non-QCM file %name%")
  and `continue`. In the merged/merge branch, replace
  `for q in qcms: pg = q.get("page")` with a guarded loop that skips
  non-dict entries.
- Invariant preserved: same save/load file names; no format change for real
  QCM files; `correction_pages.json` keeps seeding Step 6 exactly as today.

### FIX-2 — blank model responses must try the FALLBACK model in `_detect_cc_sequential_page`

**File:** `modules/step3_metadata.py`

- Convert the "blank content" case into a code-triggered model failure:
  try primary → (exception OR `resp.get("content")` falsy/whitespace-only)
  → retry via fallback model (already exists in the pattern next door in
  `clinical_case_checker._ask_verdict_async`). Only if BOTH fail/blank →
  return `{}` (exactly today's behavior, so the design cannot regress).
- The `'NoneType' object has no attribute 'strip'` wrap-around disappears:
  `content = resp.get("content") or ""` before any `.strip()`.

### FIX-3 (same file, same call) — retry-once-on-parse-failure

- If `_parse_cc_statuses` returns None (unparsable), do NOT log and bail —
  retry ONCE with the fallback model (page 5 lost its verdict on a 4-minute
  unusable response). Budget: at most 2 calls per page — same 2-model policy
  as the rest of the pipeline; still a per-page call shape; no new layer.
- Keep `STEP3_MAX_INPUT_CHARS` cap as today; long-running free-tier calls are
  latency risk, but out of this fix's scope beyond the retry (see §4 notes).

### NOT part of this fix (kept out deliberately)
- Step 2 chunk 12 empty-response retry handling — already worked correctly.
- Any CC redesign behavior change — this is a crash-repair + degenerate-response
  guardrail pass; nothing about case semantics changes.
- Choosing better STEP3_MODEL defaults — operations choice, kept env-driven.

**Recovery asymmetry note (why the crash must still be fixed):** `_save_results`
wrote step3 accepted for file #1 with the SAME uid set as Step 2, so a re-run
Step 2 would take the Q8 fast-path, skip the detection leg entirely, and go
straight to the build — "recovery" that would silently bake the page-4/page-5
detection losses into history. FIX-1 makes the normal path work on the first
pass instead of relying on that accident.

---

## 3. Test plan (mapped to each fix)

1. **Sidecar immunity (FIX-1):** tmp project with `step2_qcm/accepted/`
   containing `all_qcms.json` (2 QCMs incl. one case) + `correction_pages.json`
   (`{"correction_pages": [12]}`) + a corrupted non-list JSON file.
   Assert: 3 files globbed, only the QCM list processed, `case_belonging_check`/
   propagation unchanged, run returns WITHOUT exception, and sweep leaves
   `correction_pages.json` untouched (Step 6 unaffected).
2. **Blank-response fallback (FIX-2):** mocked client returning
   `{"content": None}` on the primary → fallback called exactly once → valid
   status JSON on the fallback → correct status map (and if the fallback
   returns None too → `{}` legacy fallback; assert no `.strip` crash).
3. **Parse-retry (FIX-3):** primary returns prose; fallback returns a valid
   5-status JSON → exactly 2 LLM calls, statuses applied; then primary OK/fast
   return case asserts only 1 call.
4. **Regression anchor:** re-run the 8 phase suites (0-7) + `clinical_case_checker`
   et al. and confirm the phase-2 wiring e2e (which uses `all_qcms.json` only)
   plus the phase-5 cascade-order test still pass.

## 4. Rollout / verification
- One deployed symptom check: re-run Step 2 on `ratrapage_gyneco_2024-2025`;
  expect the previous crash point replaced by "skipping correction_pages.json",
  `📊 CAS CLINIQUE SUMMARY` printed, and the Step 4/5 build completing with the
  merged xlsx including the Cas + case_belonging_check columns.
- Log signals to watch on re-run: page-4-style blank-LLM pages now retry on
  fallback instead of forfeiting; page-5-type unparsable pages get one retry.

## 5. Cost/latency note (for the implementer to keep in mind)
- FIX-2/3 cap extra spend at **at most +1 fallback call per failing page**
  (surface only on pages that fail) — bounded, no new layer; a healthy page
  stays at exactly 1 call.
- Free-tier STEP3_MODEL latency spikes (17s → 83s → 249s → 195s across pages 1–5)
  are the actual wall-clock driver of the 468s cascade; not addressed here —
  flag separately if it matters (candidates: raising the `STEP3_MAX_TOKENS`
  ceiling, switching the primary model env, or a timeout-retry knob).
