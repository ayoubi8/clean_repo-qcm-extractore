import { useState, useEffect } from 'react'
import { fetchEnvKeys, fetchEnvKeysRaw, saveEnvKeys } from '../../lib/api'
import { EnvKeys } from '../../types'
import { ToggleSwitch } from '../autorun/ToggleSwitch'

function ApiKeyInput({ label, value, onChange, envVar }: { label: string, value: string, onChange: (v: string) => void, envVar: string }) {
  const [show, setShow] = useState(false)
  const [rawValue, setRawValue] = useState('')

  const handleToggle = async () => {
    if (!show) {
      try {
        const raw = await fetchEnvKeysRaw()
        setRawValue(raw[envVar] || value)
      } catch (e) {
        console.error("Failed to fetch raw key", e)
      }
    }
    setShow(!show)
  }

  return (
    <div className="space-y-2">
      <label className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">{label}</label>
      <div className="relative group">
        <input
          type={show ? 'text' : 'password'}
          value={show ? rawValue : value}
          onChange={(e) => {
            const v = e.target.value
            if (show) setRawValue(v)
            onChange(v)
          }}
          className="w-full bg-surface-container-lowest border border-outline-variant/20 rounded-xl px-4 py-3 text-sm font-mono focus:border-primary outline-none transition-all group-hover:border-outline-variant/40"
        />
        <button
          onClick={handleToggle}
          className="absolute right-3 top-2.5 text-outline hover:text-on-surface transition-colors"
        >
          <span className="material-symbols-outlined text-[20px]">{show ? 'visibility_off' : 'visibility'}</span>
        </button>
      </div>
      <p className="text-[10px] text-outline italic">Environment Variable: <code className="bg-surface-container-highest px-1 rounded">{envVar}</code></p>
    </div>
  )
}

export function ApiKeysSection() {
  const [keys, setKeys] = useState<EnvKeys | null>(null)
  const [originalKeys, setOriginalKeys] = useState<EnvKeys | null>(null)
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')

  useEffect(() => {
    async function load() {
      try {
        const data = await fetchEnvKeys()
        setKeys(data)
        setOriginalKeys(data)
      } catch (e) {
        console.error(e)
      }
    }
    load()
  }, [])

  const handleSave = async () => {
    if (!keys || !originalKeys) return
    setSaveStatus('saving')
    const changed = Object.fromEntries(
      Object.entries(keys).filter(([k, v]) => v !== (originalKeys as any)[k])
    )
    try {
      await saveEnvKeys(changed)
      setSaveStatus('saved')
      setOriginalKeys(keys)
      setTimeout(() => setSaveStatus('idle'), 3000)
    } catch (e) {
      setSaveStatus('error')
    }
  }

  if (!keys) return <div className="h-40 bg-surface-container-low animate-pulse rounded-2xl" />

  const isDirty = JSON.stringify(keys) !== JSON.stringify(originalKeys)

  return (
    <section className="space-y-8 animate-in fade-in duration-500">
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center border border-primary/20">
          <span className="material-symbols-outlined text-primary">key</span>
        </div>
        <div>
          <h3 className="text-lg font-black text-on-surface">API & Environment</h3>
          <p className="text-xs text-outline">Manage your connectivity and processing keys</p>
        </div>
      </div>

      <div className="space-y-6 bg-surface-container-low p-8 rounded-2xl border border-outline-variant/10 shadow-xl">
        <ApiKeyInput 
          label="OpenRouter API Key" 
          envVar="OPENROUTER_API_KEY" 
          value={keys.OPENROUTER_API_KEY}
          onChange={(v) => setKeys({...keys, OPENROUTER_API_KEY: v})}
        />

        <div className="flex items-center justify-between py-4 border-t border-outline-variant/10 mt-4">
          <div>
            <p className="text-sm font-bold text-on-surface">Response Caching</p>
            <p className="text-[11px] text-outline">Cache AI responses to save tokens and time.</p>
          </div>
          <ToggleSwitch
            id="toggle-enable-caching"
            checked={keys.ENABLE_CACHING === 'true'}
            onChange={(v) => setKeys({...keys, ENABLE_CACHING: v ? 'true' : 'false'})}
          />
        </div>

        <div className="pt-4 flex items-center justify-between">
          <p className="text-[10px] text-outline max-w-[240px]">Keys are saved to the <code className="bg-surface-container-highest px-1 rounded">.env</code> file in the backend root.</p>
          <button
            id="btn-save-env"
            onClick={handleSave}
            disabled={!isDirty || saveStatus === 'saving'}
            className={`px-8 py-3 rounded-xl text-xs font-black uppercase tracking-widest transition-all ${
              isDirty 
                ? 'bg-primary text-on-primary shadow-lg shadow-primary/20 hover:scale-105 active:scale-95' 
                : 'bg-surface-container-highest text-outline cursor-not-allowed'
            }`}
          >
            {saveStatus === 'saving' ? 'Saving...' : saveStatus === 'saved' ? '✓ Saved' : 'Save Keys'}
          </button>
        </div>
      </div>


    </section>
  )
}
