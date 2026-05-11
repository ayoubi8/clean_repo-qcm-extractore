import { Link, useLocation } from 'react-router-dom'
import { useAppStore } from '../../store/appStore'
import { useAuthStore } from '../../store/authStore'

interface SidebarLinkProps {
  label: 'Dashboard' | 'Pipeline' | 'Settings' | 'Admin Panel'
  route: '/' | '/pipeline' | '/settings' | '/admin'
  icon: string
}

function SidebarLink({ label, route, icon }: SidebarLinkProps) {
  const location = useLocation()
  const isActive = location.pathname === route

  return (
    <Link
      to={route}
      id={`nav-link-${label.toLowerCase().replace(' ', '-')}`}
      className={`flex items-center gap-3 px-4 py-3 rounded-lg text-sm font-medium transition-colors ${
        isActive
          ? 'bg-surface-container text-primary border-r-2 border-primary'
          : 'text-outline hover:text-on-surface hover:bg-surface-container'
      }`}
    >
      <span className="material-symbols-outlined text-xl">{icon}</span>
      {label}
    </Link>
  )
}

function NewProjectButton() {
  const setLauncherOpen = useAppStore((s) => s.setLauncherOpen)

  return (
    <button
      id="btn-new-project-sidebar"
      onClick={() => setLauncherOpen(true)}
      className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-primary-container text-on-primary rounded-xl font-bold hover:opacity-90 transition-opacity"
    >
      <span className="material-symbols-outlined">add</span>
      New Project
    </button>
  )
}

const NAV_ITEMS: SidebarLinkProps[] = [
  { label: 'Dashboard', route: '/', icon: 'dashboard' },
  { label: 'Pipeline', route: '/pipeline', icon: 'account_tree' },
  { label: 'Settings', route: '/settings', icon: 'settings' },
]

export function Sidebar() {
  const user = useAuthStore((s) => s.user)

  return (
    <aside className="fixed left-0 top-0 h-screen w-64 flex flex-col bg-surface-container-lowest border-r border-outline-variant/10 z-40">
      {/* Brand */}
      <div className="p-6 flex items-center gap-3">
        <div className="w-8 h-8 bg-primary flex items-center justify-center rounded-lg shadow-[0_0_15px_rgba(76,215,246,0.3)]">
          <span className="material-symbols-outlined text-on-primary text-sm">terminal</span>
        </div>
        <div>
          <span className="text-lg font-bold tracking-tighter text-primary uppercase">QCM Extractor</span>
          <span className="block text-[10px] text-outline uppercase tracking-widest">v5.0</span>
        </div>
      </div>

      {/* Nav links */}
      <nav className="flex-1 px-4 space-y-1 mt-4">
        {NAV_ITEMS.map((item) => (
          <SidebarLink key={item.route} {...item} />
        ))}
        {user?.is_admin && (
          <SidebarLink label="Admin Panel" route="/admin" icon="admin_panel_settings" />
        )}
      </nav>

      {/* New Project CTA */}
      <div className="px-4 pb-6">
        <NewProjectButton />
      </div>
    </aside>
  )
}
