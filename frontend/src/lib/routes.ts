import type { StepId } from '../types'

/**
 * Project URLs (lag plan Phase 3). The URL is the source of truth for the
 * open project and step; the stores only cache data for it.
 */

/** Step rows the pipeline shows (Steps 3/4/5 live in the Step 2 row,
 *  Steps 1.5/1.6 in the Step 1 row). */
export const UI_STEPS: StepId[] = [1, 2, 6, 7, 8]

export function projectUrl(name: string, sub = ''): string {
  return `/projects/${encodeURIComponent(name)}${sub}`
}

export function stepUrl(name: string, stepId: StepId | number | string): string {
  return projectUrl(name, `/steps/${toUiStep(stepId) ?? 1}`)
}

export function outputsUrl(name: string): string {
  return projectUrl(name, '/outputs')
}

export function autorunUrl(name: string): string {
  return projectUrl(name, '/autorun')
}

/** Any step id (URL text, backend id) -> the row the UI shows, or null. */
export function toUiStep(raw: StepId | number | string | null | undefined): StepId | null {
  if (raw === null || raw === undefined || raw === '') return null
  const n = Number(raw)
  if (!Number.isFinite(n)) return null
  if (n === 3 || n === 4 || n === 5) return 2
  if (n === 1.5 || n === 1.6) return 1
  return (UI_STEPS as number[]).includes(n) ? (n as StepId) : null
}
