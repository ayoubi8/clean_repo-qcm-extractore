import { usePipelineStore, isCcCheckerError } from '../../store/pipelineStore'
import { StepState } from '../../types'
import { runStep, stopStep, connectLogStream, getStepStatus, fetchAuthenticatedBlobUrl } from '../../lib/api'
import { useAppStore } from '../../store/appStore'
import { useState } from 'react'

const BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

interface StepRowProps {
  step: StepState
  isActive: boolean
  onClick: () => void
}

function StatusIcon({ status }: { status: string }) {
  if (status === 'running') {
    return (
      <div className="w-5 h-5 rounded-full border-2 border-primary border-t-transparent animate-spin" />
    )
  }
  if (status === 'done') {
    return (
      <div className="w-5 h-5 rounded-full bg-primary-container flex items-center justify-center">
        <span className="material-symbols-outlined text-[14px] text-on-primary-container font-bold">check</span>
      </div>
    )
  }
  if (status === 'error') {
    return (
      <div className="w-5 h-5 rounded-full bg-error-container flex items-center justify-center">
        <span className="material-symbols-outlined text-[14px] text-on-error-container font-bold">priority_high</span>
      </div>
    )
  }
  if (status === 'stopped' || status === 'cancelled' || status === 'stopping') {
    return (
      <div className="w-5 h-5 rounded-full bg-amber-500/20 flex items-center justify-center">
        <span className="material-symbols-outlined text-[14px] text-amber-500 font-bold">
          {status === 'stopping' ? 'hourglass_top' : 'pause'}
        </span>
      </div>
    )
  }
  return (
    <div className="w-5 h-5 rounded-full border border-outline-variant" />
  )
}

export function StepRow({ step, isActive, onClick }: StepRowProps) {
  const setStepStatus = usePipelineStore(s => s.setStepStatus)
  const setStepOutputExists = usePipelineStore(s => s.setStepOutputExists)
  const appendLog = usePipelineStore(s => s.appendLog)
  const raiseCcAlert = usePipelineStore(s => s.raiseCcAlert)
  const activeProject = useAppStore(s => s.activeProject)
  const setPipelineStatus = useAppStore(s => s.setPipelineStatus)
  
  // Get current config from store
  const store = usePipelineStore()
  
  const handleRun = async (e: React.MouseEvent) => {
    e.stopPropagation()
    if (!activeProject) return

    setStepStatus(step.id, 'running')
    setPipelineStatus('running')
    appendLog({ 
      ts: new Date().toLocaleTimeString(), 
      type: 'info', 
      text: `▶ Starting ${step.label}...` 
    })

    // After the log stream closes, poll the step status until it reaches a
    // terminal state. A single one-shot poll races with the backend flipping
    // "stopping" → "stopped"/"cancelled"/"done", which used to leave the Run
    // button permanently gone.
    const pollStatusUntilTerminal = async (attempt = 0) => {
      if (!activeProject) return
      try {
        const status = await getStepStatus(activeProject.name, step.id)
        if (status.status === 'running' || status.status === 'stopping') {
          if (attempt < 60) {
            setTimeout(() => pollStatusUntilTerminal(attempt + 1), 1000)
            return
          }
        }
        setStepStatus(step.id, status.status)
        setStepOutputExists(step.id, status.output_exists)
        setPipelineStatus('idle')
      } catch {
        if (attempt < 10) {
          setTimeout(() => pollStatusUntilTerminal(attempt + 1), 1000)
          return
        }
        setStepStatus(step.id, 'error')
        setPipelineStatus('idle')
      }
    }

    try {
      // Map step ID to config object
      let config = {}
      if (step.id === 1) {
        // A stopped/cancelled Step 1 resumes from its OCR cache. A completed
        // rerun may explicitly rebuild the cache from scratch.
        config = { ...store.step1Config, force_overwrite: step.status === 'done' && step.outputExists }
      }
      if (step.id === 2) {
        // Merged Step 2: forward both extraction + metadata config.
        // Step 3 config rides along as `step3` sub-key for run_post_step2_metadata.
        // Phase 1: CC Checker model pair rides at the top level for
        // real_api._call_step (CC_CHECKER_* env overrides).
        const cc = store.step3Config.clinical_case_checker ?? { model: '', model_fallback: '' }
        config = {
          ...store.step2Config,
          step3: store.step3Config,
          clinical_case_checker: {
            model_primary: cc.model,
            model_fallback: cc.model_fallback,
          },
        }
      }
      if (step.id === 6) config = store.step6Config

      await runStep(activeProject.name, step.id, config)
      
      connectLogStream(
        activeProject.name,
        step.id,
        (line) => {
          appendLog(line)
          // Phase 1 — persistent CC Checker failure alert (Step 2 only)
          if (step.id === 2 && isCcCheckerError(line?.text) && activeProject?.name) {
            raiseCcAlert(activeProject.name, line.text)
          }
        },
        async () => {
          // On close, poll status until terminal
          pollStatusUntilTerminal()
        }
      )
    } catch (err: any) {
      setStepStatus(step.id, 'error')
      setPipelineStatus('idle')
      appendLog({ 
        ts: new Date().toLocaleTimeString(), 
        type: 'error', 
        text: `Failed: ${err.message}` 
      })
    }
  }

  const handleStop = async (e: React.MouseEvent, mode: 'stop' | 'cancel') => {
    e.stopPropagation()
    if (!activeProject) return
    setStepStatus(step.id, 'stopping')
    appendLog({
      ts: new Date().toLocaleTimeString(),
      type: 'warn',
      text: mode === 'stop' ? `⏸ Stopping ${step.label} and preserving partial outputs...` : `✕ Cancelling ${step.label}...`,
    })
    try {
      await stopStep(activeProject.name, step.id, mode)
    } catch (err: any) {
      appendLog({ ts: new Date().toLocaleTimeString(), type: 'error', text: `Stop failed: ${err.message}` })
      setStepStatus(step.id, 'running')
    }
  }

  const isStopping = step.status === 'running' || step.status === 'stopping'
  const showRunButton = isActive && !isStopping

  return (
    <div 
      id={`step-row-${step.id}`}
      onClick={onClick}
      className={`flex items-center gap-3 px-4 py-3.5 cursor-pointer transition-all border-l-4 ${
        isActive 
          ? 'bg-surface-container border-primary shadow-inner' 
          : 'border-transparent hover:bg-surface-container/50'
      }`}
    >
      <StatusIcon status={step.status} />
      
      <div className="flex-1 min-w-0">
        <p className={`text-xs font-bold truncate ${isActive ? 'text-primary' : 'text-on-surface'}`}>
          {step.label}
          {step.id === 1 && <span className="ml-1 text-[10px] text-outline font-normal">(+ auto 1.5/1.6)</span>}
        </p>
      </div>

      {isActive && isStopping && (
        <div className="flex items-center gap-1">
          <button
            id={`btn-stop-step-${step.id}`}
            onClick={(e) => handleStop(e, 'stop')}
            disabled={step.status === 'stopping'}
            className="px-2.5 py-1 text-[10px] font-black uppercase tracking-widest bg-amber-500 text-black rounded hover:bg-amber-400 transition-colors shadow-sm disabled:opacity-50"
          >
            {step.status === 'stopping' ? 'Stopping...' : 'Stop'}
          </button>
          <button
            id={`btn-cancel-step-${step.id}`}
            onClick={(e) => handleStop(e, 'cancel')}
            disabled={step.status === 'stopping'}
            className="px-2.5 py-1 text-[10px] font-black uppercase tracking-widest border border-error/40 text-error rounded hover:bg-error/10 transition-colors disabled:opacity-50"
          >
            Cancel
          </button>
        </div>
      )}

      {showRunButton && (
        <button
          id={`btn-run-step-${step.id}`}
          onClick={handleRun}
          className="px-2.5 py-1 text-[10px] font-black uppercase tracking-widest bg-primary text-on-primary rounded hover:bg-primary/80 transition-colors shadow-sm"
        >
          {step.status === 'stopped' || step.status === 'cancelled' ? 'Resume' : step.status === 'idle' || step.status === 'error' ? 'Run' : 'Re-run'}
        </button>
      )}
    </div>
  )
}

