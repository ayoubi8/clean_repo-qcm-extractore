# CC_CROSS_PAGE_NARRATIVE_FIX_PLAN — trailing narrative at page end, QCM on the NEXT page

> Companion to `STEP3_CLINICAL_CASE_REDESIGN_PLAN (1).md` (v2 source plan),
> `CLINICAL_CASE_REDESIGN_IMPLEMENTATION_PLAN.md` (phased build spec, phases
> 0–7 SHIPPED), and the phase 0–7 rollout report (all suites green).
> This is a PLAN ONLY — no code in this pass. It reuses the shipped vocabulary
> and mechanism: the 5 statuses (`new_case | continues | ends_here |
> unrelated | uncertain`), `case_belonging_check`, `carry_over`,
> `_detect_cc_sequential_page`, `_propagate_cas_clinine`, `linkage`
> (per_group/skip), the `case_cas = "LABEL\r\nNarrative"` format, and the
> audit schema. Nothing here introduces a parallel mechanism.

---

## 0. Status vocabulary used here (unchanged from the shipped redesign)

| Term | Meaning (as shipped) |
|---|---|
| `carry_over` | An **already-attached** running case: at least one QCM carries its `cas`, and the state persists across page boundaries in `_process_qcms`. |
| `case_belonging_check` | Per-QCM human-readable audit note (detection + checker + boundary verdicts). |
| `per_group` | Detect + propagate + CC-checker verification (full linkage). |
| `skip` | Text hygiene only: a narrative attaches to its own QCM, linkage disabled. |
| `global` | One page-1 case for every QCM — untouched, out of scope here too. |

---

## 1. The problem — confirmed gap

### 1.1 In plain terms

Today the state-aware detector works **per page, keyed by that page's QCM
numbers**: `_detect_cc_sequential_page(page_text, qcm_numbers, carry_over)`
is only invoked for pages that CONTAIN QCMs, and it only ever attaches a case
to a QCM it can point at on that page.

A narrative that sits at the very END of a page, with **zero QCMs on that
page**, and whose QCM is entirely on the next page, is invisible in both
directions:

- The narrative's page has **no QCM to attach anything to** — and the merged
  path in `_process_qcms` doesn't even visit QCM-free pages (its page list is
  derived from `q.get("page")` groups), so no detection call happens there at
  all.
- The next page has **no visibility into the previous page's text** beyond
  `carry_over` — and `carry_over` does not exist here, because it only becomes
  non-None AFTER a case has been attached to at least one QCM. Nothing was
  ever attached → no `carry_over` → the next page's call sees an ordinary QCM
  and (rightly) returns `unrelated`.

Net effect: the case is silently never linked. It is the same *class* of
failure as the "total blindness" residual the v2 plan deferred, but this one
has a concrete, mechanical root cause (page-boundary narrative placement) that
we can close with one extra output field and one extra piece of state — no new
LLM layer.

### 1.2 Page-by-page walkthrough (at least the 3 required scenarios)

