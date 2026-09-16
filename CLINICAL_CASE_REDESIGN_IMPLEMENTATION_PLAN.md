# Implementation Plan — Clinical Case Redesign v2 (state-aware detection) — PHASED

> Source plan: `STEP3_CLINICAL_CASE_REDESIGN_PLAN (1).md` (all 4 open decisions marked RESOLVED there are treated as locked here).
> Context: `STEP2_STEP3_EXPLAINER.md`, `STEP2_STEP3_CODE_CONTEXT.md`.
> This file is organized as **7 independent phases** — say "implement Phase N" and only that phase's scope is touched.
> Phase ordering is dependency-ordered; each phase states what it needs from earlier phases and what it must NOT touch.

---

## PHASE MAP (quick index)

| Phase | Title | Touches | Depends on |
|---|---|---|---|
| 0 | Test scaffolding + behavior freeze | test files only | — |
| 1 | State-aware detector (5-status classifier) | `step3_metadata.py` | P0 |
| 2 | Propagation state machine + cascade wiring | `step3_metadata.py` | P1 |
| 3 | `case_belonging_check` detection-side surface | `step3_metadata.py`, build passthrough | P2 |
| 4 | Checker patient-fact ledger + §7 consistency + audit write-back | `clinical_case_checker.py` | P3 |
| 5 | `ends_here` boundary check (bounded relink) | `clinical_case_checker.py` + Step 3 hook | P4 |
| 6 | Skip strategy: hygiene without linkage | `step3_metadata.py`, `post_step2_metadata.py` | P2 |
| 7 | Full-cascade rollout verification + idempotency smoke | none (verification only) | P1–P6 |

---

## PHASE 0 — Test scaffolding + behavior freeze
**Scope:** test files only; zero production edits.
- Snapshot current behavior of `_detect_cc_sequential_page` (shape `{num: "LABEL\r\nNarrative" | None}`) and `_propagate_cas_clinique` into characterization tests (frozen corpus fixtures: 2-page carry-over case, fused-narrative case, page with no case, repeating QCM numbers).
- Add fixtures for: narrative+questions same page; narrative p.N questions p.N+1..M; multiple cases on one page; case ends mid-page with same-topic standalone QCMs following; missing `page_N.txt`; whole-page LLM failure.
- Add a synthetic 2-page carry-over end-to-end test placeholder (filled in later phases).
**Acceptance:** all existing pipeline tests pass unchanged; characterization tests document today's behavior.
**Must NOT:** touch any module file.

---

## PHASE 1 — Edit 1: state-aware detector (`_detect_cc_sequential_page`)
**Files:** `modules/step3_metadata.py` (replace body + prompt + parser; keep method name and call site). No other modules.

**What changes:**
1. **New parameter** `carry_over: Optional[str]` (the `LABEL\r\nNarrative` active when the page starts). Backward-safe: default `None`.
2. **New prompt** (replaces the current binary "first question of a new case?" prompt):
   - State-aware preamble: "A case may already be running from an earlier page. Narratives in this corpus often have NO 'CAS CLINIQUE' header — do not anchor on headers; anchor on patient-specific third-person content (age, presenting complaint, exam/lab findings, started treatment) vs. imperative/interrogative question stems ('Quelle est votre conduite…', 'Parmi les propositions suivantes…')."
   - **Fused-narrative rule (the confirmed prod failure):** "Even when patient-specific content is fused directly into what looks like a single question block with no separator, preceding the actual interrogative/imperative sentence, classify it `new_case` (label may be derived as 'CAS CLINIQUE'). Never fold a patient narrative into question text as background."
   - Output schema: JSON array, EXACTLY ONE entry per listed QCM number:
     `{"number": N, "status": "new_case"|"continues"|"ends_here"|"unrelated"|"uncertain", "cas_label": null|"CAS CLINIQUE X", "cas_text": null|"patient story only (no title, no question)"}` — `cas_label`/`cas_text` required ONLY for `new_case`.
   - Full five-choice definitions table copied from plan §2.2 so the classifier knows exactly what `continues` (explicit confirmation) and `ends_here` (explicit termination, no new start) mean.
