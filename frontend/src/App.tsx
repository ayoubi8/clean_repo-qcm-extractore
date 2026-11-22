import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { Suspense, lazy, useEffect } from 'react'
import { Sidebar } from './components/shell/Sidebar'
import { TopBar } from './components/shell/TopBar'
import { Login } from './pages/Login'
import { Register } from './pages/Register'
import { ProjectLayout } from './components/project/ProjectLayout'
import { Toaster } from './components/ui/Toaster'
import { fetchBootstrap } from './lib/api'
import { useAppStore } from './store/appStore'
import { useAuthStore } from './store/authStore'

// Lag plan Phase 4 / §5: each page is its own chunk, loaded when first opened
// (the step panels, the Monaco editor and the admin panel no longer weigh on
// the first load).
function named<M>(load: () => Promise<M>, name: keyof M) {
  return lazy(() => load().then((m) => ({ default: m[name] as unknown as React.ComponentType<any> })))
}

const Dashboard = named(() => import('./pages/Dashboard'), 'Dashboard')
const BatchView = named(() => import('./pages/BatchView'), 'BatchView')
const AdminPanel = named(() => import('./pages/AdminPanel'), 'AdminPanel')
const SettingsLayout = named(() => import('./pages/Settings'), 'SettingsLayout')
const ApiKeysPage = named(() => import('./pages/Settings'), 'ApiKeysPage')
const ModelsPage = named(() => import('./pages/Settings'), 'ModelsPage')
const BatchConfigPage = named(() => import('./pages/Settings'), 'BatchConfigPage')
const ProjectsPage = named(() => import('./pages/ProjectsPages'), 'ProjectsPage')
const NewProjectPage = named(() => import('./pages/ProjectsPages'), 'NewProjectPage')
const AutoRunPage = named(() => import('./pages/ProjectsPages'), 'AutoRunPage')
const BatchesPage = named(() => import('./pages/ProjectsPages'), 'BatchesPage')
const ProjectWorkspace = named(() => import('./pages/ProjectWorkspace'), 'ProjectWorkspace')
const ProjectIndex = named(() => import('./pages/ProjectWorkspace'), 'ProjectIndex')
const PipelineRedirect = named(() => import('./pages/ProjectWorkspace'), 'PipelineRedirect')
const ResultsPage = named(() => import('./pages/ResultsPage'), 'ResultsPage')

function PageFallback() {
  return (
    <div className="flex items-center justify-center h-[calc(100vh-64px)] text-outline">
      <span className="material-symbols-outlined animate-spin text-[22px]">progress_activity</span>
    </div>
  )
}

function PrivateRoute({ children }: { children: React.ReactNode }) {
  const token = useAuthStore((s) => s.token)
  const initialized = useAuthStore((s) => s.initialized)
  if (!initialized) return null  // wait until localStorage is read before deciding
  if (!token) return <Navigate to="/login" replace />
  return <>{children}</>
}

function AdminRoute({ children }: { children: React.ReactNode }) {
  const token = useAuthStore((s) => s.token)
  const user = useAuthStore((s) => s.user)
  const initialized = useAuthStore((s) => s.initialized)
  if (!initialized) return null
  if (!token) return <Navigate to="/login" replace />
  if (!user?.is_admin) return <Navigate to="/" replace />
  return <>{children}</>
}

export default function App() {
  const sidebarCollapsed = useAppStore((s) => s.sidebarCollapsed ?? false)
  const loadFromStorage = useAuthStore((s) => s.loadFromStorage)
  const token = useAuthStore((s) => s.token)

  useEffect(() => { loadFromStorage() }, [])
  // One request per login warms models, feature flags and tags for every
  // page (lag plan Phases 1 + 4).
  useEffect(() => { if (token) fetchBootstrap().catch(() => {}) }, [token])

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route path="/admin" element={<AdminRoute><Suspense fallback={<PageFallback />}><AdminPanel /></Suspense></AdminRoute>} />
        <Route path="/*" element={
          <PrivateRoute>
            <div className="flex h-screen overflow-hidden bg-surface text-on-surface font-sans">
              <Sidebar />
              <div className={`flex flex-col flex-1 overflow-hidden transition-[margin] duration-300 ${sidebarCollapsed ? 'ml-[76px]' : 'ml-64'}`}>
                <TopBar />
                <main className="flex-1 overflow-y-auto pt-16">
                  <Suspense fallback={<PageFallback />}>
                    <Routes>
                      <Route path="/" element={<Dashboard />} />
                      <Route path="/projects" element={<ProjectsPage />} />
                      <Route path="/projects/new" element={<NewProjectPage />} />
                      <Route path="/projects/:name" element={<ProjectLayout />}>
                        <Route index element={<ProjectIndex />} />
                        <Route path="steps" element={<ProjectIndex />} />
                        <Route path="steps/:stepId" element={<ProjectWorkspace />} />
                        <Route path="outputs" element={<ResultsPage />} />
                        <Route path="autorun" element={<ProjectWorkspace autorun />} />
                      </Route>
                      <Route path="/autorun/new" element={<AutoRunPage />} />
                      <Route path="/batches" element={<BatchesPage />} />
                      <Route path="/pipeline" element={<PipelineRedirect />} />
                      <Route path="/batch/:batchId" element={<BatchView />} />
                      <Route path="/settings" element={<SettingsLayout />}>
                        <Route index element={<Navigate to="keys" replace />} />
                        <Route path="keys" element={<ApiKeysPage />} />
                        <Route path="models" element={<ModelsPage />} />
                        <Route path="batch" element={<BatchConfigPage />} />
                      </Route>
                      <Route path="*" element={<Navigate to="/" replace />} />
                    </Routes>
                  </Suspense>
                </main>
              </div>
            </div>
          </PrivateRoute>
        } />
      </Routes>
      <Toaster />
    </BrowserRouter>
  )
}
