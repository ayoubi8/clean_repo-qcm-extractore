import { useAutorunStore } from '../../store/autorunStore'

interface StepPickerProps {
  label: string
  value: number
  onChange: (n: number) => void
  min: number
  max: number
  id: string
}

function StepPicker({ label, value, onChange, min, max, id }: StepPickerProps) {
  const options = Array.from({ length: 8 }, (_, i) => i + 1).filter(n => n >= min && n <= max)

  return (
    <div className="flex-1 space-y-1">
      <p className="text-[10px] text-outline font-bold uppercase tracking-tighter">{label}</p>
      <select
        id={id}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full bg-surface-container-lowest border-b border-outline-variant/30 text-on-surface text-sm py-2 px-1 focus:border-primary outline-none transition-colors appearance-none cursor-pointer font-bold"
      >
        {options.map(n => (
          <option key={n} value={n}>Step {n}</option>
        ))}
      </select>
    </div>
  )
}

export function StepRangeSelector({ disabled }: { disabled?: boolean }) {
  const startStep = useAutorunStore(s => s.startStep)
  const endStep = useAutorunStore(s => s.endStep)
  const setStartStep = useAutorunStore(s => s.setStartStep)
  const setEndStep = useAutorunStore(s => s.setEndStep)

  return (
    <section className={`space-y-4 ${disabled ? 'opacity-40 pointer-events-none' : ''}`}>
      <label className="text-[10px] uppercase tracking-widest text-outline font-black block">
        Execution Range
      </label>
      <div className="flex items-center gap-4 bg-surface-container-low p-4 rounded-xl border border-outline-variant/5 shadow-inner">
        <StepPicker
          id="select-start-step"
          label="From"
          value={startStep}
          onChange={setStartStep}
          min={1}
          max={endStep}
        />
        <span className="material-symbols-outlined text-outline mt-4 opacity-30">arrow_forward</span>
        <StepPicker
          id="select-end-step"
          label="To"
          value={endStep}
          onChange={(n) => {
            setEndStep(n)
            if (n < startStep) setStartStep(n)
          }}
          min={1}
          max={8}
        />
      </div>
      {startStep > endStep && (
        <p className="text-error text-[10px] font-bold uppercase tracking-tight">Error: Start must be ≤ End</p>
      )}
    </section>
  )
}
