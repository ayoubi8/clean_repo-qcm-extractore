import { create } from 'zustand'
import type { AppState, Project } from '../types'

export const useAppStore = create<AppState>((set) => ({
  activeProject: null,
  pipelineStatus: 'idle',
  isLauncherOpen: true,
  setActiveProject: (p: Project | null) => set({ activeProject: p, isLauncherOpen: !p }),
  setPipelineStatus: (s) => set({ pipelineStatus: s }),
  setLauncherOpen: (v) => set({ isLauncherOpen: v }),
}))
