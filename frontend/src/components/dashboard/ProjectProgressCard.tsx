import { Project } from '../../types'

interface ProjectProgressCardProps {
  project: Project | null
  allProjects: Project[]
  loading: boolean
}

export function ProjectProgressCard({ project, allProjects, loading }: ProjectProgressCardProps) {
  if (loading) {
    return (
      <div className="bg-surface-container rounded-2xl p-6 border border-outline-variant/10 animate-pulse space-y-4 h-[240px]">
        <div className="h-4 w-1/2 bg-surface-container-high rounded" />
        <div className="h-2 w-full bg-surface-container-high rounded" />
        <div className="h-8 w-1/4 bg-surface-container-high rounded" />
      </div>
    )
  }

// Steps 1.5, 1.6, 4 & 5 are intentionally absent — they run as invisible
// backend steps (1.5/1.6 in the autorun sequence; 4/5 inside Step 3's cascade).
const steps = [1, 2, 3, 6, 7, 8]
// last_step from backend may be 4 or 5 (auto-build marked them done). Map
// those hidden step ids back to the visible Step 3 so the bar reflects what
// the user actually sees in the UI.
const rawLastStep = project?.last_step ?? 0
const lastStep = (rawLastStep === 4 || rawLastStep === 5) ? 3 : rawLastStep

  return (
    <div className="bg-surface-container rounded-2xl p-6 border border-outline-variant/10 flex flex-col h-[240px] shadow-sm">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <p className="text-[10px] uppercase tracking-widest text-outline font-bold">
            Active Project
          </p>
          <h3 className="text-lg font-black text-on-surface mt-1 truncate max-w-[280px]">
            {project?.name ?? "No project selected"}
          </h3>
        </div>
        <span className={`text-[10px] font-black px-3 py-1 rounded-full uppercase tracking-widest
          ${project ? "bg-primary/10 text-primary border border-primary/20"
                    : "bg-surface-container-high text-outline"}`}>
          {project ? `Stage ${lastStep} / 8` : "—"}
        </span>
      </div>

      {/* Step progress bar — 8 segments (Steps 4 & 5 hidden — auto-build) */}
      <div className="flex gap-1.5 mb-4">
        {steps.map((step, i) => {
          const currentIdx = steps.indexOf(lastStep)
          const isFilled = i <= currentIdx

          return (
            <div
              key={step}
              className={`h-2 flex-1 rounded-full transition-all duration-500 ${
                isFilled ? "bg-primary shadow-[0_0_8px_rgba(76,215,246,0.4)]" : "bg-surface-container-high"
              }`}
            />
          )
        })}
      </div>

      {/* Step labels */}
      <div className="flex justify-between text-[9px] text-outline font-mono opacity-60">
        {steps.map(s => <span key={s}>{s}</span>)}
      </div>
      <p className="text-[8px] text-outline/40 italic mt-1">Steps 4 & 5 run automatically after Step 3</p>

      {/* Total projects stat */}
      <div className="mt-auto pt-4 border-t border-outline-variant/10 flex items-center justify-between">
        <span className="text-[10px] font-bold uppercase tracking-widest text-outline">Total projects in system</span>
        <span className="text-xl font-black text-on-surface font-mono">
          {allProjects.length.toString().padStart(2, '0')}
        </span>
      </div>
    </div>
  )
}
