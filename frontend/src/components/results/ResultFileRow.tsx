import { useEffect, useState } from 'react'
import {
  SHEETS_SYNC_STEPS, deleteFile, downloadFile, hasOpenedSheet, openFileInTab,
  openWorkbookInSheets, syncSheets,
} from '../../lib/fileActions'
import {
  fetchTablePage, fetchTextChunk, formatBytes, type ResultFile, type TablePage,
} from '../../lib/results'

/**
 * One result / output file row (results plan §11.3) — used by the step card,
 * the Results page and the batch view. Previews open in place: text in 64 KB
 * chunks, workbooks as a paged table (no Google account needed).
 */

const TEXT_EXT = ['.txt', '.json', '.md', '.yaml', '.yml', '.csv', '.log']
const isXlsx = (n: string) => n.toLowerCase().endsWith('.xlsx')
const isText = (n: string) => TEXT_EXT.some((e) => n.toLowerCase().endsWith(e))
const base = (n: string) => n.split('/').pop() ?? n

function iconFor(f: ResultFile): string {
  if (f.kind === 'mbset_import') return 'upload_file'
  if (f.kind === 'mbset_report') return 'rule'
  if (isXlsx(f.name)) return 'table_chart'
  if (f.name.endsWith('.json')) return 'data_object'
  if (f.name.endsWith('.txt')) return 'description'
  return 'draft'
}

function IconBtn({ icon, title, onClick, disabled, spin, tone = 'primary' }: {
  icon: string; title: string; onClick: () => void; disabled?: boolean; spin?: boolean
  tone?: 'primary' | 'error' | 'sheets'
}) {
  const hover = tone === 'error' ? 'hover:text-error hover:bg-error/10'
    : tone === 'sheets' ? 'hover:text-[#34A853] hover:bg-[#34A853]/10'
      : 'hover:text-primary hover:bg-primary/10'
  return (
    <button
      type="button"
      onClick={(e) => { e.stopPropagation(); onClick() }}
      title={title}
      aria-label={title}
      disabled={disabled}
      className={`w-7 h-7 rounded-lg flex items-center justify-center text-outline transition-colors disabled:opacity-40 ${hover}`}
    >
      <span className={`material-symbols-outlined text-[16px] ${spin ? 'animate-spin' : ''}`}>{icon}</span>
    </button>
  )
}

