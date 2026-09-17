# CC LLM Layers Audit — every LLM touchpoint in the clinical-case pipeline
> Purpose: a review-grade map of EVERY step/layer that calls an LLM and has
> a role in clinical cases — inputs, outputs, and the exact prompt
> orchestration (verbatim prompts from the shipped code). Generated
> 2026-09-17 from `modules/step3_metadata.py` and
> `modules/clinical_case_checker.py`. Companion docs:
> `CC_PRODUCTION_EVIDENCE_DIAGNOSIS_AND_FIX_PLAN.md`,
> `ENDOCRINO_RUN_LOG_EXPLAINER.md`.

---

## 0. Pipeline position (orchestration of the layers)

```
post_step2_metadata cascade (modules/post_step2_metadata.py::run_post_step2_metadata)
  guard (deterministic) → hint (deterministic) → cas_split (deterministic)
  → [L1] step3 CC detection           (1 call/layer, per page)
  → [L2] ends_here boundary check     (1 call per ends_here transition)
  → [L3] CC Checker chain verify      (1 call per chain-QCM, parallel ≤5)
  → [L4] §7 re-check                  (1 call per NO-then-YES pattern)
  → build (deterministic)
```

Deterministic parts that DO NOT touch an LLM (so no one wastes review time):
- hint detection (`clinical_case_hint` fields — Phase 3, always-on, regex).
- `cas_split` (Phase 4 — splits `cas` out of `text` regex-based).
- `_propagate_cas_clinie` (the 5-status state machine — pure Python).
- `_apply_pending_case_resolution` (pending/claims bookkeeping — pure Python).
- chain building, early-stop counters, unlink write-backs, idempotency signatures.
Only four layers spend calls on clinical-case work: L1–L4 below.

---

## L1 — Step-3 per-page CC detection

**File/entry:** `modules/step3_metadata.py::detect_cc_sequential_page()` (via `_process_qcms`, per page; strategies `CC`=per_group, `S`=skip; strategy `G` never runs it).

**Inputs (prompt):**
- `PAGE TEXT` — the page's step-1 OCR text, truncated at `STEP3_MAX_INPUT_CHARS` (24000).
- `CURRENTLY ACTIVE CASE` (carry_over block) — label + narrative preview (1500 chars) if a case is running from an earlier page, else the explicit "NONE" block.
- `PENDING CASE` block (only if a cross-page pending candidate exists) — label + narrative (1500 chars) + the `claims_pending_case` instruction.
- `QCM NUMBERS ON THIS PAGE` — the list the model must answer one status per.
- Embedded rules: the 5-status task definitions (`new_case/continues/ends_here/unrelated/uncertain`), the TRAILING NARRATIVE page-level field (`_trailing`), the fused-narrative rule (no header / fused-into-question counts; anchor on third-person patient content, not interrogative/imperative stems), critical rules (exactly one entry per number, cas_text only for new_case, no title in cas_text).

**Output (expected JSON):**
```json
[{"number": 5, "status": "new_case", "cas_label": "CAS CLINIQUE 1", "cas_text": "Patient X…"},
 {"number": 6, "status": "continues", "cas_label": null, "cas_text": null, "claims_pending_case": true}]
```
plus optionally one extra element `{"_trailing": {"label": …, "text": …}}` -
a narrative that ENDS the page with no numbered question after it (may be
the ONLY element on a zero-QCM page). Parsed by `_parse_cc_statuses`
including pure-list known per-entry extra keys; missing/malformed →
`None` → counted as a failed attempt (below).

**Call policy:** primary model then fallback model (env `STEP3_MODEL` /
`STEP3_FALLBACK_MODEL`; 2-call ceiling — prod runs used
`google/gemini-2.5-flash-lite` for both). Blank/null/unparsable responses
count as FAILURES so the fallback still gets its try (ratrapage policy).
One call per page — no other CC budget is spent here.

**Downstream consumers:** `_apply_pending_case_resolution` (claims/declines
the pending candidate), `_propagate_cas_clinie` (5-status propagation →
`cas` fields, `case_belonging_check` notes, `cc_boundary_queue`),
`cc_pending_case` seeding via `_trailing`.

