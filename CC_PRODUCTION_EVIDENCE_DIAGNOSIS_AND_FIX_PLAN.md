# CC_PRODUCTION_EVIDENCE_DIAGNOSIS_AND_FIX_PLAN — detection-layer false positives/negatives on cardio_sec_1 (2026-09-17)

> Companion to `STEP3_CLINICAL_CASE_REDESIGN_PLAN (1).md`,
> `CLINICAL_CASE_REDESIGN_IMPLEMENTATION_PLAN.md` (phases 0–7 SHIPPED) and
> `CC_CROSS_PAGE_NARRATIVE_FIX_PLAN.md` (H-fix, SHIPPED). This is a
> **PLAN ONLY — no code in this pass**. It diagnoses a REAL production run
> (`execution_log.md` + `result.json`, doc set: cardio_sec_1 8 pages / 80
> QCMs, strategy `ClinicalCase = CC`, model
> `google/gemini-2.5-flash-lite`) and plans a detection-layer fix.
>
> It reuses the shipped vocabulary verbatim: 5 statuses
> (`new_case | continues | ends_here | unrelated | uncertain`), `carry_over`,
> `pending_case`, `_trailing`, `claims_pending_case`, `case_belonging_check`,
> and the `cas = "LABEL\r\nNarrative"` format. Nothing here introduces a
> parallel mechanism — every fix lands inside `_detect_cc_sequential_page` /
> `_parse_cc_statuses` / the `_process_qcms` page loop of
> `modules/step3_metadata.py`, before propagation consumes the map.

---

## 1. Production evidence — what actually happened

### 1.1 Run shape

- Step-2 chunked the 8-page cardboard into `all_qcms.json` (80 QCMs, 8 pages).
- Post-step-2 cascade ran `cas_split` (0 cas — nothing pre-split), then
  Step-3 CC detection over pages 1→8 (1 call per page, per-page budget held),
  then the boundary stage and the per_group CC Checker (6 chains, 11 calls).

### 1.2 Step-3 per-page trace (from `execution_log.md`)

| Page | QCMs | Detector output | Verdict by hand (against `pageN.txt`) |
|---|---|---|---|
| 1 | Q1–Q6 | `new_case` at **Q1** with cas_text `""` (empty), `new_case` at **Q4** with cas_text `"HTA\n38\n30"`; carry-over fired | ❌ Two FABRICATED cases. Page 1 has **zero** clinical narratives. `"HTA\n38\n30"` is OCR noise (stray digits/markings under Q3/Q4); an empty cas_text passed as a case anchor |
| 2 | Q7–Q11 | `new_case` at **Q9** with cas_text = the 75-year-old narrative ("Un patient âgé de 75 ans… Voici son ECG"); carry-over fired | ⚠️ FOUND but WRONGLY ANCHORED. That narrative sits at the very END of page 2 AFTER Q11 (a true `_trailing` situation). The model **did** find it, but attached it as a same-page `new_case` at an unrelated earlier QCM (Q9) instead of emitting `"_trailing"` — so the pending/cross-page path never ran, and a real case got welded to Q9–Q11 |
| 3 | Q12–Q18 | `new_case` at **Q12, Q14, Q16** — ALL with cas_text `""` (empty) | ❌ Three empty anchors. Each empty `new_case` REPLACED/ignored the running state; result.json shows Q12–Q18 end up `Cas: null` — the page-2 narrative's true claimants (the palpitations/ECG questions) got nothing |
| 4 | Q19–Q25 | `new_case` at Q22 ("Parmi les causes de syncope…") and Q25 ("Concernant le syndrome coronaire aigu…") | 🔀 Mixed. Q22 is plausible; Q25 is a QUESTION STEM ("Concernant…") — the fused-narrative rule inverted: stem content promoted to a case narrative |
| 5 | Q26–Q32 | carry-over active, no new case | ✅ correct mechanically |
| 6 | Q33–Q38 | `new_case` at **Q38** with the Mr MD narrative (its own stem) | ✅ textually right, but see 1.4: the case CONTINUES on page 7 and was not protected from the split there |
| 7 | Q39–Q40 | `new_case` at **Q39** with "Vous évoquez: …" | ❌ FALSE SPLIT. "Vous évoquez…" is Q39's block belonging to the running Mr MD case (the ECG follow-up); a `continues` was required; instead a second "case" forked, and the checker later BLESSED it (0.90 belongs to its own text) |
| 8 | Q41–Q80 | no case | ✅ (page 8 is answer-key junk — the 40 phantom QCMs are a Step-2 extraction issue, out of scope here, see OQ-6) |

