import { useState } from 'react'
import { useAppStore } from '../../store/appStore'
import { CostSummaryPanel } from '../cost/CostSummaryPanel'

function PipelineStatusChip({ status }: { status: 'idle' | 'running' }) {
  return (
    <div className={`flex items-center gap-2 px-3 py-1 rounded-full text-[11px] font-bold uppercase tracking-wider ${
      status === 'running' 
        ? 'bg-primary-container/20 text-primary border border-primary/20' 
        : 'bg-surface-container-high text-outline border border-outline/10'
    }`}>
      {status === 'running' && (
        <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
      )}
      {status}
    </div>
  )
}

function NotificationBell() {
  return (
    <div className="relative cursor-pointer hover:bg-surface-container rounded-lg p-2 transition-colors">
      <span className="material-symbols-outlined text-on-surface-variant">notifications</span>
      <span className="absolute top-2 right-2 w-2 h-2 bg-error rounded-full border-2 border-surface" />
    </div>
  )
}

import { createPortal } from 'react-dom'

export function TopBar() {
  const [showCosts, setShowCosts] = useState(false)
  const activeProject = useAppStore((s) => s.activeProject)
  const pipelineStatus = useAppStore((s) => s.pipelineStatus)
  const setActiveProject = useAppStore((s) => s.setActiveProject)

  return (
    <header className="fixed top-0 right-0 left-64 h-16 z-30 flex items-center justify-between px-8 bg-surface/60 backdrop-blur-xl border-b border-outline-variant/10">
      {/* Left: project name + status chip */}
      <div className="flex items-center gap-4">
        <span className="text-sm font-bold text-on-surface tracking-tight" id="active-project-name">
          { activeProject?.name ?? 'No Project Selected' }
        </span>
        <PipelineStatusChip status={pipelineStatus} />
      </div>

      {/* Right: Switch Project button + notifications stub */}
      <div className="flex items-center gap-6">
        <button 
          id="btn-switch-project"
          onClick={() => setActiveProject(null)}
          className="text-xs font-semibold text-primary hover:text-primary-fixed transition-colors underline underline-offset-4"
        >
          Switch Project
        </button>

        <button
          id="btn-open-costs"
          onClick={() => setShowCosts(true)}
          className="text-outline hover:text-on-surface transition-colors flex items-center gap-2 group"
          title="Cost Summary"
        >
          <span className="material-symbols-outlined text-[20px] group-hover:scale-110 transition-transform">payments</span>
          <span className="text-[10px] font-black uppercase tracking-widest hidden sm:inline">Costs</span>
        </button>

        <NotificationBell />
      </div>

      {showCosts && createPortal(<CostSummaryPanel onClose={() => setShowCosts(false)} />, document.body)}
    </header>
  )
}
