# CC Detection v4 — Step 3 per-page sequential CC detection prompt (frozen)
> Section "4. STEP 3 — per-page sequential CC detection — `step3_metadata.py`".
> Source of truth: `_detect_cc_sequential_page()` in `modules/step3_metadata.py`
> (CC Detection v4, commit `7dbcc4b`). This file is a REVIEW COPY of the
> exact prompt the model receives — reproducing it verbatim (f-string with
> the variable slots marked) so reviewers can audit the wording without
> reading code. Companion docs: `CC_DETECTION_V4_PLAN.md`,
> `CC_LLM_LAYERS_AUDIT.md` (this is L1 in that audit).

---

## Build-time variables injected before the template

| Slot | Source | Value |
|---|---|---|
| `carry_block` | `carry_over` argument (the running `cas`, split into label + 1500-char preview) | ACTIVE-case block IF a case is running, else the NONE block |
| `pending_block` | `pending_case` argument (a cross-page trailing candidate not yet attached) | PENDING block, only if one exists |
| `trailing_hint_lines` | computed | WITH QCMs: `max(QCM numbers on this page) + 1`; WITHOUT QCMs: the zero-QCM convention |
| `nums_str` | `qcm_numbers` argument | comma list, or "none — this page holds no numbered questions" |
| `page_text` | `page_N.txt` (step-1 OCR text) | truncated at `STEP3_MAX_INPUT_CHARS` (24000) |

Model policy: `STEP3_MODEL` default `google/gemini-2.5-pro` (reasoning
capable — the primary), fallback `google/gemini-2.5-flash-lite`
(`STEP3_FALLBACK_MODEL`); 2-call ceiling; blank/parsable-fail counts as
failure and retries via the fallback (`_parse_cc_response` sniffs the
schema). One call per page.

---

## The prompt (as generated, verbatim)

```text
You are analyzing one page of a French medical exam (OCR text) to find any
clinical-case ("Cas Clinique") narratives on it, and to determine exactly
which QCM number each one belongs to. Think it through before answering.
<CARRY-BLOCK>

## Trailing cases
{trailing cases instruction}

## What IS a clinical case narrative
Descriptive prose about a specific patient: a name or initial, an age, and
their clinical/paraclinical profile (history, presenting complaint, exam
findings, lab/imaging results). Third person, describing someone — never
instructing or asking the reader anything. This is the PATTERN, not literal
text to match:
- "Madame F., 37 ans, suivie pour une thyroïdite de Hashimoto..."
- "Zhor, 77 ans, est diabétique de type II, découvert en 2021. Bilan
  initial: GAJ: 1.92 g/l, HbA1c=7.9%..."
A narrative may lack any "Cas Clinique" header and may even be FUSED directly
into the FIRST question's own text block with no separator — in that fused
case you STILL report it as an anchor (see anchor_text_clean below).

## What is NOT a clinical case narrative (confirmed real mistakes to avoid)
- An ordinary question stem, even when medically coherent and well-written:
  "Parmi les causes de syncope au cours de la cardiomyopathie hypertrophique,
  on peut citer:" — this is a question, not a patient.
- Short fragments with no sentence structure — isolated numbers, page
  annotations, section headers: "HTA 38 30" — OCR noise, not a narrative,
  regardless of where it sits.
- A lettered answer-choice list — "a- ... b- ... c- ... d- ... e- ..." (with
  or without checkmarks) — always propositions, never a narrative.
If you are not confident something is a genuine patient narrative by this
definition, do not report it.

## Which QCM it belongs to
A narrative belongs to the QCM immediately after it in reading order — never
to a QCM that already appeared earlier in the text, even if no better
candidate exists on this page.
If the page ENDS with a narrative and no QCM follows it on this page at all
(this includes pages with ZERO numbered questions), it belongs to the next
page's first question — the "Trailing cases" section above tells you what
anchor_num to report in that situation.

## Output format
Return a JSON array. Include an entry ONLY for each QCM number that anchors
a genuine NEW narrative — do NOT list every QCM on the page:
[
  {
    "anchor_num": <int>,
    "cas_label": "<as written, or \"CAS CLINIQUE\" if unlabeled>",
    "cas_text": "<the narrative only — patient story, nothing else>",
    "anchor_text_clean": "<if the narrative was fused directly into this
       QCM's own question text with no separator, that QCM's own text with
       the narrative removed — null if the narrative was already a
       separate block>",
    "note": "<one short sentence — why this is a genuine narrative>"
  }
]
If no genuine narrative starts on this page, return [].

QCM NUMBERS ON THIS PAGE (in order): [{nums_str}]

Return ONLY a valid JSON array — no markdown fences, no explanation.

PAGE TEXT:
{page TEXT}
```

