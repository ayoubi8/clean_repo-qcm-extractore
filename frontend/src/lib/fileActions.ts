import {
  BASE_URL, deleteStepOutput, disconnectGoogle, downloadAuthenticatedFile, fetchAuthenticatedBlobUrl,
  openInGoogleSheets, syncFromSheets,
} from './api'
import { fileUrl, forgetFile, refreshResults } from './results'
import { reloadAfterSync } from '../store/outputsCache'
import { toast } from '../components/ui/Toaster'

/**
 * File actions shared by the pipeline, the Results page and the batch view
 * (results plan §11.1-3: one implementation, so a fix lands everywhere).
 */

/** Steps whose workbook can be edited in Google Sheets and synced back. */
export const SHEETS_SYNC_STEPS = ['2', '6']

// Set when a workbook is opened in Sheets: returning to this tab then pulls
// the edits back automatically (CLOUD_SYNC). Keyed project|step.
const openedSheets = new Set<string>()

export function hasOpenedSheet(project: string, step: string): boolean {
  return openedSheets.has(`${project}|${step}`)
}

export async function openWorkbookInSheets(project: string, step: string, filename: string): Promise<void> {
  if (SHEETS_SYNC_STEPS.includes(step)) openedSheets.add(`${project}|${step}`)
  // Open the tab now (inside the click) so the popup blocker allows it.
  const tab = window.open('about:blank', '_blank')
  try {
    const res = await openInGoogleSheets(project, step, filename)
    if (res.url) {
      if (tab) tab.location.href = res.url
      else window.open(res.url, '_blank')
    } else {
      tab?.close()
      toast.error('Google Sheets upload succeeded but no URL was returned.')
    }
  } catch (e: any) {
    const msg = String(e?.message || '')
    if (msg === 'NOT_AUTHORIZED') {
      // No Google token yet: send the new tab through Google sign-in; it
      // comes back to /projects/:name/steps/:id?sheets_pending=1 and finishes.
      const url = googleAuthUrl(project, step, filename)
      if (tab) tab.location.href = url
      else window.open(url, '_blank')
      return
    }
    tab?.close()
    showSheetsError(msg, project, step, filename)
  }
}

function googleAuthUrl(project: string, step: string, filename: string): string {
  const jwt = localStorage.getItem('qcm_token') || ''
  return `${BASE_URL}/auth/google?project=${encodeURIComponent(project)}&step=${encodeURIComponent(step)}`
    + `&filename=${encodeURIComponent(filename)}&token=${encodeURIComponent(jwt)}`
}

/** Sheets failure toast. A full Drive gets its way out instead of Google's raw error. */
export function showSheetsError(message: string | undefined, project: string, step: string, filename: string): void {
  if (message !== 'DRIVE_QUOTA_EXCEEDED') {
    toast.error(`Google Sheets: ${message || 'upload failed'}`)
    return
  }
  toast.error('Your Google Drive is full, so this workbook could not be opened in Sheets.', 20000, [
    { label: 'Download xlsx', onClick: () => { void downloadFile(project, step, filename) } },
    { label: 'Open Drive storage', onClick: () => { window.open('https://drive.google.com/drive/quota', '_blank', 'noopener') } },
    {
      label: 'Use another Google account',
      onClick: () => {
        // Open inside the click so the popup blocker allows it.
        const tab = window.open('about:blank', '_blank')
        disconnectGoogle()
          .then(() => {
            const url = googleAuthUrl(project, step, filename)
            if (tab) tab.location.href = url
            else window.open(url, '_blank')
          })
          .catch((e: any) => {
            tab?.close()
            toast.error(e?.message || 'Could not disconnect the Google account.')
          })
      },
    },
  ])
}

export async function openFileInTab(project: string, step: string, filename: string, runId?: string): Promise<void> {
  const tab = window.open('about:blank', '_blank')
  try {
    const viewable = filename.endsWith('.json') || filename.endsWith('.pdf')
    const blobUrl = await fetchAuthenticatedBlobUrl(fileUrl(project, step, filename, viewable ? 'view' : 'download', runId))
    if (tab) tab.location.href = blobUrl
    setTimeout(() => URL.revokeObjectURL(blobUrl), 30000)
  } catch {
    tab?.close()
    toast.error('Could not open the file.')
  }
}

export async function downloadFile(project: string, step: string, filename: string, runId?: string): Promise<void> {
  try {
    await downloadAuthenticatedFile(fileUrl(project, step, filename, 'download', runId), filename.split('/').pop() ?? filename)
  } catch {
    toast.error('Download failed.')
  }
}

export async function deleteFile(project: string, step: string, filename: string): Promise<boolean> {
  if (!window.confirm(`Delete ${filename}?`)) return false
  try {
    await deleteStepOutput(project, step, filename)
    forgetFile(project, step, filename)
    toast.success(`Deleted ${filename.split('/').pop()}`)
    return true
  } catch (e: any) {
    toast.error(e?.message || 'Delete failed')
    return false
  }
}

let syncing = false

/**
 * Pull Google Sheets edits back into the step (Steps 2 / 6). `quiet` = the
 * automatic sync on tab return: errors are logged, not shown.
 */
export async function syncSheets(project: string, step: string, quiet = false): Promise<boolean> {
  if (syncing) return false
  syncing = true
  if (!quiet) toast.info('Syncing from Google Sheets…', 2500)
  const run = async (force: boolean) => {
    const r = await syncFromSheets(project, step, force)
    const parts: string[] = []
    if (r.newly_corrected > 0) parts.push(`${r.newly_corrected} change${r.newly_corrected === 1 ? '' : 's'}`)
    if (r.deleted_count > 0) parts.push(`${r.deleted_count} deleted row${r.deleted_count === 1 ? '' : 's'}`)
    const other = step === '6' ? 'Step 2' : 'Step 6'
    const prop = r.propagated > 0 ? ` (${r.propagated} propagated to ${other})` : ''
    toast.success(parts.length ? `Synced ${parts.join(', ')} from Google Sheets${prop}` : `Sheet is up to date (${r.total} rows)`)
    await Promise.allSettled([reloadAfterSync(project, step), refreshResults(project)])
  }
  try {
    await run(false)
    return true
  } catch (e: any) {
    const msg = String(e?.message || e)
    if (msg.startsWith('DELETION_SAFETY') && !quiet &&
        window.confirm(`${msg.replace('DELETION_SAFETY: ', '')}\n\nApply the deletion anyway?`)) {
      try { await run(true); return true } catch (r: any) { toast.error(r?.message || 'Sync from Sheets failed') }
    } else if (quiet) {
      console.warn('Auto-sync from Sheets failed:', msg)
    } else {
      toast.error(msg)
    }
    return false
  } finally {
    syncing = false
  }
}
