import { useState, useEffect } from 'react'
import { fetchStepOutput, retryBatchPdf, fetchAuthenticatedBlobUrl } from '../../lib/api'
import { StepFileRow, StepFileMeta } from './StepFileRow'

/**
 * Auto Run batch â€” expand-in-place detail (resolved Q5).
 * A small surface-container rendered INSIDE the grid flow (col-span-full,
 * directly below the clicked folder card â€” no overlay, no portal). Body shows
 * one section per step with the OutputViewer-style space-y-2 rows, the
 * "Open source PDF" button, the per-PDF RETRY button (resolved Q9) and the
 * small close icon (resolved close: material-symbols-outlined text-[20px]).
 */

const BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

function getAuthHeaders(): Record<string, string> {
  const token = localStorage.getItem('qcm_token')
  return token ? { 'Authorization': `Bearer ${token}` } : {}
}

const BATCH_STEPS: { id: string; label: string; icon: string }[] = [
  { id: '1', label: 'Step 1 Â· Text Extraction', icon: 'text_fields' },
  { id: '2', label: 'Step 2 Â· QCM Extraction + Metadata', icon: 'question_answer' },
  { id: '6', label: 'Step 6 Â· Corrections', icon: 'fact_check' },
]

interface BatchDetailPanelProps {
  batchId: string
  projectName: string
  projectState: string
  errorStep?: string
  onClose: () => void
}

export function BatchDetailPanel({ batchId, projectName, projectState, errorStep, onClose }: BatchDetailPanelProps) {
  const [files, setFiles] = useState<Record<string, StepFileMeta[]>>({})
  const [loading, setLoading] = useState(true)
  const [retrying, setRetrying] = useState(false)
  const [pdfLoading, setPdfLoading] = useState(false)
  const canRetry = projectState === 'error' || projectState === 'cancelled'

  async function load() {
    setLoading(true)
    for (const step of BATCH_STEPS) {
      try {
        const data = await fetchStepOutput(projectName, step.id)
        setFiles((prev) => ({ ...prev, [step.id]: data.files ?? [] }))
      } catch {
        setFiles((prev) => ({ ...prev, [step.id]: [] }))
      }
    }
    setLoading(false)
  }

  useEffect(() => { load() }, [projectName])

  const openSourcePdf = async () => {
    setPdfLoading(true)
    const newTab = window.open('about:blank', '_blank')
    try {
      const blobUrl = await fetchAuthenticatedBlobUrl(
        `${BASE}/projects/${encodeURIComponent(projectName)}/pdf`)
      if (newTab) newTab.location.href = blobUrl
      setTimeout(() => URL.revokeObjectURL(blobUrl), 30000)
    } catch {
      if (newTab) newTab.close()
      alert('Could not open the source PDF.')
    } finally {
      setPdfLoading(false)
    }
  }

  const handleRetry = async () => {
    if (retrying) return
    setRetrying(true)
    try {
      await retryBatchPdf(batchId, projectName)
      // Give the retry a beat to re-mark state, then visually refresh the panel.
      await new Promise(r => setTimeout(r, 600))
      await load()
    } catch (e: any) {
      alert(e?.message || 'Retry failed')
    } finally {
      setRetrying(false)
    }
  }

  const removeFile = (stepId: string, filename: string) => {
    setFiles(prev => ({ ...prev, [stepId]: (prev[stepId] ?? []).filter(f => f.name !== filename) }))
  }

  return (
    <div
      id="batch-detail-panel"
      className="bg-surface-container rounded-2xl border border-outline-variant/20 shadow-lg p-6 space-y-5 animate-in fade-in slide-in-from-top-2 duration-300"
    >
      {/* Header: name + open source PDF + retry + close */}
      <div className="flex items-center gap-3">
        <span className="material-symbols-outlined text-primary text-xl shrink-0">picture_as_pdf</span>
        <p className="text-sm font-black text-on-surface tracking-tight truncate flex-1 min-w-0">{projectName}</p>

        {canRetry && (
          <button
            id="btn-retry-batch-pdf"
            onClick={handleRetry}
            disabled={retrying || pdfLoading}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-[10px] font-black uppercase tracking-widest transition-all border
              bg-primary/10 border-primary/30 text-primary hover:bg-primary/20 disabled:opacity-40"
            title="Re-run this PDF from its first not-done step"
          >
            <span className="material-symbols-outlined text-[14px]">{retrying ? 'progress_activity' : 'refresh'}</span>
            {retrying ? 'Retryingâ€¦' : 'Retry'}
            {errorStep ? ` (step ${errorStep})` : ''}
          </button>
        )}

        <button
          onClick={openSourcePdf}
          disabled={pdfLoading}
          title="Open source PDF"
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-surface-container-low border border-outline-variant/10 text-outline hover:text-primary hover:border-primary/30 transition-all text-[10px] font-bold disabled:opacity-50"
        >
          <span className="material-symbols-outlined text-[16px]">{pdfLoading ? 'hourglass_top' : 'picture_as_pdf'}</span>
          <span className="material-symbols-outlined text-[12px] opacity-50">open_in_new</span>
        </button>

        <button
          onClick={onClose}
          id="btn-close-batch-detail"
          title="Close details"
          className="w-8 h-8 rounded-full hover:bg-surface-container-highest flex items-center justify-center text-outline transition-colors"
        >
          <span className="material-symbols-outlined text-[20px]">close</span>
        </button>
      </div>

      {/* Per-step output sections */}
      <div className="space-y-6">
        {BATCH_STEPS.map(step => (
          <div key={step.id} className="space-y-3">
            <div className="flex items-center gap-2">
              <span className="material-symbols-outlined text-outline text-[18px]">{step.icon}</span>
              <span className="text-xs font-black text-on-surface-variant uppercase tracking-widest">{step.label}</span>
              <span className="text-[10px] text-outline-variant font-bold ml-auto">{(files[step.id] ?? []).length} files</span>
            </div>

            {loading ? (
              <div className="text-[10px] text-outline animate-pulse font-bold tracking-widest">SCANNINGâ€¦</div>
            ) : (files[step.id] ?? []).length === 0 ? (
              <div className="text-[10px] text-outline-variant italic px-1">No output files yet for this step.</div>
            ) : (
              <div className="space-y-2">
                {files[step.id].map(f => (
                  <StepFileRow
                    key={`${step.id}/${f.name}`}
                    projectName={projectName}
                    stepId={step.id}
                    file={f}
                    onDeleted={(name) => removeFile(step.id, name)}
                    onSynced={() => load()}
                  />
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}




