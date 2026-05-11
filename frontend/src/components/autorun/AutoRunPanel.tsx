import { useAutorunStore } from '../../store/autorunStore'
import { useAppStore } from '../../store/appStore'
import { StepRangeSelector } from './StepRangeSelector'
import { ToggleSwitch } from './ToggleSwitch'
import { YamlConfigSection } from './YamlConfigSection'
import { FolderBatchIndicator } from './FolderBatchIndicator'
import { Step3Config } from '../pipeline/configs/Step3Config'
import { Step6Config } from '../pipeline/configs/Step6Config'
import { startAutoRun } from '../../lib/api'
import { usePipelineStore } from '../../store/pipelineStore'

interface AutoRunPanelProps {
  onClose: () => void
}

export function AutoRunPanel({ onClose }: AutoRunPanelProps) {
  const store = useAutorunStore()
  const appStore = useAppStore()
  const pipelineStore = usePipelineStore()

  const isFolderBatch = store.useYaml && store.batchConfig?.folder_batch?.enabled === true
  const showPreflight = !store.useYaml
  const showStep3Pre = showPreflight && store.startStep <= 3 && store.endStep >= 3
  const showStep6Pre = showPreflight && store.startStep <= 6 && store.endStep >= 6

  const handleStart = async () => {
    if (!appStore.activeProject) return
    store.setIsRunning(true)

    // Serialization logic
    const serializeStep3 = (c: any) => {
      const CODE_MAP: any = { skip: 'S', global: 'G', per_qcm: 'P', per_group: 'CC' }
      const FIELD_MAP: any = { year: 'Year', source: 'Source', category: 'Category', subcategory: 'Subcategory', clinical_case: 'ClinicalCase' }
      const metaConfig: any = {}
      const globalValues: any = {}
      for (const [k, v] of Object.entries(c.fields) as any) {
        metaConfig[FIELD_MAP[k]] = CODE_MAP[v.strategy]
        if (v.strategy === 'global' && v.value) globalValues[FIELD_MAP[k]] = v.value
      }
      return {
        config: metaConfig,
        global_values: globalValues,
        global_pages: c.global_pages.split(',').map((n: string) => parseInt(n.trim())),
      }
    }

    const serializeStep6 = (c: any) => {
      const SRC_MAP: any = { ai_knowledge: '1', page_text: '2', auto_detect: '3', vision_ai: '4' }
      return {
        source: SRC_MAP[c.source],
        ...(c.ai_mode ? { ai_mode: c.ai_mode } : {}),
        ...(c.page_ref ? { page_ref: c.page_ref } : {}),
        ...(c.vision_prompt ? { vision_prompt: c.vision_prompt } : {}),
        correction_search_mode: c.correction_search_mode,
        ...(c.pages ? { pages: c.pages.split(',').map((p: string) => p.trim()) } : {})
      }
    }

    const payload = store.useYaml
      ? {
          mode: 'yaml',
          start_step: store.batchConfig!.batch_mode.start_step,
          end_step: Math.min(store.batchConfig!.batch_mode.end_step, 8),
          pause_for_verification: store.batchConfig!.batch_mode.pause_for_verification,
          use_folder_batch: isFolderBatch,
          run_config: {
            step1: store.batchConfig!.extraction,
            step2: store.batchConfig!.qcm_extraction,
            step3: store.batchConfig!.metadata,
            step4: store.batchConfig!.template,
            step6: store.batchConfig!.corrections,
          }
        }
      : {
          mode: 'interactive',
          start_step: store.startStep,
          end_step: store.endStep,
          pause_for_verification: store.pauseForVerification,
          use_folder_batch: false,
          run_config: {
            ...(showStep3Pre ? { step3: serializeStep3(pipelineStore.step3Config) } : {}),
            ...(showStep6Pre ? { step6: serializeStep6(pipelineStore.step6Config) } : {}),
          }
        }

    try {
      await startAutoRun(appStore.activeProject.name, payload)
      onClose()
    } catch (e) {
      console.error(e)
    } finally {
      store.setIsRunning(false)
    }
  }

  return (
    <>
      {/* Backdrop */}
      <div 
        className="fixed inset-0 bg-black/60 backdrop-blur-sm z-[60] animate-in fade-in duration-300" 
        onClick={onClose} 
      />

      {/* Drawer */}
      <div className="fixed right-0 top-0 h-full w-[560px] z-[70] bg-surface-container flex flex-col shadow-2xl border-l border-outline-variant/10 animate-in slide-in-from-right duration-500 ease-out">
        
        {/* Header */}
        <div className="px-8 py-8 border-b border-outline-variant/10 flex items-center justify-between bg-surface-container-high/50">
          <div>
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-primary animate-pulse" />
              <h2 className="text-2xl font-black text-on-surface tracking-tighter">Auto Run</h2>
            </div>
            <p className="text-[11px] text-outline mt-1 font-bold uppercase tracking-widest opacity-60">Pipeline Automation System</p>
          </div>
          <button 
            id="btn-close-autorun"
            onClick={onClose} 
            className="w-10 h-10 rounded-full hover:bg-surface-container-highest flex items-center justify-center transition-colors border border-outline-variant/10"
          >
            <span className="material-symbols-outlined text-outline">close</span>
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-8 py-8 space-y-10 custom-scrollbar">
          <StepRangeSelector disabled={isFolderBatch} />
          
          <div className={`flex items-center justify-between py-5 border-y border-outline-variant/10 ${isFolderBatch ? 'opacity-40 pointer-events-none' : ''}`}>
            <div>
              <p className="text-sm font-bold text-on-surface">Pause for Verification</p>
              <p className="text-[11px] text-outline mt-0.5 font-medium leading-tight">Wait for manual confirmation after each step.</p>
            </div>
            <ToggleSwitch 
              id="toggle-pause-verification"
              checked={store.pauseForVerification} 
              onChange={store.setPauseForVerification} 
            />
          </div>

          <YamlConfigSection />

          {isFolderBatch && <FolderBatchIndicator config={store.batchConfig!.folder_batch} />}

          {showPreflight && (
            <div className="space-y-10 pt-4 animate-in fade-in duration-500">
              <div className="flex items-center gap-3 pb-3 border-b border-outline-variant/10">
                <span className="material-symbols-outlined text-primary text-xl">tune</span>
                <span className="text-[10px] uppercase tracking-[0.2em] text-outline font-black">Pre-flight Config</span>
              </div>

              {showStep3Pre && (
                <div className="space-y-6">
                  <div className="flex items-center gap-2">
                    <span className="material-symbols-outlined text-primary">analytics</span>
                    <span className="text-xs font-black text-on-surface-variant uppercase tracking-widest">Step 3 · Metadata Strategy</span>
                  </div>
                  <Step3Config embedded />
                </div>
              )}

              {showStep6Pre && (
                <div className="space-y-6">
                  <div className="flex items-center gap-2">
                    <span className="material-symbols-outlined text-primary">fact_check</span>
                    <span className="text-xs font-black text-on-surface-variant uppercase tracking-widest">Step 6 · Corrections</span>
                  </div>
                  <Step6Config embedded />
                </div>
              )}

              {!showStep3Pre && !showStep6Pre && (
                <div className="p-6 bg-surface-container-low rounded-xl border border-outline-variant/10 text-center">
                  <p className="text-[11px] text-outline italic font-medium">No pre-flight configuration required for steps {store.startStep}–{store.endStep}.</p>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-8 py-8 bg-surface-container-high/80 backdrop-blur-xl border-t border-outline-variant/10">
          <div className="mb-5 flex items-center justify-between px-1">
            <span className="text-[10px] font-mono text-outline uppercase tracking-tighter">Execution Summary</span>
            <span className="text-[10px] font-mono text-primary font-bold">
              {isFolderBatch ? 'Folder Batch' : `Steps ${store.startStep} → ${store.endStep}`}
            </span>
          </div>
          
          <button
            id="btn-start-autorun"
            onClick={handleStart}
            disabled={store.isRunning || (!isFolderBatch && store.startStep > store.endStep)}
            className="w-full h-14 bg-gradient-to-r from-primary to-primary-container text-on-primary font-black uppercase tracking-widest rounded-2xl flex items-center justify-center gap-3 hover:shadow-[0_8px_30px_rgba(76,215,246,0.4)] hover:scale-[1.01] transition-all disabled:opacity-30 disabled:grayscale disabled:scale-100"
          >
            {store.isRunning ? (
              <>
                <span className="material-symbols-outlined animate-spin">refresh</span>
                Running...
              </>
            ) : (
              <>
                <span className="material-symbols-outlined">
                  {isFolderBatch ? 'folder_managed' : 'rocket_launch'}
                </span>
                {isFolderBatch ? 'Start Folder Batch' : 'Start Auto Run'}
              </>
            )}
          </button>
        </div>
      </div>
    </>
  )
}
