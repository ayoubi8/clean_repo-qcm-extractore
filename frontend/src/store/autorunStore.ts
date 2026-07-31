import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { AutoRunState } from '../types'

// Steps 3, 4 and 5 are intentionally absent:
// - Step 3 now fires inside Step 2's task (see backend
//   modules/post_step2_metadata.py).
// - Steps 4 & 5 fire inside that same cascade (modules/post_step3_build.py).
const ALLOWED_STEPS = [1, 2, 6, 7, 8]
const nearestAllowed = (n: number, fallback: number) =>
  ALLOWED_STEPS.includes(n) ? n : fallback

export const useAutorunStore = create<AutoRunState>()(
  persist(
    (set) => ({
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
    }),
    {
      name: 'qcm-autorun-store-v2',
      partialize: (state) => ({
        startStep: state.startStep,
        endStep: state.endStep,
        pauseForVerification: state.pauseForVerification,
        useYaml: state.useYaml,
        batchConfig: state.batchConfig,
      }),
      migrate: (persisted: any) => {
        // Coerce any legacy persisted startStep/endStep that pointed at a
        // now-removed step (3, 4 or 5) back onto a valid allowed step.
        // Step 3 was merged into Step 2, so legacy step-3 selections collapse
        // onto Step 2; 4/5 were already handled at v1 but the helper now also
        // covers 3.
        if (!persisted) return persisted
        const startStep = nearestAllowed(Number(persisted.startStep ?? 1), 1)
        const endStep = nearestAllowed(Number(persisted.endStep ?? 7), 7)
        return { ...persisted, startStep, endStep }
      },
      version: 2,
    }
  )
)
