# CC Production-Evidence Fix — Open Questions
> Extracted (authoritative) from `CC_PRODUCTION_EVIDENCE_DIAGNOSIS_AND_FIX_PLAN.md` §5.
> All six need a decision BEFORE implementation of any D-phase (validation layer on the CC detection).
> Companion plans: `STEP3_CLINICAL_CASE_REDESIGN_PLAN (1).md`,
> `CC_CROSS_PAGE_NARRATIVE_FIX_PLAN.md` (vocabulary: `new_case/continues/ends_here/unrelated/uncertain`,
> `carry_over`, `pending_case`, `case_belonging_check`, `_trailing`).

---

## OQ-1 — V-2 cue-list scope (narrative sanity gate)

A frozen French patient-cue regex list can false-NEGATIVE genuine narratives
that lack any listed cue (e.g. a narrative starting directly with a lab line
instead of an age/presentation cue; a purely numeric BP/labs-only narrative
could exist).

- **Option (a):** require cue AND length ≥ 20 chars (strict — risks recall).
- **Option (b):** cue OR length ≥ 120 chars (recall valve — a 120+ char block
  of real text is probably a narrative even without a listed cue).
- **Recommendation:** (b), the 120-char recall valve.
- **Decision:** ✅ DECIDED (2026-09-17) — Gate on the DEFINITION of a
  clinical case context, not on a generic cue list: a clinical case context
  is *"a description of a patient's situation — symptoms, signs, history,
  examination findings, or test results — that provides the information
  needed to answer one or more exam questions."* (Simple example: "A
  45-year-old patient presents with chest pain, shortness of breath, and
  sweating.")
  Concretely in the implementation:
  - the cue list derives from that definition: symptoms, signs, history,
    examination findings (physical exam incl. ECG), test results, patient
    situation (age/sex + presentation verbs);
  - "long enough to probably be real" = a block that reads as such a patient-
    situation description passes EVEN without an exact-opener keyword, as
    long as it objectively reads as clinical description (length ≥ 120 chars
    of real descriptive text acts as the fall-through valve);
  - a random/numeric/label gibberish block ("HTA 38 30") fails BOTH layers.

## OQ-2 — V-3 downgrade target (empty cas_text anchor)

What should a `new_case` with an empty/whitespace `cas_text` become?

- **`uncertain`** (carry-over keeps running, checker backstops — matches the
  shipped uncertain doctrine, already tested).
- **`unrelated`** (hard negative — risks destroying a real anchor when the
  model just returned an empty text / quota artifact).
- **Recommendation:** `uncertain`. `unrelated` would be the FIRST
  hard-negative ever synthesized outside the model's verdict — a policy
  change this plan must not make silently.
- **Decision:** ✅ DECIDED (2026-09-17) — `uncertain`: keep linking the
  previous (running) clinical case to it, then flag for manual review in the
  xlsx (`case_belonging_check` note). The empty anchor itself never starts a
  new case.

## OQ-3 — V-1 unlocatable text (positioning rule vs paraphrase)

If a `cas_text` does not exist literally in `page_text` (paraphrase, CRLF
rejoin failures from extraction), the positional rule cannot verify the
"after the last QCM" condition.

- **Option (a):** trust the model (status quo — G-1 survives in this corner).
- **Option (b):** always downgrade to `uncertain` + note (over-eager).
- **Middle recommendation:** downgrade ONLY if the anchor QCM is NOT the last
  QCM of the page AND the text is unlocatable (two strikes); an exact
  text-match always wins.
- **Needs sign-off:** it widens V-1 beyond pure geometry.
- **Decision:** ✅ DECIDED (2026-09-17) — TRUST the model when the extracted
  cas_text cannot be literally located on the page. No downgrade, no note.
  Rationale: a human manual check happens downstream in the xlsx anyway, so
  the pipeline must not synthesize rewrites the geometry cannot prove; an
  exact text-match   (when locatable) still wins for the V-1 positional rule.

## OQ-4 — Where do V-rule audit notes go

- **Option (a):** `case_belonging_check` (existing key/column — zero schema
  change; recommended). Same wording family, prefixed by rule id
  (`rule V-1` / `V-2` / `V-3` / `V-4`) for reviewer distinction.

## OQ-5
- **Option (b):** a NEW audit key — cleaner to grep but violates the
  "no new columns" doctrine both companion plans held.
- **Recommendation:** (a).
- **Decision:** ✅ DECIDED (2026-09-17) — Reuse the EXISTING
  `case_belonging_check` column/key. We already committed to not adding more
  columns; note wording uses the same family as shipped notes, prefixed
  `rule V-*` for reviewer distinction. — How conservative should V-4 (running-case split guard) be?

The split guard changes semantics for correct-but-unusual new cases (a
narrative that legitimately begins with an imperative line).

- **Mitigation inside V-4:** the downgrade fires ONLY when `carry_over` is
  active AND the cas_text is composed primarily of proposition-list lines
  (`a- …\nb- …\nc- …`) — a shape no real narrative has.
- This makes the false-positive path split-safe, but it widens V-4 beyond the
  opener cue alone (a guard ON TOP of the stem cue, not instead of it).
- **Recommendation:** guard + opener cue together.
- **Decision:** ✅ DECIDED (2026-09-17) — Trigger V-4 based on the SAME
  clinical-context definition as OQ-1: when the "new case" text does NOT
  read as a patient-situation description, that is not a clinical case →
  the running case stays attached. Concretely: the downgrade fires when
  `carry_over` is active AND the cas_text fails the V-2
  clinical-description gate (proposition lists, imperative question stems,
  generic course-stem blocks) — i.e. "it doesn't look like the definition",
  not because of a keyword heuristic alone. Anything passing the V-2 gate
  stays a legal fresh case.

## OQ-6 — Page-8 junk QCMs (out of scope, recorded)

Page 8 produced 40 junk QCMs from an answer-key page. Out of this plan's
scope (Step-2 extraction layer, not the CC detection layer), but recorded:
it inflated every count in the evidence run and will confuse any future
diff-based verification — a separate Step-2 issue is likely warranted.

- **Status:** ✅ DECIDED (2026-09-17) — out of scope for this fix; track the
  page-8 answer-key junk as a SEPARATE Step-2 issue.
- **Secondary note:** page-1's Q1 empty anchor may have been the model
  reacting to the exam-header block rather than a real narrative attempt —
  covered by the same V-3 gate either way.

---

## Log of decisions (fill as they are made)

| OQ | Decision | Date | Decided by |
|---|---|---|---|
| OQ-1 | Definition-gated V-2 (patient-situation cues; ≥120-char descriptive fall-through) | 2026-09-17 | ayoub |
| OQ-2 | `uncertain` — keep the running case linked, flag for manual review in xlsx | 2026-09-17 | ayoub |
| OQ-3 | Trust the model when text is unlocatable (manual xlsx review downstream) | 2026-09-17 | ayoub |
| OQ-4 | Reuse the existing `case_belonging_check` column — no new columns | 2026-09-17 | ayoub |
| OQ-5 | V-4 fires when cas_text fails the V-2 clinical-context definition gate (prop-list/stem shapes), not by keyword alone | 2026-09-17 | ayoub |
| OQ-6 | Out of scope — separate Step-2 issue for the page-8 answer-key junk | 2026-09-17 | ayoub |
