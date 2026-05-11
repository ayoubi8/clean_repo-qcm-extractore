import { usePipelineStore } from '../../../store/pipelineStore'
import { useStepModels } from '../../../hooks/useStepModels'
import { useAppStore } from '../../../store/appStore'
import { useState, useEffect } from 'react'

export function Step1Config() {
  const config = usePipelineStore(s => s.step1Config)
  const setConfig = usePipelineStore(s => s.setStep1Config)
  const activeProject = useAppStore(s => s.activeProject)
  const { models, loading } = useStepModels()
  const [isCustom, setIsCustom] = useState(false)

  // When models load for the first time and model is blank, seed from .env
  useEffect(() => {
    if (!loading && models?.step1?.primary && !config.model) {
      setConfig({ model: models.step1.primary })
    }
  }, [loading, models])

  return (
    <div className="space-y-8 animate-in fade-in slide-in-from-bottom-2 duration-300">

      {/* PDF Source — shows what file will be processed */}
      <div className="space-y-2">
        <label className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">PDF Source</label>
        <div className={`p-3 rounded-xl border text-[11px] font-mono break-all leading-relaxed ${
          activeProject?.pdf_path
            ? 'bg-surface-container-low border-outline-variant/10 text-on-surface-variant'
            : 'bg-error-container/5 border-error/20 text-error italic'
        }`}>
          {activeProject?.pdf_path
            ? activeProject.pdf_path
            : '⚠ No PDF path — delete and re-create this project to save the path'
          }
        </div>
      </div>

      <div className="space-y-3">
        <label className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">Extraction Method</label>
        <div className="grid grid-cols-1 gap-3">
          {[
            { id: 'pypdfium2', label: 'pypdfium2', sub: 'Fast, digital PDFs (Selectable text)' },
            { id: 'vision_ocr', label: 'Vision OCR', sub: 'Scanned / Image PDFs (Uses Gemini Vision)' }
          ].map((opt) => (
            <div 
              key={opt.id}
              id={`method-${opt.id}`}
              onClick={() => setConfig({ method: opt.id as any })}
              className={`p-4 rounded-xl border-2 cursor-pointer transition-all ${
                config.method === opt.id 
                  ? 'border-primary bg-primary/5 shadow-[0_0_15px_rgba(76,215,246,0.1)]' 
                  : 'border-outline-variant/10 bg-surface-container-low hover:border-outline-variant/30'
              }`}
            >
              <div className="flex items-center justify-between">
                <div>
                  <p className={`text-sm font-bold ${config.method === opt.id ? 'text-primary' : 'text-on-surface'}`}>
                    {opt.label}
                  </p>
                  <p className="text-[11px] text-outline mt-0.5">{opt.sub}</p>
                </div>
                <div className={`w-4 h-4 rounded-full border-2 flex items-center justify-center ${
                  config.method === opt.id ? 'border-primary' : 'border-outline'
                }`}>
                  {config.method === opt.id && <div className="w-2 h-2 bg-primary rounded-full" />}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {config.method === 'vision_ocr' && (
        <div className="space-y-6 animate-in fade-in duration-500">
          <div className="space-y-2">
            <label className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">OCR Guidance</label>
            <textarea
              id="input-step1-ocr-guidance"
              rows={4}
              value={config.ocr_guidance}
              onChange={(e) => setConfig({ ocr_guidance: e.target.value })}
              className="w-full bg-surface-container-lowest border border-outline-variant/20 rounded-xl px-4 py-3 text-sm focus:border-primary outline-none transition-all resize-none custom-scrollbar"
              placeholder="e.g. Preserve two-column layout..."
            />
          </div>

          <div className="space-y-2">
            <label className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">Vision Model</label>
            <div className="relative group">
              <select
                id="select-step1-model"
                value={isCustom ? 'custom' : config.model}
                onChange={(e) => {
                  if (e.target.value === 'custom') {
                    setIsCustom(true);
                  } else {
                    setIsCustom(false);
                    setConfig({ model: e.target.value });
                  }
                }}
                disabled={loading}
                className="w-full bg-surface-container-lowest border border-outline-variant/20 rounded-xl px-4 py-3 text-sm focus:border-primary outline-none transition-all appearance-none disabled:opacity-50"
              >
                {loading ? (
                  <option>Loading models...</option>
                ) : (
                  <>
                    <option value={models?.step1?.primary}>{models?.step1?.primary} (Primary)</option>
                    <option value={models?.step1?.fallback}>{models?.step1?.fallback} (Fallback)</option>
                    <option value="custom">Custom...</option>
                  </>
                )}
              </select>
              <div className="absolute right-4 top-1/2 -translate-y-1/2 pointer-events-none text-outline">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="Step 19 9l-7 7-7-7" />
                </svg>
              </div>
            </div>

            {isCustom && (
              <input
                type="text"
                id="input-step1-custom-model"
                value={config.model}
                onChange={(e) => setConfig({ model: e.target.value })}
                className="w-full mt-2 bg-surface-container-lowest border border-outline-variant/20 rounded-xl px-4 py-3 text-sm focus:border-primary outline-none transition-all animate-in fade-in slide-in-from-top-1"
                placeholder="Enter model ID (e.g. openai/gpt-4o)..."
              />
            )}
          </div>
        </div>
      )}
    </div>
  )
}
