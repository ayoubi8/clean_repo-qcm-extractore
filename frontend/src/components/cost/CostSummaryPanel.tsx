import { useState, useEffect } from 'react'
import { fetchCosts, saveCosts } from '../../lib/api'
import { CostSummary, ModelCost, StepCost } from '../../types'
import { useAppStore } from '../../store/appStore'

function CostModelRow({ model, data }: { model: string, data: ModelCost }) {
  return (
    <div className="flex items-center gap-4 py-3 border-b border-outline-variant/10 text-sm">
      <span className="flex-1 font-bold text-on-surface truncate capitalize">{model.replace(/_/g, ' ')}</span>
      <span className="w-24 font-mono text-on-surface-variant text-[11px] text-right">{data.tokens.prompt.toLocaleString()}</span>
      <span className="w-24 font-mono text-on-surface-variant text-[11px] text-right">{data.tokens.completion.toLocaleString()}</span>
      <span className="w-20 font-mono text-primary font-bold text-right">${data.cost.toFixed(4)}</span>
    </div>
  )
}

function CostStepRow({ step, data }: { step: string, data: StepCost }) {
  return (
    <div className="flex items-center gap-4 py-3 border-b border-outline-variant/10 text-sm">
      <span className="flex-1 font-bold text-on-surface truncate capitalize">{step}</span>
      <span className="w-16 font-mono text-on-surface-variant text-[11px] text-right">{data.call_count}</span>
      <span className="w-28 font-mono text-on-surface-variant text-[11px] text-right">{(data.total_tokens.prompt + data.total_tokens.completion).toLocaleString()}</span>
      <span className="w-20 font-mono text-primary font-bold text-right">${data.total_cost.toFixed(4)}</span>
    </div>
  )
}

export function CostSummaryPanel({ onClose }: { onClose: () => void }) {
  const activeProject = useAppStore(s => s.activeProject)
  const [summary, setSummary] = useState<CostSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [savedPath, setSavedPath] = useState<string | null>(null)

  useEffect(() => {
    async function load() {
      if (!activeProject) return
      try {
        const data = await fetchCosts(activeProject.name)
        setSummary(data)
      } catch (e) {
        setError('Failed to load cost summary.')
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [activeProject])

  const handleSave = async () => {
    if (!activeProject) return
    setSaving(true)
    try {
      const res = await saveCosts(activeProject.name)
      setSavedPath(res.saved_to)
    } catch (e) {
      setError('Failed to save costs.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-[60] animate-in fade-in duration-300" onClick={onClose} />
      <div className="fixed right-0 top-0 h-full w-[480px] z-[70] bg-surface-container flex flex-col shadow-2xl border-l border-outline-variant/10 animate-in slide-in-from-right duration-500 ease-out">
        
        <div className="px-8 py-8 border-b border-outline-variant/10 flex items-center justify-between bg-surface-container-high/50">
          <div>
            <h2 className="text-2xl font-black text-on-surface tracking-tighter">Cost Summary</h2>
            <p className="text-[11px] text-outline mt-1 font-bold uppercase tracking-widest opacity-60">Usage & Token Reporting</p>
          </div>
          <button onClick={onClose} className="w-10 h-10 rounded-full hover:bg-surface-container-highest flex items-center justify-center transition-colors border border-outline-variant/10">
            <span className="material-symbols-outlined text-outline">close</span>
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-8 py-8 space-y-10 custom-scrollbar">
          {loading ? (
            <div className="space-y-6">
              {[...Array(4)].map((_, i) => (
                <div key={i} className="h-12 bg-surface-container-high rounded-xl animate-pulse" />
              ))}
            </div>
          ) : error ? (
            <div className="p-6 bg-error-container/10 border border-error/20 rounded-xl text-center">
              <p className="text-error text-sm font-bold">{error}</p>
            </div>
          ) : summary && (
            <>
              {/* Models Table */}
              <section className="space-y-4">
                <div className="flex items-center gap-2 mb-2">
                  <span className="material-symbols-outlined text-primary text-sm">smart_toy</span>
                  <label className="text-[10px] uppercase tracking-widest text-outline font-black">Consumption per Model</label>
                </div>
                <div className="flex items-center gap-4 pb-2 border-b-2 border-outline-variant/20 text-[9px] font-black uppercase tracking-widest text-outline">
                  <span className="flex-1">Model</span>
                  <span className="w-24 text-right">Prompt</span>
                  <span className="w-24 text-right">Compl.</span>
                  <span className="w-20 text-right">Cost</span>
                </div>
                {Object.entries(summary.per_model).map(([model, data]) => (
                  <CostModelRow key={model} model={model} data={data} />
                ))}
              </section>

              {/* Steps Table */}
              <section className="space-y-4">
                <div className="flex items-center gap-2 mb-2">
                  <span className="material-symbols-outlined text-primary text-sm">account_tree</span>
                  <label className="text-[10px] uppercase tracking-widest text-outline font-black">Consumption per Step</label>
                </div>
                <div className="flex items-center gap-4 pb-2 border-b-2 border-outline-variant/20 text-[9px] font-black uppercase tracking-widest text-outline">
                  <span className="flex-1">Step</span>
                  <span className="w-16 text-right">Calls</span>
                  <span className="w-28 text-right">Tokens</span>
                  <span className="w-20 text-right">Cost</span>
                </div>
                {Object.entries(summary.per_step).map(([step, data]) => (
                  <CostStepRow key={step} step={step} data={data} />
                ))}
              </section>

              {/* Total Footer */}
              <div className="bg-surface-container-lowest p-6 rounded-2xl border border-outline-variant/20 shadow-xl">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-black text-on-surface uppercase tracking-[0.2em]">TOTAL ESTIMATED</span>
                  <span className="font-mono text-2xl font-black text-primary">${summary.total_cost.toFixed(4)}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-[10px] text-outline font-medium">TOTAL TOKENS PROCESSED</span>
                  <span className="text-[10px] font-mono text-on-surface-variant">{summary.total_tokens.toLocaleString()} tokens</span>
                </div>
              </div>
            </>
          )}
        </div>

        <div className="px-8 py-8 bg-surface-container-high/80 backdrop-blur-xl border-t border-outline-variant/10">
          <button
            id="btn-save-costs"
            onClick={handleSave}
            disabled={saving || !summary}
            className={`w-full h-14 rounded-2xl font-black uppercase tracking-widest flex items-center justify-center gap-3 transition-all ${
              savedPath 
                ? 'bg-primary/10 text-primary border border-primary/20' 
                : 'bg-surface-container-highest text-on-surface border border-outline-variant/20 hover:bg-surface-container-highest/80'
            }`}
          >
            {saving ? (
              <span className="material-symbols-outlined animate-spin">refresh</span>
            ) : (
              <span className="material-symbols-outlined">{savedPath ? 'check_circle' : 'save'}</span>
            )}
            {savedPath ? 'Saved to Project Folder' : 'Save to total_costs.json'}
          </button>
          {savedPath && (
            <p className="text-[9px] font-mono text-outline mt-3 truncate text-center px-4">
              📄 {savedPath}
            </p>
          )}
        </div>
      </div>
    </>
  )
}