3. **New parser** `_parse_cc_statuses(content, qcm_numbers)` → `{qcm_number: {"status": ..., "label": ..., "text": ...}}`; validate status strings, coerce anything outside the enum to `"uncertain"`, missing remnant entries default to `"uncertain"` (never silently dropped), same fence-stripping/trailing-comma repair as today.

**Compatibility rule for this phase alone:** Phase 1 ships WITHOUT the propagation change — the interim adapter converts the new status map back into the OLD `{num: cas_str | None}` shape (new_case → narrative; continues → None; ends_here → None; uncertain → None) so existing propagation behaves identically until Phase 2.

**Acceptance:** detector unit tests (status parsing, enum coercion, missing entries → uncertain, carry-over in prompt when provided, fused-narrative prompt line present); interim adapter test asserts old-shape equivalence.
**Must NOT:** change `_propagate_cas_clinique`, checker, build, Step 2, `cas_text_split`.

---

## PHASE 2 — Edits 2+3: status-driven propagation `_propagate_cas_clinique` (+ wiring)
**Depends on:** Phase 1 (5-status output + parser). Removes the Phase 1 interim adapter.

**Files:** `modules/step3_metadata.py` (`_propagate_cas_clinique` + `_process_qcms`, both page-source paths: `page_N.json` files and merged `all_qcms.json` page groups).

**What changes (plan §2.3 verbatim semantics):**

```python
def _propagate_cas_clinique(self, qcms, cc_map, carry_over) -> tuple:
    # cc_map: {num: {"status": ..., "label": ..., "text": ...}}  (new shape)
    cas_for_propagate = {}   # {num: cas_str} derived for propagation
    check_notes         = {}   # {num: reason string} -> case_belonging_check
    current_cas = carry_over
    for qcm in qcms (document order):
        status = cc_map.get(num, "uncertain")  # unknown QCM treated as uncertain
        match status:
            new_case:  current_cas = f"{label}\r\n{text}"; attach; note "new_case: ..."
            continues: keep current_cas; attach; note "continues: confirmed by detector"
            ends_here: current_cas = None; NO attach; note "ends_here: case does not inform this question"
                       + queue ONE boundary check for the NEXT QCM (phase 5 mechanism; queue is a no-op until then)
            unrelated: no-op; NO case_belonging_check entry at all
                       (see Phase 3 population rule — ordinary case-free QCMs stay clutter-free)
            uncertain: fall back to TODAY's behavior (persist current_cas if any)
    return (updated_qcms, new_carry_over, check_notes, boundary_queue)
```

- Attaching = `qcm["cas"] = "LABEL\r\nNarrative"` (format invariant unchanged).
- Every QCM with a decision gets `qcm["case_belonging_check"] = "<short reason>"` — NEW key, never written into `cas`.
- `_process_qcms` threads carry-over INTO each `_detect_cc_sequential_page(...)` call (the loop already maintains this variable today — it just never told the LLM) and consumes the return tuple.
- Carry-over returns as before (cross-page linkage preserved; can be `None` after `ends_here`).

