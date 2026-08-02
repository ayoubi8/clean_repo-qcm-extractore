import { Step2Config } from './Step2Config'
import { Step3Config } from './Step3Config'
import { usePipelineStore } from '../../../store/pipelineStore'

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
export function Step2_3Config() {
  const hugeEdit = usePipelineStore(s => s.step3Config.huge_edit)
  const setStep3Config = usePipelineStore(s => s.setStep3Config)

  return (
    <div className="space-y-8 animate-in fade-in slide-in-from-bottom-2 duration-300">
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
      </div>
    </div>
  )
}