State legend: `carry_over` = attached-and-running case; `pending_case` = NEW
shipped-not-yet state (detected candidate that hasn't attached to any QCM yet).
Note both are None in today's code — `pending_case` does not exist yet.

---

**Scenario 1a — narrative at end of page N, the claiming QCM at top of N+1** (the direct case)

- Before page N: `carry_over = None`, `pending_case = None` (today: state doesn't exist).
- **Page N call (today):** `_detect_cc_sequential_page(page_N_text, [..])`;
  page has zero QCMs → `qcm_numbers` empty → the method returns `{}` **before
  even calling the LLM** (early guard `if not page_text.strip() or not qcm_numbers: return {}`).
  → Trailing narrative "Mme B.A., 38 ans…" is completely invisible. No output, no state.
- **Page N+1 call (today):** prompt shows `CURRENTLY ACTIVE CASE: NONE.`
  (there is none — nothing was ever attached). The QCM genuinely belongs to
  the narrative, but the model has no narrative in front of it → returns
  `unrelated` (best case `uncertain`).
- Result (today): the QCM is case-less forever; checker has no chain to
  verify; `case_belonging_check` empty. The gap is fully invisible.
- **Result (with fix, per §2):** page N's call (now also run for QCM-free
  pages) returns `trailing_narrative = {label, text}; `pending_case` holds it
  across the boundary; page N+1's call is given the pending narrative as
  context; the model claims it (`continues` against the pending case) → the
  existing `new_case` semantics attach the full narrative as
  `"LABEL\r\nNarrative"` with the distinct cross-page note (§2.4) and
  `pending_case` clears. From there the normal pipeline takes over: a chain
  exists → CC Checker verifies it.

---

**Scenario 1b — narrative, then one or more QCM-free pages, then finally a QCM**

- Page N: trailing narrative detected, nothing to attach → `pending_case` set.
- Page N+1 (all narrative/results, no QCMs): today and fixed — no call output
  to use; with the fix, the page call runs again and must RE-EMIT the pending
  narrative (or return null); the state machine keeps `pending_case` alive —
  it persists across any number of QCM-free pages as long as each scanned page
  still supports that the case exists (re-affirmed by the repeated
  `trailing_narrative` output, or simply carried by the Python state — see
  open question OQ-3).
- Page N+2 (first page containing a QCM): ONE resolution attempt against
  `pending_case` — confirmed via the detector's output → attach via the
  standard `new_case` path (with the cross-page note) and clear `pending_case`.
- Invariant: between the narrative page and the first QCM page, nothing gets
  bracketed as `cas` anywhere — the pending candidate exists ONLY in in-memory
  run state; a crash mid-cascade simply drops the pending candidate (same
  durability trade-off as `cc_carry_over`, no difference).
- Same rule as `carry_over`: a `pending_case` never survives the cascade — it
  exists only inside one Step-3 run.

---

**Scenario 1c — decline case: the next QCM does NOT belong to the trailing narrative**

- Page N: trailing narrative detected → `pending_case` set (same as 1a/1b).
- Page N+1 (the next QCM-bearing page): the call receives the pending
  narrative as context, but its QCM is genuinely unrelated → the detector
  marks it `unrelated` (or `ends_here` against the pending case).
- Behavior: the pending case is **dropped permanently on this ONE resolution
  attempt** — no attachment, `pending_case = None`, and the narrative is
  **never re-offered to any later page** (bounded-time-resolution contract:
  one candidate narrative, one resolution shot). This is intentional: the
  checker can only verify links that already exist; giving a stale candidate
  multiple bites across many pages would create chains nothing could police,
  and would eventually contradict the "one narrative is fully contained on a
  single page" invariant.
- Audit: the decline lands in `case_belonging_check` on the declining QCM as
  a short cross-page note (see §2.4) so a reviewer can see that a case
  candidate existed, was offered once, and was declined — without inflating
  any `cas` field.

---

Additional forced-realism scenario in the walkthrough (worth a test of its own):

**Scenario 1d — the trailing narrative is FOLLOWED on the next page by QCMs
that belong to it, but a DIFFERENT case also starts later on that page.**
- `pending_case` resolves on the first QCM that claims it; the later `new_case`
  on the same page then replaces `current_cas` exactly like today. No new
  interaction with multiple-cases-per-page machinery needed — `pending_case`
  only ever resolves ONCE (either claimed or declined) and then ceases to
  exist regardless of what the rest of the page does.

---

## 2. Design — the fix mechanism (shipped-style phases at the end; here: the semantics)

### 2.1 New page-level detector field (same call, no new layer)

`_detect_cc_sequential_page(page_text, qcm_numbers, carry_over)` gains ONE
additional output field (the status map stays exactly as shipped):

- New output envelope: the method returns `{qcm_number: {status,label,text}}`
  as today, PLUS a new top-level page field. Two implementation options (open
  question OQ-1 picks one):
  - **(a)** return tuple `(status_map, trailing)`, OR
  - **(b)** keep dict return and add a reserved key `"_trailing"`:
    `{..., "_trailing": {"label": ..., "text": ...} | None}`.
- New prompt field (same single call):
  `trailing_narrative`: if the page ENDS with a patient-narrative block (a
  case narrative with NO numbered question following it on this page — zero
  QCMs anywhere on the page qualifies), return `"trailing_narrative": {label:
  <exact label or "CAS CLINIQUE">, text: <full patient story>}`; otherwise
  `null`.
- A narrative that is followed by even ONE QCM on the same page is NOT
  "trailing" — that is today's same-page `new_case`, unchanged.
- The fused-narrative rule from Phase 1 applies verbatim: a narrative without
  a "CAS CLINIQUE" header still qualifies — anchored on patient-specific
  third-person content vs. imperative/interrogative stems. It must not be
  folded into question text, and (new) it must not be ignored just because it
  isn't separated from a footer/blank space.

### 2.2 New propagated state: `pending_case` (distinct from `carry_over`)

| Property | `carry_over` (existing) | `pending_case` (new) |
|---|---|---|
| Meaning | A case **already attached** to ≥1 QCM (its `cas` is set); keep attaching until status changes. | A **detected candidate** narrative that has not attached to any QCM yet. |
| Set by | A `new_case` (attached QCMs). | A page's `trailing_narrative` output, OR a narrative-only page. |
| Cleared by | `ends_here`/replacement by a new case. | ONE resolution attempt (below); also cleared when attached. |
| Survives QCM-free pages | Yes (today: `cc_carry_over` is passed onward unchanged) | Yes — as long as intervening QCM-free pages do not resolve it (they can't — no QCM exists to resolve against). |
| Interaction with checker | Chains exist → checker verifies | ONLY once attached (then it is an ordinary `cas` chain). |

**Resolution contract (exactly ONE attempt):**
1. `_process_qcms` walks pages in document order (both paths — named
   `page_N.json` files and merged `all_qcms.json`; see Phase H-3).
2. When a page has QCMs and `pending_case` is set: the page's detection call
   receives the pending narrative (as an explicit `PENDING CASE (carried over
   from the previous page, NOT yet attached to any question)` block —
   distinct copy from the carry-over block today).
3. Resolution is decided by the detector's verdict for the page's QCM(s):
   - The page's FIRST QCM returns `continues` **or `new_case` with the same
     label/text** (claiming the candidate) → **attach**: that QCM (and by the
     existing semantics, its forward cascade) gets
     `cas = "LABEL\r\nNarrative"`, `pending_case = None`, and the distinct
     audit note (§2.4) — plus, for `per_group`, the boundary/chain pipeline
     treats it exactly like any other case from here (normal chain building,
     CC Checker verification).
   - Declined (`unrelated`, or an explicit `ends_here` without a new case) →
     `pending_case = None`, narrative discarded, **never retried on any later
     page** (one single resolution attempt — bounded, no cross-page drift).
4. QCM-free pages NEVER resolve the pending (nothing to resolve against) and
   keep it alive (Scenario 1b).

### 2.3 Interaction with each strategy

- **`per_group` (full linkage):** `pending_case` participates like
  `carry_over` — persist, resolve once, attach through existing statuses,
  checker verifies the resulting chain. Boundary/ends_here machinery is untouched.
- **`skip` (hygiene-only):** resolution is the SINGLE attach decision — when
  the next QCM-bearing page claims the pending narrative, exactly that QCM
  gets the `cas` field (same attach-once-no-chain rule as Phase 6 today; no
  `continues` cascade, no checker, no boundary check). Decline also drops it.
  The audit entry still marks the cross-page origin (§2.4) — consistent with
  the population rule (a real attachment decision happened).
- **`global` (G):** untouched/out of scope — the global strategy stays its
  page-1 single call exactly as today, no `pending_case`, no trailing field
  changes (deferred scope creep avoidance, same as Ship-phase 0 decision).

### 2.4 `case_belonging_check` note (cross-page attach must be distinguishable)

Attachment via a SAME-page narrative (today):
`new_case: <LABEL> starts this case` — unchanged.

Cross-page attachment (this fix, per_group + skip):
```
new_case (cross-page): narrative from page <N> (no QCM followed it on its own
page) claimed by this question; pending candidate attached
```
- Label hint: SHIP-option — keep the SAME wording family as the same-page
  note so the checker/building do not branch on it. The `(cross-page)` marker
  plus the originating page number is the reviewer-out call: this is the
  rarer, higher-risk attach (the narrative was never co-located with a
  question), and the checker verifies the link AFTER it attaches (per_group),
  the same as any link.
- Decline note (next QCM-bearing page):
  ```
  cross-page: narrative from page <N> pending was offered once and declined
  (this question does not claim it) — candidate dropped
  ```
  Population rule unchanged: recorded for the DECIDING QCM only; no entries
  on the narrative-only pages themselves (they have no QCMs).

### 2.5 `trailing_narrative` output cap and parser treatment

- Parser: missing `trailing_narrative` key in the model's response → treated
  as `null` (tolerated-missing, same policy as `case_facts_used`),
  never an error.
- Narratives shorter than the existing safety floor (20 chars — same
  `MIN_NARRATIVE_LEN` rationale as `cas_text_split`) are NEVER promoted into
  `pending_case` (too-short text is unsafe to attach/match downstream).
- `SKIP` + audit trail: the pending candidate is NOT persisted across Step-3
  runs (same durability convention as `cc_carry_over`).

---

## 3. Phase breakdown (built and verified independently, same as phases 0–7)

> Naming: phases H-0 … H-5 (H = hotfix-line for cross-page narrative), built
> on top of the shipped phases 0–7; same style — each phase states what
> changes, which files, and how it is verified before the next phase starts.

### H-0 — Characterization fixtures + scenarios frozen (no production edits)
- Files: `tests/cc_redesign_fixtures.py` (+ a new suite
  `tests/test_cc_cross_page_narrative_h*.py`).
- Add frozen fixtures for scenarios 1a/1b/1c: page_N text ending in a
  narrative with zero QCMs; N+1 text with the full claiming QCM; the extra
  QCM-free middle page; the decline page. Reuse the existing mocked-client
  shape (`status_response`) + the new `trailing_narrative` field stub.
- Verify: characterize TODAY's behavior in each scenario (all emitted
  nothing; page N+1 = unrelated) — locks the baseline so H-phases can prove
  the delta deliberately.

### H-1 — Detection field: `trailing_narrative` in the per-page call
- File: `modules/step3_metadata.py` — `_detect_cc_sequential_page` + parser.
- Changes: prompt gains the trailing-narrative instruction + output field;
  parser normalizes it (`{"label", "text"} | None`); return shape per OQ-1
  decision; missing field = null (tolerated-missing); zero-QCM pages are now
  valid inputs (guard change: they may return ONLY the trailing field).
- Verify: unit tests — narrative at end w/ zero QCMs → extracted; narrative
  followed by a same-page QCM → NOT trailing (same-page new_case path
  unchanged); unfused/short narrative → null; old-shape responses (no field)
  parse to `None` cleanly.

### H-2 — Page-loop mechanics: pages without QCMs get visited
- Files: `modules/step3_metadata.py` — `_process_qcms` (BOTH page-source
  paths: named page_N.json and merged all_qcms.json).
- Changes: the merged path's page set is extended beyond `q.get("page")`
  groups to include pages that exist as `page_N.txt` (or in the merged list)
  with zero QCMs, so their detection call actually runs. Named-page path
  already visits each file — confirmed no change needed there beyond the
  call-site wiring.
- Verify: a QCM-free page with a trailing narrative now produces a call (1
  per QCM-free page, bounded by plan cost contract "1 call per page already
  allowed"); the page-stage keeps `cc_boundary_queue`/sidecar files untouched.

### H-3 — State machinery: `pending_case` across pages
- Files: `modules/step3_metadata.py` — `_process_qcms` (carry the new state
  alongside `cc_carry_over`), `_propagate_cas_clinie` (resolution contract,
  attach path).
- Changes: new in-loop variable `cc_pending_case` — set/cleared exactly per
  §2.2; resolution at the next QCM-bearing page via the existing statuses
  (`continues`/`new_case` claiming semantics + attach + clear); decline path
  (`unrelated`/`ends_here`-without-new) — drop forever; scenario 1b keeps
  `pending_case` alive over QCM-free pages.
- Verify: unit battery for 1a/1b/1c at the propagation level before any UI/
  audit concerns; assert distinct state names (never conflated with
  `cc_carry_over` — a running case and a pending candidate may co-exist; see
  OQ-2 for precedence).

### H-4 — Strategy scoping (per_group / skip gates)
- Files: `modules/step3_metadata.py` (`_process_qcms`, propagate via
  `linkage=` flag — already exists).
- Changes: `per_group` → full pending resolution path; `skip` → the
  resolution attempt still runs (single attach-once-or-drop, no chain, no
  checker); `global` → `trailing_narrative` is parsed but IGNORED (no
  pending, unchanged propagation) — exact cost contract: under G the extra
  field costs prompt tokens only.
- Verify: three strategy sub-tests; assert extend-not-replace (per-group and
  skip suite behaviors byte-identical when no trailing narrative exists).

### H-5 — Audit note + build/xlsx passthrough + rollout verification
- Files: `modules/step3_metadata.py` (notes as §2.4 — zero new columns; the
  note rides the EXISTING `case_belonging_check` key), plus the shipped
  surface (already passes the note through build → XLSX/Sheets) and the
  `post_step2_metadata` wiring (no changes needed for this fix — the per-page
  loop already runs before checker/boundary; order is preserved).
- Changes: nothing new to thread; only the note text is new.
- Rollout verification: run the 1a/1b/1c scenario files end-to-end through
  `_process_qcms` with mocked LLMs (assert attach/decline/audit), then run
  the full phase 0–7 suite set + regression suites (the "regression anchor"
  from the shipped rollout) and confirm: same-page new_case behavior
  byte-stable; a page with truly no narrative still returns null and costs
  zero behavioral change (existing suite coverage is the regression gate).

---

## 4. Test plan

**New capability scenarios (must):**
1. **1a direct:** page N ends with narrative + zero QCMs → page N+1 opens
   with the full QCM. Assert: page-N call DOES run (QCM-free page), returns
   `trailing_narrative`; `pending_case` set; N+1's prompt embeds the pending
   block; claim → attach with note `new_case (cross-page): ... page N`
   in `case_belonging_check`; chain exists → (per_group) checker verifies it
   as an ordinary chain.
2. **1b endurance:** narrative → N+1 QCM-free (detection still runs, returns
   the SAME narrative or null) → N+2 first QCM claims it. Assert pending
   survives; the attach happens at the FIRST QCM-bearing page only.
3. **1c decline:** next QCM does not claim the candidate (returns
   `unrelated`/`ends_here`) → decline → `pending_case = None`, NO `cas` on
   the QCM, decline note in `case_belonging_check` on the DECIDING QCM, and
   the candidate is NEVER retried on any later page (later pages show no
   reference to the dropped narrative).
4. (bonus) 1d: multiple cases per page + a pending candidate — pending
   resolves first, later `new_case` replaces `current_cas` normally; two
   states never bleed into each other.

**Regression anchors (must):**
1. **Same-page new_case unchanged:** narrative followed by a QCM on the SAME
   page — no `trailing_narrative`, no `pending_case`, exact same statuses and
   audit note as today (`new_case: <label> starts this case`).
2. **No-narrative page:** zero QCMs AND no narrative — `trailing_narrative`
   = null, no pending created, no extra prompt states; QCM-free walk-over
   pages processed without LLM calls when there is nothing pending (open
   question OQ-4 decides whether QCM-free narrative-less pages get scanned
   at all, at zero-LLM cost).
3. **Quantified check:** pages that already work today must produce byte-
   identical `all_qcms.json` (cas + notes) before vs. after the fix when no
   trailing narrative exists anywhere (assert on the synthetic corpus from
   the shipped characterization).

**Cost contract (same discipline as the redesign):** same per-page call
budget; `trailing_narrative` rides the SAME call (one more field); the ONLY
behavioral add is calling the detection for QCM-free pages (which today get
zero calls) — one call per QCM-free page that contains any page text, gated
by strategy per §2.3.

---

## 5. Open questions (decisions needed BEFORE implementation)

- **OQ-1 — Where does the new field live in the output?** Option (a) tuple
  return from `_detect_cc_sequential_page` (caller unpacks, most explicit,
  mirrors the propagation return signature) vs. Option (b) reserved key in
  the returned dict (single return shape; risks the `_trailing` sentinel ever
  colliding with a real QCM number key — QCM numbers are ints, so a `"_trailing"`
  string key cannot collide). Leaning: (b), fewer call-site changes across
  `per_group`/`skip` paths, and the shipped contract already tolerates
  dict-plus-description shapes (`_parse_cc_statuses`).
- **OQ-2 — Precedence when BOTH a running case (`carry_over`) and a
  `pending_case` exist at a QCM-bearing page:** today's carry-over semantics
  say QCMs after the running case stay with it until `ends_here`/new_case. If
  a trailing candidate ALSO exists, the first QCM could legitimately claim
  either. Proposal: give the LLM both blocks (active case + pending
  candidate) in the prompt and let the statuses decide; the FIRST resolution
  target wins and the other stays for later QCMs/page ends. Needs a sign-off
  because it changes what `continues` means on that page (continues the
  running case vs. claims the candidate — the note disambiguates).
- **OQ-3 — Does `pending_case` need re-affirmation across QCM-free pages?**
  Option A: Python keeps it alive across QCM-free pages (cheapest — but then
  a "decade-long" candidate could theoretically live over many blank-looking
  pages); Option B: each QCM-free page's call must RE-CONFIRM (return the
  same `trailing_narrative`) or the candidate drops (protects against
  phantom-carry across genuinely unrelated content; costs +1 call per
  QCM-free page but the loop has to visit those pages anyway per OQ-4 /
  the 1b walkthrough). Recommendation: Option A (persistence without
  re-affirmation) for v1 — simpler, matches `carry_over` durability, and the
  single-resolution contract already bounds staleness to "resolved at the
  next QCM, or dropped".
- **OQ-4 — Scan policy for QCM-free pages.** Today QCM-free pages get NO
  detection call (early `qcm_numbers` guard). The fix needs calls on pages
  that may hold a trailing narrative. Choices: (i) always scan every page
  with text (any strategy that has detection enabled); (ii) scan only when a
  later page could plausibly have a QCM (cannot know cheaply — reject);
  (iii) scan QCM-free pages ONLY when the NEXT page contains QCMs (i.e.,
  look-ahead by page index in `_process_qcms` — deterministic, no extra look
  back). Cost check under `skip`: this NEW call changes what skip costs the
  same way Phase-6 did (the "skip still costs ~1 call per page" copy in
  `Step3Config` stays accurate). Recommendation: (i), with the same
  per-page budget discipline; (iii) is an optimization to revisit if the
  cost adds up on QCM-heavy docs with many narrative-less footers — but note
  (iii) cannot help scenario 1b (it would skip the middle QCM-free pages —
  acceptable, since only the FIRST narrative page's trailing output is what
  seeds `pending_case`).
- **OQ-5 — `ends_here` interplay:** trailing narrative is a CANDIDATE, not a
  running case; can a QCM-bearing page that declines it via an explicit
  `ends_here` (rather than `unrelated`) trigger the same ONE resolution and
  the same drop contract? Recommendation: yes — treat both decline statuses
  identically for the pending candidate (the distinction between
  `unrelated`/`ends_here` remains meaningful for the already-running case).
- **OQ-6 — Decline audit entry on decline:** confirm that the decline note
  (§2.4) should be written ONLY on the deciding QCM (one line, reviewer-
  visible) — never on the QCM-free narrative pages, and never as `cas`.

---

## 6. Reference behaviors (do-not-touch invariants for this fix)

1. `cas` string format `"{label}\r\n{narrative}"` — unchanged.
2. QCM identity = **uid**; per-page detector semantics unchanged for pages
   WITH QCMs beyond the new field.
3. Failure policy (unresolved ⇒ keep; two NOs ⇒ close chain) — untouched.
4. Same-page trigger flow (the dominant case today) — byte-identical.
5. Cascade order + soft-fail contract (hint → cas_split → step3 → boundary →
   checker → build) — untouched; `trailing_narrative` is consumed INSIDE
   Step 3's page machinery only.
6. Strategy G untouched; `skip` costs documented in the UI already stay accurate.
7. Idempotency (uid-set gates + checker uid audit) — unchanged; H-phases add
   no new persisted artifacts (pending_case is in-run state only).
