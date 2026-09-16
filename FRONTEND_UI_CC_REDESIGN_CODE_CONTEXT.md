# FRONTEND/UI — Code excerpts for context (re-engineering reference)

> Companion to `FRONTEND_UI_CC_REDESIGN_EXPLAINER.md`. File paths + trimmed
> render/data-flow logic for the surfaces relevant to the three new backend
> surfaces (`case_belonging_check`, boundary disagreement, skip cost).
> Context-gathering only — no changes proposed here.

---

## 1. File map (what owns what)

| File | Role |
|---|---|
| `frontend/src/pages/Pipeline.tsx` | StepList + ConfigPanel + TerminalLog composition |
| `frontend/src/components/pipeline/ConfigPanel.tsx` | per-step config host, run/stop wiring, WS log stream, CC alert raising |
| `frontend/src/components/pipeline/configs/Step2_3Config.tsx` | merged Step 2 panel: CC failure alert, extraction block, Metadata Strategy block + Huge-edit, CC Checker model pair |
| `frontend/src/components/pipeline/configs/Step3Config.tsx` | the per-field strategy cycle table (+ Global panel, YAML preview) |
| `frontend/src/components/pipeline/configs/Step2Config.tsx` | extraction models + auto-loop banner + "Clinical Case Hints" toggle |
| `frontend/src/components/pipeline/OutputViewer.tsx` | file list/preview/Sheets open/sync-back (steps 2/6) |
| `frontend/src/store/pipelineStore.ts` | zustand persisted store: steps, step3Config, `ccAlerts`, `isCcCheckerError` |
| `frontend/src/types/index.ts` | TS types (MetaStrategy, Step3Config, no QCM record type) |
| `frontend/src/lib/api.ts` | fetch layer (auth-aware) |
| `api/real_api.py` | step run mapping + output listing + step3 config forwarding |

---

## 2. Single-QCM display for review/editing

There is **no in-app per-QCM component** — verified: no file renders a QCM
record object. The human review/edit surface is external (Google Sheets) over
the exported xlsx. What exists closest:

### 2.1 OutputViewer raw preview (the only in-app "record view")
`frontend/src/components/pipeline/OutputViewer.tsx`
```tsx
const openPreview = async (file: any) => {
  ...
  setPreviewFile(file.name);
  ...
  const res = await fetch(
    `${BASE}/projects/${encodeURIComponent(projectName)}/steps/${stepId}/output/${encodedName}`,
    { headers: getAuthHeaders() });
  const data = await res.json();
  setPreviewContent(data.content || '[No content]');   // raw text, not parsed
};

// render (JSON files only; .xlsx never previews in-app):
{previewFile === file.name && !file.name.endsWith('.xlsx') && (
  <div className="bg-surface-container-lowest rounded-xl border ... font-mono text-[11px] ...">
    <code className="text-on-surface-variant">{previewContent}</code>
  </div>
)}
```
A JSON preview of `all_qcms.json` therefore already renders
`case_belonging_check` as plain text inside unformatted JSON.

### 2.2 The external human-review surface (Google Sheets round-trip)
OutputViewer:
```tsx
{["2", "6"].includes(stepId) && file.name.endsWith('.xlsx') && ... (
  <button ... title="Open in Google Sheets" onClick={... openInSheets(file)}>
  // POST /projects/.../open-sheets -> sheet URL; edits pulled back by:
  const vis-change auto-sync:
    const result = await syncFromSheets(projectName, stepId);
    if (result.newly_corrected > 0) { /* refresh file list + toast */ }
```
Columns shown to a reviewer = whatever `export_qcms_to_xlsx` emitted
(backend: `modules/utils/xlsx_exporter.py` `_build_columns`; `case_belonging_check`
is in `_PREFERRED_COLUMNS` right after `Cas` — backend phase 3 — so reviewers
SEE the audit column today, without any frontend change).

---

## 3. step3_config strategy-selection config component + its copy

