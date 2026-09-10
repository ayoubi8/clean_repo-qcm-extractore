import { useState, useEffect } from 'react'
import { Step2Config } from './Step2Config'
import { Step3Config } from './Step3Config'
import { usePipelineStore } from '../../../store/pipelineStore'
import { useStepModels } from '../../../hooks/useStepModels'
import { useAppStore } from '../../../store/appStore'

/**
 * Merged "Step 2 · QCM Extraction + Metadata" config panel.
 *
 * Auto-Loop mode is now always on (1-1-1 hardcoded; see
 * Step2Config.tsx info banner + ConfigPanel.handleRun). The metadata
 * strategy block is shown by default — no more "Advanced" collapsible.
 * A "Huge edit" toggle at the top of the metadata block lets the user
 * flag (for the audit log) when their overrides deviate significantly
 * from the defaults.
 *
 * The underlying store state (`step2Config` + `step3Config`) is kept
 * split (Q3→3a): ConfigPanel.tsx forwards both to the backend, where
 * Step 2's cascade passes `step3Config` to run_post_step2_metadata.
 */

/** Persistent alert shown when the Clinical Case Checker failed during a
 * Step 2 run (soft-fail: the build continued with UNVERIFIED case links).
 * Kept in the persisted store — it survives reloads and only disappears
 * when the user explicitly dismisses it. */
function CcAlertCard({ project }: { project: string }) {
  const alert = usePipelineStore(s => s.ccAlerts[project])
  const dismissCcAlert = usePipelineStore(s => s.dismissCcAlert)
  if (!alert) return null

  return (
    <div
      id="cc-checker-alert"
      className="p-4 bg-error-container/40 border border-error/40 rounded-xl flex items-start gap-3"
    >
      <span className="material-symbols-outlined text-error text-lg mt-0.5">error</span>
      <div className="flex-1 min-w-0">
        <p className="text-xs font-black text-error uppercase tracking-[0.15em]">
          Clinical Case Checker failed
        </p>
        <p className="text-[11px] text-on-surface-variant mt-1 break-all">
          {alert.text.replace('[CC-CHECK] ⚠️ ERROR:', '').trim()}
        </p>
        <p className="text-[10px] text-outline mt-1 font-mono">
          Case links were NOT verified — the run continued with unverified data.
        </p>
      </div>
      <button
        id="btn-dismiss-cc-alert"
        onClick={() => dismissCcAlert(project)}
        title="Hide this alert"
        className="shrink-0 w-7 h-7 rounded-lg border border-error/30 flex items-center justify-center text-error hover:bg-error/10 transition-colors"
      >
        <span className="material-symbols-outlined text-[16px]">close</span>
      </button>
    </div>
  )
}

/** Phase 1 — Clinical Case Checker model pair (cheap/fast verifier).
 * Independent from the Step 2 extraction model: it only double-checks the
 * cascaded Cas Clinique links, one question per QCM. Distinct from the
 * "Clinical Case Hints" toggle in Step2Config (that one tags headers during
 * extraction). */