## L2 — ends_here boundary check (bounded re-link)

**File/entry:** `modules/clinical_case_checker.py::run_boundary_checks()` (Phase 5; runs BEFORE the checker inside the cascade; can be run standalone too).

**Purpose:** an `ends_here` transition closes a running case, leaving the
NEXT QCM `cas`-less; if the detector closed the chain wrongly, that QCM would
be silently under-linked forever (the normal checker never even sees it,
because chains are only built over linked QCMs). This check is the only
guard, and it is BOUNDED to one call per transition (never per QCM).

**Inputs (prompt):** reused `_verification_prompt` (identical shape to L3)
with: the `case_cas` ("LABEL\r\nNarrative") of the closed case, and the
BOUNDARY QCM = the entry immediately following the trigger QCM. The boundary
QCM participates untouched below.

**Gate (no call at all) when:** no following QCM (trigger is last in the
document), or the boundary QCM already carries a `cas` (a later case
claimed it — relinking would overwrite), or the sha-1 idempotency signature
(uids + queue contents,`cc_boundary_checks.json`) matches a prior run.

**Output (prompt answer):** same one-line JSON verdict
`{applies, confidence, case_facts_used}` parsed by the SAME `_parse_verdict`.

**Outcomes:**
- YES → `cas` re-attached + note `boundary re-check YES (conf): case actually informs this question — cas re-attached`.
- NO → note `boundary re-check NO (conf): ends_here confirmed`.
- unresolved (technical/invalid JSON) → unlink STANDS + note (a failure never silently relinks).

## L3 — CC Checker per-QCM chain verification (the biggest spender)

**File/entry:** `modules/clinical_case_checker.py::_verify_one_async()` → `_verification_prompt()`; orchestrated by `_verify_all_chains_async` (parallel, max 5 chains concurrently, `early_stop=on` in per_group mode).

**Inputs (prompt):**
- the case: `CLINICAL CASE — {label}: {narrative}` (split of the chain's
  `cas` string),
- `ACCUMULATED CASE FACTS (established by earlier questions of this case)`
  — the chain-scoped patient-fact ledger block (Phase 4), verbatim guard
  baked in: *"This list contains ONLY patient-specific facts (age,
  findings, labs, established diagnosis). It never contains general
  subject/topic language. Judge with the definition exactly."* Empty
  ledger → the whole block is omitted (not an empty stub).
- `QUESTION:` — the QCM's question text,
- `PROPOSITIONS:` — A–E rendered lines.
- Fixed DEFINITION block (applied literally): *"A QCM belongs to the
  clinical case only when the information contained in that case is
  necessary or materially useful to answer correctly; if it can be answered
  without the case-specific information, it does NOT belong — even on the
  same medical subject."*

**Output (prompt answer):** ONE line JSON, no markdown:
`{applies: bool, confidence: 0..1, case_facts_used: "<the patient-specific facts needed to answer>"}`.
Parsing is strict (`_parse_verdict`): bare bool or "true"/"false" strings
only; any other shape/confidence out of range/facts missing → returns value-pair without
facts (ambiguous string → null verdict → unresolved). A verdict FAILURE is
never treated as a rejection (link stays, decision flagged `unresolved`).

**Orchestration decisions the checker makes with verdicts:**
- ✅ YES → link kept; the returned `case_facts_used` string is APPENDED to
  the chain's ledger (only YES iterations reinforce it).
- ❓ First NO = provisional — link kept until the NEXT verdict (§6.2).
- ⛔ Two consecutive NOs (no YES between) → the chain CLOSES at the QCM
  before the first NO, all remaining members unlinked WITHOUT more calls
  (`force_save` counter).
- 2-er chains: a single NO is already end-of-chain → immediately confirmed
  and that member only is unlinked.
- YES right after a lone provisional NO → triggers the §7 re-check (L4).

## L4 — §7 re-check (NO-then-YES arbitration)

