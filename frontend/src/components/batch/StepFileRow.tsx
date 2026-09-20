import { useState } from 'react'
import { fetchAuthenticatedBlobUrl, downloadAuthenticatedFile, syncFromSheets, deleteStepOutput, fetchStepFileContent } from '../../lib/api'

/**
 * Auto Run batch detail â€” one output-file row (plan Â§3.3).
 * Exact visual copy of the pipeline OutputViewer `space-y-2` rows minus the
 * run-history variant: same icons, same w-7 h-7 action buttons.
 */

const BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

function getAuthHeaders(): Record<string, string> {
  const token = localStorage.getItem('qcm_token')
  return token ? { 'Authorization': `Bearer ${token}` } : {}
}

export interface StepFileMeta {
  name: string
  size_bytes: number
  created_at?: string
}

function getIcon(name: string) {
  if (name.endsWith('.json')) return 'schema'
  if (name.endsWith('.txt')) return 'description'
  if (name.endsWith('.xlsx')) return 'table_chart'
  return 'draft'
}

interface StepFileRowProps {
  projectName: string
  stepId: string
  file: StepFileMeta
  projectStepId?: string        // stepId the sync/sheets routes work for (2/6)
  onDeleted: (filename: string) => void
  onSynced: () => void
}

const VIEW_ENDPOINT = (project: string, step: string, filename: string) =>
  `${BASE}/projects/${encodeURIComponent(project)}/steps/${encodeURIComponent(step)}/view/${filename.split('/').map(encodeURIComponent).join('/')}`

const DOWNLOAD_ENDPOINT = (project: string, step: string, filename: string) =>
  `${BASE}/projects/${encodeURIComponent(project)}/steps/${encodeURIComponent(step)}/download/${filename.split('/').map(encodeURIComponent).join('/')}`

