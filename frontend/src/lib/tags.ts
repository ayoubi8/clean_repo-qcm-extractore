import { TagEntry, Project } from '../types'

/** Tags & Search plan (docs/plans/tags-search-session-preserve-plan.md).
 *  Colors mirror the backend vocabulary (GET /env/tags); the region list is
 *  hardcoded so the forced-selection UI works even if /env/tags fails. */

export interface RegionTag { key: 'region'; value: string; label: string; color: string }

export const REGION_TAGS: RegionTag[] = [
  { key: 'region', value: 'oran',    label: 'Oran',    color: 'orange' },
  { key: 'region', value: 'mosta',   label: 'Mosta',   color: 'green' },
  { key: 'region', value: 'tlemcen', label: 'Tlemcen', color: 'brown' },
]

// chip classes per color (grey = untagged legacy)
export const TAG_COLOR: Record<string, string> = {
  orange: 'text-orange-500 border-orange-500/40 bg-orange-500/10',
  green:  'text-emerald-500 border-emerald-500/40 bg-emerald-500/10',
  brown:  'text-amber-700 border-amber-700/40 bg-amber-700/10',
  grey:   'text-outline border-outline-variant/30 bg-surface-container-low',
}

export function tagColorClass(value: string, key: TagEntry['key']): string {
  if (key === 'region') {
    const t = REGION_TAGS.find(r => r.value === value)
    if (t) return TAG_COLOR[t.color]
  }
  return TAG_COLOR.grey
}

export function regionOf(tags: TagEntry[] | undefined): string | null {
  return tags?.find(t => t.key === 'region')?.value ?? null
}

export function moduleOf(tags: TagEntry[] | undefined): string | null {
  return tags?.find(t => t.key === 'module')?.value ?? null
}

export function regionTag(value: string): TagEntry {
  return { key: 'region', value }
}

export function moduleTag(value: string): TagEntry {
  return { key: 'module', value }
}

export function hasRegionTag(project: Project): boolean {
  return !!regionOf(project.tags)
}

/** Client-side filter: name substring match + AND-matched tag values.
 *  items: Project[] or BatchSummary[]; activeTags empty list = no tag filter. */
export function filterBySearchTags<T extends { name?: string; batch_id?: string; tags?: TagEntry[] }>(
  items: T[],
  query: string,
  activeTags: TagEntry[]
): T[] {
  const q = query.trim().toLowerCase()
  return items.filter(it => {
    const name = it.name ?? it.batch_id ?? ''
    if (q && !name.toLowerCase().includes(q.toLowerCase())) return false
    for (const t of activeTags) {
      if (!it.tags?.some(x => x.key === t.key && x.value === t.value)) return false
    }
    return true
  })
}
