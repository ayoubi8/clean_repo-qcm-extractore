import { memo, useEffect, useMemo, useRef, useState } from 'react'
import { usePipelineStore } from '../../store/pipelineStore'
import { useAppStore } from '../../store/appStore'
import { LogLine } from '../../types'

/**
 * Maps log line text to Tailwind classes based on content prefix.
 * Preserves the beautiful terminal output from the original pipeline.
 */
function getLogLineStyle(text: string): string {
  // CC Checker & Summary enhancements (must sit ABOVE the generic ✅/▶
  // rules so checker-specific lines get their own styling).
  if (/\[CC-CHECK\].*▶\s*Starting/.test(text))                     return 'text-tertiary font-bold tracking-wide'
  if (/\[CC-CHECK\]\s*\[CAS\s*\d+\]/.test(text))                   return 'text-tertiary font-bold'
  if (/\[CC-CHECK\].*✅\s*Done/.test(text))                         return 'text-green-400 font-medium'
  if (/❓\s*provisional/.test(text))                                return 'text-yellow-400/80 italic'
  if (/⛔\s*Two consecutive/.test(text))                            return 'text-error font-bold'
  if (/📊 CLINICAL CASE VERIFICATION & EXTRACTION SUMMARY/.test(text)) return 'text-tertiary font-black'
  if (/Total QCMs extracted:/.test(text))                          return 'text-primary font-bold'
  if (/Total Clinical Cases:/.test(text))                          return 'text-cyan-400 font-bold'
  if (/QCMs with Case:/.test(text))                                return 'text-secondary font-medium'
  if (/QCMs without Case:/.test(text))                             return 'text-on-surface-variant font-medium'
  if (/🔹\s*Case\s*\d+:/.test(text))                               return 'pl-2 text-cyan-300 font-mono text-[11px]'
  if (/✅|^\[OK\]|\[SUCCESS\]/.test(text))             return 'text-green-400'
  if (/❌|\[ERROR\]/.test(text))                        return 'text-red-400'
  // Phase 1 — Clinical Case Checker lines (must sit ABOVE the generic ⚠️
  // rule so the checker's error marker gets error styling, not warning).
  if (/\[CC-CHECK\].*ERROR/.test(text))                 return 'text-error font-bold'
  if (/\[CC-CHECK\]/.test(text))                        return 'text-tertiary'
  if (/📊 CLINICAL CASE VERIFICATION SUMMARY/.test(text)) return 'text-tertiary font-bold'
  if (/⚠️|\[WARN\]/.test(text))                        return 'text-yellow-400'
  if (/📦\s*Chunk|🔁\s*AUTO/.test(text))               return 'text-primary font-bold'
  if (/💾|\[SAVE\]/.test(text))                         return 'text-primary'
  if (/\[INTEGRITY\]/.test(text))                       return 'text-cyan-400'
  if (/\[MERGE\]/.test(text))                           return 'text-cyan-400/80'
  if (/\[API\]/.test(text))                             return 'text-outline'
  if (/\[INFO\]/.test(text))                            return 'text-on-surface-variant'
  if (/Q\d+:/.test(text))                              return 'pl-4 text-on-surface-variant font-mono text-[11px]'
  if (/📊.*CAS CLINIQUE SUMMARY/.test(text))   return 'text-tertiary font-bold'
  if (/📋.*CC triggered/.test(text))            return 'text-tertiary font-bold'
  if (/[↩↪]/.test(text))                       return 'text-outline italic'
  if (/ℹ️/.test(text))                          return 'text-outline/60'
  if (/📑/.test(text))                           return 'text-primary'
  if (/\[CAS\s*\d+\]/.test(text))              return 'text-tertiary font-bold'
  if (/[├└]─/.test(text))                      return 'text-outline/70 pl-4 font-mono text-[11px]'
  if (/🔍/.test(text))                          return 'text-cyan-400'
  if (/\[STEP4\]/.test(text))              return 'text-primary font-medium'
  if (/\[AUTO\].*template/i.test(text))    return 'text-primary'
  if (/🔧.*CUSTOM TEMPLATE/.test(text))    return 'text-tertiary font-bold'
  if (/✨.*Generated Template/.test(text)) return 'text-tertiary'
  if (/♻️/.test(text))                             return 'text-yellow-500'
  if (/📊\s*Status/.test(text))                    return 'text-primary font-medium'
  if (/🌐.*all_pages/.test(text))                  return 'text-cyan-400 font-bold'
  if (/📋\s*Candidate pages/.test(text))           return 'text-tertiary font-bold'
  if (/✨$|✨\s*$/.test(text) && /Page/.test(text)) return 'text-primary/80 font-mono text-[11px]'
  if (/↔️.*neighbor/.test(text))                   return 'text-outline/60 italic font-mono text-[11px]'
  if (/🤖\s*Sending/.test(text))                   return 'text-primary font-bold'
  if (/💰\s*API call cost/.test(text))             return 'text-outline/60 text-[10px]'
  if (/\[all_pages\]/.test(text))                  return 'text-primary'
  if (/🧠\s*AI Knowledge/.test(text))              return 'text-secondary font-bold'
  if (/Solving batch/.test(text))                  return 'text-on-surface-variant'
  if (/♻️|Force-overwrite/.test(text))             return 'text-yellow-500/80'
  if (/STEP 8/.test(text))                       return 'text-primary font-black tracking-wide'
  if (/🔍.*Auto-detected/.test(text))            return 'text-cyan-400 font-bold'
  if (/📄\s*Source:/.test(text))                 return 'text-primary font-medium'
  if (/📚\s*Reference:/.test(text))              return 'text-secondary font-medium'
  if (/🚀\s*Matching/.test(text))               return 'text-tertiary font-bold'
  if (/🚀\s*Weighted/.test(text))               return 'text-tertiary font-bold'
  if (/💾\s*JSON/.test(text))                   return 'text-primary'
  if (/📊\s*XLSX/.test(text))                   return 'text-primary'
  if (/📊\s*Summary/.test(text))               return 'text-primary'
  if (/✅\s*Step 8 Complete/.test(text))        return 'text-tertiary font-black'
  if (/🟢\s*High/.test(text))                  return 'text-green-400 font-bold'
  if (/🟡\s*Medium/.test(text))               return 'text-yellow-400 font-bold'
  if (/🔴\s*Low/.test(text))                   return 'text-red-400 font-bold'
  if (/📈\s*Average/.test(text))               return 'text-primary font-medium'
  if (/❌\s*No source/.test(text))             return 'text-error font-bold'
  if (/❌\s*Reference DB/.test(text))          return 'text-error font-bold'
  if (/⚙️/.test(text))                          return 'text-on-surface font-medium'
  if (/Global Values set/.test(text))           return 'text-primary'
  if (/^[=═]{3,}/.test(text.trim()))               return 'text-outline/40 text-[10px]'
  if (/^\[PAGE-STAMP\]/.test(text))                    return 'text-yellow-400/70'
  if (/^\[SANITIZE\]/.test(text))                      return 'text-yellow-400/70'
  if (/📄|📋/.test(text))                               return 'text-on-surface font-medium'
  if (/✨/.test(text))                                  return 'text-tertiary'
  if (/▶\s*Starting/.test(text))                       return 'text-primary font-bold tracking-wide'
  return 'text-on-surface-variant'
}

