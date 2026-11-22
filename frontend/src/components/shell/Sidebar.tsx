import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAutorunEnabled } from '../hub/ProjectHub'
import { useAppStore } from '../../store/appStore'
import { useAuthStore } from '../../store/authStore'
import { usePipelineStore } from '../../store/pipelineStore'
import { stepUrl } from '../../lib/routes'

/**
 * App sidebar (shell redesign 2026-11).
 * - Collapsible (persisted in appStore.sidebarCollapsed): 256px ↔ 76px.
 * - Active page marked by a sliding highlight + accent bar.
 * - "Pipeline" shows a live pulse while a step runs.
 * - Active-project card + signed-in user footer.
 */

type Route = '/' | '/projects' | '/pipeline' | '/batches' | '/settings' | '/admin'

interface NavItem {
  label: 'Dashboard' | 'Projects' | 'Pipeline' | 'Batches' | 'Settings' | 'Admin Panel'
  route: Route
  icon: string
  /** Extra path prefixes that belong to this section. */
  also?: string[]
  /** Custom "is this section open" test (wins over route/also). */
  match?: (pathname: string) => boolean
}

const ITEM_H = 44   // px — row height (h-11)
const ITEM_GAP = 4  // px — space-y-1

function isActiveRoute(pathname: string, item: NavItem): boolean {
  if (item.match) return item.match(pathname)
  if (item.route === '/') return pathname === '/'
  return [item.route, ...(item.also ?? [])].some(
    (r) => pathname === r || pathname.startsWith(`${r}/`))
}

function SidebarLink({ item, to, active, collapsed, running }: {
  item: NavItem; to: string; active: boolean; collapsed: boolean; running: boolean
}) {
  return (
    <Link
      to={to}
      id={`nav-link-${item.label.toLowerCase().replace(' ', '-')}`}
      title={collapsed ? item.label : undefined}
      aria-current={active ? 'page' : undefined}
      className={`group relative z-10 flex items-center h-11 rounded-xl text-sm font-medium transition-colors ${
        collapsed ? 'justify-center px-0' : 'gap-3 px-4'
      } ${active ? 'text-primary' : 'text-outline hover:text-on-surface'}`}
    >
      <span
        className="material-symbols-outlined text-xl transition-transform duration-200 group-hover:scale-110"
        style={active ? { fontVariationSettings: "'FILL' 1, 'wght' 500" } : undefined}
      >
        {item.icon}
      </span>
      {!collapsed && <span className="truncate">{item.label}</span>}
      {running && (
        <span
          className={`absolute w-2 h-2 rounded-full bg-primary qe-ring ${collapsed ? 'top-2 right-3' : 'right-4'}`}
          aria-label="A step is running"
        />
      )}
    </Link>
  )
}

const NAV_ITEMS: NavItem[] = [
  { label: 'Dashboard', route: '/', icon: 'dashboard' },
  { label: 'Projects', route: '/projects', icon: 'folder_open',
    match: (p) => p === '/projects' || p === '/projects/new' },
  // /projects/<name>/… is the open project's workspace.
  { label: 'Pipeline', route: '/pipeline', icon: 'account_tree',
    match: (p) => p === '/pipeline' || (/^\/projects\/[^/]+/.test(p) && p !== '/projects/new') },
  { label: 'Batches', route: '/batches', icon: 'stacks', also: ['/batch', '/autorun'] },
  { label: 'Settings', route: '/settings', icon: 'settings' },
]

