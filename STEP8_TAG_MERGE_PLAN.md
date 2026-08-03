# Step 8 — Tag Merge & Auto-Dedup Implementation Plan

> Status: **PLAN ONLY — do not edit code yet.**
> Scope: extend the existing website Step 8 (matcher + report) so that, after matching the project's QCMs against the reference DB, the backend **merges tags of high-similarity duplicates**, **deletes the duplicate rows from the reference DB**, and **emits 4 new artifacts** in addition to the existing color-coded report.
>
> Source scripts that inspire this work live in `step 8 new logic/match_qcm.py` + `step 8 new logic/dedup_99plus.py`. They are **reference prototypes**, not the files we edit. All real edits go to `modules/step8_matcher.py`, `api/real_api.py`, `frontend/src/...`.
>
> This plan is layered **frontend / backend / API** so each tier can be reviewed and merged independently.

---

## 0. Locked decisions (answers to the 5 questions)

| # | Question | Locked answer |
|---|---|---|
| Q1 | Where does the merge/delete happen? | **No live mutation of the uploaded reference DB.** The backend produces a downloadable **`<ref_name>_UPDATED.xlsx`** (reference DB with merged tags + duplicate rows removed) plus a **`merge_report.json`** and an **`unmerged_qcms.xlsx`**. The original uploaded reference DB in Supabase Storage is left untouched. |
| Q2 | Auto-approve 99–100% or confirm? | **Auto-merge from a configurable floor up to 100%.** Default floor = **97%** (i.e. 97–100% auto-merged with no click). The user can drag that floor down to 95% or up to 99% in the UI. Anything **strictly below** the floor is **never** auto-merged — it stays in `unmerged_qcms.xlsx` for manual review. |
| Q3 | Self-scan as a separate mode? | **Yes, inline toggle.** When the user **selects a reference DB** in Step8Config, a small **"Self-scan"** checkbox appears **above the Run button** (in the StepRunOnly panel). Default = **off**. When on, Step 8 runs the reference DB **against itself** (skipping self-row matches) to find internal duplicates. There is no `source_qcms` in self-scan — the reference DB is also the source. |
| Q4 | Keep the existing match report? | **Yes.** The current `step8_matches.xlsx` color-coded report is kept **as-is** (same columns, same 🟢/🟡/🔴 colors, same Legend sheet). The new merge outputs are **additional** artifacts in the same `step8_matches/` output folder. |
| Q5 | Merge threshold configurable? | **Yes.** New `auto_merge_floor` slider (default 0.97, range 0.50–0.99) is added to Step8Config, alongside the existing `threshold` match-similarity cutoff. Auto-merge only fires for pairs with `similarity >= auto_merge_floor`. |

---

## 1. Output artifacts (what the user downloads after Step 8)

All written to `output/<project>/step8_matches/` and uploaded to Supabase Storage under `<user>/<project>/step8_matches/`.

| # | File | Purpose | When produced |
|---|---|---|---|
| A | `step8_matches.xlsx` | **Unchanged** color-coded match report (current behavior) | Always |
| B | `step8_matches.json` | **Unchanged** full match records (current behavior) | Always |
| C | `step8_summary.json` | **Unchanged** summary (current behavior) | Always |
| **D** | **`merge_report.json`** | Per-merge audit: `{ ref_qcm, source_qcm, similarity, old_tag_ref, old_tag_src, new_tag, tier }` | When ≥1 pair `>= auto_merge_floor` |
| **E** | **`<ref_name>_UPDATED.xlsx`** | Reference DB **after** tag merges + duplicate-row deletions (downloadable, **not** pushed back to Storage) | Same as D |
| **F** | **`unmerged_qcms.xlsx`** | QCMs from the project's Step 6/5 output whose tags were **not** merged (i.e. their best-match similarity `< auto_merge_floor` — these are the user's new QCMs to keep) | Always, post-run |

> Self-scan mode produces D + E only (F would be empty/identical, so it is skipped).
> If `auto_merge_floor` produces **zero** merges, D and E are still emitted (D = `[]` / empty-report shape, E = byte-identical copy of the input reference DB) so downstream UI never 404s.

### `merge_report.json` shape