**Guardrail so the design can never under-link vs today:**
- If a page's LLM call **fails entirely** (exception/invalid JSON), fall back to today's exact behavior for that whole page: treat every QCM as `uncertain`/legacy-propagate with the incoming carry-over, set no per-QCM `ends_here` notes.
- An individual `uncertain` never clears a running case.
- Only `ends_here` (explicit, verified enum) can close a case. **`ends_here` is the one state that creates under-linking the normal checker can never see** — the checker only verifies QCMs that already carry `cas`, and an `ends_here` QCM has none — so a wrongly-fired `ends_here` would be silently invisible forever. This is covered by the **bounded boundary check** (Phase 5): every `ends_here` transition triggers exactly ONE verification call for the QCM immediately after the transition, judged against the case that just closed. Outcome stated plainly: YES ⇒ `cas` IS re-attached to that QCM (a confirmed disagree verdict is direct evidence the close was wrong — acting on it is the point of the check); NO or unresolved/failed ⇒ the unlink stands (a technical failure never silently relinks). Either way the outcome lands in `case_belonging_check`. Known limitation: the relink covers that one QCM only; if it confirms and the following QCMs were also swept by the same `ends_here`, the audit column flags it for review — validation of propagation beyond one QCM is deliberately not built for v1 to keep the cost bounded.
- Strategy `G`: **out of scope — untouched.** G keeps its existing single-call, page-1-only design exactly as it is today. This redesign applies only to `per_group` and `skip` paths.

**Acceptance:** unit tests on the synthetic 2-page set: new_case on p1; continues/ends_here/unrelated mixes on p2; fused-narrative case; LLM-failure fallback == old behavior; boundary queue emitted but inert.

---

## PHASE 3 — Edits 2.7/6: `case_belonging_check` detection-side surface
**Depends on:** Phase 2 (check_notes + boundary queue exist).
**Files:** `step3_metadata.py` (persist via `_save_results`), build (step5) passthrough for the new dict key.

**What changes:**
- Populated ONLY for QCMs with an actual case-linkage decision — statuses `new_case`, `continues`, `ends_here` (plus `uncertain` when it resolved to something), and later any checker/boundary verdict; `unrelated` gets NO entry (reserved rule: the column stays focused on real linkage decisions and is not cluttered by the large majority of ordinary case-free QCMs).
- `cas` column format/content UNCHANGED (narrative only). Plain dict key — the XLSX column materializes at export as today's other string fields do.
- `cas_text_split` and the build are untouched beyond the key passthrough — `cas` stays clean.
**Acceptance:** assertions on presence/absence rules (ends_here QCMs HAVE the note; unrelated QCMs do NOT; retained `cas` format byte-identical).

---

## PHASE 4 — Edit 4 (points 1–5) + Edit 7: checker ledger, §7 consistency, audit write-back
**Depends on:** Phase 3 (audit column exists on data).
**Files:** `modules/clinical_case_checker.py` (verification prompts + chain loop + persistence only; chain building, parallelism, early-stop, audit JSON unchanged).

**What changes:**
1. `_verification_prompt(cas, qcm, ledger=None)`: append optional block
   `ACCUMULATED CASE FACTS (from earlier questions in this case):\n<ledger lines>` after the narrative; instruction: "the ledger holds ONLY patient-specific facts established earlier in this chain; judge with the definition exactly."
2. Response schema: `{"applies": bool, "confidence": 0-1, "case_facts_used": "<short note>"}`; `_parse_verdict` returns the new optional field, tolerated-missing (None) — a response without it defaults to None, never an error.
3. `_verify_chain_async`: new `ledger: list[str]`; on `applies: true` → append the note to the ledger and pass `_verification_prompt(..., ledger=ledger)` to the next QCM. On NO / unresolved / failed → **do not** append (guardrail: only confirmed links reinforce). Ledger resets per chain, per case.
4. Strict patient-scoped constraint stated in the prompt: "never general subject/topic language — only patient-specific facts (age, findings, labs, established diagnosis)."
5. **§7 re-check also receives the ledger:** `_recheck_prompt(cas, suspicious_qcm, next_qcm, ledger=None)` appends the same accumulated patient-fact block (same patient-facts-only guard wording) so the lone-NO judgement is evaluated against the same case context as the surrounding chain, not the bare narrative alone. Consistency rule: a QCM must never see different case evidence depending on which prompt shape judged it.
6. Edit 7 (write-back): alongside today's unlink writes (`eq.pop("cas")`), write `qcm["case_belonging_check"] = <formatted verdict string>` for every decision entry (kept/unlinked alike): `"checker NO (0.85): answerable without case info"`, `"checker YES: uses reported diagnosis from case"` (folding in `case_facts_used` for confirmed links), `"§7 re-check confirmed NO"`, `"unresolved: call failed — link kept"`. Unlink semantics, early-stop, chain building, audit JSON — all unchanged.