export function ResultFileRow({ project, step, file, runId, canDelete = true, onDeleted, highlight = false }: {
  project: string
  step: string
  file: ResultFile
  /** History run: download/open only. */
  runId?: string
  canDelete?: boolean
  onDeleted?: (name: string) => void
  highlight?: boolean
}) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState<null | 'sheets' | 'sync' | 'delete'>(null)
  const xlsx = isXlsx(file.name)
  const previewable = !runId && (xlsx || isText(file.name))
  const when = file.updated_at || file.created_at
  const label = file.label && file.label !== base(file.name) ? file.label : null

  const act = async (kind: 'sheets' | 'sync' | 'delete', fn: () => Promise<unknown>) => {
    setBusy(kind)
    try { await fn() } finally { setBusy(null) }
  }

  return (
    <div className="space-y-2">
      <div
        className={`flex items-center gap-3 p-3 rounded-xl border transition-all ${
          open ? 'bg-primary/5 border-primary/40'
            : highlight ? 'bg-primary/[0.04] border-primary/20 hover:border-primary/40'
              : 'bg-surface-container-low border-outline-variant/10 hover:border-outline-variant/30'
        } ${previewable ? 'cursor-pointer' : ''}`}
        onClick={() => previewable && setOpen((v) => !v)}
      >
        <span className={`material-symbols-outlined text-[18px] shrink-0 ${highlight ? 'text-primary' : 'text-outline'}`}>
          {iconFor(file)}
        </span>
        <div className="min-w-0 flex-1">
          {label && <p className="text-xs font-bold text-on-surface truncate">{label}</p>}
          <p className={`truncate ${label ? 'text-[10px] text-outline font-mono' : 'text-xs font-bold text-on-surface-variant'}`} title={file.name}>
            {file.name}
          </p>
        </div>
        <span className="hidden sm:block text-[10px] text-outline tabular-nums shrink-0 text-right">
          {formatBytes(file.size_bytes)}
          {when && <span className="block text-outline/50">{when}</span>}
        </span>
        <div className="flex items-center gap-0.5 shrink-0">
          {previewable && (
            <IconBtn icon={open ? 'visibility_off' : 'visibility'} title={open ? 'Close preview' : 'Preview'} onClick={() => setOpen((v) => !v)} />
          )}
          <IconBtn icon="download" title="Download" onClick={() => { void downloadFile(project, step, file.name, runId) }} />
          {xlsx && !runId ? (
            <IconBtn
              icon={busy === 'sheets' ? 'progress_activity' : 'open_in_new'}
              spin={busy === 'sheets'}
              tone="sheets"
              title="Open in Google Sheets"
              disabled={busy === 'sheets'}
              onClick={() => { void act('sheets', () => openWorkbookInSheets(project, step, file.name)) }}
            />
          ) : (
            <IconBtn icon="open_in_new" title="Open in a new tab" onClick={() => { void openFileInTab(project, step, file.name, runId) }} />
          )}
          {xlsx && !runId && SHEETS_SYNC_STEPS.includes(step) && file.kind !== 'mbset_import' && file.kind !== 'mbset_report' && (
            <IconBtn
              icon={busy === 'sync' ? 'sync' : 'cloud_sync'}
              spin={busy === 'sync'}
              title="Pull the latest edits back from Google Sheets"
              disabled={busy === 'sync'}
              onClick={() => { void act('sync', () => syncSheets(project, step, false, file.name)) }}
            />
          )}
          {canDelete && !runId && (
            <IconBtn
              icon={busy === 'delete' ? 'hourglass_top' : 'delete'}
              tone="error"
              title="Delete"
              disabled={busy === 'delete'}
              onClick={() => {
                void act('delete', async () => {
                  if (await deleteFile(project, step, file.name)) onDeleted?.(file.name)
                })
              }}
            />
          )}
        </div>
      </div>
      {open && previewable && (
        <div className="ml-2 sm:ml-6 qe-fade-up">
          {xlsx
            ? <TablePreview project={project} step={step} path={file.name} />
            : <TextPreview project={project} step={step} path={file.name} />}
        </div>
      )}
    </div>
  )
}