export function StepFileRow({ projectName, stepId, file, onDeleted, onSynced }: {
  projectName: string
  stepId: string
  file: StepFileMeta
  projectStepId?: string
  onDeleted: (filename: string) => void
  onSynced: () => void
}) {
  const [previewOpen, setPreviewOpen] = useState(false)
  const [previewContent, setPreviewContent] = useState('')
  const [previewLoading, setPreviewLoading] = useState(false)
  const [sheetsLoading, setSheetsLoading] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [syncing, setSyncing] = useState(false)

  const isXlsx = file.name.endsWith('.xlsx')

  const openPreview = async () => {
    if (previewOpen) { setPreviewOpen(false); return }
    setPreviewOpen(true)
    setPreviewLoading(true)
    try {
      const data = await fetchStepFileContent(projectName, stepId, file.name)
      setPreviewContent(data.content || '[No content]')
    } catch {
      setPreviewContent('Failed to load content.')
    } finally {
      setPreviewLoading(false)
    }
  }

  const handleDownload = () => {
    downloadAuthenticatedFile(DOWNLOAD_ENDPOINT(projectName, stepId, file.name), file.name.split('/').pop() ?? file.name)
      .catch(() => alert('Download failed'))
  }

  const openInSheets = async () => {
    setSheetsLoading(true)
    const newTab = window.open('about:blank', '_blank')
    try {
      const res = await fetch(`${BASE}/projects/${encodeURIComponent(projectName)}/steps/${stepId}/open-sheets`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
        body: JSON.stringify({ filename: file.name }),
      })
      if (res.status === 401) {
        let detail = ''
        try { detail = (await res.json()).detail || '' } catch {}
        if (detail === 'NOT_AUTHORIZED') {
          const jwt = localStorage.getItem('qcm_token') || ''
          const oauthUrl = `${BASE}/auth/google?project=${encodeURIComponent(projectName)}&step=${stepId}&filename=${encodeURIComponent(file.name)}&token=${encodeURIComponent(jwt)}`
          if (newTab) newTab.location.href = oauthUrl
          else window.open(oauthUrl, '_blank')
        } else {
          if (newTab) newTab.close()
          alert('Session expired. Please log in again.')
        }
        return
      }
      if (!res.ok) {
        if (newTab) newTab.close()
        let errMsg = 'Upload to Google Sheets failed'
        try { errMsg = (await res.json()).detail || errMsg } catch {}
        alert(errMsg)
        return
      }
      const data = await res.json()
      if (data.url) { if (newTab) newTab.location.href = data.url }
      else { if (newTab) newTab.close(); alert('Upload succeeded but no URL was returned.') }
    } catch (e: any) {
      if (newTab) newTab.close()
      alert(`Google Sheets error: ${e?.message || 'Unknown error'}`)
    } finally {
      setSheetsLoading(false)
    }
  }

  const openInNewTab = async () => {
    if (isXlsx) { openInSheets(); return }
    const newTab = window.open('about:blank', '_blank')
    try {
      const url = (file.name.endsWith('.json') || file.name.endsWith('.pdf'))
        ? VIEW_ENDPOINT(projectName, stepId, file.name)
        : DOWNLOAD_ENDPOINT(projectName, stepId, file.name)
      const blobUrl = await fetchAuthenticatedBlobUrl(url)
      if (newTab) newTab.location.href = blobUrl
      setTimeout(() => URL.revokeObjectURL(blobUrl), 30000)
    } catch {
      if (newTab) newTab.close()
      alert('Could not open file.')
    }
  }

  const handleSync = async () => {
    if (syncing) return
    setSyncing(true)
    try {
      await syncFromSheets(projectName, stepId, false)
      onSynced()
    } catch (e: any) {
      const msg = String(e?.message || e)
      if (msg.startsWith('DELETION_SAFETY') &&
          window.confirm(`${msg.replace('DELETION_SAFETY: ', '')}\n\nApply the deletion anyway?`)) {
        try { await syncFromSheets(projectName, stepId, true); onSynced() } catch (r: any) { alert(r?.message || 'Sync failed') }
      } else {
        alert(msg)
      }
    } finally {
      setSyncing(false)
    }
  }

  const handleDelete = async () => {
    if (!window.confirm(`Delete ${file.name}?`)) return
    setDeleting(true)
    try {
      await deleteStepOutput(projectName, stepId, file.name)
      onDeleted(file.name)
    } catch (e: any) {
      alert(e?.message || 'Delete failed')
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div className="space-y-2">
      <div className={`flex items-center justify-between p-3 rounded-xl border transition-all ${
        previewOpen
          ? 'bg-primary/5 border-primary shadow-[0_0_15px_rgba(76,215,246,0.1)]'
          : 'bg-surface-container-low border-outline-variant/10 hover:border-outline-variant/30'
      }`}>
        <div className="flex items-center gap-3 flex-1 min-w-0">
          <span className="material-symbols-outlined text-[18px] text-outline flex-shrink-0">{getIcon(file.name)}</span>
          <span className="text-xs font-bold truncate text-on-surface-variant">{file.name}</span>
        </div>

        <div className="flex items-center gap-1 flex-shrink-0 ml-2">
          <span className="text-[10px] text-outline tabular-nums mr-2">
            {Math.round(file.size_bytes / 1024)} KB
            {file.created_at && <span className="text-outline/40 ml-2">{file.created_at}</span>}
          </span>

          {!isXlsx && (
            <button
              onClick={() => openPreview()}
              title={previewOpen ? 'Close preview' : 'Preview file'}
              className="w-7 h-7 rounded-lg flex items-center justify-center text-outline hover:text-primary hover:bg-primary/10 transition-colors"
            >
              <span className="material-symbols-outlined text-[16px]">{previewOpen ? 'visibility_off' : 'visibility'}</span>
            </button>
          )}

          <button
            onClick={handleDownload}
            title="Download file"
            className="w-7 h-7 rounded-lg flex items-center justify-center text-outline hover:text-primary hover:bg-primary/10 transition-colors"
          >
            <span className="material-symbols-outlined text-[16px]">download</span>
          </button>

          <button
            onClick={openInNewTab}
            title={isXlsx ? 'Open in Google Sheets' : 'Open in new tab'}
            disabled={isXlsx && sheetsLoading}
            className={`w-7 h-7 rounded-lg flex items-center justify-center transition-colors ${
              isXlsx
                ? 'text-outline hover:text-[#34A853] hover:bg-[#34A853]/10'
                : 'text-outline hover:text-primary hover:bg-primary/10'
            }`}
          >
            {isXlsx && sheetsLoading
              ? <span className="material-symbols-outlined text-[14px] animate-spin">refresh</span>
              : <span className="material-symbols-outlined text-[16px]">open_in_new</span>}
          </button>

          <button
            onClick={handleDelete}
            title="Delete result"
            disabled={deleting}
            className="w-7 h-7 rounded-lg flex items-center justify-center text-outline hover:text-error hover:bg-error/10 transition-colors disabled:opacity-50"
          >
            <span className="material-symbols-outlined text-[16px]">{deleting ? 'hourglass_top' : 'delete'}</span>
          </button>

          {['2', '6'].includes(stepId) && isXlsx && (
            <button
              onClick={handleSync}
              title="Pull the latest edits back from Google Sheets"
              disabled={syncing}
              className="w-7 h-7 rounded-lg flex items-center justify-center text-outline hover:text-primary hover:bg-primary/10 transition-colors disabled:opacity-50"
            >
              {syncing
                ? <span className="material-symbols-outlined text-[14px] animate-spin">sync</span>
                : <span className="material-symbols-outlined text-[16px]">cloud_sync</span>}
            </button>
          )}
        </div>
      </div>

      {previewOpen && !isXlsx && (
        <div className="animate-in slide-in-from-top-2 fade-in duration-300 ml-4">
          <div className="bg-surface-container-lowest rounded-xl border border-outline-variant/20 p-4 font-mono text-[11px] leading-relaxed overflow-x-auto custom-scrollbar max-h-96 whitespace-pre-wrap">
            {previewLoading ? (
              <div className="flex items-center justify-center py-8 text-outline italic">Loading content...</div>
            ) : (
              <code className="text-on-surface-variant">{previewContent}</code>
            )}
          </div>
        </div>
      )}
    </div>
  )
}


