# Antigravity — Redo Plan (Clinical Case Checker + Metadata/Hint Rework)

> How to use this file: paste **one phase at a time** into OpenCode. Ask it to
> propose a plan for that phase only, review the plan before it touches code,
> and confirm the plan does not include anything outside the "In scope" list.
> Do not let it batch multiple phases into one pass.

## Ground rule for every phase

Implement **only** what is listed under "In scope" for that phase. No
unrelated refactors, no state-migration shims, no "while I'm in here" fixes,
no legacy-compatibility layers unless a phase explicitly asks for one. If
something else looks like it needs to change to make a phase work, stop and
ask before doing it instead of implementing it silently.

---

## Phase 1 — Clinical case cascading (per-QCM)

**Behavior:**
- This is a togglable option ("per group"), not forced-on. When enabled:
- When the system finds a "cas clinique" (clinical case) text attached to a
  QCM, that text is applied to every QCM that follows it *until* a QCM with
  its own new clinical case text is found.
- Example: clinical case text found at QCM 1 → applies to QCMs 1, 2, 3, 4
  (none of which have their own). QCM 5 has its own new clinical case text →
  that new text now applies to QCM 5 onward, until another new one appears.

**Verification step:**
- Use a cheap/fast model (example given: `inception/mercury-2.5-preview`) to
  double-check the linkage.
- Check QCM by QCM, starting from the first QCM that has an attached
  clinical case text.
- For each QCM in the chain, ask **one** simple verification question
  confirming that the clinical case really applies to that QCM.

**Reference:** full spec lives in `clinical_case_checker.md` — pull any
detail not covered above from that file directly, it is the source of truth.

---

## Phase 2 — Remove "Subcategory" completely

- Metadata Strategy currently has: Year, Category, Subcategory, Source,
  Clinical Case.
- Remove **Subcategory only** — Year, Category, Source, and Clinical Case
  stay untouched.
- Remove it from **both** frontend and backend: config schema, API payloads,
  DB/JSON fields, and the UI control.
- This must be a full removal, not a hide/disable. Acceptance check: after
  the change, there should be **no** leftover "Subcategory" element anywhere
  in the Step 2 config UI (e.g. no dead "Subcategory … Skip" cycle button
  still rendering).

---

## Phase 3 — Hint detection (new, always-on backend feature)

- New backend-only feature. **Always runs** — it is not a user-facing
  toggle.
- Location in source text: the hint block always appears at the very end of
  a QCM, right after the last proposition (after proposition E).
- Pattern example as it appears in OCR output:
  ```
  A(1+2+3)
  B(1+3+4)
  C(2+3+4)
  D(3+4+5)
  E(2+4+5)
  ```
- Parsing rule: inside each line, map the numbers to proposition letters
  using **1=A, 2=B, 3=C, 4=D, 5=E**, then join the mapped letters into a
  combo string for that line (e.g. `A(1+2+3)` → `A,B,C` → `"ABC"`).
- For the example block above, the required output is exactly:
  ```json
  ["ABC", "ACD", "BCD", "CDE", "BDE"]
  ```
  (order follows the order the lines appear in, A-line first through E-line
  last). This confirms the number→letter substitution above is the whole
  algorithm — nothing fancier.
- Output field: JSON key `hint`, an array of these combo strings. If a QCM
  has no hint block, output `hint: []`.
- Destination: XLSX maker writes this into a dedicated **Hint** column,
  placed immediately after the proposition E column.
- Hard constraint: the raw hint block content (e.g. the literal text
  `A(1+3+4)`) must **only** ever land in the Hint column. It must never be
  written into, or used to overwrite, the proposition (A–E) text columns.

---

## Phase 4 — Dedicated "Cas" (clinical case) column in XLSX output

- The XLSX produced by the pipeline steps needs its own column for the
  clinical case context/text.
- That clinical case text must **not** be merged/concatenated into the
  question-text column — it stays in its own separate column.

---

## Phase 5 — Proposition detector must support both A–E and 1–5 labeling

- Current QCM-detection prompt structure only recognizes and maps
  propositions labeled with letters (A, B, C, D, E).
- Fix: make it handle **both** labeling styles found in source documents —
  letters (A–E) and numbers (1–5) — routing each proposition into the
  correct column (e.g. label "1" or label "A" both go to the A column, and
  so on) regardless of which style the source PDF uses.