export function TextPreview({ project, step, path }: { project: string; step: string; path: string }) {
  const [text, setText] = useState('')
  const [next, setNext] = useState<number | null>(0)
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = async (offset: number) => {
    setLoading(true)
    try {
      const c = await fetchTextChunk(project, step, path, offset)
      setText((t) => (offset === 0 ? c.content : t + c.content))
      setNext(c.next_offset)
      setTotal(c.total_bytes)
      setError(null)
    } catch (e: any) {
      setError(e?.message || 'Could not load the file')
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => { void load(0) }, [project, step, path]) // eslint-disable-line react-hooks/exhaustive-deps

  if (error) return <p className="text-xs text-error px-1">{error}</p>
  const shown = new TextEncoder().encode(text).length
  return (
    <div className="rounded-xl border border-outline-variant/20 bg-surface-container-lowest overflow-hidden">
      <pre className="p-4 font-mono text-[11px] leading-relaxed text-on-surface-variant whitespace-pre-wrap break-words max-h-96 overflow-auto custom-scrollbar">
        {loading && !text ? 'Loading…' : text || '[empty file]'}
      </pre>
      {(next !== null || total > 0) && (
        <div className="flex items-center justify-between px-4 py-2 border-t border-outline-variant/10 text-[10px] text-outline">
          <span>{formatBytes(shown)} of {formatBytes(total)}</span>
          {next !== null && (
            <button
              onClick={() => { void load(next) }}
              disabled={loading}
              className="font-bold text-primary hover:underline disabled:opacity-50"
            >
              {loading ? 'Loading…' : 'Load more'}
            </button>
          )}
        </div>
      )}
    </div>
  )
}

export function TablePreview({ project, step, path }: { project: string; step: string; path: string }) {
  const [sheet, setSheet] = useState('')
  const [page, setPage] = useState(1)
  const [data, setData] = useState<TablePage | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const size = 50

  useEffect(() => {
    let alive = true
    setLoading(true)
    fetchTablePage(project, step, path, sheet, page, size)
      .then((d) => { if (alive) { setData(d); setError(null) } })
      .catch((e) => { if (alive) setError(e?.message || 'Could not read the workbook') })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [project, step, path, sheet, page])

  if (error) return <p className="text-xs text-error px-1">{error}</p>
  if (!data) return <p className="text-xs text-outline px-1 animate-pulse">Reading workbook…</p>
  const pages = Math.max(1, Math.ceil(data.total_rows / size))
  return (
    <div className="rounded-xl border border-outline-variant/20 bg-surface-container-lowest overflow-hidden">
      {data.sheets.length > 1 && (
        <div className="flex gap-1 p-2 border-b border-outline-variant/10 overflow-x-auto">
          {data.sheets.map((s) => (
            <button
              key={s}
              onClick={() => { setSheet(s); setPage(1) }}
              className={`px-3 h-7 rounded-lg text-[10px] font-bold whitespace-nowrap ${
                s === data.sheet ? 'bg-surface-container-highest text-primary' : 'text-outline hover:text-on-surface'
              }`}
            >
              {s}
            </button>
          ))}
        </div>
      )}
      <div className={`max-h-[28rem] overflow-auto custom-scrollbar ${loading ? 'opacity-60' : ''}`}>
        <table className="w-full text-[11px] border-collapse">
          <thead className="sticky top-0 bg-surface-container-high z-10">
            <tr>
              <th className="px-2 py-1.5 text-right text-outline font-bold w-10">#</th>
              {data.header.map((h, i) => (
                <th key={i} className="px-2 py-1.5 text-left font-black text-on-surface-variant whitespace-nowrap">{String(h)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.rows.map((r, i) => (
              <tr key={i} className="border-t border-outline-variant/10 hover:bg-primary/[0.03] align-top">
                <td className="px-2 py-1.5 text-right text-outline tabular-nums">{(page - 1) * size + i + 1}</td>
                {r.map((c, j) => (
                  <td key={j} className="px-2 py-1.5 text-on-surface-variant max-w-[22rem]">
                    <span className="line-clamp-3 break-words">{String(c)}</span>
                  </td>
                ))}
              </tr>
            ))}
            {data.rows.length === 0 && (
              <tr><td colSpan={data.header.length + 1} className="px-3 py-6 text-center text-outline italic">This sheet is empty.</td></tr>
            )}
          </tbody>
        </table>
      </div>
      <Pager page={page} pages={pages} total={data.total_rows} unit="rows" onPage={setPage} />
    </div>
  )
}

export function Pager({ page, pages, total, unit, onPage }: {
  page: number; pages: number; total: number; unit: string; onPage: (p: number) => void
}) {
  return (
    <div className="flex items-center justify-between px-3 py-2 border-t border-outline-variant/10 text-[10px] text-outline">
      <span>{total} {unit}</span>
      {pages > 1 && (
        <div className="flex items-center gap-1">
          <button onClick={() => onPage(Math.max(1, page - 1))} disabled={page <= 1} className="w-6 h-6 rounded-md hover:bg-surface-container-highest disabled:opacity-30" aria-label="Previous page">
            <span className="material-symbols-outlined text-[14px]">chevron_left</span>
          </button>
          <span className="tabular-nums font-bold">{page} / {pages}</span>
          <button onClick={() => onPage(Math.min(pages, page + 1))} disabled={page >= pages} className="w-6 h-6 rounded-md hover:bg-surface-container-highest disabled:opacity-30" aria-label="Next page">
            <span className="material-symbols-outlined text-[14px]">chevron_right</span>
          </button>
        </div>
      )}
    </div>
  )
}

/** Returning to this tab after editing in Google Sheets pulls the edits back. */
export function useSheetsAutoSync(project: string | undefined) {
  useEffect(() => {
    if (!project) return
    const onVisible = async () => {
      if (document.visibilityState !== 'visible') return
      for (const step of SHEETS_SYNC_STEPS) {
        if (hasOpenedSheet(project, step)) await syncSheets(project, step, true)
      }
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => document.removeEventListener('visibilitychange', onVisible)
  }, [project])
}
