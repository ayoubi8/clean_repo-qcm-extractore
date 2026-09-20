import { useState, useEffect } from 'react'
import { retryBatchPdf, fetchAuthenticatedBlobUrl } from '../../lib/api'
import { useBatchStore } from '../../store/batchStore'
import { useOutputsCache, ensureStepOutput, reloadAfterSync, removeCachedFile } from '../../store/outputsCache'
import { StepFileRow, StepFileMeta } from './StepFileRow'

/**
 * Auto Run batch — expand-in-place detail (resolved Q5).
 * A small surface-container rendered INSIDE the grid flow (col-span-full,
 * directly below the clicked folder card — no overlay, no portal). Body shows
 * one section per step with the OutputViewer-style space-y-2 rows, the
 * "Open source PDF" button, the per-PDF RETRY button (resolved Q9) and the
 * small close icon (resolved close: material-symbols-outlined text-[20px]).
 *
 * Phase 6 (Q-C1): step outputs come from the client outputsCache — a fresh
 * entry is served FREE (no request); after a sync the affected step (and its
 * sibling) is refetched and the cached entries REPLACED; deletes update the
 * cached entry locally. Steps whose every file predates the batch get a
 * "cached results" note (output computed by an earlier run, not this batch).
 */

const BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

function getAuthHeaders(): Record<string, string> {
  const token = localStorage.getItem('qcm_token')
  return token ? { 'Authorization': `Bearer ${token}` } : {}
}

const BATCH_STEPS: { id: string; label: string; icon: string }[] = [
  { id: '1', label: 'Step 1 · Text Extraction', icon: 'text_fields' },
  { id: '2', label: 'Step 2 · QCM Extraction + Metadata', icon: 'question_answer' },
  { id: '6', label: 'Step 6 · Corrections', icon: 'fact_check' },
]

interface BatchDetailPanelProps {
  batchId: string
  projectName: string
  projectState: string
  errorStep?: string
  onClose: () => void
}

export function BatchDetailPanel({ batchId, projectName, projectState, errorStep, onClose }: BatchDetailPanelProps) {
  const entries = useOutputsCache()
  const batchCreatedAt = useBatchStore(s => s.manifest?.created_at)
  const [retrying, setRetrying] = useState(false)
  const [pdfLoading, setPdfLoading] = useState(false)
  const canRetry = projectState === 'error' || projectState === 'cancelled'

  const filesFor = (stepId: string): StepFileMeta[] =>
    entries[`${projectName}|${stepId}`]?.files ?? []

  const predates = (stepId: string): boolean => {
    const files = filesFor(stepId)
    const batchStart = batchCreatedAt ? Date.parse(batchCreatedAt) : 0
    if (!batchStart || files.length === 0) return false
    return files.every(f => !f.created_at || Date.parse(f.created_at) < batchStart)
  }

  useEffect(() => {
    for (const step of BATCH_STEPS) {
      void ensureStepOutput(projectName, step.id)
    }
    // project switch → fresh panel scope; the cache entries are keyed so old
    // projects stay cached for their TTL window.
  }, [projectName])

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
      // Phase 2: a retry re-activates the batch — polling stops on terminal
      // manifests, so restart it explicitly (idempotent in the store).
      useBatchStore.getState().startPolling(batchId)
      // The retry may re-run steps → drop this project's cached outputs so the
      // fresh pass is rendered.
      BATCH_STEPS.forEach(step => void reloadAfterSync(projectName, step.id))
    } catch (e: any) {
      alert(e?.message || 'Retry failed')
    } finally {
      setRetrying(false)
    }
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
            {retrying ? 'Retrying…' : 'Retry'}
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
        {BATCH_STEPS.map(step => {
          const files = filesFor(step.id)
          const scanning = entries[`${projectName}|${step.id}`] === undefined
          return (
            <div key={step.id} className="space-y-3">
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined text-outline text-[18px]">{step.icon}</span>
                <span className="text-xs font-black text-on-surface-variant uppercase tracking-widest">{step.label}</span>
                {predates(step.id) ? (
                  <span className="text-[9px] font-black uppercase tracking-widest text-secondary inline-flex items-center gap-0.5 ml-1">
                    <span className="material-symbols-outlined text-[12px]">cached</span>
                    previous run
                  </span>
                ) : null}
                <span className="text-[10px] text-outline-variant font-bold ml-auto">{files.length} files</span>
              </div>

              {scanning ? (
                <div className="text-[10px] text-outline animate-pulse font-bold tracking-widest">SCANNING…</div>
              ) : files.length === 0 ? (
                <div className="text-[10px] text-outline-variant italic px-1">No output files yet for this step.</div>
              ) : (
                <div className="space-y-2">
                  {files.map(f => (
                    <StepFileRow
                      key={`${step.id}/${f.name}`}
                      projectName={projectName}
                      stepId={step.id}
                      file={f}
                      onDeleted={() => removeCachedFile(projectName, step.id, f.name)}
                      onSynced={() => reloadAfterSync(projectName, step.id)}
                    />
                  ))}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
