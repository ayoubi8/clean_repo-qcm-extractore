import { useState } from 'react'
import { useStepModels } from '../../../hooks/useStepModels'
import { MetaStrategy, MetaFieldConfig, AutoRunBatchConfig, TagEntry } from '../../../types'
import { TagSelector } from '../../tags/TagSelector'

/**
 * Auto Run batch — one config for ALL PDFs (plan docs/plans/autorun-batch-plan.md §3.2).
 *
 * Wizard-local config state (NOT pipelineStore) — identical visual language to
 * the pipeline config panels (Step1/2/6) without touching their stores.
 * Hidden cascades (Step 1.5/1.6, the Step 3 metadata cascade, CC Checker) are
 * NOT exposed — they run at Settings defaults (resolved Q7).
 */

export interface WizardConfig {
  step1: {
    method: 'vision_ocr' | 'pypdfium2'
    ocr_guidance: string
    model: string
    model_fallback: string
  }
  step2: {
    model_primary: string
    model_fallback: string
    extraction_guidance: string
    clinical_case_hints: boolean
  }
  meta: {
    fields: {
      year: MetaFieldConfig
      source: MetaFieldConfig
      category: MetaFieldConfig
      clinical_case: MetaFieldConfig
    }
    global_pages: string
  }
  step6: {
    correction_source: 'last_page' | 'first_page' | 'auto_search'
    text_model: string
    text_fallback: string
    all_pages_model: string
    all_pages_fallback: string
    page_text_guidance: string
    candidate_threshold: number
    include_neighbors: boolean
  }
}

export function defaultWizardConfig(): WizardConfig {
  return {
    step1: {
      method: 'vision_ocr',
      ocr_guidance: 'Two-column layout. PRESERVE ALL TABLES as markdown. Preserve lists.',
      model: '',
      model_fallback: '',
    },
    step2: {
      model_primary: '',
      model_fallback: '',
      extraction_guidance: '',
      clinical_case_hints: false,
    },
    meta: {
      fields: {
        year: { strategy: 'per_qcm', value: null },
        source: { strategy: 'skip', value: 'Externat' },
        category: { strategy: 'global', value: null },
        clinical_case: { strategy: 'per_group', value: null },
      },
      global_pages: '1',
    },
    step6: {
      correction_source: 'auto_search',
      text_model: '',
      text_fallback: '',
      all_pages_model: '',
      all_pages_fallback: '',
      page_text_guidance: '',
      candidate_threshold: 15,
      include_neighbors: true,
    },
  }
}

// Metadata cycle orders — same as the pipeline Step 3 panel
const STRATEGIES: Record<string, { order: MetaStrategy[] }> = {
  default: { order: ['skip', 'global', 'per_qcm'] },
  clinical_case: { order: ['skip', 'per_group', 'global'] },
}

const STRATEGY_STYLING: Record<MetaStrategy, { label: string; icon: string; style: string }> = {
  skip: { label: 'Skip', icon: 'block', style: 'bg-surface-container-highest text-outline border-outline-variant/20' },
  global: { label: 'Global', icon: 'public', style: 'bg-primary/10 text-primary border-primary/30' },
  per_qcm: { label: 'Per-QCM', icon: 'neurology', style: 'bg-secondary-container/30 text-secondary border-secondary/30' },
  per_group: { label: 'Per-Group', icon: 'group', style: 'bg-tertiary-container/10 text-tertiary border-tertiary/30' },
}

const CLINICAL_NOTES: Record<string, string> = {
  skip: 'No case grouping — text is still cleaned of any embedded case narrative (~1 extra LLM call per page).',
  per_group: 'Detects and links related cases across QCMs, verified by the CC Checker (Settings defaults).',
  global: 'One case narrative applied to every QCM in the document.',
}

/** Serialize the wizard metadata state → backend autorun shape
 *  (identical to AutoRunPanel.serializeStep3 so the cascade contract holds). */
function serializeMeta(meta: WizardConfig['meta']) {
  const CODE_MAP: Record<string, string> = { skip: 'S', global: 'G', per_qcm: 'P', per_group: 'CC' }
  const FIELD_MAP: Record<string, string> = { year: 'Year', source: 'Source', category: 'Category', clinical_case: 'ClinicalCase' }
  const config: Record<string, string> = {}
  const global_values: Record<string, string> = {}
  for (const [k, v] of Object.entries(meta.fields) as [string, MetaFieldConfig][]) {
    config[FIELD_MAP[k]] = CODE_MAP[v.strategy]
    if (v.strategy === 'global' && v.value) global_values[FIELD_MAP[k]] = v.value
  }
  const global_pages = meta.global_pages.split(',').map(s => parseInt(s.trim())).filter(n => !isNaN(n))
  return { config, global_values, global_pages }
}

