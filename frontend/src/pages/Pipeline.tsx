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
    const projectName   = searchParams.get('project') || ''
    const step          = searchParams.get('step') || ''
    const filename      = searchParams.get('filename') || ''
    const BASE          = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
    const token         = localStorage.getItem('qcm_token') || ''
    const authHeaders: Record<string, string> = token ? { 'Authorization': `Bearer ${token}` } : {}

    if (!projectName) return

    // Clear URL params so a refresh doesn't re-trigger
    setSearchParams({})

    // Fetch full project object (has pdf_path, last_step, etc.) and activate it
    fetch(`${BASE}/projects`, { headers: authHeaders })
      .then(r => r.json())
      .then(data => {
        const found = (data.projects || []).find((p: any) => p.name === projectName)
        if (found) setActiveProject(found)

        // If sheets_pending, trigger upload then auto-redirect THIS tab to the sheet
        // (this tab went through OAuth, it exists solely to complete the flow)
        if (sheetsPending && step && filename) {
          fetch(`${BASE}/projects/${encodeURIComponent(projectName)}/steps/${step}/open-sheets`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...authHeaders },
            body: JSON.stringify({ filename })
          })
            .then(async r => {
              const data = await r.json();
              if (!r.ok) {
                throw new Error(data.detail || 'Upload to Google Sheets failed');
              }
              return data;
            })
            .then(res => {
              if (res.url) {
                // Auto-redirect: this tab goes straight to the Google Sheet
                window.location.href = res.url;
              } else {
                alert('Google Sheets upload succeeded but no URL was returned.');
              }
            })
            .catch(err => {
              console.error('Sheets retry failed:', err);
              alert(`Google Sheets error: ${err.message || 'Unknown error'}`);
            })
        }
      })
      .catch(err => console.error('Pipeline: failed to load projects', err))
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
        <StepList />
        <ConfigPanel />
      </div>

      <TerminalLog />

      {showAutoRun && createPortal(<AutoRunPanel onClose={() => setShowAutoRun(false)} />, document.body)}
    </div>
  )
}