**Acceptance:** chain tests: YES adds to ledger, NO/unresolved never does, ledger cleared per chain; §7 prompt contains ledger when present; verdict write-backs appear on data; NO changes to early-stop/close behavior.

---

## PHASE 5 — Edit 4 point 6: the `ends_here` boundary check (bounded relink)
**Depends on:** Phase 2 (boundary queue) + Phase 4 (checker verdict plumbing).
**Files:** `modules/clinical_case_checker.py` (NEW narrow entry point) + `step3_metadata.py` (consume queue → call hook). SEPARATE from normal chain verification.

**What changes:**
- New checker-hook entry point: `run_boundary_checks(context, transitions)` called by Step 3 wiring after the page loop, BEFORE normal chain verification.
- Input: the boundary-transition queue built during propagation — `[{case_cas, boundary_qcm_uid/page/number}]`, one entry per `ends_here` transition.
- One verification call per entry (per case-ending transition, NOT per QCM — proportional to how often cases end): prompt = the case that just closed + the single QCM immediately after the transition, judged with the same `applies/confidence` definition.
- Outcome handling (stated plainly): YES ⇒ re-attach `cas` (`"LABEL\r\nNarrative"` of the closed case) to that boundary QCM — the close was demonstrably wrong; NO or unresolved/failed ⇒ unlink stands, no relink ever on ambiguity or technical failure.
- Write-back: `case_belonging_check` gets `"boundary re-check YES (0.87): case actually informs this question — cas re-attached"` or `"boundary re-check NO: ends_here confirmed"`. Re-attached QCMs join normal chain verification afterwards (they now carry `cas`, so chain-building picks them up organically — no special-casing).
- Cost contract: bounded by case-boundary frequency; this is the only added budget item anywhere in the redesign.

**Acceptance:** boundary test: one call per transition; YES ⇒ `cas` re-attached; NO/unresolved ⇒ stays unlinked; re-attached QCM joins chain building; queue length == number of ends_here transitions.

---

## PHASE 6 — Edit 5: skip strategy — hygiene without linkage
**Depends on:** Phase 2 (same per-page call reused); ships with its own tests.
**Files:** `step3_metadata.py` (`_process_qcms`), `post_step2_metadata.py` (gate placement only — already skips checker under non-per_group).

**What changes (plan §2.6):**
- `ClinicalCase = "S"` no longer means "zero detection": run the SAME per-page state-aware call (independent per page — plan §5.4 confirms narratives never split across pages, so no carry-over needed for completeness).
- Gate: under `skip`, statuses `new_case` attaches the narrative **only to the QCM(s) it was triggered at / found fused into** — propagation disabled, `carry_over` permanently None, no `continues` linkage, no chains.
- `uncertain` under `skip` → no attach (case linkage is off by definition).
- CC Checker still does not run under `skip` (unchanged; and no boundary checks — no linkage exists). `cas_text_split` unchanged — it operates on whatever narratives landed in `cas`.
- Config plumbing: `Step3Metadata.run` already normalizes `{"clinical_case": {"strategy": "skip"}}` → `"S"`; add an internal flag `self._cc_linkage = (strategy == "CC")` consulted by propagation.

**Why (explicitly, not hidden):** changes what skip costs — from 0 CC calls to ~1 detection call/page (still no checker calls; still cheaper than per_group). Decoupled hygiene fixes the "skip leaves duplicated narrative in text forever" hole.

**Acceptance:** skip test: no cross-QCM `cas` ever appears, carry-over stays None, narrative still lands in its own QCM's `cas`, checker never invoked.

---

## PHASE 7 — Full-cascade rollout verification + idempotency smoke
**Depends on:** Phases 1–6.
**Scope:** verification only; no edits unless failures.

