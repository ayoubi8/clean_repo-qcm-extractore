import { useState } from 'react'
import { StepList } from '../components/pipeline/StepList'
import { ConfigPanel } from '../components/pipeline/ConfigPanel'
import { TerminalLog } from '../components/pipeline/TerminalLog'
import { AutoRunPanel } from '../components/autorun/AutoRunPanel'
import { useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useAppStore } from '../store/appStore'

import { createPortal } from 'react-dom'

export function Pipeline() {
  const [showAutoRun, setShowAutoRun] = useState(false)
  const [searchParams, setSearchParams] = useSearchParams()
  const setActiveProject = useAppStore((s) => s.setActiveProject)

  useEffect(() => {
    const sheetsPending = searchParams.get('sheets_pending') === '1'
    const project      = searchParams.get('project') || ''
    const step         = searchParams.get('step') || ''
    const filename     = searchParams.get('filename') || ''
    const BASE         = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
    const token        = localStorage.getItem('qcm_token') || ''

    // If project is in URL, activate it in the store so the sidebar shows it
    if (project && setActiveProject) {
      setActiveProject(project)
    }

    if (sheetsPending && project && step && filename) {
      // Clear the URL params so a refresh doesn't re-trigger
      setSearchParams({})
      // Auto-retry the upload now that we have a Google token
      fetch(`${BASE}/projects/${encodeURIComponent(project)}/steps/${step}/open-sheets`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { 'Authorization': `Bearer ${token}` } : {})
        },
        body: JSON.stringify({ filename })
      }).then(r => r.json()).then(data => {
        if (data.url) window.open(data.url, '_blank')
        else console.error('Sheets upload succeeded but no URL returned:', data)
      }).catch(err => console.error('Auto-retry sheets upload failed:', err))
    }
  }, [searchParams])


  return (
    <div className="flex flex-col h-[calc(100vh-64px)] overflow-hidden relative">
      {/* Header with Auto Run trigger */}
      <div className="h-14 bg-surface-container-low border-b border-outline-variant/10 flex items-center justify-end px-6 shrink-0">
        <button
          id="btn-open-autorun"
          onClick={() => setShowAutoRun(true)}
          className="flex items-center gap-2 px-4 py-1.5 bg-secondary-container text-on-secondary-container rounded-lg text-xs font-black uppercase tracking-widest hover:opacity-90 transition-opacity shadow-sm"
        >
          <span className="material-symbols-outlined text-[18px]">play_circle</span>
          Auto Run
        </button>
      </div>

      {/* Main two-column area */}
      <div className="flex flex-1 overflow-hidden">
        {/* LEFT — Step list */}
        <StepList />

        {/* RIGHT — Config panel */}
        <ConfigPanel />
      </div>

      {/* BOTTOM — Terminal log */}
      <TerminalLog />

      {/* Slide-over Drawer */}
      {showAutoRun && createPortal(<AutoRunPanel onClose={() => setShowAutoRun(false)} />, document.body)}
    </div>
  )
}
