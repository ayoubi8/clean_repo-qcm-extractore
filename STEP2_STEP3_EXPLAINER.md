# STEP 2 + STEP 3 — How they work (context document)

> Purpose: explain what the merged "Step 2" (QCM extraction) and the auto-enrich
> cascade (Step 3 metadata + clinical case handling) do, in what order, and how
> clinical cases ("Cas Clinique") are currently handled in ALL situations.
> Companion file with the actual code excerpts: `STEP2_STEP3_CODE_CONTEXT.md`.

---

## 1. The big picture

"Step 2" is no longer just QCM extraction. After the frontend merge, **Step 2 is
the only visible extract+enrich step**. When it finishes, one backend cascade
fires automatically (`modules/post_step2_metadata.py` → `run_post_step2_metadata`):

```
Step 2 (QCM extraction, per-chunk LLM)
   └─> RUN ONCE, in this order (the cascade):
        1. Guard        — no accepted QCMs? stop (no_qcms).
        2. Hint detect  — pure Python. Parses trailing "A(1+2+3)" answer-combo
                          lines out of propositions into a `hint` array and
                          scrubs them from proposition text.
        3. Cas split    — pure Python. If a QCM has `cas`, the clinical-case
                          narrative is REMOVED from the question `text` field
                          (it must live ONLY in the Cas column).
        4. Step 3       — LLM metadata (Year / Source / Category) + the
                          clinical case detection & propagation ("cas" fields).
        5. CC Checker   — Phase-1 verification: a cheap fast model re-verifies
                          EVERY QCM↔case link produced by Step 3, in parallel
                          per chain, sequential inside a chain (early-stop).
        6. Build 4/5    — merged JSON → final QCM objects (auto-build).
```

Each stage is soft-fail (an error never blocks the cascade) and traced with
`[CASCADE-TRACE] stage=... event=START|END|ERROR|SKIP` lines.

Idempotency fast-path (Q8): stage 4–5 are skipped only when existing Step 3
accepted metadata covers EXACTLY the same uid set as the current Step 2
`all_qcms.json`. If Step 2 grew (re-run added QCMs), Step 3 re-runs.

---

## 2. Step 2 — QCM extraction v7.0 (`step2_qcm_extract_batch.py`)

**Input:** `step1_extraction/accepted/page_N.txt` files (one per page, from Step 1).
**Output:** `step2_qcm/accepted/all_qcms.json` (accumulated), plus
`correction_pages.json` sidecar and `check/incomplete_qcms.json`.

**How it runs:**
- Default page range = `1-1-1` → AUTO-LOOP mode: pages are grouped into chunks
  of N pages, **1 LLM call per chunk**, results accumulate (uid-keyed merge,
  never deletes other runs).
- Models: primary `STEP2_MODEL` (gemini-flash-lite), fallback
  `STEP2_FALLBACK_MODEL`; promotion to fallback after 2 consecutive chunk
  failures (fail-streak), resets on any primary success.
- Retries per chunk: `max_tokens` escalates ×attempt (truncated-JSON cure),
  ceiling `STEP2_MAX_TOKENS_CEILING`.
- JSON parsing is truncation-safe: whole-content → array slice → **object scan
  recovery** (rebuilds `{...}` objects from a truncated array).

**Prompt rules baked in (what the LLM must obey):**
- Each QCM gets a `page` = number of the `=== PAGE X ===` marker before it;
  split QCMs merged, page = page of the QUESTION text.
- Visible numbers preserved; missing/cropped numbers resequenced using
  `PREVIOUS PAGE QCM NUMBERS` injected from the previous chunk (cross-page
  sequential numbering).
- Propositions labeled A–E **or** 1–5 both route to canonical keys `a`–`e`.
- `clinical_case_hint` (optional knob `qcm_extraction.clinical_case_hints`):
  if a "Cas Clinique" header + patient narrative sits immediately BEFORE the
  question, the LLM adds `"clinical_case_hint": "CAS CLINIQUE 1"`. This is a
  cheap signal Step 3 later verifies.
