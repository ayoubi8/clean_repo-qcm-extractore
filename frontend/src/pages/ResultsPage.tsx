import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { BASE_URL, fetchAuthenticatedBlobUrl } from '../lib/api'
import { downloadFile, openWorkbookInSheets } from '../lib/fileActions'
import {
  fetchQcmPage, fetchResultHistory, fetchWorkingFiles, formatBytes, prettyRunLabel,
  refreshResults, useProjectResults,
  type FilesPage, type HistoryRun, type ProjectResults, type QcmPage, type QcmRow, type StepResults,
} from '../lib/results'
import { stepUrl } from '../lib/routes'
import { ResultFileRow, Pager, useSheetsAutoSync } from '../components/results/ResultFileRow'
import { useRefreshResultsOnRunEnd } from '../hooks/useResultsLive'
import { toast } from '../components/ui/Toaster'
import { DownloadResultsButton } from '../components/results/DownloadResultsDialog'

/**
 * /projects/:name/outputs — Results page (lag plan Phase R, §11.3).
 * Results first, files second: what did I get, what must I check, what do I
 * upload. Everything is shaped by the server; one summary request (cached).
 */

const STEP_LABELS: Record<string, string> = {
  '1': 'Step 1 · Text extraction',
  '2': 'Step 2 · QCM extraction + metadata',
  '6': 'Step 6 · Corrections',
  '7': 'Step 7 · Categorization',
  '8': 'Step 8 · Similarity match',
}
const STEP_ORDER = ['1', '2', '6', '7', '8']

export function ResultsPage() {
  const { name = '' } = useParams()
  const { data, loading, error, reload } = useProjectResults(name)
  const [refreshing, setRefreshing] = useState(false)
  useRefreshResultsOnRunEnd(name)
  useSheetsAutoSync(name)

  const refresh = async () => {
    setRefreshing(true)
    try { await refreshResults(name) } catch (e: any) { toast.error(e?.message || 'Refresh failed') }
    finally { setRefreshing(false) }
  }

  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-6 py-8 space-y-6 qe-fade-up">
      <div className="flex items-end justify-between gap-4 flex-wrap">
        <div className="min-w-0">
          <Link to={stepUrl(name, 1)} className="inline-flex items-center gap-1 text-[11px] font-bold text-outline hover:text-primary">
            <span className="material-symbols-outlined text-[14px]">arrow_back</span>
            Pipeline
          </Link>
          <h1 className="text-2xl font-black tracking-tight text-on-surface mt-1">Results</h1>
          <p className="text-sm text-outline truncate">{name}</p>
        </div>
        <div className="flex items-center gap-2">
        <DownloadResultsButton projects={[{ name }]} zipName={`${name}_results`} />
        <button
          onClick={() => { void refresh() }}
          disabled={refreshing}
          className="flex items-center gap-2 h-9 px-3 rounded-xl border border-outline-variant/20 text-xs font-bold text-on-surface-variant hover:text-primary hover:border-primary/30 transition-colors disabled:opacity-50"
        >
          <span className={`material-symbols-outlined text-[18px] ${refreshing ? 'animate-spin' : ''}`}>refresh</span>
          Refresh
        </button>
        </div>
      </div>

      {loading && !data ? (
        <SkeletonCards />
      ) : error && !data ? (
        <div className="p-6 rounded-2xl border border-error/30 bg-error-container/20 text-sm text-on-surface flex items-center justify-between gap-4">
          <span>Could not load results: {error}</span>
          <button onClick={() => { void reload() }} className="text-primary font-bold text-xs">Retry</button>
        </div>
      ) : data ? (
        <>
          <SummaryCard project={name} data={data} />
          {data.summary && !data.summary.error && <QuestionsSection project={name} data={data} />}
          <FilesSection project={name} data={data} />
        </>
      ) : null}
    </div>
  )
}

function SkeletonCards() {
  return (
    <div className="space-y-4">
      {[0, 1, 2].map((i) => <div key={i} className="h-32 rounded-2xl bg-surface-container animate-pulse" />)}
    </div>
  )
}

