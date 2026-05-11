import { StepId } from '../../../types'
import { ExportExistingButton } from '../../step8/ExportExistingButton'
import { useAppStore } from '../../../store/appStore'
import { useStepModels } from '../../../hooks/useStepModels'

const STEP_DESCRIPTIONS: Record<number, string> = {
  1.5: "Fixes common text issues and formatting in the extracted text automatically.",
  1.6: "Optional manual check step for OCR errors. This will be expanded in Phase 4.",
  5: "Merges all per-page JSON files from Step 2 into a single unified QCM list. No configuration needed.",
  7: "Assigns category IDs using Llama-3.3. Reads categorization.model from .env.",
  8: "Runs similarity matching against the reference DB. Configure thresholds in Settings."
}

export function StepRunOnly({ id }: { id: StepId }) {
  const activeProject = useAppStore(s => s.activeProject)
  const { models } = useStepModels()

  const getActiveModel = () => {
    if (!models) return null;
    if (id === 1.5) return models.step1_5?.primary;
    if (id === 1.6) return models.step1_6?.primary;
    if (id === 7) return models.step7?.primary;
    return null;
  }

  const activeModel = getActiveModel();

  return (
    <div className="space-y-6 animate-in fade-in slide-in-from-bottom-2 duration-300">
      <div className="p-6 bg-surface-container-low rounded-2xl border border-outline-variant/10 flex gap-4">
        <span className="material-symbols-outlined text-primary text-3xl">info</span>
        <div className="flex-1">
          <p className="text-sm text-on-surface leading-relaxed">
            {STEP_DESCRIPTIONS[id as number] || "This step has no configurable parameters."}
          </p>
          <div className="mt-4 flex items-center justify-between">
            <p className="text-[11px] text-outline font-bold uppercase tracking-widest">
              Configuration: None Required
            </p>
            {activeModel && (
              <div className="px-2 py-1 bg-surface-container rounded-lg border border-outline-variant/10">
                <p className="text-[10px] text-primary font-mono">{activeModel}</p>
              </div>
            )}
          </div>
        </div>
      </div>

      {id === 8 && activeProject && (
        <ExportExistingButton projectName={activeProject.name} />
      )}
    </div>
  )
}
