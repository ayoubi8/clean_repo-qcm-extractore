import { useState, useEffect } from 'react'
import { usePipelineStore } from '../../../store/pipelineStore'
import { fetchTemplates } from '../../../lib/api'
import { Step4Fields } from '../../../types'

const FIELDS: { key: keyof Step4Fields; label: string; desc: string }[] = [
  { key: 'Num',          label: 'Num',          desc: 'Question number' },
  { key: 'Text',         label: 'Text',         desc: 'Question stem' },
  { key: 'Propositions', label: 'Propositions', desc: 'Choices A–E' },
  { key: 'Correct',      label: 'Correct',      desc: 'Correct answer' },
  { key: 'Year',         label: 'Year',         desc: 'Exam year' },
  { key: 'Category',     label: 'Category',     desc: 'Medical module' },
  { key: 'Subcategory',  label: 'Subcategory',  desc: 'Specific topic' },
  { key: 'Source',       label: 'Source',       desc: 'University/origin' },
  { key: 'Tag',          label: 'Tag',          desc: 'Combined tag' },
  { key: 'ClinicalCase', label: 'Cas Clinique', desc: 'Clinical case narrative' },
]

export function Step4Config() {
  const config = usePipelineStore(s => s.step4Config)
  const setConfig = usePipelineStore(s => s.setStep4Config)
  const [templates, setTemplates] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  useEffect(() => {
    async function load() {
      try {
        const data = await fetchTemplates()
        setTemplates(data)
      } catch (e) {
        setError(true)
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  const toggleField = (field: keyof Step4Fields) => {
    setConfig({
      fields: {
        ...config.fields,
        [field]: !config.fields[field]
      }
    })
  }

  const buildPreviewTemplate = (fields: Step4Fields) => {
    const tmpl: any = {}
    if (fields.Num) tmpl["Num"] = 0
    if (fields.Text) tmpl["Text"] = "Question text here..."
    if (fields.Propositions) {
      tmpl["A"] = "Option A"; tmpl["B"] = "Option B"; tmpl["C"] = "Option C"; tmpl["D"] = "Option D"; tmpl["E"] = "Option E"
    }
    if (fields.Correct) tmpl["Correct"] = "ABC"
    if (fields.Year) tmpl["Year"] = "2024"
    if (fields.Category) tmpl["categoryName"] = "Cardiologie"
    if (fields.Subcategory) tmpl["subcategoryName"] = "HTA"
    if (fields.Source) tmpl["Source"] = "Alger"
    if (fields.Tag) tmpl["Tag"] = ["Alger", "2024"]
    if (fields.ClinicalCase) tmpl["Cas"] = "CAS CLINIQUE 1\r\nNarrative..."
    return tmpl
  }

  return (
    <div className="space-y-8 animate-in fade-in slide-in-from-bottom-2 duration-300">
      {/* Template Selection */}
      <div className="space-y-4">
        <div className="space-y-2">
          <label className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">Output Template Base</label>
          {loading ? (
            <div className="w-full h-12 bg-surface-container-low animate-pulse rounded-xl" />
          ) : error ? (
            <div className="space-y-2">
              <input
                type="text"
                value={config.name}
                onChange={(e) => setConfig({ name: e.target.value })}
                className="w-full bg-surface-container-lowest border border-error/30 rounded-xl px-4 py-3 text-sm focus:border-error outline-none transition-all"
                placeholder="pediat"
              />
              <p className="text-[10px] text-error">Failed to load templates. Entering manually.</p>
            </div>
          ) : (
            <div className="relative">
              <select
                id="select-step4-template"
                value={config.name}
                onChange={(e) => setConfig({ name: e.target.value })}
                className="w-full bg-surface-container-lowest border border-outline-variant/20 rounded-xl px-4 py-3 text-sm focus:border-primary outline-none transition-all appearance-none cursor-pointer"
              >
                <option value="">Select a template...</option>
                {templates.map(t => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
              <span className="material-symbols-outlined absolute right-4 top-3.5 text-outline pointer-events-none">expand_more</span>
            </div>
          )}
        </div>

        <div className="space-y-2">
          <label className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">Custom Template Name</label>
          <input
            id="input-step4-template-name"
            type="text"
            value={config.name}
            onChange={(e) => setConfig({ name: e.target.value })}
            placeholder="e.g. MyCustomFormat"
            className="w-full bg-surface-container-lowest border border-outline-variant/20 rounded-xl px-4 py-3 text-sm focus:border-primary outline-none transition-all"
          />
        </div>
      </div>

      {/* Field Toggles */}
      <div className="space-y-3">
        <label className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">Fields to Include</label>
        <div className="grid grid-cols-2 gap-2">
          {FIELDS.map(({ key, label, desc }) => (
            <button
              key={key}
              onClick={() => toggleField(key)}
              title={desc}
              className={`flex items-center justify-between p-3 rounded-xl border-2 transition-all group ${
                config.fields[key]
                  ? 'border-primary bg-primary/10 text-primary'
                  : 'border-outline-variant/10 bg-surface-container-low text-outline hover:border-outline-variant/30'
              }`}
            >
              <div className="flex flex-col items-start text-left">
                <span className="text-xs font-black uppercase tracking-wider">{label}</span>
                <span className="text-[9px] opacity-60 font-medium">{desc}</span>
              </div>
              <div className={`w-5 h-5 rounded-full flex items-center justify-center transition-all ${
                config.fields[key] ? 'bg-primary text-on-primary' : 'bg-outline-variant/20 text-transparent group-hover:text-outline/30'
              }`}>
                <span className="material-symbols-outlined text-[14px] font-black">check</span>
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* JSON Preview */}
      <div className="space-y-2">
        <label className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">Resulting Structure Preview</label>
        <pre className="font-mono text-[10px] text-primary/80 bg-surface-container-lowest rounded-xl p-4 border border-primary/10 leading-relaxed max-h-48 overflow-y-auto custom-scrollbar shadow-inner">
          {JSON.stringify(buildPreviewTemplate(config.fields), null, 2)}
        </pre>
      </div>
    </div>
  )
}