/** Wizard state → POST /autorun/batch/start wire config */
export function buildBatchConfig(c: WizardConfig): AutoRunBatchConfig {
  const step1: AutoRunBatchConfig['step1'] = { method: c.step1.method }
  if (c.step1.method === 'vision_ocr') {
    step1.ocr_guidance = c.step1.ocr_guidance
    step1.model = c.step1.model
  }
  return {
    step1,
    step2: {
      model_primary: c.step2.model_primary,
      model_fallback: c.step2.model_fallback,
      extraction_guidance: c.step2.extraction_guidance,
      clinical_case_hints: c.step2.clinical_case_hints,
      step3: serializeMeta(c.meta),
    },
    step6: {
      correction_source: c.step6.correction_source,
      ...(c.step6.correction_source === 'auto_search'
        ? { all_pages_model: c.step6.all_pages_model, all_pages_fallback: c.step6.all_pages_fallback,
            candidate_threshold: c.step6.candidate_threshold, include_neighbors: c.step6.include_neighbors }
        : { text_model: c.step6.text_model, text_fallback: c.step6.text_fallback }),
      ...(c.step6.page_text_guidance ? { page_text_guidance: c.step6.page_text_guidance } : {}),
    },
  }
}

// ── Shared small pieces ────────────────────────────────────────────────────

const SELECT_CLASS = "w-full bg-surface-container-lowest border border-outline-variant/20 rounded-xl px-4 py-3 text-sm focus:border-primary outline-none transition-all appearance-none disabled:opacity-50"
const CUSTOM_INPUT_CLASS = "w-full mt-1 bg-surface-container-lowest border border-outline-variant/20 rounded-xl px-4 py-3 text-sm focus:border-primary outline-none animate-in fade-in font-mono"

/** Main/fallback option pair seeded from GET /env/step-models. */
interface Pair { primary: string; fallback: string }

interface SectionProps {
  config: WizardConfig
  onChange: (c: Partial<WizardConfig>) => void
  models: any
  loading: boolean
}

/** Main + fallback model selects, seeded from Settings (Step2Config pattern). */
function ModelPair({ primary, fallback, options, onPrimary, onFallback, disabled }:
  { primary: string; fallback: string; options: Pair; onPrimary: (v: string) => void; onFallback: (v: string) => void; disabled?: boolean }) {
  const [customPrimary, setCustomPrimary] = useState(false)
  const [customFallback, setCustomFallback] = useState(false)
  if (disabled) {
    return <div className="p-4 rounded-xl bg-surface-container-low border border-outline-variant/10 text-[11px] text-outline animate-pulse">Loading models…</div>
  }
  return (
    <div className="grid grid-cols-2 gap-4">
      <div className="space-y-2">
        <label className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">Main</label>
        <select
          value={customPrimary ? 'custom' : primary}
          onChange={e => { if (e.target.value === 'custom') { setCustomPrimary(true) } else { setCustomPrimary(false); onPrimary(e.target.value) } }}
          className={SELECT_CLASS}
        >
          <option value="">⚙️ Use Settings default{options.primary ? ` (${options.primary})` : ''}</option>
          {options.primary && <option value={options.primary}>{options.primary} (Primary)</option>}
          {options.fallback && <option value={options.fallback}>{options.fallback} (Fallback)</option>}
          <option value="custom">Custom…</option>
        </select>
        {customPrimary && (
          <input type="text" value={primary} onChange={e => onPrimary(e.target.value)} placeholder="Model ID..." className={CUSTOM_INPUT_CLASS} />
        )}
      </div>
      <div className="space-y-2">
        <label className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">Fallback</label>
        <select
          value={customFallback ? 'custom' : fallback}
          onChange={e => { if (e.target.value === 'custom') { setCustomFallback(true) } else { setCustomFallback(false); onFallback(e.target.value) } }}
          className={SELECT_CLASS}
        >
          <option value="">⚙️ Use Settings default{options.fallback ? ` (${options.fallback})` : ''}</option>
          {options.primary && <option value={options.primary}>{options.primary}</option>}
          {options.fallback && <option value={options.fallback}>{options.fallback} (Fallback)</option>}
          <option value="custom">Custom…</option>
        </select>
        {customFallback && (
          <input type="text" value={fallback} onChange={e => onFallback(e.target.value)} placeholder="Model ID..." className={CUSTOM_INPUT_CLASS} />
        )}
      </div>
    </div>
  )
}

