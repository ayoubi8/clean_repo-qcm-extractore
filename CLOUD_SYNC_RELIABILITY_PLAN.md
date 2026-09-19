# Cloud-Sync (Google Sheets ⇄ DB) — full audit + fix plan (IMPLEMENTED)

> Status: all phases below are implemented (P0-P8) and the user decisions in §7
> are applied. Tests: `python tests/test_sheet_edit_sync.py` covers S1-S8
> (S5-S8 = the regression tests for the real sheet shape, deletions, uid
> bridge, and dict-safe merge that were red concepts at audit time).

Scope — the exact user journey this plan must guarantee:

- **R1**: user opens a step's result xlsx in Google Sheets (e.g. Step 2), edits it
  (fix text, delete rows…), comes back to the website → **auto-sync** updates the
  xlsx/JSON stored in the DB (Supabase Storage).
- **R2**: re-opening the file in Sheets **or downloading it** shows the edits.
- **R3**: running the **next steps** builds on the edited version (edits AND deletions).
- **R4**: row **deletions** in the sheet must propagate everywhere (today they don't — worst bug).

---

## 1. Current system inventory (verified in code)

| Piece | Where | What it does |
|---|---|---|
| "Open in Google Sheets" button | `frontend/src/components/pipeline/OutputViewer.tsx:435-471` → `POST /projects/{name}/steps/{step_id}/open-sheets` | Uploads the xlsx to Drive as a new Google Sheet, remembers `sheet_id` in `_sheets_meta.json` (only for steps 2 & 6, `real_api.py:3278-3294`). **Creates a NEW Sheet every click** (`real_api.py:3264-3275`). |
| Auto-sync on tab return | `OutputViewer.tsx:50-83` (`visibilitychange`) | Fires `sync-from-sheets` when the browser tab becomes visible again, only if a sheet was opened this session (`hasOpenedSheetRef`) and this step's OutputViewer is mounted. |
| Manual `cloud_sync` button | `OutputViewer.tsx:486-498` (icon `cloud_sync`, steps 2 & 6, xlsx only) | Same endpoint, manual fallback. |
| Sync endpoint | `POST /projects/{name}/steps/{step_id}/sync-from-sheets` — `real_api.py:3327-3576` | Reads the Google Sheet → rows→dicts via header (all values **strings**) → **full-overwrite** of the step's canonical JSON (local + Storage) → regenerates the xlsx → propagates to sibling step JSON (field merge) → propagates to the Step 2→3→5 build chain (field merge). |
| Step config | `_SYNC_STEP_CONFIG` (`real_api.py:3309-3324`) | Step 2 → canonical `step2_qcm/accepted/all_qcms.json`, xlsx kind `qcms`, sibling 6. Step 6 → canonical `step6_corrections/corrected_qcms.json`, xlsx kind `corrections`, sibling 2. |
| Merge helpers | `modules/utils/qcm_merge.py` | `qcm_key` (uid\|Num\|number), `merge_qcm_fields` (empty-never-overwrites, list/dict protected via `ast.literal_eval`), `propagate_sheet_edits` (merges into step5 `merged_qcms.json`, step2 `accepted/merged_qcms.json` mirror, `step3_metadata/accepted/*.json`). **Merge-only — no deletion support.** |
| Step 6 re-run keeps edits | `modules/step6_corrections.py:117-184` (Phase 1) | Re-applies ALL fields from previous `corrected_qcms.json` onto the loaded step5 QCMs (so synced edits survive re-runs); `force_overwrite` clears only `Correct`. |
| Stable workbook names | `modules/utils/output_naming.py:28-33` | `{count}_qcms_{pdf_stem}.xlsx` / `{count}_corrections_{pdf_stem}.xlsx` — name embeds the row/corrected count. |
| Which xlsx the user opens for Step 2 | copy of the Step-5 workbook made by the cascade (`modules/post_step2_metadata.py:371-375`) into `step2_qcm/accepted/` | Columns = Template.json schema (`Num, Cas, Text, A-E, Hint, Correct, Exp, categoryName, tagSuggere, Year, Tag, Type`) — **no `uid`, no `page`, no `propositions` dict**. |
| Tests | `tests/test_sheet_edit_sync.py` (S1-S4) | Cover merge safety + chain propagation — but with a **uid-keyed "step-2 sheet row" fixture that the real sheet cannot produce** (see F3). |

Data flow today:

```
Google Sheet (Num-keyed string rows)
   └─ sync_from_sheets
       ├─ canonical JSON        ← FULL OVERWRITE (deletions DO apply here only)
       ├─ regenerated xlsx      ← reflects sheet (new filename when count changes)
       ├─ sibling JSON           ← field-merge only (no deletions; key mismatch half the time)
       └─ build chain:
           ├─ step5_json/merged_qcms.json      ← field-merge only
           ├─ step2_qcm/accepted/merged_qcms.json ← field-merge only
           └─ step3_metadata/accepted/*.json  ← SILENT NO-OP (key + field mismatch)
```

---

## 2. What already works (keep as-is)

- Auto-sync trigger on tab-return works when the step's OutputViewer is mounted and
  a sheet was opened this session; manual button covers the rest of that session.
- Canonical JSON + regenerated xlsx of the **edited step itself** reflect the sheet
  (including deletions) — that's why re-opening/downloading the *newest* file looks right.
- `merge_qcm_fields` is sheet-safe: empty cells never wipe data, `Tag` lists survive the
  `"['a','b']"` string round-trip, unparseable dict strings are skipped not written.
- Step 6 re-runs keep sheet edits (Phase 1 full-field merge) — verified by test S3.
- Step-2 sheet **text edits** do reach `step5_json/merged_qcms.json`, the step2 mirror and
  `corrected_qcms.json` (all Num-keyed → keys match).

---

## 3. Findings (each blocks one of R1-R4)

### F1 — Deletions never propagate beyond the edited step's canonical file (R4, critical)
Sync only *overwrites* the canonical JSON (`real_api.py:3453-3455`). Everything else is
merge-only: sibling propagation (`real_api.py:3497-3540`) and
`propagate_sheet_edits` (`qcm_merge.py:90-122,125-168`) never remove rows.
So a row deleted in the Step-2 sheet stays in `step5_json/merged_qcms.json` — and
**Step 6 loads exactly that file** (`step6_corrections.py:104`) → the deleted QCM
resurrects in `corrected_qcms.json`, the Step-6 xlsx, Step 7 (`final_qcms.json`) and
Step 8. The user sees deleted rows come back to life in every next step.

### F2 — Step-2 sync destroys the `all_qcms.json` schema (R3, critical)
The Step-2 workbook has no `uid/page/number/propositions` columns (Template.json),
so the sheet rows are Num-keyed strings. Sync **fully overwrites** the uid-keyed
`all_qcms.json` with them (`real_api.py:3412-3455`). Consequences:
- `_step2_uid_set` finds no uids → Q8 fast-path never matches → Step 3 always re-runs
  (`post_step2_metadata.py:76-131`).
- A Step-2 re-run merges into the corrupted file: `_sanitize_qcms` stamps
  `page=0/number=0` and assigns junk uids `0_0_i` (`step2_qcm_extract_batch.py:627-665`).
- hint/cas-split/Step-3 scan `step2_qcm/accepted/*.json` and get Num-keyed rows with
  empty `text` → degraded enrich.
- The raw extraction record (uid/page/propositions) is lost (only `_history` copy remains).

### F3 — Chain propagation to `step3_metadata/accepted/*.json` is a silent no-op (R3, high)
`qcm_key` = `uid|Num|number` (`qcm_merge.py:31-40`). Sheet rows key by `Num` ("1");
step-3 rows key by `uid` ("1_1_0") → no match → nothing merges. Even if keys matched,
field names don't (`Text`/`A`.. vs `text`/`propositions.a`). So the documented promise
"edits survive a Step-2 re-run via step3 accepted" (`qcm_merge.py:125-147`) is not true
for real sheets: a Step-2 re-run rebuilds step5 from *unedited* step3 files →
**the user's sheet edits vanish**. Test S2 passes only because it hand-feeds a
uid-keyed row the real sheet never contains (`test_sheet_edit_sync.py:104-113`).

### F4 — Sibling propagation step6→step2 is also a no-op (medium)
Same key mismatch: `all_qcms.json` rows are uid-keyed, Step-6 sheet rows Num-keyed
(`real_api.py:3497-3540`). Step-6 sheet edits never reach `all_qcms.json`. (The step5
mirror does get them, which is why the system *looks* mostly alive.)

### F5 — Stale-workbook trap (R2, high)
Workbook names embed the count (`output_naming.py:28-33`). Delete rows → count changes →
sync writes a **new** `145_qcms_stem.xlsx` while the old `150_qcms_stem.xlsx` stays in
local FS, Storage and the `step_results.file_manifest`. The file list shows several
near-identical workbooks; re-opening/downloading an old one shows stale data, and
editing that stale sheet then syncing would silently **revert** newer data (the sheet is
the source of truth). Also: `open-sheets` creates a **new** Google Sheet every click and
just overwrites `_sheets_meta.json` — old Sheets linger in Drive; edits made there are
ignored by later syncs. Additionally the step5-built xlsx is copied to 3 folders
(`step5_json/`, `step3_metadata/accepted/`, `step2_qcm/accepted/`) but sync regenerates
**only** the step2 copy — the other two stay stale forever.

### F6 — Auto-sync trigger is frontend-only and session-scoped (R1/R3, high)
`visibilitychange` fires only while that step's OutputViewer is mounted and only after
an in-session "open in sheets" click (`OutputViewer.tsx:50-83,250`); a page reload resets
`hasOpenedSheetRef`. If the user edits the Step-2 sheet, then (in another tab) reloads
the site or navigates straight to Step 6 and hits Run → **no sync** → Step 6 runs on
stale data. There is no server-side guarantee that a run consumes the sheet's latest state.

### F7 — Sync is not restart-safe (R3, high)
After a container restart the local FS is wiped. `sync_from_sheets` reads the canonical
and chain files from **local disk only** (`real_api.py:3412-3419, 3547-3562`) →
chain propagation finds no files → Storage copies of `step5_json/merged_qcms.json` etc.
keep the *older* edits. The next step run restores those stale chain files from Storage
(`real_api.py:2073-2083`) → edits lost even though sync "succeeded".

### F8 — UI feedback misses deletions and text-only edits (R1, low)
`newly_corrected` counts only field diffs on rows still present
(`real_api.py:3421-3451`) — deleted rows are never counted, deletions aren't returned in
the response at all. The frontend refreshes the file list and toasts only when
`newly_corrected > 0` (`OutputViewer.tsx:61-71`) → a deletion-only sync shows nothing
(and the newly-named xlsx doesn't appear until a manual reload). For Step 6, text-only
edits aren't counted either (only `Correct` changes are).

### F9 — Canonical type flattening (low)
Sheet values are all strings; the full overwrite stores `Tag` as `"['a','b']"`, `Year`
as `"2024"`. Downstream merges re-parse (`qcm_merge.py:43-58`), but the canonical files
themselves lose types (step 7 consumes `corrected_qcms.json` directly).

### F10 — Restore-deps mismatches (R3 after restart, verify-then-fix)
`STEP_INPUT_DEPENDENCIES` (`real_api.py:1859-1870`): step 7 restores
`step6_corrections/accepted` but step 7 reads `step6_corrections/corrected_qcms.json`
at the folder **root** (`step7_categorization.py:55`); step 8 restores
`step7_categories/accepted` but its source list reads `step7_categories/final_qcms.json`
at root (`step8_matcher.py:116-120`). Post-restart, steps 7/8 may not find their inputs
locally. (Needs a wipe-local verification test before touching.)

---

## 4. Requirements → findings

| Req | Blocked by | Fixed by phase |
|---|---|---|
| R1 auto-sync on return | works partially; F6, F8 | P4, P6 |
| R2 reopen/download shows edits | works for newest file; F5 | P3 |
| R3 next steps use edited version | F2, F3, F4, F6, F7, F10 | P1, P2, P4, P5, P7 |
| R4 deletions propagate | F1 (+F5 for stale files) | P2, P3 |

---

## 5. Phased plan

### P0 — Baseline characterization (tests first, no behavior change)
Extend `tests/test_sheet_edit_sync.py` with **real-shape** fixtures: sheet rows exactly
as `sync_from_sheets` builds them for the current workbooks (Num-keyed, no uid column,
all-string values). These expose F1/F3/F4 as red-by-design:
- deletion in sheet → still present in step5 merged / sibling / step3 (assert current
  broken behavior with a `# TODO(P2)` marker so the P2 diff flips them to green);
- real-shape Step-2 row → nothing reaches step3 accepted (same marker pattern);
- step-2 sync → `all_qcms.json` keeps uid/page/propositions after fix (P3 flips it).

### P1 — Identity bridge: give every workbook a `uid` column
- `Step5Builder._map_to_template` (`step5_builder.py:91-165`): carry `uid` (and `page`,
  `number`) from the step-3 row onto the mapped row. `xlsx_exporter` already appends
  extra fields (`xlsx_exporter.py:58-78`) → add `uid` at the end of `_PREFERRED_COLUMNS`
  so the Sheet gains a `uid` column; `merged_qcms.json` carries it too.
- With `uid` present, `qcm_key` matches **every** artifact (all_qcms, step3 pages, step5
  merged, corrected) — one identity everywhere; `Num` stays for humans.
- Migration for already-opened sheets (no uid column): at sync time, build a
  `Num→uid` bridge from the current `merged_qcms.json` order (step 5 assigns `Num`
  sequentially from the same files step 2 re-reads, so the index mapping is exact for
  the current generation); fall back to Num-keyed matching only for Num-keyed files.
- Bonus: row sorting/reordering in the sheet becomes identity-safe (key is uid, not order).

### P2 — Deletion propagation (tombstones) — core of R4
In `sync_from_sheets` after parsing the sheet:
1. `sheet_keys = {qcm_key(r) for r in new_qcms}`; `deleted_keys = old_canonical_keys − sheet_keys`.
2. Extend `qcm_merge.py` with `prune_deleted_qcms(path, deleted_keys) -> bool` and a
   chain-level `propagate_sheet_edits(root, edited_rows, deleted_keys)`; remove deleted
   rows from: sibling JSON, `step5_json/merged_qcms.json`, `step2_qcm/accepted/merged_qcms.json`,
   `step3_metadata/accepted/*.json`, and (P3) the merged-into canonical itself.
3. Re-upload every changed file to Storage (existing loop pattern, `real_api.py:3555-3560`).
4. Response gains `deleted_count`; log `[SYNC{step}] pruned N deleted row(s) from chain`.
5. Safety valve: if `deleted_keys` > 30% (configurable) of the old canonical, refuse and
   return 422 "sheet lost N% of rows — confirm deletion" unless `?force=1` (guards against
   a half-loaded/filtered sheet nuking the project). Threshold + behavior = Q1/Q2 below.

### P3 — Schema-safe canonical sync for Step 2 (kills F2)
Replace the full overwrite for step 2 with **merge + prune**:
- Load existing `all_qcms.json` (uid-keyed), translate sheet fields onto it
  (`Text→text`, `A..E→propositions.a..e`, `Cas→cas`; skip `Correct` — not a step-2 concept),
  apply deletions, write back uid-keyed. Raw extraction record stays intact.
- Regenerate the step-2 xlsx from the **merged** `merged_qcms.json` (not raw sheet rows)
  so workbook columns stay canonical.
- For step 6 keep the full overwrite (schema already matches) but type-normalize values
  against the previous canonical using `merge_qcm_fields` semantics (kills F9).

### P4 — Server-side sync-before-run (the R3 guarantee)
Refactor the sync body into an internal service `sync_step_from_sheets(user, project, step_id) -> dict`
(endpoint becomes a thin wrapper). In `_run_step_task`, **after**
`_restore_step_input_from_storage` (`real_api.py:2080-2083`) and **before** the step runs:
- for step in `("2","6")` registered in `_sheets_meta.json` and inside the dependency
  closure of the step being run (2 → all; 6/7/8 → 6 and 2): call the service
  (silent-fail on Google errors, visible log line `[PRE-RUN-SYNC]`).
- This makes "run next steps" correct regardless of frontend state: reloads, other panels,
  multi-device, races (sequential in-task → no race with the frontend auto-sync).
- Scope choice (both sheets vs only the run's inputs) = Q5.

### P5 — Stale-workbook hygiene (R2)
- After regenerating the xlsx, move superseded `^\d+_(qcms|corrections)_{stem}\.xlsx`
  files (local + Storage + `step_results.file_manifest`) into
  `_history/step{N}/sync_archive/` — exactly one current workbook per step folder.
- Regenerate the step-2 workbook copy in all 3 locations it lives in
  (`step5_json/`, `step3_metadata/accepted/`, `step2_qcm/accepted/`) or stop copying
  duplicates and keep a single canonical workbook (preferred — pick in Q4).
- `open-sheets`: when `_sheets_meta.json` has a `sheet_id` for the same filename,
  **update the existing Drive file** (`files().update` + media) instead of creating a
  new one; refresh `opened_at`. One Sheet per workbook; re-opens keep the same URL and
  the edit history (see Q3).

### P6 — Frontend polish (R1 UX)
- Refresh + toast whenever the sync response reports any change:
  `newly_corrected + deleted_count > 0` (or total changed) — not only `newly_corrected`.
- Toast text: "Synced X edit(s), Y deletion(s) from Google Sheets" (+ propagation info).
- Show a transient "Syncing from Google Sheets…" pill while the visibility sync runs
  (today it's silent until done).
- Manual `cloud_sync` button: same messaging; keep per-file placement.

### P7 — Restart-safe sync (kills F7)
- `sync_from_sheets`: on local-file miss, pull canonical + chain candidates from Storage
  (`_stream_file_from_storage` warms the local cache already) before diffing/merging —
  same pattern as the download endpoint (`real_api.py:3206-3210`).
- (P4 already covers the run path; this fixes the user-triggered sync path.)

### P8 — Restore-deps fixes (F10)
- Change deps to `("step6_corrections", None)` for step 7 and add
  `("step7_categories", None)` for step 8 (keep existing entries).
- Verify with a wipe-local-sim test (delete `/app/output/...` tree in test context,
  run restore, assert `corrected_qcms.json`/`final_qcms.json` land locally).

### Suggested order
P0 → P1 → P2 (core R4) → P3 → P4 (core R3) → P5 → P6 → P7 → P8.
P2+P3 together close the worst regression ("deleted rows resurrect"); P4 closes "ran on stale".

---

## 6. Test plan (summary)

1. `qcm_merge`: prune function (deleted keys removed; missing keys no-op; idempotent).
2. Real-shape sync tests (P0 fixtures flipped green after P1-P3):
   - Step-2 sheet delete row → gone from all_qcms, step5 merged, mirrors, step3 pages, sibling.
   - Step-2 sheet text edit → reaches all_qcms (`text`), step3 (`text`), step5 (`Text`), corrected.
   - `Tag`/`Year`/propositions survive round-trip (extend existing S1).
   - uid column present in exported step-5 workbook.
3. Endpoint-level: mock `build("sheets")` → sync service returns `deleted_count`,
   refuses >threshold without force (P2.5), 409/404/502 paths unchanged.
4. Pre-run hook: fake project with registered sheets → step-6 run consumes edited data
   even when no frontend sync ever fired (P4); Google failure → run proceeds (soft-fail log).
5. Restart simulation: wipe local dir → sync → Storage chain files updated (P7);
   restore deps for 7/8 (P8).
6. Stale-workbook: after sync with changed count, exactly one current xlsx per folder,
   manifest updated, old ones in `_history/.../sync_archive/` (P5).

All runnable via `python -m tests.test_sheet_edit_sync` style mains (repo convention).

---

## 7. Decisions (user-confirmed)

1. ✅ Deletion safety valve: ON — sync aborts (422) when a sync would delete >30% of
   the stored rows; user confirms (manual force) to apply.
2. ✅ Deleting a corrected QCM: deletion wins everywhere — no Correct-protection.
3. ✅ Re-open: browser open on the SAME Google Sheet gets UPDATED in place
   (one Sheet per workbook, same URL/edit history).
4. ✅ Stale workbooks: archived to `_history/step{N}/sync_archive/` (local+Storage+manifest);
   duplicate copies stay in sync (step5_json/, step3_metadata/accepted/) when present.
5. ✅ Pre-run auto-sync: option (a) — before running a step, sync every registered
   sheet whose step feeds it (2 and 6 before 6/7/8; just 2 before 2).
6. ✅ Conflicts: last-synced wins + a log line (no conflict UI).
7. ✅ `uid` column OK (hide, don't delete).
8. ✅ No periodic poll — on-return + pre-run is enough.

## 8. Original open questions (answered)

1. **Deletion safety valve (P2.5):** if the sheet loses more than ~30% of its rows vs
   the stored version, should sync (a) abort and ask you to confirm (recommended —
   protects against a half-loaded/filtered sheet wiping the project), or (b) always
   apply deletions blindly? And should the threshold be 30%, higher, or off?

2. **Deleting a corrected QCM (P2):** if you delete a row in the Step-2 sheet that already
   has a manual `Correct` answer in Step 6, deletion wins everywhere (recommended), or
   should corrected QCMs be protected from deletion until you clear the Correct first?

3. **Re-open behavior (P5):** today every "Open in Google Sheets" click creates a NEW
   Google Sheet and old ones linger in your Drive. Proposed: re-opening the same workbook
   updates the SAME Sheet (same URL/ID, same edit history). OK? Or do you sometimes
   intentionally open multiple copies?

4. **Stale workbooks (P5):** after a sync changes the row count, the old
   `150_qcms_...xlsx` style files — archive them to run-history (recommended, keeps
   everything inspectable), or hard-delete from the current output? Same question for
   the duplicate workbook copies in `step5_json/` and `step3_metadata/accepted/`:
   keep one canonical workbook only (recommended), or keep all three copies in sync?

5. **Pre-run auto-sync scope (P4):** before running a step, should the backend auto-sync
   (a) every registered sheet whose step feeds it (2 and 6 before steps 6/7/8; just 2
   before step 2 re-runs) — recommended; or (b) only the sheet of the step being run;
   or (c) never, keep sync strictly manual/visibility-triggered?

6. **Conflicting edits:** if you edit the same QCM differently in the Step-2 sheet and
   the Step-6 sheet (e.g. two different `Text`s), which wins? Options:
   last-synced wins (current behavior, no conflict detection), or fixed precedence
   "Step-6 sheet wins" (it's the correction stage), or surface the conflict and let
   you pick. Recommended: last-synced wins + a log line; conflict UI later if needed.

7. **Sheet identity column (P1):** the plan adds a `uid` column at the far right of the
   Step-2/5/6 workbooks (one per QCM, stable across runs). Harmless in Sheets; you can
   hide the column there but must not delete it. OK? (Without it, edits/deletions cannot
   reliably reach `all_qcms.json` and `step3_metadata`.)

8. **Auto-sync timing (R1):** today sync fires only when you *return to the website tab*
   (visibility change) or click the button. The plan adds server-side sync before every
   relevant run (P4). Do you also want a periodic background poll (say every 2-5 min
   while the site is open) so the file list/DB stay live even if you never leave the
   Sheets tab? (Costs Sheets API quota; recommended: no, pre-run + on-return is enough.)