```json
{
  "auto_merge_floor": 0.97,
  "self_scan": false,
  "ref_db_name": "modules-bio-chir-med.xlsx",
  "source_step": "Step 6 (Corrected)",
  "total_pairs_considered": 412,
  "total_merges": 17,
  "total_deletions": 17,
  "per_tier_stats": {
    "100": {"merges": 4,  "deletions": 4},
    "99":  {"merges": 6,  "deletions": 6},
    "98":  {"merges": 3,  "deletions": 3},
    "95_97":{"merges": 4, "deletions": 4}
  },
  "merges": [
    {
      "ref_qcm":      { "ref_index": 12, "Num": "...", "Text": "...", "Tag": ["Alger","2024"] },
      "source_qcm":   { "source_index": 47, "source_step": "Step 6 (Corrected)",
                        "Num": "...", "Text": "...", "Tag": ["Oran"], "Year": 2025 },
      "similarity":   0.985,
      "tier":         "99",
      "old_tag_ref":  ["Alger","2024"],
      "old_tag_src":  ["Oran"],
      "new_tag":      ["Alger","2024","Oran","2025"]
    }
  ]
}
```

### `unmerged_qcms.xlsx` shape

Same columns as the project's source QCM JSON (Num, Text, A–E, Correct, Year, categoryName, subcategoryName, Tag, Source). One row per source QCM whose best-match similarity `< auto_merge_floor`. This is the file the user reviews/imports manually — it's effectively "the new QCMs Step 6/5 produced that we did NOT merge into the reference DB".

---

## 2. Backend changes — `modules/step8_matcher.py`

### 2.1 New `__init__` config fields

```python
self.auto_merge_floor = float(os.getenv("MATCH_AUTO_MERGE_FLOOR", "0.97"))  # NEW
self.self_scan        = False                                              # NEW (set per-run)
```

### 2.2 `run()` additions

After the existing `_save_xlsx_report` / `_save_summary` / `_offer_custom_export` block, **append** a new phase:

```python
# 7. Tag merge + dedup (NEW)
self._produce_merge_outputs(match_records, ref_qcms, source_qcms, output_dir, ref_path)
```

Remove the interactive `input()`-based tiered prompt that the prototype uses (`process_tiered_merges_and_deletions` in `match_qcm.py`); the website is non-interactive (the API `input()` patch already returns `""` for any prompt). Instead:

### 2.3 New method: `_produce_merge_outputs(...)`

Logic:

