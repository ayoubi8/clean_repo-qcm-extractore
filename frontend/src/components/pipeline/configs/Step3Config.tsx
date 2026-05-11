import { usePipelineStore } from '../../../store/pipelineStore'
import { useStepModels } from '../../../hooks/useStepModels'
import { useState, useEffect } from 'react'
import { MetaStrategy } from '../../../types'

const STRATEGIES: Record<string, { label: string, icon: string, color: string, order: MetaStrategy[] }> = {
  default: {
    label: 'Standard',
    icon: 'settings',
    color: 'bg-surface-container-highest text-outline',
    order: ['skip', 'global', 'per_qcm']
  },
  clinical_case: {
    label: 'Clinical',
    icon: 'group',
    color: 'bg-tertiary-container/10 text-tertiary',
    order: ['skip', 'per_group', 'global']
  }
}

const STRATEGY_STYLING: Record<MetaStrategy, { label: string, icon: string, style: string }> = {
  skip: { label: 'Skip', icon: 'block', style: 'bg-surface-container-highest text-outline border-outline-variant/20' },
  global: { label: 'Global', icon: 'public', style: 'bg-primary/10 text-primary border-primary/30' },
  per_qcm: { label: 'Per-QCM', icon: 'neurology', style: 'bg-secondary-container/30 text-secondary border-secondary/30' },
  per_group: { label: 'Per-Group', icon: 'group', style: 'bg-tertiary-container/10 text-tertiary border-tertiary/30' }
}

function CycleButton({ field, strategy, onCycle }: { field: string, strategy: MetaStrategy, onCycle: () => void }) {
  const meta = STRATEGY_STYLING[strategy]
  
  return (
    <button
      id={`btn-cycle-${field}`}
      onClick={onCycle}
      className={`flex items-center gap-2 px-4 py-2 rounded-lg border text-xs font-bold transition-all w-32 justify-center ${meta.style}`}
    >
      <span className="material-symbols-outlined text-[16px]">{meta.icon}</span>
      {meta.label}
    </button>
  )
}

