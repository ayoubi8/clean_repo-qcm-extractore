import { useState, useRef, ChangeEvent } from 'react'
import { scanDriveFolder, runBatch, createProject, uploadProjectPdf, fetchProjects } from '../../../lib/api'
import { defaultWizardConfig, buildBatchConfig, WizardConfig, BatchConfigForm } from './BatchConfigForm'
import { WizardFileEntry, Project } from '../../../types'

/**
 * Auto Run wizard (plan docs/plans/autorun-batch-plan.md Â§3.2):
 *   source â†’ files â†’ config â†’ starting
 * Runs steps 1 â†’ 2 â†’ 6 on every PDF (parallel 5-at-a-time, sequential per PDF;
 * engine: phases/Â§4.2). Steps 7â€“8 are excluded by design (resolved Q6/Q7).
 */

const MAX_FILES = 10 // matches MAX_AUTORUN_BATCH_FILES (resolved Q11)

type Stage = 'source' | 'files' | 'config' | 'starting'

interface AutoRunWizardProps {
  onStarted: (batchId: string) => void
}

/** Client-side 3-parallel upload pool (resolved Q10). */
async function runPool<T>(items: T[], limit: number, fn: (item: T, i: number) => Promise<void>) {
  let index = 0
  const workers = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (index < items.length) {
      const i = index++
      await fn(items[i], i)
    }
  })
  await Promise.all(workers)
}

/** AR_ namer with the same prefix/collision rules as the backend (resolved Q3). */
function makeArNamer(taken: Set<string>) {
  return (displayName: string) => {
    let clean = displayName.replace(/\.pdf$/i, '').trim()
      .replace(/[^A-Za-z0-9._-]+/g, '_')
      .replace(/^[._-]+|[._-]+$/g, '')
      .slice(0, 60)
    clean = clean.replace(/^[._-]+|[._-]+$/g, '') || 'pdf'
    let candidate = `AR_${clean}`
    let n = 2
    while (taken.has(candidate)) {
      candidate = `AR_${clean}_${n}`
      n += 1
    }
    taken.add(candidate)
    return candidate
  }
}

