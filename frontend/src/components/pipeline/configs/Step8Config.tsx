import { usePipelineStore } from '../../../store/pipelineStore'
import { MatchMode } from '../../../types'

const MODES: { id: MatchMode; label: string; desc: string }[] = [
  { id: 'text_only', label: 'Text Only', desc: 'Match on question + options' },
  { id: 'full',      label: 'Full',      desc: 'Includes Correct answer field' },
  { id: 'weighted',  label: 'Weighted',  desc: 'Combine text + answer scores' },
]

export function Step8Config() {
  const config = usePipelineStore(s => s.step8Config)
  const setConfig = usePipelineStore(s => s.setStep8Config)

  return (
    <div className="space-y-8 animate-in fade-in slide-in-from-bottom-2 duration-300">

      {/* Reference DB Path */}
      <div className="space-y-2">
        <label className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">Reference Database Path</label>
        <input
          type="text"
          value={config.ref_db_path}
          onChange={(e) => setConfig({ ref_db_path: e.target.value })}
          placeholder="/app/reference_db.xlsx or /app/reference_db.json"
          className="w-full bg-surface-container-lowest border border-outline-variant/20 rounded-xl px-4 py-3 text-sm font-mono focus:border-primary outline-none transition-all"
        />
        <p className="text-[10px] text-outline">Must be accessible inside the container. Can also be set via REFERENCE_DB_PATH in .env</p>
      </div>

      {/* Match Mode */}
      <div className="space-y-3">
        <label className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">Similarity Mode</label>
        <div className="grid grid-cols-3 gap-2">
          {MODES.map((m) => (
            <div
              key={m.id}
              onClick={() => setConfig({ match_mode: m.id })}
              className={`p-4 rounded-xl border-2 cursor-pointer transition-all flex flex-col gap-1 ${
                config.match_mode === m.id
                  ? 'border-primary bg-primary/5 shadow-[0_0_15px_rgba(76,215,246,0.1)]'
                  : 'border-outline-variant/10 bg-surface-container-low hover:border-outline-variant/30'
              }`}
            >
              <p className={`text-xs font-bold ${config.match_mode === m.id ? 'text-primary' : 'text-on-surface'}`}>{m.label}</p>
              <p className="text-[10px] text-outline leading-tight">{m.desc}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Threshold */}
      <div className="space-y-3 p-5 bg-surface-container-low rounded-2xl border border-outline-variant/10">
        <div className="flex items-center justify-between">
          <label className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">Match Threshold</label>
          <span className="text-sm font-black text-primary">{Math.round(config.threshold * 100)}%</span>
        </div>
        <input
          type="range" min="0" max="100" step="1"
          value={Math.round(config.threshold * 100)}
          onChange={(e) => setConfig({ threshold: parseInt(e.target.value) / 100 })}
          className="w-full accent-primary"
        />
        <div className="flex justify-between text-[10px] text-outline">
          <span>0% (all)</span><span>75% (default)</span><span>100% (exact)</span>
        </div>
      </div>

      {/* Weighted mode controls */}
      {config.match_mode === 'weighted' && (
        <div className="space-y-3 p-5 bg-surface-container-low rounded-2xl border border-outline-variant/10 animate-in slide-in-from-top-2">
          <label className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">Score Weights</label>
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs text-on-surface-variant">Text weight</span>
              <span className="text-sm font-black text-primary">{Math.round(config.text_weight * 100)}%</span>
            </div>
            <input
              type="range" min="0" max="100" step="5"
              value={Math.round(config.text_weight * 100)}
              onChange={(e) => {
                const tw = parseInt(e.target.value) / 100
                setConfig({ text_weight: tw, corr_weight: Math.round((1 - tw) * 100) / 100 })
              }}
              className="w-full accent-primary"
            />
            <div className="flex justify-between text-[10px] text-outline">
              <span>Text: {Math.round(config.text_weight * 100)}%</span>
              <span>Correction: {Math.round(config.corr_weight * 100)}%</span>
            </div>
          </div>
        </div>
      )}

      {/* Color Bands */}
      <div className="grid grid-cols-2 gap-3 p-4 bg-surface-container-low rounded-xl border border-outline-variant/10">
        <div className="space-y-1">
          <label className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">🟢 Green ≥</label>
          <div className="flex items-center gap-2">
            <input
              type="number" min="0" max="100" step="1"
              value={Math.round(config.color_green * 100)}
              onChange={(e) => setConfig({ color_green: parseInt(e.target.value) / 100 })}
              className="w-full bg-surface-container-lowest border border-outline-variant/20 rounded-lg px-3 py-2 text-xs focus:border-primary outline-none"
            />
            <span className="text-xs text-outline">%</span>
          </div>
        </div>
        <div className="space-y-1">
          <label className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">🟡 Yellow ≥</label>
          <div className="flex items-center gap-2">
            <input
              type="number" min="0" max="100" step="1"
              value={Math.round(config.color_yellow * 100)}
              onChange={(e) => setConfig({ color_yellow: parseInt(e.target.value) / 100 })}
              className="w-full bg-surface-container-lowest border border-outline-variant/20 rounded-lg px-3 py-2 text-xs focus:border-primary outline-none"
            />
            <span className="text-xs text-outline">%</span>
          </div>
        </div>
      </div>

      {/* Custom Export Section */}
      <div className="space-y-4 pt-4 border-t border-outline-variant/10">
        <label className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">Custom Export (after run)</label>
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1">
            <label className="text-[10px] text-outline uppercase tracking-widest">From %</label>
            <input type="number" min="0" max="100" step="1"
              value={Math.round(config.export_from * 100)}
              onChange={(e) => setConfig({ export_from: parseInt(e.target.value) / 100 })}
              className="w-full bg-surface-container-lowest border border-outline-variant/20 rounded-lg px-3 py-2 text-xs focus:border-primary outline-none"
            />
          </div>
          <div className="space-y-1">
            <label className="text-[10px] text-outline uppercase tracking-widest">To %</label>
            <input type="number" min="0" max="100" step="1"
              value={Math.round(config.export_to * 100)}
              onChange={(e) => setConfig({ export_to: parseInt(e.target.value) / 100 })}
              className="w-full bg-surface-container-lowest border border-outline-variant/20 rounded-lg px-3 py-2 text-xs focus:border-primary outline-none"
            />
          </div>
        </div>
        <input
          type="text"
          value={config.export_filename}
          onChange={(e) => setConfig({ export_filename: e.target.value })}
          placeholder="custom_export"
          className="w-full bg-surface-container-lowest border border-outline-variant/20 rounded-xl px-4 py-2.5 text-xs focus:border-primary outline-none"
        />
      </div>

    </div>
  )
}
