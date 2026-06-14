import { useState, useEffect } from 'react';
import { fetchStepOutput, fetchAuthenticatedBlobUrl, downloadAuthenticatedFile } from '../../lib/api';

const BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

function getAuthHeaders(): Record<string, string> {
  const token = localStorage.getItem('qcm_token')
  return token ? { 'Authorization': `Bearer ${token}` } : {}
}

interface OutputViewerProps {
  projectName: string;
  stepId: string;
}

export function OutputViewer({ projectName, stepId }: OutputViewerProps) {
  const [files, setFiles] = useState<any[]>([]);
  const [loadingFiles, setLoadingFiles] = useState(true);
  const [previewFile, setPreviewFile] = useState<string | null>(null);
  const [previewContent, setPreviewContent] = useState<string>('');
  const [previewLoading, setPreviewLoading] = useState(false);
  const [sheetsLoading, setSheetsLoading] = useState<string | null>(null);
  
  // History state
  const [showHistory, setShowHistory] = useState(false);
  const [historyRuns, setHistoryRuns] = useState<any[]>([]);
  const [selectedRun, setSelectedRun] = useState<string | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);

  useEffect(() => {
    async function loadAll() {
      // 1. Load current step files
      setLoadingFiles(true);
      try {
        const data = await fetchStepOutput(projectName, stepId);
        setFiles(data.files);
      } catch (err) {
        console.error(err);
      } finally {
        setLoadingFiles(false);
      }

      // 2. Always load history metadata on mount — lightweight check
      try {
        const res = await fetch(`${BASE}/projects/${encodeURIComponent(projectName)}/steps/${stepId}/history`, {
          headers: getAuthHeaders()
        });
        const hdata = await res.json();
        const runs = hdata.runs || [];
        setHistoryRuns(runs);
        if (runs.length > 0) setSelectedRun(runs[0].run_id);
      } catch (err) {
        console.error('History load error:', err);
      }
    }

    // Reset view when step changes
    setShowHistory(false);
    setSelectedRun(null);
    setHistoryRuns([]);
    loadAll();
  }, [projectName, stepId]);

  const loadHistory = async () => {
    // Called on manual refresh via the button toggle
    setHistoryLoading(true);
    try {
      const res = await fetch(`${BASE}/projects/${encodeURIComponent(projectName)}/steps/${stepId}/history`, {
        headers: getAuthHeaders()
      });
      const data = await res.json();
      const runs = data.runs || [];
      setHistoryRuns(runs);
      if (runs.length > 0 && !selectedRun) setSelectedRun(runs[0].run_id);
    } catch (err) {
      console.error(err);
    } finally {
      setHistoryLoading(false);
    }
  };

  const openPreview = async (file: any) => {
    if (file.name === previewFile) {
      setPreviewFile(null);
      setPreviewContent('');
      return;
    }
    setPreviewFile(file.name);
    setPreviewLoading(true);
    try {
      const encodedName = file.name.split('/').map(encodeURIComponent).join('/');
      const res = await fetch(`${BASE}/projects/${encodeURIComponent(projectName)}/steps/${stepId}/output/${encodedName}`, {
        headers: getAuthHeaders()
      });
      const data = await res.json();
      setPreviewContent(data.content || '[No content]');
    } catch {
      setPreviewContent('Failed to load content.');
    } finally {
      setPreviewLoading(false);
    }
  };

  const getDownloadUrl = (filename: string) => {
    const encodedName = filename.split('/').map(encodeURIComponent).join('/');
    return `${BASE}/projects/${encodeURIComponent(projectName)}/steps/${stepId}/download/${encodedName}`;
  };

  const getViewUrl = (filename: string) => {
    const encodedName = filename.split('/').map(encodeURIComponent).join('/');
    return `${BASE}/projects/${encodeURIComponent(projectName)}/steps/${stepId}/view/${encodedName}`;
  };

  const getHistoryDownloadUrl = (runId: string, filename: string) => {
    const encodedName = filename.split('/').map(encodeURIComponent).join('/');
    return `${BASE}/projects/${encodeURIComponent(projectName)}/steps/${stepId}/history/${runId}/${encodedName}`;
  };

  const getHistoryViewUrl = (runId: string, filename: string) => {
    const encodedName = filename.split('/').map(encodeURIComponent).join('/');
    return `${BASE}/projects/${encodeURIComponent(projectName)}/steps/${stepId}/history/${runId}/${encodedName}`;
  };

  const openInSheets = async (file: any) => {
    setSheetsLoading(file.name);
    // Pre-open window immediately to bypass popup blocker
    const newTab = window.open('about:blank', '_blank');
    try {
      const res = await fetch(`${BASE}/projects/${encodeURIComponent(projectName)}/steps/${stepId}/open-sheets`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
        body: JSON.stringify({ filename: file.name })
      });

      if (res.status === 401) {
        // Read the body to distinguish JWT-expired vs Google-creds-missing
        let detail = '';
        try { detail = (await res.json()).detail || ''; } catch {}

        if (detail === 'NOT_AUTHORIZED') {
          // No Google OAuth token — redirect the pre-opened tab to Google consent
          // so the main app window stays open and unchanged
          const encodedFile = encodeURIComponent(file.name);
          const jwt = localStorage.getItem('qcm_token') || '';
          const oauthUrl = `${BASE}/auth/google?project=${encodeURIComponent(projectName)}&step=${stepId}&filename=${encodedFile}&token=${encodeURIComponent(jwt)}`;
          if (newTab) {
            newTab.location.href = oauthUrl;
          } else {
            // Popup was blocked — fall back to opening a new window
            window.open(oauthUrl, '_blank');
          }
        } else {
          if (newTab) newTab.close();
          // App JWT expired — ask user to re-login
          alert('Session expired. Please log in again.');
        }
        return;
      }

      if (!res.ok) {
        if (newTab) newTab.close();
        let errMsg = 'Upload to Google Sheets failed';
        try { errMsg = (await res.json()).detail || errMsg; } catch {}
        alert(errMsg);
        return;
      }

      const data = await res.json();
      if (data.url) {
        if (newTab) {
          newTab.location.href = data.url;
        }
      } else {
        if (newTab) newTab.close();
        alert('Google Sheets upload succeeded but no URL was returned.');
      }
    } catch (e: any) {
      if (newTab) newTab.close();
      console.error('Google Sheets error:', e);
      alert(`Google Sheets error: ${e.message || 'Unknown error'}`);
    } finally {
      setSheetsLoading(null);
    }
  };

  const getIcon = (name: string) => {
    if (name.endsWith('.json')) return 'schema';
    if (name.endsWith('.txt')) return 'description';
    if (name.endsWith('.xlsx')) return 'table_chart';
    return 'draft';
  };

  if (loadingFiles) return (
    <div className="p-4 flex items-center justify-center text-outline animate-pulse text-[10px] uppercase font-bold tracking-widest">
      Scanning Output...
    </div>
  );

  // Hide completely only when there's nothing at all to show
  if (files.length === 0 && historyRuns.length === 0) return null;

  return (
    <div className="mt-8 space-y-4 border-t border-outline-variant/10 pt-8 animate-in fade-in duration-500">
      <div className="flex items-center justify-between px-1">
        <div className="flex items-center gap-3">
          <label className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">Step Output Files</label>
          <button 
            onClick={() => { setShowHistory(!showHistory); if (!showHistory) loadHistory(); }}
            className={`flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[9px] font-bold tracking-wider transition-all border ${
              showHistory 
                ? 'bg-amber-500/10 border-amber-500/20 text-amber-500' 
                : 'bg-outline-variant/5 border-outline-variant/10 text-outline hover:text-primary hover:border-primary/20'
            }`}
          >
            <span className="material-symbols-outlined text-[14px] leading-none">
              {showHistory ? 'history' : 'history_toggle_off'}
            </span>
            {showHistory ? 'RUN HISTORY' : 'VIEW HISTORY'}
          </button>
        </div>
        <span className="text-[10px] text-outline-variant font-bold">
          {showHistory ? (historyRuns.find(r => r.run_id === selectedRun)?.files.length || 0) : files.length} files
        </span>
      </div>

      {showHistory && (
        <div className="px-1 flex flex-col gap-2">
          {historyLoading ? (
            <div className="text-[10px] text-outline animate-pulse font-bold tracking-widest">LOADING ARCHIVE...</div>
          ) : historyRuns.length === 0 ? (
            <div className="text-[10px] text-outline-variant italic">No archived runs found.</div>
          ) : (
            <div className="flex items-center gap-2">
              <span className="text-[10px] text-outline font-bold">Select Run:</span>
              <select 
                value={selectedRun || ''} 
                onChange={(e) => setSelectedRun(e.target.value)}
                className="bg-surface-container-high border border-outline-variant/20 rounded-lg px-2 py-1 text-[11px] font-mono text-on-surface-variant focus:outline-none focus:border-primary/50"
              >
                {historyRuns.map(run => (
                  <option key={run.run_id} value={run.run_id}>
                    {run.label || run.run_id} ({run.files.length} files)
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>
      )}

      <div className="space-y-2 max-h-80 overflow-y-auto custom-scrollbar pr-2">
        {(showHistory ? (historyRuns.find(r => r.run_id === selectedRun)?.files || []) : files).map((file) => (
          <div key={file.name} className="space-y-2">
            <div className={`flex items-center justify-between p-3 rounded-xl border transition-all ${
              previewFile === file.name
                ? 'bg-primary/5 border-primary shadow-[0_0_15px_rgba(76,215,246,0.1)]'
                : 'bg-surface-container-low border-outline-variant/10 hover:border-outline-variant/30'
            }`}>
              <div className="flex items-center gap-3 flex-1 min-w-0">
                <span className="material-symbols-outlined text-[18px] text-outline flex-shrink-0">
                  {getIcon(file.name)}
                </span>
                <span className="text-xs font-bold truncate text-on-surface-variant">
                  {file.name}
                </span>
              </div>

              <div className="flex items-center gap-1 flex-shrink-0 ml-2">
                <span className="text-[10px] text-outline tabular-nums mr-2">
                  {Math.round(file.size_bytes / 1024)} KB
                  {file.created_at && <span className="text-outline/40 ml-2">{file.created_at}</span>}
                </span>



                {!file.name.endsWith('.xlsx') && (
                  <button
                    onClick={() => openPreview(file)}
                    title={previewFile === file.name ? 'Close preview' : 'Preview file'}
                    className="w-7 h-7 rounded-lg flex items-center justify-center text-outline hover:text-primary hover:bg-primary/10 transition-colors"
                  >
                    <span className="material-symbols-outlined text-[16px]">
                      {previewFile === file.name ? 'visibility_off' : 'visibility'}
                    </span>
                  </button>
                )}

                <button
                  onClick={() => {
                    const url = showHistory
                      ? getHistoryDownloadUrl(selectedRun!, file.name)
                      : getDownloadUrl(file.name);
                    downloadAuthenticatedFile(url, file.name.split('/').pop() ?? file.name)
                      .catch(() => alert('Download failed'));
                  }}
                  title="Download file"
                  className="w-7 h-7 rounded-lg flex items-center justify-center text-outline hover:text-primary hover:bg-primary/10 transition-colors"
                >
                  <span className="material-symbols-outlined text-[16px]">download</span>
                </button>

                <button
                  onClick={async () => {
                    if (file.name.endsWith('.xlsx')) {
                      openInSheets(file);
                      return;
                    }
                    // Pre-open window immediately to bypass popup blocker
                    const newTab = window.open('about:blank', '_blank');
                    const url = showHistory
                      ? getHistoryViewUrl(selectedRun!, file.name)
                      : (file.name.endsWith('.json') || file.name.endsWith('.pdf')
                          ? getViewUrl(file.name)
                          : getDownloadUrl(file.name));
                    try {
                      const blobUrl = await fetchAuthenticatedBlobUrl(url);
                      if (newTab) {
                        newTab.location.href = blobUrl;
                      }
                      setTimeout(() => URL.revokeObjectURL(blobUrl), 30000);
                    } catch {
                      if (newTab) newTab.close();
                      alert('Could not open file.');
                    }
                  }}
                  title={file.name.endsWith('.xlsx') ? 'Open in Google Sheets' : 'Open in new tab'}
                  disabled={file.name.endsWith('.xlsx') && sheetsLoading === file.name}
                  className={`w-7 h-7 rounded-lg flex items-center justify-center transition-colors ${
                    file.name.endsWith('.xlsx')
                      ? 'text-outline hover:text-[#34A853] hover:bg-[#34A853]/10'
                      : 'text-outline hover:text-primary hover:bg-primary/10'
                  }`}
                >
                  {file.name.endsWith('.xlsx') && sheetsLoading === file.name
                    ? <span className="material-symbols-outlined text-[14px] animate-spin">refresh</span>
                    : <span className="material-symbols-outlined text-[16px]">open_in_new</span>
                  }
                </button>
              </div>
            </div>

            {previewFile === file.name && !file.name.endsWith('.xlsx') && (
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
        ))}
      </div>
    </div>
  );
}