// ── Execution log panel (redesign 2026-11) ─────────────────────────────────
// Resizable / collapsible / maximisable; level filters with live counts;
// search; follow-tail that pauses when you scroll up; copy + download.
// Colour rules above are unchanged.

type Level = 'error' | 'warn' | 'ok' | 'info'
type Filter = 'all' | 'warn' | 'error'

// Level and style are computed once per line object (lines are immutable).
const LEVEL_CACHE = new WeakMap<LogLine, Level>()
const STYLE_CACHE = new WeakMap<LogLine, string>()
const ID_CACHE = new WeakMap<LogLine, number>()
let nextLineId = 0
/** Stable key per line: survives the front-trimming of the capped log. */
function idOf(line: LogLine): number {
  let id = ID_CACHE.get(line)
  if (id === undefined) { id = ++nextLineId; ID_CACHE.set(line, id) }
  return id
}

function levelOf(line: LogLine): Level {
  const hit = LEVEL_CACHE.get(line)
  if (hit) return hit
  let lvl: Level = 'info'
  if (line.type === 'error' || /❌|\[ERROR\]|⛔|\bERROR\b|Traceback/.test(line.text)) lvl = 'error'
  else if (line.type === 'warn' || /⚠️|\[WARN\]/.test(line.text)) lvl = 'warn'
  else if (line.type === 'ok' || /✅|\[OK\]|\[SUCCESS\]/.test(line.text)) lvl = 'ok'
  LEVEL_CACHE.set(line, lvl)
  return lvl
}