### 1.3 Checker aftermath ("detect then remove" pattern)

- 6 chains detected → checker verified: **CAS 1 (`HTA 38 30`) unlinked
  wholesale** (two NOs, closed before Q4), **CAS 2 (Q9 narrative + Q9–Q11)
  unlinked wholesale** (two NOs, closed before Q9), CAS 4 (Q25 stem-as-case)
  unlinked after provisional+confirmed NO. Final: 3 of 6
  fabricated-or-split chains removed; one §7 resurrection saved only CAS 3.
- The checker did its job as backstop — but the user-visible cost is exactly
  the complained-about pattern: *the log looks like the system detects cases
  and then deletes them*, while the ONE TRUE cross-page case (75-year-old
  patient) never appears in `result.json` at all (its claimants are
  `Cas: null`, only `case_belonging_check` NO-notes), and the Mr MD case was
  forked instead of continued.

### 1.4 The four confirmed gaps (what the fix must close)

- **G-1 — Positional mis-attachment (page 2):** detection has NO positional
  rule. A narrative appearing AFTER the last QCM of a page (`_trailing`'s
  very definition) was absorbed as a same-page `new_case`'s cas_text at an
  unrelated earlier QCM (Q9). The prompt says "not trailing if even ONE
  numbered question follows", but the model matched the topic anyway. The
  H-fix machinery (`_trailing` → `pending_case` → `claims_pending_case`)
  never got a chance: it only consumes `_trailing`; it cannot arbitrate a
  WRONG same-page anchor.
- **G-2 — Fabricated case from OCR noise (page 1):** `"HTA\n38\n30"`
  passed as a full case narrative. No detection-layer sanity gate exists:
  any non-empty cas_text anchors.
- **G-3 — Empty-text anchors (pages 1 & 3):** `new_case` with
  `cas_text == ""` was accepted (Q1, Q12, Q14, Q16) and — critically — an
  empty `new_case` REPLACED the running carry-over on page 3, destroying the
  genuine chain from page 2's narrative. Nothing between
  `_parse_cc_statuses` and `_propagate_cas_clinie` refuses an empty anchor.
- **G-4 — False split of a running case (page 6→7):** with `carry_over`
  active (Mr MD), page 7's Q39 ("Vous évoquez…" — the answer block of the
  same case) was allowed to become a fresh free-standing `new_case`. Nothing
  deterministic prefers a continuing block to stay under the running case,
  so the chain forked and the checker verified the WRONG fork (against its
  own attached narrative, never against the page-6 narrative it actually
  belongs to).

Secondary observation (not addressed here): checker policy itself is
untouched. Fewer false chains emitted at detection automatically shrinks
checker churn (11 calls, 2 early closes in this run).

---

## 2. Design — a deterministic post-call validation layer (no new LLM calls)

### 2.1 Principle

Per-page call budget stays exactly as shipped. Between the model's response
and propagation, a PURE-PYTHON validation/arbitration function runs:

```
_validate_cc_map(page_text, qcm_positions, cc_map) -> validated cc_map
```

