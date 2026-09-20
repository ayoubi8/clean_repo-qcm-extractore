import { BatchProjectEntry } from '../../types'
import { stepChipStatus } from '../../store/batchStore'

/**
 * Auto Run batch — one folder card per PDF (plan §3.3).
 *
 * Live per-step chips (1 / 2 / 6) — idle outline, running primary + pulse,
 * done check, error red. Done cards become inspectable (expand-in-place)
 * while the rest of the batch still runs.
 */

const CHIP_BASE = 'inline-flex items-center gap-1 px-2 py-0.5 rounded border text-[9px] font-black uppercase tracking-wider'

const STEP_CHIP_STYLES: Record<string, string> = {
  idle: 'bg-surface-container-highest text-outline border-outline-variant/20',
  running: 'bg-primary/10 text-primary border-primary/30',
  done: 'bg-primary/10 text-primary border-primary/30',
  error: 'bg-error-container/10 text-error border-error/30',
}

function StepChip({ step, status }: { step: number; status: string }) {
  const icon = status === 'done' ? 'check_circle'
    : status === 'running' ? 'progress_activity'
    : status === 'error' ? 'error'
    : 'circle'
  return (
    <span className={`${CHIP_BASE} ${style_for(status)}`} title={`Step ${step}: ${status}`}>
      {status === 'running'
        ? <span className="material-symbols-outlined text-[12px] animate-spin">progress_activity</span>
        : <span className="material-symbols-outlined text-[12px]">{icon}</span>}
      Step {step}
    </span>
  )
}

function style_for(status: string): string {
  return STEP_CHIP_STYLES[status] ?? STEP_CHIP_STYLES.idle
}

function stateChip(p: BatchProjectEntry): { label: string; cls: string } {
  switch (p.state) {
    case 'running':
      return { label: p.current_step ? `Running · step ${p.current_step}` : 'Running',
               cls: 'bg-primary-container/20 text-primary border-primary/30' }
    case 'done':
      return { label: 'Completed', cls: 'bg-primary/10 text-primary border-primary/40' }
    case 'error':
      return { label: p.error_step ? `Failed · step ${p.error_step}` : 'Failed',
               cls: 'bg-error-container/10 text-error border-error/30' }
    case 'cancelled':
      return { label: 'Cancelled', cls: 'bg-error-container/10 text-error border-error/30' }
    case 'pending':
      return { label: 'Queued', cls: 'bg-surface-container-high text-outline border-outline/10' }
    default:
      return { label: p.state, cls: 'bg-surface-container-high text-outline border-outline/10' }
  }
}

interface BatchFolderCardProps {
  project: BatchProjectEntry
  live?: Record<string, string>
  selected: boolean
  onClick: () => void
}

export function BatchFolderCard({ project, live, selected, onClick }: BatchFolderCardProps) {
  const { name, state } = project
  const chip = stateChip(project)
  const isRunning = state === 'running'
  const isDone = state === 'done'
  const isError = state === 'error' || state === 'cancelled'

  return (
    <button
      id={`batch-card-${name}`}
      onClick={onClick}
      className={`text-left p-5 rounded-xl border cursor-pointer transition-all flex flex-col gap-3 ${
        selected
          ? 'border-primary bg-primary/5 shadow-[0_0_15px_rgba(76,215,246,0.1)]'
          : isError
          ? 'border-error/30 bg-surface-container-low hover:border-error/40'
          : isDone
          ? 'border-primary/40 bg-surface-container-low hover:border-primary/60'
          : 'border-outline-variant/10 bg-surface-container-low hover:border-outline-variant/30'
      }`}
    >
      <div className="flex items-center gap-2 min-w-0">
        <span className={`material-symbols-outlined text-[18px] shrink-0 ${isDone ? 'text-primary' : isError ? 'text-error' : 'text-outline'}`}>
          picture_as_pdf
        </span>
        <span className="text-xs font-black text-on-surface tracking-tight truncate flex-1 min-w-0">{name}</span>
        {isRunning && <span className="w-2 h-2 rounded-full bg-primary animate-pulse shrink-0" />}
      </div>

      <div className="flex items-center gap-1.5 flex-wrap">
        {[1, 2, 6].map(step => (
          <StepChip key={step} step={step} status={stepChipStatus(live, step as 1 | 2 | 6)} />
        ))}
      </div>

      <div className="flex items-center gap-2">
        <span className={`${CHIP_BASE} ${chip.cls}`}>{chip.label}</span>
        {isDone && (
          <span className="text-[9px] font-black uppercase tracking-widest text-primary inline-flex items-center gap-0.5">
            View results
            <span className="material-symbols-outlined text-[12px]">chevron_right</span>
          </span>
        )}
      </div>
    </button>
  )
}

