import { Project } from "../types"
import { useAuthStore } from "../store/authStore"

const BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

function getAuthHeaders(): Record<string, string> {
  const token = localStorage.getItem("qcm_token")
  return token ? { "Authorization": `Bearer ${token}` } : {}
}

// ---------------------------------------------------------------------------
// fetchWithRefresh — wraps fetch() for protected endpoints.
// On a 401, attempts one silent token refresh before giving up.
// ---------------------------------------------------------------------------
async function fetchWithRefresh(input: RequestInfo, init?: RequestInit): Promise<Response> {
  let res = await fetch(input, init)

  if (res.status === 401) {
    const { refreshSession } = useAuthStore.getState()
    const refreshed = await refreshSession()

    if (refreshed) {
      // Retry with the new access token
      const newToken = useAuthStore.getState().token
      const newInit: RequestInit = {
        ...init,
        headers: {
          ...(init?.headers as Record<string, string> ?? {}),
          "Authorization": `Bearer ${newToken}`,
        },
      }
      res = await fetch(input, newInit)
    }
  }

  return res
}

// ---------------------------------------------------------------------------
// Auth-aware file helpers (use instead of plain <a href> or window.open)
// ---------------------------------------------------------------------------

/**
 * Fetch a protected URL with auth headers and return a temporary blob URL.
 * Use this to open PDFs or files in a new tab:
 *   const url = await fetchAuthenticatedBlobUrl(endpoint)
 *   window.open(url, '_blank')
 *   // Caller should URL.revokeObjectURL(url) after a delay if desired
 */
export async function fetchAuthenticatedBlobUrl(url: string): Promise<string> {
  const res = await fetchWithRefresh(url, { headers: getAuthHeaders() })
  if (!res.ok) throw new Error(`Auth fetch failed: ${res.status}`)
  const blob = await res.blob()
  return URL.createObjectURL(blob)
}

/**
 * Fetch a protected URL with auth headers and trigger a browser download.
 */
export async function downloadAuthenticatedFile(url: string, filename: string): Promise<void> {
  const res = await fetchWithRefresh(url, { headers: getAuthHeaders() })
  if (!res.ok) throw new Error(`Download failed: ${res.status}`)
  const blob = await res.blob()
  const blobUrl = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = blobUrl
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  setTimeout(() => URL.revokeObjectURL(blobUrl), 10000)
}

// ---------------------------------------------------------------------------
// Projects
// ---------------------------------------------------------------------------

// GET /projects
export async function fetchProjects(): Promise<Project[]> {
  const res = await fetchWithRefresh(`${BASE}/projects`, {
    headers: { ...getAuthHeaders() }
  })
  if (!res.ok) throw new Error('Failed to fetch projects')
  const data = await res.json()
  return data.projects
}

// DELETE /projects/{name}
export async function deleteProject(name: string): Promise<void> {
  const res = await fetchWithRefresh(`${BASE}/projects/${encodeURIComponent(name)}`, {
    method: 'DELETE',
    headers: { ...getAuthHeaders() }
  })
  if (!res.ok) throw new Error('Failed to delete project')
}

