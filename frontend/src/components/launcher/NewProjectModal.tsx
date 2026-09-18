import { useState, useEffect, useRef, DragEvent } from 'react'
import { createProject, uploadProjectPdf, importPdfFromDrive } from '../../lib/api'
import { Project } from '../../types'

interface NewProjectModalProps {
  onSuccess: (project: Project) => void
}

type Stage = 'pick' | 'uploading' | 'importing' | 'done' | 'error'
type Mode = 'file' | 'link'

export function NewProjectModal({ onSuccess }: NewProjectModalProps) {
  const [file, setFile] = useState<File | null>(null)
  const [projectName, setProjectName] = useState('')
  const [stage, setStage] = useState<Stage>('pick')
  const [uploadPct, setUploadPct] = useState(0)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [isDragOver, setIsDragOver] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // ── Drive link import (additive — file mode is untouched) ──
  const [mode, setMode] = useState<Mode>('file')
  const [driveLink, setDriveLink] = useState('')
  const [recognized, setRecognized] = useState<string | null>(null)

  // Auto-derive project name from file name (file mode only)
  useEffect(() => {
    if (file) {
      const name = file.name.replace(/\.pdf$/i, '').replace(/\s+/g, '_')
      setProjectName(name)
    }
  }, [file])

  function handleDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault()
    setIsDragOver(false)
    const dropped = e.dataTransfer.files[0]
    if (dropped && dropped.name.toLowerCase().endsWith('.pdf')) {
      setFile(dropped)
      setErrorMsg(null)
    } else {
      setErrorMsg('Please drop a PDF file.')
    }
  }

  function handleFileInput(e: React.ChangeEvent<HTMLInputElement>) {
    const selected = e.target.files?.[0]
    if (selected) {
      setFile(selected)
      setErrorMsg(null)
    }
  }

  // Loose client-side sanity flag — the backend re-validates strictly.
  useEffect(() => {
    const link = driveLink.trim()
    if (!link) { setRecognized(null); return }
    const m = link.match(/drive\.google\.com\/(?:file\/d\/([A-Za-z0-9_-]+)|\?.*id=([A-Za-z0-9_-]+))/)
    setRecognized(m ? 'Drive file detected — click Import below.' : null)
  }, [driveLink])

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    if (!projectName) return
    if (mode === 'file' && !file) return

    setStage(mode === 'file' ? 'uploading' : 'importing')
    setErrorMsg(null)
    setUploadPct(0)

    try {
      // Step 1 — create project folder (no pdf_path yet)
      const project = await createProject({ name: projectName, pdf_path: '' })

      if (mode === 'file') {
        // Step 2 — upload PDF into container volume
        const uploaded = await uploadProjectPdf(projectName, file!, (pct) => {
          setUploadPct(pct)
        })
        // Return updated project with the internal pdf_path
        setStage('done')
        onSuccess({ ...project, pdf_path: uploaded.pdf_path })
      } else {
        // Step 2 — download from Google Drive (same ingest tail server-side)
        const imported = await importPdfFromDrive(projectName, driveLink.trim())
        setStage('done')
        onSuccess({ ...project, pdf_path: imported.pdf_path })
      }
    } catch (err: any) {
      setStage('error')
      setErrorMsg(err.message ?? 'Import failed. Please try again.')
    }
  }

  const isReady = stage === 'pick' && projectName.length > 0 &&
    (mode === 'link' ? driveLink.trim().length > 0 : file !== null)

  const busy = stage === 'uploading' || stage === 'importing'

  return (
    <form onSubmit={handleCreate} className="space-y-6">

      {/* Mode switch */}
      <div className="flex gap-2">
        {([
          { id: 'file', label: 'Upload PDF', icon: 'upload_file' },
          { id: 'link', label: 'Google Drive link', icon: 'add_link' },
        ] as const).map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => { setMode(t.id); setStage('pick'); setErrorMsg(null) }}
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

      {/* Drop Zone (file mode) */}
      {mode === 'file' && (
        <div
          onDragOver={(e) => { e.preventDefault(); setIsDragOver(true) }}
          onDragLeave={() => setIsDragOver(false)}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}
          className={`relative flex flex-col items-center justify-center gap-3 p-8 rounded-2xl border-2 border-dashed cursor-pointer transition-all duration-200 ${
            isDragOver
              ? 'border-primary bg-primary/10 scale-[1.01]'
              : file
              ? 'border-primary/40 bg-primary/5'
              : 'border-outline-variant/30 bg-surface-container-low hover:border-primary/40 hover:bg-primary/5'
          }`}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf"
            className="hidden"
            onChange={handleFileInput}
          />

          {file ? (
            <>
              <span className="material-symbols-outlined text-4xl text-primary">picture_as_pdf</span>
              <div className="text-center">
                <p className="text-sm font-bold text-on-surface">{file.name}</p>
                <p className="text-[11px] text-outline mt-1">
                  {(file.size / 1024 / 1024).toFixed(2)} MB · Click to change
                </p>
              </div>
            </>
          ) : (
            <>
              <span className="material-symbols-outlined text-4xl text-outline">upload_file</span>
              <div className="text-center">
                <p className="text-sm font-semibold text-on-surface">Drop your PDF here</p>
                <p className="text-[11px] text-outline mt-1">or click to browse</p>
              </div>
            </>
          )}
        </div>
      )}

      {/* Drive Link Import (link mode) */}
      {mode === 'link' && (
        <div className="space-y-2 animate-in fade-in slide-in-from-bottom-2 duration-300">
          <div className="flex items-center gap-2 p-4 rounded-xl border border-outline-variant/15 bg-surface-container-low">
            <span className="material-symbols-outlined text-lg text-[#34A853]">add_link</span>
            <span className="text-xs font-bold text-on-surface">Paste a Google Drive PDF link</span>
            <span className="material-symbols-outlined text-lg text-[#34A853] ml-auto">picture_as_pdf</span>
          </div>
          <input
            id="input-drive-link"
            type="url"
            value={driveLink}
            onChange={(e) => setDriveLink(e.target.value)}
            placeholder="https://drive.google.com/file/d/…/view"
            className="w-full bg-surface-container-lowest border border-outline-variant/20 rounded-xl px-4 py-3 text-sm focus:border-primary outline-none transition-all"
          />
          <p className="text-[10px] text-outline leading-tight">
            {recognized
              ? <span className="text-[#34A853] font-bold">{recognized}</span>
              : <>The file must be shared as <span className="font-bold text-outline/80">"Anyone with the link → Viewer"</span> — the server downloads it without any Google login.</>
            }
          </p>
        </div>
      )}

      {/* Divider */}
      <div className="flex items-center gap-3">
        <div className="flex-1 h-px bg-outline-variant/20" />
        <span className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">
          project
        </span>
        <div className="flex-1 h-px bg-outline-variant/20" />
      </div>

      {/* Project Name */}
      <div className="space-y-2 animate-in fade-in slide-in-from-bottom-2 duration-300">
        <label className="text-xs font-bold uppercase tracking-widest text-outline">
          Project Name
        </label>
        <input
          id="input-project-name"
          type="text"
          value={projectName}
          onChange={(e) => setProjectName(e.target.value.replace(/[^A-Za-z0-9._-]+/g, '_'))}
          className="w-full bg-surface-container-lowest border border-outline-variant/30 rounded-xl px-4 py-3 text-sm focus:border-primary focus:ring-1 focus:ring-primary outline-none transition-all"
          placeholder="my_extraction_project"
          required
        />
        <p className="text-[10px] text-outline opacity-60">
          {mode === 'file' && file
            ? 'Auto-derived from filename. You can edit it.'
            : 'Letters, numbers, dots, dashes or underscores.'}
        </p>
      </div>

      {/* Upload Progress (file mode) */}
      {stage === 'uploading' && (
        <div className="space-y-2 animate-in fade-in duration-200">
          <div className="flex items-center justify-between text-xs text-outline">
            <span>Uploading PDF into workspace…</span>
            <span className="font-bold text-primary">{uploadPct}%</span>
          </div>
          <div className="w-full h-2 bg-surface-container-low rounded-full overflow-hidden">
            <div
              className="h-full bg-primary rounded-full transition-all duration-200"
              style={{ width: `${uploadPct}%` }}
            />
          </div>
        </div>
      )}

      {/* Drive import progress (server-side download — indeterminate) */}
      {stage === 'importing' && (
        <div className="space-y-2 animate-in fade-in duration-200">
          <div className="flex items-center justify-between text-xs text-outline">
            <span>Importing PDF from Google Drive…</span>
            <span className="inline-flex items-center gap-1 text-primary font-bold">
              <span className="material-symbols-outlined animate-spin text-[14px]">progress_activity</span>
              working
            </span>
          </div>
          <div className="relative w-full h-2 bg-surface-container-low rounded-full overflow-hidden">
            <div className="absolute inset-y-0 left-0 w-1/3 bg-primary rounded-full animate-pulse" />
          </div>
          <p className="text-[10px] text-outline opacity-70">
            Large files can take a minute. Keep the tab open.
          </p>
        </div>
      )}

      {/* Error */}
      {errorMsg && (
        <div className="p-3 rounded-lg bg-error-container/10 border border-error/20 text-error text-xs font-medium animate-in fade-in duration-200">
          {errorMsg}
        </div>
      )}

      {/* Submit */}
      {mode === 'file' ? (
        <button
          id="btn-create-project"
          type="submit"
          disabled={!isReady}
          className="w-full py-4 bg-primary text-on-primary rounded-xl font-black uppercase tracking-tighter flex items-center justify-center gap-2 hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-[0_4px_20px_rgba(76,215,246,0.3)]"
        >
          {stage === 'uploading' ? (
            <>
              <span className="material-symbols-outlined animate-spin text-sm">refresh</span>
              Uploading…
            </>
          ) : (
            <>
              <span className="material-symbols-outlined">upload</span>
              {file ? 'Upload & Create Project' : 'Select a PDF first'}
            </>
          )}
        </button>
      ) : (
        <button
          id="btn-import-drive"
          type="submit"
          disabled={!isReady || busy}
          className="w-full py-4 bg-primary text-on-primary rounded-xl font-black uppercase tracking-tighter flex items-center justify-center gap-2 hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-[0_4px_20px_rgba(76,215,246,0.3)]"
        >
          {busy ? (
            <>
              <span className="material-symbols-outlined animate-spin text-sm">refresh</span>
              Importing…
            </>
          ) : (
            <>
              <span className="material-symbols-outlined">add_link</span>
              Import from Drive & Create Project
            </>
          )}
        </button>
      )}
    </form>
  )
}