function styleOf(line: LogLine): string {
  const hit = STYLE_CACHE.get(line)
  if (hit !== undefined) return hit
  const style = line.type === 'info'
    ? getLogLineStyle(line.text)
    : ({ ok: 'text-green-400', warn: 'text-yellow-400', error: 'text-red-400' } as Record<string, string>)[line.type] ?? 'text-on-surface-variant'
  STYLE_CACHE.set(line, style)
  return style
}

const GUTTER: Record<Level, string> = {
  error: 'bg-red-400',
  warn: 'bg-yellow-400/80',
  ok: 'bg-green-400/60',
  info: 'bg-transparent',
}

const LogLineRow = memo(function LogLineRow({ line, fresh }: { line: LogLine; fresh: boolean }) {
  const lvl = levelOf(line)
  return (
    <div className={`group flex gap-3 pl-2 pr-3 py-[1px] rounded hover:bg-white/[0.03] leading-relaxed ${fresh ? 'qe-fade-up' : ''}`}>
      <span className={`w-[2px] shrink-0 rounded-full ${GUTTER[lvl]}`} />
      <span className="text-outline-variant/70 shrink-0 tabular-nums select-none group-hover:text-outline">{line.ts}</span>
      <span className={`${styleOf(line)} break-all whitespace-pre-wrap`}>{line.text}</span>
    </div>
  )
})

const HEIGHT_KEY = 'qe-log-height'
const MIN_H = 120
const COLLAPSED_H = 40

function readHeight(): number {
  try {
    const v = Number(localStorage.getItem(HEIGHT_KEY))
    return Number.isFinite(v) && v >= MIN_H ? v : 220
  } catch {
    return 220
  }
}

function saveHeight(h: number) {
  try { localStorage.setItem(HEIGHT_KEY, String(Math.round(h))) } catch { /* storage unavailable */ }
}

