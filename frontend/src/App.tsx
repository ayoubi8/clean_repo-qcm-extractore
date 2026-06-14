import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useEffect } from 'react'
import { Sidebar } from './components/shell/Sidebar'
import { TopBar } from './components/shell/TopBar'
import { ProjectLauncher } from './components/launcher/ProjectLauncher'
import { Dashboard } from './pages/Dashboard'
import { Pipeline } from './pages/Pipeline'
import { Settings } from './pages/Settings'
import { Login } from './pages/Login'
import { Register } from './pages/Register'
import { AdminPanel } from './pages/AdminPanel'
import { useAppStore } from './store/appStore'
import { useAuthStore } from './store/authStore'

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
  const isLauncherOpen = useAppStore((s) => s.isLauncherOpen)
  const loadFromStorage = useAuthStore((s) => s.loadFromStorage)

  useEffect(() => { loadFromStorage() }, [])

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route path="/admin" element={<AdminRoute><AdminPanel /></AdminRoute>} />
        <Route path="/*" element={
          <PrivateRoute>
            <div className="flex h-screen overflow-hidden bg-surface text-on-surface font-sans">
              <Sidebar />
              <div className="flex flex-col flex-1 overflow-hidden ml-64">
                <TopBar />
                <main className="flex-1 overflow-y-auto pt-16">
                  <Routes>
                    <Route path="/" element={<Dashboard />} />
                    <Route path="/pipeline" element={<Pipeline />} />
                    <Route path="/settings" element={<Settings />} />
                    <Route path="*" element={<Navigate to="/" replace />} />
                  </Routes>
                </main>
              </div>
              {isLauncherOpen && <ProjectLauncher />}
            </div>
          </PrivateRoute>
        } />
      </Routes>
    </BrowserRouter>
  )
}
