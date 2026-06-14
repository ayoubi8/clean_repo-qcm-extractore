import React, { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'
import { useAppStore } from '../store/appStore'
import {
  fetchAdminUsers,
  fetchAdminStats,
  approveUser,
  rejectUser,
  setUserApiKey,
  setUserModels,
  fetchAdminUserProjects
} from '../lib/api'

// --- Main Component ---

export function AdminPanel() {
  const [activeTab, setActiveTab] = useState<'users' | 'stats' | 'projects'>('users')
  const [users, setUsers] = useState<any[]>([])
  const [stats, setStats] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  
  const navigate = useNavigate()
  const logout = useAuthStore(s => s.logout)
  const userEmail = useAuthStore(s => s.user?.email)
  const setActiveProject = useAppStore(s => s.setActiveProject)

  const loadUsers = useCallback(async () => {
    setLoading(true)
    try {
      const data = await fetchAdminUsers()
      setUsers(data)
    } catch (err: any) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  const loadStats = useCallback(async () => {
    setLoading(true)
    try {
      const data = await fetchAdminStats()
      setStats(data)
    } catch (err: any) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  // Always load users on mount
  useEffect(() => { loadUsers() }, [loadUsers])

  useEffect(() => {
    if (activeTab === 'stats') loadStats()
  }, [activeTab, loadStats])

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  return (
    <div className="min-h-screen bg-background text-on-surface font-sans selection:bg-primary/30 relative">
      {/* Bottom Accent Glow */}
      <div className="fixed bottom-0 left-0 w-full h-1 bg-gradient-to-r from-transparent via-primary/20 to-transparent opacity-50 z-0"></div>

      {/* Fixed Top Header Bar */}
      <header className="fixed top-0 z-50 w-full flex items-center justify-between px-6 py-3 bg-[#0e0e0e] border-b border-[#3d494c]/20 shadow-[0px_24px_48px_rgba(0,0,0,0.4)] h-16">
        <div className="flex items-center gap-4">
          <span className="material-symbols-outlined text-primary text-2xl">settings</span>
          <div className="flex flex-col leading-tight">
            <span className="text-lg font-bold tracking-tighter text-primary uppercase">Admin Panel</span>
            <span className="text-[10px] uppercase tracking-widest text-outline font-semibold">System Control</span>
          </div>
        </div>
        
        <div className="flex items-center gap-6">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-full bg-surface-container border border-outline-variant/30 flex items-center justify-center overflow-hidden">
              <span className="material-symbols-outlined text-outline text-lg">person</span>
            </div>
            <span className="text-sm font-medium text-on-surface-variant hidden sm:inline">{userEmail}</span>
          </div>
          <button 
            onClick={handleLogout}
            className="flex items-center gap-2 px-4 py-1.5 bg-surface-container-high hover:bg-surface-container-highest text-on-surface text-sm font-medium rounded-lg transition-all active:scale-95 border border-outline-variant/20"
          >
            <span className="material-symbols-outlined text-sm">logout</span>
            Logout
          </button>
        </div>
      </header>

      <main className="pt-16 max-w-[1600px] mx-auto px-6 relative z-10">
        {/* Tab Navigation */}
        <nav className="flex gap-8 mt-8 border-b border-outline-variant/10">
          {(['users', 'stats', 'projects'] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`pb-2 text-sm transition-all relative ${
                activeTab === tab
                  ? 'text-primary font-semibold'
                  : 'text-outline hover:text-on-surface'
              }`}
            >
              {tab.charAt(0).toUpperCase() + tab.slice(1)}
              {activeTab === tab && (
                <div className="absolute bottom-0 left-0 w-full h-[2px] bg-primary animate-in fade-in slide-in-from-bottom-1 duration-300"></div>
              )}
            </button>
          ))}
        </nav>

        {error && (
          <div className="mt-6 p-4 bg-error-container/20 text-error border border-error/30 rounded-xl flex items-center gap-3">
            <span className="material-symbols-outlined">warning</span>
            <span className="text-sm font-medium">Error: {error}</span>
          </div>
        )}

        {/* Tab Content */}
        <div className="mt-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
          {activeTab === 'users' && <UsersTab users={users} refresh={loadUsers} />}
          {activeTab === 'stats' && <StatsTab stats={stats} />}
          {activeTab === 'projects' && <ProjectsTab users={users} onSelectProject={(p) => {
            setActiveProject(p)
            navigate('/pipeline')
          }} />}
        </div>
      </main>
    </div>
  )
}

// --- Tab: Users ---

function UsersTab({ users, refresh }: { users: any[], refresh: () => void }) {
  const [editingApiKey, setEditingApiKey] = useState<string | null>(null)
  const [apiKeyVal, setApiKeyVal] = useState('')
  const [expandingModels, setExpandingModels] = useState<string | null>(null)

  const handleApprove = async (uid: string) => {
    try {
      await approveUser(uid)
      refresh()
    } catch (err: any) { alert(err.message) }
  }

  const handleReject = async (uid: string) => {
    if (confirm('Are you sure you want to reject/delete this user?')) {
      try {
        await rejectUser(uid)
        refresh()
      } catch (err: any) { alert(err.message) }
    }
  }

  const handleSaveApiKey = async (uid: string) => {
    try {
      await setUserApiKey(uid, apiKeyVal)
      setEditingApiKey(null)
      refresh()
    } catch (err: any) { alert(err.message) }
  }

  return (
    <div className="bg-surface-container-low rounded-xl overflow-hidden border border-outline-variant/10 shadow-lg">
      <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="bg-surface-container-lowest text-outline text-[11px] uppercase tracking-widest font-semibold border-b border-outline-variant/10">
              <th className="px-6 py-4">User Email</th>
              <th className="px-6 py-4">Joined</th>
              <th className="px-6 py-4 text-center">Status</th>
              <th className="px-6 py-4">API Key</th>
              <th className="px-6 py-4 text-center">Projects</th>
              <th className="px-6 py-4 text-right">Tokens</th>
              <th className="px-6 py-4 text-right">Cost</th>
              <th className="px-6 py-4 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="text-sm">
            {users.map((user) => (
              <React.Fragment key={user.id}>
                <tr className="border-b border-outline-variant/5 hover:bg-surface-container/50 transition-colors group">
                  <td className="px-6 py-4 font-medium text-on-surface">
                    {user.email}
                    {user.is_admin && (
                      <span className="text-[10px] bg-primary/10 text-primary px-1.5 py-0.5 rounded border border-primary/20 ml-2 font-bold uppercase tracking-wider">ADMIN</span>
                    )}
                  </td>
                  <td className="px-6 py-4 text-on-surface-variant">
                    {new Date(user.created_at).toLocaleDateString()}
                  </td>
                  <td className="px-6 py-4 text-center">
                    {user.is_approved ? (
                      <span className="px-2.5 py-1 rounded-full bg-secondary-container text-on-secondary-container text-[10px] font-bold uppercase tracking-wider">Approved</span>
                    ) : (
                      <span className="px-2.5 py-1 rounded-full bg-tertiary-container/20 text-tertiary text-[10px] font-bold uppercase tracking-wider">Pending</span>
                    )}
                  </td>
                  <td className="px-6 py-4 font-mono text-xs">
                    {editingApiKey === user.id ? (
                      <div className="flex items-center gap-2">
                        <input 
                          type="text" 
                          value={apiKeyVal} 
                          onChange={(e) => setApiKeyVal(e.target.value)}
                          className="bg-surface-container border border-outline-variant rounded px-2 py-1 text-xs w-32 focus:outline-none focus:border-primary text-on-surface"
                        />
                        <button onClick={() => handleSaveApiKey(user.id)} className="text-primary font-bold hover:underline">Save</button>
                      </div>
                    ) : (
                      <div className="flex items-center gap-2 text-outline group-hover:text-on-surface transition-colors">
                        <span>sk_••••••••</span>
                        <button 
                          onClick={() => { setEditingApiKey(user.id); setApiKeyVal(user.api_key || '') }}
                          className="material-symbols-outlined text-[16px] hover:text-primary transition-colors"
                        >
                          edit
                        </button>
                      </div>
                    )}
                  </td>
                  <td className="px-6 py-4 text-center">{user.project_count || 0}</td>
                  <td className="px-6 py-4 text-right text-on-surface-variant">{user.total_tokens?.toLocaleString() || 0}</td>
                  <td className="px-6 py-4 text-right text-primary font-semibold font-mono">
                    ${user.total_cost?.toFixed(4) || '0.0000'}
                  </td>
                  <td className="px-6 py-4 text-right">
                    <div className="flex items-center justify-end gap-2">
                      {!user.is_approved && (
                        <button 
                          onClick={() => handleApprove(user.id)}
                          className="px-3 py-1 bg-primary text-on-primary text-[10px] font-bold uppercase rounded hover:shadow-[0_0_15px_rgba(76,215,246,0.3)] transition-all active:scale-95"
                        >
                          Approve
                        </button>
                      )}
                      {!user.is_approved && (
                        <button 
                          onClick={() => handleReject(user.id)}
                          className="px-3 py-1 bg-error-container text-on-error-container text-[10px] font-bold uppercase rounded hover:bg-error transition-all active:scale-95"
                        >
                          Reject
                        </button>
                      )}
                      <button 
                        onClick={() => setExpandingModels(expandingModels === user.id ? null : user.id)}
                        className="p-1.5 hover:bg-surface-container-highest rounded-lg transition-all text-on-surface-variant hover:text-primary"
                      >
                        <span className="material-symbols-outlined text-lg">
                          {expandingModels === user.id ? 'unfold_less' : 'unfold_more'}
                        </span>
                      </button>
                    </div>
                  </td>
                </tr>
                {expandingModels === user.id && (
                  <tr className="bg-surface-container-lowest/50 animate-in fade-in slide-in-from-top-1 duration-300">
                    <td colSpan={8} className="p-6 border-b border-outline-variant/10">
                      <ModelConfigEditor user={user} onSave={refresh} />
                    </td>
                  </tr>
                )}
              </React.Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function ModelConfigEditor({ user, onSave }: { user: any, onSave: () => void }) {
  const slots = [
    { key: 'step1_models', label: 'Step 1 (Primary)' },
    { key: 'step2_models_primary', label: 'Step 2 (Primary)' },
    { key: 'step2_models_fallback', label: 'Step 2 (Fallback)' },
    { key: 'step3_models', label: 'Step 3 Models' },
    { key: 'step6_text_models', label: 'Step 6 Text' },
    { key: 'step6_all_pages_models', label: 'Step 6 All Pages' },
  ]
  
  const [values, setValues] = useState<Record<string, string>>({}) 
  useEffect(() => {
    const res: Record<string, string> = {}
    slots.forEach(s => {
      res[s.key] = (user.allowed_models?.[s.key] || []).join(', ')
    })
    setValues(res)
  }, [user])

  const handleSave = async () => {
    const payload: Record<string, string[]> = {}
    Object.entries(values).forEach(([k, v]) => {
      payload[k] = v.split(',').map(s => s.trim()).filter(Boolean)
    })
    try {
      await setUserModels(user.id, payload)
      onSave()
    } catch (err: any) { alert(err.message) }
  }

  return (
    <div className="space-y-4">
      <h4 className="text-xs font-bold text-primary uppercase tracking-widest">Model Configuration Slots</h4>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {slots.map(s => (
          <div key={s.key} className="space-y-1">
            <label className="text-[10px] text-outline uppercase font-semibold block">{s.label}</label>
            <input 
              type="text"
              value={values[s.key]}
              onChange={(e) => setValues({...values, [s.key]: e.target.value})}
              placeholder="e.g. gpt-4, gemini-pro"
              className="w-full bg-surface-container border-b border-outline-variant focus:border-primary text-xs px-2 py-1.5 outline-none transition-all text-on-surface"
            />
          </div>
        ))}
      </div>
      <div className="flex items-center justify-between mt-6">
        <span className="text-[10px] text-outline italic">
          {Object.values(user.allowed_models || {}).flat().length === 0 ? '(uses global defaults)' : ''}
        </span>
        <button 
          onClick={handleSave}
          className="bg-primary hover:bg-surface-tint text-on-primary text-xs font-bold py-1.5 px-6 rounded shadow-lg shadow-primary/10 transition-all active:scale-95"
        >
          Save Models
        </button>
      </div>
    </div>
  )
}

// --- Tab: Statistics ---

function StatsTab({ stats }: { stats: any }) {
  const [sortKey, setSortKey] = useState<string>('total_cost')
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc')

  if (!stats) return <div className="text-outline animate-pulse">Loading analytics engine...</div>

  const sortedUsers = [...(stats.per_user || [])].sort((a, b) => {
    const valA = a[sortKey] || 0
    const valB = b[sortKey] || 0
    return sortOrder === 'desc' ? valB - valA : valA - valB
  })

  const toggleSort = (key: string) => {
    if (sortKey === key) setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc')
    else {
      setSortKey(key)
      setSortOrder('desc')
    }
  }

  return (
    <div className="space-y-10">
      {/* Overview Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        {[
          { label: 'Total Users', value: stats.total_users, icon: 'groups', color: 'text-on-surface' },
          { label: 'Total Projects', value: stats.total_projects, icon: 'folder_open', color: 'text-on-surface' },
          { label: 'Total Tokens', value: stats.total_tokens?.toLocaleString(), icon: 'analytics', color: 'text-on-surface' },
          { label: 'Total Cost', value: `$${stats.total_cost?.toFixed(2)}`, icon: 'payments', color: 'text-primary' },
        ].map((item, idx) => (
          <div key={idx} className="bg-surface-container p-6 rounded-xl border border-outline-variant/10 shadow-md">
            <span className="text-[10px] text-outline uppercase font-bold tracking-widest block mb-2">{item.label}</span>
            <div className="flex items-center justify-between">
              <div className={`text-3xl font-bold ${item.color}`}>{item.value}</div>
              <span className={`material-symbols-outlined opacity-20 text-3xl ${item.color}`}>{item.icon}</span>
            </div>
            <div className="text-xs text-on-surface-variant mt-2 flex items-center gap-1 opacity-60">
              <span className="material-symbols-outlined text-xs">trending_up</span>
              Updated live
            </div>
          </div>
        ))}
      </div>

      {/* Sorting Table */}
      <div className="bg-surface-container-low rounded-xl border border-outline-variant/10 overflow-hidden shadow-lg">
        <div className="px-6 py-4 border-b border-outline-variant/10 bg-surface-container-lowest">
          <h3 className="text-lg font-bold">User Usage Breakdown</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-surface-container-lowest text-outline text-[11px] uppercase tracking-widest font-semibold">
                <th className="px-6 py-4 cursor-pointer hover:text-on-surface transition-colors" onClick={() => toggleSort('email')}>
                  <div className="flex items-center gap-1">Email {sortKey === 'email' && <span className="material-symbols-outlined text-xs">{sortOrder === 'asc' ? 'expand_less' : 'expand_more'}</span>}</div>
                </th>
                <th className="px-6 py-4 text-center cursor-pointer hover:text-on-surface transition-colors" onClick={() => toggleSort('project_count')}>
                  <div className="flex items-center justify-center gap-1">Projects {sortKey === 'project_count' && <span className="material-symbols-outlined text-xs">{sortOrder === 'asc' ? 'expand_less' : 'expand_more'}</span>}</div>
                </th>
                <th className="px-6 py-4 text-right cursor-pointer hover:text-on-surface transition-colors" onClick={() => toggleSort('total_tokens')}>
                  <div className="flex items-center justify-end gap-1">Tokens {sortKey === 'total_tokens' && <span className="material-symbols-outlined text-xs">{sortOrder === 'asc' ? 'expand_less' : 'expand_more'}</span>}</div>
                </th>
                <th className="px-6 py-4 text-right cursor-pointer hover:text-on-surface transition-colors" onClick={() => toggleSort('total_cost')}>
                  <div className="flex items-center justify-end gap-1">Cost {sortKey === 'total_cost' && <span className="material-symbols-outlined text-xs">{sortOrder === 'asc' ? 'expand_less' : 'expand_more'}</span>}</div>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-outline-variant/5 text-sm">
              {sortedUsers.map(u => (
                <tr key={u.id} className="hover:bg-surface-container transition-colors">
                  <td className="px-6 py-4 font-medium text-on-surface">{u.email}</td>
                  <td className="px-6 py-4 text-center">{u.project_count}</td>
                  <td className="px-6 py-4 text-right text-on-surface-variant font-mono">{u.total_tokens?.toLocaleString()}</td>
                  <td className="px-6 py-4 text-right font-mono text-primary font-semibold">${u.total_cost?.toFixed(4)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

// --- Tab: Projects ---

function ProjectsTab({ users, onSelectProject }: { users: any[], onSelectProject: (p: any) => void }) {
  const [selectedUid, setSelectedUid] = useState('')
  const [projects, setProjects] = useState<any[]>([])
  const [loading, setLoading] = useState(false)

  const handleUserSelect = async (uid: string) => {
    setSelectedUid(uid)
    if (!uid) {
      setProjects([])
      return
    }
    setLoading(true)
    try {
      const data = await fetchAdminUserProjects(uid)
      setProjects(data.projects || [])
    } catch (err: any) { alert(err.message) }
    finally { setLoading(false) }
  }

  return (
    <div className="space-y-8">
      {/* Header Row */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
        <div className="flex flex-col">
          <h2 className="text-2xl font-bold">Project Audit</h2>
          <p className="text-sm text-outline">Monitoring clinical extraction pipelines across all users.</p>
        </div>
        <div className="flex items-center gap-4">
          <label className="text-[11px] font-bold text-outline uppercase tracking-wider">Select User:</label>
          <select 
            value={selectedUid} 
            onChange={(e) => handleUserSelect(e.target.value)}
            className="bg-surface-container border border-outline-variant/30 rounded-lg px-4 py-2 text-sm text-on-surface focus:ring-1 focus:ring-primary outline-none transition-all min-w-[250px]"
          >
            <option value="">-- All Users --</option>
            {users.map(u => (
              <option key={u.id} value={u.id}>{u.email}</option>
            ))}
          </select>
        </div>
      </div>

      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {[1,2,3].map(i => (
            <div key={i} className="bg-surface-container/50 h-48 rounded-xl border border-outline-variant/10 animate-pulse"></div>
          ))}
        </div>
      ) : projects.length > 0 ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 pb-12">
          {projects.map((p: any) => {
            const pName = typeof p === 'string' ? p : p.name
            return (
              <div key={pName} className="bg-surface-container rounded-xl border border-outline-variant/10 p-6 flex flex-col justify-between hover:border-primary/30 transition-all group shadow-md">
                <div>
                  <div className="flex justify-between items-start mb-4">
                    <span className="material-symbols-outlined text-primary bg-primary/10 p-2 rounded-lg">description</span>
                    <span className="text-[10px] text-outline-variant font-mono uppercase tracking-tighter">Clinical Batch</span>
                  </div>
                  <h3 className="font-bold text-on-surface text-lg mb-1 truncate" title={pName}>{pName}</h3>
                  <p className="text-[10px] text-outline font-medium uppercase tracking-widest mb-4">
                    {typeof p === 'object' ? `Modified: ${new Date(p.last_modified).toLocaleDateString()}` : 'Project Archive'}
                  </p>
                  
                  {typeof p === 'object' && (
                    <div className="grid grid-cols-2 gap-4 mb-6">
                      <div className="flex flex-col">
                        <span className="text-[9px] text-outline uppercase font-bold">Tokens</span>
                        <span className="text-xs font-semibold text-on-surface">{p.total_tokens?.toLocaleString() || 0}</span>
                      </div>
                      <div className="flex flex-col">
                        <span className="text-[9px] text-outline uppercase font-bold">Est. Cost</span>
                        <span className="text-xs font-semibold text-primary">${p.total_cost?.toFixed(4) || '0.0000'}</span>
                      </div>
                    </div>
                  )}
                </div>
                
                <div className="mt-4 pt-6 border-t border-outline-variant/5">
                  <button 
                    onClick={() => onSelectProject(typeof p === 'string' ? { name: p } : p)}
                    className="w-full py-2.5 bg-surface-container-high hover:bg-primary hover:text-on-primary rounded text-xs font-bold uppercase tracking-wider transition-all shadow-md group-hover:shadow-primary/10 active:scale-95"
                  >
                    View Pipeline
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      ) : selectedUid ? (
        <div className="bg-surface-container-low p-12 rounded-xl border border-outline-variant/10 text-center">
          <span className="material-symbols-outlined text-outline text-5xl mb-4">folder_off</span>
          <p className="text-outline font-medium">No projects found for this user.</p>
        </div>
      ) : (
        <div className="bg-surface-container-low p-12 rounded-xl border border-outline-variant/10 text-center">
          <span className="material-symbols-outlined text-outline text-5xl mb-4">search</span>
          <p className="text-outline font-medium">Select a user to audit their project library.</p>
        </div>
      )}
    </div>
  )
}
