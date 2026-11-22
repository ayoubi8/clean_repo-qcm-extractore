import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ProjectHubLayout, useAutorunEnabled, useOpenProject } from '../components/hub/ProjectHub'
import { ResumeProjectModal } from '../components/launcher/ResumeProjectModal'
import { NewProjectModal } from '../components/launcher/NewProjectModal'
import { AutoRunWizard } from '../components/launcher/autorun-wizard/AutoRunWizard'
import { BatchHistoryList } from '../components/batch/BatchHistoryList'
import { SearchBar } from '../components/tags/SearchBar'
import type { TagEntry } from '../types'

/** Lag plan Phase 2 — the launcher's tabs as pages. */

/** /projects — open, search, delete projects (was: Resume Project tab). */
export function ProjectsPage() {
  const openProject = useOpenProject()
  const navigate = useNavigate()
  return (
    <ProjectHubLayout title="Projects" subtitle="Open a project to continue where you left off.">
      <ResumeProjectModal
        onSuccess={openProject}
        onOpenBatch={(id) => navigate(`/batch/${id}`)}
        showBatches={false}
        fullHeight
      />
    </ProjectHubLayout>
  )
}

/** /projects/new — upload a PDF or a Drive link (was: New Project tab). */
export function NewProjectPage() {
  const openProject = useOpenProject()
  return (
    <ProjectHubLayout title="New project" subtitle="Upload an exam PDF, tag it, and start extracting.">
      <NewProjectModal onSuccess={openProject} />
    </ProjectHubLayout>
  )
}

/** /autorun/new — batch wizard for many PDFs (was: Auto Run tab). */
export function AutoRunPage() {
  const navigate = useNavigate()
  const enabled = useAutorunEnabled()
  return (
    <ProjectHubLayout title="Auto Run" subtitle="Run the whole pipeline on several PDFs at once." width="max-w-4xl">
      {enabled ? (
        <AutoRunWizard onStarted={(id) => navigate(`/batch/${id}`)} />
      ) : (
        <p className="text-sm text-outline">Auto Run is turned off on this server.</p>
      )}
    </ProjectHubLayout>
  )
}

/** /batches — Auto Run batch history (was: "Recent batches" in the launcher). */
export function BatchesPage() {
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [activeTags, setActiveTags] = useState<TagEntry[]>([])
  return (
    <ProjectHubLayout title="Batches" subtitle="Every Auto Run batch, newest first.">
      <div className="space-y-6">
        <SearchBar
          query={query}
          onQueryChange={setQuery}
          activeTags={activeTags}
          onToggleTag={(t: TagEntry) => setActiveTags(prev =>
            prev.some(x => x.key === t.key && x.value === t.value)
              ? prev.filter(x => !(x.key === t.key && x.value === t.value))
              : [...prev, t])}
          onClear={() => { setQuery(''); setActiveTags([]) }}
        />
        <BatchHistoryList onOpenBatch={(id) => navigate(`/batch/${id}`)} query={query} activeTags={activeTags} />
      </div>
    </ProjectHubLayout>
  )
}
