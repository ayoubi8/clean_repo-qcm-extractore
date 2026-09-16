# FRONTEND/UI — How it works today (context document)

> Purpose: inventory of what the frontend currently renders/does BEFORE any
> proposal for the three new backend surfaces introduced by Clinical Case
> Redesign v2 (phases 0–7):
> 1. `case_belonging_check` — per-QCM audit string (written to data only today)
> 2. Boundary-check disagreement (flag exists in data, consumed by nothing)
> 3. `skip` strategy behavior/cost change (was "do nothing", now ~1 hygiene
>    LLM call per page)
> Companion code file: `FRONTEND_UI_CC_REDESIGN_CODE_CONTEXT.md`.
> This is a context-gathering pass — no changes proposed.

---

## 1. The big picture

- **One visible pipeline row per step.** The UI shows Step 1 · Text Extraction,
  **Step 2 · QCM Extraction + Metadata** (merged row), Step 6 · Corrections,
  Step 7 · Categorization, Step 8 · Similarity Match. Steps 3/4/5 are invisible
  backend cascade stages inside Step 2 (rows removed in store v2→v3; `StepId 3`
  survives for status polling). The merged row's config panel is
  `Step2_3Config` (extraction model + hint toggle + Metadata Strategy block +
  CC Checker model pair), and the run button forwards
  `{step3: store.step3Config, clinical_case_checker: {...}}` to the backend.
- **The frontend NEVER renders individual QCM records in-app.** There is no
  per-QCM review/edit screen anywhere. Humans review and edit QCMs EXTERNALLY
  in **Google Sheets**: for steps 2 & 6 the OutputViewer lets the user push the
  merged `.xlsx` to Sheets ("Open in Google Sheets"), edit there, and the app
  pulls edits BACK with `sync-from-sheets` (auto-syncs on tab-return + manual
  cloud_sync button). So per-QCM display = **whatever the XLSX exporter puts
  in columns**.
- **In-app "QCM view"** = the OutputViewer: a file list per step (sorted by
  page number) with preview/download/open/delete. JSON files preview as **raw
  text** (`data.content` in a `<code>` block) — so a JSON preview shows
  `case_belonging_check` only as unformatted JSON text. `.xlsx` files do not
  preview in-app; they open in Sheets or download.

---

## 2. WHAT EXISTS TODAY for the three new backend surfaces

### 2.1 `case_belonging_check` (per-QCM audit string)

- **No frontend consumer, no UI surface.** Grep of the whole `frontend/src`
  finds zero occurrences of `case_belonging_check`. Nothing renders data
  fields from the merged JSON in-app (no per-QCM table/cards anywhere).
- **Where it COULD surface passively today, without any new code:**
  - The Step 8 XLSX export (and the Step 5 merged build copyback file
    `merged_qcms.json` / `merged_qcms.xlsx` surfaced into step2_qcm/accepted)
    build their columns **dynamically from the data keys** — `case_belonging_check`
    is in the exporter's preferred-column list (added backend Phase 3),
    ordered right after `Cas`. So any user who opens the merged xlsx (in-app
    download `merged_qcms.xlsx` → Sheets) ALREADY gets the audit column.
  - The raw JSON preview in OutputViewer (steps "2" or "3") would show the key
    verbatim if the user previews `all_qcms.json` / step3 accepted JSON.
- **No "flagged for review" pattern exists for data rows** — review happens
  externally in Sheets; in-app, the only per-row "meta" display is the step
  Last-Run badge line (badge emoji + qcms/pages/merged counts).

### 2.2 Boundary-check disagreement flag

- **Nothing consumes it.** The backend relink check (phase 5) writes its
  outcome into `case_belonging_check` ("boundary re-check YES/NO/unresolved")
  and an audit file `cc_boundary_checks.json` — no fetch endpoint, no store
  slice, no component references `cc_boundary_*` files or the term.
- What DOES surface related to CC quality today: the **persistent CC Checker
  failure alert** (`CcAlertCard` in Step2_3Config), raised by string-matching
  the single backend marker line `[CC-CHECK] ⚠️ ERROR:` in the WebSocket log
  stream; it survives reloads (persisted store) and is dismissed only by
  click. This is the closest existing "persistent review flag" pattern, but
  it is run-level (checker crashed), not per-QCM.
- Terminal log also streams the cascade's plain lines; boundary run lines
  (`[CC-BOUNDARY] ...`) would appear as ordinary terminal-log text during a
  run, and vanish when the log is cleared — nothing persists/summarizes them.

### 2.3 `skip` strategy behavior/cost