function SectionHeader({ icon, title }: { icon: string; title: string }) {
  return (
    <div className="flex items-center gap-2">
      <span className="material-symbols-outlined text-primary text-xl">{icon}</span>
      <span className="text-xs font-black text-on-surface-variant uppercase tracking-widest">{title}</span>
    </div>
  )
}

// ── Step 1 ─────────────────────────────────────────────────────────────────

const STEP1_METHODS = [
  { id: 'pypdfium2', label: 'pypdf', sub: 'Fast, digital PDFs (Selectable text)' },
  { id: 'vision_ocr', label: 'Vision OCR', sub: 'Scanned / Image PDFs (Uses Gemini Vision)' },
]

function Step1Section({ config, onChange, models, loading }: SectionProps) {
  const opts: Pair = { primary: models?.step1?.primary ?? '', fallback: models?.step1?.fallback ?? '' }
  return (
    <div className="space-y-5">
      <SectionHeader icon="text_fields" title="Step 1 · Text Extraction" />
      <div className="grid grid-cols-1 gap-3">
        {STEP1_METHODS.map(opt => (
          <div
            key={opt.id}
            id={`ar-method-${opt.id}`}
            onClick={() => onChange({ step1: { ...config.step1, method: opt.id as 'vision_ocr' | 'pypdfium2' } })}
            className={`p-4 rounded-xl border-2 cursor-pointer transition-all ${
              config.step1.method === opt.id
                ? 'border-primary bg-primary/5 shadow-[0_0_15px_rgba(76,215,246,0.1)]'
                : 'border-outline-variant/10 bg-surface-container-low hover:border-outline-variant/30'
            }`}
          >
            <div className="flex items-center justify-between">
              <div>
                <p className={`text-sm font-bold ${config.step1.method === opt.id ? 'text-primary' : 'text-on-surface'}`}>{opt.label}</p>
                <p className="text-[11px] text-outline mt-0.5">{opt.sub}</p>
              </div>
              <div className={`w-4 h-4 rounded-full border-2 flex items-center justify-center ${config.step1.method === opt.id ? 'border-primary' : 'border-outline'}`}>
                {config.step1.method === opt.id && <div className="w-2 h-2 bg-primary rounded-full" />}
              </div>
            </div>
          </div>
        ))}
      </div>

      {config.step1.method === 'vision_ocr' && (
        <div className="space-y-5 animate-in fade-in duration-500">
          <div className="space-y-2">
            <label className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">OCR Guidance</label>
            <textarea
              id="ar-input-ocr-guidance"
              rows={3}
              value={config.step1.ocr_guidance}
              onChange={(e) => onChange({ step1: { ...config.step1, ocr_guidance: e.target.value } })}
              className="w-full bg-surface-container-lowest border border-outline-variant/20 rounded-xl px-4 py-3 text-sm focus:border-primary outline-none transition-all resize-none custom-scrollbar"
            />
          </div>
          <ModelPair
            primary={config.step1.model}
            fallback={config.step1.model_fallback}
            options={opts}
            disabled={loading}
            onPrimary={v => onChange({ step1: { ...config.step1, model: v } })}
            onFallback={v => onChange({ step1: { ...config.step1, model_fallback: v } })}
          />
        </div>
      )}
    </div>
  )
}

// ── Step 2 ─────────────────────────────────────────────────────────────────

