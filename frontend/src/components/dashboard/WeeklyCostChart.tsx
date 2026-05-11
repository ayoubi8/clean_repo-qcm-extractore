interface WeeklyCostChartProps {
  weeklyData: Record<string, { cost: number; projects: string[] }>
  loading: boolean
}

export function WeeklyCostChart({ weeklyData, loading }: WeeklyCostChartProps) {
  if (loading) {
    return (
      <div className="bg-surface-container rounded-2xl p-6 border border-outline-variant/10 animate-pulse space-y-4 h-[240px]">
        <div className="h-4 w-1/3 bg-surface-container-high rounded" />
        <div className="flex items-end gap-2 h-24 mt-8">
          {[1, 2, 3, 4, 5, 6].map(i => (
            <div key={i} className="flex-1 bg-surface-container-high rounded-t h-full opacity-50" />
          ))}
        </div>
      </div>
    )
  }

  const weeks = Object.entries(weeklyData).slice(-6)  // last 6 weeks
  const maxCost = Math.max(...weeks.map(([, d]) => d.cost), 0.001)

  return (
    <div className="bg-surface-container rounded-2xl p-6 border border-outline-variant/10 flex flex-col h-[240px] shadow-sm">
      <div className="flex items-center justify-between mb-8">
        <p className="text-[10px] uppercase tracking-widest text-outline font-bold">
          Weekly Spend
        </p>
        <span className="text-[9px] font-mono text-outline opacity-40 uppercase tracking-widest">Last 6 Weeks</span>
      </div>

      <div className="flex items-end gap-3 h-20 mb-2">
        {weeks.map(([week, data]) => {
          return (
            <div key={week} className="flex-1 flex flex-col items-center gap-2 group relative">
              {/* Tooltip */}
              <div className="opacity-0 group-hover:opacity-100 transition-opacity absolute -top-8 z-10 pointer-events-none">
                <div className="text-[10px] font-mono font-black text-primary bg-surface-container-highest px-2 py-1 rounded shadow-xl border border-outline-variant/20 whitespace-nowrap">
                  ${data.cost.toFixed(4)}
                </div>
                <div className="w-1.5 h-1.5 bg-surface-container-highest border-r border-b border-outline-variant/20 rotate-45 mx-auto -mt-1" />
              </div>
              
              {/* Bar */}
              <div
                className="w-full bg-primary/20 hover:bg-primary/60 border-t border-x border-primary/10 rounded-t-sm transition-all duration-500 cursor-help"
                style={{ height: `${Math.max((data.cost / maxCost) * 80, 6)}px` }}
              />
              
              {/* Label */}
              <span className="text-[8px] text-outline font-black uppercase tracking-tighter opacity-60">
                {week.split("-W")[1] || week}W
              </span>
            </div>
          )
        })}
        {weeks.length === 0 && (
          <div className="flex flex-col items-center justify-center w-full h-full opacity-20">
            <span className="material-symbols-outlined text-4xl mb-1">analytics</span>
            <p className="text-[10px] font-bold uppercase tracking-widest">No data collected</p>
          </div>
        )}
      </div>
      
      <div className="pt-4 border-t border-outline-variant/5 mt-auto">
        <p className="text-[9px] text-outline italic leading-tight">
          Costs are aggregated across all active projects for the specified period.
        </p>
      </div>
    </div>
  )
}
