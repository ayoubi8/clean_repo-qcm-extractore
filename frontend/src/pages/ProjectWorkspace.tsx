import { useEffect, useLayoutEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import { Navigate, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { StepList } from '../components/pipeline/StepList'
import { ConfigPanel } from '../components/pipeline/ConfigPanel'
import { TerminalLog } from '../components/pipeline/TerminalLog'
import { AutoRunPanel } from '../components/autorun/AutoRunPanel'
import { openInGoogleSheets } from '../lib/api'
import { autorunUrl, outputsUrl, stepUrl, toUiStep } from '../lib/routes'
import { useAppStore } from '../store/appStore'
import { usePipelineStore } from '../store/pipelineStore'
import { useToast } from '../components/ui/Toaster'

/**
 * Lag plan Phase 3 — the pipeline workspace under a project URL:
 *   /projects/:name/steps/:stepId   step list + config + live log
 *   /projects/:name/autorun         same, with the Auto Run drawer open
 * The step in the URL drives the selected step; clicking a step navigates.
 */

/** Google Sheets sign-in return: ?sheets_pending=1&step=…&filename=… */
function useSheetsReturn(project: string) {
  const [params, setParams] = useSearchParams()
  const done = useRef(false)
  const toast = useToast()
  useEffect(() => {
    if (done.current || params.get('sheets_pending') !== '1') return
    const step = params.get('step') || ''
    const filename = params.get('filename') || ''
    done.current = true
    setParams({}, { replace: true })   // a refresh must not re-trigger the upload
    if (!step || !filename) return
    // This tab went through Google sign-in only to finish the upload:
    // send it straight to the new sheet.
    openInGoogleSheets(project, step, filename)
      .then((res) => {
        if (res.url) window.location.href = res.url
        else toast.error('Google Sheets upload succeeded but no URL was returned.')
      })
      .catch((err) => toast.error(`Google Sheets error: ${err?.message || 'Unknown error'}`))
  }, [params, project, setParams, toast])
}

export function ProjectWorkspace({ autorun = false }: { autorun?: boolean }) {
  const { name = '', stepId } = useParams()
  const navigate = useNavigate()
  const { search } = useLocation()
  const activeStepId = usePipelineStore((s) => s.activeStepId)
  const setActiveStep = usePipelineStore((s) => s.setActiveStep)
  const uiStep = toUiStep(stepId)

  // URL → selected step (before paint, so the old step never flashes).
  useLayoutEffect(() => {
    if (uiStep !== null && uiStep !== usePipelineStore.getState().activeStepId) setActiveStep(uiStep)
  }, [uiStep, setActiveStep])

  useSheetsReturn(name)

  if (!autorun) {
    if (uiStep === null) return <Navigate to={stepUrl(name, activeStepId ?? 1)} replace />
    if (String(uiStep) !== stepId) return <Navigate to={stepUrl(name, uiStep) + search} replace />
  }

  return (
    <div className="flex flex-col h-[calc(100vh-64px)] overflow-hidden relative">
      <div className="h-14 bg-surface-container-low border-b border-outline-variant/10 flex items-center justify-end gap-2 px-6 shrink-0">
        <button
          id="btn-open-results"
          onClick={() => navigate(outputsUrl(name))}
          className="flex items-center gap-2 px-4 py-1.5 rounded-lg text-xs font-black uppercase tracking-widest border border-outline-variant/20 text-on-surface-variant hover:text-primary hover:border-primary/30 transition-colors"
        >
          <span className="material-symbols-outlined text-[18px]">fact_check</span>
          Results
        </button>
        <button
          id="btn-open-autorun"
          onClick={() => navigate(autorunUrl(name))}
          className="flex items-center gap-2 px-4 py-1.5 bg-secondary-container text-on-secondary-container rounded-lg text-xs font-black uppercase tracking-widest hover:opacity-90 transition-opacity shadow-sm"
        >
          <span className="material-symbols-outlined text-[18px]">play_circle</span>
          Auto Run
        </button>
      </div>

      <div className="flex flex-1 overflow-hidden">
        <StepList />
        <ConfigPanel />
      </div>

      <TerminalLog />

      {autorun && createPortal(
        <AutoRunPanel onClose={() => navigate(stepUrl(name, activeStepId ?? 1))} />,
        document.body,
      )}
    </div>
  )
}

/** /projects/:name → the first step that is not done yet. */
export function ProjectIndex() {
  const { name = '' } = useParams()
  const steps = usePipelineStore((s) => s.steps)
  const statusProject = usePipelineStore((s) => s.statusProject)
  const activeStepId = usePipelineStore((s) => s.activeStepId)
  const first = statusProject === name
    ? (steps.find((s) => s.status !== 'done')?.id ?? steps[steps.length - 1]?.id ?? 1)
    : (activeStepId ?? 1)
  return <Navigate to={stepUrl(name, first)} replace />
}

/**
 * /pipeline — compatibility redirect (old bookmarks, older backend OAuth
 * returns that still send ?sheets_pending=1&project=…&step=…&filename=…).
 */
export function PipelineRedirect() {
  const [params] = useSearchParams()
  const active = useAppStore((s) => s.activeProject)
  const last = useAppStore((s) => s.lastActiveProject)
  const activeStepId = usePipelineStore((s) => s.activeStepId)

  const project = params.get('project')
  if (project) {
    const q = new URLSearchParams()
    for (const k of ['sheets_pending', 'step', 'filename']) {
      const v = params.get(k)
      if (v) q.set(k, v)
    }
    const qs = q.toString()
    return <Navigate to={stepUrl(project, params.get('step') || 1) + (qs ? `?${qs}` : '')} replace />
  }
  const p = active ?? last
  if (p) return <Navigate to={stepUrl(p.name, activeStepId ?? 1)} replace />
  return <Navigate to="/projects" replace />
}
