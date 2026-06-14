import { useState, useEffect } from 'react';
import { fetchEnvKeysRaw, saveEnvKeys, fetchAvailableModels } from '../../lib/api';

const STEP_KEYS = [
  { label: 'Step 1 (OCR)', keys: ['STEP1_MODEL', 'STEP1_FALLBACK_MODEL'] },
  { label: 'Step 1.5 (Fix)', keys: ['STEP1_5_MODEL', 'STEP1_5_FALLBACK_MODEL'] },
  { label: 'Step 1.6 (Correct)', keys: ['STEP1_6_MODEL', 'STEP1_6_FALLBACK_MODEL'] },
  { label: 'Step 2 (QCM)', keys: ['STEP2_MODEL', 'STEP2_FALLBACK_MODEL'] },
  { label: 'Step 3 (Metadata)', keys: ['STEP3_MODEL', 'STEP3_FALLBACK_MODEL'] },
  { label: 'Step 6 (Text)', keys: ['STEP6_TEXT_MODEL', 'STEP6_TEXT_FALLBACK_MODEL'] },
  { label: 'Step 6 (Vision)', keys: ['STEP6_ALL_PAGES_MODEL'] },
  { label: 'Step 6 (Reasoning)', keys: ['STEP6_AI_MODEL'] },
  { label: 'Step 7 (Category)', keys: ['STEP7_MODEL', 'STEP7_FALLBACK_MODEL'] },
];

export function ModelConfigSection() {
  const [env, setEnv] = useState<Record<string, string>>({});
  const [availableModels, setAvailableModels] = useState<Record<string, string[]>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        const [envData, availData] = await Promise.all([
          fetchEnvKeysRaw(),
          fetchAvailableModels()
        ]);
        setEnv(envData);
        setAvailableModels(availData);
      } catch (err) {
        console.error(err);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  const handleSave = async () => {
    setSaving(true);
    setStatus(null);
    try {
      // Filter to only step keys
      const updates: Record<string, string> = {};
      STEP_KEYS.forEach(group => {
        group.keys.forEach(key => {
          if (env[key]) updates[key] = env[key];
        });
      });

      await saveEnvKeys(updates);
      setStatus('Models updated successfully!');
      setTimeout(() => setStatus(null), 3000);
    } catch (err) {
      setStatus('Failed to save model configuration.');
    } finally {
      setSaving(false);
    }
  };

  if (loading) return null;

  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      <div className="space-y-1">
        <h2 className="text-xl font-black text-on-surface tracking-tight">Model Configuration</h2>
        <p className="text-[11px] text-outline font-medium uppercase tracking-[0.1em]">Assign LLMs to specific pipeline stages</p>
      </div>

      <div className="bg-surface-container-low rounded-3xl border border-outline-variant/10 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm border-collapse">
            <thead>
              <tr className="border-b border-outline-variant/10 bg-surface-container">
                <th className="px-6 py-4 text-[10px] font-black uppercase tracking-widest text-outline">Pipeline Step</th>
                <th className="px-6 py-4 text-[10px] font-black uppercase tracking-widest text-outline">Primary Model ID</th>
                <th className="px-6 py-4 text-[10px] font-black uppercase tracking-widest text-outline">Fallback Model ID</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-outline-variant/5">
              {STEP_KEYS.map((group) => (
                <tr key={group.label} className="hover:bg-surface-container-highest/30 transition-colors">
                  <td className="px-6 py-5 font-bold text-on-surface-variant whitespace-nowrap">{group.label}</td>
                  <td className="px-6 py-4">
                    <input
                      type="text"
                      value={env[group.keys[0]] || ''}
                      onChange={(e) => setEnv({ ...env, [group.keys[0]]: e.target.value })}
                      className="w-full bg-surface-container-lowest border border-outline-variant/10 rounded-xl px-4 py-2.5 text-xs focus:border-primary outline-none transition-all tabular-nums font-mono"
                      placeholder="e.g. google/gemini-pro"
                    />
                    {(() => {
                      const availKey = group.keys[0].toLowerCase().replace('_model', '_available');
                      const availList = availableModels[availKey] || [];
                      const isKnown = availList.includes(env[group.keys[0]] || '');
                      return availList.length > 0 && (
                        <p className="text-[9px] text-outline mt-1 truncate">
                          {isKnown ? '✓ In approved list' : availList.length + ' options in admin.env'}
                        </p>
                      );
                    })()}
                  </td>
                  <td className="px-6 py-4">
                    {group.keys[1] && (
                      <>
                        <input
                          type="text"
                          value={env[group.keys[1]] || ''}
                          onChange={(e) => setEnv({ ...env, [group.keys[1]]: e.target.value })}
                          className="w-full bg-surface-container-lowest border border-outline-variant/10 rounded-xl px-4 py-2.5 text-xs focus:border-primary outline-none transition-all tabular-nums font-mono opacity-80 focus:opacity-100"
                          placeholder="Fallback ID..."
                        />
                        {(() => {
                          const availKey = group.keys[1].toLowerCase().replace('_model', '_available');
                          const availList = availableModels[availKey] || [];
                          const isKnown = availList.includes(env[group.keys[1]] || '');
                          return availList.length > 0 && (
                            <p className="text-[9px] text-outline mt-1 truncate">
                              {isKnown ? '✓ In approved list' : availList.length + ' options in admin.env'}
                            </p>
                          );
                        })()}
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="flex items-center justify-between gap-4 bg-surface-container-lowest p-6 rounded-2xl border border-outline-variant/10">
        <div>
          <p className="text-xs font-bold text-on-surface">Apply Changes</p>
          <p className="text-[10px] text-outline">This will update the .env file and reload the backend process environment.</p>
        </div>
        <div className="flex items-center gap-4">
          {status && (
            <span className={`text-xs font-bold animate-in fade-in slide-in-from-right-2 ${status.includes('Failed') ? 'text-error' : 'text-primary'}`}>
              {status}
            </span>
          )}
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-8 py-3 bg-on-surface text-surface rounded-full font-black uppercase tracking-widest text-[10px] hover:scale-105 active:scale-95 disabled:opacity-50 transition-all shadow-xl shadow-surface-container-highest"
          >
            {saving ? 'Updating...' : 'Save Models'}
          </button>
        </div>
      </div>
    </div>
  );
}
