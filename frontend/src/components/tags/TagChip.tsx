import { TagEntry } from '../../types'
import { tagColorClass } from '../../lib/tags'

/** Colored chip for one tag entry (region → its color, module → outline). */
export function TagChip({ tag, onClick, clickable }: {
  tag: TagEntry
  clickable?: boolean
  onClick?: () => void
}) {
  const label = tag.key === 'region' ? tag.value : `#${tag.value}`
  return (
    <button
      onClick={clickable ? onClick : undefined}
      className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-[9px] font-black uppercase tracking-wider shrink-0 ${tagColorClass(tag.value, tag.key)} ${clickable ? 'cursor-pointer hover:brightness-125' : 'cursor-default'}`}
    >
      <span className="w-1.5 h-1.5 rounded-full bg-current" />
      {label}
    </button>
  )
}