// POST /projects
export async function createProject(payload: {
  name: string
  pdf_path: string
}): Promise<Project> {
  const res = await fetchWithRefresh(`${BASE}/projects`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error('Failed to create project')
  return res.json()
}

// POST /projects/{name}/pdf  (XHR for progress tracking — with 401 retry on token expiry)
export async function uploadProjectPdf(
  projectName: string,
  file: File,
  onProgress?: (pct: number) => void
): Promise<{ pdf_path: string; size_bytes: number }> {

  // Inner helper: performs the actual XHR upload with a given token.
  // Attaches a `status` property to the rejected Error so the caller can
  // detect 401s without string-matching the error message.
  function doUpload(token: string | null): Promise<{ pdf_path: string; size_bytes: number }> {
    return new Promise((resolve, reject) => {
      const formData = new FormData()
      formData.append('file', file)

      const xhr = new XMLHttpRequest()
      xhr.open('POST', `${BASE}/projects/${encodeURIComponent(projectName)}/pdf`)

      if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`)

      if (onProgress) {
        xhr.upload.onprogress = (e) => {
          if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100))
        }
      }

      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(JSON.parse(xhr.responseText))
        } else {
          const err = Object.assign(
            new Error(`Upload failed: ${xhr.status} ${xhr.statusText}`),
            { status: xhr.status }
          )
          reject(err)
        }
      }
      xhr.onerror = () => reject(new Error('Network error during upload'))
      xhr.send(formData)
    })
  }

  // First attempt — use the current stored token
  const token = localStorage.getItem('qcm_token')
  try {
    return await doUpload(token)
  } catch (err: any) {
    // On 401 only: attempt one silent token refresh and retry the upload.
    // Any other status (403, 413, 500…) is re-thrown immediately.
    if (err.status === 401) {
      const { refreshSession } = useAuthStore.getState()
      const refreshed = await refreshSession()
      if (refreshed) {
        const newToken = useAuthStore.getState().token
        return await doUpload(newToken)
      }
    }
    throw err
  }
}

// ---------------------------------------------------------------------------
// Steps
// ---------------------------------------------------------------------------

// POST /projects/{name}/steps/{stepId}/run
export async function runStep(projectName: string, stepId: number, config: object) {
  const res = await fetchWithRefresh(`${BASE}/projects/${encodeURIComponent(projectName)}/steps/${stepId}/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify(config),
  })
  if (!res.ok) throw new Error('Failed to run step')
  return res.json()
}

// GET /projects/{name}/steps/{stepId}/status
export async function getStepStatus(projectName: string, stepId: number): Promise<{ status: any, output_exists: boolean }> {
  const res = await fetchWithRefresh(`${BASE}/projects/${encodeURIComponent(projectName)}/steps/${stepId}/status`, {
    headers: { ...getAuthHeaders() }
  })
  if (!res.ok) throw new Error('Failed to get step status')
  return res.json()
}

// GET /templates
export async function fetchTemplates(): Promise<string[]> {
  const res = await fetchWithRefresh(`${BASE}/templates`, {
    headers: { ...getAuthHeaders() }
  })
  if (!res.ok) throw new Error('Failed to fetch templates')
  return res.json()
}

// WebSocket: ws://localhost:8000/ws/log/{project}/{stepId}  (no auth header over WS)
export function connectLogStream(
  projectName: string,
  stepId: number,
  onLine: (l: any) => void,
  onClose: () => void
): WebSocket {
  const wsBase = BASE.replace('http', 'ws')
  const ws = new WebSocket(`${wsBase}/ws/log/${encodeURIComponent(projectName)}/${stepId}`)

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data)
      onLine(data)
    } catch (e) {
      console.error('Failed to parse WS message', e)
    }
  }

  ws.onclose = onClose
  return ws
}

// ---------------------------------------------------------------------------
// Config / Env
// ---------------------------------------------------------------------------

// GET /config/batch
export async function fetchBatchConfig(): Promise<any> {
  const res = await fetchWithRefresh(`${BASE}/config/batch`, {
    headers: { ...getAuthHeaders() }
  })
  if (!res.ok) throw new Error('Failed to load batch_config.yaml')
  return res.json()
}

// POST /projects/{name}/autorun
export async function startAutoRun(
  projectName: string,
  payload: any
): Promise<{ job_id: string }> {
  const res = await fetchWithRefresh(`${BASE}/projects/${encodeURIComponent(projectName)}/autorun`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error('Failed to start auto run')
  return res.json()
}

// GET /projects/{name}/costs
export async function fetchCosts(projectName: string): Promise<any> {
  const res = await fetchWithRefresh(`${BASE}/projects/${encodeURIComponent(projectName)}/costs`, {
    headers: { ...getAuthHeaders() }
  })
  if (!res.ok) throw new Error('Failed to fetch costs')
  return res.json()
}

// POST /projects/{name}/costs/save
export async function saveCosts(projectName: string): Promise<{ saved_to: string }> {
  const res = await fetchWithRefresh(`${BASE}/projects/${encodeURIComponent(projectName)}/costs/save`, {
    method: 'POST',
    headers: { ...getAuthHeaders() }
  })
  if (!res.ok) throw new Error('Failed to save costs')
  return res.json()
}

// POST /projects/{name}/step8/export-existing
export async function exportExisting(projectName: string, body?: object): Promise<any> {
  const res = await fetchWithRefresh(`${BASE}/projects/${encodeURIComponent(projectName)}/step8/export-existing`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify(body ?? {}),
  })
  if (!res.ok) throw new Error('Failed to export existing data')
  return res.json()
}

