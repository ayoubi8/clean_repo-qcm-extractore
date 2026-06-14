import { create } from 'zustand'
import { AutoRunState } from '../types'

export const useAutorunStore = create<AutoRunState>((set) => ({
  startStep: 1,
  endStep: 7,
  pauseForVerification: false,
  useYaml: true,
  batchConfig: null,
  yamlLoading: false,
  yamlError: null,
  isRunning: false,
  setStartStep: (n) => set({ startStep: n }),
  setEndStep: (n) => set({ endStep: n }),
  setPauseForVerification: (v) => set({ pauseForVerification: v }),
  setUseYaml: (v) => set({ useYaml: v }),
  setBatchConfig: (c) => set({ batchConfig: c }),
  setYamlLoading: (v) => set({ yamlLoading: v }),
  setYamlError: (e) => set({ yamlError: e }),
  setIsRunning: (v) => set({ isRunning: v }),
}))
