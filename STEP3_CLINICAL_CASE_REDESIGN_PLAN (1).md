# Clinical Case (Cas Clinique) Handling — Redesign Plan v2

> Companion to `STEP2_STEP3_EXPLAINER.md` / `STEP2_STEP3_CODE_CONTEXT.md`.
> This is a PLAN, not code — for review before anything gets implemented
> (e.g. fed to OpenCode as a scoped phase).
> Constraints locked in for this plan: (1) real misclassifications already
> observed in prod, not just theoretical; (2) the vast majority of cases have
> NO literal "CAS CLINIQUE N" header before the narrative, so detection
> cannot anchor on regex/structure — it must stay LLM/semantic; (3) stay near
> the current 2-layer LLM budget (per-page detection + cheap verification),
> no new layer added by default.

---

## 1. Diagnosis — the two blind spots in the current design

The current `_detect_cc_sequential_page` call answers exactly one binary
question per QCM: *"is this the very first question of a NEW case?"* Every
QCM that isn't a trigger gets `null`, and Python's `_propagate_cas_clinique`
then blindly carries whatever case is currently running **forward until the
next trigger fires** — with no explicit signal that the case has ended.

This creates two blind spots, and they're asymmetric:

1. **Over-propagation is eventually caught, but expensively.** If a case
   keeps getting silently copied onto QCMs it doesn't belong to, the CC
   Checker *will* eventually catch it — two consecutive verified NOs close
   the chain. But that's N verification calls spent walking through wrongly
   -tagged QCMs before the system self-corrects. It's a real but recoverable
   cost.
2. **Under-detection is invisible and unrecoverable today.** If the per-page
   detector fails to recognize a narrative as a new trigger, or fails to
   recognize that the running case has ended, nothing gets written — and the
   checker has nothing to check, because it only verifies links that already
   exist. There's currently zero mechanism catching a missed case boundary.
   This is the more dangerous failure mode, and it's the one most likely
   behind "case wasn't linked at all" bugs.

Both blind spots trace back to the same root cause: **the detector has no
concept of "currently running case" — it only ever looks for new starts, and
Python fills in the rest by assumption, not confirmation.**

---

## 2. The fix — make the existing per-page call state-aware (no new layer)

Keep exactly the same call shape: **1 LLM call per page**, same place in the
cascade (Step 3, before the checker). What changes is what it's asked and
what it returns.

### 2.1 Input change
The per-page prompt now also receives the **carry-over case** from the
previous page (label + narrative), when one is active — today's page call is
stateless about this; it doesn't know a case is even running.

### 2.2 Output change
Instead of `{qcm_number: "LABEL\r\nNarrative" | null}`, return one status per
QCM number on the page, chosen from:

| Status       | Meaning                                                              |
|--------------|-----------------------------------------------------------------------|
| `new_case`   | First question of a fresh narrative appearing on this page (+ label/text) |
| `continues`  | This QCM depends on the currently active (carried-over) case — explicit confirmation, not a default |
| `ends_here`  | The active case does NOT cover this QCM — explicit termination, no new case starts |
| `unrelated`  | No case applies, and none was running                                |
| `uncertain`  | Genuinely ambiguous — defer to the checker, same as today's fallback |

This is still one call per page — the prompt is heavier (carries case
context + 5 choices instead of 2), but no new call is added anywhere.

**Confirmed real failure this targets (§5.3):** the dominant known misses
happen when the case narrative is fused directly into the QCM's own text
block with no separator at all — the detector reads the whole block as
"context for the question" instead of recognizing a distinct patient
narrative inside it. The `new_case` instruction has to say this explicitly:
even when patient-specific content (age, presenting complaint, exam/lab
findings) is fused into what looks like a single question block, preceding
the actual interrogative/imperative sentence, it must still be classified
`new_case` — never folded into the question as background.

### 2.3 Updated propagation logic (still pure Python, still page-ordered, still carries state across pages)

- `new_case` → replace `current_cas`, apply to this QCM onward.
- `continues` → keep `current_cas`, apply — now an *explicit confirmation*
  instead of a blind default.
- `ends_here` → clear `current_cas` for this QCM and forward (until the next
  `new_case`). **This is the direct fix for over-propagation at the source**,
  instead of waiting for the checker to trim it after the fact.
