import { CostSummary, Project } from '../../types'

interface CostOverviewCardProps {
  summary: CostSummary | null
  loading: boolean
  activeProject: Project | null
}

/** Per-model bars when the cost file gives models; per-step bars otherwise
 *  (costs read from the SQL table have no model breakdown). */
function breakdown(summary: CostSummary): [string, { cost: number }][] {
  const models = Object.entries(summary.per_model ?? {}).filter(([, d]) => (d?.cost ?? 0) > 0)
  if (models.length > 0) return models
  return Object.entries(summary.per_step ?? {})
    .filter(([, d]) => (d?.total_cost ?? 0) > 0)
    .sort(([a], [b]) => parseFloat(a) - parseFloat(b))
    .map(([step, d]) => [/^\d/.test(step) ? `Step ${step}` : step, { cost: d.total_cost }])
}

export function CostOverviewCard({ summary, loading, activeProject }: CostOverviewCardProps) {
  if (loading) {
    return (
      <div className="bg-surface-container rounded-2xl p-6 border border-outline-variant/10 animate-pulse space-y-4 h-[240px]">
        <div className="h-4 w-1/3 bg-surface-container-high rounded" />
        <div className="h-10 w-1/2 bg-surface-container-high rounded" />
        <div className="space-y-2">
          <div className="h-2 w-full bg-surface-container-high rounded" />
          <div className="h-2 w-full bg-surface-container-high rounded" />
        </div>
      </div>
    )
  }

  return (
    <div className="bg-surface-container rounded-2xl p-6 border border-outline-variant/10 flex flex-col h-[240px] shadow-sm">
      <p className="text-[10px] uppercase tracking-widest text-outline font-bold mb-4">
        Project Cost — <span className="text-on-surface-variant truncate inline-block max-w-[120px] align-bottom">{activeProject?.name ?? "No project"}</span>
      </p>

      {/* Big total */}
      <div className="flex items-end gap-3 mb-6">
        <span className="text-4xl font-black text-primary font-mono tracking-tighter">
          ${summary?.total_cost.toFixed(4) ?? "0.0000"}
        </span>
        <span className="text-[10px] text-outline mb-2 font-mono uppercase tracking-widest">
          {summary?.total_tokens.toLocaleString() ?? "0"} tokens
        </span>
      </div>

      {/* Per-model mini bars */}
      <div className="flex-1 overflow-y-auto custom-scrollbar pr-2 space-y-4">
        {summary && breakdown(summary).length > 0 ? (
          breakdown(summary).map(([model, data]) => {
            const pct = summary.total_cost > 0
              ? (data.cost / summary.total_cost) * 100 : 0
            return (
              <div key={model}>
                <div className="flex justify-between text-[10px] mb-1.5">
                  <span className="text-on-surface-variant font-bold capitalize">
                    {model.replace(/_/g, " ")}
                  </span>
                  <span className="font-mono text-primary font-black">${data.cost.toFixed(4)}</span>
                </div>
                <div className="h-1 bg-surface-container-high rounded-full overflow-hidden">
                  <div
                    className="h-1 bg-primary rounded-full transition-all duration-1000 ease-out"
                    style={{ width: `${pct}%` }}
                  />
                </div>
              </div>
            )
          })
        ) : (
          <div className="flex flex-col items-center justify-center h-full opacity-40">
            <span className="material-symbols-outlined text-3xl mb-1">payments</span>
            <p className="text-[10px] text-outline italic font-medium">
              {activeProject ? "Run a step to see cost data" : "Select a project to see costs"}
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
