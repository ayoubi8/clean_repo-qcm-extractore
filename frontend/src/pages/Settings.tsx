import { NavLink, Outlet } from 'react-router-dom'
import { ApiKeysSection } from '../components/settings/ApiKeysSection'
import { YamlEditorSection } from '../components/settings/YamlEditorSection'
import { ModelConfigSection } from '../components/settings/ModelConfigSection'

/**
 * /settings/* (lag plan Phase 4): one sub-page per section instead of one
 * long page — /settings/keys, /settings/models, /settings/batch.
 */

const TABS = [
  { to: 'keys', label: 'API keys', icon: 'key' },
  { to: 'models', label: 'Models', icon: 'neurology' },
  { to: 'batch', label: 'Batch rules', icon: 'tune' },
]

export function SettingsLayout() {
  return (
    <div className="max-w-4xl mx-auto px-6 sm:px-8 py-12 pb-32 qe-fade-up">
      <div className="mb-8 border-b border-outline-variant/10 pb-8">
        <h1 className="text-4xl font-black text-on-surface tracking-tighter mb-2">System Settings</h1>
        <p className="text-sm text-outline font-medium">Global environment keys, model configurations, and batch processing rules.</p>
      </div>
      <nav className="flex gap-1 p-1 mb-10 rounded-2xl bg-surface-container-low border border-outline-variant/10 w-fit max-w-full overflow-x-auto" aria-label="Settings">
        {TABS.map((t) => (
          <NavLink
            key={t.to}
            to={t.to}
            className={({ isActive }) =>
              `flex items-center gap-2 h-9 px-4 rounded-xl text-xs font-bold whitespace-nowrap transition-all ${
                isActive ? 'bg-surface-container-highest text-primary shadow-sm' : 'text-outline hover:text-on-surface'
              }`}
          >
            <span className="material-symbols-outlined text-[18px]">{t.icon}</span>
            {t.label}
          </NavLink>
        ))}
      </nav>
      <Outlet />
    </div>
  )
}

export function ApiKeysPage() { return <ApiKeysSection /> }
export function ModelsPage() { return <ModelConfigSection /> }
export function BatchConfigPage() { return <YamlEditorSection /> }
