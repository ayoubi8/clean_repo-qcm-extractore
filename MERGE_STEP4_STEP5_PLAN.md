# Plan — Merge Step 4 & Step 5 Into an Automatic Post-Step-3 Backend Operation

> Goal: Turn the currently manual, visible **Step 4 (Format/Template)** and **Step 5 (JSON Merge/Build)** into a single, invisible backend operation that fires automatically right after **Step 3** completes. The auto-build must use the **Template.xlsx** default schema (all fields included), so the output matches what a user would get today if they selected "all Fields to Include" in the Step 4 UI.

---

## 1. Current Roles of Step 4 & Step 5

### Step 4 — `modules/step4_format.py` → `Step4Format`

File: `modules/step4_format.py:12`

- **Pure deterministic, zero LLM call, zero `input()` in API auto mode** (`api/real_api.py:1407` `_run_step4_auto`).
- Builds a **template skeleton** — a dict with the *keys* the final output will have, populated with placeholder values (`"Question text here..."`, A–E default choices, etc.).
- Saves the skeleton to:
  - `output/step4_format/templates/{name}.json` (via `TemplateLibrary`)
  - `output/step4_format/current_template.json` (the file Step 5 reads)
- Frontend (`Step4Config.tsx`) only picks `name` + toggles 10 checkboxes (`Num, Text, Propositions, Correct, Year, Category, Subcategory, Source, Tag, ClinicalCase`) and writes the same skeleton via the backend.
- Default frontend preset (`pipelineStore.ts:78`): `name="pediat"` with `Subcategory / Source / ClinicalCase = false`. This is **NOT** the Template.xlsx default.

### Step 5 — `modules/step5_builder.py` → `Step5Builder`

File: `modules/step5_builder.py:13`

- **Pure deterministic, zero LLM call**.
- Reads `step4_format/current_template.json` + `step3_metadata/accepted/*.json`.
- `_map_to_template()` (`modules/step5_builder.py:85`) maps each QCM's fields onto the template keys using `field_map` + propositions fallback + Cas auto-propagation.
- Writes:
  - `step5_json/merged_qcms.json`
  - `step5_json/merged_qcms_{timestamp}.xlsx` (via `export_qcms_to_xlsx`)
- Frontend has no config for it (`ConfigPanel.tsx:23` maps step 5 to `StepRunOnly`).

### Key insight — `Template.xlsx` (repo root file)

Its columns go **beyond** what `Step4Config` exposes today:

```
Num, Cas, Text, A, B, C, D, E, Correct, Exp, categoryName, tagSuggere, subcategoryName, Year, Tag, Type
```

To honor *"let Step 4 work on defaults like Template.xlsx as if all Fields to Include were selected"*, the auto-skeleton must include the extra keys **`Exp`, `tagSuggere`, `Type`** too — not just the 10 toggles Step 4 currently offers.

### Conclusion

Both steps are deterministic and only depend on Step 3 outputs + a fixed skeleton. They are perfect candidates for an invisible post-Step-3 backend operation. The existing `implementation_plan.md` only covers the Step 8 restore fix — **it does NOT already merge 4 & 5**. We need a new, dedicated plan.

---

## 2. Plan

### A. Backend changes

#### A1. New module `modules/post_step3_build.py` (~80 lines, one new file)

A single entrypoint:

```python
def run_post_step3_build(tracker, context, output_user_id, output_project) -> dict:
```

Behavior:

1. Build the **Template.xlsx default skeleton** (`DEFAULT_TEMPLATE_XLSX` dict constant) with ALL keys present in `Template.xlsx`:
   ```
   Num, Cas, Text, A, B, C, D, E, Correct, Exp, categoryName, tagSuggere, subcategoryName, Year, Tag, Type
   ```
   This is the "all fields selected" preset.
2. Save it via `TemplateLibrary().save_template("Default-Template-xlsx", tmpl)` (idempotent — overwrites same name).
3. Write it to `{context.get_path("step4_format")}/current_template.json` (same path Step 5 reads today).
4. Call `Step5Builder(tracker, context).run()` — produces `merged_qcms.json` + the timestamped `.xlsx`.
5. Return `{"step4": {"template": tmpl}, "step5": s5_result}` for logging.

No `input()` patching, no LLM client, no env overrides.

#### A2. `api/real_api.py` — invoke after Step 3 succeeds

In `_run_step_task` (around the `finally` block, `api/real_api.py:1215`), add a guarded cascade:

