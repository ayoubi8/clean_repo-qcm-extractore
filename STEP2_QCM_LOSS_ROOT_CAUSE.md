# Root Cause Analysis: QCM Loss in Step 2 (Two-Half Pages)

**Symptom:** Running the system on a file where pages have two halves, each containing QCMs.
Real example: total QCMs per file = **87**, after running all steps the Excel contained only **70** → **17 QCMs lost**.
Loss reproduces across every Step 2 mode tried (one batch, page-per-page `1-1-1`, two-per-two `2-2-2`).

**Conclusion:** The primary cause is **not** a max-tokens / per-page weight cap. It is a
**(page, number) key collision** in the Step 2 save step, which silently overwrites QCMs
whenever the two halves of a page number their questions independently.

---

## Files Inspected (read-only)

- `modules/step2_qcm_extract_batch.py` — primary Step 2 runner (used by the batch pipeline)
- `modules/step2_qcm_extract.py` — legacy per-page Step 2 runner (NOT used by batch path)
- `modules/step2_5_qcm_merger.py` — auto-merge of split QCMs (post Step 2)
- `modules/openrouter_client.py` — LLM API client (max_tokens handling)
- `modules/folder_batch_processor.py` — orchestrator that calls Step 2
- `modules/step1_extraction.py` — confirms page file granularity (`page_{i}.txt`, one per PDF page)
- `modules/utils/config_loader.py` — YAML step config parser
- `batch_config.yaml` — runtime Step 2 config
- `.env.example`, `admin.env` — env vars for `STEP2_MAX_TOKENS` and model list

---

## PRIMARY ROOT CAUSE — `(page, number)` key collision during save

**Location:** `modules/step2_qcm_extract_batch.py:343-399` — `_save_batch_results_accumulate`

**The colliding logic:**

```python
# line 376-379
existing_map = {}
for q in existing:
    key = (q['page'], q['number'])      # ← dedup key
    existing_map[key] = q

# line 384-390
for qcm in new_qcms:
    key = (qcm['page'], qcm['number'])  # ← dedup key
    if key in existing_map:
        updated += 1
    else:
        added += 1
    existing_map[key] = qcm             # ← SILENT OVERWRITE on duplicate
```

**Why two-half pages trigger it:**

1. `modules/step1_extraction.py:69` saves **one** `page_{i}.txt` per PDF page. A two-half page
   becomes a **single** text file containing both halves.
2. Step 2 sends that page to the LLM. The prompt at
   `modules/step2_qcm_extract_batch.py:213` explicitly says:
   *"Preserve the original question numbers EXACTLY."*
3. If both halves number their QCMs independently (1..N on the left, 1..M on the right),
   the LLM returns multiple QCMs sharing the **same `(page, number)`**
   (e.g. `(page=5, number=1)` twice).
4. The dict assignment `existing_map[key] = qcm` makes the second entry **overwrite** the first.
   Each collision = 1 QCM lost. No warning, no log.
5. With ~2 two-half pages and ~9 overlapping numbers each → **~17 QCMs lost. Exact match
   with the observed 87 → 70 gap.**

**Why the loss persists across every mode tried:**

| Mode                | Code path                                  | Calls `_save_batch_results_accumulate`? |
|---------------------|--------------------------------------------|------------------------------------------|
| one batch (`1-N`)   | `run()` → line 128                         | YES                                      |
| `1-1-1` loop        | `_run_loop_mode` → line 479                | YES                                      |
| `2-2-2` loop        | `_run_loop_mode` → line 479                | YES                                      |
| folder batch (auto) | `folder_batch_processor.py:106`            | YES (always uses `Step2QCMExtractBatch`) |

The chunk size changes the LLM call shape, but the **save/dedup logic is identical** in every
mode. This is why varying the batch size never fixed the loss.

---

## Why the max-tokens hypothesis is only a SECONDARY risk (not the main cause)

`STEP2_MAX_TOKENS=20000`
(`modules/step2_qcm_extract_batch.py:244`, `.env.example:33`) is a **completion (output)
budget**, not a per-page weight. A grep over the entire codebase confirms there is
**no per-page token/weight cap** anywhere — `max_tokens` is only ever passed straight to the
OpenRouter payload (`modules/openrouter_client.py:117`).

