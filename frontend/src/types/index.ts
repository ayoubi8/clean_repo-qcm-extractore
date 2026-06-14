// Maps to ProjectContext.list_projects() output + stub_api.py MOCK_PROJECTS shape
export interface Project {
  name: string;          // = folder name under output/
  last_step: number;     // 0–8, maps to tracker.current_step
  last_modified: string; // ISO 8601
  total_tokens: number;  // from cost_tracker.total_tokens
  pdf_path: string;      // absolute path to source PDF — persisted in project.json
}

export type StepId = 1 | 1.5 | 1.6 | 2 | 3 | 4 | 5 | 6 | 7 | 8
export type StepStatus = 'idle' | 'running' | 'done' | 'error'

export interface StepState {
  id: StepId
  label: string          // display name
  status: StepStatus
  outputExists: boolean  // true = warn before overwrite
}

export interface LogLine {
  ts: string             // "14:22:01"
  type: 'info' | 'ok' | 'warn' | 'error'
  text: string
}

// Step configs — one interface per step that has fields
export interface Step1Config {
  method: 'vision_ocr' | 'pypdfium2'
  ocr_guidance: string
  model: string
}

export interface Step2Config {
  extraction_mode: 'single_batch' | 'auto_loop'
  chunk_size: number
  page_range: string
  model_primary: string
  model_fallback: string
  extraction_guidance: string
  clinical_case_hints: boolean
}

export type MetaStrategy = 'skip' | 'global' | 'per_qcm' | 'per_group'
export interface MetaFieldConfig {
  strategy: MetaStrategy
  value: string | null
}
export interface Step3Config {
  model: string
  model_fallback: string
  fields: {
    year: MetaFieldConfig
    source: MetaFieldConfig
    category: MetaFieldConfig
    subcategory: MetaFieldConfig
    clinical_case: MetaFieldConfig
  }
  global_pages: string
}

export interface Step4Fields {
  Num: boolean
  Text: boolean
  Propositions: boolean
  Correct: boolean
  Year: boolean
  Category: boolean
  Subcategory: boolean
  Source: boolean
  Tag: boolean
  ClinicalCase: boolean
}

export interface Step4Config {
  name: string
  fields: Step4Fields
}

export type CorrectionSource = 'ai_knowledge' | 'page_text' | 'auto_detect' | 'vision_ai'
export type SearchMode = 'specific_pages' | 'all_pages'
export interface Step6Config {
  source: CorrectionSource
  ai_mode: 'sequential' | 'batch'
  correction_search_mode: SearchMode
  pages: string
  force_overwrite: boolean
  ai_model: string
  text_model: string
  vision_model: string
  all_pages_model: string
  vision_prompt: string
  page_text_guidance: string
  candidate_threshold: number
  include_neighbors: boolean
  pdf_path: string
}

export type MatchMode = 'text_only' | 'full' | 'weighted'

export interface Step8Config {
  ref_db_path: string
  match_mode: MatchMode
  threshold: number        // 0.0 – 1.0
  text_weight: number      // 0.0 – 1.0 (weighted mode only)
  corr_weight: number      // auto = 1 - text_weight
  color_green: number      // default 0.90
  color_yellow: number     // default 0.75
  // Custom export params
  export_from: number      // 0.0 – 1.0
  export_to: number        // 0.0 – 1.0
  export_filename: string
}

export interface BatchConfig {
  batch_mode: {
    enabled: boolean
    start_step: number
    end_step: number
    pause_for_verification: boolean
  }
  extraction: object
  qcm_extraction: object
  metadata: object
  template: object
  corrections: object
  folder_batch: {
    enabled: boolean
    input_folder: string
    file_pattern: string
    output_base: string
    parallel_processing: boolean
  }
}

export interface AutoRunPayload {
  mode: 'yaml' | 'interactive'
  start_step: number
  end_step: number
  pause_for_verification: boolean
  use_folder_batch: boolean
  run_config: {
    step1?: object
    step2?: object
    step3?: object
    step4?: object
    step6?: object
  }
}

export interface AutoRunState {
  startStep: number
  endStep: number
  pauseForVerification: boolean
  useYaml: boolean
  batchConfig: BatchConfig | null
  yamlLoading: boolean
  yamlError: string | null
  isRunning: boolean
  setStartStep: (n: number) => void
  setEndStep: (n: number) => void
  setPauseForVerification: (v: boolean) => void
  setUseYaml: (v: boolean) => void
  setBatchConfig: (c: BatchConfig | null) => void
  setYamlLoading: (v: boolean) => void
  setYamlError: (e: string | null) => void
  setIsRunning: (v: boolean) => void
}

export type StepBadge = 'success' | 'warning' | 'error'

export interface StepRunRecord {
  run_at: string
  badge: StepBadge
  duration_seconds: number
  pages_ok?: number
  pages_failed?: number
  qcms?: number
  empty_pages?: number
  merged_qcms?: number
}

export type StepHistory = Record<string, StepRunRecord[]>

// Maps to CostTracker.get_total_summary() output
export interface ModelCost {
  cost: number
  tokens: { prompt: number; completion: number }
}
export interface StepCost {
  total_cost: number
  call_count: number
  total_tokens: { prompt: number; completion: number }
}
export interface CostSummary {
  per_model: Record<string, ModelCost>
  per_step:  Record<string, StepCost>
  total_cost: number
  total_tokens: number
}

// .env key shape returned by GET /env
export interface EnvKeys {
  OPENROUTER_API_KEY: string
  ENABLE_CACHING: string
}

// Export result from POST /step8/export-existing
export interface ExportResult {
  success: boolean
  file_path: string
  record_count: number
}

// Global app state shape
export interface AppState {
  activeProject: Project | null;
  pipelineStatus: 'idle' | 'running';
  isLauncherOpen: boolean;
  setActiveProject: (p: Project | null) => void;
  setPipelineStatus: (s: 'idle' | 'running') => void;
  setLauncherOpen: (v: boolean) => void;
}
