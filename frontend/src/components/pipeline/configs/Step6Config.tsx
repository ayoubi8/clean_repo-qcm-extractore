import { usePipelineStore } from '../../../store/pipelineStore'
import { useStepModels } from '../../../hooks/useStepModels'
import { useState, useEffect } from 'react'
import { CorrectionSource, SearchMode } from '../../../types'

const SOURCES: { id: CorrectionSource, label: string, icon: string, desc: string }[] = [
  { id: 'ai_knowledge', label: 'AI Knowledge', icon: 'psychology', desc: 'DeepSeek R1 answers from memory' },
  { id: 'page_text', label: 'Page Text', icon: 'description', desc: 'Extract from specific page' },
  { id: 'auto_detect', label: 'Auto-Detect', icon: 'search', desc: 'Scan for correction tables' },
  { id: 'vision_ai', label: 'Vision AI', icon: 'visibility', desc: 'Detect marks in scanned PDF' },
]

export function Step6Config() {
  const config = usePipelineStore(s => s.step6Config)
  const setConfig = usePipelineStore(s => s.setStep6Config)
  const { models, loading } = useStepModels()
  const [isCustom, setIsCustom] = useState(false)

  // Seed models from .env on first load
  useEffect(() => {
    if (!loading && models?.step6) {
      if (!config.ai_model && models.step6.ai_model)
        setConfig({ ai_model: models.step6.ai_model })
      if (!config.text_model && models.step6.text_model)
        setConfig({ text_model: models.step6.text_model })
      if (!config.all_pages_model && models.step6.all_pages_model)
        setConfig({ all_pages_model: models.step6.all_pages_model })
    }
  }, [loading, models])

  // Determine which model to show/edit based on source
  const getModelId = () => {
    if (config.source === 'ai_knowledge') return config.ai_model || '';
    if (config.source === 'vision_ai') return config.vision_model || '';
    return config.text_model || '';
  };

  const setModelId = (val: string) => {
    if (config.source === 'ai_knowledge') setConfig({ ai_model: val });
    else if (config.source === 'vision_ai') setConfig({ vision_model: val });
    else setConfig({ text_model: val });
  };

  const getModelOptions = () => {
    if (!models?.step6) return [];
    if (config.source === 'ai_knowledge') return [models.step6.ai_model];
    if (config.source === 'vision_ai') return [models.step6.all_pages_model];
    return [models.step6.text_model, models.step6.text_fallback];
  };

  const activeModels = getModelOptions();

  return (
    <div className="space-y-8 animate-in fade-in slide-in-from-bottom-2 duration-300">
      {/* Source Grid */}
      <div className="space-y-3">
        <label className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">Correction Source</label>
        <div className="grid grid-cols-2 gap-3">
          {SOURCES.map((s) => (
            <div
              key={s.id}
              onClick={() => {
                setConfig({ source: s.id });
                setIsCustom(false);
              }}
              className={`p-4 rounded-xl border-2 cursor-pointer transition-all flex flex-col gap-2 ${
                config.source === s.id 
                  ? 'border-primary bg-primary/5 shadow-[0_0_15px_rgba(76,215,246,0.1)]' 
                  : 'border-outline-variant/10 bg-surface-container-low hover:border-outline-variant/30'
              }`}
            >
              <span className={`material-symbols-outlined text-2xl ${config.source === s.id ? 'text-primary' : 'text-outline'}`}>
                {s.icon}
              </span>
              <div>
                <p className={`text-xs font-bold ${config.source === s.id ? 'text-primary' : 'text-on-surface'}`}>
                  {s.label}
                </p>
                <p className="text-[10px] text-outline mt-0.5 leading-tight">{s.desc}</p>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Model Selection */}
      <div className="space-y-2 p-5 bg-surface-container-low rounded-2xl border border-outline-variant/10">
        <label className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">
          {config.source === 'ai_knowledge' ? 'Reasoning Model' : config.source === 'vision_ai' ? 'Vision Model' : 'Extraction Model'}
        </label>
        <select
          value={isCustom ? 'custom' : getModelId()}
          onChange={(e) => {
            if (e.target.value === 'custom') {
              setIsCustom(true);
            } else {
              setIsCustom(false);
              setModelId(e.target.value);
            }
          }}
          disabled={loading}
          className="w-full bg-surface-container-lowest border border-outline-variant/20 rounded-xl px-4 py-2.5 text-xs focus:border-primary outline-none transition-all appearance-none disabled:opacity-50"
        >
          {loading ? <option>Loading...</option> : (
            <>
              {activeModels.map(m => m && <option key={m} value={m}>{m}</option>)}
              <option value="custom">Custom...</option>
            </>
          )}
        </select>
        {isCustom && (
          <input
            type="text"
            value={getModelId()}
            onChange={(e) => setModelId(e.target.value)}
            placeholder="Model ID..."
            className="w-full mt-2 bg-surface-container-lowest border border-outline-variant/20 rounded-xl px-4 py-2.5 text-xs focus:border-primary outline-none animate-in fade-in"
          />
        )}
      </div>

      {/* Conditional Fields */}
      <div className="space-y-6">
        {config.source === 'ai_knowledge' && (
          <div className="space-y-3 p-5 bg-surface-container-low rounded-2xl border border-outline-variant/10">
            <label className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">AI Mode</label>
            <div className="flex gap-2 p-1 bg-surface-container-lowest rounded-xl border border-outline-variant/20">
              {['sequential', 'batch'].map((mode) => (
                <button
                  key={mode}
                  onClick={() => setConfig({ ai_mode: mode as any })}
                  className={`flex-1 py-2 text-xs font-bold rounded-lg capitalize transition-all ${
                    config.ai_mode === mode 
                      ? 'bg-primary text-on-primary shadow-lg' 
                      : 'text-outline hover:text-on-surface'
                  }`}
                >
                  {mode}
                </button>
              ))}
            </div>
          </div>
        )}


        {config.source === 'page_text' && (
          <div className="space-y-2">
            <label className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">Page Reference</label>
            <input
              type="text"
              value={config.pages || ''}
              onChange={(e) => setConfig({ pages: e.target.value })}
              placeholder="e.g. 11 or path/to/page.txt"
              className="w-full bg-surface-container-lowest border border-outline-variant/20 rounded-xl px-4 py-3 text-sm focus:border-primary outline-none transition-all"
            />
          </div>
        )}

        {(config.source === 'page_text' || config.source === 'auto_detect') && (
          <div className="space-y-2">
            <label className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">Extraction Guidance (Optional)</label>
            <textarea
              value={config.page_text_guidance || ''}
              onChange={(e) => setConfig({ page_text_guidance: e.target.value })}
              placeholder="e.g. Focus on rows with X marks in columns A-E..."
              rows={2}
              className="w-full bg-surface-container-lowest border border-outline-variant/20 rounded-xl px-4 py-3 text-sm focus:border-primary outline-none transition-all resize-none"
            />
          </div>
        )}

        {config.source === 'vision_ai' && (
          <div className="space-y-2">
            <label className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">Vision Prompt</label>
            <textarea
              rows={2}
              value={config.vision_prompt || ''}
              onChange={(e) => setConfig({ vision_prompt: e.target.value })}
              placeholder="Detect circled propositions..."
              className="w-full bg-surface-container-lowest border border-outline-variant/20 rounded-xl px-4 py-3 text-sm focus:border-primary outline-none transition-all resize-none"
            />
          </div>
        )}
      </div>

      {/* Search Mode */}
      <div className="space-y-4 pt-4 border-t border-outline-variant/10">
        <div className="space-y-3">
          <label className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">Search Mode</label>
          <div className="flex gap-2">
            {[
              { id: 'all_pages', label: 'All Pages Scan' },
              { id: 'specific_pages', label: 'Specific Pages' }
            ].map((m) => (
              <button
                key={m.id}
                onClick={() => setConfig({ correction_search_mode: m.id as SearchMode })}
                className={`flex-1 py-3 text-xs font-bold rounded-xl border transition-all ${
                  config.correction_search_mode === m.id 
                    ? 'border-primary bg-primary/10 text-primary' 
                    : 'border-outline-variant/20 bg-surface-container-low text-outline hover:text-on-surface'
                }`}
              >
                {m.label}
              </button>
            ))}
          </div>
        </div>

        {config.correction_search_mode === 'specific_pages' && (
          <div className="space-y-2 animate-in slide-in-from-top-2">
            <label className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">Pages</label>
            <input
              type="text"
              value={config.pages || ''}
              onChange={(e) => setConfig({ pages: e.target.value })}
              placeholder="4,5,6,7"
              className="w-full bg-surface-container-lowest border border-outline-variant/20 rounded-xl px-4 py-3 text-sm focus:border-primary outline-none transition-all"
            />
          </div>
        )}

        {(config.source === 'auto_detect' || config.correction_search_mode === 'all_pages') && (
          <div className="grid grid-cols-2 gap-3 p-4 bg-surface-container-low rounded-xl border border-outline-variant/10">
            <div className="space-y-1">
              <label className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">Candidate Threshold</label>
              <input 
                type="number" 
                min="5" 
                max="50"
                value={config.candidate_threshold}
                onChange={(e) => setConfig({ candidate_threshold: parseInt(e.target.value) })}
                className="w-full bg-surface-container-lowest border border-outline-variant/20 rounded-lg px-3 py-2 text-xs focus:border-primary outline-none"
              />
            </div>
            <div className="flex items-center justify-between">
              <div className="space-y-0.5">
                <label className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">Include Neighbors</label>
                <p className="text-[9px] text-outline leading-tight">Scan adjacent pages</p>
              </div>
              <button
                onClick={() => setConfig({ include_neighbors: !config.include_neighbors })}
                className={`w-10 h-6 rounded-full transition-all ${config.include_neighbors ? 'bg-primary' : 'bg-outline-variant/30'}`}
              >
                <div className={`w-4 h-4 bg-white rounded-full mx-1 transition-all ${config.include_neighbors ? 'translate-x-4' : ''}`} />
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Force Overwrite */}
      <div className="flex items-center justify-between p-4 bg-surface-container-low rounded-xl border border-outline-variant/10">
        <div>
          <p className="text-xs font-bold text-on-surface">Force Re-extract</p>
          <p className="text-[10px] text-outline">Overwrite existing corrections from previous runs</p>
        </div>
        <button
          onClick={() => setConfig({ force_overwrite: !config.force_overwrite })}
          className={`w-10 h-6 rounded-full transition-all ${config.force_overwrite ? 'bg-error' : 'bg-outline-variant/30'}`}
        >
          <div className={`w-4 h-4 bg-white rounded-full mx-1 transition-all ${config.force_overwrite ? 'translate-x-4' : ''}`} />
        </button>
      </div>
    </div>
  )
}