function stamp(): string {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}`
}

export function TerminalLog() {
  const logLines = usePipelineStore(s => s.logLines)
  const clearLog = usePipelineStore(s => s.clearLog)
  const running = useAppStore(s => s.pipelineStatus === 'running')
  const projectName = useAppStore(s => s.activeProject?.name ?? 'project')

  const [height, setHeight] = useState<number>(readHeight)
  const [collapsed, setCollapsed] = useState(false)
  const [maximized, setMaximized] = useState(false)
  const [filter, setFilter] = useState<Filter>('all')
  const [query, setQuery] = useState('')
  const [follow, setFollow] = useState(true)
  const [unseen, setUnseen] = useState(0)
  const [copied, setCopied] = useState(false)

  const scrollRef = useRef<HTMLDivElement>(null)
  const lastLen = useRef(logLines.length)

  // Counts per level (cached per line → cheap on every append).
  const counts = useMemo(() => {
    let warn = 0, error = 0
    for (const l of logLines) {
      const lv = levelOf(l)
      if (lv === 'error') error++
      else if (lv === 'warn') warn++
    }
    return { warn, error }
  }, [logLines])

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (filter === 'all' && !q) return logLines
    return logLines.filter(l => {
      const lv = levelOf(l)
      if (filter === 'error' && lv !== 'error') return false
      if (filter === 'warn' && lv !== 'warn' && lv !== 'error') return false
      return !q || l.text.toLowerCase().includes(q)
    })
  }, [logLines, filter, query])

  // Follow the tail; count lines that arrive while the user reads above.
  useEffect(() => {
    const added = logLines.length - lastLen.current
    lastLen.current = logLines.length
    if (logLines.length === 0) { setUnseen(0); return }
    const el = scrollRef.current
    if (follow && el) {
      el.scrollTop = el.scrollHeight
    } else if (added > 0) {
      setUnseen(u => u + added)
    }
  }, [logLines, follow])

  useEffect(() => {
    // Filter / search changes: show the newest matches.
    const el = scrollRef.current
    if (el && follow) el.scrollTop = el.scrollHeight
  }, [filter, query]) // eslint-disable-line react-hooks/exhaustive-deps

  const onScroll = () => {
    const el = scrollRef.current
    if (!el) return
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 32
    if (atBottom !== follow) setFollow(atBottom)
    if (atBottom) setUnseen(0)
  }

  const jumpToLatest = () => {
    const el = scrollRef.current
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
    setFollow(true)
    setUnseen(0)
  }

  // Drag the top edge to resize.
  const startResize = (e: React.PointerEvent) => {
    e.preventDefault()
    const startY = e.clientY
    const startH = height
    const maxH = Math.round(window.innerHeight * 0.75)
    let latest = startH
    const move = (ev: PointerEvent) => {
      latest = Math.min(maxH, Math.max(MIN_H, startH + (startY - ev.clientY)))
      setHeight(latest)
    }
    const up = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
      saveHeight(latest)
    }
    setCollapsed(false)
    setMaximized(false)
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }

  const asText = () => logLines.map(l => `[${l.ts}] ${l.text}`).join('\n')

  const copyAll = async () => {
    try {
      await navigator.clipboard.writeText(asText())
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch { /* clipboard blocked */ }
  }

  const download = () => {
    const url = URL.createObjectURL(new Blob([asText()], { type: 'text/plain;charset=utf-8' }))
    const a = document.createElement('a')
    a.href = url
    a.download = `${projectName}_log_${stamp()}.log`
    a.click()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  }

  const panelH = collapsed ? COLLAPSED_H : maximized ? Math.round(window.innerHeight * 0.7) : height
  const newest = logLines[logLines.length - 1]
  const freshFrom = visible.length - 12

  const chip = (id: Filter, label: string, count: number | null, tone: string) => (
    <button
      key={id}
      onClick={() => setFilter(id)}
      aria-pressed={filter === id}
      className={`flex items-center gap-1.5 h-6 px-2 rounded-md text-[10px] font-bold transition-colors ${
        filter === id ? 'bg-surface-container-highest text-on-surface' : 'text-outline hover:text-on-surface'
      }`}
    >
      {label}
      {count !== null && (
        <span className={`min-w-[18px] px-1 rounded tabular-nums text-[9px] ${count > 0 ? tone : 'bg-outline-variant/30 text-outline'}`}>
          {count > 999 ? '999+' : count}
        </span>
      )}
    </button>
  )

  const iconBtn = (id: string, icon: string, title: string, onClick: () => void, active = false) => (
    <button
      id={id}
      onClick={onClick}
      title={title}
      aria-label={title}
      className={`w-7 h-7 rounded-md flex items-center justify-center transition-colors ${
        active ? 'text-primary bg-primary/10' : 'text-outline hover:text-on-surface hover:bg-surface-container-highest'
      }`}
    >
      <span className="material-symbols-outlined text-[16px]">{icon}</span>
    </button>
  )

  return (
    <section
      aria-label="Execution log"
      style={{ height: panelH }}
      className="relative shrink-0 bg-surface-container-lowest border-t border-outline-variant/15 flex flex-col font-mono text-xs shadow-[0_-6px_24px_rgba(0,0,0,0.45)] z-10 transition-[height] duration-200 ease-out"
    >
      {/* Resize handle */}
      <div
        onPointerDown={startResize}
        onDoubleClick={() => setMaximized(m => !m)}
        title="Drag to resize · double-click to maximise"
        className="absolute -top-1.5 left-0 right-0 h-3 cursor-row-resize group z-20"
      >
        <div className="mx-auto mt-1 w-12 h-1 rounded-full bg-outline-variant/40 group-hover:bg-primary/60 transition-colors" />
      </div>

      {/* Header */}
      <div className="flex items-center gap-3 px-3 h-10 shrink-0 bg-surface-container-high/80 backdrop-blur border-b border-outline-variant/10 font-sans">
        <div className="flex items-center gap-2 min-w-0">
          <span className="material-symbols-outlined text-[18px] text-primary">terminal</span>
          <span className="text-[10px] uppercase tracking-[0.18em] text-on-surface font-black">Execution log</span>
          {running ? (
            <span className="flex items-center gap-1 px-1.5 h-5 rounded-md bg-primary/10 text-primary text-[9px] font-black tracking-widest">
              <span className="w-1.5 h-1.5 rounded-full bg-primary qe-blink" /> LIVE
            </span>
          ) : (
            <span className="text-[10px] text-outline tabular-nums">{logLines.length.toLocaleString()} lines</span>
          )}
        </div>

        {collapsed ? (
          <button onClick={() => setCollapsed(false)} className="flex-1 min-w-0 text-left text-[11px] text-outline truncate font-mono hover:text-on-surface">
            {newest ? newest.text : 'No output yet'}
          </button>
        ) : (
          <>
            <div className="flex items-center gap-0.5 ml-1">
              {chip('all', 'All', null, '')}
              {chip('warn', 'Warnings', counts.warn, 'bg-yellow-400/20 text-yellow-300')}
              {chip('error', 'Errors', counts.error, 'bg-red-400/20 text-red-300')}
            </div>
            <div className="flex-1" />
            <label className="hidden md:flex items-center gap-1.5 h-7 px-2 rounded-md bg-surface-container-lowest border border-outline-variant/20 focus-within:border-primary/50 transition-colors">
              <span className="material-symbols-outlined text-[15px] text-outline">search</span>
              <input
                id="input-log-search"
                value={query}
                onChange={e => setQuery(e.target.value)}
                placeholder="Filter log…"
                className="w-36 bg-transparent outline-none text-[11px] text-on-surface placeholder:text-outline/60"
              />
              {query && (
                <button onClick={() => setQuery('')} aria-label="Clear search" className="text-outline hover:text-on-surface">
                  <span className="material-symbols-outlined text-[14px]">close</span>
                </button>
              )}
            </label>
          </>
        )}

        <div className="flex items-center gap-0.5 shrink-0">
          {!collapsed && iconBtn('btn-log-follow', follow ? 'vertical_align_bottom' : 'pause_circle', follow ? 'Following new lines (scroll up to pause)' : 'Paused — click to follow', jumpToLatest, follow)}
          {!collapsed && iconBtn('btn-log-copy', copied ? 'check' : 'content_copy', copied ? 'Copied' : 'Copy log', copyAll, copied)}
          {!collapsed && iconBtn('btn-log-download', 'download', 'Download .log', download)}
          {!collapsed && (
            <button
              id="btn-clear-log"
              onClick={clearLog}
              title="Clear log"
              className="h-7 px-2 rounded-md text-outline hover:text-error hover:bg-error/10 text-[10px] uppercase font-bold tracking-wider transition-colors"
            >
              Clear
            </button>
          )}
          {iconBtn('btn-log-maximize', maximized ? 'close_fullscreen' : 'open_in_full', maximized ? 'Restore size' : 'Maximise', () => { setCollapsed(false); setMaximized(m => !m) })}
          {iconBtn('btn-log-collapse', collapsed ? 'expand_less' : 'expand_more', collapsed ? 'Show log' : 'Hide log', () => setCollapsed(c => !c))}
        </div>
      </div>

      {/* Lines */}
      {!collapsed && (
        <div className="relative flex-1 min-h-0">
          <div
            ref={scrollRef}
            onScroll={onScroll}
            role="log"
            aria-live="polite"
            className="h-full overflow-y-auto py-2 pl-1 pr-2 space-y-0 custom-scrollbar"
          >
            {visible.map((l, i) => (
              <LogLineRow key={idOf(l)} line={l} fresh={follow && i >= freshFrom} />
            ))}
            {logLines.length === 0 && (
              <div className="h-full flex flex-col items-center justify-center gap-2 text-outline/60 font-sans">
                <span className="material-symbols-outlined text-[28px]">receipt_long</span>
                <span className="text-[11px]">No output yet. Run a step to see its log here.</span>
              </div>
            )}
            {logLines.length > 0 && visible.length === 0 && (
              <div className="py-6 text-center text-outline/60 font-sans text-[11px]">No line matches this filter.</div>
            )}
          </div>

          {!follow && unseen > 0 && (
            <button
              onClick={jumpToLatest}
              className="absolute bottom-3 left-1/2 -translate-x-1/2 flex items-center gap-1.5 h-7 px-3 rounded-full bg-primary text-on-primary text-[10px] font-black font-sans shadow-[0_4px_16px_rgba(0,0,0,0.5)] qe-fade-up"
            >
              <span className="material-symbols-outlined text-[15px]">arrow_downward</span>
              {unseen > 999 ? '999+' : unseen} new line{unseen === 1 ? '' : 's'}
            </button>
          )}
        </div>
      )}
    </section>
  )
}
