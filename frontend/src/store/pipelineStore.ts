import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { StepId, StepStatus, StepState, LogLine, Step1Config, Step2Config, Step3Config, Step4Config, Step6Config, Step8Config } from '../types'

interface PipelineStore {
  steps: StepState[]
  activeStepId: StepId | null
  logLines: LogLine[]

  // configs
  step1Config: Step1Config
  step2Config: Step2Config
  step3Config: Step3Config
  step4Config: Step4Config
  step6Config: Step6Config
  step8Config: Step8Config

  setStepStatus: (id: StepId, s: StepStatus) => void
  setStepOutputExists: (id: StepId, exists: boolean) => void
  setActiveStep: (id: StepId) => void
  appendLog: (line: LogLine) => void
  clearLog: () => void
  setStep1Config: (c: Partial<Step1Config>) => void
  setStep2Config: (c: Partial<Step2Config>) => void
  setStep3Config: (c: Partial<Step3Config>) => void
  setStep4Config: (c: Partial<Step4Config>) => void
  setStep6Config: (c: Partial<Step6Config>) => void
  setStep8Config: (c: Partial<Step8Config>) => void
}

const INITIAL_STEPS: StepState[] = [
  { id: 1, label: 'Step 1 · Text Extraction', status: 'idle', outputExists: false },
  { id: 1.5, label: 'Step 1.5 · Text Fixer (auto)', status: 'idle', outputExists: false },
  { id: 1.6, label: 'Step 1.6 · OCR Corrector', status: 'idle', outputExists: false },
  { id: 2, label: 'Step 2 · QCM Extraction', status: 'idle', outputExists: false },
  { id: 3, label: 'Step 3 · Metadata Detection', status: 'idle', outputExists: false },
  { id: 4, label: 'Step 4 · Format & Template', status: 'idle', outputExists: false },
  { id: 5, label: 'Step 5 · JSON Merge', status: 'idle', outputExists: false },
  { id: 6, label: 'Step 6 · Corrections', status: 'idle', outputExists: false },
  { id: 7, label: 'Step 7 · Categorization', status: 'idle', outputExists: false },
  { id: 8, label: 'Step 8 · Similarity Match', status: 'idle', outputExists: false },
]

export const usePipelineStore = create<PipelineStore>()(
  persist(
    (set) => ({
      steps: INITIAL_STEPS,
      activeStepId: 1,
      logLines: [],

      step1Config: {
        method: 'vision_ocr',
        ocr_guidance: 'Two-column layout. PRESERVE ALL TABLES as markdown. Preserve lists.',
        model: ''   // seeded from .env STEP1_MODEL by Step1Config useEffect
      },
      step2Config: {
        extraction_mode: 'single_batch',
        chunk_size: 3,
        page_range: '',
        model_primary: '',
        model_fallback: '',
        extraction_guidance: '',
        clinical_case_hints: false,
      },
      step3Config: {
        model: '',
        model_fallback: '',
        fields: {
          year:           { strategy: 'per_qcm', value: null },
          source:         { strategy: 'skip',    value: 'Externat' },
          category:       { strategy: 'global',  value: null },
          subcategory:    { strategy: 'per_qcm', value: null },
          clinical_case:  { strategy: 'per_group', value: null }
        },
        global_pages: '1'
      },
      step4Config: { 
        name: 'pediat',
        fields: {
          Num:          true,
          Text:         true,
          Propositions: true,
          Correct:      true,
          Year:         true,
          Category:     true,
          Subcategory:  false,
          Source:       false,
          Tag:          true,
          ClinicalCase: false,
        }
      },
      step6Config: {
        source: 'auto_detect',
        ai_mode: 'sequential',
        correction_search_mode: 'all_pages',
        pages: '',
        force_overwrite: false,
        ai_model: '',
        text_model: '',
        vision_model: '',
        all_pages_model: '',
        vision_prompt: '',
        page_text_guidance: '',
        candidate_threshold: 15,
        include_neighbors: true,
        pdf_path: '',
      },
      step8Config: {
        ref_db_path: '',
        match_mode: 'text_only',
        threshold: 0.75,
        text_weight: 0.7,
        corr_weight: 0.3,
        color_green: 0.90,
        color_yellow: 0.75,
        export_from: 0.0,
        export_to: 0.6,
        export_filename: 'custom_export',
      },

      setStepStatus: (id, s) => set((state) => ({
        steps: state.steps.map(st => st.id === id ? { ...st, status: s } : st)
      })),
      setStepOutputExists: (id, exists) => set((state) => ({
        steps: state.steps.map(st => st.id === id ? { ...st, outputExists: exists } : st)
      })),
      setActiveStep: (id) => set({ activeStepId: id }),
      appendLog: (line) => set((state) => ({ logLines: [...state.logLines, line] })),
      clearLog: () => set({ logLines: [] }),
      setStep1Config: (c) => set((state) => ({ step1Config: { ...state.step1Config, ...c } })),
      setStep2Config: (c) => set((state) => ({ step2Config: { ...state.step2Config, ...c } })),
      setStep3Config: (c) => set((state) => ({ step3Config: { ...state.step3Config, ...c } })),
      setStep4Config: (c) => set((state) => ({ step4Config: { ...state.step4Config, ...c } })),
      setStep6Config: (c) => set((state) => ({ step6Config: { ...state.step6Config, ...c } })),
      setStep8Config: (c) => set((state) => ({ step8Config: { ...state.step8Config, ...c } })),
    }),
    {
      name: 'qcm-pipeline-store',
      partialize: (state) => ({
        activeStepId: state.activeStepId,
        step1Config: state.step1Config,
        step2Config: state.step2Config,
        step3Config: state.step3Config,
        step4Config: state.step4Config,
        step6Config: state.step6Config,
        step8Config: state.step8Config,
      }),
    }
  )
)