Rules are deterministic text position/shape checks. The 5-status vocabulary
is never widened — validation only DOWNGRADES or REWRITES into existing
statuses — and every rewrite writes an audit note riding the EXISTING
`case_belonging_check` key (population rule preserved: notes only where a
real decision occurred).

### 2.2 Rule V-1 — positional arbitration (closes G-1)

- Compute, per page, the char offset of each QCM's stem in `page_text`
  (same question-stem matching style used by the hint stage).
- If a `new_case`'s `cas_text` matches a text region located AFTER the LAST
  QCM offset on that page, the model has done G-1: the anchor entry is
  rewritten to `unrelated` (no attach, no chain) and the matched narrative is
  re-routed into the reserved `"_trailing"` key — from there the SHIPPED
  H-fix takes over untouched (`pending_case` seeded, ONE resolution attempt
  at the next QCM-bearing page via `_apply_pending_case_resolution`,
  existing `claims_pending_case` claim semantics, existing cross-page notes).
- Match basis: normalized-whitespace equality of a sufficiently long span of
  `cas_text` inside `page_text` (see OQ-3 for the unlocatable-text corner).
- Audit note on the de-anchored QCM:
  `detection: narrative attached here sits after the last question of this
  page — re-routed as a pending candidate for a later page (rule V-1)`.

### 2.3 Rule V-2 — narrative sanity gate (closes G-2)

A `new_case`'s `cas_text` must pass two deterministic checks before it may
anchor a chain (and `"_trailing"` narratives must pass the same gate before
being promoted to `pending_case`):

1. **Minimum body:** normalized length ≥ 20 chars (the same
   `MIN_NARRATIVE_LEN` rationale as `cas_text_split`) AND at least one
   alphabetic word of length ≥ 3 (kills pure digits/markup blobs).
2. **Patient-content cue:** at least one hit from a frozen French cue list
   (patient-specific anchors: age, presenting complaint, history, exam or
   lab findings, presentation verbs…). A single hit suffices.

Failure of either → the anchor entry is rewritten to `unrelated` + note
`detection: cas_text failed narrative validation ("HTA 38 30") — no case
started (rule V-2)`. No `carry_over` is ever seeded from a rejected text —
a never-attached case never becomes a running one. This moves the same
verdict the checker eventually reached (CAS 1 fully unlinked) UPSTREAM and
saves the whole chain's verification/boundary overhead.

Exceptions and trade-offs (cue-list false negatives, labs-only narratives):
OQ-1 proposes a recall valve; decision pending.

### 2.4 Rule V-3 — empty-anchor handling (closes G-3 — the chain-killer)

- `new_case` with empty/whitespace-only `cas_text` CANNOT anchor a case.
  Deterministic rewrite: entry → `uncertain` (the shipped safety valve)
  + note `detection: empty cas_text — anchor rejected, kept as uncertain
  (rule V-3)`.