// GET /env
export async function fetchEnvKeys(): Promise<any> {
  const res = await fetchWithRefresh(`${BASE}/env`, {
    headers: { ...getAuthHeaders() }
  })
  if (!res.ok) throw new Error('Failed to fetch environment keys')
  return res.json()
}

export async function fetchEnvKeysRaw(): Promise<any> {
  const res = await fetchWithRefresh(`${BASE}/env/raw`, {
    headers: { ...getAuthHeaders() }
  })
  if (!res.ok) throw new Error('Failed to fetch raw environment keys')
  return res.json()
}

export async function fetchAvailableModels(): Promise<Record<string, string[]>> {
  const res = await fetchWithRefresh(`${BASE}/admin/available-models`, {
    headers: { ...getAuthHeaders() }
  })
  if (!res.ok) return {}
  return res.json()
}

// POST /env
export async function saveEnvKeys(keys: any): Promise<{ updated: string[] }> {
  const res = await fetchWithRefresh(`${BASE}/env`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify(keys),
  })
  if (!res.ok) throw new Error('Failed to save environment keys')
  return res.json()
}

// POST /config/batch
export async function saveBatchConfig(yamlContent: string): Promise<{ saved: boolean }> {
  const res = await fetchWithRefresh(`${BASE}/config/batch`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify({ yaml_content: yamlContent }),
  })
  if (!res.ok) throw new Error('Failed to save batch config')
  return res.json()
}

// GET /costs/weekly
export async function fetchWeeklyCosts(): Promise<Record<string, any>> {
  const res = await fetchWithRefresh(`${BASE}/costs/weekly`, {
    headers: { ...getAuthHeaders() }
  })
  if (!res.ok) return {}
  return res.json()
}

// GET /env/step-models
export async function fetchStepModels(): Promise<any> {
  const res = await fetchWithRefresh(`${BASE}/env/step-models`, {
    headers: { ...getAuthHeaders() }
  })
  if (!res.ok) throw new Error('Failed to fetch step models')
  return res.json()
}

// GET /projects/{name}/steps/{step_id}/output
export async function fetchStepOutput(projectName: string, stepId: string): Promise<{ files: any[] }> {
  const res = await fetchWithRefresh(`${BASE}/projects/${encodeURIComponent(projectName)}/steps/${stepId}/output`, {
    headers: { ...getAuthHeaders() }
  })
  if (!res.ok) throw new Error('Failed to fetch step output list')
  return res.json()
}

// GET /projects/{name}/steps/{step_id}/output/{filename}
export async function fetchStepFileContent(projectName: string, stepId: string, filename: string): Promise<any> {
  const encodedFilename = filename.split('/').map(encodeURIComponent).join('/')
  const res = await fetchWithRefresh(
    `${BASE}/projects/${encodeURIComponent(projectName)}/steps/${stepId}/output/${encodedFilename}`,
    { headers: { ...getAuthHeaders() } }
  )
  if (!res.ok) throw new Error('Failed to fetch file content')
  return res.json()
}

export async function fetchStepHistory(projectName: string): Promise<any> {
  const res = await fetchWithRefresh(`${BASE}/projects/${encodeURIComponent(projectName)}/step-history`, {
    headers: { ...getAuthHeaders() }
  })
  if (!res.ok) return {}
  return res.json()
}

// ---------------------------------------------------------------------------
// Auth API  — plain fetch() (no auth needed, no refresh loop)
// ---------------------------------------------------------------------------