- The settings screen where strategies are chosen is the **merged Step 2
  panel → "Metadata Strategy" block** (`Step3Config` embedded): for each
  field (year / source / category / clinical case) a cycle button toggles
  through a strategy order. Cycle button labels are the ONLY copy:
  - clinical_case cycle order: **Skip → Per-Group → Global**
  - other fields: **Skip → Global → Per-QCM**
  - `SHOW METADATA STRATEGIES` panel copy (Step2_3Config): "Metadata detection
    runs automatically after extraction completes. These settings control how
    year / source / category / clinical-case are assigned."
  - There are **no per-strategy descriptions anywhere in the UI** — "Skip",
    "Global", "Per-QCM", "Per-Group" are icon+label chips only. Nothing today
    states any cost implication for skip, so nothing textually LIES about the
    new hygiene call — but the UI also doesn't tell the user that `skip` now
    still spends ~1 LLM call per page, or that hygiene (narrative split into
    the Cas column even without linkage) still happens.
- Related existing copy that borders on stale: the CC Checker block says it
  "Runs when the Clinical Case strategy is **Per-Group**" (still true; it now
  also applies to a new boundary check that is bounded per case-ending).
- The nearest "cost" messaging in the app: the terminal log (`appendLog`) and
  the costs panels — no copy ties strategy choice to expected cost.

### 2.4 Does any screen show `cas` / clinical case info? 

- **In-app:** no component renders `cas` or any case text. The only clinical-
  case UI artifacts today are all config/plumbing:
  - "Clinical Case Hints" toggle (Step2Config) — extraction-time hint tagging.
  - "Clinical Case Checker" model pair (Step2_3Config) + its failure alert.
  - Metadata strategy cycle button for `clinical_case`.
- **Externally:** the merged xlsx (Cas column, after Num; `case_belonging_check`
  column since phase 3) viewed in Google Sheets.

### 2.5 Export/build surfaces

- There is **no export/build screen** for steps 4/5 (invisible). The only
  export-related UI is **Step 8** (`Step8Config` + `ExportExistingButton` +
  `MergeResultsPanel`): thresholds, weights, color cut-offs, custom-export
  range/filename, tag-merge stats. Nothing in Step 8's config mentions
  clinical cases; the export result carries the columns the exporter put in.
- Step 8's MergeResultsPanel shows a summary manifest (merge/deletion counts,
  files). If `case_belonging_check` is in the underlying xlsx it rides along,
  but no UI element names it.

---

## 3. Existing reusable UI patterns (for reference; not proposals)

| Pattern | Where | Shape |
|---|---|---|
| Persistent run-level failure alert | `CcAlertCard` (Step2_3Config) | persisted store `ccAlerts{project}`, red-bordered card, icon+title+text+dismiss-click, survives reloads |
| Log-driven flag raising | `ConfigPanel.handleRun` + `isCcCheckerError` (store) | string-match a backend marker line on the WS stream → store alert |
| Confirmation/warning block | `OverwriteWarning` (ConfigPanel) | inline yellow banner + checkbox confirmation |
| "User intent flag for audit log" | "Huge edit" toggle (Step2_3Config) | small pill toggle + amber info card when toggled |
| Run badges/stats | `StepHeader lastRun` (ConfigPanel) | badge emoji + counts (pages_ok / qcms / merged_qcms) |
| Raw file preview | `OutputViewer.openPreview` | monospace `<code>` text of JSON (would display `case_belonging_check` if presented) |
| Toast | `syncToast` (OutputViewer) | fixed bottom-right transient |

---

## 4. Data-flow map (backend → screen)

Step run → backend cascade (`modules/post_step2_metadata.py`) writes
`step3_metadata/accepted/*.json` + `cc_boundary_transitions.json` + audits,
then Step 4/5 build writes `merged_qcms.json`/`merged_qcms.xlsx` (copyback into
`step2_qcm/accepted`). Frontend sees this ONLY via OutputViewer endpoints:
`GET /projects/{name}/steps/{stepId}/output` (file list, recursive from
`step2_qcm`; xlsx→Sheets upload via `/open-sheets`; pull-back via
`/sync-from-sheets`), raw JSON preview via the same path. Config flows the
other way: pipelineStore `step3Config` → `config.step3` on the Step 2 run
payload → `real_api._call_step` (side: CC_CHECKER_* env overrides) →
`run_post_step2_metadata.step3_config`. To reach a React component (if later
wanted), `case_belonging_check` would thread: accepted JSON → OutputViewer
`data.content` (raw pre-view) / the xlsx exporter (via Sheets) — there is no
typed QCM object in the frontend (no field exists in any TS interface).
