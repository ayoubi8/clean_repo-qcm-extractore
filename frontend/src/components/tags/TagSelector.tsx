import { useEffect, useState } from 'react'
import { TagEntry } from '../../types'
import { REGION_TAGS, regionTag } from '../../lib/tags'
import { fetchEnvTags, addModuleTag, EnvTags } from '../../lib/api'

/** Forced tag selection (Tags & Search plan §4.2): a required region
 *  (oran/mosta/tlemcen, colored) + an optional module tag (free text with
 *  autocomplete over previously saved module tags). */
export function TagSelector({ tags, onChange }: {
  tags: TagEntry[]            // the current selection (region required)
  onChange: (tags: TagEntry[]) => void
}) {
  const [env, setEnv] = useState<EnvTags | null>(null)
  const [moduleDraft, setModuleDraft] = useState(moduleTag)

  useEffect(() => {
    fetchEnvTags().then(setEnv).catch(() => setEnv({ region: REGION_TAGS, modules: [] }))
  }, [])

  useEffect(() => { setModuleDraft(moduleTag) }, [moduleTag])

  const region = tags.find(t => t.key === 'region')?.value ?? ''
  const moduleTag = tags.find(t => t.key === 'module')?.value ?? ''
  const modules = env?.modules ?? []
  const isRegionPicked = !!region

  function pickRegion(value: string) {
    const next = tags.filter(t => t.key !== 'region')
    next.unshift(regionTag(value))
    onChange(next)
  }
  function pickModule(value: string) {
    const next = tags.filter(t => t.key !== 'module')
    if (value.trim()) {
      next.push({ key: 'module', value: value.trim().slice(0, 60).toLowerCase() })
    }
    onChange(next)
  }
  function saveModule(value: string) {
    const clean = value.trim().slice(0, 60).toLowerCase()
    if (!clean) return
    pickModule(clean)
    // If it's NOT an existing known module, persist it for future reuse.
    if (!modules.includes(clean)) {
      addModuleTag(clean)
        .then(() => setEnv(prev => prev ? { ...prev, modules: [...prev.modules, clean].sort() } : prev))
        .catch(() => { })
    }
  }

  const colorCls: Record<string, string> = {
    orange: 'text-orange-500 border-orange-500/40 bg-orange-500/10',
    green: 'text-emerald-500 border-emerald-500/40 bg-emerald-500/10',
    brown: 'text-amber-700 border-amber-700/40 bg-amber-700/10',
  }

  return (
    <div className="space-y-3">
      <div>
        <p className="text-[10px] font-black uppercase tracking-[0.2em] text-outline mb-2">
          Wilaya tag <span className="text-error">*</span>
        </p>
        <div className="flex gap-2">
          {REGION_TAGS.map(t => {
            const active = region === t.value
            return (
              <button
                key={t.value}
                id={`tag-region-${t.value}`}
                onClick={() => pickRegion(t.value)}
                className={`flex-1 py-2.5 rounded-xl border text-xs font-black uppercase tracking-wider transition-all ${colorCls[t.color]} ${
                  active ? 'brightness-125 ring-1 ring-current' : 'opacity-40 hover:opacity-80'
                }`}
              >
                {t.label}
              </button>
            )
          })}
        </div>
        {!region && (
          <p className="text-[10px] text-error mt-1.5 font-bold">Select a wilaya to continue.</p>
        )}
      </div>
      <div>
        <p className="text-[10px] font-black uppercase tracking-[0.2em] text-outline mb-2">
          Module tag <span className="text-outline/50 normal-case tracking-normal">(optional)</span>
        </p>
        <input
          id="tag-module-input"
          list="tag-module-options"
          value={moduleDraft}
          placeholder="e.g. anatomie"
          onChange={(e) => setModuleDraft(e.target.value)}
          onBlur={(e) => saveModule(e.target.value)}
          className="w-full py-2.5 px-3 text-sm font-medium bg-surface-container-low border border-outline-variant/30 rounded-xl outline-none focus:border-primary/50 text-on-surface"
        />
        <datalist id="tag-module-options">
          {modules.map(m => <option key={m} value={m} />)}
        </datalist>
      </div>
    </div>
  )
}

export function hasRegionSelection(tags: TagEntry[]): boolean {
  return tags.some(t => t.key === 'region')
}
