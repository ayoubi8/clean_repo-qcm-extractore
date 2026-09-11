# Cas-in-Text dedup (post-checker) + forward-only page neighbors — PLAN (no implementation)

Two independent edits. No DB, no frontend, no model changes.

---

## PART A — scrub replicated cas narrative out of Text AFTER the checker

### A.1 Evidence (verified, not assumed)

- `all_qcms-resolt.json`: 63 QCMs (Step-5-style capitalized keys `Num/Text/Cas`),
  **58 carry `Cas`**. Sample Q4: `Text` starts with the `Cas` narrative
  **verbatim** (minus the `CAS CLINIQUE` label line) — exact-substring match
  will hit, no fuzzy logic needed.
- Why it survives today: cascade order is
  hint → **cas_split** → step3 → checker (`post_step2_metadata.py`), but
  `run_cas_text_split` reads `step2_qcm/accepted` where QCMs have **no `cas`
  yet** (`cas` is attached later by Step 3 per_group). The user's own HF log
  is the smoking gun:
  `QCMs scanned: 50, QCMs carrying cas: 0, Texts scrubbed: 0`.
  The module only ever fires on re-run/global leftovers — never on the
  first-run per_group path that produced this file.

### A.2 Design

- **Reuse the existing core** `split_cas_from_text(text, cas)`
  (`cas_text_split.py:77-114`) unchanged: exact-substring attempt first,
  whitespace-normalized fallback with index-map back to originals,
  standalone label-line drop, `MIN_NARRATIVE_LEN=20`, never-empty-text
  guards. No new matching logic.
- **Placement (recommended: A)** — inside `run_clinical_case_checker`,
  post-gather, on the same in-memory QCM dicts before file write-back:
  zero extra file I/O, scrubs + unlinks persisted in the single write,
  stats merged into the checker summary. Only QCMs whose `cas` survived
  verification get scrubbed (unlinked QCMs have no `cas` → auto-skipped,
  which is exactly the requested "after the checker" semantics; the checker
  itself keeps running on full text, unchanged).
- **Placement (option B, not recommended)** — separate cascade stage in
  `post_step2_metadata.py` after the checker: clearer trace separation but
  an extra full file read/write pass for zero behavioral gain.
- **Keep the existing pre-Step-3 pass untouched** — still useful for
  re-run/global leftovers; harmless otherwise.
- **Key robustness**: step3 files use lowercase (`text`/`cas`); mirror the
  existing `for key in ("text", "Text")` loop and read cas from
  `("cas", "Cas")`, same as the current module.
- **Trace**: new `[CASCADE-TRACE]` stage named `cas_scrub` (distinct from the
  existing `cas_split` stage for the pre-Step-3 pass — reusing the name
  would produce double-START lines and break the stuck-detector reading).
- **Downstream effect**: scrubbed step3 files flow into the existing
  Step 4/5 build untouched → merged `merged_qcms.json`/xlsx come out with
  clean `Text` + intact `Cas` automatically. No Step 5 changes. Note:
  already-produced files (like `all_qcms-resolt.json`) are NOT retro-fixed;
  only new runs are clean.
- **Mojibake note**: the `�` artifacts in the sample are byte-identical in
  both fields (same extraction source), so exact-substring attempt 1 hits;
  no special-casing required.

### A.3 Tests (extend `tests/test_cas_column.py`)

1. Verified `cas` → narrative removed from `text`/`Text`, `cas` intact.
2. Unlinked QCM (no `cas` after checker) → text untouched.
3. No-`cas` QCM → untouched.
4. Both key casings (`text`/`cas`, `Text`/`Cas`).
5. Idempotent re-run (second pass changes nothing).
6. Short-narrative (<20 chars) and would-empty-text guards hold (already
   covered by core, keep passing).

---

## PART B — forward-only window for split-QCM re-extraction (drop page-before)

### B.1 Target (corrected per user — verified in code)

`modules/step2_qcm_extract_batch.py:731-767`, `_reextract_for_incomplete`:
every QCM flagged incomplete (proposition count below the dynamic threshold
→ possibly split across a page break) is re-run through the LLM on window
`[P-1, P, P+1]` (`:744-746`). Change to `[P, P+1]` only — **hard-coded, no
flag** (user decision).

Explicitly OUT of scope / untouched: Step 6's one-blob correction scan
neighbors (`step6_corrections.py:795-804`, correction-table coverage — a
different feature), `_scan_all_pages_per_page_ai` (already single-page),
`step1_5_smart_text_merger.py:120-172` (already current + next only).

### B.2 Rationale

- Spillover is always forward in reading order: a QCM starting on P that is
  missing propositions can only continue onto P+1. P-1 can hold at most the
  question stem — already captured in the QCM's `text` — so re-sending it is
  pure token overhead (~1/3 of the window) plus noise: the wider window
  widens the `min/max(window_pages)` page-range header (`:751-755`) and
  invites the LLM to re-extract duplicate QCMs from P-1.
- **Coverage note (accepted)**: if a QCM's stem sits on P-1 and only its
  propositions landed on P, the stem is already in `text`; `[P, P+1]`
  still contains everything missing. No realistic miss case — strictly
  safer than the Step-6 neighbor tradeoff.

### B.3 Change shape

- 2-line change at `:744-746`: `[p-1, p, p+1]` → `[p, p+1]` (+ comment).
  The existing `if pg in page_map` guard already handles boundaries
  (p=1 → `[1, 2]`; last page → `[P]`; missing files skipped).
- The `🔄 Re-extracting Q{qnum} (page {p}) using window: pages ...` log
  (`:748`) stays truthful automatically; no prompt changes.
- Tests: window assertion on a fake `page_map` (middle → `[P, P+1]`;
  first page → `[1, 2]`; last page → `[P]`; gap in map → skipped) + an
  end-to-end incomplete-QCM case asserting the re-extracted match still
  wins when the missing props live on P+1.

---

## Rollout

- **PR-A**: post-checker scrub (placement A) + `cas_scrub` trace + Part A tests.
- **PR-B**: forward-only neighbors + log-label updates + Part B tests.
- Independent, either order. No migration, no frontend, no env vars.

## Decisions (approved)

1. Part A placement: **A — inside `run_clinical_case_checker`**, post-gather,
   on the in-memory QCM dicts before write-back.
2. Part B: **hard-coded `[P, P+1]`** in `_reextract_for_incomplete`, no flag.
   (Note: target corrected during review — Step 2 re-extraction window, not
   Step 6 neighbors.)
