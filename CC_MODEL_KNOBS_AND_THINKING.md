# CC model knobs + thinking-mode instruction (explanation of the change)
> Answers: (1) WHICH model knobs matter for clinical-case work — is it Step 2?
> the checker? — and (2) the request (prompt) edit that asks the model to
> THINK when it has thinking abilities, which has now been applied to the
> Step-3 CC detection prompt. Reference: `CC_LLM_LAYERS_AUDIT.md` (L1–L4).

---

## 1. Which model does what — the knob map (do NOT mix them)

Each clinical-case layer has its OWN pair of env knobs. Changing Step 2's
model does NOT change CC detection, and changing the checker's model does
not change detection.

| Layer | File | Primary knob | Fallback knob | Current defaults |
|---|---|---|---|---|
| **Step 2** (QCM extraction — NOT clinical-case logic) | `step2_qcm_extract.py` / `_batch` | `STEP2_MODEL` | `STEP2_FALLBACK_MODEL` | `gemini-2.5-flash-lite-preview-09-2025` / `nvidia/nemotron-3-super-120b-a12b:free` |
| **L1 — Step-3 CC detection (THE one you asked about)** | `step3_metadata.py::_detect_cc_sequential_page` | `STEP3_MODEL` | `STEP3_FALLBACK_MODEL` | **`google/gemini-2.5-pro` (reasoning, primary)** / `google/gemini-2.5-flash-lite` |
| **L2 boundary + L3/L4 checker** | `clinical_case_checker.py` | `CC_CHECKER_MODEL` | `CC_CHECKER_FALLBACK_MODEL` | `DEFAULT_CC_MODEL` / `DEFAULT_CC_FALLBACK` (cheap/fast — deliberate) |
| Shared per-layer extras | — | `STEP3_MAX_TOKENS` (10000) / `STEP3_MAX_INPUT_CHARS` (24000) | — | `CC_CHECKER_MAX_TOKENS` (500), `CC_CHECKER_MAX_PARALLEL`, `CC_CHECKER_EARLY_STOP` |

Practical answer:

- To change the **case-context DETECTION** model → set `STEP3_MODEL`
  (+ `STEP3_FALLBACK_MODEL` if you want a different safety net).
  Step 2's `STEP2_MODEL` has **nothing to do with it** (Step 2 extracts QCMs
  and carries hints; it does not detect clinical cases).
- The checker deliberately stays on a CHEAP fast model — its job is binary
  verdicts (`{"applies": true/false}`) over facts already extracted; a
  reasoning model there buys nothing and multiplies the by-far-biggest call
  count (1 per linked QCM, parallel 5). Leave `CC_CHECKER_MODEL` alone
  unless evidence shows verdict quality problems.

UI note: the "Model policy" panel sets these same env knobs — picking a
different model in the UI currently routes to the shared `STEP3_MODEL`
family of settings, so config survives without code edits.

---

## 2. The thinking directive that was ADDED (edit applied)

Location: `_detect_cc_sequential_page`, the prompt header — replacing the
single line "Think it through before answering." The new instruction is
model-agnostic (self-disarming for non-reasoning models, and harmless in
front of the many OpenRouter model families that expose internal thinking
differently):

```text
THINKING (use it if your model exposes reasoning/thinking abilities — ignore
this section otherwise): before answering, silently reason step by step:
(a) locate every block of this page that reads as a patient-situation
description by the definition below; (b) for each candidate, check the
not-a-narrative list (question stems, OCR noise fragments, proposition
lists) and discard anything failing it; (c) decide the owning QCM by
reading order, applying the trailing rule for narratives nothing follows;
(d) prepare anchor_text_clean for fused blocks; (e) only then emit the
JSON array. Never print the reasoning itself — the JSON array alone is
the answer.
```

Why THIS is the right shape for a thinking-capable model:

1. **It scopes WHAT to reason about** — the five concrete passes (locate →
   filter → owning-QCM → fused-cleanup → emit), in the order the per-page
   task actually needs. Generic "think hard" prompts produce generic
   reasoning; this one seeds every pass with the right question.
2. **It keeps the reasoning INVISIBLE** — OpenRouter-style endpoints return
   one content string; the parser (`_parse_cc_response`) expects the JSON
   array alone. Both branches (v4 anchor schema AND legacy 5-status) grep
   for a JSON array, so silent thinking is safe while printed reasoning
   would poison the parse.
3. **Cost/latency discipline holds** — nothing about the protocol adds
   calls or tokens if the chosen model has NO thinking mode (the section
   self-deactivates); for thinking models the extra tokens are the model's
   own thinking budget, not a second call. The 2-call ceiling and
   per-page budget are unchanged.
4. **max_tokens hygiene** — the reasoning happens OUTSIDE the answer, but
   `STEP3_MAX_TOKENS` (10000) must still cover narrative cas_text output;
   if a thinking model eats the budget, raise `STEP3_MAX_TOKENS` rather
   than trimming the reasoning (the parser treats a TRUNCATED JSON array as
   a failure and re-tries with the fallback model).

What was NOT changed on purpose:

- The **checker** (L3/L4) gets NO thinking directive — its prompt is a
  boolean, per-question verdict with early-stop economics; the DEFINITION
  text says "apply it exactly", forcing deterministic judgment, and a
  thinking budget there would multiply the biggest cost bucket of the whole
  cascade for near-zero gain.
- **Step 2** extraction logic is untouched.

## Verification

- `tests/test_cc_v4_anchors.py` — 12/12 PASS (the prompt-surface test
  asserts on the schema markers, not the thinking line, so it is stable).
- `tests/test_cc_redesign_phase0_characterization.py`,
  `test_cc_redesign_phase1_detector.py`, `test_cc_cross_page_narrative.py`
  — ALL PASS (the frozen F6/P1.4 contracts survive the wording edit).
- Review copy of the prompt: `STEP3_CC_DETECTION_V4_PROMPT.md` — add the
  thinking protocol there when it is next regenerated (the doc's prompt
  quote above is now one revision behind by exactly this block).
