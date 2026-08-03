import { useState } from 'react'
import { usePipelineStore } from '../../store/pipelineStore'
import { StepId } from '../../types'
import { Step1Config } from './configs/Step1Config'
import { Step2_3Config } from './configs/Step2_3Config'
import { Step6Config } from './configs/Step6Config'
import { Step8Config } from './configs/Step8Config'
import { StepRunOnly } from './configs/StepRunOnly'
import { runStep, connectLogStream, getStepStatus } from '../../lib/api'
import { useAppStore } from '../../store/appStore'
import { OutputViewer } from './OutputViewer'
import { useStepHistory } from '../../hooks/useStepHistory'

// Steps 3, 4 & 5 are intentionally absent:
// - Step 3 is now part of the merged "Step 2 · QCM Extraction + Metadata"
//   row — it fires as an invisible cascade after Step 2 succeeds
//   (see modules/post_step2_metadata.py).
// - Steps 4 & 5 are an invisible backend operation after Step 3
//   (see modules/post_step3_build.py).
const CONFIG_MAP: Record<string, React.FC<any>> = {
  '1': Step1Config,
  '2': Step2_3Config,
  '6': Step6Config,
  '7': StepRunOnly,
  '8': Step8Config,
}

function StepHeader({ id, label, lastRun }: { id: StepId, label: string, lastRun?: any }) {
  return (
    <div className="flex items-center gap-4 mb-8">
      <div className="w-12 h-12 bg-primary/10 rounded-2xl flex items-center justify-center border border-primary/20">
        <span className="text-xl font-black text-primary">{id}</span>
      </div>
      <div>
        <h2 className="text-2xl font-black text-on-surface tracking-tight" id="config-step-title">{label}</h2>
        <p className="text-xs text-outline font-medium">Pipeline Configuration Panel</p>
        
        {lastRun && (() => {
          const badgeEmoji = lastRun.badge === 'success' ? '✅' : lastRun.badge === 'warning' ? '⚠️' : lastRun.badge === 'error' ? '❌' : ''
          return (
            <div className="flex items-center gap-2 mt-2 flex-wrap">
              <span className="bg-surface-container-highest px-1.5 py-0.5 rounded text-[9px] uppercase font-black tracking-tighter text-outline">Last Run</span>
              {badgeEmoji && <span className="text-[11px]" title={`Status: ${lastRun.badge}`}>{badgeEmoji}</span>}
              <span className="text-[10px] text-outline font-mono">{new Date(lastRun.run_at).toLocaleDateString()}</span>
              {lastRun.duration_seconds && <span className="text-[10px] text-outline font-mono">· {lastRun.duration_seconds}s</span>}
              {lastRun.qcms != null && <span className="text-[10px] text-outline font-mono">· {lastRun.qcms} QCMs</span>}
              {lastRun.pages_ok != null && <span className="text-[10px] text-outline font-mono">· {lastRun.pages_ok} pages</span>}
              {lastRun.merged_qcms != null && <span className="text-[10px] text-outline font-mono">· {lastRun.merged_qcms} merged</span>}
            </div>
          )
        })()}
      </div>
    </div>
  )
}

function OverwriteWarning({ onConfirm, confirmed }: { onConfirm: (v: boolean) => void, confirmed: boolean }) {
  return (
    <div className="p-4 bg-tertiary-container/5 border border-tertiary/20 rounded-xl flex gap-3 mt-8 animate-in shake-in duration-300">
      <span className="material-symbols-outlined text-tertiary">warning</span>
      <div className="space-y-3">
        <p className="text-xs text-tertiary font-bold">Existing output detected for this step.</p>
        <label className="flex items-center gap-2 cursor-pointer group">
          <input 
            id="checkbox-overwrite-confirm"
            type="checkbox" 
            checked={confirmed} 
            onChange={(e) => onConfirm(e.target.checked)}
            className="w-4 h-4 rounded border-tertiary/40 bg-transparent text-tertiary focus:ring-tertiary"
          />
          <span className="text-[11px] text-on-surface-variant group-hover:text-on-surface transition-colors">
            I understand, overwrite existing output
          </span>
        </label>
      </div>
    </div>
  )
}



