import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { downloadResultsZip, type ZipFiles } from '../../lib/api'
import { toast } from '../ui/Toaster'

/**
 * "Download results" — several projects' result files in one zip.
 * Default: Step 6 workbooks (.xlsx) of every project.
 */

const STEPS = [
  { id: '1', label: 'Step 1 · Text' },
  { id: '2', label: 'Step 2 · QCMs' },
  { id: '6', label: 'Step 6 · Corrections' },
  { id: '7', label: 'Step 7 · Categories' },
  { id: '8', label: 'Step 8 · Matches' },
]

const FILE_MODES: { id: ZipFiles; label: string; hint: string }[] = [
  { id: 'xlsx', label: 'Workbooks only (.xlsx)', hint: 'The result workbook + MBset import / report files' },
  { id: 'results', label: 'All result files', hint: 'Workbooks, MBset files and result JSON' },
  { id: 'all', label: 'Everything', hint: 'Including working files (Step 1 pages, per-page JSON…) — can be large' },
]

export function DownloadResultsButton({ projects, zipName, label = 'Download results', compact = false }: {
  projects: { name: string; note?: string }[]
  zipName: string
  label?: string
  compact?: boolean
}) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        disabled={projects.length === 0}
        className={`flex items-center gap-2 rounded-xl border border-outline-variant/20 text-xs font-bold text-on-surface-variant hover:text-primary hover:border-primary/30 transition-colors disabled:opacity-40 ${compact ? 'h-8 px-3' : 'h-9 px-3'}`}
      >
        <span className="material-symbols-outlined text-[18px]">download</span>
        {label}
      </button>
      {open && createPortal(
        <DownloadResultsDialog projects={projects} zipName={zipName} onClose={() => setOpen(false)} />,
        document.body,
      )}
    </>
  )
}

function DownloadResultsDialog({ projects, zipName, onClose }: {
  projects: { name: string; note?: string }[]
  zipName: string
  onClose: () => void
}) {
  const [steps, setSteps] = useState<string[]>(['6'])
  const [files, setFiles] = useState<ZipFiles>('xlsx')
  const [selected, setSelected] = useState<string[]>(() => projects.map((p) => p.name))
  const [busy, setBusy] = useState(false)
  const multi = projects.length > 1

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape' && !busy) onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [busy, onClose])

  const toggle = (list: string[], v: string) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v])

  const go = async () => {
    setBusy(true)
    try {
      const n = await downloadResultsZip({ projects: selected, steps, files, name: zipName })
      toast.success(`Downloaded ${n} file${n === 1 ? '' : 's'}`)
      onClose()
    } catch (e: any) {
      toast.error(e?.message || 'Download failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-[80]" onClick={() => !busy && onClose()} />
      <div role="dialog" aria-label="Download results"
        className="fixed z-[90] left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-[min(560px,calc(100vw-32px))] max-h-[calc(100vh-48px)] flex flex-col rounded-2xl bg-surface-container border border-outline-variant/15 shadow-2xl qe-pop">
        <div className="flex items-center justify-between px-6 h-16 border-b border-outline-variant/10 shrink-0">
          <h2 className="text-sm font-black text-on-surface">Download results</h2>
          <button onClick={onClose} disabled={busy} aria-label="Close"
            className="w-8 h-8 rounded-full hover:bg-surface-container-highest flex items-center justify-center text-outline">
            <span className="material-symbols-outlined text-[20px]">close</span>
          </button>
        </div>

        <div className="p-6 space-y-6 overflow-y-auto custom-scrollbar">
          <section className="space-y-2">
            <div className="flex items-center justify-between">
              <p className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">Steps</p>
              <div className="flex gap-2 text-[10px] font-bold">
                <button onClick={() => setSteps(STEPS.map((s) => s.id))} className="text-primary hover:underline">All</button>
                <button onClick={() => setSteps(['6'])} className="text-outline hover:text-on-surface">Only Step 6</button>
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              {STEPS.map((s) => (
                <Chip key={s.id} on={steps.includes(s.id)} onClick={() => setSteps((v) => toggle(v, s.id))}>{s.label}</Chip>
              ))}
            </div>
          </section>

          <section className="space-y-2">
            <p className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">Files</p>
            <div className="space-y-1.5">
              {FILE_MODES.map((m) => (
                <label key={m.id}
                  className={`flex items-start gap-3 p-3 rounded-xl border cursor-pointer transition-colors ${
                    files === m.id ? 'border-primary/40 bg-primary/5' : 'border-outline-variant/10 hover:border-outline-variant/30'
                  }`}>
                  <input type="radio" name="zip-files" checked={files === m.id} onChange={() => setFiles(m.id)} className="mt-0.5 accent-[var(--tw-color-primary,#4cd7f6)]" />
                  <span>
                    <span className="block text-xs font-bold text-on-surface">{m.label}</span>
                    <span className="block text-[11px] text-outline">{m.hint}</span>
                  </span>
                </label>
              ))}
            </div>
          </section>

          {multi && (
            <section className="space-y-2">
              <div className="flex items-center justify-between">
                <p className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">
                  PDFs · {selected.length} of {projects.length}
                </p>
                <div className="flex gap-2 text-[10px] font-bold">
                  <button onClick={() => setSelected(projects.map((p) => p.name))} className="text-primary hover:underline">All</button>
                  <button onClick={() => setSelected([])} className="text-outline hover:text-on-surface">None</button>
                </div>
              </div>
              <div className="max-h-56 overflow-y-auto custom-scrollbar space-y-1 pr-1">
                {projects.map((p) => (
                  <label key={p.name} className="flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-surface-container-high cursor-pointer">
                    <input type="checkbox" checked={selected.includes(p.name)}
                      onChange={() => setSelected((v) => toggle(v, p.name))} />
                    <span className="text-xs text-on-surface truncate flex-1">{p.name}</span>
                    {p.note && <span className="text-[10px] text-outline shrink-0">{p.note}</span>}
                  </label>
                ))}
              </div>
            </section>
          )}
        </div>

        <div className="px-6 py-4 border-t border-outline-variant/10 flex items-center justify-between gap-3 shrink-0">
          <p className="text-[11px] text-outline">One .zip · a folder per PDF and per step</p>
          <button
            onClick={() => { void go() }}
            disabled={busy || steps.length === 0 || selected.length === 0}
            className="flex items-center gap-2 h-10 px-5 rounded-xl bg-primary text-on-primary text-xs font-black disabled:opacity-40"
          >
            <span className={`material-symbols-outlined text-[18px] ${busy ? 'animate-spin' : ''}`}>{busy ? 'progress_activity' : 'download'}</span>
            {busy ? 'Preparing zip…' : 'Download .zip'}
          </button>
        </div>
      </div>
    </>
  )
}

function Chip({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" onClick={onClick} aria-pressed={on}
      className={`h-8 px-3 rounded-full text-[11px] font-bold border transition-colors ${
        on ? 'bg-primary/10 border-primary/40 text-primary' : 'border-outline-variant/20 text-outline hover:text-on-surface'
      }`}>
      {children}
    </button>
  )
}
