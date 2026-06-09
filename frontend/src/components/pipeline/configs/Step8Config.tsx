import { useState, useEffect } from 'react'
import { usePipelineStore } from '../../../store/pipelineStore'
import { MatchMode } from '../../../types'
import { fetchRefDbs, uploadRefDb, deleteRefDb } from '../../../lib/api'

// Helper for formatting file size
const formatBytes = (bytes: number) => {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

const MODES: { id: MatchMode; label: string; desc: string }[] = [
  { id: 'text_only', label: 'Text Only', desc: 'Match on question + options' },
  { id: 'full',      label: 'Full',      desc: 'Includes Correct answer field' },
  { id: 'weighted',  label: 'Weighted',  desc: 'Combine text + answer scores' },
]

export function Step8Config() {
  const config = usePipelineStore(s => s.step8Config)
  const setConfig = usePipelineStore(s => s.setStep8Config)

  const [files, setFiles] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const loadFiles = async () => {
    setLoading(true)
    setError(null)
    try {
      const list = await fetchRefDbs()
      setFiles(list)
    } catch (err: any) {
      setError(err.message || 'Failed to load reference files')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadFiles()
  }, [])

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    setError(null)
    try {
      const newRecord = await uploadRefDb(file)
      setFiles(prev => [...prev, newRecord])
      setConfig({ ref_db_path: newRecord.filename })
    } catch (err: any) {
      setError(err.message || 'Upload failed')
    } finally {
      setUploading(false)
      if (e.target) e.target.value = ''
    }
  }

  const handleDelete = async (id: string, filename: string, e: React.MouseEvent) => {
    e.stopPropagation()
    if (!confirm(`Are you sure you want to delete "${filename}"?`)) return
    try {
      await deleteRefDb(id)
      setFiles(prev => prev.filter(f => f.id !== id))
      if (config.ref_db_path === filename) {
        setConfig({ ref_db_path: '' })
      }
    } catch (err: any) {
      setError(err.message || 'Delete failed')
    }
  }

  return (
    <div className="space-y-8 animate-in fade-in slide-in-from-bottom-2 duration-300">

      {/* Reference DB Section */}
      <div className="space-y-3">
        <div className="flex justify-between items-center">
          <label className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">
            Reference Database ({files.length}/5)
          </label>
          {loading && (
            <span className="text-[10px] text-primary flex items-center gap-1.5 animate-pulse">
              <svg className="animate-spin h-3.5 w-3.5 text-primary" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
              </svg>
              Syncing...
            </span>
          )}
        </div>

        {error && (
          <div className="bg-red-950/40 border border-red-500/20 text-red-400 text-xs px-4 py-2.5 rounded-xl">
            {error}
          </div>
        )}

        {/* Files Grid */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {files.map((file) => {
            const isSelected = config.ref_db_path === file.filename
            return (
              <div
                key={file.id}
                onClick={() => setConfig({ ref_db_path: file.filename })}
                className={`p-4 rounded-2xl border-2 transition-all flex flex-col gap-2 relative cursor-pointer group ${
                  isSelected
                    ? 'border-primary bg-primary/5 shadow-[0_0_15px_rgba(76,215,246,0.1)]'
                    : 'border-outline-variant/10 bg-surface-container-low hover:border-outline-variant/30'
                }`}
              >
                {/* Checkmark indicator */}
                <div className={`absolute top-3 right-3 w-5 h-5 rounded-full border-2 flex items-center justify-center transition-all ${
                  isSelected ? 'border-primary bg-primary text-black' : 'border-outline-variant/30'
                }`}>
                  {isSelected && (
                    <svg className="w-3.5 h-3.5 text-black" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="3">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                    </svg>
                  )}
                </div>

                {/* File Details */}
                <div className="flex items-center gap-3 pr-6">
                  <div className={`p-2 rounded-xl ${isSelected ? 'bg-primary/20 text-primary' : 'bg-surface-container-lowest text-outline'}`}>
                    <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4" />
                    </svg>
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="text-xs font-bold text-on-surface truncate" title={file.filename}>
                      {file.filename}
                    </p>
                    <p className="text-[10px] text-outline mt-0.5">
                      {formatBytes(file.size_bytes)} • {file.line_count} rows
                    </p>
                  </div>
                </div>

                {/* Actions */}
                <div className="flex justify-end items-center mt-2 pt-2 border-t border-outline-variant/5">
                  <button
                    onClick={(e) => handleDelete(file.id, file.filename, e)}
                    className="p-1.5 rounded-lg text-outline hover:text-red-400 hover:bg-red-500/10 transition-all"
                    title="Delete reference database"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                    </svg>
                  </button>
                </div>
              </div>
            )
          })}

          {/* Import / Upload Button Card */}
          {files.length < 5 && (
            <label className="p-5 rounded-2xl border-2 border-dashed border-outline-variant/20 bg-surface-container-low/40 hover:border-primary/40 hover:bg-primary/5 transition-all flex flex-col items-center justify-center gap-2 cursor-pointer h-[132px] group">
              <input
                type="file"
                onChange={handleUpload}
                accept=".xlsx,.xls,.json"
                className="hidden"
                disabled={uploading}
              />
              {uploading ? (
                <>
                  <svg className="animate-spin h-6 w-6 text-primary" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
                  </svg>
                  <span className="text-[10px] font-black uppercase tracking-widest text-primary mt-1">Uploading...</span>
                </>
              ) : (
                <>
                  <div className="p-2 rounded-xl bg-surface-container-lowest text-outline group-hover:text-primary group-hover:bg-primary/10 transition-all">
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
                    </svg>
                  </div>
                  <span className="text-[10px] font-black uppercase tracking-widest text-outline group-hover:text-primary transition-all">
                    Import Database
                  </span>
                  <span className="text-[8px] text-outline/60 uppercase">Excel or JSON</span>
                </>
              )}
            </label>
          )}
        </div>

        {files.length === 0 && !loading && (
          <div className="p-6 text-center rounded-2xl border border-outline-variant/10 bg-surface-container-low text-outline text-xs">
            ⚠️ No reference databases uploaded yet. Upload at least one Excel/JSON file to proceed.
          </div>
        )}
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
