import { create } from 'zustand'
import { BatchManifest } from '../types'
import { getBatchProgress } from '../lib/api'

/**
 * Auto Run batch view state (plan docs/plans/autorun-batch-plan.md Â§3.3).
 * NOT persisted â€” the manifest comes from GET /autorun/batches/{id}, polled
 * ~every 3s while the batch is still running.
 */

type LiveStatus = Record<string, string>            // step id â†’ status
type LiveStatusMap = Record<string, LiveStatus>     // project name â†’ statuses

interface BatchStore {
  manifest: BatchManifest | null
  liveStatus: LiveStatusMap
  loading: boolean
  error: string | null
  expandedProject: string | null
  setExpandedProject: (name: string | null) => void
  loadProgress: (batchId: string) => Promise<void>
  clear: () => void
}

export const useBatchStore = create<BatchStore>((set) => ({
  manifest: null,
  liveStatus: {},
  loading: false,
  error: null,
  expandedProject: null,
  setExpandedProject: (name) => set({ expandedProject: name }),
  loadProgress: async (batchId) => {
    set((s) => ({ loading: !s.manifest, error: null }))
    try {
      const data = await getBatchProgress(batchId)
      set({ manifest: data.batch, liveStatus: data.live_status ?? {}, loading: false })
    } catch (e: any) {
      set({ error: e?.message ?? 'Failed to load the batch', loading: false })
    }
  },
  clear: () => set({ manifest: null, liveStatus: {}, loading: false, error: null, expandedProject: null }),
}))

/** True while any project in the batch is pending/running (keeps polling alive). */
export function batchActive(manifest: BatchManifest | null): boolean {
  if (!manifest) return false
  return (manifest.projects ?? []).some(p => p.state === 'pending' || p.state === 'running') ||
    manifest.state === 'running' || manifest.state === 'pending'
}

/**
 * User-facing chip state for a step (steps 1 / 2 / 6):
 * step 1 covers the invisible 1.5 / 1.6 helpers â€” any of them running means
 * the Step 1 chip shows running; a done "1" makes the chip done.
 */
export function stepChipStatus(live: LiveStatus | undefined, step: 1 | 2 | 6): string {
  if (!live) return 'idle'
  if (step === 1) {
    for (const sid of ['1', '1.5', '1.6']) {
      const s = live[sid]
      if (s === 'running' || s === 'stopping') return 'running'
    }
    return live['1'] === 'done' ? 'done' : (live['1'] ? live['1'] : 'idle')
  }
  const s = live[String(step)]
  if (s === 'running' || s === 'stopping') return 'running'
  if (s === 'done') return 'done'
  if (s === 'error') return 'error'
  if (s === 'stopped' || s === 'cancelled') return 'error'
  return 'idle'
}


