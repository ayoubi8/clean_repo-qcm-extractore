/**
 * Exam document type + exam-paper defaults (plan §6 UI / §7).
 *
 * - Document type: Auto (detected from origin lines), Single exam, or
 *   "QCM classé" compilation (each question preceded by
 *   "Question N° 32, Sec 01 de l'année 2021-2022").
 * - Source / Session / Year: fallbacks used only when the document itself
 *   does not say it. A Session typed here beats the header auto-detection,
 *   never a compilation's origin line.
 */
export type ExamMode = 'auto' | 'single_paper' | 'compilation'

export interface ExamPaperValues {
  exam_mode?: ExamMode
  exam_source?: string
  exam_period?: string
  exam_year?: string
}

const MODES: { id: ExamMode; label: string; hint: string }[] = [
  { id: 'auto', label: 'Auto', hint: 'Detected from the pages' },
  { id: 'single_paper', label: 'Single exam', hint: 'One exam, numbers 1..N' },
  { id: 'compilation', label: 'QCM classé', hint: 'Origin line before each question' },
]

export function ExamPaperFields({
  value,
  onChange,
  idPrefix,
}: {
  value: ExamPaperValues
  onChange: (v: Partial<ExamPaperValues>) => void
  idPrefix: string
}) {
  const mode = value.exam_mode ?? 'auto'
  const input =
    'w-full bg-surface-container-lowest border border-outline-variant/20 rounded-xl px-3 py-2.5 text-sm focus:border-primary outline-none transition-all'
  return (
    <div className="space-y-3">
      <label className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">Exam document</label>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2" role="radiogroup" aria-label="Document type">
        {MODES.map(m => (
          <button
            key={m.id}
            id={`${idPrefix}-exam-mode-${m.id}`}
            type="button"
            role="radio"
            aria-checked={mode === m.id}
            onClick={() => onChange({ exam_mode: m.id })}
            className={`text-left px-3 py-2.5 rounded-xl border-2 transition-all ${
              mode === m.id
                ? 'border-primary/50 bg-primary/5'
                : 'border-outline-variant/10 bg-surface-container-low hover:border-outline-variant/30'
            }`}
          >
            <p className={`text-xs font-bold ${mode === m.id ? 'text-primary' : 'text-on-surface'}`}>{m.label}</p>
            <p className="text-[10px] text-outline mt-0.5">{m.hint}</p>
          </button>
        ))}
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
        <input
          id={`${idPrefix}-exam-source`}
          aria-label="Exam source"
          value={value.exam_source ?? ''}
          onChange={e => onChange({ exam_source: e.target.value })}
          className={input}
          placeholder="Source (e.g. Residanat Blida)"
        />
        <input
          id={`${idPrefix}-exam-period`}
          aria-label="Exam session"
          value={value.exam_period ?? ''}
          onChange={e => onChange({ exam_period: e.target.value })}
          className={input}
          placeholder="Session (e.g. EMD1, Rattrapage)"
        />
        <input
          id={`${idPrefix}-exam-year`}
          aria-label="Exam year"
          inputMode="numeric"
          value={value.exam_year ?? ''}
          onChange={e => onChange({ exam_year: e.target.value })}
          className={input}
          placeholder="Year (e.g. 2024)"
        />
      </div>
      <p className="text-[10px] text-outline px-1">
        Optional. Used only when the PDF doesn't say it. In a QCM classé, each question keeps the
        session, year and number of its own origin line.
      </p>
    </div>
  )
}