1. Determine `is_self_scan = self.self_scan`.
2. Build a list of eligible merge pairs from `match_records`:
   - Skip pairs where `best_match.similarity < self.auto_merge_floor`.
   - For self-scan: skip pairs where `ref_index == source_index` (same row).
   - Skip pairs whose ref row has **already been merged into** in this run (a ref row may absorb multiple source QCMs' tags, but a source row that was itself used as a ref absorber is locked out — first-come-first-served by descending similarity).
3. Group pairs into tiers using the same thresholds as the prototype:
   - `100`: `sim >= 0.9999`
   - `99`:  `0.9899 <= sim < 0.9999`
   - `98`:  `0.9799 <= sim < 0.9899`
   - `95_97`: `self.auto_merge_floor <= sim < 0.9799` (only if floor < 0.98)
4. **Auto-apply all merges** (no user prompt — the floor IS the approval gate). For each merge:
   - Combine `ref.Tag` + `source.Tag` + `source.Year` (if missing from ref.Tag) via `merge_tags(...)` (reuse the helper from the prototype).
   - Format merged tag list as JSON string for the Tag cell.
   - Record `ref_index` in a `deleted_ref_indices` set (the duplicate row to remove from `<ref>_UPDATED.xlsx`).
   - Append a structured entry to `merge_report["merges"]`.
5. Produce **`<ref_name>_UPDATED.xlsx`**:
   - Load the original reference DB into a pandas DataFrame (already available — reuse `_load_reference_db` result converted to DataFrame).
   - Apply the merged tags to surviving ref rows.
   - Drop `deleted_ref_indices` rows.
   - Save with openpyxl. Filename = `Path(ref_path).stem + "_UPDATED.xlsx"`.
6. Produce **`unmerged_qcms.xlsx`**:
   - Filter `source_qcms` for those whose best-match `< auto_merge_floor` (or whose all source rows in self-scan were absorbers, not duplicates).
   - Save as XLSX using the same column layout + color helpers as `_save_custom_xlsx` (grey fill for "not merged").
7. Emit **`merge_report.json`**.
8. Update `step8_summary.json` to add a `"merge"` block with totals + tier stats so the frontend dashboard can show a one-line result without parsing the full report.
9. Return dict gains `merge_report_path`, `ref_updated_path`, `unmerged_path`.

### 2.4 Self-scan branch

When `self.self_scan == True`:

- `source_qcms` = `ref_qcms` (the same list).
- The matching loop already supports `is_self_scan` filtering in the prototype worker; **import** that filter (one-line `match_idx == i` skip) into `_match_chunk_worker` and `_match_chunk_worker_weighted`. Add a new `is_self_scan` parameter threaded via the chunk args.
- Output only `step8_matches.xlsx`, `step8_matches.json`, `step8_summary.json`, `merge_report.json`, `<ref>_UPDATED.xlsx`. Skip `unmerged_qcms.xlsx`.
- In the report, source labels read "Self-scan (ref DB vs itself)".

### 2.5 No candidate limit (alignment with prototype)

The prototype keeps **all** matches above threshold (limit=None) while the current `_match_chunk_worker` uses `limit=5`. **Keep `limit=5`** for `step8_matches.xlsx`/`.json` (display top-5 per QCM, unchanged UI behavior) but add a **separate** full-list pass internally for merge-pair collection:

> Decision: do **not** bump the displayed top-5. The merge logic only ever needs the **best** match per source QCM, which we already have. No second pass needed.

### 2.6 Tag-merge helpers (lift from prototype)

Copy verbatim from `step 8 new logic/match_qcm.py` lines 179–213 → `modules/step8_matcher.py`:

- `parse_tag_list(tag_value)`
- `merge_tags(*tag_values)`
- `format_tag_list(tags)`

These are pure functions; safe to reuse. Tag detection reuses `tag_col = "Tag" if "Tag" in df.columns else "tag" if "tag" in df.columns else None` (matches both DB schemas).

---

## 3. API changes — `api/real_api.py`

### 3.1 New Step 8 config keys accepted by `/projects/{name}/steps/8/run`

Add to the Step 8 env-override block (~line 1556–1575):

```python
if config.get("auto_merge_floor") is not None:
    os.environ["MATCH_AUTO_MERGE_FLOOR"] = str(config["auto_merge_floor"])
if config.get("self_scan") is not None:
    # stored on the matcher instance, not env — but env works as a string flag
    os.environ["MATCH_SELF_SCAN"] = "1" if config["self_scan"] else "0"
```

### 3.2 Pass `self_scan` into the matcher

The `step_map["8"]` lambda currently is `lambda: Step8Matcher(tracker, context).run()`. Change to:

```python
"8": lambda: self._run_step8(tracker, context, config),
```

with a helper:

```python
def _run_step8(tracker, context, config):
    m = Step8Matcher(tracker, context)
    m.self_scan = bool(config.get("self_scan", False))
    if config.get("auto_merge_floor") is not None:
        m.auto_merge_floor = float(config["auto_merge_floor"])
    return m.run()
```

### 3.3 New download endpoint

Add `GET /projects/{name}/step8/merge-outputs` returning a JSON manifest:

```json
{
  "ref_updated":   { "filename": "modules-bio-chir-med_UPDATED.xlsx", "size_bytes": 12345, "url": "<signed supabase url or /files/...>" },
  "merge_report":   { "filename": "merge_report.json", ... },
  "unmerged":       { "filename": "unmerged_qcms.xlsx", ... },
  "summary":        { "filename": "step8_summary.json", ... }
}
```

The frontend uses this manifest to render the post-run download cards. The actual bytes come from the existing `/projects/{name}/step/{step}/file` route (Step 8 is already wired for this via STEP_FOLDER_MAP `"8": "step8_matches"`).

### 4.4 Step folder map unchanged

`STEP_FOLDER_MAP["8"] = "step8_matches"` already covers the new files — no need to add a new step folder.

### 3.5 `input()` auto-patch updates

The `_auto_input` function (lines 1494–1516) skips the prototype-style prompts (`"do you want to merge tags"`, etc.). Add guards so **any** stray prompt from `_produce_merge_outputs` returns `""` — but because we're removing the prototype's `input()` loop entirely, nothing changes here. Just sanity-confirm the new method contains **no** `input()` calls (it must be non-interactive on the server).

---

## 4. Frontend changes — `frontend/src/`

### 4.1 Types — `types/index.ts`

Extend `Step8Config`:

```ts
export interface Step8Config {
  ref_db_path: string
  match_mode: MatchMode
  threshold: number
  text_weight: number
  corr_weight: number
  color_green: number
  color_yellow: number
  export_from: number
  export_to: number
  export_filename: string
  // NEW
  auto_merge_floor: number   // 0.50 – 0.99, default 0.97
  self_scan: boolean         // default false
}
```

### 4.2 Store defaults — `pipelineStore.ts`

`step8Config` initial object (around line 88) gains:

```ts
auto_merge_floor: 0.97,
self_scan: false,
```

Bump the persist `version` constant + add a `migrate()` entry so existing localStorage from earlier sessions fills the two new keys with their defaults (mirror the v3 / v7 pattern already used).

### 4.3 Step8Config panel — `components/pipeline/configs/Step8Config.tsx`

Add **two new UI sections**, both after the "Color Bands" block and before "Custom Export":

**Section "Auto-Merge"** — a slider identical in styling to the existing Threshold slider:

- Label: `"Auto-Merge Floor"`
- Range: 50–99 %, step 1
- Default 97 %
- Helper line: `"QCMs with similarity ≥ this floor are auto-merged into the reference DB. Below = manual review. Default 97 %."`

**Section "Self-Scan"** — a single checkbox row that appears **only when a reference DB is selected** (`config.ref_db_path` is non-empty):

- Label: `☐ Self-scan (check reference DB for internal duplicates)`
- Description line: `"Runs the selected reference DB against itself. Source QCMs are ignored for this run."`
- Toggling on sets `self_scan: true` and **disables** the Custom Export block (it's irrelevant in self-scan).
- Toggling off restores prior behavior.

> The visually-disabled Run button / `StepRunOnly` panel is **not** where the checkbox lives. Per the user's requirement, the small checkbox is rendered **inside** `Step8Config.tsx`, appearing only above the Run button which lives in `StepRunOnly.tsx` — meaning the checkbox sits at the bottom of the config panel, directly above the Run/Custom-Export area.

### 4.4 Run button gating

`ConfigPanel.tsx` already forwards `step8Config` to the run payload (line 146). Add the two new keys to that spread so they reach the backend.

### 4.5 Post-run results display — `components/step8/`

Add new file `components/step8/MergeResultsPanel.tsx` rendered **only after** Step 8 succeeds and `step8_summary.json` contains a `merge` block. It shows:

1. A summary header: **"17 tags merged • 17 duplicates removed • 395 QCMs kept for manual review"** (numbers from the merge block).
2. A 4-row tier table mirroring the prototype's `MERGE & DEDUP STATS` printout.
3. Three download buttons:
   - 📥 `Download <ref>_UPDATED.xlsx` (the new reference DB)
   - 📥 `Download merge_report.json` (audit log)
   - 📥 `Download unmerged_qcms.xlsx` (new QCMs to review)
4. A "View merge report" expandable that pretty-prints `merge_report.json["merges"]` with ref Text ↔ source Text side-by-side and the four tag columns (old_ref, old_src, new, similarity%).

The existing `ExportExistingButton.tsx` (Custom Export trigger) stays. In self-scan mode, hide `merge_report.json`+`unmerged` download buttons, keep only `<ref>_UPDATED.xlsx`.

### 4.6 Files inventory refresh

Wherever the frontend lists files for Step 8's output (OutputViewer / step-files dropdown), the new files must appear automatically because they live in the same `step8_matches/` folder and the backend's `/projects/{name}/steps/8/files` route already lists that folder. No code change expected; verify after implementation.

### 4.7 Progress-bar colors

Per Q4, **no color changes**. The merged `_UPDATED.xlsx` keeps the green/yellow/red fills only in the matched-questions report (`step8_matches.xlsx`); the `_UPDATED.xlsx` itself is plain data (no similarity column = no color band).

---

## 5. Tests — `tests/`

New `tests/test_step8_merge_outputs.py`:

| Test | Asserts |
|---|---|
| `test_no_merges_below_floor` | With `auto_merge_floor=0.99` and best matches at 0.85, `merge_report.json` has `total_merges: 0`, `_UPDATED.xlsx` byte-identical to input, `unmerged_qcms.xlsx` contains all source QCMs. |
| `test_merges_at_default_floor` | A synthetic ref + source with a 98% overlap → 1 merge, 1 deletion, `new_tag` is union of both, `unmerged` excludes that source QCM. |
| `test_tier_grouping` | Mixed similarities (100, 99, 98, 96%) → 4 merges across 4 tiers, `per_tier_stats` matches expected counts. |
| `test_self_scan_filters_selfmatch` | Same DB as source+ref, identical rows are **not** flagged as duplicates. |
| `test_year_added_to_tag` | Source has `Year=2025` not in ref.Tag → after merge, "2025" appended to ref.Tag. |
| `test_first_come_first_served` | Two source QCMs both ≥ floor against the same ref QCM → both merge into the **same** ref row (tags accumulate), and **neither** source row stays in `unmerged`. |
| `test_input_prompts_none` | Assert `_produce_merge_outputs` makes **zero** `input()` calls (so the API auto-input patch is irrelevant). Mock `builtins.input` to raise if ever called. |

Existing Step 8 tests must still pass (the new phase only adds outputs; the existing report is unperturbed).

---

## 6. PR breakdown (suggested merge order)

| PR | Layer | Files | Independently shippable? |
|---|---|---|---|
| **PR-S8-1** | Backend | `modules/step8_matcher.py` + `tests/test_step8_merge_outputs.py`. No UI changes; outputs already appear in the file list. Default `auto_merge_floor=0.97`, `self_scan=False`. Old behavior unchanged when both are at defaults and no mergeable pairs exist. | ✅ Yes |
| **PR-S8-2** | API | `api/real_api.py` (env overrides + `_run_step8` helper + new `/step8/merge-outputs` manifest endpoint). | ✅ Yes (after PR-S8-1) |
| **PR-S8-3** | Frontend types + store + config panel | `types/index.ts`, `pipelineStore.ts`, `Step8Config.tsx`. Adds the floor slider + self-scan checkbox. Not yet visible results. | ✅ Yes (after PR-S8-2) |
| **PR-S8-4** | Frontend results | `components/step8/MergeResultsPanel.tsx` + wiring in OutputViewer / StepRunOnly. Download buttons + tier table + expandable audit. | ✅ Yes (after PR-S8-3) |

---

## 7. Verification checklist (end-to-end on HuggingFace after each PR)

- [ ] PR-S8-1: Run Step 8 against `modules-bio-chir-med.xlsx` reference; check `step8_matches/` folder contains the 3 new files with correct shapes; rerun Step 8 to verify idempotency (running twice does **not** double-merge because `_UPDATED` is downloaded, not re-uploaded to the reference slot).
- [ ] PR-S8-2: `curl /projects/{name}/step8/merge-outputs` returns the 4-entry manifest with non-zero sizes.
- [ ] PR-S8-3: Slider + checkbox render; setting `auto_merge_floor` to 0.50 increases merge count; toggling self-scan swaps the panel heading; old localStorage migrates without errors.
- [ ] PR-S8-4: MergeResultsPanel tier table matches `merge_report.json`; download buttons fetch via the existing file route; "View merge report" expandable shows ref Text ↔ source Text side-by-side.
- [ ] Self-scan: pick `modules-bio-chir-med.xlsx` as both ref and source (via the checkbox); verify internal duplicates are merged into `_UPDATED.xlsx` and no `unmerged_qcms.xlsx` is produced.
- [ ] Color report unchanged: visually compare `step8_matches.xlsx` before/after — same columns, same 🟢/🟡/🔴 bands.

---

## 8. Out of scope / non-goals

- **No live mutation of the uploaded reference DB in Supabase Storage.** The user downloads `_UPDATED.xlsx` and decides whether to re-upload it manually as a new reference DB (this is the safest contract — never auto-replace a shared reference).
- **No tier-by-tier confirmation UI.** The floor replaces the prototype's interactive `y/n` per-tier prompts. If the user later wants a per-tier review panel, that's a separate frontend feature on top of `merge_report.json`.
- **No change to displayed top-5 candidates** in `step8_matches.xlsx`. The merge logic only needs the best match per source, which we already have.
- **No backend autorun sequence change.** Step 8 is already the last entry in `["1","1.5","1.6","2","6","7","8"]`.
- **No edits to `step 8 new logic/*`** (those are reference prototypes, not the live code).
- **No edits to `new-version/**`** (stale snapshot — per SESSION_RESUME §4).