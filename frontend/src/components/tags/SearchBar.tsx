import { TagEntry } from '../../types'
import { REGION_TAGS } from '../../lib/tags'

/** Inline search + tag chip filter row (Tags & Search plan §4.3).
 *  Controlled: `query` + `activeTags` live in the parent so the same filter
 *  can drive both the project list and the batch history rows. */
export function SearchBar({ query, onQueryChange, activeTags, onToggleTag, onClear }: {
  query: string
  onQueryChange: (q: string) => void
  activeTags: TagEntry[]
  onToggleTag: (t: TagEntry) => void
  onClear: () => void
}) {
  const isTagActive = (key: string, value: string) =>
    activeTags.some(t => t.key === key && t.value === value)

  return (
    <div className="space-y-2">
      <div className="relative">
        <span className="material-symbols-outlined text-[16px] text-outline absolute left-3 top-1/2 -translate-y-1/2">search</span>
        <input
          id="tag-search-input"
          value={query}
          onChange={(e) => onQueryChange(e.target.value)}
          placeholder="Search by name…"
          className="w-full pl-9 pr-8 py-2.5 text-sm font-medium text-on-surface placeholder:text-outline bg-surface-container-low border border-outline-variant/30 rounded-xl outline-none focus:border-primary/50 transition-colors"
        />
        {(query || activeTags.length > 0) && (
          <button
            id="tag-search-clear"
            onClick={onClear}
            title="Clear search + filters"
            className="absolute right-2 top-1/2 -translate-y-1/2 w-6 h-6 rounded-full hover:bg-surface-container-highest flex items-center justify-center text-outline"
          >
            <span className="material-symbols-outlined text-[14px]">close</span>
          </button>
        )}
      </div>
      {/* Tag filter chips — click to toggle an AND filter */}
      <div className="flex items-center gap-2 px-1">
        <span className="text-[10px] font-black uppercase tracking-[0.2em] text-outline">Tags</span>
        <div className="flex gap-1.5">
          {REGION_TAGS.map(t => (
            <button
              key={t.value}
              onClick={() => onToggleTag({ key: 'region', value: t.value })}
              className={`px-1.5 py-0.5 rounded border text-[9px] font-black uppercase tracking-wider ${isTagActive('region', t.value) ? 'border-current' : 'opacity-40 hover:opacity-100'}`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
