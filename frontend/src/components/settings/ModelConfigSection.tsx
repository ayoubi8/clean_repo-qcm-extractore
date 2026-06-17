import { useState, useEffect } from 'react';
import { fetchEnvKeysRaw, saveEnvKeys, fetchAvailableModels } from '../../lib/api';

const STEP_KEYS = [
  { label: 'Step 1 (OCR)',       keys: ['STEP1_MODEL',          'STEP1_FALLBACK_MODEL'] },
  { label: 'Step 1.5 (Fix)',     keys: ['STEP1_5_MODEL',        'STEP1_5_FALLBACK_MODEL'] },
  { label: 'Step 1.6 (Correct)', keys: ['STEP1_6_MODEL',        'STEP1_6_FALLBACK_MODEL'] },
  { label: 'Step 2 (QCM)',       keys: ['STEP2_MODEL',          'STEP2_FALLBACK_MODEL'] },
  { label: 'Step 3 (Metadata)',  keys: ['STEP3_MODEL',          'STEP3_FALLBACK_MODEL'] },
  { label: 'Step 6 (Text)',      keys: ['STEP6_TEXT_MODEL',     'STEP6_TEXT_FALLBACK_MODEL'] },
  { label: 'Step 6 (Vision)',    keys: ['STEP6_ALL_PAGES_MODEL'] },
  { label: 'Step 6 (Reasoning)', keys: ['STEP6_AI_MODEL'] },
  { label: 'Step 7 (Category)',  keys: ['STEP7_MODEL',          'STEP7_FALLBACK_MODEL'] },
];

/** Derives the available-list key from a model env key, e.g. STEP1_MODEL → step1_available */
function getAvailKey(modelKey: string): string {
  return modelKey.toLowerCase().replace('_model', '_available');
}

export function ModelConfigSection() {
  const [env,             setEnv]             = useState<Record<string, string>>({});
  const [availableModels, setAvailableModels] = useState<Record<string, string[]>>({});
  /** Keys whose current value is not in the approved list and need a free-text override */
  const [customMode,      setCustomMode]      = useState<Record<string, boolean>>({});
  const [loading,         setLoading]         = useState(true);
  const [saving,          setSaving]          = useState(false);
  const [status,          setStatus]          = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        const [envData, availData] = await Promise.all([
          fetchEnvKeysRaw(),
          fetchAvailableModels(),
        ]);
        setEnv(envData);
        setAvailableModels(availData);

        // Pre-compute custom mode: a key needs custom mode when its saved value
        // is not in the approved list for that key.
        const initCustom: Record<string, boolean> = {};
        STEP_KEYS.forEach(group => {
          group.keys.forEach(key => {
            const list = availData[getAvailKey(key)] ?? [];
            const val  = envData[key] ?? '';
            if (list.length > 0 && val && !list.includes(val)) {
              initCustom[key] = true;
            }
          });
        });
        setCustomMode(initCustom);
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
      const updates: Record<string, string> = {};
      STEP_KEYS.forEach(group => {
        group.keys.forEach(key => {
          if (env[key]) updates[key] = env[key];
        });
      });
      await saveEnvKeys(updates);
      setStatus('Models updated successfully!');
      setTimeout(() => setStatus(null), 3000);
    } catch {
      setStatus('Failed to save model configuration.');
    } finally {
      setSaving(false);
    }
  };

  /** Smart dropdown + optional custom text input for one env key */
  function ModelField({ envKey, isFallback }: { envKey: string; isFallback?: boolean }) {
    const availList  = availableModels[getAvailKey(envKey)] ?? [];
    const currentVal = env[envKey] ?? '';
    const isCustom   = customMode[envKey] ?? false;

    // When no curated list exists, show a plain text input (original behaviour)
    if (availList.length === 0) {
      return (
        <input
          type="text"
          value={currentVal}
          onChange={e => setEnv({ ...env, [envKey]: e.target.value })}
          className={`w-full bg-surface-container-lowest border border-outline-variant/10 rounded-xl px-4 py-2.5 text-xs focus:border-primary outline-none transition-all tabular-nums font-mono ${isFallback ? 'opacity-80 focus:opacity-100' : ''}`}
          placeholder={isFallback ? 'Fallback ID...' : 'e.g. google/gemini-pro'}
        />
      );
    }

    // Determine what the <select> should show as selected
    const selectVal = isCustom || !availList.includes(currentVal)
      ? '__custom__'
      : currentVal;

    return (
      <div className="space-y-1.5">
        {/* --- Dropdown -------------------------------------------------- */}
        <select
          value={selectVal}
          onChange={e => {
            if (e.target.value === '__custom__') {
              setCustomMode({ ...customMode, [envKey]: true });
            } else {
              setCustomMode({ ...customMode, [envKey]: false });
              setEnv({ ...env, [envKey]: e.target.value });
            }
          }}
          className="w-full bg-surface-container-lowest border border-outline-variant/10 rounded-xl px-4 py-2.5 text-xs focus:border-primary outline-none transition-all font-mono cursor-pointer"
        >
          {availList.map(m => (
            <option key={m} value={m}>{m}</option>
          ))}
          <option value="__custom__">✏️ Custom model ID...</option>
        </select>

        {/* --- Custom free-text override (shown only when "Custom" chosen) -- */}
        {(isCustom || selectVal === '__custom__') && (
          <input
            type="text"
            autoFocus
            value={currentVal}
            onChange={e => setEnv({ ...env, [envKey]: e.target.value })}
            className="w-full bg-surface-container-lowest border border-primary/40 rounded-xl px-4 py-2 text-xs focus:border-primary outline-none transition-all tabular-nums font-mono"
            placeholder="Enter custom model ID..."
          />
        )}

        {/* --- Status badge ---------------------------------------------- */}
        {selectVal !== '__custom__' && (
          <p className="text-[9px] text-primary font-semibold">✓ Approved model selected</p>
        )}
      </div>
    );
  }

  if (loading) return null;

  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      <div className="space-y-1">
        <h2 className="text-xl font-black text-on-surface tracking-tight">Model Configuration</h2>
        <p className="text-[11px] text-outline font-medium uppercase tracking-[0.1em]">
          Assign LLMs to specific pipeline stages
        </p>
      </div>

      <div className="bg-surface-container-low rounded-3xl border border-outline-variant/10 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm border-collapse">
            <thead>
              <tr className="border-b border-outline-variant/10 bg-surface-container">
                <th className="px-6 py-4 text-[10px] font-black uppercase tracking-widest text-outline">
                  Pipeline Step
                </th>
                <th className="px-6 py-4 text-[10px] font-black uppercase tracking-widest text-outline">
                  Primary Model
                </th>
                <th className="px-6 py-4 text-[10px] font-black uppercase tracking-widest text-outline">
                  Fallback Model
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-outline-variant/5">
              {STEP_KEYS.map(group => (
                <tr key={group.label} className="hover:bg-surface-container-highest/30 transition-colors">
                  <td className="px-6 py-5 font-bold text-on-surface-variant whitespace-nowrap">
                    {group.label}
                  </td>
                  <td className="px-6 py-4">
                    <ModelField envKey={group.keys[0]} />
                  </td>
                  <td className="px-6 py-4">
                    {group.keys[1] && <ModelField envKey={group.keys[1]} isFallback />}
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
          <p className="text-[10px] text-outline">
            Updates the .env file and reloads the backend process environment.
          </p>
        </div>
        <div className="flex items-center gap-4">
          {status && (
            <span className={`text-xs font-bold animate-in fade-in slide-in-from-right-2 ${
              status.includes('Failed') ? 'text-error' : 'text-primary'
            }`}>
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
