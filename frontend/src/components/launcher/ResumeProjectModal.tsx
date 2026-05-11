import { useState, useEffect } from 'react'
import { fetchProjects, deleteProject } from '../../lib/api'
import { Project } from '../../types'
import { formatRelative } from '../../lib/format'

interface ResumeProjectModalProps {
  onSuccess: (project: Project) => void
}

export function ResumeProjectModal({ onSuccess }: ResumeProjectModalProps) {
  const [projects, setProjects] = useState<Project[]>([])
  const [selected, setSelected] = useState<Project | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [deletingName, setDeletingName] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)

  useEffect(() => {
    load()
  }, [])

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const data = await fetchProjects()
      setProjects([...data].sort((a, b) => new Date(b.last_modified).getTime() - new Date(a.last_modified).getTime()))
    } catch (e) {
      setError('Failed to load existing projects.')
    } finally {
      setLoading(false)
    }
  }

  async function handleDelete(name: string, e: React.MouseEvent) {
    e.stopPropagation() // don't select the row
    if (confirmDelete !== name) {
      // First click → ask for confirmation
      setConfirmDelete(name)
      return
    }
    // Second click → execute delete
    setDeletingName(name)
    setConfirmDelete(null)
    try {
      await deleteProject(name)
      setProjects(prev => prev.filter(p => p.name !== name))
      if (selected?.name === name) setSelected(null)
    } catch {
      setError(`Failed to delete "${name}".`)
    } finally {
      setDeletingName(null)
    }
  }

  if (loading) {
    return (
      <div className="space-y-3">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-20 bg-surface-container-high rounded-xl animate-pulse" />
        ))}
      </div>
    )
  }

  if (error && projects.length === 0) {
    return (
      <div className="p-4 rounded-xl bg-error-container/10 border border-error/20 text-center">
        <span className="material-symbols-outlined text-error text-3xl block mb-2">wifi_off</span>
        <p className="text-error text-sm font-bold">{error}</p>
        <p className="text-outline text-xs mt-1">Check that the API is running on port 8000.</p>
      </div>
    )
  }

  if (projects.length === 0) {
    return (
      <div className="text-center py-8 text-outline">
        <span className="material-symbols-outlined text-5xl block mb-4 opacity-20">folder_off</span>
        <p className="text-sm font-bold text-on-surface">No existing projects found.</p>
        <p className="text-xs mt-1">Start a new extraction project to see it here.</p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="space-y-2 max-h-[320px] overflow-y-auto pr-2 custom-scrollbar">
        {projects.map((project) => {
          const isSelected = selected?.name === project.name
          const isDeleting = deletingName === project.name
          const isConfirming = confirmDelete === project.name

          return (
            <div
              key={project.name}
              id={`project-row-${project.name}`}
              onClick={() => { setSelected(project); setConfirmDelete(null) }}
              className={`group flex items-center justify-between p-4 cursor-pointer border-l-4 transition-all rounded-r-xl ${
                isSelected
                  ? 'border-primary bg-surface-container-highest shadow-lg'
                  : 'border-transparent bg-surface-container-low hover:bg-surface-container-high'
              }`}
            >
              {/* Project info */}
              <div className="flex-1 min-w-0">
                <p className="text-sm font-black text-on-surface tracking-tight truncate">
                  {project.name}
                </p>
                <p className="text-[11px] text-outline mt-0.5 font-medium">
                  Step {project.last_step} / 8 · {formatRelative(project.last_modified)}
                </p>
                {project.pdf_path && (
                  <p className="text-[10px] text-outline/50 font-mono truncate mt-0.5">
                    {project.pdf_path}
                  </p>
                )}
              </div>

              {/* Right side: tokens + delete */}
              <div className="flex items-center gap-2 ml-3 shrink-0">
                <p className="text-[10px] font-mono text-primary bg-primary/10 px-2 py-0.5 rounded border border-primary/20">
                  {project.total_tokens.toLocaleString()} tokens
                </p>

                {/* Delete button */}
                <button
                  id={`btn-delete-${project.name}`}
                  onClick={(e) => handleDelete(project.name, e)}
                  disabled={isDeleting}
                  title={isConfirming ? 'Click again to confirm delete' : 'Delete project'}
                  className={`p-1.5 rounded-lg transition-all opacity-0 group-hover:opacity-100 ${
                    isConfirming
                      ? 'opacity-100 bg-error/15 text-error border border-error/30 animate-pulse'
                      : 'text-outline hover:bg-error/10 hover:text-error'
                  } disabled:opacity-30`}
                >
                  {isDeleting
                    ? <span className="material-symbols-outlined text-base animate-spin">refresh</span>
                    : isConfirming
                    ? <span className="material-symbols-outlined text-base">warning</span>
                    : <span className="material-symbols-outlined text-base">delete</span>
                  }
                </button>
              </div>
            </div>
          )
        })}
      </div>

      {/* Error toast */}
      {error && (
        <p className="text-error text-xs text-center animate-in fade-in">{error}</p>
      )}

      {/* Confirm hint */}
      {confirmDelete && (
        <p className="text-[11px] text-center text-tertiary animate-in fade-in">
          ⚠ Click the delete icon again to permanently remove <strong>{confirmDelete}</strong>
        </p>
      )}

      <button
        id="btn-resume-project"
        onClick={() => selected && onSuccess(selected)}
        disabled={!selected}
        className="w-full py-4 bg-primary text-on-primary rounded-xl font-black uppercase tracking-tighter flex items-center justify-center gap-2 hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-[0_4px_20px_rgba(76,215,246,0.3)]"
      >
        <span className="material-symbols-outlined">
          {selected?.last_step === 0 ? 'open_in_new' : 'history'}
        </span>
        {selected
          ? (selected.last_step === 0 ? 'Open Project' : `Continue from Step ${selected.last_step}`)
          : 'Select a project'
        }
      </button>
    </div>
  )
}