export function AutoRunWizard({ onStarted }: { onStarted: (batchId: string) => void }) {
  const [stage, setStage] = useState<Stage>('source')
  const [mode, setMode] = useState<'drive' | 'folder'>('drive')
  const [folderLink, setFolderLink] = useState('')
  const [scanning, setScanning] = useState(false)
  const [entries, setEntries] = useState<WizardFileEntry[]>([])
  const [folderTotal, setFolderTotal] = useState(0)
  const [folderName, setFolderName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [config, setConfig] = useState<WizardConfig>(defaultWizardConfig())
  const [starting, setStarting] = useState(false)
  const [uploadDone, setUploadDone] = useState(0)
  const [uploadTotal, setUploadTotal] = useState(0)
  const [rowErrors, setRowErrors] = useState<Record<string, string>>({})
  const folderInputRef = useRef<HTMLInputElement>(null)

  const selCount = entries.filter(e => e.selected).length

  function updateConfig(c: Partial<WizardConfig>) { setConfig(prev => ({ ...prev, ...c })) }

  function toggle(key: string) {
    setEntries(prev => prev.map(e => e.key === key ? { ...e, selected: !e.selected } : e))
  }

  function toggleAll() {
    const allSelected = entries.every(e => e.selected)
    setEntries(prev => prev.map(e => ({ ...e, selected: !allSelected })))
  }

  function backToSource() { setStage('source'); setError(null) }
  function backToFiles() { setStage('files'); setError(null) }

  async function handleImport() {
    setError(null)
    if (mode === 'drive') {
      setScanning(true)
      try {
        const res = await scanDriveFolder(folderLink.trim())
        setFolderName(res.folder_name)
        setFolderTotal(res.total_in_folder)
        const existing = new Set((await fetchProjects()).map(p => p.name))
        const namer = makeArNamer(existing)
        setEntries(res.files.map(f => ({
          key: f.file_id,
          display_name: f.name,
          drive_file_id: f.file_id,
          ar_name: namer(f.name),
          selected: true,
        })))
        setStage('files')
      } catch (e: any) {
        setError(e.message ?? 'Folder scan failed.')
      } finally {
        setScanning(false)
      }
    } else {
      folderInputRef.current?.click()
    }
  }

  async function handleFolderPick(e: ChangeEvent<HTMLInputElement>) {
    setError(null)
    const all = Array.from(e.target.files ?? []) as File[]
    e.target.value = ''
    const pdfs = all
      .filter(f => f.name.toLowerCase().endsWith('.pdf'))
      .filter(f => {
        const rp = ((f as any).webkitRelativePath as string) || ''
        return rp ? rp.split('/').filter(Boolean).length <= 2 : true   // top-level only (resolved Q4)
      })
    if (pdfs.length === 0) {
      setError('No PDF files found at the top level of that folder.')
      return
    }
    setFolderName(pdfs[0].webkitRelativePath?.split('/')[0] ?? '')
    setFolderTotal(pdfs.length)
    const existing = new Set((await fetchProjects()).map(p => p.name))
    const namer = makeArNamer(existing)
    setEntries(pdfs.slice(0, MAX_FILES).map(f => ({
      key: ((f as any).webkitRelativePath || f.name),
      display_name: f.name,
      size: f.size,
      file: f,
      ar_name: namer(f.name),
      selected: true,
    })))
    setStage('files')
  }

  async function handleStart() {
    setError(null)
    setStarting(true)
    const selected = entries.filter(e => e.selected)
    try {
      let batchId: string
      if (mode === 'folder') {
        const usable = selected.filter(e => e.file)
        setUploadTotal(usable.length)
        setUploadDone(0)
        const names: string[] = []
        const errs: Record<string, string> = {}
        let done = 0
        await runPool(usable, 3, async (e) => {
          try {
            await createProject({ name: e.ar_name, pdf_path: '' })
            await uploadProjectPdf(e.ar_name, e.file!, () => {})
            names.push(e.ar_name)
          } catch (err: any) {
            errs[e.key] = err?.message ?? 'Upload failed'
          } finally {
            done += 1
            setUploadDone(done)
          }
        })
        if (names.length === 0) {
          setError('No files uploaded â€” nothing to run.')
          setStarting(false)
          return
        }
        const { batch_id } = await runBatch({
          source: 'upload',
          project_names: names,
          config: buildBatchConfig(config),
        })
        batchId = batch_id
      } else {
        const { batch_id } = await runBatch({
          source: 'drive',
          drive_files: selected.filter(e => e.drive_file_id).map(e => ({
            file_id: e.drive_file_id!, name: e.display_name,
          })),
          config: buildBatchConfig(config),
        })
        batchId = batch_id
      }
      onStarted(batchId)
    } catch (e: any) {
      setError(e.message ?? 'Failed to start the batch.')
    } finally {
      setStarting(false)
    }
  }

  const stepper = (
    <div className="flex items-center justify-center gap-2 mb-2">
      {['Source', 'Files', 'Config'].map((label, i) => {
        const order = ['source', 'files', 'config']
        const idx = order.indexOf(stage === 'starting' ? 'config' : stage)
        const active = i === idx
        const passed = i < idx
        return (
          <div key={label} className="flex items-center gap-2">
            {i > 0 && <span className={`material-symbols-outlined text-[14px] ${passed || active ? 'text-primary' : 'text-outline'}`}>chevron_right</span>}
            <span className={`text-[9px] font-black uppercase tracking-widest ${
              active ? 'text-primary' : passed ? 'text-on-surface-variant' : 'text-outline'
            }`}>{label}</span>
          </div>
        )
      })}
    </div>
  )

  return (
    <div className="max-h-[72vh] overflow-y-auto custom-scrollbar space-y-5 pr-1">
      {stepper}

      {/* â”€â”€ Stage 1 Â· Source â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */}
      {stage === 'source' && (
        <div className="space-y-5 animate-in fade-in duration-300">
          <div className="flex gap-2">
            {([
              { id: 'drive', label: 'Drive folder link', icon: 'add_link' },
              { id: 'folder', label: 'Local folder', icon: 'folder_open' },
            ] as const).map(t => (
              <button
                key={t.id}
                id={`tab-ar-${t.id}`}
                type="button"
                onClick={() => { setMode(t.id); setError(null) }}
                className={`flex-1 py-2.5 rounded-xl text-xs font-bold border transition-all flex items-center justify-center gap-1.5 ${
                  mode === t.id
                    ? 'border-primary bg-primary/10 text-primary'
                    : 'border-outline-variant/20 bg-surface-container-low text-outline hover:text-on-surface'
                }`}
              >
                <span className="material-symbols-outlined text-[16px]">{t.icon}</span>
                {t.label}
              </button>
            ))}
          </div>

          {mode === 'drive' ? (
            <div className="space-y-2 animate-in fade-in duration-300">
              <input
                id="ar-input-drive-folder-link"
                type="url"
                value={folderLink}
                onChange={(e) => setFolderLink(e.target.value)}
                placeholder="https://drive.google.com/drive/folders/â€¦"
                className="w-full bg-surface-container-lowest border border-outline-variant/20 rounded-xl px-4 py-3 text-sm focus:border-primary outline-none transition-all"
              />
              <p className="text-[10px] text-outline leading-tight">
                The folder must be shared as <span className="font-bold text-outline/80">"Anyone with the link â†’ Viewer"</span> â€” top-level PDFs only.
              </p>
            </div>
          ) : (
            <p className="text-[10px] text-outline">
              All PDFs at the top level of the selected folder are uploaded (up to {MAX_FILES}).
            </p>
          )}

          <button
            id="btn-ar-import"
            onClick={handleImport}
            disabled={scanning || (mode === 'drive' && !folderLink.trim())}
            className="w-full py-3.5 bg-primary text-on-primary rounded-xl font-black uppercase tracking-tighter flex items-center justify-center gap-2 hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-[0_4px_20px_rgba(76,215,246,0.3)]"
          >
            {scanning ? (
              <>
                <span className="material-symbols-outlined animate-spin text-sm">progress_activity</span>
                Scanning folderâ€¦
              </>
            ) : (
              <>
                <span className="material-symbols-outlined">{mode === 'drive' ? 'add_link' : 'folder_open'}</span>
                {mode === 'drive' ? 'Import from Drive folder' : 'Select folder'}
              </>
            )}
          </button>

          <input
            ref={folderInputRef}
            type="file"
            multiple
            hidden
            onChange={handleFolderPick}
            {...({ webkitdirectory: '' } as any)}
          />
        </div>
      )}

      {/* â”€â”€ Stage 2 Â· Found files â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */}
      {stage === 'files' && (
        <div className="space-y-4 animate-in fade-in duration-300">
          {folderName && (
            <div className="flex items-center gap-2 text-[11px] text-outline font-mono truncate">
              <span className="material-symbols-outlined text-[14px]">folder</span>
              {folderName}
            </div>
          )}
          {folderTotal > entries.length && (
            <div className="p-3 rounded-lg bg-secondary-container/10 border border-secondary/30 text-secondary text-[11px] font-bold flex items-start gap-2">
              <span className="material-symbols-outlined text-base mt-0.5">info</span>
              Folder has {folderTotal} PDFs â€” a batch runs at most {MAX_FILES}. Showing the first {entries.length}.
            </div>
          )}

          <div className="flex items-center justify-between px-1">
            <span className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">
              {selCount} selected
            </span>
            <button
              id="btn-ar-select-all"
              onClick={toggleAll}
              className="text-[10px] font-bold uppercase tracking-widest text-outline hover:text-primary transition-colors"
            >
              {entries.every(e => e.selected) ? 'Deselect all' : 'Select all'}
            </button>
          </div>

          <div className="space-y-2 max-h-[240px] overflow-y-auto custom-scrollbar pr-1">
            {entries.map(e => (
              <div
                key={e.key}
                onClick={() => toggle(e.key)}
                className={`flex items-center gap-3 p-3 cursor-pointer rounded-xl border transition-all ${
                  e.selected
                    ? 'border-primary/40 bg-primary/5'
                    : 'bg-surface-container-low border-outline-variant/10 hover:border-outline-variant/30'
                }`}
              >
                <input
                  type="checkbox"
                  checked={e.selected}
                  onClick={(ev) => ev.stopPropagation()}
                  onChange={() => toggle(e.key)}
                  className="w-4 h-4 rounded shrink-0 border-primary/40 text-primary focus:ring-primary"
                />
                <span className="material-symbols-outlined text-[18px] text-outline shrink-0">picture_as_pdf</span>
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-bold text-on-surface truncate">{e.display_name}</p>
                  <p className="text-[10px] text-outline font-mono truncate mt-0.5">will run as {e.ar_name}</p>
                </div>
                <span className="text-[10px] text-outline tabular-nums shrink-0">
                  {e.size ? `${(e.size / 1024 / 1024).toFixed(2)} MB` : ''}
                </span>
              </div>
            ))}
          </div>

          <div className="flex gap-2">
            <button
              id="btn-ar-back-source"
              onClick={backToSource}
              className="px-4 py-3.5 rounded-xl border border-outline-variant/20 bg-surface-container-low text-outline text-xs font-black uppercase tracking-widest hover:text-on-surface transition-colors"
            >
              <span className="material-symbols-outlined text-[16px]">arrow_back</span>
            </button>
            <button
              id="btn-ar-to-config"
              onClick={() => setStage('config')}
              disabled={selCount === 0}
              className="flex-1 py-3.5 bg-primary text-on-primary rounded-xl font-black uppercase tracking-tighter flex items-center justify-center gap-2 hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-[0_4px_20px_rgba(76,215,246,0.3)]"
            >
              <span className="material-symbols-outlined">tune</span>
              Configure ({selCount})
            </button>
          </div>
        </div>
      )}

      {/* â”€â”€ Stage 3 Â· Config â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */}
      {stage === 'config' && (
        <div className="space-y-5 animate-in fade-in duration-300">
          <BatchConfigForm config={config} onChange={updateConfig} />

          <div className="flex gap-2">
            <button
              id="btn-ar-back-files"
              onClick={backToFiles}
              className="px-4 py-3.5 rounded-xl border border-outline-variant/20 bg-surface-container-low text-outline text-xs font-black uppercase tracking-widest hover:text-on-surface transition-colors"
            >
              <span className="material-symbols-outlined text-[16px]">arrow_back</span>
            </button>
            <button
              id="btn-ar-start-batch"
              onClick={handleStart}
              disabled={starting || selCount === 0}
              className="flex-1 py-3.5 bg-gradient-to-r from-primary to-primary-container text-on-primary font-black uppercase tracking-widest rounded-2xl flex items-center justify-center gap-3 hover:shadow-[0_8px_30px_rgba(76,215,246,0.4)] hover:scale-[1.01] transition-all disabled:opacity-30 disabled:grayscale"
            >
              {starting ? (
                <>
                  <span className="material-symbols-outlined animate-spin">progress_activity</span>
                  {mode === 'folder' && uploadTotal > 0 ? `Uploading ${uploadDone}/${uploadTotal}` : 'Startingâ€¦'}
                </>
              ) : (
                <>
                  <span className="material-symbols-outlined">rocket_launch</span>
                  Start Auto Run ({selCount})
                </>
              )}
            </button>
          </div>
        </div>
      )}

      {/* â”€â”€ Starting progress â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */}
      {stage === 'config' && starting && mode === 'folder' && uploadTotal > 0 && (
        <div className="space-y-2 animate-in fade-in duration-200">
          <div className="flex items-center justify-between text-xs text-outline">
            <span>Uploading PDFs (3 at a time)â€¦</span>
            <span className="font-bold text-primary">{uploadDone}/{uploadTotal}</span>
          </div>
          <div className="w-full h-2 bg-surface-container-low rounded-full overflow-hidden">
            <div
              className="h-full bg-primary rounded-full transition-all duration-200"
              style={{ width: `${Math.round((uploadDone / uploadTotal) * 100)}%` }}
            />
          </div>
        </div>
      )}
      {stage === 'config' && starting && mode === 'drive' && (
        <div className="space-y-2 animate-in fade-in duration-200">
          <div className="flex items-center justify-between text-xs text-outline">
            <span>Registering the batchâ€¦</span>
            <span className="inline-flex items-center gap-1 text-primary font-bold">
              <span className="material-symbols-outlined animate-spin text-[14px]">progress_activity</span>
              working
            </span>
          </div>
          <div className="relative w-full h-2 bg-surface-container-low rounded-full overflow-hidden">
            <div className="absolute inset-y-0 left-0 w-1/3 bg-primary rounded-full animate-pulse" />
          </div>
        </div>
      )}

      {/* Row-level upload errors (one failed file doesn't abort the batch) */}
      {Object.keys(rowErrors).length > 0 && (
        <div className="p-3 rounded-lg bg-error-container/10 border border-error/20 space-y-1">
          {Object.entries(rowErrors).map(([k, msg]) => (
            <p key={k} className="text-[10px] text-error font-medium truncate">âš  {msg}</p>
          ))}
        </div>
      )}

      {error && (
        <div className="p-3 rounded-lg bg-error-container/10 border border-error/20 text-error text-xs font-medium animate-in fade-in duration-200">
          {error}
        </div>
      )}
    </div>
  )
}