```python
if step_succeeded and step_id == "3":
    try:
        from modules.post_step3_build import run_post_step3_build
        res = run_post_step3_build(tracker, context, user_id, project)
        log_callback({"ts": ..., "type": "ok", "text":
            f"⚡ Auto-build (Step 4→5) done: {res['step5'].get('total_qcms',0)} QCMs merged."})
        # Mirror badge statuses so polling clients see them as done
        job_manager.set_done(project, "4")
        job_manager.set_done(project, "5")
    except Exception as e:
        log_callback({"ts": ..., "type": "warn", "text":
            f"⚠️ Auto-build (Step 4→5) failed: {e}. You can run Steps 4/5 manually."})
```

In `_do_post_step`'s upload block: if `step_id == "3"`, also upload `step4_format/` and `step5_json/` folders (currently only `folder_name` for the step being run is uploaded). Reuse `_upload_step_folder_to_storage` for both.

#### A3. `_autorun_task` (line 2053) — drop "4" and "5" from the visible sequence

```python
sequence = ["1", "1.5", "1.6", "2", "3", "6", "7", "8"]   # drop "4", "5"
```

Step 3's task internally fires the auto-build, so the autorun chain keeps continuity (Step 6 reads `step5_json/merged_qcms.json` as before).

#### A4. Status contract for steps "4" and "5"

Keep `get_step_status` unchanged. `_check_step_done_in_storage` already returns `done` once Supabase contains those folders. After A2 we **also** `set_done` in memory, so polling during the same session sees them.

#### A5. Keep manual endpoints alive

`POST /projects/{name}/steps/4/run` and `/5/run` remain functional for advanced users / debug. No code deletion; just no UI trigger. Keeps `tests/test_step4.py` and `tests/test_step5.py` green.

#### A6. `folder_batch_processor.py:120-125`

Leave as-is (still calls `Step4Format` + `Step5Builder` directly). Optionally switch it to `run_post_step3_build` to guarantee one code path; recommended refactor.

#### A7. Tests — add `tests/test_post_step3_build.py`

- Given a fake `step3_metadata/accepted/{n}.json` and a `ProjectContext`, run `run_post_step3_build` and assert `step5_json/merged_qcms.json` exists, contains N items, and the template used == `DEFAULT_TEMPLATE_XLSX` (assert keys include `Exp`, `tagSuggere`, `Type`).
- Failure path: no accepted QCMs → returns gracefully with a `no_qcms` flag, does NOT crash the Step 3 success path.

---

### B. Frontend changes

#### B1. `frontend/src/store/pipelineStore.ts`

- Remove steps 4 and 5 from `INITIAL_STEPS` (lines 36–38).
- Remove `step4Config` state, `setStep4Config`, and the `partialize` entry.
- Bump the persisted version key (`qcm-pipeline-store-v2`) so old localStorage doesn't resurrect the removed config.

#### B2. `frontend/src/types/index.ts`

- Drop `4` and `5` from `StepId`.
- Delete `Step4Fields` and `Step4Config` interfaces.
- Remove `step4?` from `AutoRunPayload.run_config`.

#### B3. `frontend/src/components/pipeline/ConfigPanel.tsx`

- Remove entries `'4'` and `'5'` from `CONFIG_MAP` (lines 22, 24).
- Delete the `import` of `Step4Config`.
- In `handleRun`, remove the `step.id === 4` branch (line 137).

#### B4. `frontend/src/components/pipeline/StepList.tsx`