function Stat({ value, label, tone = 'default', onClick, active }: {
  value: number | string; label: string; tone?: 'default' | 'warn' | 'good'; onClick?: () => void; active?: boolean
}) {
  const color = tone === 'warn' ? 'text-tertiary' : tone === 'good' ? 'text-primary' : 'text-on-surface'
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={!onClick}
      className={`text-left p-4 rounded-xl border transition-colors ${
        active ? 'border-primary/40 bg-primary/5' : 'border-outline-variant/10 bg-surface-container-low'
      } ${onClick ? 'hover:border-primary/30 cursor-pointer' : 'cursor-default'}`}
    >
      <p className={`text-2xl font-black tabular-nums ${color}`}>{value}</p>
      <p className="text-[10px] font-bold uppercase tracking-widest text-outline mt-1">{label}</p>
    </button>
  )
}

// Filter chosen from the summary tiles, applied by the questions table.
const filterListeners = new Set<(f: string) => void>()
function pickFilter(f: string) {
  filterListeners.forEach((fn) => fn(f))
  document.getElementById('results-questions')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function SummaryCard({ project, data }: { project: string; data: ProjectResults }) {
  const s = data.summary
  const mb = data.mbset
  const newestWorkbook = useMemo(() => {
    for (const sid of ['7', '6', '2']) {
      const wb = data.steps[sid]?.results.find((r) => r.kind === 'workbook')
      if (wb) return { step: sid, name: wb.name }
    }
    return null
  }, [data])

  if (!s) {
    return (
      <section className="p-8 rounded-2xl bg-surface-container border border-outline-variant/10 text-center space-y-3">
        <span className="material-symbols-outlined text-4xl text-outline">quiz</span>
        <p className="text-sm font-bold text-on-surface">No QCMs yet</p>
        <p className="text-xs text-outline">Run Step 2 to extract the questions; results appear here.</p>
        <Link to={stepUrl(project, 2)} className="inline-flex items-center gap-2 h-9 px-4 rounded-xl bg-primary text-on-primary text-xs font-bold">
          <span className="material-symbols-outlined text-[16px]">play_arrow</span>
          Go to Step 2
        </Link>
      </section>
    )
  }

  return (
    <section className="p-6 rounded-2xl bg-surface-container border border-outline-variant/10 space-y-5">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <h2 className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">Summary</h2>
        <span className="text-[10px] text-outline">
          From {STEP_LABELS[s.step] ?? `Step ${s.step}`} · <span className="font-mono">{s.file}</span>
        </span>
      </div>
      {s.error ? (
        <p className="text-sm text-error">Could not read {s.file}: {s.error}</p>
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <Stat value={s.qcms} label="QCMs" onClick={() => pickFilter('')} />
          <Stat value={s.with_answer} label="With answer" tone="good" onClick={() => pickFilter('no_answer')} />
          <Stat value={s.flagged} label="Need review" tone={s.flagged ? 'warn' : 'default'} onClick={() => pickFilter('needs_review')} />
          <Stat value={s.with_case} label="In a clinical case" onClick={() => pickFilter('has_case')} />
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2 pt-1">
        {mb?.import_file && (
          <button
            onClick={() => { void downloadFile(project, mb.step, mb.import_file!) }}
            className="flex items-center gap-2 h-10 px-4 rounded-xl bg-primary text-on-primary text-xs font-black hover:shadow-[0_0_18px_rgba(76,215,246,0.35)] transition-shadow"
          >
            <span className="material-symbols-outlined text-[18px]">upload_file</span>
            MBset import file{typeof mb.rows === 'number' ? ` · ${mb.rows} rows` : ''}
          </button>
        )}
        {mb?.report_file && (
          <button
            onClick={() => { void downloadFile(project, mb.step, mb.report_file!) }}
            className="flex items-center gap-2 h-10 px-4 rounded-xl border border-outline-variant/20 text-xs font-bold text-on-surface-variant hover:text-primary hover:border-primary/30"
            title="Rows not exported (rejected) and exported rows to check"
          >
            <span className="material-symbols-outlined text-[18px]">rule</span>
            MBset report
            {(typeof mb.rejected === 'number' || typeof mb.to_review === 'number') && (
              <span className="text-outline font-normal">· {mb.rejected ?? 0} rejected · {mb.to_review ?? 0} to check</span>
            )}
          </button>
        )}
        {newestWorkbook && (
          <>
            <button
              onClick={() => { void downloadFile(project, newestWorkbook.step, newestWorkbook.name) }}
              className="flex items-center gap-2 h-10 px-4 rounded-xl border border-outline-variant/20 text-xs font-bold text-on-surface-variant hover:text-primary hover:border-primary/30"
            >
              <span className="material-symbols-outlined text-[18px]">table_chart</span>
              Review workbook
            </button>
            <button
              onClick={() => { void openWorkbookInSheets(project, newestWorkbook.step, newestWorkbook.name) }}
              className="flex items-center gap-2 h-10 px-4 rounded-xl border border-outline-variant/20 text-xs font-bold text-on-surface-variant hover:text-[#34A853] hover:border-[#34A853]/30"
            >
              <span className="material-symbols-outlined text-[18px]">open_in_new</span>
              Open in Google Sheets
            </button>
          </>
        )}
        {!mb?.import_file && (
          <span className="text-[11px] text-outline">The MBset import file is built by Step 6 (corrections).</span>
        )}
      </div>
    </section>
  )
}

// ── Questions ───────────────────────────────────────────────────────────────

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return v
}

function QuestionsSection({ project, data }: { project: string; data: ProjectResults }) {
  const s = data.summary!
  const [filter, setFilter] = useState('')
  const [flag, setFlag] = useState('')
  const [session, setSession] = useState('')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [result, setResult] = useState<QcmPage | null>(null)
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState<QcmRow | null>(null)
  const q = useDebounced(search.trim(), 300)

  useEffect(() => {
    const fn = (f: string) => { setFilter(f); setFlag(''); setPage(1) }
    filterListeners.add(fn)
    return () => { filterListeners.delete(fn) }
  }, [])
  useEffect(() => { setPage(1) }, [filter, flag, session, q])

  useEffect(() => {
    let alive = true
    setLoading(true)
    fetchQcmPage(project, { filter, flag, session, q, page, size: 50 })
      .then((r) => { if (alive) setResult(r) })
      .catch((e) => { if (alive) toast.error(e?.message || 'Could not load questions') })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [project, filter, flag, session, q, page, data])   // `data` changes after a refresh

  const chips: { key: string; label: string; count: number }[] = [
    { key: '', label: 'All', count: s.qcms },
    { key: 'needs_review', label: 'Needs review', count: s.flagged },
    { key: 'no_answer', label: 'No answer', count: s.no_answer },
    { key: 'has_case', label: 'Has case', count: s.with_case },
  ]
  const pages = result ? Math.max(1, Math.ceil(result.total / result.size)) : 1

  return (
    <section id="results-questions" className="rounded-2xl bg-surface-container border border-outline-variant/10 overflow-hidden scroll-mt-20">
      <div className="p-4 sm:p-6 space-y-4 border-b border-outline-variant/10">
        <h2 className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">Questions</h2>
        <div className="flex flex-wrap items-center gap-2">
          {chips.map((c) => (
            <button
              key={c.key || 'all'}
              onClick={() => setFilter(c.key)}
              aria-pressed={filter === c.key}
              className={`h-8 px-3 rounded-full text-[11px] font-bold border transition-colors ${
                filter === c.key
                  ? c.key === 'needs_review' ? 'bg-tertiary/10 border-tertiary/40 text-tertiary' : 'bg-primary/10 border-primary/40 text-primary'
                  : 'border-outline-variant/20 text-outline hover:text-on-surface'
              }`}
            >
              {c.label} <span className="tabular-nums opacity-70">{c.count}</span>
            </button>
          ))}
          {s.flags.length > 0 && (
            <select
              value={flag}
              onChange={(e) => setFlag(e.target.value)}
              className="h-8 px-2 rounded-lg bg-surface-container-high border border-outline-variant/20 text-[11px] text-on-surface-variant"
              aria-label="Filter by flag"
            >
              <option value="">Any flag</option>
              {s.flags.map((f) => <option key={f.flag} value={f.flag}>{f.label} ({f.count})</option>)}
            </select>
          )}
          {s.sessions.length > 1 && (
            <select
              value={session}
              onChange={(e) => setSession(e.target.value)}
              className="h-8 px-2 rounded-lg bg-surface-container-high border border-outline-variant/20 text-[11px] text-on-surface-variant max-w-[14rem]"
              aria-label="Filter by session"
            >
              <option value="">All sessions</option>
              {s.sessions.map((x) => <option key={x.session} value={x.session}>{x.session} ({x.count})</option>)}
            </select>
          )}
          <div className="relative flex-1 min-w-[12rem]">
            <span className="material-symbols-outlined absolute left-2.5 top-1/2 -translate-y-1/2 text-[16px] text-outline">search</span>
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search text, options, or a number"
              className="w-full h-8 pl-8 pr-3 rounded-lg bg-surface-container-high border border-outline-variant/20 text-xs text-on-surface placeholder:text-outline focus:outline-none focus:border-primary/50"
            />
          </div>
        </div>
      </div>

      <div className={`overflow-x-auto ${loading ? 'opacity-60' : ''} transition-opacity`}>
        <table className="w-full text-xs">
          <thead className="bg-surface-container-high/50 text-[10px] uppercase tracking-widest text-outline">
            <tr>
              <th className="px-3 py-2 text-right w-12">#</th>
              <th className="px-3 py-2 text-right w-12">N°</th>
              <th className="px-3 py-2 text-left hidden md:table-cell">Session</th>
              <th className="px-3 py-2 text-left">Question</th>
              <th className="px-3 py-2 text-left w-16">Answer</th>
              <th className="px-3 py-2 text-left w-16">Flags</th>
            </tr>
          </thead>
          <tbody>
            {result?.rows.map((r) => (
              <tr
                key={r.row}
                onClick={() => setSelected(r)}
                className="border-t border-outline-variant/10 hover:bg-primary/[0.04] cursor-pointer"
              >
                <td className="px-3 py-2.5 text-right tabular-nums text-outline">{r.Num ?? r.row}</td>
                <td className="px-3 py-2.5 text-right tabular-nums text-on-surface-variant">{r.Number || '—'}</td>
                <td className="px-3 py-2.5 text-on-surface-variant hidden md:table-cell max-w-[12rem] truncate">{r.session || '—'}</td>
                <td className="px-3 py-2.5 text-on-surface max-w-[28rem]">
                  <span className="line-clamp-1">{r.Text}</span>
                  {r.Cas && <span className="text-[10px] text-secondary font-bold">Clinical case</span>}
                </td>
                <td className="px-3 py-2.5 font-black text-primary">{r.Correct || <span className="text-outline font-normal">—</span>}</td>
                <td className="px-3 py-2.5">
                  {r.review_flags.length > 0 ? (
                    <span title={r.flag_labels.join('\n')} className="inline-flex items-center gap-0.5 text-tertiary font-bold">
                      <span className="material-symbols-outlined text-[14px]">warning</span>{r.review_flags.length}
                    </span>
                  ) : <span className="text-outline">—</span>}
                </td>
              </tr>
            ))}
            {result && result.rows.length === 0 && (
              <tr><td colSpan={6} className="px-3 py-10 text-center text-outline italic">No question matches these filters.</td></tr>
            )}
          </tbody>
        </table>
      </div>
      {result && <Pager page={page} pages={pages} total={result.total} unit="questions" onPage={setPage} />}
      {selected && <QcmDrawer project={project} row={selected} onClose={() => setSelected(null)} />}
    </section>
  )
}

function correctLetters(c: string): Set<string> {
  return new Set((c.toUpperCase().match(/[A-F]/g) ?? []))
}

function QcmDrawer({ project, row, onClose }: { project: string; row: QcmRow; onClose: () => void }) {
  const right = correctLetters(row.Correct)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const openPage = async () => {
    const tab = window.open('about:blank', '_blank')
    try {
      const url = await fetchAuthenticatedBlobUrl(`${BASE_URL}/projects/${encodeURIComponent(project)}/pdf`)
      if (tab) tab.location.href = `${url}#page=${row.page}`
      setTimeout(() => URL.revokeObjectURL(url), 60000)
    } catch {
      tab?.close()
      toast.error('Could not open the PDF.')
    }
  }

  const meta: [string, string | number | null][] = [
    ['Exam number', row.Number || null],
    ['Session', row.session || null],
    ['Year', row.Year || null],
    ['Tag', row.Tag || null],
    ['Category', row.category || null],
    ['Page', row.page ?? null],
  ]

  return (
    <>
      <div className="fixed inset-0 bg-black/50 z-[60]" onClick={onClose} />
      <aside className="fixed right-0 top-0 h-full w-full sm:w-[520px] z-[70] bg-surface-container shadow-2xl border-l border-outline-variant/10 flex flex-col qe-fade-up" role="dialog" aria-label={`Question ${row.Num ?? row.row}`}>
        <div className="flex items-center justify-between px-6 h-16 border-b border-outline-variant/10 shrink-0">
          <h3 className="text-sm font-black text-on-surface">Question {row.Num ?? row.row}</h3>
          <button onClick={onClose} className="w-8 h-8 rounded-full hover:bg-surface-container-highest flex items-center justify-center text-outline" aria-label="Close">
            <span className="material-symbols-outlined text-[20px]">close</span>
          </button>
        </div>
        <div className="flex-1 overflow-y-auto custom-scrollbar p-6 space-y-5">
          {row.review_flags.length > 0 && (
            <div className="p-3 rounded-xl bg-tertiary/10 border border-tertiary/30 space-y-1">
              <p className="text-[10px] font-black uppercase tracking-widest text-tertiary">Needs review</p>
              <ul className="text-xs text-on-surface space-y-0.5">
                {row.flag_labels.map((l, i) => <li key={i}>• {l}</li>)}
              </ul>
            </div>
          )}
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
            {meta.filter(([, v]) => v !== null && v !== '').map(([k, v]) => (
              <div key={k}>
                <dt className="text-[10px] uppercase tracking-widest text-outline font-bold">{k}</dt>
                <dd className="text-on-surface-variant break-words">{String(v)}</dd>
              </div>
            ))}
          </dl>
          {row.Cas && (
            <div className="p-3 rounded-xl bg-secondary-container/20 border border-secondary/20">
              <p className="text-[10px] font-black uppercase tracking-widest text-secondary mb-1">Clinical case</p>
              <p className="text-xs text-on-surface whitespace-pre-wrap">{row.Cas}</p>
            </div>
          )}
          <p className="text-sm text-on-surface leading-relaxed whitespace-pre-wrap">{row.Text}</p>
          <ul className="space-y-1.5">
            {Object.entries(row.options).map(([k, v]) => (
              <li
                key={k}
                className={`flex gap-2 p-2 rounded-lg text-xs border ${
                  right.has(k) ? 'border-primary/40 bg-primary/5 text-on-surface' : 'border-outline-variant/10 text-on-surface-variant'
                }`}
              >
                <span className={`font-black w-4 shrink-0 ${right.has(k) ? 'text-primary' : 'text-outline'}`}>{k}</span>
                <span className="whitespace-pre-wrap">{v}</span>
              </li>
            ))}
          </ul>
          <p className="text-xs">
            <span className="text-outline">Answer: </span>
            <span className="font-black text-primary">{row.Correct || 'none found'}</span>
          </p>
          {row.origin_line && (
            <div>
              <p className="text-[10px] uppercase tracking-widest text-outline font-bold mb-1">Origin line</p>
              <p className="text-xs font-mono text-on-surface-variant">{row.origin_line}</p>
            </div>
          )}
        </div>
        {row.page !== null && row.page !== undefined && (
          <div className="p-4 border-t border-outline-variant/10 shrink-0">
            <button
              onClick={() => { void openPage() }}
              className="w-full flex items-center justify-center gap-2 h-10 rounded-xl border border-outline-variant/20 text-xs font-bold text-on-surface-variant hover:text-primary hover:border-primary/30"
            >
              <span className="material-symbols-outlined text-[18px]">picture_as_pdf</span>
              Open the PDF at page {row.page}
            </button>
          </div>
        )}
      </aside>
    </>
  )
}

// ── Files ───────────────────────────────────────────────────────────────────

function FilesSection({ project, data }: { project: string; data: ProjectResults }) {
  return (
    <section className="rounded-2xl bg-surface-container border border-outline-variant/10 p-4 sm:p-6 space-y-6">
      <h2 className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">Files</h2>
      {STEP_ORDER.filter((sid) => data.steps[sid]).map((sid) => (
        <StepFilesBlock key={sid} project={project} stepId={sid} step={data.steps[sid]} />
      ))}
    </section>
  )
}

const STATUS_STYLE: Record<string, string> = {
  done: 'text-primary bg-primary/10',
  running: 'text-primary bg-primary/10 qe-blink',
  stopping: 'text-amber-500 bg-amber-500/10',
  error: 'text-error bg-error/10',
  stopped: 'text-amber-500 bg-amber-500/10',
  cancelled: 'text-amber-500 bg-amber-500/10',
  idle: 'text-outline bg-outline-variant/10',
}

function StepFilesBlock({ project, stepId, step }: { project: string; stepId: string; step: StepResults }) {
  const [showOlder, setShowOlder] = useState(false)
  const [showWorking, setShowWorking] = useState(false)
  const [showHistory, setShowHistory] = useState(false)
  const empty = step.results.length === 0 && step.intermediate_count === 0 && step.older.length === 0
  const latest = step.results.map((r) => r.updated_at || '').sort().pop()

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 flex-wrap">
        <Link to={stepUrl(project, stepId)} className="text-xs font-black text-on-surface hover:text-primary">
          {STEP_LABELS[stepId]}
        </Link>
        <span className={`px-2 py-0.5 rounded-full text-[9px] font-black uppercase tracking-widest ${STATUS_STYLE[step.status] ?? STATUS_STYLE.idle}`}>
          {step.status}
        </span>
        {latest && <span className="text-[10px] text-outline">{latest}</span>}
        <span className="ml-auto text-[10px] text-outline">
          {step.results.length} result{step.results.length === 1 ? '' : 's'}
          {step.intermediate_count > 0 && ` · ${step.intermediate_count} working files`}
        </span>
      </div>
      {empty ? (
        <p className="text-[11px] text-outline italic px-1">No output yet.</p>
      ) : (
        <div className="space-y-2">
          {step.results.map((f) => (
            <ResultFileRow key={f.name} project={project} step={stepId} file={f} highlight={f.kind === 'mbset_import'} />
          ))}
          <div className="flex flex-wrap gap-2 pt-1">
            {step.older.length > 0 && (
              <Toggle open={showOlder} onClick={() => setShowOlder((v) => !v)} label={`${step.older.length} older workbook${step.older.length === 1 ? '' : 's'}`} />
            )}
            {step.intermediate_count > 0 && (
              <Toggle open={showWorking} onClick={() => setShowWorking((v) => !v)} label={`${step.intermediate_count} working files · ${formatBytes(step.intermediate_bytes)}`} />
            )}
            <Toggle open={showHistory} onClick={() => setShowHistory((v) => !v)} label="History" icon="history" />
          </div>
          {showOlder && (
            <div className="space-y-2 pl-3 border-l-2 border-outline-variant/10">
              {step.older.map((f) => <ResultFileRow key={f.name} project={project} step={stepId} file={f} />)}
            </div>
          )}
          {showWorking && <WorkingFiles project={project} stepId={stepId} />}
          {showHistory && <HistoryList project={project} stepId={stepId} />}
        </div>
      )}
    </div>
  )
}

function Toggle({ open, onClick, label, icon }: { open: boolean; onClick: () => void; label: string; icon?: string }) {
  return (
    <button
      onClick={onClick}
      aria-expanded={open}
      className={`flex items-center gap-1 h-7 px-2.5 rounded-lg text-[10px] font-bold border transition-colors ${
        open ? 'border-primary/30 text-primary bg-primary/5' : 'border-outline-variant/15 text-outline hover:text-on-surface'
      }`}
    >
      {icon && <span className="material-symbols-outlined text-[14px]">{icon}</span>}
      {label}
      <span className={`material-symbols-outlined text-[14px] transition-transform ${open ? 'rotate-90' : ''}`}>chevron_right</span>
    </button>
  )
}

function WorkingFiles({ project, stepId }: { project: string; stepId: string }) {
  const [folder, setFolder] = useState('')
  const [page, setPage] = useState(1)
  const [data, setData] = useState<FilesPage | null>(null)
  useEffect(() => {
    let alive = true
    fetchWorkingFiles(project, stepId, folder, page)
      .then((d) => { if (alive) setData(d) })
      .catch((e) => toast.error(e?.message || 'Could not list files'))
    return () => { alive = false }
  }, [project, stepId, folder, page])
  if (!data) return <p className="text-[11px] text-outline animate-pulse pl-3">Listing files…</p>
  const pages = Math.max(1, Math.ceil(data.total / data.size))
  return (
    <div className="pl-3 border-l-2 border-outline-variant/10 space-y-2">
      {data.groups.length > 1 && (
        <div className="flex flex-wrap gap-1">
          <FolderChip active={folder === ''} onClick={() => { setFolder(''); setPage(1) }} label="All" />
          {data.groups.map((g) => (
            <FolderChip key={g.folder} active={folder === g.folder} onClick={() => { setFolder(g.folder); setPage(1) }}
              label={`${g.folder || '(top)'} · ${g.count}`} />
          ))}
        </div>
      )}
      {data.files.map((f) => <ResultFileRow key={f.name} project={project} step={stepId} file={f} />)}
      <Pager page={page} pages={pages} total={data.total} unit="files" onPage={setPage} />
    </div>
  )
}

function FolderChip({ active, onClick, label }: { active: boolean; onClick: () => void; label: string }) {
  return (
    <button onClick={onClick} className={`h-6 px-2 rounded-md text-[10px] font-bold ${active ? 'bg-surface-container-highest text-primary' : 'text-outline hover:text-on-surface'}`}>
      {label}
    </button>
  )
}

function HistoryList({ project, stepId }: { project: string; stepId: string }) {
  const [runs, setRuns] = useState<HistoryRun[] | null>(null)
  const [openRun, setOpenRun] = useState<string | null>(null)
  useEffect(() => {
    let alive = true
    fetchResultHistory(project, stepId)
      .then((d) => { if (alive) setRuns(d.runs) })
      .catch((e) => { if (alive) { setRuns([]); toast.error(e?.message || 'Could not load history') } })
    return () => { alive = false }
  }, [project, stepId])
  if (!runs) return <p className="text-[11px] text-outline animate-pulse pl-3">Loading history…</p>
  if (runs.length === 0) return <p className="text-[11px] text-outline italic pl-3">No earlier runs kept.</p>
  return (
    <div className="pl-3 border-l-2 border-outline-variant/10 space-y-1">
      {runs.map((r) => (
        <div key={r.run_id}>
          <button
            onClick={() => setOpenRun(openRun === r.run_id ? null : r.run_id)}
            className="w-full flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-surface-container-high text-left"
          >
            <span className={`material-symbols-outlined text-[14px] text-outline transition-transform ${openRun === r.run_id ? 'rotate-90' : ''}`}>chevron_right</span>
            <span className="text-xs font-bold text-on-surface-variant">{prettyRunLabel(r.label)}</span>
            <span className="ml-auto text-[10px] text-outline">{r.file_count} files · {formatBytes(r.total_bytes)}</span>
          </button>
          {openRun === r.run_id && (
            <div className="space-y-2 py-2 pl-6">
              {r.results.length === 0
                ? <p className="text-[11px] text-outline italic">Only working files in this run.</p>
                : r.results.map((f) => (
                  <ResultFileRow key={f.name} project={project} step={stepId} file={f} runId={r.run_id} canDelete={false} />
                ))}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