1. Run the full merged cascade (Step 2 → hint → cas split → Step 3 → checker → build) on the characterization corpus from Phase 0; compare against expectations: no regression in linked QCM count (recall parity), reduced/flat verification-call volume.
2. Idempotency smoke: re-run cascade on the same uid set → skip via existing gates (Q8 fast-path + checker audit uid_set) — unchanged behavior; boundary-check decisions must be recorded in the same audit surface so a re-run reproduces identical outcomes instead of re-firing calls (audit column persists for already-processed pages; `cancel_check` break points unchanged).
3. Confirm cascade order + soft-fail contract unchanged: hint → cas_split → step3 → checker(+boundary) → build; any error never blocks the next stage beyond the current contract.
4. If missed-case incidents persist post-ship: the deferred opt-in document-level reconciliation pass (`_detect_clinical_cases_document`) is the documented fallback — NOT part of this plan.

---

## Invariants any phase MUST preserve (checklist for every implementation order)

1. `cas` string format `"{label}\r\n{narrative}"` — unchanged.
2. uid-keyed identity (`page_number_position`) — unchanged.
3. Cross-page carry-over — preserved, now explicitly confirmed per page instead of assumed.
4. Failure policy (unresolved ⇒ keep link; two verified NOs ⇒ close chain) — unchanged in the checker.
5. Idempotency (uid-set gating) — unchanged.
6. Cascade order and soft-fail contract — unchanged; only `_detect_cc_sequential_page` and `_propagate_cas_clinique` internals change.
7. Narrative lives only in the Cas column — `cas_text_split` untouched.
8. Strategy G untouched; no state-aware classifier, no fused-narrative guidance there.

---

## PART B — MIND MAP: EVERY CLINICAL-CASE SITUATION → HOW THE NEW DESIGN HANDLES IT

