import { useState, useEffect } from 'react'
import Editor from '@monaco-editor/react'
import { fetchBatchConfig, saveBatchConfig } from '../../lib/api'

export function YamlEditorSection() {
  const [yamlContent, setYamlContent] = useState<string>('')
  const [originalContent, setOriginalContent] = useState<string>('')
  const [isDirty, setIsDirty] = useState(false)
  const [status, setStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      if (isDirty) {
        e.preventDefault()
        e.returnValue = ''
      }
    }
    window.addEventListener('beforeunload', handleBeforeUnload)
    return () => window.removeEventListener('beforeunload', handleBeforeUnload)
  }, [isDirty])

  useEffect(() => {
    async function load() {
      try {
        const data = await fetchBatchConfig()
        const yaml = JSON.stringify(data, null, 2) // In real app, this would be raw YAML string
        setYamlContent(yaml)
        setOriginalContent(yaml)
      } catch (e) {
        console.error(e)
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  const handleSave = async () => {
    setStatus('saving')
    try {
      await saveBatchConfig(yamlContent)
      setStatus('saved')
      setOriginalContent(yamlContent)
      setIsDirty(false)
      setTimeout(() => setStatus('idle'), 3000)
    } catch (e) {
      setStatus('error')
    }
  }

  const handleReset = () => {
    setYamlContent(originalContent)
    setIsDirty(false)
  }

  if (loading) return <div className="h-64 bg-surface-container-low animate-pulse rounded-2xl" />

  return (
    <section className="space-y-8 animate-in fade-in duration-500 delay-100">
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center border border-primary/20">
          <span className="material-symbols-outlined text-primary">settings_applications</span>
        </div>
        <div>
          <h3 className="text-lg font-black text-on-surface">Batch Configuration</h3>
          <p className="text-xs text-outline">Directly edit <code className="bg-surface-container-highest px-1 rounded">batch_config.yaml</code></p>
        </div>
      </div>

      <div className="rounded-2xl overflow-hidden border border-outline-variant/20 h-[560px] bg-surface-container-lowest flex flex-col shadow-2xl">
        <div className="flex items-center justify-between px-6 py-3 bg-surface-container-high border-b border-outline-variant/10">
          <div className="flex items-center gap-4">
            <span className="text-[10px] uppercase tracking-[0.2em] text-outline font-black">YAML EDITOR</span>
            {isDirty && (
              <span className="flex items-center gap-1.5 text-[10px] text-tertiary font-black uppercase tracking-widest animate-pulse">
                <span className="w-1.5 h-1.5 rounded-full bg-tertiary" />
                Unsaved Changes
              </span>
            )}
          </div>
          <button
            onClick={handleReset}
            className="text-[10px] text-outline hover:text-on-surface font-black uppercase tracking-widest transition-colors flex items-center gap-1.5"
          >
            <span className="material-symbols-outlined text-[16px]">restart_alt</span>
            Reset
          </button>
        </div>

        <div className="flex-1">
          <Editor
            height="100%"
            defaultLanguage="json" // backend stub returns JSON for now
            value={yamlContent}
            onChange={(v) => { setYamlContent(v ?? ''); setIsDirty(v !== originalContent) }}
            theme="vs-dark"
            options={{
              minimap: { enabled: false },
              fontSize: 13,
              fontFamily: 'JetBrains Mono, monospace',
              lineNumbers: 'on',
              scrollBeyondLastLine: false,
              padding: { top: 20, bottom: 20 },
              smoothScrolling: true,
              cursorBlinking: 'smooth',
              cursorSmoothCaretAnimation: 'on',
              fontLigatures: true,
              renderLineHighlight: 'all',
              backgroundColor: '#0e0e0e'
            }}
          />
        </div>
      </div>

      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-[10px] text-outline">
          <span className="material-symbols-outlined text-sm">info</span>
          <p>These settings are used by the Auto Run system. Changes are persistent.</p>
        </div>
        <button
          id="btn-save-yaml"
          onClick={handleSave}
          disabled={!isDirty || status === 'saving'}
          className={`px-10 py-3.5 rounded-xl text-xs font-black uppercase tracking-widest transition-all ${
            isDirty 
              ? 'bg-primary text-on-primary shadow-[0_4px_20px_rgba(76,215,246,0.3)] hover:scale-105 active:scale-95' 
              : 'bg-surface-container-highest text-outline cursor-not-allowed'
          }`}
        >
          {status === 'saving' ? 'Saving...' : status === 'saved' ? '✓ Config Saved' : 'Save Configuration'}
        </button>
      </div>
    </section>
  )
}