export function ConfigPanel() {
  const activeStepId = usePipelineStore(s => s.activeStepId)
  const steps = usePipelineStore(s => s.steps)
  const activeStep = steps.find(s => s.id === activeStepId)
  const [overwriteConfirmed, setOverwriteConfirmed] = useState(false)
  const [loading, setLoading] = useState(false)

  const setStepStatus = usePipelineStore(s => s.setStepStatus)
  const setStepOutputExists = usePipelineStore(s => s.setStepOutputExists)
  const appendLog = usePipelineStore(s => s.appendLog)
  const clearLog = usePipelineStore(s => s.clearLog)
  const activeProject = useAppStore(s => s.activeProject)
  const setPipelineStatus = useAppStore(s => s.setPipelineStatus)
  const store = usePipelineStore()
  const { history, reloadHistory } = useStepHistory(activeProject?.name ?? null)

  if (!activeStep) return (
    <div className="flex-1 flex items-center justify-center text-outline italic text-sm">
      Select a step to configure
    </div>
  )

  const handleRun = async () => {
    if (!activeProject) return
    clearLog()
    setLoading(true)
    setStepStatus(activeStep.id, 'running')
    setPipelineStatus('running')
    appendLog({ 
      ts: new Date().toLocaleTimeString(), 
      type: 'info', 
      text: `▶ Starting ${activeStep.label}...` 
    })

    try {
      let config: Record<string, any> = {}
      if (activeStep.id === 1) config = {
        ...store.step1Config,
        pdf_path: activeProject?.pdf_path ?? '',
        force_overwrite: overwriteConfirmed,
      }
      if (activeStep.id === 2) {
        const s = store.step2Config
        config = {
          // Auto-Loop mode is the only mode now (single_batch removed). The
          // page_range pattern "{n}-{n}-{n}" makes Step2QCMExtractBatch.run
          // take the _run_loop_mode branch. Hardcoded to 1-1-1 (one page per
          // chunk) for safest extraction on long PDFs.
          page_range: '1-1-1',
          model_primary: s.model_primary,
          model_fallback: s.model_fallback,
          extraction_guidance: s.extraction_guidance,
          clinical_case_hints: s.clinical_case_hints,
          // Step 3 config is embedded in the merged Step 2 panel and
          // forwarded to run_post_step2_metadata. Includes huge_edit flag.
          step3: store.step3Config,
        }
      }
      if (activeStep.id === 3) config = store.step3Config  // legacy: step 3 row removed, kept for safety
      if (activeStep.id === 6) config = {
        ...store.step6Config,
        pdf_path: activeProject?.pdf_path ?? ''
      }
      if (activeStep.id === 8) config = {
        ...store.step8Config,
      }

      await runStep(activeProject.name, activeStep.id, config)
      
      connectLogStream(
        activeProject.name, 
        activeStep.id, 
        (line) => appendLog(line),
        async () => {
          const status = await getStepStatus(activeProject.name, activeStep.id)
          setStepStatus(activeStep.id, status.status)
          setStepOutputExists(activeStep.id, status.output_exists)
          setPipelineStatus('idle')
          setLoading(false)
          reloadHistory() // Refresh badges and stats
        }
      )
    } catch (err: any) {
      setStepStatus(activeStep.id, 'error')
      setPipelineStatus('idle')
      setLoading(false)
      appendLog({ 
        ts: new Date().toLocaleTimeString(), 
        type: 'error', 
        text: `Failed: ${err.message}` 
      })
    }
  }

  const ConfigComponent = CONFIG_MAP[activeStep.id.toString()]
  const isRunDisabled = loading || (activeStep.outputExists && !overwriteConfirmed)

  return (
    <section className="flex-1 overflow-y-auto bg-surface custom-scrollbar">
      <div className="max-w-3xl p-10 pb-32">
        <StepHeader 
          id={activeStep.id} 
          label={activeStep.label} 
          lastRun={history[activeStep.id.toString()]?.slice(-1)[0]}
        />
        
        {ConfigComponent ? <ConfigComponent id={activeStep.id} /> : <p>No config for this step</p>}

        {activeStep.outputExists && (
          <OverwriteWarning 
            confirmed={overwriteConfirmed} 
            onConfirm={setOverwriteConfirmed} 
          />
        )}

        {activeStep.id !== 1.5 && (  // legacy guard — 1.5 no longer in CONFIG_MAP, but keep for safety
          <div className="mt-12 pt-8 border-t border-outline-variant/10">
            <button
              id="btn-run-step-config"
              onClick={handleRun}
              disabled={isRunDisabled}
              className="w-full py-4 bg-primary text-on-primary rounded-xl font-black uppercase tracking-widest flex items-center justify-center gap-3 hover:bg-primary/90 disabled:opacity-40 disabled:cursor-not-allowed transition-all shadow-[0_4px_20px_rgba(76,215,246,0.3)]"
            >
              {activeStep.status === 'running' ? (
                <>
                  <span className="material-symbols-outlined animate-spin">refresh</span>
                  Running...
                </>
              ) : (
                <>
                  <span className="material-symbols-outlined">play_arrow</span>
                  {activeStep.status === 'done' ? 'Re-run Step' : 'Run Step'}
                </>
              )}
            </button>
          </div>
        )}

        {activeProject && (
          <OutputViewer projectName={activeProject.name} stepId={activeStep.id.toString()} />
        )}
      </div>
    </section>
  )
}
