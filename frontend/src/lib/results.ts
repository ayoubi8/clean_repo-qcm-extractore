import { cached, invalidate, useCached } from './cache'
import { authFetchJson, BASE_URL } from './api'
import { removeCachedFile } from '../store/outputsCache'

/**
 * Results data layer (lag plan Phase R, §11). The server shapes the data:
 * counts, paged QCM rows, chunked text previews, xlsx tables.
 */

export interface ResultFile {
  name: string
  kind?: 'mbset_import' | 'mbset_report' | 'workbook' | 'result_json' | 'intermediate'
  label?: string
  size_bytes: number
  updated_at?: string
  created_at?: string
}

export interface StepResults {
  status: string
  output_exists: boolean
  results: ResultFile[]
  older: ResultFile[]
  intermediate_count: number
  intermediate_bytes: number
  qcm_json: string | null
}

export interface CountItem { flag?: string; session?: string; label?: string; count: number }

export interface ProjectResults {
  name: string
  steps: Record<string, StepResults>
  summary: null | {
    step: string; file: string; error?: string
    qcms: number; with_answer: number; no_answer: number; flagged: number; with_case: number
    flags: CountItem[]; sessions: CountItem[]
  }
  mbset: null | {
    step: string; import_file: string | null; report_file: string | null
    rows?: number | null; rejected?: number | null; to_review?: number | null; error?: string
  }
  flag_labels: Record<string, string>
}

export interface QcmRow {
  row: number
  Num: number | string | null
  Number: string
  page: number | null
  Text: string
  options: Record<string, string>
  Correct: string
  Year: string
  Tag: string
  session: string
  Cas: string
  category: string
  review_flags: string[]
  flag_labels: string[]
  origin_line: string
}

export interface QcmPage { step: string | null; file: string | null; total: number; page: number; size: number; rows: QcmRow[] }

export interface QcmQuery { filter?: string; flag?: string; session?: string; q?: string; page?: number; size?: number; step?: string }

const enc = encodeURIComponent
const RESULTS_TTL_MS = 30_000

export const resultsKey = (project: string) => `results:${project}`

export function fetchResults(project: string): Promise<ProjectResults> {
  return authFetchJson(`${BASE_URL}/projects/${enc(project)}/results`)
}

export function useProjectResults(project: string) {
  return useCached<ProjectResults>(resultsKey(project), () => fetchResults(project), RESULTS_TTL_MS)
}

/** Something changed on the server (run end, sync, delete): refetch. */
export function refreshResults(project: string): Promise<ProjectResults> {
  invalidate(`rq:${project}:`)
  return cached(resultsKey(project), () => fetchResults(project), RESULTS_TTL_MS, true)
}

export function fetchQcmPage(project: string, query: QcmQuery): Promise<QcmPage> {
  const params = new URLSearchParams()
  Object.entries(query).forEach(([k, v]) => { if (v !== undefined && v !== '' && v !== null) params.set(k, String(v)) })
  const key = `rq:${project}:${params.toString()}`
  return cached(key, () => authFetchJson(`${BASE_URL}/projects/${enc(project)}/results/qcms?${params}`), 60_000)
}

export interface TextChunk { content: string; offset: number; next_offset: number | null; total_bytes: number }
export function fetchTextChunk(project: string, step: string, path: string, offset = 0): Promise<TextChunk> {
  return authFetchJson(`${BASE_URL}/projects/${enc(project)}/results/${enc(step)}/preview?path=${enc(path)}&offset=${offset}`)
}

export interface TablePage { sheets: string[]; sheet: string; header: any[]; rows: any[][]; total_rows: number; page: number; size: number }
export function fetchTablePage(project: string, step: string, path: string, sheet = '', page = 1, size = 100): Promise<TablePage> {
  return authFetchJson(
    `${BASE_URL}/projects/${enc(project)}/results/${enc(step)}/table?path=${enc(path)}&sheet=${enc(sheet)}&page=${page}&size=${size}`)
}

export interface FilesPage { groups: { folder: string; count: number }[]; total: number; page: number; size: number; files: ResultFile[] }
export function fetchWorkingFiles(project: string, step: string, folder = '', page = 1, q = ''): Promise<FilesPage> {
  return authFetchJson(
    `${BASE_URL}/projects/${enc(project)}/results/${enc(step)}/files?folder=${enc(folder)}&page=${page}&q=${enc(q)}`)
}

export interface HistoryRun { run_id: string; label: string; file_count: number; total_bytes: number; results: ResultFile[] }
export function fetchResultHistory(project: string, step: string): Promise<{ runs: HistoryRun[] }> {
  return cached(`rh:${project}:${step}`,
    () => authFetchJson(`${BASE_URL}/projects/${enc(project)}/results/${enc(step)}/history`), 120_000)
}

export function fileUrl(project: string, step: string, name: string, mode: 'download' | 'view', runId?: string): string {
  const path = name.split('/').map(enc).join('/')
  if (runId) return `${BASE_URL}/projects/${enc(project)}/steps/${enc(step)}/history/${enc(runId)}/${path}`
  return `${BASE_URL}/projects/${enc(project)}/steps/${enc(step)}/${mode}/${path}`
}

/** After a delete: drop the file from every client cache that lists it. */
export function forgetFile(project: string, step: string, name: string) {
  removeCachedFile(project, step, name)
  void refreshResults(project).catch(() => {})
}

/** "20261121_140233"-style run ids → "21 Nov 2026, 14:02". */
export function prettyRunLabel(label: string): string {
  const m = /(\d{4})(\d{2})(\d{2})[_T-]?(\d{2})(\d{2})/.exec(label)
  if (!m) return label
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]), Number(m[4]), Number(m[5]))
  return isNaN(d.getTime()) ? label : d.toLocaleString(undefined, { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

export function formatBytes(n: number): string {
  if (!n) return '0 KB'
  if (n < 1024 * 1024) return `${Math.max(1, Math.round(n / 1024))} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}