```
CLINICAL CASE SITUATIONS
│
├─ 1. CASE EXISTS ON PAGE
│   ├─ 1.1 Has header ("CAS CLINIQUE N") → new_case at 1st Q after narrative
│   │        → cas = LABEL\r\nstory; case_belonging_check="new_case: ..."
│   ├─ 1.2 NO header, separate block (most common)
│   │        → same classification; detector anchors on patient content vs
│   │          imperative stems (prompt guidance, Phase 1)
│   ├─ 1.3 Narrative FUSED into the QCM text block (confirmed prod failure)
│   │        → MUST classify new_case; narrative extracted to cas,
│   │          cas_text_split scrubs it from text; never treated as background
│   ├─ 1.4 Narrative on page N, questions on page N+1..M (cross-page)
│   │        → carry-over passed into next page's prompt (content, not just
│   │          Python state); questions confirmed via "continues"; ends via
│   │          ends_here or page runs out
│   ├─ 1.5 Multiple cases on one page
│   │        → each new_case replaces current_cas; QCMs between cases belong
│   │          to prior case; per-chain ledgers isolate per case
│   └─ 1.6 Case ends mid-page, standalone QCMs follow (same topic!)
│        → ends_here closes AT that QCM; no propagation; checker only
│          backstops residuals — no "same course ≠ same case" drift
│            (ledger is patient-scoped by prompt constraint)
│
├─ 2. NO CASE ON PAGE
│   ├─ 2.1 Nothing running → every QCM "unrelated"; no cas; checker nothing
│   ├─ 2.2 Case was running from previous page
│   │        → each QCM individually: continues / ends_here / uncertain;
│   │          uncertain degrades to today's blind propagate (safety valve)
│   └─ 2.3 Page is answer-key/correction page only (Step 2 marker)
│        → no real QCMs; detection naturally no-QCM; untouched
│
├─ 3. ADJACENT / SEQUENCE EDGE CASES
│   ├─ 3.1 New case starts while previous still running (no explicit end)
│   │        → new_case replaces current_cas; previous case implicitly ends;
│   │          no relink math needed downstream
│   ├─ 3.2 QCM numbers repeat across exam sections
│   │        → propagation is scoped within a page + carry_over; uid-based
│   │          identity; no cross-section bleed (document-level variant,
│   │          page+number pairs, remains the dormant fallback)
│   └─ 3.3 Divider pages / no case then case resumes later (same doc)
│        → ends_here (or unrelated) cleared carry-over; new_case restarts it
│
├─ 4. DETECTOR FAILURE MODES
│   ├─ 4.1 Whole-page LLM call fails / invalid JSON
│   │        → whole page falls back to TODAY's behavior (uncertain,
│   │          propagate carry-over); checker backstops; nothing relinked
│   ├─ 4.2 Detector misses a case entirely ("total blindness", no header)
│   │        → v1: free prompt guidance only; fields say what unmarked
│   │          narratives look like; opt-in document-level reconciliation
│   │          pass stays DEFERRED (plan §3/§5.2)
│   ├─ 4.3 Detector says ends_here but the QCM actually still belongs
│   │        → bounded boundary check fires (ONE call per ends_here
│   │          transition, checker-module entry point): YES ⇒ cas re-attached
│   │          (confirmed evidence acts — the close was wrong); NO or
│   │          unresolved ⇒ unlink stands; outcome logged in
│   │          case_belonging_check; relink covers that one QCM only, audit
│   │          flags further swept QCMs for review
│   └─ 4.4 Ambiguous single QCM ("uncertain")
│        → persist current_cas exactly like today + checker verifies; audit
│          column marks it
│
├─ 5. CHECKER OUTCOMES (unchanged mechanics, new role: backstop)
│   ├─ 5.1 applies=true  → link kept; case_facts_used written to ledger;
│   │                      next prompt = narrative + ledger + QCM
│   ├─ 5.2 Single NO     → provisional; §7 re-check if followed by YES;
│   │                      confirmed NO unlinks that QCM only
│   ├─ 5.3 Two NOs       → chain closed at QCM before 1st NO; tail unlinked,
│   │                      zero extra calls
│   ├─ 5.4 Unresolved    → link kept, counter untouched; audit "call failed"
│   └─ 5.5 Ledger guard  → only patient facts; NO/failed never write it;
│                          reset per chain; same-course/different-case never
│                          aggregates topic vocabulary
│
├─ 6. STRATEGY × SITUATION
│   ├─ 6.1 per_group (default) → full: detect(propagate) + verify
│   ├─ 6.2 skip → same detection call, propagation OFF: narrative attaches
│   │        ONLY at its own QCM(s); no chains; NO checker; cas_text_split
│   │        still cleans text; cost = ~1 call/page (explicitly documented)
│   ├─ 6.3 global (G) → UNCHANGED / OUT OF SCOPE for this pass: keeps its
│   │        existing single-call, page-1-only design exactly as it is today
│   │        (no state-aware classifier, no fused-narrative guidance)
│   └─ 6.4 No config / new explicit → falls back to per_group (unchanged)
│
└─ 7. INFRASTRUCTURE CASES
    ├─ 7.1 Missing page_N.txt → carry-over applied, no LLM call (as today);
    │        skip mode: nothing to detect, nothing attached
    ├─ 7.2 Re-run / idempotency → uid-set gates unchanged (Q8 fast-path +
    │        checker audit uid_set); boundary-check decisions must be
    │        recorded in the same audit surface so a re-run reproduces
    │        identical outcomes instead of re-firing calls
    └─ 7.3 cancel_check mid-cascade → already-processed pages saved; loop
             break points unchanged
```

**One-line summary of the new contract:** every QCM gets an EXPLICIT case
decision (`new_case | continues | ends_here | unrelated | uncertain`) instead
of starts-only detection + blind propagation — with `uncertain` degrading to
today's behavior, so the redesign is monotone-safe against the current pipeline;
the one state that could silently under-link (`ends_here`) is covered by a
bounded one-call-per-transition boundary check that re-attaches `cas` on a
confirmed disagree verdict.
