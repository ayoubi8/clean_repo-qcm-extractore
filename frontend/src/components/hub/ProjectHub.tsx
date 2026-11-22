import { useEffect, useState, ReactNode } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import { fetchStepModels } from '../../lib/api'
import { peek } from '../../lib/cache'
import { projectUrl, stepUrl } from '../../lib/routes'
import { usePipelineStore } from '../../store/pipelineStore'
import { useAppStore } from '../../store/appStore'
import type { Project } from '../../types'

/**
 * Project hub (lag plan Phase 2): the old launcher pop-up's tabs as real
 * pages — /projects, /projects/new, /autorun/new, /batches. Each has its own
 * URL, so the browser Back button and refresh work, and nothing is fetched
 * just to draw the tabs.
 */

/** Auto Run feature flag. Optimistic (shown) until the cached server flag
 *  says otherwise — the tab never "pops in" seconds later (lag plan L1). */
export function useAutorunEnabled(): boolean {
  const initial = peek<any>('env:step-models')?.features?.autorun_batch
  const [enabled, setEnabled] = useState<boolean>(initial !== false)
  useEffect(() => {
    let alive = true
    fetchStepModels()
      .then((m) => { if (alive) setEnabled(m?.features?.autorun_batch !== false) })
      .catch(() => {})
    return () => { alive = false }
  }, [])
  return enabled
}

/** Open a project in the pipeline. */
export function useOpenProject() {
  const setActiveProject = useAppStore((s) => s.setActiveProject)
  const navigate = useNavigate()
  return (project: Project) => {
    setActiveProject(project)
    navigate(projectUrl(project.name))
  }
}

const TABS = [
  { to: '/projects', label: 'Projects', icon: 'folder_open', end: true, autorun: false },
  { to: '/projects/new', label: 'New project', icon: 'add_circle', end: true, autorun: false },
  { to: '/autorun/new', label: 'Auto Run', icon: 'rocket_launch', end: true, autorun: true },
  { to: '/batches', label: 'Batches', icon: 'stacks', end: false, autorun: true },
]

export function ProjectHubLayout({ title, subtitle, children, width = 'max-w-3xl' }: {
  title: string
  subtitle?: string
  children: ReactNode
  width?: string
}) {
  const autorun = useAutorunEnabled()
  const activeProject = useAppStore((s) => s.activeProject)
  const activeStepId = usePipelineStore((s) => s.activeStepId)
  const navigate = useNavigate()

  return (
    <div className={`${width} mx-auto px-6 py-8 space-y-6 qe-fade-up`}>
      <div className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-black tracking-tight text-on-surface">{title}</h1>
          {subtitle && <p className="text-sm text-outline mt-1">{subtitle}</p>}
        </div>
        {activeProject && (
          <button
            onClick={() => navigate(stepUrl(activeProject.name, activeStepId ?? 1))}
            className="flex items-center gap-2 h-9 px-3 rounded-xl border border-outline-variant/20 text-xs font-bold text-on-surface-variant hover:text-primary hover:border-primary/30 transition-colors"
            title="Back to the project you were working on"
          >
            <span className="material-symbols-outlined text-[18px]">arrow_back</span>
            <span className="truncate max-w-[220px]">{activeProject.name}</span>
          </button>
        )}
      </div>

      <nav className="flex gap-1 p-1 rounded-2xl bg-surface-container-low border border-outline-variant/10 w-fit max-w-full overflow-x-auto" aria-label="Projects">
        {TABS.filter((t) => autorun || !t.autorun).map((t) => (
          <NavLink
            key={t.to}
            to={t.to}
            end={t.end}
            className={({ isActive }) =>
              `flex items-center gap-2 h-9 px-4 rounded-xl text-xs font-bold whitespace-nowrap transition-all ${
                isActive
                  ? 'bg-surface-container-highest text-primary shadow-sm'
                  : 'text-outline hover:text-on-surface'
              }`
            }
          >
            <span className="material-symbols-outlined text-[18px]">{t.icon}</span>
            {t.label}
          </NavLink>
        ))}
      </nav>

      <div className="bg-surface-container rounded-2xl border border-outline-variant/10 p-6 md:p-8">
        {children}
      </div>
    </div>
  )
}
