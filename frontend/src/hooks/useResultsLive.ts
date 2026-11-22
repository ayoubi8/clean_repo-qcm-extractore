import { useEffect, useRef } from 'react'
import { refreshResults } from '../lib/results'
import { usePipelineStore } from '../store/pipelineStore'

/** Refetch the project's results when one of its steps stops running
 *  (run end invalidation, results plan R4). */
export function useRefreshResultsOnRunEnd(project: string | undefined) {
  const steps = usePipelineStore((s) => s.steps)
  const statusProject = usePipelineStore((s) => s.statusProject)
  const prev = useRef<Record<string, string>>({})
  useEffect(() => {
    if (!project || statusProject !== project) return
    let ended = false
    for (const st of steps) {
      const before = prev.current[String(st.id)]
      if ((before === 'running' || before === 'stopping') && st.status !== 'running' && st.status !== 'stopping') ended = true
      prev.current[String(st.id)] = st.status
    }
    if (ended) void refreshResults(project).catch(() => {})
  }, [steps, project, statusProject])
}
