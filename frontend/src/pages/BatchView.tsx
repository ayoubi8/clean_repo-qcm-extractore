import { useEffect, useRef } from 'react'
import { useParams } from 'react-router-dom'
import { useBatchStore, batchActive } from '../store/batchStore'
import { BatchFolderCard } from '../components/batch/BatchFolderCard'
import { BatchDetailPanel } from '../components/batch/BatchDetailPanel'

/**
 * Auto Run batch cockpit (plan docs/plans/autorun-batch-plan.md Â§3.3):
 * a folder card per PDF in a responsive grid with live per-step progress;
 * clicking a card expands the detail panel IN PLACE (col-span-full inside the
 * same grid) so finished folders are inspectable while others still run.
 * Polls GET /autorun/batches/{id} every ~3s while anything is active.
 */

const POLL_INTERVAL_MS = 3000

const STATE_CHIP: Record<string, { label: string; cls: string }> = {
  pending:   { label: 'Queued',          cls: 'bg-surface-container-high text-outline border-outline/10' },
  running:   { label: 'Running',         cls: 'bg-primary-container/20 text-primary border-primary/30' },
  done:      { label: 'Completed',       cls: 'bg-primary/10 text-primary border-primary/40' },
  done_with_errors: { label: 'Done with errors', cls: 'bg-secondary-container/20 text-secondary border-secondary/30' },
  error:     { label: 'Failed',          cls: 'bg-error-container/10 text-error border-error/30' },
}

export function BatchView() {
  const { batchId } = useParams<{ batchId: string }>()
  const manifest = useBatchStore(s => s.manifest)
  const liveStatus = useBatchStore(s => s.liveStatus)
  const loading = useBatchStore(s => s.loading)
  const error = useBatchStore(s => s.error)
  const expandedProject = useBatchStore(s => s.expandedProject)
  const setExpandedProject = useBatchStore(s => s.setExpandedProject)
  const loadProgress = useBatchStore(s => s.loadProgress)
  const pollRef = useRef<number | null>(null)

  useEffect(() => {
    if (!batchId) return
    let fresh = true
    const tick = () => { useBatchStore.getState().loadProgress(batchId) }
    tick()
    const timer = window.setInterval(tick, POLL_INTERVAL_MS)
    pollRef.current = timer
    return () => { window.clearInterval(timer); pollRef.current = null }
  }, [batchId])

  const active = batchActive(manifest) && !error

  // Stop polling when the batch settles (interval no-ops fast when active=false)
  useEffect(() => {
    if (!active && pollRef.current) {
      window.clearInterval(pollRef.current)
      pollRef.current = null
    }
  }, [active])

  const chip = manifest ? (STATE_CHIP[manifest.state] ?? { label: manifest.state, cls: 'bg-surface-container-high text-outline border-outline/10' }) : null

  return (
    <div className="p-10 max-w-[1600px] mx-auto space-y-8 animate-in fade-in duration-500">
      {/* Header */}
      <div className="flex items-center gap-4">
        <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center shrink-0">
          <span className="material-symbols-outlined text-primary">rocket_launch</span>
        </div>
        <div className="flex-1 min-w-0">
          <h1 className="text-xl font-black text-on-surface tracking-tighter">Auto Run Batch</h1>
          <p className="text-[11px] text-outline font-mono truncate mt-0.5">
            {batchId}{manifest?.created_at ? ` Â· started ${new Date(manifest.created_at).toLocaleString()}` : ''}
          </p>
        </div>
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

      {!loading && error && (
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
                live={liveStatus[p.name]}
                selected={expandedProject === p.name}
                onClick={() => setExpandedProject(expandedProject === p.name ? null : p.name)}
              />
              {expandedProject === p.name && (
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
      {active && (
        <p className="text-[10px] text-outline text-center animate-pulse font-bold tracking-widest uppercase">
          Refreshing every 3 s â€” finished folders are inspectable while the rest still run
        </p>
      )}
    </div>
  )
}