function Step2Section({ config, onChange, models, loading }: SectionProps) {
  const opts: Pair = { primary: models?.step2?.primary ?? '', fallback: models?.step2?.fallback ?? '' }
  const fields = config.meta.fields
  const showGlobalPanel = Object.values(fields).some(f => f.strategy === 'global')

  const cycle = (field: 'year' | 'source' | 'category' | 'clinical_case') => {
    const order = field === 'clinical_case' ? STRATEGIES.clinical_case.order : STRATEGIES.default.order
    const next = order[(order.indexOf(fields[field].strategy) + 1) % order.length]
    onChange({ meta: { ...config.meta, fields: { ...fields, [field]: { ...fields[field], strategy: next } } } })
  }

  return (
    <div className="space-y-5">
      <SectionHeader icon="question_answer" title="Step 2 · QCM Extraction + Metadata" />

      <ModelPair
        primary={config.step2.model_primary}
        fallback={config.step2.model_fallback}
        options={opts}
        disabled={loading}
        onPrimary={v => onChange({ step2: { ...config.step2, model_primary: v } })}
        onFallback={v => onChange({ step2: { ...config.step2, model_fallback: v } })}
      />

      <div className="space-y-2">
        <label className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">Extraction Guidance</label>
        <textarea
          id="ar-step2-guidance"
          rows={3}
          value={config.step2.extraction_guidance}
          onChange={e => onChange({ step2: { ...config.step2, extraction_guidance: e.target.value } })}
          className="w-full bg-surface-container-lowest border border-outline-variant/20 rounded-xl px-4 py-3 text-sm focus:border-primary outline-none transition-all resize-none custom-scrollbar"
          placeholder="Optional rules for the LLM..."
        />
      </div>

      {/* Metadata Strategy wizard-local (cycle table like Step3Config) */}
      <div className="space-y-3">
        <label className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">Metadata Strategy</label>
        <div className="bg-surface-container-low rounded-2xl border border-outline-variant/10 divide-y divide-outline-variant/5">
          {(Object.keys(fields) as Array<keyof typeof fields>).map(field => (
            <div key={field}>
              <div className="flex items-center justify-between p-4">
                <span className="text-sm font-bold capitalize text-on-surface-variant w-32">{field.replace('_', ' ')}</span>
                <button
                  id={`ar-cycle-${field}`}
                  onClick={() => cycle(field)}
                  className={`flex items-center gap-2 px-4 py-2 rounded-lg border text-xs font-bold transition-all w-32 justify-center ${STRATEGY_STYLING[fields[field].strategy].style}`}
                >
                  <span className="material-symbols-outlined text-[16px]">{STRATEGY_STYLING[fields[field].strategy].icon}</span>
                  {STRATEGY_STYLING[fields[field].strategy].label}
                </button>
              </div>
              {field === 'clinical_case' && (
                <div className="px-4 pb-4 -mt-2 space-y-1">
                  {STRATEGIES.clinical_case.order.map(st => (
                    <p key={st} className="text-[10px] text-outline px-1">
                      <span className="font-bold text-tertiary">{STRATEGY_STYLING[st].label}:</span>{' '}
                      {CLINICAL_NOTES[st]}
                    </p>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {showGlobalPanel && (
        <div className="space-y-4 p-5 bg-primary/5 rounded-2xl border border-primary/20 animate-in zoom-in-95 duration-300">
          <div className="space-y-2">
            <label className="text-[10px] font-black uppercase tracking-[0.2em] text-primary">Global Pages</label>
            <input
              type="text"
              value={config.meta.global_pages}
              onChange={(e) => onChange({ meta: { ...config.meta, global_pages: e.target.value } })}
              placeholder="1 or 1,11"
              className="w-full bg-surface-container-lowest border border-primary/20 rounded-xl px-4 py-3 text-sm focus:border-primary outline-none text-primary"
            />
          </div>
          {(Object.keys(fields) as Array<keyof typeof fields>).map(field => fields[field].strategy === 'global' && (
            <div key={field} className="space-y-2">
              <label className="text-[10px] font-black uppercase tracking-[0.2em] text-primary">{field} Value</label>
              <input
                type="text"
                value={fields[field].value || ''}
                onChange={(e) => onChange({
                  meta: {
                    ...config.meta,
                    fields: { ...fields, [field]: { ...fields[field], value: e.target.value } },
                  }
                })}
                placeholder={`Global ${field}...`}
                className="w-full bg-surface-container-lowest border border-primary/20 rounded-xl px-4 py-3 text-sm focus:border-primary outline-none text-primary"
              />
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Step 6 ─────────────────────────────────────────────────────────────────

const STEP6_SOURCES: { id: 'last_page' | 'first_page' | 'auto_search'; label: string; icon: string; desc: string }[] = [
  { id: 'last_page', label: 'Last page', icon: 'last_page', desc: "Each PDF's last page is auto-detected — e.g. a 9-page PDF uses page 9" },
  { id: 'first_page', label: 'First page', icon: 'first_page', desc: 'Corrections extracted from page 1 of every PDF' },
  { id: 'auto_search', label: 'Auto search', icon: 'search', desc: 'Scan every page with the full auto-detect cascade' },
]

function Step6Section({ config, onChange, models, loading }: SectionProps) {
  const isAuto = config.step6.correction_source === 'auto_search'
  const opts: Pair = isAuto
    ? { primary: models?.step6?.all_pages_model ?? '', fallback: models?.step6?.all_pages_fallback ?? '' }
    : { primary: models?.step6?.text_model ?? '', fallback: models?.step6?.text_fallback ?? '' }
  return (
    <div className="space-y-5">
      <SectionHeader icon="fact_check" title="Step 6 · Corrections" />
      <div className="grid grid-cols-1 gap-3">
        {STEP6_SOURCES.map(s => (
          <div
            key={s.id}
            id={`ar-step6-${s.id}`}
            onClick={() => onChange({ step6: { ...config.step6, correction_source: s.id } })}
            className={`p-4 rounded-xl border-2 cursor-pointer transition-all ${
              config.step6.correction_source === s.id
                ? 'border-primary bg-primary/5 shadow-[0_0_15px_rgba(76,215,246,0.1)]'
                : 'border-outline-variant/10 bg-surface-container-low hover:border-outline-variant/30'
            }`}
          >
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className={`text-sm font-bold ${config.step6.correction_source === s.id ? 'text-primary' : 'text-on-surface'}`}>{s.label}</p>
                <p className="text-[10px] text-outline mt-0.5 leading-tight">{s.desc}</p>
              </div>
              <span className={`material-symbols-outlined text-xl ${config.step6.correction_source === s.id ? 'text-primary' : 'text-outline'}`}>{s.icon}</span>
            </div>
          </div>
        ))}
      </div>

      <ModelPair
        primary={isAuto ? config.step6.all_pages_model : config.step6.text_model}
        fallback={isAuto ? config.step6.all_pages_fallback : config.step6.text_fallback}
        options={opts}
        disabled={loading}
        onPrimary={v => onChange({ step6: { ...config.step6, ...(isAuto ? { all_pages_model: v } : { text_model: v }) } })}
        onFallback={v => onChange({ step6: { ...config.step6, ...(isAuto ? { all_pages_fallback: v } : { text_fallback: v }) } })}
      />

      {isAuto && (
        <div className="p-4 bg-surface-container-low rounded-xl border border-outline-variant/10 grid grid-cols-2 gap-3">
          <div className="space-y-1">
            <label className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">Candidate Threshold</label>
            <input
              type="number" min={5} max={50}
              value={config.step6.candidate_threshold}
              onChange={(e) => onChange({ step6: { ...config.step6, candidate_threshold: parseInt(e.target.value) || 15 } })}
              className="w-full bg-surface-container-lowest border border-outline-variant/20 rounded-lg px-3 py-2 text-xs focus:border-primary outline-none"
            />
          </div>
          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <label className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">Include Neighbors</label>
              <p className="text-[9px] text-outline leading-tight">Scan adjacent pages</p>
            </div>
            <button
              onClick={() => onChange({ step6: { ...config.step6, include_neighbors: !config.step6.include_neighbors } })}
              className={`w-10 h-6 rounded-full transition-all ${config.step6.include_neighbors ? 'bg-primary' : 'bg-outline-variant/30'}`}
            >
              <div className={`w-4 h-4 bg-white rounded-full mx-1 transition-all ${config.step6.include_neighbors ? 'translate-x-4' : ''}`} />
            </button>
          </div>
        </div>
      )}

      <div className="space-y-2">
        <label className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">Extraction Guidance (Optional)</label>
        <textarea
          rows={2}
          value={config.step6.page_text_guidance}
          onChange={(e) => onChange({ step6: { ...config.step6, page_text_guidance: e.target.value } })}
          placeholder="e.g. Focus on rows with X marks in columns A-E..."
          className="w-full bg-surface-container-lowest border border-outline-variant/20 rounded-xl px-4 py-3 text-sm focus:border-primary outline-none transition-all resize-none custom-scrollbar"
        />
      </div>
    </div>
  )
}

export function BatchConfigForm({ config, onChange, tags, onTagsChange }: {
  config: WizardConfig
  onChange: (c: Partial<WizardConfig>) => void
  tags: TagEntry[]
  onTagsChange: (tags: TagEntry[]) => void
}) {
  const { models, loading } = useStepModels()
  return (
    <div className="space-y-10 animate-in fade-in slide-in-from-bottom-2 duration-300">
      {/* Tags & Search plan — required wilaya + optional module */}
      <div>
        <TagSelector tags={tags} onChange={onTagsChange} />
      </div>
      <div className="border-t border-outline-variant/10 pt-6" />
      <Step1Section config={config} onChange={onChange} models={models} loading={loading} />
      <div className="border-t border-outline-variant/10 pt-6" />
      <Step2Section config={config} onChange={onChange} models={models} loading={loading} />
      <div className="border-t border-outline-variant/10 pt-6" />
      <Step6Section config={config} onChange={onChange} models={models} loading={loading} />
    </div>
  )
}