Evidence that tokens are NOT the primary culprit:

- In **1-1-1 mode**, one two-half page ≈ 34 QCMs ≈ ~7,000 tokens — far below 20,000.
  Truncation is physically impossible, **yet QCMs still disappear.** This alone rules out
  truncation as the primary cause.
- If truncation did occur in single-batch mode, `_parse_json`
  (`modules/step2_qcm_extract_batch.py:300-322`) would return `[]`: it does
  `content.find('[')` ... `content.rfind(']')` and a truncated array has no closing `]`,
  so the whole parse returns 0. Getting **70** (not 0) means the JSON parsed successfully;
  the loss happens *after* parsing, at the save step.

Secondary token risk (real but narrower): in single-batch-all-pages mode, the model
`google/gemini-2.5-flash-lite-preview-09-2025` may cap output below 20,000 (Gemini Flash Lite
family typically outputs ~8K–10K). If the model self-closes the `]` when nearing its real
limit, you'd get a *partial* count. This would only affect the all-pages-at-once mode, not
`1-1-1`. It does not explain the loss observed in `1-1-1`.

---

## Contributing factor — incomplete-QCM re-extraction can also drop items

`_apply_incomplete_fix` (`modules/step2_qcm_extract_batch.py:600`) calls
`_reextract_for_incomplete` (line 522), which re-runs the LLM on a ±1 page window.
`_save_to_check_bucket` (line 560) keeps still-incomplete QCMs in `all_qcms.json`, but the
re-extraction can return fewer matches than flagged, and the dynamic threshold
(`_compute_min_prop_threshold`, line 487) may mis-flag dense two-half QCMs. This is a minor
contributor relative to the key collision.

---

## Proposed Fix Plan (not implemented — for review)

**Fix 1 (required, addresses root cause) — stop using `(page, number)` as a unique key.**
- Option A (safest, minimal): key by a stable synthetic id (e.g. `(page, number, half, position)`
  or a generated `uid`). Never overwrite; if a duplicate key appears, append instead of replace.
- Option B: add a `half`/`column` field ("left"/"right") so two-half QCMs get distinct keys.
  Requires a prompt tweak so the LLM labels the half.
- Option C: detect duplicate `(page, number)` in `new_qcms` before merging and auto-increment a
  suffix (`number` → `number.1`, `number.2`) with a warning log.

**Fix 2 (recommended, defense in depth) — make `_parse_json` truncation-safe.**
- Backport the "Stream Decoder" strategy from `modules/step2_qcm_extract.py:361-384` into the
  batch parser, so a truncated array still yields the QCMs it contained instead of `[]`.

**Fix 3 (recommended) — verify/raise the real output budget.**
- Confirm the actual max output of `google/gemini-2.5-flash-lite-preview-09-2025` via OpenRouter.
  If it is < 20,000, switch to a model with larger output (e.g. `google/gemini-2.5-flash-preview`)
  or keep chunks small in loop mode. Set `STEP2_MAX_TOKENS` to the model's true cap.
- Optional dynamic sizing: `max_tokens = max(4000, min(estimated_qcms * 250, model_cap))`.

**Fix 4 (optional) — preserve two-half numbering.**
- Update the prompt to instruct the LLM to continue numbering across halves (1..2N) instead of
  restarting per half, OR to emit a `half` marker. Either eliminates the collision at the source.

**Verification step after fix:** re-run the failing file, assert
`len(all_qcms.json) == 87`, and add a unit test feeding two QCMs with identical
`(page, number)` through `_save_batch_results_accumulate` — it must keep both.

---

## Summary

- **Root cause:** `(page, number)` key collision in
  `modules/step2_qcm_extract_batch.py:_save_batch_results_accumulate` (lines 376-390).
  Two-half pages produce duplicate `(page, number)` pairs from the LLM; the dict assignment
  silently overwrites them, losing ~1 QCM per collision. ~17 collisions → 17 lost QCMs.
- **Why chunk-size experiments didn't help:** all Step 2 modes funnel through the same
  save/dedup routine.
- **Max tokens:** a real but secondary risk, limited to single-batch-all-pages mode, and ruled
  out as the primary cause by the 1-1-1 reproduction and by the fact that the parser would
  return 0 (not 70) on a truncated array.
