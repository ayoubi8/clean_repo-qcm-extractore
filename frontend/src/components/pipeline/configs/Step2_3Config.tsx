import { useState } from 'react'
import { Step2Config } from './Step2Config'
import { Step3Config } from './Step3Config'

/**
 * Merged "Step 2 · QCM Extraction + Metadata" config panel.
 *
 * The old Step 2 (extraction) and Step 3 (metadata) were merged into a single
 * visible step — see MERGE_STEP2_STEP3_REPORT.md. This panel renders the
 * extraction config as the primary surface and exposes the metadata strategies
 * under an "Advanced" collapsible so power users keep discoverability.
 *
 * The underlying store state (`step2Config` + `step3Config`) is kept split
 * (Q3→3a): ConfigPanel.tsx forwards both to the backend, where Step 2's
 * cascade passes `step3Config` to run_post_step2_metadata.
 */
export function Step2_3Config() {
  const [showAdvanced, setShowAdvanced] = useState(false)

  return (
    <div className="space-y-8 animate-in fade-in slide-in-from-bottom-2 duration-300">
      {/* Primary: extraction config (the old Step2Config, unchanged) */}
      <Step2Config />

      {/* Divider */}
      <div className="border-t border-outline-variant/10 pt-6" />

      {/* Advanced: metadata strategies (the old Step3Config, collapsible) */}
      <div className="space-y-3">
        <button
          id="btn-toggle-advanced-metadata"
          type="button"
          onClick={() => setShowAdvanced(v => !v)}
          className="w-full flex items-center justify-between p-3 rounded-xl border border-outline-variant/10 bg-surface-container-low hover:border-primary/30 transition-all"
        >
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined text-outline text-lg">tune</span>
            <span className="text-xs font-black text-on-surface-variant uppercase tracking-[0.2em]">
              Advanced · Metadata Strategy
            </span>
          </div>
          <span className={`material-symbols-outlined text-outline transition-transform ${showAdvanced ? 'rotate-180' : ''}`}>
            expand_more
          </span>
        </button>

        <p className="text-[10px] text-outline px-1">
          Metadata detection runs automatically after extraction completes.
          These settings control how year / source / category / clinical-case
          are assigned. Collapse to use defaults.
        </p>

        {showAdvanced && (
          <div className="animate-in fade-in slide-in-from-top-1 duration-300 pt-2">
            <Step3Config embedded />
          </div>
        )}
      </div>
    </div>
  )
}
