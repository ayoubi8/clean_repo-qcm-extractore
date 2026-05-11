import { ApiKeysSection } from '../components/settings/ApiKeysSection'
import { YamlEditorSection } from '../components/settings/YamlEditorSection'
import { ModelConfigSection } from '../components/settings/ModelConfigSection'

function PageHeader({ title, subtitle }: { title: string, subtitle: string }) {
  return (
    <div className="mb-12 border-b border-outline-variant/10 pb-8">
      <h1 className="text-4xl font-black text-on-surface tracking-tighter mb-2">{title}</h1>
      <p className="text-sm text-outline font-medium">{subtitle}</p>
    </div>
  )
}

export function Settings() {
  return (
    <div className="max-w-4xl mx-auto px-8 py-12 pb-32 animate-in fade-in slide-in-from-bottom-4 duration-700">
      <PageHeader 
        title="System Settings" 
        subtitle="Global environment keys, model configurations, and batch processing rules." 
      />

      <div className="space-y-20">
        <ApiKeysSection />
        
        <div className="h-px bg-gradient-to-r from-transparent via-outline-variant/20 to-transparent" />
        
        <ModelConfigSection />

        <div className="h-px bg-gradient-to-r from-transparent via-outline-variant/20 to-transparent" />
        
        <YamlEditorSection />
      </div>
    </div>
  )
}
