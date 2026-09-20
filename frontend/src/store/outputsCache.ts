import { create } from 'zustand'
import { fetchStepOutput, fetchStepModels } from '../lib/api'

/**
 * outputsCache — Phase 6 client cache (Q-C1 contract, history-progress-cache plan):
 *
 * 1. Expand a folder → fresh entry (< TTL) → served, NO request sent.
 * 2. Expand after expiry → fetch fresh + replace.
 * 3. Expand all → same per-entry logic (cached = instant, expired = fetch).
 * 4. After a Sync (manual or automatic) completes → fetch the updated version
 *    and REPLACE the cached entry (replace, not just invalidate — the next
 *    expand must still be instant AND show the synced data).
 * 5. Future expansions of that folder show the new synced version.
 *
 * ONE simple cache, ONE TTL — the same value the server uses
 * (STEP_CACHE_TTL via GET /env/step-models `features.step_cache_ttl`).
 */

export interface CachedOutput {
  files: { name: string; size_bytes: number; created_at?: string }[]
  ts: number
}

interface OutputsCacheState {
  entries: Record<string, CachedOutput | undefined>
}

const useOutputsCacheStore = create<OutputsCacheState>(() => ({ entries: {} }))

// Bootstrapped once from the server (Phase 5 exposes the single knob);
// 180 until it answers — never blocks first use.
let TTL_SECONDS = 180
let ttlBootstrapped = false
function bootstrapTtl() {
  if (ttlBootstrapped) return
  ttlBootstrapped = true
  fetchStepModels()
    .then((m: any) => {
      const t = m?.features?.step_cache_ttl
      if (typeof t === 'number' && t >= 120 && t <= 300) TTL_SECONDS = t
    })
    .catch(() => {})
}

const keyOf = (project: string, step: string) => `${project}|${step}`

function setEntry(project: string, step: string, files: any[]) {
  useOutputsCacheStore.setState(state => ({
    entries: { ...state.entries, [keyOf(project, step)]: { files, ts: Date.now() } },
  }))
}

export function getCachedOutput(project: string, step: string): CachedOutput | undefined {
  return useOutputsCacheStore.getState().entries[keyOf(project, step)]
}

/** Cached-first: fresh entry is served without a request; expired → fetch + replace. */
export async function ensureStepOutput(project: string, step: string): Promise<any[]> {
  bootstrapTtl()
  const cur = useOutputsCacheStore.getState().entries[keyOf(project, step)]
  if (cur && Date.now() - cur.ts < TTL_SECONDS * 1000) return cur.files
  return reloadStepOutput(project, step)
}

/** Force a request + REPLACE the cached entry (post-sync contract). */
export async function reloadStepOutput(project: string, step: string): Promise<any[]> {
  bootstrapTtl()
  try {
    const data = await fetchStepOutput(project, step)
    const files = data.files ?? []
    setEntry(project, step, files)
    return files
  } catch {
    return []   // transient errors never overwrite a good cached entry
  }
}

/** A sync propagates edits to the sibling step too — refetch both, replacing entries. */
export async function reloadAfterSync(project: string, step: string): Promise<void> {
  bootstrapTtl()
  const ids = step === '2' ? ['2', '6'] : step === '6' ? ['6', '2'] : [step]
  await Promise.all(ids.map(id => reloadStepOutput(project, id)))
}

/** Local counterpart of a delete — drop one file from the cached entry. */
export function removeCachedFile(project: string, step: string, filename: string) {
  useOutputsCacheStore.setState(state => {
    const k = keyOf(project, step)
    const cur = state.entries[k]
    if (!cur) return state
    return { entries: { ...state.entries, [k]: { files: cur.files.filter(f => f.name !== filename), ts: cur.ts } } }
  })
}

export function useOutputsCache(): Record<string, CachedOutput | undefined> {
  return useOutputsCacheStore(s => s.entries)
}
