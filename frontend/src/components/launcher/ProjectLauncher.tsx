import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAppStore } from '../../store/appStore'
import { NewProjectModal } from './NewProjectModal'
import { ResumeProjectModal } from './ResumeProjectModal'
import { Project } from '../../types'

type LauncherTab = 'new' | 'resume'

interface TabButtonProps {
  active: boolean
  onClick: () => void
  label: string
  id: string
}

function TabButton({ active, onClick, label, id }: TabButtonProps) {
  return (
    <button
      id={id}
      onClick={onClick}
      className={`flex-1 py-4 text-sm font-bold transition-all border-b-2 ${
        active 
          ? 'text-primary border-primary bg-primary/5' 
          : 'text-outline border-transparent hover:text-on-surface'
      }`}
    >
      {label}
    </button>
  )
}

export function ProjectLauncher() {
  const [tab, setTab] = useState<LauncherTab>('new')
  const setActiveProject = useAppStore((s) => s.setActiveProject)
  const setLauncherOpen = useAppStore((s) => s.setLauncherOpen)
  const activeProject = useAppStore((s) => s.activeProject)
  const navigate = useNavigate()

  const handleSuccess = (project: Project) => {
    setActiveProject(project)
    setLauncherOpen(false)
    navigate('/pipeline')
  }

  return (
    <div className="fixed inset-0 bg-black/80 backdrop-blur-md z-50 flex items-center justify-center p-4">
      {/* Dialog */}
      <div className="bg-surface-container w-full max-w-[520px] rounded-2xl shadow-2xl border border-outline-variant/20 overflow-hidden animate-in fade-in zoom-in duration-300 relative">
        
        {/* Close Button */}
        <button 
          id="btn-close-launcher"
          onClick={() => {
            setLauncherOpen(false)
            if (!activeProject) navigate('/')
          }}
          className="absolute top-4 right-4 w-8 h-8 rounded-full hover:bg-surface-container-highest flex items-center justify-center text-outline transition-colors z-10"
        >
          <span className="material-symbols-outlined text-[20px]">close</span>
        </button>

        {/* Tab switcher */}
        <div className="flex border-b border-outline-variant/10 pr-12">
          <TabButton 
            id="tab-new-project"
            active={tab === 'new'} 
            onClick={() => setTab('new')} 
            label="New Project" 
          />
          <TabButton 
            id="tab-resume-project"
            active={tab === 'resume'} 
            onClick={() => setTab('resume')} 
            label="Resume Project" 
          />
        </div>

        {/* Body */}
        <div className="p-10">
          {tab === 'new'    && <NewProjectModal onSuccess={handleSuccess} />}
          {tab === 'resume' && <ResumeProjectModal onSuccess={handleSuccess} />}
        </div>
      </div>
    </div>
  )
}
