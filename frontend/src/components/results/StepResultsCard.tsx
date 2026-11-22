import { Link } from 'react-router-dom'
import { formatBytes, useProjectResults } from '../../lib/results'
import { outputsUrl } from '../../lib/routes'
import { useRefreshResultsOnRunEnd } from '../../hooks/useResultsLive'
import { ResultFileRow, useSheetsAutoSync } from './ResultFileRow'

/**
 * "Results of this step" (results plan §11.3): the step's 1-3 result files
 * and its counts under the config panel. The full file list, the questions
 * table and history live on the project's Results page.
 */
export function StepResultsCard({ project, stepId }: { project: string; stepId: string }) {
  const { data, loading } = useProjectResults(project)
  useRefreshResultsOnRunEnd(project)
  useSheetsAutoSync(project)

  if (loading && !data) {
    return <div className="mt-8 h-20 rounded-2xl bg-surface-container-low animate-pulse" />
  }
  const step = data?.steps?.[stepId]
  if (!step || (step.results.length === 0 && step.intermediate_count === 0 && step.older.length === 0)) return null
  const counts = stepId === data?.summary?.step ? data.summary : null

  return (
    <div className="mt-8 space-y-3 border-t border-outline-variant/10 pt-8 qe-fade-up">
      <div className="flex items-center justify-between gap-3 px-1">
        <div>
          <p className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">Results of this step</p>
          <p className="text-[11px] text-on-surface-variant mt-1">
            {counts && !counts.error
              ? <>{counts.qcms} QCMs · {counts.with_answer} with answer · <span className={counts.flagged ? 'text-tertiary font-bold' : ''}>{counts.flagged} need review</span></>
              : <>{step.results.length} result file{step.results.length === 1 ? '' : 's'}</>}
            {step.intermediate_count > 0 && <span className="text-outline"> · {step.intermediate_count} working files ({formatBytes(step.intermediate_bytes)})</span>}
          </p>
        </div>
        <Link
          to={outputsUrl(project)}
          className="flex items-center gap-1 text-[11px] font-bold text-primary hover:underline shrink-0"
        >
          Open results page
          <span className="material-symbols-outlined text-[14px]">arrow_forward</span>
        </Link>
      </div>
      {step.results.length > 0 ? (
        <div className="space-y-2">
          {step.results.map((f) => (
            <ResultFileRow key={f.name} project={project} step={stepId} file={f} highlight={f.kind === 'mbset_import'} />
          ))}
        </div>
      ) : (
        <p className="text-[11px] text-outline px-1">
          This step keeps only working files. Browse them on the <Link to={outputsUrl(project)} className="text-primary font-bold">Results page</Link>.
        </p>
      )}
    </div>
  )
}