- Hint blocks (`A(1+2+3)` lines) must be kept VERBATIM as final lines of
  proposition "e" — the deterministic hint detector parses/removes them later.
- **Correction-page detection**: a page with ONLY answer markings and no
  question text → the LLM returns `{"page": X, "correction_page": true}`
  instead of inventing QCMs. Markers are split out, saved to
  `correction_pages.json`, consumed later by Step 6 (answer keys).
- Integrity pass: dynamic min-proposition threshold; incomplete QCMs
  re-extracted with a forward page window [P, P+1]; still-incomplete ones go to
  the `check` bucket (warn only, never blocks).
- Every QCM gets a stable `uid = f"{page}_{number}_{position}"` (prevents
  same-number QCMs from two halves of a page overwriting each other).

---

## 3. Step 3 — metadata + clinical cases (`step3_metadata.py`)

**Config strategies** (per field): `G` global, `P` per-QCM, `S` skip, and for
ClinicalCase: `CC` = per-group (the one used), `G` = one global case.
Default cascade config: Year=per_qcm, Source=skip, Category=global,
ClinicalCase=**per_group**.

**Standard metadata:** `_extract_metadata_with_ai` — taxonomy-enriched prompt
(Algerian faculties + modules-by-level); the LLM recommends, Python validates &
canonicalizes (`normalize_module/normalize_year/normalize_faculty`,
`derive_source` → "Externat {faculty}" or "Residanat {faculty}"). Hallucinated
values outside the closed lists are rejected to null.

---

## 4. CLINICAL CASE HANDLING — all situations (the important part)

### 4.1 Detection: `_detect_cc_sequential_page` (per page, per_group main path)

For EVERY page (either `page_N.json` files, or pages grouped from
`all_qcms.json` and processed in sorted page order):
- Reads the raw `page_N.txt` step-1 text + the QCM numbers known to exist on
  that page.
- **One LLM call per page** asks: "for each QCM number, is it the VERY FIRST
  question of a NEW clinical case narrative on this page?" Only the FIRST
  question of each case returns `{cas_label, cas_text}`; all others return
  `null`. The narrative must be only the patient story (between the header and
  the first numbered question).
- Output converted to `{qcm_number: "LABEL\r\nNarrative"}` for triggers, None
  otherwise.

### 4.2 Propagation: `_propagate_cas_clinique` (deterministic Python, no LLM)

Walks QCMs in document order; when a trigger is seen the running `current_cas`
is replaced and applied to that QCM and all subsequent ones **until the next
trigger**. The `carry_over` from the previous page is the initial state →
**cases spanning page breaks are handled**: narrative on page 6, questions on
page 7 still get the same `cas`. No page text → carry-over still applied to all
QCMs of the page (no LLM call).

### 4.3 The Step 2→3 hint bridge

If Step 2 emitted `clinical_case_hint`, Step 3 prints "verifying with LLM" and
the per-page detection still runs — the hint is a signal, not a decision.

### 4.4 Global strategy (`G`)

Single `_detect_clinical_cases` call on page-1 text; the first case found is
stamped on every QCM as `cas = "LABEL\r\nNarrative"`.

### 4.5 Legacy page-level / document-level variants (alternative paths)

- `_detect_clinical_cases(page_text, qcm_numbers)` → per-page `[{label, text,
  qcm_numbers}]` (used by the global path).
- `_detect_clinical_cases_document(full_doc_text, qcm_pairs)` → one call for the
  whole document, returns `qcm_pairs = [{"page": N, "number": M}]` to handle
  **QCM numbers repeating across exam sections** (Q1 on page 1 vs page 6).
  Rules: question belongs to the case AFTER its narrative until the next case
  header; page breaks don't break membership; number+page pairs, not bare
  numbers. (Document-level variant is defined but not part of the main cascade.)