export function StepList() {
  const steps = usePipelineStore(s => s.steps)
  const activeStepId = usePipelineStore(s => s.activeStepId)
  const setActiveStep = usePipelineStore(s => s.setActiveStep)
  const activeProject = useAppStore(s => s.activeProject)
  const [pdfLoading, setPdfLoading] = useState(false)

  const openPdf = async () => {
    if (!activeProject) return
    setPdfLoading(true)
    const newTab = window.open('about:blank', '_blank')
    try {
      const blobUrl = await fetchAuthenticatedBlobUrl(
        `${BASE}/projects/${encodeURIComponent(activeProject.name)}/pdf`
      )
      if (newTab) {
        newTab.location.href = blobUrl
      }
      setTimeout(() => URL.revokeObjectURL(blobUrl), 30000)
    } catch {
      if (newTab) newTab.close()
      alert('Could not open PDF. Make sure the project has a PDF uploaded.')
    } finally {
      setPdfLoading(false)
    }
  }

  return (
    <aside className="w-72 bg-surface-container-lowest border-r border-outline-variant/10 overflow-y-auto custom-scrollbar flex flex-col">
      <div className="p-4 border-b border-outline-variant/5">
        <h3 className="text-[10px] font-black uppercase tracking-[0.2em] text-outline mb-4">Pipeline Steps</h3>
        {activeProject && (
          <button
            onClick={openPdf}
            disabled={pdfLoading}
            title="Open source PDF"
            className="w-full flex items-center gap-2 px-3 py-2 rounded-xl bg-surface-container border border-outline-variant/10 hover:border-primary/30 hover:bg-primary/5 transition-all group disabled:opacity-50"
          >
            <span className="material-symbols-outlined text-[16px] text-outline group-hover:text-primary transition-colors">
              {pdfLoading ? 'hourglass_top' : 'picture_as_pdf'}
            </span>
            <span className="text-[10px] font-bold text-outline group-hover:text-primary transition-colors truncate flex-1">{activeProject.name}</span>
            <span className="material-symbols-outlined text-[12px] text-outline/50 group-hover:text-primary/70 transition-colors">open_in_new</span>
          </button>
        )}
      </div>
      <div className="flex-1">
        {steps.map((step) => (
          <StepRow 
            key={step.id} 
            step={step} 
            isActive={activeStepId === step.id}
            onClick={() => setActiveStep(step.id)}
          />
        ))}
      </div>
    </aside>
  )
}