export function Step3Config({ embedded }: { embedded?: boolean }) {
  const config = usePipelineStore(s => s.step3Config)
  const setConfig = usePipelineStore(s => s.setStep3Config)
  const { models, loading } = useStepModels()
  const [isCustom, setIsCustom] = useState(false)
  const [isCustomFallback, setIsCustomFallback] = useState(false)

  // Seed models from .env on first load
  useEffect(() => {
    if (!loading && models?.step3) {
      if (!config.model && models.step3.primary)
        setConfig({ model: models.step3.primary })
      if (!config.model_fallback && models.step3.fallback)
        setConfig({ model_fallback: models.step3.fallback })
    }
  }, [loading, models])

  const handleCycle = (field: keyof typeof config.fields) => {
    const order = field === 'clinical_case' ? STRATEGIES.clinical_case.order : STRATEGIES.default.order
    const currentIndex = order.indexOf(config.fields[field].strategy)
    const nextStrategy = order[(currentIndex + 1) % order.length]
    
    setConfig({
      fields: {
        ...config.fields,
        [field]: { ...config.fields[field], strategy: nextStrategy }
      }
    })
  }

  const showGlobalPanel = Object.values(config.fields).some(f => f.strategy === 'global')

  return (
    <div className="space-y-8 animate-in fade-in slide-in-from-bottom-2 duration-300">
      {/* Model Selection */}
      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-2">
          <label className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">Reasoning Model</label>
          <select
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
            {loading ? <option>Loading models...</option> : (
              <>
                <option value={models?.step3?.primary}>{models?.step3?.primary} (Primary)</option>
                <option value={models?.step3?.fallback}>{models?.step3?.fallback} (Fallback)</option>
                <option value="custom">Custom...</option>
              </>
            )}
          </select>
          {isCustom && (
            <input
              type="text"
              value={config.model}
              onChange={(e) => setConfig({ model: e.target.value })}
              placeholder="Enter model ID..."
              className="w-full mt-2 bg-surface-container-lowest border border-outline-variant/20 rounded-xl px-4 py-3 text-sm focus:border-primary outline-none transition-all animate-in fade-in"
            />
          )}
        </div>

        <div className="space-y-2">
          <label className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">Fallback Model</label>
          <select
            id="select-step3-model-fallback"
            value={isCustomFallback ? 'custom' : config.model_fallback}
            onChange={(e) => {
              if (e.target.value === 'custom') {
                setIsCustomFallback(true);
              } else {
                setIsCustomFallback(false);
                setConfig({ model_fallback: e.target.value });
              }
            }}
            disabled={loading}
            className="w-full bg-surface-container-lowest border border-outline-variant/20 rounded-xl px-4 py-3 text-sm focus:border-primary outline-none transition-all appearance-none disabled:opacity-50"
          >
            {loading ? <option>Loading models...</option> : (
              <>
                <option value={models?.step3?.primary}>{models?.step3?.primary}</option>
                <option value={models?.step3?.fallback}>{models?.step3?.fallback} (Fallback)</option>
                <option value="custom">Custom...</option>
              </>
            )}
          </select>
          {isCustomFallback && (
            <input
              type="text"
              value={config.model_fallback}
              onChange={(e) => setConfig({ model_fallback: e.target.value })}
              placeholder="Enter model ID..."
              className="w-full mt-2 bg-surface-container-lowest border border-outline-variant/20 rounded-xl px-4 py-3 text-sm focus:border-primary outline-none transition-all animate-in fade-in"
            />
          )}
        </div>
      </div>

      {/* Strategy Table */}
      <div className="space-y-3">
        <label className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">Metadata Strategies</label>
        <div className="bg-surface-container-low rounded-2xl border border-outline-variant/10 divide-y divide-outline-variant/5">
          {(Object.keys(config.fields) as Array<keyof typeof config.fields>).map((field) => (
            <div key={field} className="flex items-center justify-between p-4">
              <span className="text-sm font-bold capitalize text-on-surface-variant w-32">{field.replace('_', ' ')}</span>
              <CycleButton 
                field={field} 
                strategy={config.fields[field].strategy} 
                onCycle={() => handleCycle(field)} 
              />
            </div>
          ))}
        </div>
      </div>

      {/* Global Panel */}
      {showGlobalPanel && (
        <div className="space-y-4 p-6 bg-primary/5 rounded-2xl border border-primary/20 animate-in zoom-in-95 duration-300">
          <div className="space-y-2">
            <label className="text-[10px] font-black uppercase tracking-[0.2em] text-primary">Global Pages</label>
            <input
              type="text"
              value={config.global_pages}
              onChange={(e) => setConfig({ global_pages: e.target.value })}
              placeholder="1 or 1,11"
              className="w-full bg-surface-container-lowest border border-primary/20 rounded-xl px-4 py-3 text-sm focus:border-primary outline-none text-primary"
            />
          </div>

          {(Object.keys(config.fields) as Array<keyof typeof config.fields>).map((field) => (
            config.fields[field].strategy === 'global' && (
              <div key={field} className="space-y-2">
                <label className="text-[10px] font-black uppercase tracking-[0.2em] text-primary">{field} Value</label>
                <input
                  type="text"
                  value={config.fields[field].value || ''}
                  onChange={(e) => setConfig({
                    fields: {
                      ...config.fields,
                      [field]: { ...config.fields[field], value: e.target.value }
                    }
                  })}
                  placeholder={`Global ${field}...`}
                  className="w-full bg-surface-container-lowest border border-primary/20 rounded-xl px-4 py-3 text-sm focus:border-primary outline-none text-primary"
                />
              </div>
            )
          ))}
        </div>
      )}

      {/* YAML Preview */}
      {!embedded && (
        <div className="space-y-2">
          <label className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">YAML Preview</label>
          <div className="bg-surface-container-lowest border-l-4 border-primary/40 font-mono text-[11px] p-6 rounded-r-2xl leading-relaxed shadow-xl">
            <div className="text-primary">metadata:</div>
            <div className="ml-4 text-primary">fields:</div>
            {Object.entries(config.fields).map(([field, f]) => (
              <div key={field} className="ml-8">
                <span className="text-tertiary">{field}:</span>{' '}
                <span className="text-on-surface-variant">
                  {f.strategy}{f.strategy === 'global' ? `  →  value: ${f.value || 'null'}` : ''}
                </span>
              </div>
            ))}
            <div className="ml-4">
              <span className="text-primary">global_pages:</span>{' '}
              <span className="text-on-surface-variant">[{config.global_pages.split(',').map(p => p.trim()).join(', ')}]</span>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