**File/entry:** `_recheck_prompt()`, invoked from `_verify_chain_async` only
when `suspicious` (a provisional NO) is pending and a YES arrives.

**Inputs (prompt):** the SAME definition block; the chain's
`CLINICAL CASE` + ledger; `QCM A` = the provisional-NO member (the one being
judged), its propositions; `QCM B` (the confirmed YES immediately after) as
CONTEXT ONLY with an explicit "do NOT judge it" guard.

**Output:** ONE-line JSON `{applies, confidence}` (no `case_facts_used`
required for the verdict shape; a YES may still carry facts which are
recorded).

**Outcome handling (all three directions covered):**
- applies=false → §7 confirms the NO → unlink QCM A **only** (`§7 re-check
  confirmed NO (conf) — link removed`).
- YES elsewhere → `§7 re-check: Qn actually belongs` + provisional NO was a
  model error → link KEPT.
- technical failure → downgraded to `unresolved`, link kept (never rejected).

## Ledger mechanics (shared by L3/L4 — worth checking)

- `ledger: List[str]` is per-CHAIN, reset at chain start.
- Only `applies=true` verdicts write `case_facts_used` into it (guardrail
  against rejected-QCM facts contaminating later prompts).
- Both prompt shapes (L3 main + L4 re-check) embed the ledger with the SAME
  patient-facts-only guard so every shape sees identical case evidence.
- Prompting contract: each verdict line is a SELF-CONTAINED prompt (case
  narrative + ledger + question + propositions); there is NO continuing
  chat session — every call is stateless except the ledger content.

## Model/cost policy common to all four layers (verified identical)

| Aspect | L1 detection | L2 boundary | L3 checker | L4 §7 re-check |
|---|---|---|---|---|
| Call per | page | transition | chain-QCM | §7 trigger |
| Primary→fallback | 2 attempts (blank/unparsable = failure) | 2 | 2 | 2 |
| temperature | default | default | **0.0** (forced in `_ask_verdict_async`) | same as L3 |
| max_tokens | `STEP3_MAX_TOKENS` (10000) | checker config | checker `max_tokens` | checker `max_tokens` |
| cost label | `step3_cc_sequential` | `cc_checker` | `cc_checker` | `cc_checker` |
| failure semantics | {} on both failures (never a hard negative) | unlink stands | unresolved, link kept | unresolved, link kept |
| idempotency | none (per-run state) | sha-1 skip file | chain uid coverage check (`_verification_covers` + step3/step2 uid gates) | — |

---

## What to check while reviewing the prompts (the audit checklist)

1. **Same DEFINITION text in L2/L3/L4** — all three use the identical
   "necessary or materially useful" definition with the "even if it deals
   with the same medical subject" exclusion (this is the anti-topical bias
   guard). L1 uses the entire different detection definition (status
   taxonomy) — do NOT merge those two prompts.
2. **`claims_pending_case` wording** — lives ONLY inside L1's pending block
   (`continues` + claim flag). Any other layer referencing it is a bug.
3. **`_trailing` reserved-key plan** — its element shape is a promise made
   to `_parse_cc_statuses(include_trailing=True)`; the parser treats a
   missing `"_trailing"` as None (tolerated-missing) — keep that always.
4. **L2 must reuse L3's prompt builder** — it shares the `_verification_prompt`
   with the same model/config budget, by design ("same applies/confidence
   definition, same cheap model budget").
5. **The ledger guardrail** — nothing except `applies=true` will move facts
   into the ledger, so confirm no new code populates the ledger elsewhere.
6. **No existing CC layer uses function-augment-chat / tool-queries** — they
   are single completion calls (probe formats: strictly-line JSON in L2–L4,
   a JSON array in L1); checker-side invalid JSON verdicts are retried via
   the fallback MODEL, not via a "convert your answer" second prompt.
7. **Case facts requirement** — the checker prompt only REQUIRES
   `case_facts_used` on YES verdicts (a NO can exist without naming facts);
   if a run shows NOs without facts, that is expected, not parsing loss.
