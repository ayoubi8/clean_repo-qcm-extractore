import { useNavigate } from 'react-router-dom'
import { useAppStore } from '../../store/appStore'

interface ActionButtonProps {
  icon: string
  label: string
  onClick: () => void
  disabled?: boolean
  variant: "primary" | "secondary" | "ghost"
  id: string
}

function ActionButton({ icon, label, onClick, disabled, variant, id }: ActionButtonProps) {
  const styles = {
    primary:   "bg-primary text-on-primary hover:bg-primary/90 shadow-lg shadow-primary/20",
    secondary: "bg-secondary-container text-on-secondary-container hover:opacity-90",
    ghost:     "text-on-surface-variant hover:bg-surface-container-high border border-outline-variant/10",
  }

  return (
    <button
      id={id}
      onClick={onClick}
      disabled={disabled}
      className={`w-full flex items-center gap-3 px-4 py-3.5 rounded-xl text-xs font-black uppercase tracking-widest transition-all disabled:opacity-40 disabled:cursor-not-allowed ${styles[variant]}`}
    >
      <span className="material-symbols-outlined text-[20px]">{icon}</span>
      <span className="flex-1 text-left">{label}</span>
      {!disabled && variant !== 'ghost' && (
        <span className="material-symbols-outlined text-[16px] opacity-40">chevron_right</span>
      )}
    </button>
  )
}

export function QuickActions() {
  const activeProject = useAppStore(s => s.activeProject)
  const setLauncherOpen = useAppStore(s => s.setLauncherOpen)
  const navigate = useNavigate()

  return (
    <div className="bg-surface-container rounded-2xl p-6 border border-outline-variant/10 flex flex-col gap-3 h-[240px] shadow-sm">
      <p className="text-[10px] uppercase tracking-widest text-outline font-black mb-2">
        Quick Actions
      </p>

      {/* Go to pipeline */}
      <ActionButton
        id="dash-action-pipeline"
        icon="account_tree"
        label="Open Pipeline"
        onClick={() => navigate('/pipeline')}
        disabled={!activeProject}
        variant="primary"
      />

      {/* Open launcher — new project */}
      <ActionButton
        id="dash-action-new"
        icon="add_circle"
        label="New Project"
        onClick={() => setLauncherOpen(true)}
        variant="secondary"
      />

      {/* Settings shortcut */}
      <ActionButton
        id="dash-action-settings"
        icon="settings"
        label="Settings & Keys"
        onClick={() => navigate('/settings')}
        variant="ghost"
      />
    </div>
  )
}