### 4.6 Verification: Phase-1 CC Checker (`clinical_case_checker.py`)

Runs AFTER Step 3, BEFORE the build, only when strategy = per_group:

- Loads all accepted Step 3 files in document order, groups consecutive QCMs
  sharing the same non-null `cas` into **chains**.
- Chains verified in PARALLEL (`asyncio`, `CC_CHECKER_MAX_PARALLEL` = 5),
  QCMs strictly sequential **within** each chain.
- Per QCM, prompt == definition applied exactly:
  *"A QCM belongs to the clinical case only when the information in that case
  is necessary or materially useful to answer the QCM correctly; otherwise it
  does NOT belong, even if same medical subject."* Response = one-line JSON
  `{"applies": bool, "confidence": 0-1}`. Tiny budget (`CC_CHECKER_MAX_TOKENS`
  default 500). Primary `inception/mercury-2.5-preview`, fallback
  gemini-2.0-flash-lite. Invalid/failed verdict → **unresolved, link KEPT**
  (failure is never a rejection).
- **Early-stop state machine** (`CC_CHECKER_EARLY_STOP=1`):
  - YES → keep link, reset consecutive-NO counter; a pending NO triggers one
    **§7 re-check** (lone NO followed by YES is suspicious; re-verify with QCM
    B as context; confirmed NO unlinks that QCM only; re-check failure keeps
    link).
  - First NO → PROVISIONAL, link kept, counter = 1.
  - Second consecutive NO → **CLOSE the case at the QCM before the first NO**;
    all remaining QCMs of the chain unlinked with ZERO further LLM calls.
  - Chain ends on a pending NO → confirm it (unlink that QCM only).
  - Early-stop off → legacy: every NO unlinks that QCM immediately.
- Unlink = remove the `cas` key from the QCM dict; corrections written back to
  the accepted files after `asyncio.gather` (single-threaded writes).
- Audit trail: `step3_metadata/clinical_case_verification.json` with full
  decisions + `uid_set`; a re-run with the SAME uid set is skipped (idempotent).

### 4.7 Text hygiene: Cas split (`cas_text_split.py`)

Step 2 does NOT exclude the narrative from question text, so question `text`
often duplicates the case. `split_cas_from_text` deterministically removes the
narrative span from `text`/`Text`: (1) exact substring removal, (2)
whitespace-normalized fallback with index mapping; then drops a surviving
standalone label line. Narratives < 20 chars are never scrubbed; empty-result
removal never applied ("never mangle a question on an uncertain match").
Pure Python — no LLM, no cost, idempotent.

---

## 5. Data shape at each stage

After Step 2   : {uid, page, number, text, propositions{a..e}, year?, clinical_case_hint?, Correct?}
After Step 3   : + source, module_detected, tag[src,yr], cas = "LABEL\r\nNarrative" (propagated)
After CC check : cas removed from QCMs rejected by the verification policy
After build 4/5: merged final objects; Cas is its own column, narrative stripped from Text

---

## 6. Known pain points / re-engineering notes

1. **Case-boundary fidelity depends on the per-page LLM call** — if it
   misidentifies the first question of a case, propagation spreads a wrong case
   until the checker (or a §7 re-check) trims it. Two LLM layers (detect +
   verify) already exist; a third (document-level) is dormant.
2. QCM numbers repeating across sections are safe in the document-level path
   (page+number pairs) but the MAIN sequential path keys propagation by
   `qcm.get("number")` within a page — safe per page, carry-over handles the
   rest.
3. The checker's definition prompt is purely semantic ("case info necessary to
   answer") — position-in-document evidence (a YES question right after the
   narrative) is used only in the §7 re-check, not as a rule.
4. `cas` values store `LABEL\r\nNarrative` in a single string; split downstream
   (`_split_cas` duplicated in 2 modules, plus cas_text_split).
5. All stages are soft-fail/idempotent — re-running Step 2 re-enriches only
   changed uid sets.
