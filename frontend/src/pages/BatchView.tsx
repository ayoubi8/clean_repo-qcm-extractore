import { useEffect, useReducer, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useBatchStore, batchActive } from '../store/batchStore'
import { resumeBatch } from '../lib/api'
import { BatchFolderCard } from '../components/batch/BatchFolderCard'
import { BatchDetailPanel } from '../components/batch/BatchDetailPanel'

/**
 * Auto Run batch cockpit (plan docs/plans/autorun-batch-plan.md §3.3):
 * a folder card per PDF in a responsive grid with live per-step progress;
 * clicking a card expands the detail panel IN PLACE (col-span-full inside the
 * same grid) so finished folders are inspectable while others still run.
 *
 * Phase 2: polling lives in batchStore (self-scheduling chain that cannot die
 * on a failed poll — backoff + "reconnecting…" hint); this view only owns its
 * lifecycle (mount → start, unmount → stop) and a 1s "updated Ns ago" ticker.
 */

const STATE_CHIP: Record<string, { label: string; cls: string }> = {
  pending:   { label: 'Queued',          cls: 'bg-surface-container-high text-outline border-outline/10' },
  running:   { label: 'Running',         cls: 'bg-primary-container/20 text-primary border-primary/30' },
  done:      { label: 'Completed',       cls: 'bg-primary/10 text-primary border-primary/40' },
  done_with_errors: { label: 'Done with errors', cls: 'bg-secondary-container/20 text-secondary border-secondary/30' },
  interrupted: { label: 'Interrupted',  cls: 'bg-secondary-container/20 text-secondary border-secondary/30' },
  error:     { label: 'Failed',          cls: 'bg-error-container/10 text-error border-error/30' },
}

function UpdatedAgo({ ts }: { ts: number | null }) {
  const [, force] = useReducer((x: number) => x + 1, 0)
  useEffect(() => {
    const timer = window.setInterval(force, 1000)
    return () => window.clearInterval(timer)
  }, [])
  if (!ts) return null
  const s = Math.max(0, Math.round((Date.now() - ts) / 1000))
  const label = s < 60 ? `${s}s` : `${Math.floor(s / 60)}m`
  return <span> · updated {label} ago</span>
}