function CCCheckerModels() {
  const config = usePipelineStore(s => s.step3Config.clinical_case_checker)
  const setStep3Config = usePipelineStore(s => s.setStep3Config)
  const { models, loading } = useStepModels()
  const [isCustomPrimary, setIsCustomPrimary] = useState(false)
  const [isCustomFallback, setIsCustomFallback] = useState(false)

  // Seed from .env (CC_CHECKER_MODEL / CC_CHECKER_FALLBACK_MODEL) on first load
  useEffect(() => {
    if (!loading && models?.clinical_case_checker) {
      if (!config.model && models.clinical_case_checker.primary)
        setStep3Config({ clinical_case_checker: { ...config, model: models.clinical_case_checker.primary } })
      if (!config.model_fallback && models.clinical_case_checker.fallback)
        setStep3Config({ clinical_case_checker: { ...config, model_fallback: models.clinical_case_checker.fallback } })
    }
  }, [loading, models])

  const selectClass = "w-full bg-surface-container-lowest border border-outline-variant/20 rounded-xl px-4 py-3 text-sm focus:border-primary outline-none transition-all appearance-none disabled:opacity-50"
  const inputClass = "w-full mt-1 bg-surface-container-lowest border border-outline-variant/20 rounded-xl px-4 py-3 text-sm focus:border-primary outline-none animate-in fade-in font-mono"

  return (
    <div className="space-y-4">
      <div className="space-y-1">
        <div className="flex items-center gap-2">
          <span className="material-symbols-outlined text-tertiary text-lg">fact_check</span>
          <label className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">
            Clinical Case Checker
          </label>
        </div>
        <p className="text-[10px] text-outline px-1">
          Cheap/fast verification model — double-checks every cascaded{' '}
          <span className="font-mono text-tertiary">Cas Clinique</span> link (one question
          per QCM) after metadata detection, then removes wrong links. Runs when the
          Clinical Case strategy is <span className="font-bold text-tertiary">Per-Group</span>.
          Independent from the extraction model above.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-2">
          <label className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">Primary</label>
          <select
            id="select-cc-checker-model-primary"
            value={isCustomPrimary ? 'custom' : config.model}
            onChange={e => {
              if (e.target.value === 'custom') { setIsCustomPrimary(true) }
              else {
                setIsCustomPrimary(false)
                setStep3Config({ clinical_case_checker: { ...config, model: e.target.value } })
              }
            }}
            disabled={loading}
            className={selectClass}
          >
            {loading ? (
              <option>Loading...</option>
            ) : (
              <>
                <option value={models?.clinical_case_checker?.primary}>{models?.clinical_case_checker?.primary} (Primary)</option>
                <option value={models?.clinical_case_checker?.fallback}>{models?.clinical_case_checker?.fallback} (Fallback)</option>
                <option value="custom">Custom…</option>
              </>
            )}
          </select>
          {isCustomPrimary && (
            <input
              id="input-cc-checker-model-primary-custom"
              type="text"
              value={config.model}
              onChange={e => setStep3Config({ clinical_case_checker: { ...config, model: e.target.value } })}
              className={inputClass}
              placeholder="Model ID..."
            />
          )}
        </div>

        <div className="space-y-2">
          <label className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">Fallback</label>
          <select
            id="select-cc-checker-model-fallback"
            value={isCustomFallback ? 'custom' : config.model_fallback}
            onChange={e => {
              if (e.target.value === 'custom') { setIsCustomFallback(true) }
              else {
                setIsCustomFallback(false)
                setStep3Config({ clinical_case_checker: { ...config, model_fallback: e.target.value } })
              }
            }}
            disabled={loading}
            className={selectClass}
          >
            {loading ? (
              <option>Loading...</option>
            ) : (
              <>
                <option value={models?.clinical_case_checker?.primary}>{models?.clinical_case_checker?.primary}</option>
                <option value={models?.clinical_case_checker?.fallback}>{models?.clinical_case_checker?.fallback} (Fallback)</option>
                <option value="custom">Custom…</option>
              </>
            )}
          </select>
          {isCustomFallback && (
            <input
              id="input-cc-checker-model-fallback-custom"
              type="text"
              value={config.model_fallback}
              onChange={e => setStep3Config({ clinical_case_checker: { ...config, model_fallback: e.target.value } })}
              className={inputClass}
              placeholder="Model ID..."
            />
          )}
        </div>
      </div>
    </div>
  )
}

export function Step2_3Config() {
  const hugeEdit = usePipelineStore(s => s.step3Config.huge_edit)
  const setStep3Config = usePipelineStore(s => s.setStep3Config)
  const activeProject = useAppStore(s => s.activeProject)

  return (
    <div className="space-y-8 animate-in fade-in slide-in-from-bottom-2 duration-300">
      {/* Persistent Clinical Case Checker failure alert (survives reloads,
          dismissed only by click) */}
      {activeProject?.name && <CcAlertCard project={activeProject.name} />}

      {/* Primary: extraction config (Auto-Loop 1-1-1, always on) */}
      <Step2Config />

      {/* Divider */}
      <div className="border-t border-outline-variant/10 pt-6" />

      {/* Metadata strategies — shown by default (was previously hidden behind a collapsible) */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined text-outline text-lg">tune</span>
            <span className="text-xs font-black text-on-surface-variant uppercase tracking-[0.2em]">
              Metadata Strategy
            </span>
          </div>

          {/* Huge-edit toggle */}
          <button
            id="toggle-huge-edit"
            type="button"
            onClick={() => setStep3Config({ huge_edit: !hugeEdit })}
            className={`flex items-center gap-2 px-3 py-1.5 rounded-xl border-2 transition-all ${
              hugeEdit
                ? 'border-tertiary bg-tertiary/10 text-tertiary'
                : 'border-outline-variant/20 bg-surface-container-low text-outline hover:text-on-surface'
            }`}
          >
            <div className={`w-8 h-4 rounded-full flex items-center px-0.5 transition-all ${
              hugeEdit ? 'bg-tertiary justify-end' : 'bg-outline/30 justify-start'
            }`}>
              <div className="w-3 h-3 bg-white rounded-full shadow" />
            </div>
            <span className="text-[10px] font-black uppercase tracking-[0.18em]">
              Huge edit
            </span>
          </button>
        </div>

        <p className="text-[10px] text-outline px-1">
          Metadata detection runs automatically after extraction completes.
          These settings control how year / source / category / clinical-case
          are assigned. Toggle <span className="font-bold text-tertiary">Huge edit</span> on
          if your overrides significantly deviate from defaults (labels the run
          in the audit log).
        </p>

        {hugeEdit && (
          <div className="p-3 rounded-xl bg-tertiary-container/5 border border-tertiary/20 flex items-center gap-2 animate-in fade-in slide-in-from-top-1 duration-300">
            <span className="material-symbols-outlined text-tertiary text-lg">flag</span>
            <p className="text-[11px] text-tertiary font-medium">
              Huge edit enabled — non-default strategies will override the metadata cascade.
            </p>
          </div>
        )}

        <div className="pt-2">
          <Step3Config embedded />
        </div>

        {/* Phase 1 — Clinical Case Checker verification model */}
        <div className="pt-2">
          <CCCheckerModels />
        </div>
      </div>
    </div>
  )
}