- `unrelated` → no-op (nothing running, nothing to attach).
- `uncertain` → fall back to today's behavior (persist `current_cas` if any).
  This is the safety valve: it means the new design can never have *less*
  recall than the current one — worst case, an ambiguous QCM degrades to
  exactly today's blind-propagate behavior, and the checker still backstops it.

### 2.4 What the CC Checker does differently
Mechanically, nothing changes — same chain-building, same parallel-chains /
sequential-within-chain, same early-stop two-NO rule, same §7 re-check. What
changes is its **job**: it now mainly backstops `uncertain` classifications
and any residual detector errors, rather than being the primary mechanism
that discovers every over-extension. Expected effect: **verification call
volume should go down or stay flat**, even though the detection prompt got
slightly heavier — net cost should not exceed the current 2-layer budget.

### 2.5 Checker enhancement — accumulated case-fact ledger within a chain

Today each verification call sees only the raw case narrative + the single
QCM being checked, in isolation. Add a **running, chain-scoped ledger** of
case-specific facts confirmed by earlier QCMs in the same chain:

- Each verification call, when it returns `applies: true`, also returns a
  short `case_facts_used` note — the specific patient/case facts (not
  course/topic facts) that were needed to answer that QCM. Same call, no new
  layer — just one more field on the existing JSON response.
- That note is appended to a per-chain ledger and passed into the **next**
  QCM's verification prompt alongside the raw narrative: `narrative +
  accumulated ledger + this QCM`. Chains already verify strictly
  sequentially internally, so this fits the existing control flow with no
  reordering.
- **Scope guardrail, and this is the important part:** the ledger only ever
  holds patient/case-specific facts (age, findings, lab values, established
  diagnosis, etc.) — never general subject/topic language. This is exactly
  because of the risk you flagged: two QCMs from the *same course* but a
  *different* clinical case must never get linked. If the ledger absorbed
  topic/course vocabulary instead of patient-specific facts, it would make
  every same-topic QCM look progressively more "connected" as the chain goes
  on — the opposite of what you need. Keeping it strictly patient-scoped is
  what makes it safe to add rather than a source of drift.
- Ledger resets per chain (new case = fresh ledger, no bleed-over between
  cases). A NO verdict, or an unresolved/failed verdict, never contributes to
  it — only confirmed `applies: true` QCMs write to the ledger, so a rejected
  or uncertain link can't quietly reinforce the next check.

### 2.6 Skip strategy — text hygiene without case linkage

Today, `ClinicalCase = skip` disables clinical-case handling entirely — zero
detection calls. If a narrative is merged into a QCM's question text, it
stays there, uncleaned and duplicated, forever.

Requested change: **decouple text hygiene from case linkage.** Reuse the same
per-page detection call from §2.2 under `skip` too, but gate what its output
is allowed to do:

- `new_case` / `continues` / `ends_here` still get classified (same call,
  same prompt) — but under `skip`, propagation across QCMs is disabled: a
  detected narrative is applied ONLY to the QCM(s) it's directly attached to,
  never carried forward, no chain/group ever forms.
- The CC Checker still does not run under `skip` — there's no multi-QCM
  linkage to verify, just single-QCM text cleanup.
- `cas_text_split` still runs exactly as it does today on whatever narrative
  got extracted — no change to that mechanism.
- Net effect: under `skip`, question `text` is always clean of embedded
  narrative and the narrative always lands in its own Cas column for that
  specific QCM — but no cross-QCM case relationships get built or verified.

**Cost note, stated plainly:** this changes what `skip` costs. Today it's
zero clinical-case LLM calls. Under this change it becomes ~1 detection call
per page (the same call reused from §2.2), just without any checker calls on
top. Still cheaper than `per_group`, but no longer free — flagging this
because it's a real shift in what `skip` has meant so far, not a hidden side
effect.

### 2.7 Audit column — `case_belonging_check` (decided: yes, own column)

Resolved decision (see §5.1): the reasoning behind a case-linkage
outcome — whether from `ends_here` at detection, or a `applies:false` /
§7-recheck verdict at verification — gets a short human-readable note. It
does **not** go into the `cas` column, which stays reserved for the actual
narrative text only, unchanged. It goes into a new dedicated column,
`case_belonging_check`, populated for every QCM that had a case-linkage
decision made about it. Examples: `"ends_here: case does not inform this
question"`, `"checker NO (0.85): answerable without case info"`, `"checker
YES: uses reported diagnosis from case"`. This also folds in the checker's
`case_facts_used` ledger entries from §2.5 for confirmed links. Purpose: one
unified, human-readable audit surface a reviewer can scan without opening
internal logs or JSON — while keeping `cas` itself clean and unaffected, so
nothing downstream of `cas` (`cas_text_split`, the build step) changes.

