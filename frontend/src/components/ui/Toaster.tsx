import { create } from 'zustand'

/**
 * One app-wide toaster (results plan §11.3 — replaces window.alert and the
 * per-viewer toasts). `toast.success / error / info` work from anywhere,
 * inside or outside React.
 */

type Kind = 'success' | 'error' | 'info'
export interface ToastAction { label: string; onClick: () => void }
interface Toast { id: number; kind: Kind; text: string; actions?: ToastAction[] }

interface ToastStore {
  toasts: Toast[]
  push: (kind: Kind, text: string, ms?: number, actions?: ToastAction[]) => void
  dismiss: (id: number) => void
}

let nextId = 1

const useToastStore = create<ToastStore>((set, get) => ({
  toasts: [],
  push: (kind, text, ms, actions) => {
    const id = nextId++
    set({ toasts: [...get().toasts.slice(-3), { id, kind, text, actions }] })
    setTimeout(() => get().dismiss(id), ms ?? (kind === 'error' ? 7000 : 3500))
  },
  dismiss: (id) => set({ toasts: get().toasts.filter((t) => t.id !== id) }),
}))

export const toast = {
  success: (text: string, ms?: number) => useToastStore.getState().push('success', text, ms),
  error: (text: string, ms?: number, actions?: ToastAction[]) => useToastStore.getState().push('error', text, ms, actions),
  info: (text: string, ms?: number) => useToastStore.getState().push('info', text, ms),
}

/** Hook form (stable identity) for components. */
export function useToast() {
  return toast
}

const STYLE: Record<Kind, { box: string; icon: string }> = {
  success: { box: 'bg-primary/10 border-primary/30 text-primary', icon: 'check_circle' },
  error: { box: 'bg-error-container/80 border-error/40 text-on-error-container', icon: 'error' },
  info: { box: 'bg-surface-container-high/95 border-outline-variant/30 text-on-surface-variant', icon: 'info' },
}

export function Toaster() {
  const toasts = useToastStore((s) => s.toasts)
  const dismiss = useToastStore((s) => s.dismiss)
  if (toasts.length === 0) return null
  return (
    <div className="fixed bottom-6 right-6 z-[100] flex flex-col gap-2 max-w-sm" role="status" aria-live="polite">
      {toasts.map((t) => (
        <div
          key={t.id}
          className={`flex items-start gap-2 px-4 py-3 rounded-xl border shadow-lg backdrop-blur text-xs font-bold qe-pop ${STYLE[t.kind].box}`}
        >
          <span className="material-symbols-outlined text-[16px] shrink-0">{STYLE[t.kind].icon}</span>
          <div className="flex-1 min-w-0">
            <span className="break-words">{t.text}</span>
            {t.actions && t.actions.length > 0 && (
              <div className="flex flex-wrap gap-x-3 gap-y-1 mt-2">
                {t.actions.map((a) => (
                  <button
                    key={a.label}
                    onClick={() => { dismiss(t.id); a.onClick() }}
                    className="underline underline-offset-2 hover:opacity-80"
                  >
                    {a.label}
                  </button>
                ))}
              </div>
            )}
          </div>
          <button onClick={() => dismiss(t.id)} aria-label="Dismiss" className="opacity-60 hover:opacity-100">
            <span className="material-symbols-outlined text-[14px]">close</span>
          </button>
        </div>
      ))}
    </div>
  )
}
