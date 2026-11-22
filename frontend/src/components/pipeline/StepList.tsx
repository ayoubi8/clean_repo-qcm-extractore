import { usePipelineStore, isCcCheckerError } from '../../store/pipelineStore'
import { StepId, StepState } from '../../types'
import { useNavigate } from 'react-router-dom'
import { stepUrl } from '../../lib/routes'
import { runStep, stopStep, connectLogStream, getStepStatus, fetchAuthenticatedBlobUrl } from '../../lib/api'
import { useAppStore } from '../../store/appStore'
import { useEffect, useState } from 'react'

const BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

interface StepRowProps {
  step: StepState
  isActive: boolean
  onClick: () => void
  isLast?: boolean
}

// ── Presentation helpers (pipeline redesign 2026-11) ───────────────────────

const STATUS_TEXT: Record<string, string> = {
  idle: 'Ready',
  running: 'Running',
  stopping: 'Stopping…',
  done: 'Completed',
  error: 'Failed',
  stopped: 'Paused · resumable',
  cancelled: 'Cancelled',
}

const STATUS_TONE: Record<string, string> = {
  idle: 'text-outline',
  running: 'text-primary',
  stopping: 'text-amber-400',
  done: 'text-primary/80',
  error: 'text-error',
  stopped: 'text-amber-400',
  cancelled: 'text-amber-400',
}

/** "Step 2 · QCM Extraction + Metadata" -> ["Step 2", "QCM Extraction + Metadata"] */
function splitLabel(label: string): [string, string] {
  const i = label.indexOf('·')
  return i < 0 ? ['', label] : [label.slice(0, i).trim(), label.slice(i + 1).trim()]
}

function fmtElapsed(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  const mm = String(m).padStart(h > 0 ? 2 : 1, '0')
  return h > 0 ? `${h}:${mm}:${String(sec).padStart(2, '0')}` : `${mm}:${String(sec).padStart(2, '0')}`
}

// Start time of each running step for this page's lifetime, keyed "project|step".
const RUN_STARTED: Record<string, number> = {}

/** Live elapsed time while a step runs; ticks once per second, only then. */
function useElapsed(key: string, running: boolean): string | null {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!running) {
      delete RUN_STARTED[key]
      return
    }
    if (!RUN_STARTED[key]) RUN_STARTED[key] = Date.now()
    setNow(Date.now())
    const t = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(t)
  }, [key, running])
  return running && RUN_STARTED[key] ? fmtElapsed(now - RUN_STARTED[key]) : null
}

function StatusIcon({ status, number }: { status: string; number: string }) {
  const base = 'relative z-10 w-8 h-8 rounded-full flex items-center justify-center shrink-0 transition-all duration-300'
  if (status === 'running') {
    return (
      <div className={`${base} bg-surface-container-lowest border-2 border-primary/25 qe-ring`}>
        <div className="absolute -inset-[2px] rounded-full border-2 border-primary border-t-transparent animate-spin" />
        <span className="text-[11px] font-black text-primary tabular-nums">{number}</span>
      </div>
    )
  }
  if (status === 'done') {
    return (
      <div className={`${base} bg-gradient-to-br from-primary to-primary-container shadow-[0_0_12px_rgba(76,215,246,0.35)]`}>
        <span className="material-symbols-outlined text-[18px] text-on-primary font-bold qe-pop">check</span>
      </div>
    )
  }
  if (status === 'error') {
    return (
      <div className={`${base} bg-error-container border border-error/40`}>
        <span className="material-symbols-outlined text-[17px] text-on-error-container font-bold qe-pop">priority_high</span>
      </div>
    )
  }
  if (status === 'stopped' || status === 'cancelled' || status === 'stopping') {
    return (
      <div className={`${base} bg-amber-500/15 border border-amber-500/40`}>
        <span className={`material-symbols-outlined text-[16px] text-amber-400 font-bold ${status === 'stopping' ? 'qe-blink' : ''}`}>
          {status === 'stopping' ? 'hourglass_top' : status === 'cancelled' ? 'close' : 'pause'}
        </span>
      </div>
    )
  }
  return (
    <div className={`${base} bg-surface-container-lowest border border-outline-variant`}>
      <span className="text-[11px] font-black text-outline tabular-nums">{number}</span>
    </div>
  )
}