`frontend/src/components/pipeline/configs/Step3Config.tsx` (rendered embedded
inside the merged Step 2 panel):
```tsx
const STRATEGIES: Record<string, { label, icon, color, order: MetaStrategy[] }> = {
  default:       { label: 'Standard', icon: 'settings', order: ['skip', 'global', 'per_qcm'] },
  clinical_case: { label: 'Clinical',  icon: 'group', order: ['skip', 'per_group', 'global'] }
}

const STRATEGY_STYLING: Record<MetaStrategy, { label: string, icon: string, style: string }> = {
  skip:      { label: 'Skip',      icon: 'block',     style: 'bg-surface-container-highest text-outline border-outline-variant/20' },
  global:    { label: 'Global',    icon: 'public',    style: 'bg-primary/10 text-primary border-primary/30' },
  per_qcm:   { label: 'Per-QCM',   icon: 'neurology', style: 'bg-secondary-container/30 text-secondary border-secondary/30' },
  per_group: { label: 'Per-Group', icon: 'group',     style: 'bg-tertiary-container/10 text-tertiary border-tertiary/30' }
}

function CycleButton({ field, strategy, onCycle }: ...) {
  const meta = STRATEGY_STYLING[strategy]
  return <button id={`btn-cycle-${field}`} onClick={onCycle}
      className={`... ${meta.style}`}>
    <span ...>{meta.icon}</span>{meta.label}
  </button>
}

export function Step3Config({ embedded }: { embedded?: boolean }) {
  const handleCycle = (field) => {
    const order = field === 'clinical_case' ? STRATEGIES.clinical_case.order
                                            : STRATEGIES.default.order
    const nextStrategy = order[(currentIndex + 1) % order.length]
    setConfig({ fields: { ...config.fields, [field]: { ...config.fields[field], strategy: nextStrategy } } })
  }
  // rows: field name (capitalize) + CycleButton            <- the whole strategy picker
  // Global panel appears when any field is 'global' (global_pages input + per-field value inputs)
  // {!embedded && ... YAML preview showing "metadata: fields: <field>: strategy"}
}
```
**All the strategy copy that exists:** the 4 chips' labels above — no
descriptions, no cost text. (So `skip`'s changed behavior isn't misdescribed;
it's simply undescribed.)

Host + surrounding copy in `frontend/src/components/pipeline/configs/Step2_3Config.tsx`:
```tsx
<p className="text-[10px] text-outline px-1">
  Metadata detection runs automatically after extraction completes.
  These settings control how year / source / category / clinical-case
  are assigned. Toggle <b>Huge edit</b> on if your overrides significantly
  deviate from defaults (labels the run in the audit log).
</p>
```
CC Checker description (`CCCheckerModels`, same file — the closest thing to a
strategy/cost statement; no mention of boundary checks or skip costs):
```tsx
Cheap/fast verification model — double-checks every cascaded Cas Clinique
link (one question per QCM) after metadata detection, then removes wrong
links. Runs when the Clinical Case strategy is Per-Group. Independent from
the extraction model above.
```
Clinical Case Hints toggle copy (`Step2Config.tsx`):
```tsx
Detect Cas Clinique headers and tag adjacent QCMs with
clinical_case_hint field. Useful for Step 3 detection.
```

---

## 4. Existing flag/note/audit UI patterns (reuse candidates)

### 4.1 Persistent, dismiss-only CC failure alert — closest pattern
`Step2_3Config.tsx`:
```tsx
function CcAlertCard({ project }: { project: string }) {
  const alert = usePipelineStore(s => s.ccAlerts[project])
  const dismissCcAlert = usePipelineStore(s => s.dismissCcAlert)
  if (!alert) return null
  return (
    <div id="cc-checker-alert" className="p-4 bg-error-container/40 border border-error/40 rounded-xl flex items-start gap-3">
      <span className="material-symbols-outlined text-error text-lg mt-0.5">error</span>
      <div className="flex-1 min-w-0">
        <p className="text-xs font-black text-error uppercase tracking-[0.15em]">Clinical Case Checker failed</p>
        <p ...>{alert.text.replace('[CC-CHECK] ⚠️ ERROR:', '').trim()}</p>
        <p ...>Case links were NOT verified — the run continued with unverified data.</p>
      </div>
      <button id="btn-dismiss-cc-alert" onClick={() => dismissCcAlert(project)} ...>...</button>
    </div>
  )
}
```
Raised from the WS log stream (store matcher — `pipelineStore.ts`):
```ts
export function isCcCheckerError(text: unknown): boolean {
  return typeof text === 'string' && text.includes('[CC-CHECK]') && text.includes('⚠️ ERROR')
}
// ConfigPanel.handleRun:
if (activeStep.id === 2 && isCcCheckerError(line?.text) && activeProject?.name) {
  raiseCcAlert(activeProject.name, line.text)
}
```
Persisted state (`pipelineStore.ts`): `ccAlerts: Record<string, { ts: string; text: string }>`
in `partialize` — survives reloads, cleared only by `dismissCcAlert`.

### 4.2 Inline warning + confirmation — `ConfigPanel.OverwriteWarning` (shown above)
Banner + checkbox; pattern for "acknowledge before proceeding" blocks.

### 4.3 Intent-flag for audit logging — "Huge edit" toggle (`Step2_3Config.tsx`)
```tsx
<button id="toggle-huge-edit" onClick={() => setStep3Config({ huge_edit: !hugeEdit })} ...>
  {/* pills row: Huge edit */}
</button>
<p>...Toggle Huge edit on if your overrides significantly deviate from defaults
   (labels the run in the audit log).</p>
```
That is the ONLY existing "human review intent" primitive — flag-shaped
(pill + flag icon + tertiary color), run-scoped, not data-scoped.

### 4.4 Run stats badges — `ConfigPanel.StepHeader`
```tsx
{lastRun.merged_qcms != null && <span ...>· {lastRun.merged_qcms} merged</span>}
```

---

## 5. Data flow: backend files → rendered UI (excerpts)

### 5.1 Run payload carries step3Config — `ConfigPanel.handleRun`
```tsx
if (activeStep.id === 2) {
  const s = store.step2Config
  const cc = store.step3Config.clinical_case_checker ?? { model: '', model_fallback: '' }
  config = {
    page_range: '1-1-1', ...
    step3: store.step3Config,
    clinical_case_checker: { model_primary: cc.model, model_fallback: cc.model_fallback },
  }
}
await runStep(activeProject.name, activeStep.id, config)      // lib/api.ts
```

### 5.2 Backend consumes it + env overrides — `api/real_api.py`
```python
# step 2 env side:
cc_cfg = config.get("clinical_case_checker", {}) or {}
if cc_cfg.get("model_primary"):
    os.environ["CC_CHECKER_MODEL"] = cc_cfg["model_primary"]
...
step3_cfg = config.get("step3", config.get("step3_config", {}))
res = await loop.run_in_executor(None, lambda: _cascade_with_telemetry(
        tracker, context, user_id, project, step3_cfg, cancel_check, step_id, ...))
if rstatus == "ok":
    ... log_callback(... "⚡ Auto-enrich (Step 3 + build) completed: ...")
    for _sid in ("3", "4", "5"): job_manager.set_done(project, _sid)
elif rstatus == "no_qcms": warn "Auto-enrich skipped: no accepted QCMs after Step 2."
```

### 5.3 Output surfacing — OutputViewer list + preview + Sheets round-trip
```tsx
// GET /projects/{name}/steps/{stepId}/output  → { files: [...] }
const data = await fetchStepOutput(projectName, stepId);
setFiles(sortOutputFiles(data.files));
// backend (_SFMAP): step "2" -> step2_qcm folder (recursive; hides _sheets_meta.json)
// preview: GET .../output/{filename} -> {content: <raw text>}  (JSON preview)
// xlsx: "open-sheets" upload + "sync-from-sheets" pull-back:
const result = await syncFromSheets(projectName, stepId);   // new / propagated counters -> toast
```
Backed mapping excerpt (`api/real_api.py`) — where a per-QCM audit field
would need to be threaded if a screen later wanted structured access:
```python
_SFMAP = {"1": "step1_extraction", "2": "step2_qcm", "3": "step3_metadata",
          "6": "step6_corrections", "8": "step8_matches", ...}
step_dir = Path(f"/app/output/{user['id']}/{name}/{folder_name}")
# file list (recursive), raw JSON served as {"content": ...}
```

### 5.4 Store types — nothing QCM-typed exists
`frontend/src/types/index.ts`: `Step3Config`, `MetaFieldConfig {strategy, value}`,
`CCCheckerConfig`, `StepRunRecord` (badge/counts) — **no interface for QCM
records**, so `case_belonging_check` needs no type change to appear in raw JSON
previews, but would require a new type + component to render structured.