- After Step 3 completes, the existing auto-trigger pattern (used today for `1 → 1.5`, line 86) should **not** fire any visible run for 4/5 — they don't exist anymore.
- The "⚡ Auto-build (Step 4→5) completed" log line comes from the backend WS stream (A2) — no extra frontend logic needed.
- Optional: after Step 3 done, silently call `getStepStatus(project, 4)` and `/5` and discard (or use them to refresh the project card's `last_step`).

#### B5. `frontend/src/components/autorun/StepRangeSelector.tsx`

- `options` array currently derives from `1..8`; drop 4 and 5:
  ```ts
  const allowed = [1, 2, 3, 6, 7, 8]
  const options = Array
    .from({ length: 8 }, (_, i) => i + 1)
    .filter(n => allowed.includes(n) && n >= min && n <= max)
  ```
- So users can only pick `{1, 2, 3, 6, 7, 8}`.

#### B6. `frontend/src/components/autorun/AutoRunPanel.tsx` & `YamlConfigSection.tsx`

- Remove any `step4` field block in the YAML/interactive config builder.
- The `runConfig` sent to `/autorun` no longer includes `step4`.

#### B7. Delete `frontend/src/components/pipeline/configs/Step4Config.tsx`

---

### C. API contract changes

#### C1. `POST /projects/{name}/steps/3/run`

- Response unchanged (still just `{job_id}`).
- The WS log stream now emits the auto-build "ok" line + (if it fails) a "warn" line.
- Document in the endpoint's OpenAPI summary: *"Step 3 success auto-triggers Steps 4→5 in the backend."*

#### C2. `POST /projects/{name}/steps/4/run` and `/5/run`

- Keep them, but mark them Deprecated (`deprecated=True` on the route, or add a note in summary).
- Remain functional for manual override.

#### C3. `POST /projects/{name}/autorun`

- `active_sequence` no longer contains `"4"` or `"5"`.
- If a client sends `run_config.step4` or `step5`, the backend silently ignores them (already the case since they aren't in `sequence`).

#### C4. `GET /projects/{name}/steps/4|5/status`

- Unchanged. After a successful Step 3, both return `{status: "done", output_exists: true}` (via A2's `set_done` + Supabase storage check). Useful for any monitoring client.

#### C5. `GET /projects` (`project_manager.py` STEP_ORDER`, line 133)

- Unchanged. `last_step` correctly becomes `5` after Step 3 auto-build because the auto-build writes `step5_json/`. No DB schema change needed.

---

## 3. Verification checklist (proves "it does it correctly")

1. **Unit** — new `test_post_step3_build.py` asserts:
   - Skeleton keys == Template.xlsx columns incl. `Exp`, `tagSuggere`, `Type`.
   - Produces `merged_qcms.json` with N items.
   - Idempotent on re-run.
2. **Integration** — upload a small PDF, run Step 1→2→3 via API; assert `GET /steps/4/status` and `/steps/5/status` both return `done` afterward, and `step5_json/merged_qcms.json` exists in Supabase storage under `{user}/{project}/step5_json/`.
3. **Failure isolation** — force Step 3 to error (e.g. empty PDF); assert Steps 4/5 are NOT marked done and no `step5_json` folder is created.
4. **Autorun** — `POST /autorun` with `start_step=1, end_step=6`; assert sequence executes `1, 1.5, 1.6, 2, 3, 6` and that `step5_json/merged_qcms.json` is produced by the auto-build fired at end of step 3 (before step 6 starts).
5. **Frontend smoke** — after refactor, the pipeline sidebar shows steps `{1, 1.5(auto), 1.6, 2, 3, 6, 7, 8}`; Step 3 row turns green and a log line "⚡ Auto-build (Step 4→5) completed" appears; Step 6 can be run next and finds Step 5's `merged_qcms.json`.
6. **Regression** — `tests/test_step4.py`, `tests/test_step5.py`, `tests/test_step6.py` still pass (modules themselves are untouched).

---

## 4. Data flow after the change

```
Step 1 (OCR)        ─▶ step1_extraction/
Step 1.5 (Fixer)    ─▶ step1_extraction/     [auto after Step 1]
Step 1.6 (OCR Corr) ─▶ step1_extraction/
Step 2 (QCM Extract)─▶ step2_qcm/
Step 3 (Metadata)  ─▶ step3_metadata/accepted/
        │
        └─▶ [NEW] run_post_step3_build()    ◀── invisible backend step
                │
                ├─▶ step4_format/current_template.json   (Template.xlsx-all-fields skeleton)
                └─▶ step5_json/merged_qcms.json + merged_qcms_*.xlsx
Step 6 (Corrections) ─▶ step6_corrections/   (reads step5_json/)
Step 7 (Categorization) ─▶ step7_categories/
Step 8 (Similarity Match) ─▶ step8_matches/  (reads step7 > step6 > step5)
```

---

## 5. Risks & mitigations

| Risk | Mitigation |
|------|------------|
| Existing user `localStorage` has `step4Config` | Bump the store version key (`qcm-pipeline-store-v2`) in B1 |
| A project mid-pipeline (Step 3 already done, Step 4 not run) | Manual `POST /steps/4/run` still works (A5). No backfill script needed |
| Step 6 re-runs Step5Builder internally (`folder_batch_processor.py:144`) | Same module, behavior identical; auto-build just changes *who* calls Step 5 first |
| Auto-build fires even when Step 3 produced 0 accepted QCMs | `run_post_step3_build` checks `accepted/*.json` count and returns `{status: "no_qcms"}` without crashing Step 3's success path |
| Log noise — extra "ok" line after every Step 3 | Single concise line; consistent with existing Step 1.5 auto-trigger message style |

---

## 6. Summary

This plan:

- Makes **Step 4 + Step 5 a single invisible backend operation** triggered after Step 3.
- Uses the **Template.xlsx all-fields skeleton** (`Exp`, `tagSuggere`, `Type` included) as requested.
- **Removes Steps 4 & 5 from the frontend** (sidebar, autorun picker, config panel, types, store) while keeping **backward-compatible manual endpoints** for advanced/debug use.
- Keeps the data flow backwards-compatible: Step 6/7/8 keep reading the same `step5_json/merged_qcms.json` they always did.
- Adds targeted tests and a verification checklist.