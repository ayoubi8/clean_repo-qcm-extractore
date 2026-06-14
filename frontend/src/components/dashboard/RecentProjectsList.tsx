import { useNavigate } from 'react-router-dom'
import { useAppStore } from '../../store/appStore'
import { Project } from '../../types'
import { formatRelative } from '../../lib/format'

interface RecentProjectsListProps {
  projects: Project[]
  loading: boolean
}

export function RecentProjectsList({ projects, loading }: RecentProjectsListProps) {
  const setActiveProject = useAppStore(s => s.setActiveProject)
  const navigate = useNavigate()

  if (loading) {
    return (
      <div className="bg-surface-container rounded-2xl p-6 border border-outline-variant/10 animate-pulse space-y-4">
        <div className="h-4 w-1/4 bg-surface-container-high rounded mb-4" />
        {[1, 2, 3].map(i => (
          <div key={i} className="h-16 w-full bg-surface-container-high rounded-xl" />
        ))}
      </div>
    )
  }

  const recent = [...projects]
    .sort((a, b) => b.last_modified.localeCompare(a.last_modified))
    .slice(0, 5)

  return (
    <div className="bg-surface-container rounded-2xl p-6 border border-outline-variant/10 shadow-sm">
      <div className="flex items-center justify-between mb-6">
        <p className="text-[10px] uppercase tracking-widest text-outline font-black">
          Recent Projects
        </p>
        <span className="text-[9px] font-mono text-outline opacity-40 uppercase tracking-widest">Showing last 5</span>
      </div>

      {recent.length === 0 ? (
        <div className="py-12 flex flex-col items-center justify-center opacity-30 border-2 border-dashed border-outline-variant/10 rounded-2xl">
          <span className="material-symbols-outlined text-4xl mb-2">folder_open</span>
          <p className="text-xs font-bold uppercase tracking-widest">No projects found</p>
        </div>
      ) : (
        <div className="space-y-2">
          {recent.map(proj => (
            <div
              key={proj.name}
              id={`recent-project-${proj.name}`}
              onClick={() => { setActiveProject(proj); navigate('/pipeline') }}
              className="flex items-center justify-between p-4 rounded-xl
                         bg-surface-container-low hover:bg-surface-container-highest/50
                         border border-outline-variant/5 hover:border-primary/20
                         cursor-pointer transition-all group"
            >
              <div className="flex items-center gap-4">
                <div className="w-10 h-10 rounded-lg bg-surface-container-high flex items-center justify-center group-hover:bg-primary/10 transition-colors">
                  <span className="material-symbols-outlined text-outline group-hover:text-primary transition-colors">description</span>
                </div>
                <div>
                  <p className="text-sm font-black text-on-surface group-hover:text-primary transition-colors truncate max-w-[320px] tracking-tight">
                    {proj.name}
                  </p>
                  <p className="text-[10px] text-outline mt-0.5 font-medium uppercase tracking-widest opacity-60">
                    Step {proj.last_step}/8 · {formatRelative(proj.last_modified)}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-6">
                <div className="hidden sm:flex flex-col items-end">
                  <span className="text-[11px] font-mono font-black text-on-surface">
                    {proj.total_tokens.toLocaleString()}
                  </span>
                  <span className="text-[8px] text-outline font-bold uppercase tracking-widest">Tokens</span>
                </div>
                <span className="material-symbols-outlined text-outline text-[18px] group-hover:text-primary group-hover:translate-x-1 transition-all">
                  arrow_forward
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
