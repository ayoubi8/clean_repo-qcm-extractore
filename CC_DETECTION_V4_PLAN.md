# CC_DETECTION_V4_PLAN — reasoning-model prompt + integration (plan ONLY, no code yet)
> Implements the *CC Detection v4* proposal as a phased plan, same discipline
> as phases 0–7 / H-fix / D-plan. Companions:
> `STEP3_CLINICAL_CASE_REDESIGN_PLAN (1).md`,
> `CC_CROSS_PAGE_NARRATIVE_FIX_PLAN.md`,
> `CC_PRODUCTION_EVIDENCE_DIAGNOSIS_AND_FIX_PLAN.md`,
> `CC_PRODUCTION_EVIDENCE_FIX_OPEN_QUESTIONS.md` (OQ-1..6 DECIDED, see §6).
>
> **Hard requirement from the user, stated first:** a case sitting at the END
> of a page MUST be linked to the NEXT QCM based on **`"Num"`** in the merged
> `all_qcms.json` — and the CC Checker (L3) then verifies the whole thing.
> The v4 anchor arithmetic (`max(qcm_numbers) + 1`) is exactly that link;
> this plan wires it through the merged JSON's `Num` field end-to-end so the
> checker receives a chain built on the right numbers.

---

## 1. Scope — changes / stays / deferred

**CHANGES:** only the LLM layer **L1** (`_detect_cc_sequential_page`):
model choice, prompt, and the parser/normalizer. The env knobs
(`STEP3_MODEL` / `STEP3_FALLBACK_MODEL`) are reused — no new pipeline stage,
no new cost contract shapes.

**STAYS AS-IS (round one):**
- `_propagate_cas_clinie` and its `carry_over`/`cc_carry_over` state machine.
- `_apply_pending_case_resolution` + the shipped `_trailing` key (§3 shows
  WHY the trailing shape still routes through it).
- The CC Checker L3/L4 (chains, parallel ≤5, early-stop, §7, ledger).
- `cas_text_split` — kept as a fallback safety net (§4).
- Boundary stage L2 (unchanged; it re-verifies anything `ends_here` closed).

**DEFERRED, NOT ABANDONED:** the V-rules (OQ-1..6 enforcement layer). The
v4 prompt absorbs most of their failure modes by definition (positive
definition + confirmed-negative examples). After the evidence re-run, ONLY
whichever V-rules still address a reproduced gap get built (§8 escalation).

---

## 2. The trailing question: `Num`-based linking, end to end (the user's must-have)

### 2.1 The problem, restated precisely

Page N ends with a narrative (`"_trailing"` today). The proposal wants the
narrative anchored to `max(page-N numbers) + 1` — the FIRST QCM of page N+1.

Mechanical truth (verified in the shipped code today): `_process_qcms`
consumes the CC map **per page** (`cc_map` keys are matched against
`pg_qcms` only — `number` or **`Num`** fallback at lines 551–552, 592, 601,
631, 679 of `modules/step3_metadata.py`). A `new_case` at
`max(page_N_numbers)+1` therefore CANNOT be consumed by page N's own
propagation pass — that QCM dict does not live in this page's batch. This
is why v4 must retain one of:

- **(A) route through the shipped `_trailing` → `pending_case`** (chosen):
  the parser converts a `max+1` anchor into `_trailing`; the EXISTING
  shipped mechanism then resolves it at the next QCM-bearing page — the
  merged path walks that page's QCM list and resolves the claim on
  `q.get("number") or q.get("Num")` — i.e. exactly the merged JSON's
  `"Num"`. NOTHING new is added for cross-page; the state machine already
  does this, keyed on the same fields the proposal names.
- (B) let the detector's map carry an out-of-page anchor as a synthetic
  entry — rejected: `_propagate_cas_clinie` iterates `pg_qcms` only; an
  out-of-page status has no attach site, so this path would REQUIRE new
  propagation machinery (the exact parallel mechanism the H-fix avoided).

### 2.2 `Num` continuity check (the "so the check fixes everything" clause)

For the pending→claim pipeline to land on the RIGHT member of the merged
JSON, one invariant must hold across the merged file: page N's `Num` group
and page N+1's `Num` group must be contiguous (page-N max ≡ page-N+1
`\u2212` gap of 1). This is true for the cardio/endocrino corpora, but the
plan formalizes it as a VALIDITY PREDICATE, not an assumption:

- `pipeline invariant P-Num:` in the merged `all_qcms.json`, the resolved
  anchor target for a trailing narrative is defined as **the smallest
  "Num" on the next page that is strictly greater than `max(page N's
  Num values)`**. If that smallest next-page `Num` is NOT `max+1`
  (numbering gap from multi-section docs / shuffled merging), the pending
  case still resolves (the claim rule stays: FIRST QCM page context
  decides via `claims_pending_case`), and gap-over-shipped-note info is
  written for the reviewer — but the `anchor_num == max+1` ARITHMETIC must
  not be the only safety: the Num-based predicate is computed in Python
  BEFORE relying on any model arithmetic.