export function BatchView() {
  const { batchId } = useParams<{ batchId: string }>()
  const navigate = useNavigate()
  const manifest = useBatchStore(s => s.manifest)
  const loading = useBatchStore(s => s.loading)
  const error = useBatchStore(s => s.error)
  const lastUpdated = useBatchStore(s => s.lastUpdated)
  const expandedProject = useBatchStore(s => s.expandedProject)
  const setExpandedProject = useBatchStore(s => s.setExpandedProject)

  useEffect(() => {
    if (!batchId) return
    useBatchStore.getState().startPolling(batchId)
    return () => useBatchStore.getState().stopPolling()
  }, [batchId])

  const active = batchActive(manifest)
  const reconnecting = !!error && !!manifest
  const interrupted = manifest?.state === 'interrupted'
  const [resuming, setResuming] = useState(false)
  const expandedAll = expandedProject === 'ALL'

  const handleResume = async () => {
    if (resuming || !batchId) return
    setResuming(true)
    try {
      await resumeBatch(batchId)
      useBatchStore.getState().startPolling(batchId)
    } catch (e: any) {
      alert(e?.message || 'Could not resume this batch')
    } finally {
      setResuming(false)
    }
  }

  const chip = manifest ? (STATE_CHIP[manifest.state] ?? { label: manifest.state, cls: 'bg-surface-container-high text-outline border-outline/10' }) : null

  return (
    <div className="p-10 max-w-[1600px] mx-auto space-y-8 animate-in fade-in duration-500">
      {/* Header */}
      <div className="flex items-center gap-4">
        <button
          id="btn-back-batch"
          onClick={() => navigate(-1)}
          title="Back"
          className="w-9 h-9 rounded-full hover:bg-surface-container-highest flex items-center justify-center text-outline hover:text-on-surface transition-colors shrink-0"
        >
          <span className="material-symbols-outlined text-[20px]">arrow_back</span>
        </button>
        <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center shrink-0">
          <span className="material-symbols-outlined text-primary">rocket_launch</span>
        </div>
        <div className="flex-1 min-w-0">
          <h1 className="text-xl font-black text-on-surface tracking-tighter">Auto Run Batch</h1>
          <p className="text-[11px] text-outline font-mono truncate mt-0.5">
            {batchId}{manifest?.created_at ? ` · started ${new Date(manifest.created_at).toLocaleString()}` : ''}
            <UpdatedAgo ts={lastUpdated} />
          </p>
        </div>
        {manifest && manifest.projects.length > 1 && (
          <button
            id="btn-expand-all"
            onClick={() => setExpandedProject(expandedAll ? null : 'ALL')}
            title={expandedAll ? 'Collapse all folders' : 'Expand all folders'}
            className="w-10 h-10 rounded-full hover:bg-surface-container-highest flex items-center justify-center text-outline hover:text-primary transition-colors shrink-0"
          >
            <span className="material-symbols-outlined text-[20px]">{expandedAll ? 'collapse_all' : 'expand_all'}</span>
          </button>
        )}
        {chip && (
          <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-[10px] font-black uppercase tracking-widest border ${chip.cls}`}>
            {active && <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />}
            {chip.label}
          </span>
        )}
      </div>

      {/* Body */}
      {loading && !manifest && (
        <div className="space-y-3 max-w-[1200px]">
          {[1, 2, 3].map(i => <div key={i} className="h-28 bg-surface-container-low rounded-xl animate-pulse" />)}
        </div>
      )}

      {!loading && error && !manifest && (
        <div className="p-4 rounded-xl bg-error-container/10 border border-error/20 text-center max-w-lg mx-auto">
          <span className="material-symbols-outlined text-error text-3xl block mb-2">wifi_off</span>
          <p className="text-error text-sm font-bold">{error}</p>
          <p className="text-outline text-xs mt-1">The batch manifest may have been deleted, or the API is unreachable.</p>
        </div>
      )}

      {manifest && manifest.projects.length === 0 && (
        <div className="text-center py-10 text-outline">
          <span className="material-symbols-outlined text-5xl block mb-4 opacity-20">folder_off</span>
          <p className="text-sm font-bold text-on-surface">This batch has no files.</p>
        </div>
      )}

      {/* Folder grid with expand-in-place detail */}
      {manifest && manifest.projects.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4 items-start">
          {manifest.projects.map((p) => (
            <div key={p.name} className="contents">
              <BatchFolderCard
                project={p}
                steps={p.steps}
                selected={expandedAll || expandedProject === p.name}
                onClick={() => setExpandedProject(expandedProject === p.name ? null : p.name)}
              />
              {(expandedAll || expandedProject === p.name) && (
                <div className="md:col-span-2 xl:col-span-3 col-span-full">
                  <BatchDetailPanel
                    batchId={batchId ?? ''}
                    projectName={p.name}
                    projectState={p.state}
                    errorStep={p.error_step}
                    onClose={() => setExpandedProject(null)}
                  />
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Status footer: never freezes — polling keeps running through errors */}
      {active && !error && (
        <p className="text-[10px] text-outline text-center animate-pulse font-bold tracking-widest uppercase">
          Refreshing every 3 s — finished folders are inspectable while the rest still run
        </p>
      )}
      {reconnecting && (
        <p className="text-[10px] text-secondary text-center font-bold tracking-widest uppercase flex items-center justify-center gap-1.5">
          <span className="material-symbols-outlined text-[14px] animate-spin">progress_activity</span>
          Reconnecting — showing the last received update
        </p>
      )}

      {/* Interrupted (zombie reconciliation): offer Resume instead of polling */}
      {interrupted && (
        <div className="p-4 rounded-xl bg-secondary-container/10 border border-secondary/20 text-center max-w-lg mx-auto">
          <span className="material-symbols-outlined text-secondary text-3xl block mb-2">pause_circle</span>
          <p className="text-secondary text-sm font-bold">This batch was interrupted — some PDFs never finished.</p>
          <button
            id="btn-resume-interrupted"
            onClick={handleResume}
            disabled={resuming}
            className="mt-3 px-4 py-2 rounded-xl bg-primary/10 border border-primary/30 text-primary text-[10px] font-black uppercase tracking-widest hover:bg-primary/20 disabled:opacity-40 inline-flex items-center gap-1.5 transition-all"
          >
            <span className={`material-symbols-outlined text-[14px] ${resuming ? 'animate-spin' : ''}`}>
              {resuming ? 'progress_activity' : 'play_arrow'}
            </span>
            {resuming ? 'Resuming…' : 'Resume batch'}
          </button>
        </div>
      )}
    </div>
  )
}
