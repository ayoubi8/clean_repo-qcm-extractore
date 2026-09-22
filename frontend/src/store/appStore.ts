import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { AppState, Project } from '../types'

export const useAppStore = create<AppState>()(
  persist(
    (set, get) => ({
      activeProject: null,
      pipelineStatus: 'idle',
      isLauncherOpen: true,
      lastActiveProject: null,
      setActiveProject: (p: Project | null) => {
        if (p) {
          // lastActiveProject keeps the most recent REAL session so closing
          // the launcher without a new selection restores it (tags-search plan §4.4)
          set({ activeProject: p, isLauncherOpen: false, lastActiveProject: p })
        } else {
          // null clears the view but KEEPS the restorable session
          set({ activeProject: null, isLauncherOpen: true })
        }
      },
      setPipelineStatus: (s) => set({ pipelineStatus: s }),
      setLauncherOpen: (v) => set({ isLauncherOpen: v }),
      closeLauncherRestoringSession: () => {
        // Switch Project → X without choosing anything: restore the session
        // the user came from instead of dropping them to a blank dashboard.
        const last = get().lastActiveProject
        if (last) {
          set({ activeProject: last, isLauncherOpen: false })
        } else {
          set({ isLauncherOpen: false })
        }
      },
    }),
    {
      name: 'qcm-app-store',
      partialize: (state) => ({
        activeProject: state.activeProject,
        isLauncherOpen: state.isLauncherOpen,
        lastActiveProject: state.lastActiveProject,
      }),
    }
  )
)