- Why `uncertain` and not `unrelated`: `uncertain` preserves the safety-valve
  semantics — if a case IS genuinely running, it stays running (so on page 3
  the carry-over case from page 2 would have KEPT running instead of being
  killed by Q12's empty `new_case`); if nothing is running (page 1 Q1), it
  merely forbids a bogus anchor, attaches nothing, and leaves the note.
  Downgrading to `unrelated` would be the first hard negative ever
  synthesized outside the model's verdict — a policy change this plan
  deliberately does NOT make (see OQ-2, recommendation `uncertain`).
- The rewrite happens BEFORE propagation consumes the map, so a garbage
  anchor can never again REPLACE a running case.

### 2.5 Rule V-4 — running-case split guard (closes G-4)

- When `carry_over` is active, a `new_case` whose `cas_text` begins with an
  INTERROGATIVE/IMPERATIVE stem ("Vous évoquez :", "Quelle est votre
  conduite…", "Conduite face à…") or is composed primarily of
  proposition-list lines (`a- …\nb- …\nc- …`) is SUSPECT of being the next
  block of the running case rather than a fresh narrative.
- Deterministic treatment: entry → `uncertain` (safety valve — the running
  case stays attached; the suspected block is NOT married as a forked
  sibling) + note `detection: stem/proposition-shaped cas_text while a case
  is running — kept under the active case (rule V-4)`.
- Cue list frozen into fixtures like every other rule; any narrative with a
  real patient-content cue stays a legal new_case, exactly as the shipped
  fused-narrative rule already justifies (conservatism scoped in OQ-5).

### 2.6 Strategy scoping

- **`per_group` (`CC`)** — full validation; all four rules; notes written.
- **`skip` (`S`)** — the attach-once decision benefits too: V-1/V-2/V-3
  still apply (a wrong single attach is the only artifact skip can
  produce, so the gates protect exactly that); V-4 has no running case
  under skip (no linkage) and therefore never fires there.
- **`global` (`G`)** — untouched, for the same scope-creep avoidance stated
  in both companion plans.

### 2.7 What the checker then sees (contract unchanged)

The checker remains the backstop with UNCHANGED policy: two-NO unlinks,
§6.2 provisional verdicts, §7 re-checks — all intact. The added guarantee is
upstream hygiene: detection may no longer hand the checker fabricated
narratives (V-2), positional mis-fits (V-1), empty anchors (V-3), or naive
splits (V-4). Expected evidence effect: the "detect then remove" churn
seen in this run collapses, with the checker retained for genuine truth-
content questions.

---

## 3. Phase breakdown (same discipline as phases 0–7 / H-0–H-5)

> Phases D-0 … D-4. Each phase is built and verified BEFORE the next begins
> and leaves the suite green. Production files involved:
> `modules/step3_metadata.py` (validation layer + call sites) only. New test
> files: `tests/test_cc_narrative_validation.py` re-using
> `tests/cc_redesign_fixtures.py`.

### D-0 — Evidence fixtures frozen (no production edits)
- Files: `tests/cc_redesign_fixtures.py` (extend the mocked client shape),
  `tests/test_cc_narrative_validation.py` (new).
- Freeze the six concrete scenarios from §1 as mocked page texts + LLM
  responses EXACTLY as the production run produced them (including the model
  welding the narrative onto Q9's cas_text, the `"HTA\n38\n30"` fabrication,
  the empty anchors, and the page-6→7 split). Only AFTER this
  characterization is proven does any rule code land.
- Verify: characterization run reproduces today's outcomes for all six
  (Q9 holds the false anchor; Q4 anchors `"HTA 38 30"`; Q12/14/16 anchor
  `""`; Q39 forks; the page-2 narrative never travels; the `result.json`
  end-state is reproduced). Baseline locked.

### D-1 — Narrative sanity gate (V-2 + V-3, at the parse layer)
- File: `modules/step3_metadata.py` — `_parse_cc_statuses` downgrade logic +
  a shared `_looks_like_patient_narrative` helper; the gate also runs on
  `_trailing` before it is returned.
- Changes: V-2 (min body + cue) and V-3 (empty → `uncertain`) applied to the
  returned map; notes ride the existing `case_belonging_check` thread
  (build → xlsx, already end-to-end).
- Verify: unit tests — `"HTA\n38\n30"` → rejected with the V-2 note; `""` →
  `uncertain` with the V-3 note; the Q22 syncope and Q38 MD narratives PASS
  unchanged; empty/no `"_trailing"` parsing unchanged (regression anchor for
  the shipped H-fix parser).

### D-2 — Positional arbitration (V-1, needs QCM positions first)
- File: `modules/step3_metadata.py` — per-page stem-offset computation in
  `_process_qcms` (BOTH page-source paths — named `page_N.json` and merged
  `all_qcms.json` — from the SAME offset source so the two paths never
  diverge) + `_validate_cc_map` invoked in the call site AFTER pending
  resolution returns and BEFORE trailing promotion and propagation.
- Changes: an after-the-last-QCM `new_case` whose text matches the page →
  de-anchored and re-emitted as `_trailing`; the SHIPPED H-fix handles
  everything downstream (no new state, no new note key, no new status).
- Verify: page-2 scenario — Q9 loses the anchor, the narrative travels as
  `pending_case`, and the claim at page 3's resolving QCM carries the
  EXISTING cross-page note wording byte-identically with the shipped
  suite (`test_cc_cross_page_narrative.py`); corpora with no positional
  suspects produce unchanged output (extend-not-replace check).

### D-3 — Running-case split guard (V-4, gated on carry_over)
- File: same `modules/step3_metadata.py` — inside `_validate_cc_map`.
- Changes: stem cue list applied to `new_case` cas_text ONLY when
  `carry_over` is active; downgrade to `uncertain` + rule V-4 note; a real
  patient-content cue still makes it a legal fresh case (false-negative
  guard for the guard).
- Verify: page-6→7 scenario — no sibling fork; Q39 stays under the running
  Mr MD chain via the uncertain safety valve; the verification summary shows
  ONE chain (Q38→Q39→Q40) instead of today's fork; the 1c decline contract
  and all shipped pending semantics remain byte-stable.

### D-4 — End-to-end rollout + shrink-check
- Files: the shipped surface only (build/xlsx/checker pass-through — ZERO
  changes; notes ride the existing `case_belonging_check` column). This
  phase is pure verification.
- Rollout verification: re-run the FULL frozen cardio_sec_1 corpus through
  `_process_qcms` with the frozen production-like mocked responses and
  assert end-state deltas vs `result.json`:
  - page-1's fabricated chain disappears at detection (V-2 gate) instead of
    costing 3 unlink paths at the checker;
  - the 75-year-old narrative survives (V-1 → `pending_case`) and resolves
    at page 3 via `new_case (cross-page)` — the first real link the run
    failed to produce;
  - Q12/Q14/Q16 empty anchors no longer kill the running case (V-3 safety
    valve keeps it);
  - the page-7 fork disappears (V-4), leaving one Mr MD chain;
  - `case_belonging_check` values for all rejected/rewritten anchors carry
    the `rule V-*` notes; schema and note columns unchanged.
- Regression anchor set: `test_cc_redesign_phase0..7`,
  `test_step3_crash_fixes`, `test_cross_page_`, `test_cc_cross_page_`,
  `test_UI_`, `test_u_edits_` — all green; quantified no-change check:
  pages with NO suspect narratives produce byte-identical cas/notes
  (extend-not-replace gate, same discipline as every shipped phase).

---

## 4. Test plan

**New behavior (from the frozen production evidence):**
1. **V-2 garbage:** page-1 Q4 with cas_text `"HTA\n38 30"` → no `new_case`
   reaches propagation, no `cas` attached, the V-2 note lands in
   `case_belonging_check`; the OCR blob never reaches the checker chain.
2. **V-2 trailing gate:** a trailing narrative of pure OCR noise → NOT
   promoted to `pending_case` (nothing bogus carried across pages).
3. **V-3 empty anchors:** the page-1 and page-3 scenarios → `uncertain` +
   note; with carry-over active (page 3), the key outcome asserted: the
   running case STAYS attached (safety-valve keep) instead of being
   replaced by the empty anchor.
4. **V-1 positional:** the page-2 scenario — Q9 de-anchored to `unrelated`,
   narrative re-routed via `"_trailing"` → `pending_case`, then the EXISTING
   cross-page notes appear exactly as in
   `test_cc_cross_page_narrative.py`.
5. **V-4 split:** the page-6→7 scenario — no second case; Q39/Q40 stay under
   the running chain; verification summary shows ONE chain instead of
   today's two forks.
6. **V false-negative guard:** a genuine narrative with a patient cue (or a
   ≥120-char real story, once OQ-1's valve is adopted) passes V-2 untouched;
   a legitimate imperative-led narrative with patient content still gets its
   fresh case under V-4.

**Regression anchors (must):**
1. **Normal same-page `new_case` unchanged** — a healthy narrative followed
   by QCMs on the same page: byte-identical statuses and notes (no V-rule
   fires).
2. **Narrative-and-QCM-free page:** an all-`unrelated` page: no note churn,
   no `pending_case` change, byte-stable output.
3. **Shipped cross-page happy path** — the 1a direct claim via
   `claims_pending_case` still passes byte-identically (the validation layer
   must NOT intercept a legal cross-page claim).
4. **Checker untouched** — checker module diff must be EMPTY in this fix;
   the two-NO unlink paths and §6.2/§7 logic are exercised untouched by the
   regression suites to prove it.
5. **Quantified:** frozen `result.json` expected-diff shows ONLY the
   intended deltas (the three fabricated chains quietly refused at
   detection with `rule V-*` notes; the ONE true cross-page link added; the
   page-7 fork removed) — reviewed listing kept with the rollout artifact.

**Cost contract:** ZERO new LLM calls anywhere in the fix (validation is
pure Python over already-fetched data). Per-page budgets, the checker's
2-model policy, the boundary's 1-call-per-transition — all unchanged.

---

## 5. Open questions (decisions needed BEFORE implementation)

> Extracted to a standalone, sign-off-ready document:
> `CC_PRODUCTION_EVIDENCE_FIX_OPEN_QUESTIONS.md` (authoritative; includes a
> decision log table). Summary here for continuity; the standalone doc rules.

- **OQ-1 — V-2 cue-list scope.** Frozen French patient-cue regex can
  false-NEGATIVE genuine narratives lacking any listed cue. (a) cue + length
  (strict) vs (b) cue OR length ≥ 120 chars (recall valve). Recommend (b).
- **OQ-2 — V-3 downgrade target.** `uncertain` (safety valve; recommended)
  vs `unrelated` (first-ever model-external hard negative — a silent policy
  change).
- **OQ-3 — V-1 unlocatable text.** cas_text not literally in `page_text`
  breaks the geometry check. Middle recommendation: downgrade only if the
  anchor is NOT the last QCM of the page AND text is unlocatable (two
  strikes); exact match always wins. Needs sign-off (widens V-1).
- **OQ-4 — Where V-rule notes go.** Existing `case_belonging_check` key
  (recommended; rule-id prefix) vs a new audit key (violates the no-new-
  columns doctrine).
- **OQ-5 — V-4 conservatism.** Downgrade fires ONLY when `carry_over` is
  active AND cas_text is mostly proposition-list lines, on TOP of the stem
  cue. Needs sign-off.
- **OQ-6 — Page-8 junk QCMs** (40 phantom QCMs from an answer-key page):
  out of scope (Step-2 extraction layer), flagged for a separate issue;
  it inflated every count in the evidence run. Secondary: page-1's Q1 empty
  anchor may stem from the exam-header block — covered by the same V-3 gate
  either way.

---

## 6. Reference behaviors (do-not-touch invariants for this fix)

1. `cas` string format `"{label}\r\n{narrative}"` — unchanged.
2. The 5-status vocabulary and every status's propagation semantics —
   unchanged (validation only rewrites INTO existing statuses).
3. Failure policy (unresolved ⇒ keep; two NOs ⇒ close chain) — untouched.
4. `claims_pending_case` resolution contract (ONE attempt; never retried
   forward) — untouched; V-1/`_trailing` only feeds it more reliably.
5. Checker, boundary machinery, §6.2/§7 verdict logic — untouched.
6. Strategy G untouched; skip costs documented in the UI stay accurate.
7. Idempotency (uid-set gates; checker uid audit) — unchanged; no new
   persisted artifacts (validation state is per-page, in-run only).
8. Per-page LLM-call budget — unchanged (zero additional calls).
