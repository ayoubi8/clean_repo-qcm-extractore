import { usePipelineStore } from '../../store/pipelineStore'
import { StepState } from '../../types'
import { runStep, connectLogStream, getStepStatus, fetchAuthenticatedBlobUrl } from '../../lib/api'
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
  return (
    <div className="w-5 h-5 rounded-full border border-outline-variant" />
  )
}

export function StepRow({ step, isActive, onClick }: StepRowProps) {
  const setStepStatus = usePipelineStore(s => s.setStepStatus)
  const setStepOutputExists = usePipelineStore(s => s.setStepOutputExists)
  const appendLog = usePipelineStore(s => s.appendLog)
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

    try {
      // Map step ID to config object
      let config = {}
      if (step.id === 1) config = store.step1Config
      if (step.id === 2) config = store.step2Config
      if (step.id === 3) config = store.step3Config
      if (step.id === 4) config = store.step4Config
      if (step.id === 6) config = store.step6Config

      await runStep(activeProject.name, step.id, config)
      
      connectLogStream(
        activeProject.name, 
        step.id, 
        (line) => appendLog(line),
        async () => {
          // On close, poll status
          const status = await getStepStatus(activeProject.name, step.id)
          setStepStatus(step.id, status.status)
          setStepOutputExists(step.id, status.output_exists)
          setPipelineStatus('idle')
          
          // Auto-trigger Step 1.5 if Step 1 finishes
          // Auto-trigger Step 1.5 if Step 1 finishes
          if (step.id === 1 && status.status === 'done') {
            (async () => {
              try {
                setStepStatus(1.5, 'running')
                appendLog({ 
                  ts: new Date().toLocaleTimeString(), 
                  type: 'info', 
                  text: '⚡ Auto-triggering Step 1.5 (Text Fixer)...' 
                })
                await runStep(activeProject.name, 1.5, {})
                connectLogStream(
                  activeProject.name,
                  1.5,
                  (line) => appendLog(line),
                  async () => {
                    const s = await getStepStatus(activeProject.name, 1.5)
                    setStepStatus(1.5, s.status)
                    setStepOutputExists(1.5, s.output_exists)
                  }
                )
              } catch (e) {
                setStepStatus(1.5, 'error')
              }
            })()
          }
        }
      )
    } catch (err: any) {
      setStepStatus(step.id, 'error')
      appendLog({ 
        ts: new Date().toLocaleTimeString(), 
        type: 'error', 
        text: `Failed: ${err.message}` 
      })
    }
  }

  const showRunButton = isActive && step.status !== 'running' && step.id !== 1.5

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
          {step.id === 1.5 && <span className="ml-1 text-[10px] text-outline font-normal">(auto)</span>}
        </p>
      </div>

      {showRunButton && (
        <button
          id={`btn-run-step-${step.id}`}
          onClick={handleRun}
          className="px-2.5 py-1 text-[10px] font-black uppercase tracking-widest bg-primary text-on-primary rounded hover:bg-primary/80 transition-colors shadow-sm"
        >
          {step.status === 'idle' || step.status === 'error' ? 'Run' : 'Re-run'}
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