---

## The three variable blocks (exact wording)

### (1) `carry_block` — when a case IS running

```text

CURRENTLY ACTIVE CASE (carried over from an earlier page — running now):
- Label: {label}
- Narrative (may be truncated): {narrative[:1500]}
This case is ALREADY linked — you never need to anchor it again. Report an
anchor ONLY when a NEW patient narrative starts on this page; the active
case flows automatically over un-anchored questions.
```

### (1b) `carry_block` — when nothing is running

```text

CURRENTLY ACTIVE CASE (carried over from an earlier page): NONE.
```

### (2) `pending_block` — only when a cross-page pending candidate exists

```text

PENDING CASE — DETECTED AT THE END OF AN EARLIER PAGE (NOT yet attached to any question):
- Label: {label}
- Narrative (may be truncated): {narrative[:1500]}
This pending narrative is ALREADY TRACKED by the pipeline: it attaches
automatically to the first question of a coming page. Do NOT re-report it
as an anchor of your own — only report anchors for NEW patient narratives
that genuinely appear on THIS page.
```

(When no pending case exists, this block is omitted entirely.)

### (3) `Trailing cases` instruction — the Num hand-off (V4 requirement)

With QCMs on the page (anchor = `max(page numbers) + 1`):

```text
When the page ENDS with a narrative and no QCM follows it on this page,
report anchor_num = {max(qcm_numbers) + 1} — the pipeline delivers it to that
QCM's "Num" on the next page on your behalf.
```

Without QCMs (zero-QCM page):

```text
This page holds ZERO numbered questions: if a patient narrative exists
anywhere in this page text, report it as an anchor with anchor_num 1 and
full cas_text — the pipeline routes it to the next page's first question
by Num.
```

---

## What happens to the answer (downstream contract, one call, no new layers)

1. `_parse_cc_response` sniffs the schema:
   - `anchor_num` IN the page's own numbers → a `new_case` entry in the
     per-page map (the shipped propagation consumes it unchanged).
   - `anchor_num == max(nums)+1` (or ANY anchor on a zero-QCM page) → routed
     into the reserved `"_trailing"` key → the shipped `pending_case`
     machinery resolves it on the NEXT page's first QCM — **keyed on the
     merged JSON's `Num`** (both `number` and `Num` accepted at every
     read site; the Num-gap predicate warns log-only when the next page
     does not start at `max+1`).
   - anything else → entry DROPPED, logged
     (`[CC-V4] anchor proposal rejected …`), never cascaded.
   - legacy 5-status responses still parse through `_parse_cc_statuses`
     untouched (backward compatibility for tests/corpus mocks).
2. `_apply_anchor_extras` — `anchor_text_clean` (non-null) REPLACES the
   anchored QCM's question text (`text`/`Text`); a null clean runs
   `cas_text_split` on that QCM as the safety net; the `note` is stored as
   `cc_detector_note = "detector: <note>"` — NEVER inside
   `case_belonging_check` (the checker's verdicts keep their own column
   wording).
3. Propagation / carry-over / `claims_pending_case` / CC Checker / boundary
   stage: zero changes — they see the same `{qcm_number: {status,label,text}}`
   shape as before.

## Review checklist for this prompt

- [ ] The two CONFIRMED-mistake examples (question stem, OCR noise) are
      present on every call.
- [ ] The trailing instruction's `anchor_num = max+1` VALUE is the real
      computed number for THIS page (never a stale/absolute number).
- [ ] The `PENDING CASE` block tells the model NOT to re-report the pending
      narrative — the pipeline resolves it (the model re-reporting it would
      double-attach).
- [ ] `anchor_num` semantics survive the zero-QCM page (whole page = holder
      for the trailing narrative).
- [ ] The `note` is L1-only (`detector:` prefix) — it must never be parsed
      into `case_belonging_check`.
