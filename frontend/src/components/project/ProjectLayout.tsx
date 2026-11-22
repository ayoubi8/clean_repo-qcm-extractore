import { useEffect, useState } from 'react'
import { Link, Outlet, useParams } from 'react-router-dom'
import {
  PROJECTS_KEY, connectLogStream, fetchProjectOverview, fetchProjectsCached,
  getStepStatus, isStreaming, overviewKey, type ProjectOverview,
} from '../../lib/api'
import { peek } from '../../lib/cache'
import { UI_STEPS } from '../../lib/routes'
import { useAppStore } from '../../store/appStore'
import { isCcCheckerError, usePipelineStore } from '../../store/pipelineStore'
import type { Project, StepId } from '../../types'

/**
 * /projects/:name/* (lag plan Phase 3).
 * - Resolves the project named in the URL (store → cached list → network) and
 *   makes it the active project, so every panel reading `activeProject` works.
 * - Loads ALL step statuses with one GET /overview when the project opens;
 *   moving between steps of the same project sends no status request.
 * - After a page refresh, reattaches the live log of a step that is still
 *   running (a stream opened earlier in this tab is left alone).
 */

function applyOverview(o: ProjectOverview) {
  const ps = usePipelineStore.getState()
  let anyRunning = false
  for (const id of UI_STEPS) {
    const s = o.steps?.[String(id)]
    if (!s) continue
    ps.setStepStatus(id, s.status)
    ps.setStepOutputExists(id, !!s.output_exists)
    if (s.status === 'running' || s.status === 'stopping') anyRunning = true
  }
  useAppStore.getState().setPipelineStatus(anyRunning ? 'running' : 'idle')
}

function reattachRunningLogs(name: string, o: ProjectOverview) {
  const ps = usePipelineStore.getState()
  for (const id of UI_STEPS) {
    const s = o.steps?.[String(id)]
    if (!s || (s.status !== 'running' && s.status !== 'stopping')) continue
    if (isStreaming(name, id)) continue
    ps.appendLog({ ts: new Date().toLocaleTimeString(), type: 'info', text: `↻ Reconnected to the live log of step ${id}` })
    connectLogStream(
      name,
      id,
      (line) => {
        usePipelineStore.getState().appendLog(line)
        if (id === 2 && isCcCheckerError(line?.text)) usePipelineStore.getState().raiseCcAlert(name, line.text)
      },
      () => { void pollUntilDone(name, id) },
    )
  }
}

async function pollUntilDone(name: string, id: StepId, attempt = 0): Promise<void> {
  try {
    const st = await getStepStatus(name, id)
    if ((st.status === 'running' || st.status === 'stopping') && attempt < 60) {
      setTimeout(() => { void pollUntilDone(name, id, attempt + 1) }, 1000)
      return
    }
    if (usePipelineStore.getState().statusProject !== name) return
    usePipelineStore.getState().setStepStatus(id, st.status)
    usePipelineStore.getState().setStepOutputExists(id, st.output_exists)
    useAppStore.getState().setPipelineStatus('idle')
  } catch {
    if (attempt < 10) setTimeout(() => { void pollUntilDone(name, id, attempt + 1) }, 1000)
  }
}

function findProject(name: string): Project | undefined {
  const active = useAppStore.getState().activeProject
  if (active?.name === name) return active
  return peek<Project[]>(PROJECTS_KEY)?.find((p) => p.name === name)
}

export function ProjectLayout() {
  const { name = '' } = useParams()
  const setActiveProject = useAppStore((s) => s.setActiveProject)
  const activeName = useAppStore((s) => s.activeProject?.name)
  const [missing, setMissing] = useState(false)

  // 1) Resolve the project and make it active.
  useEffect(() => {
    setMissing(false)
    const known = findProject(name)
    if (known) {
      if (useAppStore.getState().activeProject?.name !== name) setActiveProject(known)
      return
    }
    let alive = true
    fetchProjectsCached()
      .then((list) => {
        if (!alive) return
        const p = list.find((x) => x.name === name)
        if (p) setActiveProject(p)
        else setMissing(true)
      })
      .catch(() => { if (alive) setMissing(true) })
    return () => { alive = false }
  }, [name, setActiveProject])

  // 2) Step statuses: one request per project visit.
  useEffect(() => {
    if (!name) return
    const ps = usePipelineStore.getState()
    if (ps.statusProject !== name) {
      ps.resetStepStates(name)
      const prev = peek<ProjectOverview>(overviewKey(name))
      if (prev) applyOverview(prev)    // instant, refreshed just below
    }
    let alive = true
    fetchProjectOverview(name)
      .then((o) => {
        if (!alive) return
        applyOverview(o)
        reattachRunningLogs(name, o)
        // Not in the caller's list but the server knows it (admin view).
        if (o.project && useAppStore.getState().activeProject?.name !== name) setActiveProject(o.project)
      })
      .catch((err) => console.warn('Project overview failed:', err))
    return () => { alive = false }
  }, [name, setActiveProject])

  if (missing && activeName !== name) {
    return (
      <div className="max-w-lg mx-auto px-6 py-20 text-center space-y-4 qe-fade-up">
        <span className="material-symbols-outlined text-5xl text-outline">folder_off</span>
        <h1 className="text-xl font-black text-on-surface">Project not found</h1>
        <p className="text-sm text-outline">
          No project called <span className="font-bold text-on-surface-variant">{name}</span> in your account.
        </p>
        <Link to="/projects" className="inline-flex items-center gap-2 h-10 px-4 rounded-xl bg-primary text-on-primary text-sm font-bold">
          <span className="material-symbols-outlined text-[18px]">folder_open</span>
          All projects
        </Link>
      </div>
    )
  }

  if (activeName !== name) {
    return (
      <div className="flex items-center justify-center h-[calc(100vh-64px)] text-outline text-sm gap-2">
        <span className="material-symbols-outlined animate-spin text-[18px]">progress_activity</span>
        Opening {name}…
      </div>
    )
  }

  return <Outlet />
}