---

## 3. Residual gap — true total blindness only

The confirmed real failure mode (§5.3 — narrative fused into the QCM's own
text with no separator, misread as ordinary question context) is now
addressed directly inside §2.2's classifier design, not left as an open
mitigation here. What's left in this section is the narrower, harder
residual case: **true total blindness** — a page-level call that never
notices a narrative exists at all, anywhere in the page's raw text (not
merged, not separated, just missed outright), with no carry-over to fall
back on. Since there's no header to anchor recall on, this can't be fully
eliminated by a single-page/single-call detector. Two mitigations, both
optional and outside the default budget:

- **Free fix (prompt only, no added calls):** give the detector explicit
  guidance on what unmarked narratives look like in this corpus — descriptive
  third-person patient history (age, presenting complaint, exam findings)
  vs. imperative/interrogative question stems ("Quelle est votre conduite…",
  "Parmi les propositions suivantes…"). This costs nothing but prompt tokens.
- **Opt-in safety net (off by default, costs an extra call only when used):**
  the dormant `_detect_clinical_cases_document` path already exists and is
  built for exactly this — one whole-document pass that's less prone to
  page-boundary blindness. Rather than running it always (which would break
  the "stay lean" constraint), it could run **only** as a triggered
  reconciliation pass when a document's case-tagged ratio looks anomalous
  relative to what's typical for that exam/module — a cheap Python heuristic
  gate, not a default LLM cost.

---

## 4. Compatibility — invariants preserved

Mapped against the invariants list already established for this pipeline:

1. `cas` string format (`LABEL\r\nNarrative`) — unchanged.
2. uid-keyed identity — unchanged; nothing here touches uid assignment.
3. Cross-page carry-over — preserved, and arguably strengthened (now
   explicitly confirmed per page instead of assumed).
4. Failure policy (unresolved ⇒ keep link; two verified NOs ⇒ close chain) —
   unchanged in the checker.
5. Idempotency (uid-set gating) — unchanged.
6. Cascade order and soft-fail contract — unchanged; only the internals of
   `_detect_cc_sequential_page` and `_propagate_cas_clinique` change.
7. Narrative lives only in the Cas column — unchanged; `cas_text_split` is
   untouched by this plan.

**Blast radius:** this plan only touches the detection prompt/output schema
and the propagation function. The checker, `cas_text_split`, the build step,
and Step 2 are untouched.

---

## 5. Open decisions before implementation

1. **RESOLVED** — `ends_here`/verdict reasoning: yes, keep a short reason
   string. Stored in a new dedicated column, `case_belonging_check`, never
   in `cas` itself. See §2.7.
2. **RESOLVED (leaning deferred)** — the opt-in document-level
   reconciliation pass (§3) is not built for v1. Pages with no case at all
   are already handled by the normal per-page call at zero extra cost (that
   IS the `unrelated` classification from §2.2 — no second check, no added
   layer); the free prompt-guidance fix is the only mitigation shipped for
   "total blindness" initially. The reconciliation pass stays documented as
   a fallback, only worth building if missed-case issues persist after this
   redesign ships.
3. **RESOLVED** — the real prod misses are caused by merged narratives: the
   case text is fused directly into the QCM's own text with no separator, and
   the detector reads the whole thing as "context for the question" rather
   than a distinct case narrative. This is a §2.2 detection problem, not an
   over-extension problem — confirms the state-aware classifier + its
   confirmed-pattern guidance are the right primary fix, and supports keeping
   the reconciliation pass deferred (decision 2): the failure mode is now
   precisely understood, not a vague blind spot needing a statistical safety
   net.
4. **RESOLVED** — this situation doesn't occur in the corpus: a case
   narrative is always fully contained within a single page, even when the
   QCMs it applies to (under `per_group`) come later on subsequent pages.
   So under `skip`, plain independent-per-page evaluation is sufficient —
   no carry-over-awareness needed for narrative-text completeness, since a
   page will always contain the whole narrative if one starts on it. This
   is separate from, and doesn't affect, the existing cross-page *linkage*
   behavior under `per_group` (§2.1) — that's about a complete narrative on
   one page applying to QCMs on later pages, not the narrative text itself
   splitting.
