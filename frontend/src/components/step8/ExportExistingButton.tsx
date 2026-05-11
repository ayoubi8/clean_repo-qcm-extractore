import { useState } from 'react'
import { exportExisting } from '../../lib/api'
import { ExportResult } from '../../types'

export function ExportExistingButton({ projectName }: { projectName: string }) {
  const [status, setStatus] = useState<'idle' | 'loading' | 'done' | 'error'>('idle')
  const [result, setResult] = useState<ExportResult | null>(null)

  const handleExport = async () => {
    setStatus('loading')
    try {
      const res = await exportExisting(projectName)
      setResult(res)
      setStatus('done')
    } catch (e) {
      setStatus('error')
    }
  }

  return (
    <div className="mt-8 pt-8 border-t border-outline-variant/10 animate-in fade-in duration-500">
      <div className="flex items-center gap-2 mb-4">
        <span className="material-symbols-outlined text-primary text-sm">history</span>
        <label className="text-[10px] uppercase tracking-widest text-outline font-black">Re-Export (No Re-matching)</label>
      </div>
      
      <p className="text-xs text-on-surface-variant mb-6 leading-relaxed font-medium">
        Re-generate the Excel report from the existing results in <code className="bg-surface-container-highest px-1 rounded">step8_matches.json</code>. 
        This is much faster as it skips similarity calculations.
      </p>

      <button
        id="btn-step8-reexport"
        onClick={handleExport}
        disabled={status === 'loading'}
        className="w-full flex items-center justify-center gap-3 py-4 bg-surface-container-low border border-outline-variant/30 text-on-surface text-xs font-black uppercase tracking-widest rounded-xl hover:bg-surface-container-high transition-all disabled:opacity-40"
      >
        <span className="material-symbols-outlined text-[18px]">
          {status === 'loading' ? 'refresh' : 'download'}
        </span>
        {status === 'loading' ? 'Exporting...' : 'Export XLSX (Option E)'}
      </button>

      {status === 'done' && result && (
        <div className="mt-4 bg-primary/5 border border-primary/20 rounded-xl p-5 animate-in zoom-in-95 duration-300">
          <div className="flex items-center gap-2 text-primary font-bold text-xs mb-2">
            <span className="material-symbols-outlined text-sm">check_circle</span>
            <span>Export complete · {result.record_count} records</span>
          </div>
          <p className="text-[10px] font-mono text-outline truncate bg-surface-container-lowest/50 p-2 rounded border border-outline-variant/5">
            📄 {result.file_path}
          </p>
        </div>
      )}

      {status === 'error' && (
        <div className="mt-4 p-4 bg-error-container/10 border border-error/20 rounded-xl flex items-start gap-3">
          <span className="material-symbols-outlined text-error text-sm mt-0.5">error</span>
          <p className="text-[11px] text-error leading-relaxed font-medium">
            Export failed. Make sure Step 8 similarity matching has been run successfully at least once.
          </p>
        </div>
      )}
    </div>
  )
}
