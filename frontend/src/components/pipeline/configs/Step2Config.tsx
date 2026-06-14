import { usePipelineStore } from '../../../store/pipelineStore'
import { useStepModels } from '../../../hooks/useStepModels'
import { useState, useEffect } from 'react'

const CHUNK_SIZES = [1, 2, 3, 5, 10]

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

      {/* ── Extraction Mode ── */}
      <div className="space-y-3">
        <label className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">Extraction Mode</label>
        <div className="grid grid-cols-1 gap-3">
          {[
            {
              id: 'single_batch',
              label: 'Single Batch',
              sub: 'All pages in one LLM call — best for short PDFs (≤ 10 pages)'
            },
            {
              id: 'auto_loop',
              label: 'Auto-Loop',
              sub: 'N pages per chunk — reliable for long PDFs, shows chunk progress'
            }
          ].map(opt => (
            <div
              key={opt.id}
              id={`mode-${opt.id}`}
              onClick={() => setConfig({ extraction_mode: opt.id as any })}
              className={`p-4 rounded-xl border-2 cursor-pointer transition-all ${
                config.extraction_mode === opt.id
                  ? 'border-primary bg-primary/5 shadow-[0_0_15px_rgba(76,215,246,0.1)]'
                  : 'border-outline-variant/10 bg-surface-container-low hover:border-outline-variant/30'
              }`}
            >
              <div className="flex items-center justify-between">
                <div>
                  <p className={`text-sm font-bold ${config.extraction_mode === opt.id ? 'text-primary' : 'text-on-surface'}`}>
                    {opt.label}
                  </p>
                  <p className="text-[11px] text-outline mt-0.5">{opt.sub}</p>
                </div>
                <div className={`w-4 h-4 rounded-full border-2 flex items-center justify-center shrink-0 ${
                  config.extraction_mode === opt.id ? 'border-primary' : 'border-outline'
                }`}>
                  {config.extraction_mode === opt.id && <div className="w-2 h-2 bg-primary rounded-full" />}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* ── Chunk Size (auto_loop only) ── */}
      {config.extraction_mode === 'auto_loop' && (
        <div className="space-y-3 animate-in fade-in slide-in-from-top-1 duration-300">
          <label className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">
            Pages per Chunk
          </label>
          <div className="flex gap-2 flex-wrap">
            {CHUNK_SIZES.map(n => (
              <button
                key={n}
                id={`chunk-${n}`}
                type="button"
                onClick={() => setConfig({ chunk_size: n })}
                className={`px-4 py-2 rounded-xl text-sm font-bold border-2 transition-all ${
                  config.chunk_size === n
                    ? 'border-primary bg-primary text-on-primary shadow-[0_0_12px_rgba(76,215,246,0.3)]'
                    : 'border-outline-variant/20 bg-surface-container-low text-on-surface hover:border-primary/40'
                }`}
              >
                {n}
              </button>
            ))}
          </div>
          <p className="text-[10px] text-outline px-1">
            Pattern sent to backend: <span className="font-mono text-primary">{config.chunk_size}-{config.chunk_size}-{config.chunk_size}</span>
            {' '}· Each chunk = 1 LLM call
          </p>
        </div>
      )}

      {/* ── Page Subset (single_batch only) ── */}
      {config.extraction_mode === 'single_batch' && (
        <div className="space-y-2 animate-in fade-in slide-in-from-top-1 duration-300">
          <label className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">
            Page Subset <span className="normal-case font-normal text-outline/60">(optional)</span>
          </label>
          <input
            id="input-step2-page-range"
            type="text"
            value={config.page_range}
            onChange={e => setConfig({ page_range: e.target.value })}
            placeholder="blank = all pages"
            className="w-full bg-surface-container-lowest border border-outline-variant/20 rounded-xl px-4 py-3 text-sm focus:border-primary outline-none transition-all font-mono"
          />
          <p className="text-[10px] text-outline px-1">
            Examples: <span className="font-mono">1-5</span> · <span className="font-mono">3-7</span> · blank = all pages
          </p>
        </div>
      )}

      {/* ── Models ── */}
      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-2">
          <label className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">Primary Model</label>
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
          <label className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">Fallback Model</label>
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