export async function loginUser(email: string, password: string): Promise<any> {
  const res = await fetch(`${BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || 'Login failed')
  }
  return res.json()
}

export async function registerUser(email: string, password: string): Promise<any> {
  const res = await fetch(`${BASE}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || 'Registration failed')
  }
  return res.json()
}

// ---------------------------------------------------------------------------
// Protected Auth / Admin endpoints
// ---------------------------------------------------------------------------

export async function fetchCurrentUser(): Promise<any> {
  const res = await fetchWithRefresh(`${BASE}/auth/me`, {
    headers: { ...getAuthHeaders() }
  })
  if (!res.ok) throw new Error('Failed to fetch user profile')
  return res.json()
}

export async function fetchAdminUsers(): Promise<any[]> {
  const res = await fetchWithRefresh(`${BASE}/admin/users`, {
    headers: { ...getAuthHeaders() }
  })
  if (!res.ok) throw new Error('Failed to fetch users')
  return res.json()
}

export async function approveUser(uid: string): Promise<any> {
  const res = await fetchWithRefresh(`${BASE}/admin/users/${uid}/approve`, {
    method: 'PATCH',
    headers: { ...getAuthHeaders() }
  })
  if (!res.ok) throw new Error('Failed to approve user')
  return res.json()
}

export async function rejectUser(uid: string): Promise<any> {
  const res = await fetchWithRefresh(`${BASE}/admin/users/${uid}/reject`, {
    method: 'PATCH',
    headers: { ...getAuthHeaders() }
  })
  if (!res.ok) throw new Error('Failed to reject user')
  return res.json()
}

export async function setUserApiKey(uid: string, api_key: string): Promise<any> {
  const res = await fetchWithRefresh(`${BASE}/admin/users/${uid}/api-key`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify({ api_key }),
  })
  if (!res.ok) throw new Error('Failed to set API key')
  return res.json()
}

export async function setUserModels(uid: string, allowed_models: Record<string, string[]>): Promise<any> {
  const res = await fetchWithRefresh(`${BASE}/admin/users/${uid}/models`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify({ allowed_models }),
  })
  if (!res.ok) throw new Error('Failed to set allowed models')
  return res.json()
}

export async function fetchAdminStats(): Promise<any> {
  const res = await fetchWithRefresh(`${BASE}/admin/stats`, {
    headers: { ...getAuthHeaders() }
  })
  if (!res.ok) throw new Error('Failed to fetch admin stats')
  return res.json()
}

export async function fetchAdminUserProjects(uid: string): Promise<any> {
  const res = await fetchWithRefresh(`${BASE}/admin/users/${uid}/projects`, {
    headers: { ...getAuthHeaders() }
  })
  if (!res.ok) throw new Error('Failed to fetch user projects')
  return res.json()
}

// ---------------------------------------------------------------------------
// Reference Databases
// ---------------------------------------------------------------------------

// GET /ref-db
export async function fetchRefDbs(): Promise<any[]> {
  const res = await fetchWithRefresh(`${BASE}/ref-db`, {
    headers: { ...getAuthHeaders() }
  })
  if (!res.ok) throw new Error('Failed to fetch reference databases')
  const data = await res.json()
  return data.files
}

// POST /ref-db/upload
export async function uploadRefDb(file: File): Promise<any> {
  const formData = new FormData()
  formData.append('file', file)
  const res = await fetchWithRefresh(`${BASE}/ref-db/upload`, {
    method: 'POST',
    headers: { ...getAuthHeaders() },
    body: formData
  })
  if (!res.ok) {
    const errData = await res.json().catch(() => ({}))
    throw new Error(errData.detail || 'Failed to upload reference database')
  }
  return res.json()
}

// DELETE /ref-db/{id}
export async function deleteRefDb(id: string): Promise<void> {
  const res = await fetchWithRefresh(`${BASE}/ref-db/${id}`, {
    method: 'DELETE',
    headers: { ...getAuthHeaders() }
  })
  if (!res.ok) throw new Error('Failed to delete reference database')
}
