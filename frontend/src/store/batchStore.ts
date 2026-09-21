import { create } from 'zustand'
import { BatchManifest, BatchSteps } from '../types'
import { getBatchProgress } from '../lib/api'

/**
 * Auto Run batch view state (plan docs/plans/autorun-batch-plan.md §3.3).
 * NOT persisted — the manifest comes from GET /autorun/batches/{id}.
 *
 * Phase 2 (history-progress-cache plan): polling CANNOT die. The poll loop is
 * owned by the store as a self-scheduling setTimeout chain (never a bare
 * setInterval cleared on one failure): it keeps polling while the batch is
 * active — even across failed polls — backing off 3s → 6s → 12s with a
 * "reconnecting" UI state, and stops ONLY on a terminal manifest state
 * (restartable via startPolling after a per-PDF retry re-activates the batch).
 */

type LiveStatus = Record<string, string>            // step id → status
type LiveStatusMap = Record<string, LiveStatus>     // project name → statuses

const POLL_INTERVAL_MS = 3000
const BACKOFF_CAP_MS = 12000

interface BatchStore {
  manifest: BatchManifest | null
  liveStatus: LiveStatusMap
  loading: boolean
  error: string | null
  lastUpdated: number | null                          // Date.now() of last successful poll
  expandedProject: string | null
  setExpandedProject: (name: string | null) => void
  startPolling: (batchId: string) => void
  stopPolling: () => void
  loadProgress: (batchId: string) => Promise<void>
  clear: () => void
}

export const useBatchStore = create<BatchStore>((set) => ({
  manifest: null,
  liveStatus: {},
  loading: false,
  error: null,
  lastUpdated: null,
  expandedProject: null,
  setExpandedProject: (name) => set({ expandedProject: name }),
  loadProgress: async (batchId) => {
    // Do NOT clear `error` here — it stays until a successful poll replaces
    // both manifest and error together (no flicker between ticks).
    set((s) => ({ loading: !s.manifest }))
    try {
      const data = await getBatchProgress(batchId)
      const liveStatus = data.live_status ?? {}
      batchCache[batchId] = { manifest: data.batch, liveStatus }
      set({
        manifest: data.batch,
        liveStatus,
        loading: false,
        error: null,
        lastUpdated: Date.now(),
      })
    } catch (e: any) {
      set({ error: e?.message ?? 'Failed to load the batch', loading: false })
    }
  },
  clear: () => set({ manifest: null, liveStatus: {}, loading: false, error: null, lastUpdated: null, expandedProject: null }),
  startPolling: (batchId) => startPolling(batchId),
  stopPolling: () => stopPolling(),
}))

/** True while any project in the batch is pending/running (keeps polling alive).
 *  `interrupted` (zombie reconciliation) intentionally forces polling OFF. */
export function batchActive(manifest: BatchManifest | null): boolean {
  if (!manifest || manifest.state === 'interrupted') return false
  return (manifest.projects ?? []).some(p => p.state === 'pending' || p.state === 'running') ||
    manifest.state === 'running' || manifest.state === 'pending'
}

// ── Poll loop (module-owned; survives errors, restarts, remounts) ───────────

let pollTimer: number | null = null
let pollTarget: string | null = null
let failStreak = 0
// Phase 7 hardening: when NOTHING in the manifest changes between successful
// polls (e.g. a stuck/zombie batch the backend hasn't reconciled yet), slow
// down instead of hammering every 3s: 6s → 12s → 30s → 60s cap. Any change
// (or error) snaps back to the base cadence.
let lastFingerprint = ''
let unchangedStreak = 0

function fingerprint(manifest: BatchManifest | null): string {
  if (!manifest) return ''
  return manifest.state + '|' + (manifest.projects ?? []).map(p =>
    `${p.state}:${p.current_step ?? ''}:${JSON.stringify(p.steps ?? {})}`).join(',')
}

// Phase 6 — last-good snapshot per batchId so revisiting /batch/:id renders
// instantly (the first poll replaces it). Module-level; cleared only naturally.
const batchCache: Record<string, { manifest: BatchManifest; liveStatus: LiveStatusMap }> = {}

