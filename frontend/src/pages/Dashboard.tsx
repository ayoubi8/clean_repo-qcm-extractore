import { useEffect, useState } from 'react'
import { useAppStore } from '../store/appStore'
import { fetchProjects, fetchCosts, fetchWeeklyCosts } from '../lib/api'
import { ProjectProgressCard } from '../components/dashboard/ProjectProgressCard'
import { CostOverviewCard } from '../components/dashboard/CostOverviewCard'
import { WeeklyCostChart } from '../components/dashboard/WeeklyCostChart'
import { RecentProjectsList } from '../components/dashboard/RecentProjectsList'
import { QuickActions } from '../components/dashboard/QuickActions'
import type { Project, CostSummary } from '../types'

export function Dashboard() {
  const activeProject = useAppStore(s => s.activeProject)
  
  const [projects, setProjects] = useState<Project[]>([])
  const [costs, setCosts] = useState<CostSummary | null>(null)
  const [weekly, setWeekly] = useState<Record<string, any>>({})
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function load() {
      setLoading(true)
      try {
        const [projs, wk] = await Promise.all([
          fetchProjects(),
          fetchWeeklyCosts(),
        ])
        setProjects(projs)
        setWeekly(wk)

        if (activeProject) {
          try {
            const c = await fetchCosts(activeProject.name)
            setCosts(c)
          } catch (e) {
            console.warn("Could not fetch project costs", e)
            setCosts(null)
          }
        } else {
          setCosts(null)
        }
      } catch (err) {
        console.error("Dashboard data load failed", err)
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [activeProject])

  return (
    <div className="p-8 space-y-8 overflow-y-auto h-full custom-scrollbar animate-in fade-in slide-in-from-bottom-4 duration-700">

      {/* Page header */}
      <div className="border-b border-outline-variant/10 pb-6">
        <h1 className="text-3xl font-black text-on-surface tracking-tighter" id="dashboard-title">
          Dashboard
        </h1>
        <div className="flex items-center gap-2 mt-2">
          <div className={`w-2 h-2 rounded-full ${activeProject ? 'bg-primary animate-pulse' : 'bg-outline/30'}`} />
          <p className="text-sm font-bold text-outline">
            {activeProject ? `Working on ${activeProject.name}` : "No active project selected"}
          </p>
        </div>
      </div>

      {/* Row 1: Active Progress & Quick Actions */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        <div className="xl:col-span-2">
          <ProjectProgressCard 
            project={activeProject} 
            allProjects={projects} 
            loading={loading} 
          />
        </div>
        <QuickActions />
      </div>

      {/* Row 2: Costs & Analytics */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <CostOverviewCard 
          summary={costs} 
          loading={loading} 
          activeProject={activeProject} 
        />
        <WeeklyCostChart 
          weeklyData={weekly} 
          loading={loading} 
        />
      </div>

      {/* Row 3: History */}
      <div className="pb-12">
        <RecentProjectsList 
          projects={projects} 
          loading={loading} 
        />
      </div>

    </div>
  )
}
