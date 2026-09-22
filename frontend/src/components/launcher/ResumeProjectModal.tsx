import { useState, useEffect } from 'react'
import { fetchProjects, deleteProject } from '../../lib/api'
import { Project, TagEntry } from '../../types'
import { formatRelative } from '../../lib/format'
import { BatchHistoryList } from '../batch/BatchHistoryList'
import { SearchBar } from '../tags/SearchBar'
import { TagChip } from '../tags/TagChip'
import { filterBySearchTags } from '../../lib/tags'

interface ResumeProjectModalProps {
  onSuccess: (project: Project) => void
  onOpenBatch: (batchId: string) => void
}

export function ResumeProjectModal({ onSuccess, onOpenBatch }: ResumeProjectModalProps) {
  const [projects, setProjects] = useState<Project[]>([])
  const [selected, setSelected] = useState<Project | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [deletingName, setDeletingName] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  // Tags & Search plan — one filter drives projects + batch history rows
  const [query, setQuery] = useState('')
  const [activeTags, setActiveTags] = useState<TagEntry[]>([])

  const visibleProjects = filterBySearchTags(projects, query, activeTags)

  useEffect(() => {
    load()
  }, [])

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const data = await fetchProjects()
      const ts = (p: Project) => p.last_modified ? new Date(p.last_modified).getTime() : 0
      setProjects([...data].sort((a, b) => ts(b) - ts(a)))
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

  const searchProps = {
    query, onQueryChange: setQuery, activeTags,
    onToggleTag: (t: TagEntry) => setActiveTags(prev =>
      prev.some(x => x.key === t.key && x.value === t.value)
        ? prev.filter(x => !(x.key === t.key && x.value === t.value))
        : [...prev, t]),
    onClear: () => { setQuery(''); setActiveTags([]) },
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
    const searchProps0 = searchProps
    return (
      <div className="space-y-6">
        <SearchBar {...searchProps0} />
        <BatchHistoryList onOpenBatch={onOpenBatch} query={query} activeTags={activeTags} />
        <div className="text-center py-8 text-outline">
          <span className="material-symbols-outlined text-5xl block mb-4 opacity-20">folder_off</span>
          <p className="text-sm font-bold text-on-surface">No existing projects found.</p>
          <p className="text-xs mt-1">Start a new extraction project to see it here.</p>
        </div>
      </div>
    )
  }

  const emptyFiltered = visibleProjects.length === 0 && (query || activeTags.length > 0)

  return (
    <div className="space-y-6">
      <SearchBar {...searchProps} />
      <BatchHistoryList onOpenBatch={onOpenBatch} query={query} activeTags={activeTags} />
      {emptyFiltered ? (
        <div className="text-center py-8 text-outline">
          <span className="material-symbols-outlined text-5xl block mb-4 opacity-20">search_off</span>
          <p className="text-sm font-bold text-on-surface">No matches.</p>
          <p className="text-xs mt-1">Try a different name or clear the tag filters.</p>
        </div>
      ) : (
      <div className="space-y-2 max-h-[320px] overflow-y-auto pr-2 custom-scrollbar">
        {visibleProjects.map((project) => {
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
                <div className="flex items-center gap-2 min-w-0">
                  <p className="text-sm font-black text-on-surface tracking-tight truncate">
                    {project.name}
                  </p>
                  {project.origin === 'autorun' && (
                    <span
                      title="Created by Auto Run batch"
                      className="shrink-0 inline-flex items-center gap-1 text-[9px] font-black uppercase tracking-wider text-on-secondary-container bg-secondary-container/60 px-1.5 py-0.5 rounded border border-secondary/30"
                    >
                      <span className="material-symbols-outlined text-[12px] leading-none">rocket_launch</span>
                      AUTO
                    </span>
                  )}
                  {(project.tags ?? []).map((t, i) => (
                    <TagChip key={i} tag={t} clickable onClick={() => searchProps.onToggleTag(t)} />
                  ))}
                </div>
                <p className="text-[11px] text-outline mt-0.5 font-medium">
                  Step {(project.last_step === 4 || project.last_step === 5) ? 3 : project.last_step} / 8 · {formatRelative(project.last_modified)}
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
      )}

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
          ? (selected.last_step === 0 ? 'Open Project' : `Continue from Step ${(selected.last_step === 4 || selected.last_step === 5) ? 3 : selected.last_step}`)
          : 'Select a project'
        }
      </button>
    </div>
  )
}