export function StepRow({ step, isActive, onClick, isLast = false }: StepRowProps) {
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
  const [eyebrow, title] = splitLabel(step.label)
  const elapsed = useElapsed(`${activeProject?.name ?? ''}|${step.id}`, step.status === 'running')
  const runLabel = step.status === 'stopped' || step.status === 'cancelled' ? 'Resume'
    : step.status === 'idle' || step.status === 'error' ? 'Run' : 'Re-run'
  const runIcon = runLabel === 'Run' ? 'play_arrow' : runLabel === 'Resume' ? 'resume' : 'replay'

  return (
    <div
      id={`step-row-${step.id}`}
      onClick={onClick}
      role="button"
      tabIndex={0}
      aria-current={isActive ? 'step' : undefined}
      onKeyDown={(e) => {
        if (e.target === e.currentTarget && (e.key === 'Enter' || e.key === ' ')) {
          e.preventDefault()
          onClick()
        }
      }}
      className="relative flex gap-3 pl-4 pr-3 cursor-pointer group outline-none"
    >
      {/* Timeline rail: node + connector to the next step */}
      <div className="relative flex flex-col items-center pt-3">
        <StatusIcon status={step.status} number={String(step.id)} />
        {!isLast && (
          <div className="relative w-[2px] flex-1 mt-1 min-h-[14px] rounded-full bg-outline-variant/40 overflow-hidden">
            {step.status === 'done' && <div className="absolute inset-0 bg-gradient-to-b from-primary to-primary/30" />}
            {step.status === 'running' && <div className="absolute inset-0 qe-shimmer" />}
          </div>
        )}
      </div>

      {/* Card */}
      <div
        className={`flex-1 min-w-0 my-1.5 px-3 py-2.5 rounded-xl border transition-all duration-200 ${
          isActive
            ? 'bg-surface-container border-primary/30 shadow-[0_4px_18px_rgba(0,0,0,0.35)]'
            : 'border-transparent group-hover:bg-surface-container/50 group-hover:border-outline-variant/15 group-focus-visible:border-primary/40'
        }`}
      >
        <div className="flex items-start gap-2">
          <div className="flex-1 min-w-0">
            {eyebrow && (
              <p className="text-[9px] font-black uppercase tracking-[0.18em] text-outline">{eyebrow}</p>
            )}
            <p className={`text-[13px] font-bold leading-snug ${isActive ? 'text-on-surface' : 'text-on-surface-variant group-hover:text-on-surface'}`}>
              {title}
            </p>
            <p className={`mt-1 text-[10px] font-semibold flex flex-wrap items-center gap-x-1.5 ${STATUS_TONE[step.status] ?? 'text-outline'}`}>
              {step.status === 'running' && <span className="w-1.5 h-1.5 rounded-full bg-primary qe-blink" />}
              {STATUS_TEXT[step.status] ?? step.status}
              {elapsed && <span className="tabular-nums text-outline font-medium">· {elapsed}</span>}
              {step.id === 1 && !elapsed && <span className="text-outline/70 font-normal">· + auto 1.5 / 1.6</span>}
            </p>
          </div>

          {showRunButton && (
            <button
              id={`btn-run-step-${step.id}`}
              onClick={handleRun}
              className="shrink-0 flex items-center gap-1 pl-2 pr-2.5 h-7 text-[10px] font-black uppercase tracking-widest rounded-lg text-on-primary bg-gradient-to-r from-primary-container to-primary hover:shadow-[0_0_14px_rgba(76,215,246,0.4)] active:scale-95 transition-all qe-fade-up"
            >
              <span className="material-symbols-outlined text-[16px]">{runIcon}</span>
              {runLabel}
            </button>
          )}
        </div>

        {isActive && isStopping && (
          <div className="flex items-center gap-1.5 mt-2.5 qe-fade-up">
            <button
              id={`btn-stop-step-${step.id}`}
              onClick={(e) => handleStop(e, 'stop')}
              disabled={step.status === 'stopping'}
              title="Stop and keep partial results (resumable)"
              className="flex items-center gap-1 px-2.5 h-7 text-[10px] font-black uppercase tracking-widest bg-amber-500 text-black rounded-lg hover:bg-amber-400 transition-colors disabled:opacity-50"
            >
              <span className="material-symbols-outlined text-[15px]">pause</span>
              {step.status === 'stopping' ? 'Stopping…' : 'Stop'}
            </button>
            <button
              id={`btn-cancel-step-${step.id}`}
              onClick={(e) => handleStop(e, 'cancel')}
              disabled={step.status === 'stopping'}
              title="Cancel this run"
              className="flex items-center gap-1 px-2.5 h-7 text-[10px] font-black uppercase tracking-widest border border-error/40 text-error rounded-lg hover:bg-error/10 transition-colors disabled:opacity-50"
            >
              <span className="material-symbols-outlined text-[15px]">close</span>
              Cancel
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

export function StepList() {
  const steps = usePipelineStore(s => s.steps)
  const activeStepId = usePipelineStore(s => s.activeStepId)
  const setActiveStep = usePipelineStore(s => s.setActiveStep)
  const activeProject = useAppStore(s => s.activeProject)
  const [pdfLoading, setPdfLoading] = useState(false)
  const navigate = useNavigate()
  // The step lives in the URL (lag plan Phase 3): selecting one navigates.
  const selectStep = (id: StepId) => {
    if (activeProject) navigate(stepUrl(activeProject.name, id))
    else setActiveStep(id)
  }

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

  const doneCount = steps.filter(st => st.status === 'done').length
  const runningStep = steps.find(st => st.status === 'running' || st.status === 'stopping')
  const pct = steps.length ? Math.round((doneCount / steps.length) * 100) : 0

  return (
    <aside className="w-72 bg-surface-container-lowest border-r border-outline-variant/10 overflow-y-auto custom-scrollbar flex flex-col">
      <div className="p-4 border-b border-outline-variant/5 space-y-3">
        <div className="flex items-end justify-between gap-2">
          <div className="min-w-0">
            <h3 className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">Pipeline Steps</h3>
            <p className="text-[11px] text-on-surface-variant mt-1 truncate">
              {runningStep ? (
                <span className="text-primary font-semibold">Running · {splitLabel(runningStep.label)[1]}</span>
              ) : doneCount === steps.length && steps.length > 0 ? (
                <span className="text-primary font-semibold">All steps completed</span>
              ) : (
                <>{doneCount} of {steps.length} completed</>
              )}
            </p>
          </div>
          <span className="text-lg font-black tabular-nums text-on-surface shrink-0">
            {pct}<span className="text-[10px] text-outline font-bold">%</span>
          </span>
        </div>

        {/* Segmented progress: one segment per step */}
        <div className="flex gap-1" role="img" aria-label={`${doneCount} of ${steps.length} steps completed`}>
          {steps.map(st => (
            <div key={st.id} className="h-1.5 flex-1 rounded-full bg-outline-variant/30 overflow-hidden" title={st.label}>
              <div
                className={`h-full rounded-full transition-all duration-500 ${
                  st.status === 'done' ? 'w-full bg-primary'
                  : st.status === 'running' ? 'w-full qe-shimmer'
                  : st.status === 'error' ? 'w-full bg-error/70'
                  : st.status === 'stopped' || st.status === 'cancelled' || st.status === 'stopping' ? 'w-1/2 bg-amber-500/70'
                  : 'w-0'
                }`}
              />
            </div>
          ))}
        </div>

        {activeProject && (
          <button
            onClick={openPdf}
            disabled={pdfLoading}
            title="Open source PDF"
            className="w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl bg-surface-container border border-outline-variant/10 hover:border-primary/30 hover:bg-primary/5 transition-all group disabled:opacity-50"
          >
            <span className="w-7 h-7 rounded-lg bg-error-container/40 flex items-center justify-center shrink-0">
              <span className="material-symbols-outlined text-[16px] text-error">
                {pdfLoading ? 'hourglass_top' : 'picture_as_pdf'}
              </span>
            </span>
            <span className="min-w-0 flex-1 text-left">
              <span className="block text-[9px] font-black uppercase tracking-[0.18em] text-outline">Source PDF</span>
              <span className="block text-[11px] font-bold text-on-surface-variant group-hover:text-primary transition-colors truncate">{activeProject.name}</span>
            </span>
            <span className="material-symbols-outlined text-[14px] text-outline/50 group-hover:text-primary/70 transition-colors">open_in_new</span>
          </button>
        )}
      </div>
      <div className="flex-1 py-2">
        {steps.map((step, i) => (
          <StepRow
            key={step.id}
            step={step}
            isLast={i === steps.length - 1}
            isActive={activeStepId === step.id}
            onClick={() => selectStep(step.id)}
          />
        ))}
      </div>
    </aside>
  )
}