export function Sidebar() {
  const user = useAuthStore((s) => s.user)
  const logout = useAuthStore((s) => s.logout)
  const collapsed = useAppStore((s) => s.sidebarCollapsed ?? false)
  const setCollapsed = useAppStore((s) => s.setSidebarCollapsed)
  const navigate = useNavigate()
  const autorun = useAutorunEnabled()
  const activeProject = useAppStore((s) => s.activeProject)
  const pipelineStatus = useAppStore((s) => s.pipelineStatus)
  const activeStepId = usePipelineStore((s) => s.activeStepId)
  const projectHref = activeProject ? stepUrl(activeProject.name, activeStepId ?? 1) : '/pipeline'
  const { pathname } = useLocation()

  const base = autorun ? NAV_ITEMS : NAV_ITEMS.filter((it) => it.route !== '/batches')
  const items: NavItem[] = user?.is_admin
    ? [...base, { label: 'Admin Panel', route: '/admin', icon: 'admin_panel_settings' }]
    : base
  const activeIndex = items.findIndex((it) => isActiveRoute(pathname, it))
  const running = pipelineStatus === 'running'
  const initial = (user?.email ?? '?').charAt(0).toUpperCase()

  return (
    <aside
      className={`fixed left-0 top-0 h-screen flex flex-col z-40 border-r border-outline-variant/10
        bg-gradient-to-b from-surface-container-lowest via-surface-container-lowest to-[#0b1416]
        transition-[width] duration-300 ease-out ${collapsed ? 'w-[76px]' : 'w-64'}`}
    >
      {/* Brand */}
      <div className={`h-16 flex items-center ${collapsed ? 'justify-center' : 'gap-3 px-5'}`}>
        <div className="relative w-9 h-9 shrink-0 rounded-xl bg-gradient-to-br from-primary to-primary-container flex items-center justify-center shadow-[0_0_18px_rgba(76,215,246,0.35)]">
          <span className="material-symbols-outlined text-on-primary text-[18px]">quiz</span>
          {running && <span className="absolute -top-0.5 -right-0.5 w-2.5 h-2.5 rounded-full bg-tertiary border-2 border-surface-container-lowest qe-blink" />}
        </div>
        {!collapsed && (
          <div className="min-w-0">
            <span className="block text-[15px] font-black tracking-tight text-on-surface leading-tight">
              QCM <span className="text-primary">Extractor</span>
            </span>
            <span className="inline-block mt-0.5 px-1.5 py-px rounded-md bg-primary/10 text-[9px] font-bold text-primary uppercase tracking-widest">
              v5.0
            </span>
          </div>
        )}
      </div>

      {/* Nav */}
      <nav className="relative px-3 mt-4" aria-label="Main">
        {activeIndex >= 0 && (
          <div
            aria-hidden
            className="absolute left-3 right-3 h-11 rounded-xl bg-primary/10 border border-primary/20 shadow-[inset_0_0_12px_rgba(76,215,246,0.08)] transition-transform duration-300 ease-out"
            style={{ transform: `translateY(${activeIndex * (ITEM_H + ITEM_GAP)}px)` }}
          >
            <span className="absolute left-0 top-2.5 bottom-2.5 w-[3px] rounded-r-full bg-primary" />
          </div>
        )}
        <div className="space-y-1">
          {items.map((item, i) => (
            <SidebarLink
              key={item.route}
              item={item}
              to={item.route === '/pipeline' ? projectHref : item.route}
              active={i === activeIndex}
              collapsed={collapsed}
              running={item.route === '/pipeline' && running}
            />
          ))}
        </div>
      </nav>

      <div className="flex-1" />

      {/* Active project */}
      {activeProject && !collapsed && (
        <Link
          to={projectHref}
          className="mx-3 mb-3 p-3 rounded-xl bg-surface-container/70 border border-outline-variant/10 hover:border-primary/30 transition-colors group"
        >
          <p className="text-[9px] font-black uppercase tracking-[0.2em] text-outline">Active project</p>
          <div className="flex items-center gap-2 mt-1">
            <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${running ? 'bg-primary qe-blink' : 'bg-outline/60'}`} />
            <span className="text-xs font-bold text-on-surface truncate group-hover:text-primary transition-colors">
              {activeProject.name}
            </span>
          </div>
          <p className="text-[10px] text-outline mt-0.5">{running ? 'Running…' : 'Idle'}</p>
        </Link>
      )}

      {/* New Project CTA */}
      <div className="px-3 pb-3">
        <button
          id="btn-new-project-sidebar"
          onClick={() => navigate('/projects/new')}
          title={collapsed ? 'New Project' : undefined}
          className={`w-full flex items-center justify-center gap-2 h-11 rounded-xl font-bold text-on-primary
            bg-gradient-to-r from-primary-container to-primary hover:shadow-[0_0_20px_rgba(76,215,246,0.35)]
            active:scale-[0.98] transition-all`}
        >
          <span className="material-symbols-outlined">add</span>
          {!collapsed && 'New Project'}
        </button>
      </div>

      {/* User + collapse */}
      <div className={`border-t border-outline-variant/10 p-3 flex items-center ${collapsed ? 'flex-col gap-2' : 'gap-2'}`}>
        {user && (
          <div className={`flex items-center gap-2 min-w-0 ${collapsed ? '' : 'flex-1'}`} title={user.email}>
            <div className="w-8 h-8 shrink-0 rounded-full bg-secondary-container text-on-secondary-container text-xs font-black flex items-center justify-center">
              {initial}
            </div>
            {!collapsed && (
              <div className="min-w-0">
                <p className="text-[11px] font-bold text-on-surface truncate">{user.email}</p>
                <button onClick={() => { void logout() }} className="text-[10px] text-outline hover:text-error transition-colors">
                  Sign out
                </button>
              </div>
            )}
          </div>
        )}
        <button
          id="btn-sidebar-collapse"
          onClick={() => setCollapsed?.(!collapsed)}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          className="w-8 h-8 shrink-0 rounded-lg flex items-center justify-center text-outline hover:text-primary hover:bg-primary/10 transition-colors"
        >
          <span className="material-symbols-outlined text-[18px]">
            {collapsed ? 'left_panel_open' : 'left_panel_close'}
          </span>
        </button>
      </div>
    </aside>
  )
}
