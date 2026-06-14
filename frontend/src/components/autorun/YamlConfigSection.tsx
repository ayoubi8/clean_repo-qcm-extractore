import { useAutorunStore } from '../../store/autorunStore'
import { fetchBatchConfig } from '../../lib/api'
import { ToggleSwitch } from './ToggleSwitch'

function SyntaxHighlightedJson({ value }: { value: any }) {
  const json = JSON.stringify(value, null, 2)
  
  // Simple regex-based syntax highlighting
  const highlighted = json
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g, (match) => {
      let cls = 'text-secondary' // Number/Boolean
      if (/^"/.test(match)) {
        if (/:$/.test(match)) {
          cls = 'text-tertiary' // Key
        } else {
          cls = 'text-primary' // String
        }
      } else if (/true|false/.test(match)) {
        cls = 'text-secondary'
      } else if (/null/.test(match)) {
        cls = 'text-outline'
      }
      return `<span class="${cls}">${match}</span>`
    })

  return (
    <pre 
      className="p-4 text-[11px] font-mono text-on-surface-variant overflow-auto max-h-64 leading-relaxed custom-scrollbar"
      dangerouslySetInnerHTML={{ __html: highlighted }}
    />
  )
}

export function YamlConfigSection() {
  const useYaml = useAutorunStore(s => s.useYaml)
  const batchConfig = useAutorunStore(s => s.batchConfig)
  const yamlLoading = useAutorunStore(s => s.yamlLoading)
  const yamlError = useAutorunStore(s => s.yamlError)
  const setUseYaml = useAutorunStore(s => s.setUseYaml)
  const setBatchConfig = useAutorunStore(s => s.setBatchConfig)
  const setYamlLoading = useAutorunStore(s => s.setYamlLoading)
  const setYamlError = useAutorunStore(s => s.setYamlError)

  const onToggle = async (enabled: boolean) => {
    setUseYaml(enabled)
    if (enabled && !batchConfig) {
      setYamlLoading(true)
      setYamlError(null)
      try {
        const cfg = await fetchBatchConfig()
        setBatchConfig(cfg)
      } catch (e) {
        setYamlError('Could not load batch_config.yaml')
        setUseYaml(false)
      } finally {
        setYamlLoading(false)
      }
    }
  }

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-bold text-on-surface">Load from batch_config.yaml</p>
          <p className="text-[11px] text-outline mt-0.5 font-medium leading-tight">
            Use predefined production settings from the file system.
          </p>
        </div>
        <ToggleSwitch 
          id="toggle-use-yaml"
          checked={useYaml} 
          onChange={onToggle} 
        />
      </div>

      {useYaml && (
        <div className="bg-surface-container-lowest border border-outline-variant/20 rounded-xl overflow-hidden animate-in zoom-in-95 duration-300">
          <div className="flex items-center justify-between px-4 py-2 bg-surface-container-high border-b border-outline-variant/10">
            <span className="text-[9px] uppercase tracking-[0.2em] text-outline font-black">batch_config.yaml</span>
            <span className="text-[9px] text-primary font-black uppercase tracking-widest px-2 py-0.5 bg-primary/10 rounded">Read-Only</span>
          </div>
          
          {yamlLoading ? (
            <div className="p-6 space-y-3">
              {[...Array(5)].map((_, i) => (
                <div key={i} className={`h-2 bg-surface-container-high rounded animate-pulse ${i % 2 === 0 ? 'w-1/3' : 'w-2/3'}`} />
              ))}
            </div>
          ) : yamlError ? (
            <div className="p-6 text-center">
              <span className="material-symbols-outlined text-error mb-2">error</span>
              <p className="text-xs text-error font-bold">{yamlError}</p>
            </div>
          ) : (
            <SyntaxHighlightedJson value={batchConfig} />
          )}
        </div>
      )}
    </section>
  )
}
