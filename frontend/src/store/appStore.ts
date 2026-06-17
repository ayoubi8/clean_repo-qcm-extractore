import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { AppState, Project } from '../types'

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      activeProject: null,
      pipelineStatus: 'idle',
      isLauncherOpen: true,
      setActiveProject: (p: Project | null) => set({ activeProject: p, isLauncherOpen: !p }),
      setPipelineStatus: (s) => set({ pipelineStatus: s }),
      setLauncherOpen: (v) => set({ isLauncherOpen: v }),
    }),
    {
      name: 'qcm-app-store',
      partialize: (state) => ({
        activeProject: state.activeProject,
        isLauncherOpen: state.isLauncherOpen,
      }),
    }
  )
)
