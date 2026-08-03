import { usePipelineStore } from '../../../store/pipelineStore'
import { useStepModels } from '../../../hooks/useStepModels'
import { useState, useEffect } from 'react'

export function Step2Config() {
  const config = usePipelineStore(s => s.step2Config)
  const setConfig = usePipelineStore(s => s.setStep2Config)
  const { models, loading } = useStepModels()
  const [isCustomPrimary, setIsCustomPrimary] = useState(false)
  const [isCustomFallback, setIsCustomFallback] = useState(false)

  // Seed models from .env on first load
  useEffect(() => {
    if (!loading && models?.step2) {
      if (!config.model_primary && models.step2.primary)
        setConfig({ model_primary: models.step2.primary })
      if (!config.model_fallback && models.step2.fallback)
        setConfig({ model_fallback: models.step2.fallback })
    }
  }, [loading, models])

  return (
    <div className="space-y-7 animate-in fade-in slide-in-from-bottom-2 duration-300">

      {/* Auto-loop info banner */}
      <div className="p-3 rounded-xl bg-primary/5 border border-primary/20 flex items-center gap-2">
        <span className="material-symbols-outlined text-primary text-lg">repeat_one</span>
        <p className="text-[11px] text-primary font-medium">
          Auto-Loop mode is ON — each page is processed in its own LLM chunk (1-1-1).
        </p>
      </div>

      {/* ── Models (applies to QCM extraction + metadata cascade) ── */}
      <div className="space-y-2">
        <label className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">
          Extraction Model <span className="text-primary normal-case font-medium">· applies to QCM + Metadata</span>
        </label>
        <p className="text-[10px] text-outline px-1 -mt-1">
          The primary/fallback model below is used for both QCM extraction (this step) and
          the metadata auto-detection cascade (Step 3) that runs right after.
        </p>
      </div>
      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-2">
          <label className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">Primary</label>
          <select
            id="select-step2-model-primary"
            value={isCustomPrimary ? 'custom' : config.model_primary}
            onChange={e => {
              if (e.target.value === 'custom') { setIsCustomPrimary(true) }
              else { setIsCustomPrimary(false); setConfig({ model_primary: e.target.value }) }
            }}
            disabled={loading}
            className="w-full bg-surface-container-lowest border border-outline-variant/20 rounded-xl px-4 py-3 text-sm focus:border-primary outline-none transition-all appearance-none disabled:opacity-50"
          >
            {loading ? (
              <option>Loading...</option>
            ) : (
              <>
                <option value={models?.step2?.primary}>{models?.step2?.primary} (Primary)</option>
                <option value={models?.step2?.fallback}>{models?.step2?.fallback} (Fallback)</option>
                <option value="custom">Custom…</option>
              </>
            )}
          </select>
          {isCustomPrimary && (
            <input
              id="input-step2-model-primary-custom"
              type="text"
              value={config.model_primary}
              onChange={e => setConfig({ model_primary: e.target.value })}
              className="w-full mt-1 bg-surface-container-lowest border border-outline-variant/20 rounded-xl px-4 py-3 text-sm focus:border-primary outline-none animate-in fade-in font-mono"
              placeholder="Model ID..."
            />
          )}
        </div>

        <div className="space-y-2">
          <label className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">Fallback</label>
          <select
            id="select-step2-model-fallback"
            value={isCustomFallback ? 'custom' : config.model_fallback}
            onChange={e => {
              if (e.target.value === 'custom') { setIsCustomFallback(true) }
              else { setIsCustomFallback(false); setConfig({ model_fallback: e.target.value }) }
            }}
            disabled={loading}
            className="w-full bg-surface-container-lowest border border-outline-variant/20 rounded-xl px-4 py-3 text-sm focus:border-primary outline-none transition-all appearance-none disabled:opacity-50"
          >
            {loading ? (
              <option>Loading...</option>
            ) : (
              <>
                <option value={models?.step2?.primary}>{models?.step2?.primary}</option>
                <option value={models?.step2?.fallback}>{models?.step2?.fallback} (Fallback)</option>
                <option value="custom">Custom…</option>
              </>
            )}
          </select>
          {isCustomFallback && (
            <input
              id="input-step2-model-fallback-custom"
              type="text"
              value={config.model_fallback}
              onChange={e => setConfig({ model_fallback: e.target.value })}
              className="w-full mt-1 bg-surface-container-lowest border border-outline-variant/20 rounded-xl px-4 py-3 text-sm focus:border-primary outline-none animate-in fade-in font-mono"
              placeholder="Model ID..."
            />
          )}
        </div>
      </div>

      {/* ── Extraction Guidance ── */}
      <div className="space-y-2">
        <label className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">Extraction Guidance</label>
        <textarea
          id="input-step2-guidance"
          rows={3}
          value={config.extraction_guidance}
          onChange={e => setConfig({ extraction_guidance: e.target.value })}
          className="w-full bg-surface-container-lowest border border-outline-variant/20 rounded-xl px-4 py-3 text-sm focus:border-primary outline-none transition-all resize-none custom-scrollbar"
          placeholder="Optional rules for the LLM, e.g. 'Extract year from bold markers above each question'"
        />
      </div>

      {/* ── Clinical Case Hints ── */}
      <div
        className={`flex items-start gap-4 p-4 rounded-xl border-2 cursor-pointer transition-all ${
          config.clinical_case_hints
            ? 'border-tertiary/40 bg-tertiary/5'
            : 'border-outline-variant/10 bg-surface-container-low hover:border-outline-variant/30'
        }`}
        onClick={() => setConfig({ clinical_case_hints: !config.clinical_case_hints })}
        id="toggle-clinical-case-hints"
      >
        <div className={`mt-0.5 w-10 h-5 rounded-full flex items-center px-0.5 transition-all shrink-0 ${
          config.clinical_case_hints ? 'bg-tertiary justify-end' : 'bg-outline/30 justify-start'
        }`}>
          <div className="w-4 h-4 bg-white rounded-full shadow" />
        </div>
        <div>
          <p className={`text-sm font-bold ${config.clinical_case_hints ? 'text-tertiary' : 'text-on-surface'}`}>
            Clinical Case Hints
          </p>
          <p className="text-[11px] text-outline mt-0.5">
            Detect <span className="font-mono">Cas Clinique</span> headers and tag adjacent QCMs with{' '}
            <span className="font-mono text-primary">clinical_case_hint</span> field. Useful for Step 3 detection.
          </p>
        </div>
      </div>

    </div>
  )
}