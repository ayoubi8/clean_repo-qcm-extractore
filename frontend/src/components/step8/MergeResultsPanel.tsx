import { useEffect, useState } from 'react'
import { fetchStep8MergeOutputs, Step8MergeManifest, downloadAuthenticatedFile } from '../../lib/api'

const BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

function getAuthHeaders(): Record<string, string> {
  const token = localStorage.getItem('qcm_token')
  return token ? { Authorization: `Bearer ${token}` } : {}
}

interface TierRow {
  key: string
  label: string
}
const TIER_ROWS: TierRow[] = [
  { key: '100',   label: '100% (exact)' },
  { key: '99',    label: '99% (near-exact)' },
  { key: '98',    label: '98%' },
  { key: '95_97', label: '95–97%' },
]

export function MergeResultsPanel({ projectName }: { projectName: string }) {
  const [data, setData] = useState<Step8MergeManifest | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showAudit, setShowAudit] = useState(false)
  const [audit, setAudit] = useState<any[] | null>(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const m = await fetchStep8MergeOutputs(projectName)
        if (!cancelled) setData(m)
      } catch (e: any) {
        if (!cancelled) setError(e.message || 'load failed')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
  }, [projectName])

  if (loading) {
    return (
      <div className="mt-8 pt-8 border-t border-outline-variant/10 text-[10px] uppercase font-bold tracking-widest text-outline animate-pulse">
        Loading merge results…
      </div>
    )
  }
  if (error || !data) return null

  const merge = data.summary?.merge
  // No merge block → Step 8 hasn't run with the new tag-merge phase yet.
  if (!merge) return null

  const totalMerges = merge.total_merges ?? 0
  const totalDeletions = merge.total_deletions ?? 0
  const totalUnmerged = merge.total_unmerged ?? 0
  const isSelfScan = merge.self_scan

  const download = (filename: string | null | undefined) => {
    if (!filename) return
    const url = `${BASE}/projects/${encodeURIComponent(projectName)}/steps/8/download/${encodeURIComponent(filename)}`
    downloadAuthenticatedFile(url, filename).catch(() => alert('Download failed'))
  }

  const loadAudit = async () => {
    if (audit) {
      setShowAudit(!showAudit)
      return
    }
    try {
      const res = await fetch(
        `${BASE}/projects/${encodeURIComponent(projectName)}/steps/8/download/${encodeURIComponent(merge.merge_report_filename || 'merge_report.json')}`,
        { headers: getAuthHeaders() },
      )
      const json = await res.json()
      setAudit(json.merges || [])
      setShowAudit(true)
    } catch {
      alert('Could not load merge report.')
    }
  }

  return (
    <div className="mt-8 pt-8 border-t border-outline-variant/10 animate-in fade-in duration-500">
      <div className="flex items-center gap-2 mb-4">
        <span className="material-symbols-outlined text-primary text-sm">merge_type</span>
        <label className="text-[10px] uppercase tracking-widest text-outline font-black">
          Tag-Merge &amp; Auto-Dedup Results
        </label>
        {isSelfScan && (
          <span className="px-2 py-0.5 rounded-full bg-primary/10 text-primary text-[9px] font-black uppercase tracking-widest">
            Self-Scan
          </span>
        )}
      </div>

      {/* Summary header */}
      <div className="grid grid-cols-3 gap-3 mb-4">
        <div className="p-3 rounded-xl bg-primary/5 border border-primary/20 text-center">
          <p className="text-xl font-black text-primary">{totalMerges}</p>
          <p className="text-[10px] text-outline uppercase tracking-widest">Merges</p>
        </div>
        <div className="p-3 rounded-xl bg-amber-500/5 border border-amber-500/20 text-center">
          <p className="text-xl font-black text-amber-500">{totalDeletions}</p>
          <p className="text-[10px] text-outline uppercase tracking-widest">Deletions</p>
        </div>
        <div className="p-3 rounded-xl bg-surface-container-low border border-outline-variant/10 text-center">
          <p className="text-xl font-black text-on-surface">{isSelfScan ? '—' : totalUnmerged}</p>
          <p className="text-[10px] text-outline uppercase tracking-widest">Unmerged</p>
        </div>
      </div>

      {/* Tier table */}
      {merge.per_tier_stats && Object.keys(merge.per_tier_stats).length > 0 && (
        <div className="mb-4 rounded-xl border border-outline-variant/10 overflow-hidden">
          <table className="w-full text-[11px]">
            <thead>
              <tr className="bg-surface-container-low text-outline uppercase tracking-widest text-[10px]">
                <th className="text-left px-3 py-2 font-black">Tier</th>
                <th className="text-right px-3 py-2 font-black">Merges</th>
                <th className="text-right px-3 py-2 font-black">Deletions</th>
              </tr>
            </thead>
            <tbody>
              {TIER_ROWS.filter(r => merge.per_tier_stats![r.key]).map(r => {
                const ts = merge.per_tier_stats![r.key]
                return (
                  <tr key={r.key} className="border-t border-outline-variant/5">
                    <td className="px-3 py-2 font-mono text-on-surface">{r.label}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-primary font-bold">{ts.merges}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-amber-500 font-bold">{ts.deletions}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Download buttons */}
      <div className="grid grid-cols-1 gap-2">
        <button
          onClick={() => download(merge.ref_updated_filename)}
          disabled={!merge.ref_updated_filename || !data.files.ref_updated}
          className="flex items-center justify-center gap-3 py-3 px-4 bg-surface-container-low border border-outline-variant/30 text-xs font-black uppercase tracking-widest rounded-xl hover:bg-surface-container-high transition-all disabled:opacity-40"
        >
          <span className="material-symbols-outlined text-[18px]">download</span>
          Download {merge.ref_updated_filename ? `${merge.ref_db_name?.replace(/\.[^.]+$/, '') ?? 'reference'}_UPDATED.xlsx` : '_UPDATED.xlsx'}
          <span className="text-outline/40 normal-case font-mono">({data.files.ref_updated ? Math.round(data.files.ref_updated.size_bytes / 1024) : 0} KB)</span>
        </button>

        <button
          onClick={() => download(merge.merge_report_filename)}
          disabled={!merge.merge_report_filename || !data.files.merge_report}
          className="flex items-center justify-center gap-3 py-3 px-4 bg-surface-container-low border border-outline-variant/30 text-xs font-black uppercase tracking-widest rounded-xl hover:bg-surface-container-high transition-all disabled:opacity-40"
        >
          <span className="material-symbols-outlined text-[18px]">download</span>
          Download merge_report.json
          <span className="text-outline/40 normal-case font-mono">({data.files.merge_report ? Math.round(data.files.merge_report.size_bytes / 1024) : 0} KB)</span>
        </button>

        {!isSelfScan && (
          <button
            onClick={() => download(merge.unmerged_filename)}
            disabled={!merge.unmerged_filename || !data.files.unmerged}
            className="flex items-center justify-center gap-3 py-3 px-4 bg-surface-container-low border border-outline-variant/30 text-xs font-black uppercase tracking-widest rounded-xl hover:bg-surface-container-high transition-all disabled:opacity-40"
          >
            <span className="material-symbols-outlined text-[18px]">download</span>
            Download unmerged_qcms.xlsx
            <span className="text-outline/40 normal-case font-mono">({data.files.unmerged ? Math.round(data.files.unmerged.size_bytes / 1024) : 0} KB)</span>
          </button>
        )}
      </div>

      {/* Audit viewer */}
      {totalMerges > 0 && (
        <div className="mt-4">
          <button
            onClick={loadAudit}
            className="flex items-center gap-2 text-[11px] text-primary font-bold hover:text-primary/80 transition-colors"
          >
            <span className="material-symbols-outlined text-[14px]">
              {showAudit ? 'visibility_off' : 'visibility'}
            </span>
            {showAudit ? 'Hide merge audit' : `View merge audit (${totalMerges} pair${totalMerges === 1 ? '' : 's'})`}
          </button>

          {showAudit && audit && (
            <div className="mt-3 space-y-2 max-h-80 overflow-y-auto custom-scrollbar pr-2">
              {audit.map((m, i) => (
                <div key={i} className="p-3 rounded-xl border border-outline-variant/10 bg-surface-container-lowest text-[11px]">
                  <div className="flex items-center justify-between mb-2">
                    <span className="px-1.5 py-0.5 rounded bg-primary/10 text-primary font-mono text-[10px] font-bold">
                      {m.tier}
                    </span>
                    <span className="font-mono tabular-nums text-primary font-bold">
                      {Math.round((m.similarity ?? 0) * 100)}%
                    </span>
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <p className="text-[9px] uppercase tracking-widest text-outline mb-1">Reference</p>
                      <p className="text-on-surface leading-relaxed line-clamp-2">{m.ref_qcm?.Text || '—'}</p>
                      <p className="text-[10px] text-outline mt-1 font-mono">
                        Tags: {Array.isArray(m.old_tag_ref) ? m.old_tag_ref.join(', ') : (m.old_tag_ref || '∅')}
                      </p>
                    </div>
                    <div>
                      <p className="text-[9px] uppercase tracking-widest text-outline mb-1">Source</p>
                      <p className="text-on-surface leading-relaxed line-clamp-2">{m.source_qcm?.Text || '—'}</p>
                      <p className="text-[10px] text-outline mt-1 font-mono">
                        Tags: {Array.isArray(m.old_tag_src) ? m.old_tag_src.join(', ') : (m.old_tag_src || '∅')}
                      </p>
                    </div>
                  </div>
                  <div className="mt-2 pt-2 border-t border-outline-variant/10">
                    <p className="text-[10px] text-outline uppercase tracking-widest mb-0.5">New Tag</p>
                    <p className="font-mono text-primary text-[11px] font-bold">
                      {Array.isArray(m.new_tag) ? m.new_tag.join(', ') : (m.new_tag || '∅')}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}