function backoffDelayMs(streak: number): number {
  // 3s on first failure, then 6s, then capped at 12s
  return Math.min(POLL_INTERVAL_MS * Math.pow(2, Math.min(streak - 1, 2)), BACKOFF_CAP_MS)
}

function clearTimer() {
  if (pollTimer !== null) {
    window.clearTimeout(pollTimer)
    pollTimer = null
  }
}

function scheduleTick(delayMs: number) {
  clearTimer()
  pollTimer = window.setTimeout(() => {
    pollTimer = null
    void runTick()
  }, delayMs)
}

async function runTick() {
  const target = pollTarget
  if (!target) return
  try {
    await useBatchStore.getState().loadProgress(target)
  } catch {
    // loadProgress catches internally; belt-and-braces for the scheduler.
  }
  if (pollTarget !== target) return                    // stopped/re-targeted meanwhile
  const s = useBatchStore.getState()
  if (s.error) {
    failStreak += 1
    // A terminal manifest with a failed poll has nothing to wait for.
    if (s.manifest && !batchActive(s.manifest)) {
      stopPolling()
      return
    }
    scheduleTick(backoffDelayMs(failStreak))           // keep polling — reconnecting
    return
  }
  failStreak = 0
  const fp = fingerprint(s.manifest)
  if (fp === lastFingerprint) {
    unchangedStreak += 1
  } else {
    unchangedStreak = 0
  }
  lastFingerprint = fp
  if (!batchActive(s.manifest)) {
    stopPolling()                                      // terminal manifest state only
    return
  }
  scheduleTick(unchangedStreak === 0 ? POLL_INTERVAL_MS : unchangedBackoffMs(unchangedStreak))
}

function unchangedBackoffMs(streak: number): number {
  return Math.min(POLL_INTERVAL_MS * Math.pow(2, streak), 60000)
}

function startPolling(batchId: string) {
  // Phase 6: seed from the last-good snapshot so revisits render instantly —
  // the immediate tick re-fetches and replaces it.
  const cached = batchCache[batchId]
  const s = useBatchStore.getState()
  if (cached && (s.manifest?.batch_id ?? '').toString() !== batchId) {
    useBatchStore.setState({
      manifest: cached.manifest,
      liveStatus: cached.liveStatus,
      loading: false,
      error: null,
    })
  }
  if (pollTarget === batchId) return      // already polling (possibly mid-tick — it re-arms itself)
  clearTimer()
  pollTarget = batchId
  failStreak = 0
  lastFingerprint = ''
  unchangedStreak = 0
  scheduleTick(0)                                      // first tick fires immediately
}

function stopPolling() {
  pollTarget = null
  failStreak = 0
  clearTimer()
}

/**
 * User-facing chip state for a step (steps 1 / 2 / 6), from the MERGED map the
 * API sends per project (`steps`: durable manifest states + live overlay):
 * step 1 covers the invisible 1.5 / 1.6 helpers — any of them running/error
 * drives the Step 1 chip; `skipped` (cache hit) renders as `cached`.
 */
export function stepChipStatus(steps: BatchSteps | undefined, step: 1 | 2 | 6): string {
  if (!steps) return 'idle'
  if (step === 1) {
    const seq = (['1', '1.5', '1.6'] as const).map(sid => steps[sid]?.state ?? 'idle')
    if (seq.some(s => s === 'running' || s === 'stopping')) return 'running'
    if (seq.some(s => s === 'error' || s === 'stopped' || s === 'cancelled')) return 'error'
    if (seq[0] === 'done') return 'done'
    if (seq.some(s => s === 'skipped')) return 'cached'
    return seq.find(s => s !== 'idle') ?? 'idle'
  }
  const s = steps[String(step)]?.state
  if (s === 'running' || s === 'stopping') return 'running'
  if (s === 'done') return 'done'
  if (s === 'skipped') return 'cached'
  if (s === 'error' || s === 'stopped' || s === 'cancelled') return 'error'
  return 'idle'
}
