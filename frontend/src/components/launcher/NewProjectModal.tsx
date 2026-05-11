import { useState, useEffect, useRef, DragEvent } from 'react'
import { createProject, uploadProjectPdf } from '../../lib/api'
import { Project } from '../../types'

interface NewProjectModalProps {
  onSuccess: (project: Project) => void
}

type Stage = 'pick' | 'uploading' | 'done' | 'error'

export function NewProjectModal({ onSuccess }: NewProjectModalProps) {
  const [file, setFile] = useState<File | null>(null)
  const [projectName, setProjectName] = useState('')
  const [stage, setStage] = useState<Stage>('pick')
  const [uploadPct, setUploadPct] = useState(0)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [isDragOver, setIsDragOver] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Auto-derive project name from file name
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

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    if (!file || !projectName) return

    setStage('uploading')
    setErrorMsg(null)
    setUploadPct(0)

    try {
      // Step 1 — create project folder (no pdf_path yet)
      const project = await createProject({ name: projectName, pdf_path: '' })

      // Step 2 — upload PDF into container volume
      const uploaded = await uploadProjectPdf(projectName, file, (pct) => {
        setUploadPct(pct)
      })

      // Return updated project with the internal pdf_path
      setStage('done')
      onSuccess({ ...project, pdf_path: uploaded.pdf_path })

    } catch (err: any) {
      setStage('error')
      setErrorMsg(err.message ?? 'Upload failed. Please try again.')
    }
  }

  const isReady = file !== null && projectName.length > 0 && stage === 'pick'

  return (
    <form onSubmit={handleCreate} className="space-y-6">

      {/* Drop Zone */}
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

      {/* Project Name */}
      {file && (
        <div className="space-y-2 animate-in fade-in slide-in-from-bottom-2 duration-300">
          <label className="text-xs font-bold uppercase tracking-widest text-outline">
            Project Name
          </label>
          <input
            id="input-project-name"
            type="text"
            value={projectName}
            onChange={(e) => setProjectName(e.target.value.replace(/\s+/g, '_'))}
            className="w-full bg-surface-container-lowest border border-outline-variant/30 rounded-xl px-4 py-3 text-sm focus:border-primary focus:ring-1 focus:ring-primary outline-none transition-all"
            placeholder="my_extraction_project"
            required
          />
          <p className="text-[10px] text-outline opacity-60">
            Auto-derived from filename. You can edit it.
          </p>
        </div>
      )}

      {/* Upload Progress */}
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

      {/* Error */}
      {errorMsg && (
        <div className="p-3 rounded-lg bg-error-container/10 border border-error/20 text-error text-xs font-medium animate-in fade-in duration-200">
          {errorMsg}
        </div>
      )}

      {/* Submit */}
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
    </form>
  )
}