- Both page-source paths (named `page_N.json` files and merged
  `all_qcms.json` → the page-group walk) resolve via the same
  `number`/`Num` fallback line — no divergence.

### 2.3 What the checker then sees ("fixes everything")

With the trailing narrative attached to the merged JSON's first next-page
`Num` member as a normal `cas`, the chain built for the checker (L3) begins
at the right member; the boundary queue, §6.2, §7 and the ledger all run
verbatim. The end-to-end trust chain is:

```
L1 (v4 prompt, one reasoning call/page)
  → parser: in-page anchors → direct entries;
            max+1 anchor → "_trailing"
  → pending_case (Python) resolved at the page holding
     Num == anchor_num (rooted on q.get("number") || q.get("Num"))
  → cas = "LABEL\r\nNarrative" on that QCM in the merged JSON
  → carry-over/propagation as today → chain built → CC Checker verifies
```

---

## 3. The v4 prompt (adopted from the proposal, with three corrections)

The prompt as proposed is adopted VERBATIM with these deltas:

1. **Defense-in-depth on QCM numbers.** The `QCM NUMBERS ON THIS PAGE`
   list stays as-is, but the prompt's trailing-arithmetic sentence is
   reworded to defer to the parser: *"If the page ends with a narrative and
   no QCM follows it on this page, report `anchor_num = (highest QCM number
   on this page) + 1; the pipeline will anchor it to the next page's first
   question (`Num`) on your behalf."* Reason: the model NEVER sees the next
   page's numbers, so any absolute claim about them is unverifiable — the
   Python side (§2.2) computes the real `Num` target.
2. **`note` stays an L1-only field.** It is stored under a distinct
   `"detector: <note>"` prefix (NEVER inside `case_belonging_check`), so
   the checker's own YES/NO verdicts in that column remain
   unambiguous — different questions, both kept visible.
3. **`anchor_num` validation stays PARSER-enforced, not prompt-hoped:**
   accept only (a) one of this page's own numbers, or (b) exactly
   `max(page numbers) + 1`. Anything else → the entry is REJECTED (see
   §5/§8), logged, never cascaded.

---

## 4. Fallback behaviors (per the proposal, formalized)

1. **`anchor_text_clean` handling.**
   - Non-null → apply to the anchor QCM's `text` (or `Text` — both read,
     same fallback line everywhere) so the narrative no longer pollutes the
     question stem, and the model's clean version is authoritative.
   - `null` → run `cas_text_split` on the anchor QCM as today (safety net;
     catches the model missing a fused case).
2. **`anchor_num` validation failure** → drop THE ENTRY, log it as
   `detection: anchor proposal rejected (Num arithmetic)`, same
   never-guess/never-retry-forward doctrine as the shipped pending_case.
   The page contributes NO new case; carry-over stays untouched.
3. **Whole-page call failure / unparsable JSON** → today's fallback
   exactly: page contributes nothing new, carry-over (if any) stands, and
   the boundary/checker stages proceed untouched.
4. **Multiple narratives on one page** → each narrative gets its own entry
   with its own `anchor_num`; anchors must be mutually consistent (an
   anchor that lands INSIDE another narrative's proposition list — i.e.
   before that narrative's own anchor — is treated as the outlier and
   dropped via the same validation rule).

---

## 5. Zero-change verification (implementer item #4)

Before any code, CONFIRM with a written table (it goes in this plan's §10
as a checklist) that these consumers consume the v4 output UNCHANGED:

| Consumer | Key it consumes | Why v4 stays compatible |
|---|---|---|
| `_propagate_cas_clinie` | `{qcm_number: {status,label,text}}` per page | in-page anchors produce the same `new_case` map entries as today |
| `_apply_pending_case_resolution` | the FIRST page QCM's claims | the max+1 anchor becomes `_trailing` BEFORE resolution; the pending machinery is UNCHANGED and keeps resolving on `number`/`Num` |
| `cc_carry_over` | the `cas` string | same format `LABEL\r\nNarrative` (split_first preserved) |
| chain building / L3 / L4 / L2 | accepted `cas` fields in the STEP-3-accepted merged JSON | numbers come from merged `Num`; boundary/§7/parallel config unchanged |
| `case_belonging_check` writing | existing keys only | the NEW `detector:` note lives under a separate field, same rule as OQ-4's DECIDED reuse of the existing column family — no new columns |

---

## 6. Relation to the decided OQs (must not regress)

- **OQ-1 (clinical-context definition)** — the v4 "What IS a clinical case
  narrative" section IS the decision implemented as the positive
  definition (patient-situation description). The ≥120-char fall-through is
  NOT ported into the prompt (the model judges with the full definition);
  the DECIDED cue/valve stays reserved for any later Python-side V-2 layer.
- **OQ-2 (uncertain)** — untouched: only `new_case`/other statuses appear
  in v4's OUTPUT (the anchor list shrinks to anchors only); the
  propagate layer still maps unlisted numbers to `uncertain`/legacy
  semantics. No hard negatives synthesized (no `unrelated` synthesized by
  code — still true; the v4 "If no genuine narrative exists, return []"
  just produces an EMPTY anchor map, which propagates as `uncertain`
  entries per the shipped semantics).
- **OQ-3 (unlocatable text)** — STILL DECIDED: trust the model. The v4
  `anchor_num` validation is a SHAPE constraint (numbers), not text
  matching — it does not reopen OQ-3.
- **OQ-4 (existing column)** — the `detector:` prefix rides the existing
  field family; no new columns.
- **OQ-5 (V-4 conservatism)** — superseded in round one: the v4 negative
  example list (question stems / proposition lists / OCR noise) is the
  prompt-side equivalent; a later Python V-layer is rebuilt ONLY against
  residuals (§8).
- **OQ-6 (page-8 junk)** — untouched; the v4 prompt's "HTA 38 30" example
  will ALSO mute OCR noise on answer-near pages, page 8's 40 phantom QCMs
  remain a separate Step-2 issue.

---

## 7. Phase plan (each phase gated, same shape as prior rolls)

> Phases V4-0 … V4-4. Each phase is built + verified independently; a
> failing gate blocks the next phase.

### V4-0 — Model availability + cost/latency probe + fixtures frozen
- Verify a reasoning-capable model is reachable through the existing
  OpenRouter setup (single probe call: cost/latency logged). Propose it as
  the new `STEP3_MODEL` default; current fast model becomes
  `STEP3_FALLBACK_MODEL` (outage resilience).
- Freeze the v4 characterization fixtures: the SAME evidence corpus
  (cardio_sec_1 80 QCMs, pages 1/2/3/6/7) + the endocrino run (35 QCMs) as
  mock responses in the NEW schema (`anchor_num`/`anchor_text_clean`/`note`).
- Verify: characterization reproduces today's mistakes under the v4 schema
  (the empty-anchor, the OCR blob, the stem-as-case, the page-2 weld, the
  Q39 fork) — baseline locked BEFORE the new prompt lands.

### V4-1 — Parser rewrite for the new schema
- File: `modules/step3_metadata.py` — `_parse_cc_statuses` becomes
  `_parse_cc_anchors` (new schema) with the `anchor_num` validation rule
  (§3 delta 3), plus the `anchor_text_clean` null/machine-usable
  normalization and the `note: "detector: …"` capture.
- The trailing path: `anchor_num === max(pageNums)+1` → emitted as the
  EXISTING reserved `"_trailing"` (§2.2 decision A) so all shipped
  pending/cross-page machinery is consumed verbatim.
- Verify: unit tests — in-page anchor (accepted), max+1 (accepted → routed
  to `_trailing`), max+2/gap (rejected + logged), missing fields,
  multiple-narrative ordering, `[]` for a clean page. Old-schema responses
  (5-status arrays) are NOT tolerated as a compatibility mode — v4 replaces
  the response shape entirely, so an old-shape response counts as
  unparsable → the fallback model gets its try. Assert exactly that.

### V4-2 — Prompt integration + cas_text_split bypass rule
- File: same — promote the v4 reasoning prompt into
  `_detect_cc_sequential_page`; wire `anchor_text_clean` per §4.1 (write
  back to `text`/`Text`), falling back to `cas_text_split` when null.
- Models: reasoning as primary; fast model kept as fallback (both env
  configurable; the prod run defaults from the probe in V4-0).
- Verify: unit tests — in-page fused narrative gets cleaned text (and NOT a
  second `cas_text_split` pass); separate-block narrative (clean=null)
  gets the safety-net split pass; malformed anchor_num entries are dropped
  with the log line; page-level call failure keeps carry-over standing.

### V4-3 — Trailing → Num anchoring (the user's requirement, full-route test)
- Files: `modules/step3_metadata.py` (the v4 parser's `_trailing` emission
  + the §2.2 Python Num predicate), `tests/test_cc_v4_trailing.py` (new).
- Changes: even though the shipped `pending_case` does the resolving, v4
  ADDs the Python-side Num predicate from §2.2 as a GUARD (assert logged
  when the smallest next-page `Num` ≠ `max+1`) — pure assertion/precision,
  no new state, no new statuses.
- Verify (end-to-end, both paths):
  - named `page_N.json` path AND merged `all_qcms.json` path;
  - the pending case attaches to the QCM whose **`Num` is the smallest on
    the next page greater than the trailing page's max** — the exact
    user-required behavior;
  - existing cross-page notes (`new_case (cross-page): …`) byte-stable;
  - the shipped `claims_pending_case` contract (ONE attempt, permanent
    decline) unchanged.

### V4-4 — Evidence re-run + escalation scoping (the proposal's report-back targets)
- Re-run the frozen cardio 80-QCM evidence exam (mocked schema per V4-0, then
  a real-model run) and the endocrino run; report per-target:
  1. Q12's `Cas` populated from the page-2 narrative (the silent miss) —
     PASS required.
  2. Q4–Q6 (`"HTA 38 30"`) AND the "Parmi les causes de syncope…" stem
     case NEVER proposed — PASS required.
  3. Q38 still links; the page-7 answer-choice block never proposed; Q39
     receives Q38's narrative via normal `continues` — PASS required.
  4. Endocrino: `"Le goitre simple se définit par:"` never proposed; page-4
     Q18 empty anchor eliminated; the `novembre 2023` evolution stays ONE
     Zhor chain OR is split flagged with a `detector:` note — reviewable
     delta.
- Plus: total LLM cost/latency vs the previous fast model (per-page),
  and a list of which OQ-1..6 scenarios STILL reproduce under v4 — that
  list IS the scope of any remaining V-layer (failures that no longer
  reproduce get dropped rather than built defensively).
- Full regression anchor set: phase-0..7 suites, cross-page suites, H-fix
  suite, `test_UI_`/`test u_edits_` — green before declaring the swap.

---

## 8. What happens to the D-plan / V-rules after v4

- The validation layer is NOT abandoned; it is gated ON EVIDENCE:
  - if the frozen v4 detector stops reproducing a scenario, that scenario
    leaves the V-plan's scope (no defensive code for failure modes that no
    longer occur);
  - if any scenario still reproduces (expected candidates: the
    `anchor_text_clean` mis-cleanup corner, multi-narrative page ordering),
    ONLY the matching V-rule is built, scoped to the evidence from the
    re-run;
  - the DECIDED OQ verdicts (see §6) carry over unchanged — the v4 detector
    inherits the SAME definition gate; it does not re-open decisions.

---

## 9. Test plan (summary — detailed per phase)

- **V-4 trailing anchoring (user requirement):** page-2 narrative → pending
  → next page's QCM anchored BY `Num` in the merged JSON → checker chain
  verified on that anchor. Test at the merged-path level (the QCM dicts the
  checker actually consumes).
- **Eighty-QCM target matrix** (from §4): 4 PASS targets + the endocrino
  deltas.
- **Regression:** same-page `new_case` byte-stability; narrative-free pages
  byte-stability; cross-page claims via `claims_pending_case` byte-stable;
  checker module diff EMPTY; boundary idempotency intact; quantified
  no-change assertion on corpora with no narratives.
- **Cost/latency budget:** per-page calls stay 1 (the reasoning call may be
  SLOWER per page — measure and report; the per-PAGE count never grows).

---

## 10. Open items (v4-specific, do NOT duplicate decided OQs)

- **V4-OQ-1 — Reasoning-model selection.** Which OpenRouter model qualifies
  (reasoning/"thinking" capable JSON-array output, cost/latency ≤ 5× the
  fast model's step-3 budget)? The probe (V4-0) must answer this with a
  real measurement, not a paper spec.
- **V4-OQ-2 — `note` volume.** Store `detector: <note>` for EVERY entry, or
  only for REJECTED/visited anchors? Proposed: every anchor entry carries
  one; reviewers filter in the xlsx. Confirm before build.
- **V4-OQ-3 — Anchor-only (`new_case` list) or keep the full 5-status
  array?** The v4 schema returns anchors ONLY; unlisted numbers then
  propagate as the shipped uncertainty semantics, but any page where the
  model would have RIGHTLY said `ends_here` now has no explicit signal.
  Today the carry-over keeps flowing instead of ending, until the boundary
  check or the checker fixes it. Proposed for round one: accept the
  anchor-only schema (fewer model tasks, fewer statuses to hallucinate)
  and let the ends_here/boundary pipeline absorb the closures — confirm
  this policy change explicitly.
- **V4-OQ-4 — Does `S` (skip) see v4 too?** Yes — same call, anchors only;
  under skip the attach-once/no-chain rule still applies identically
  (hygiene uses the SAME detection call by design). Confirm no separate
  skip-prompt drift.
