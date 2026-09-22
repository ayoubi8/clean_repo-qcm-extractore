import { useState, useEffect } from 'react'
import { fetchBatches, resumeBatch } from '../../lib/api'
import { BatchSummary, TagEntry } from '../../types'
import { filterBySearchTags } from '../../lib/tags'
import { TagChip } from '../tags/TagChip'

/** Phase 4 — batch history ("Recent batches") shared by the Auto Run wizard
 *  AND the Resume Project tab (click a row → `/batch/:id`). Optional
 *  search/tag filtering comes from the parent (tags-search plan). */

const HISTORY_CHIP: Record<string, { label: string; cls: string }> = {
  done:             { label: 'Completed',  cls: 'text-primary border-primary/30 bg-primary/5' },
  done_with_errors: { label: 'With errors', cls: 'text-secondary border-secondary/30 bg-secondary-container/10' },
  running:          { label: 'Running',    cls: 'text-primary border-primary/40 bg-primary/10' },
  interrupted:      { label: 'Interrupted', cls: 'text-secondary border-secondary/30 bg-secondary-container/20' },
  error:            { label: 'Failed',     cls: 'text-error border-error/30 bg-error-container/10' },
}

const HISTORY_STEP = 20

function shortDate(iso: string): string {
  const d = iso ? new Date(iso) : null
  return d && !isNaN(d.getTime())
    ? d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
    : iso
}

interface BatchHistoryListProps {
  onOpenBatch: (batchId: string) => void
  query?: string
  activeTags?: TagEntry[]
}

export function BatchHistoryList({ onOpenBatch, query = '', activeTags = [] }: BatchHistoryListProps) {
  const [batches, setBatches] = useState<BatchSummary[] | null>(null) // null = loading
  const [limit, setLimit] = useState(HISTORY_STEP)
  const [resuming, setResuming] = useState<string | null>(null)

  const load = async (l: number) => {
    try {
      setBatches((await fetchBatches(l)) ?? [])
    } catch {
      setBatches([])                       // history is optional — hide on failure
    }
  }

  useEffect(() => { load(limit) }, [limit])

  const handleResume = async (batchId: string) => {
    if (resuming) return
    setResuming(batchId)
    try {
      await resumeBatch(batchId)
      onOpenBatch(batchId)                 // queued → open the batch cockpit
    } catch {
      setResuming(null)
    }
  }

  if (batches === null) {
    return (
      <div className="space-y-2">
        {[1, 2].map((i) => (
          <div key={i} className="h-10 bg-surface-container-high rounded-xl animate-pulse" />
        ))}
      </div>
    )
  }

  if (batches.length === 0) return null

  const visible = filterBySearchTags(batches, query, activeTags)
  if (visible.length === 0) return null

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between px-1">
        <span className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">
          Recent batches
        </span>
        <div className="flex items-center gap-1">
          {batches.length >= limit && (
            <button
              onClick={() => setLimit(l => l + HISTORY_STEP)}
              className="text-[10px] font-bold uppercase tracking-widest text-outline hover:text-primary transition-colors"
            >
              Load more
            </button>
          )}
          <button
            title="Refresh"
            onClick={() => load(limit)}
            className="w-6 h-6 rounded-lg hover:bg-surface-container-highest flex items-center justify-center text-outline hover:text-primary transition-colors"
          >
            <span className="material-symbols-outlined text-[14px]">refresh</span>
          </button>
        </div>
      </div>
      <div className="space-y-2 max-h-[192px] overflow-y-auto custom-scrollbar pr-1">
        {visible.map(b => {
          const chip = HISTORY_CHIP[b.state] ?? { label: b.state, cls: 'text-outline border-outline-variant/20 bg-surface-container-low' }
          const interrupted = b.state === 'interrupted'
          return (
            <div
              key={b.batch_id}
              onClick={() => onOpenBatch(b.batch_id)}
              className="flex items-center gap-2.5 p-2.5 cursor-pointer rounded-xl border bg-surface-container-low border-outline-variant/10 hover:border-primary/40 transition-all"
            >
              <span className={`material-symbols-outlined text-[16px] shrink-0 ${interrupted ? 'text-secondary' : 'text-primary'}`}>
                {b.state === 'done' ? 'task_alt' : b.state === 'interrupted' ? 'pause_circle' : 'rocket_launch'}
              </span>
              <div className="flex-1 min-w-0">
                <p className="text-xs font-bold text-on-surface tracking-tight">
                  {shortDate(b.created_at)}
                  <span className="text-outline font-medium"> · {b.counts.total} PDF{b.counts.total > 1 ? 's' : ''}</span>
                </p>
                <div className="flex items-center gap-1.5 mt-0.5">
                  {(b.tags ?? []).slice(0, 2).map((t, i) => (
                    <TagChip key={i} tag={t} />
                  ))}
                  {!(b.tags ?? []).some(t => t.key === 'region') && (
                    <TagChip tag={{ key: 'region', value: 'untagged' }} />
                  )}
                  <p className="text-[10px] text-outline font-mono truncate">
                    {b.preview_names.join(' · ')}
                  </p>
                </div>
              </div>
              <span className={`shrink-0 inline-flex items-center px-1.5 py-0.5 rounded border text-[9px] font-black uppercase tracking-wider ${chip.cls}`}>
                {chip.label}
              </span>
              {interrupted && (
                <button
                  onClick={(e) => { e.stopPropagation(); handleResume(b.batch_id) }}
                  disabled={resuming === b.batch_id}
                  title="Re-launch this batch from its remaining PDFs"
                  className={`shrink-0 inline-flex items-center gap-1 px-2 py-1 rounded-lg text-[9px] font-black uppercase tracking-widest border transition-all ${
                    resuming === b.batch_id
                      ? 'bg-primary-container/30 text-primary border-primary/40'
                      : 'bg-primary/10 border-primary/30 text-primary hover:bg-primary/20'
                  }`}
                >
                  <span className={`material-symbols-outlined text-[12px] ${resuming === b.batch_id ? 'animate-spin' : ''}`}>
                    {resuming === b.batch_id ? 'progress_activity' : 'play_arrow'}
                  </span>
                  Resume
                </button>
              )}
              <span className="material-symbols-outlined text-[14px] text-outline shrink-0">chevron_right</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
