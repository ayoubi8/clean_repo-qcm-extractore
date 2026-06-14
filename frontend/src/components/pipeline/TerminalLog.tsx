import { useEffect, useRef } from 'react'
import { usePipelineStore } from '../../store/pipelineStore'
import { LogLine } from '../../types'

/**
 * Maps log line text to Tailwind classes based on content prefix.
 * Preserves the beautiful terminal output from the original pipeline.
 */
function getLogLineStyle(text: string): string {
  if (/✅|^\[OK\]|\[SUCCESS\]/.test(text))             return 'text-green-400'
  if (/❌|\[ERROR\]/.test(text))                        return 'text-red-400'
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

function LogLineRow({ line }: { line: LogLine }) {
  // Use content-based style for backend logs (type=info carries all real pipeline output)
  const style = line.type === 'info'
    ? getLogLineStyle(line.text)
    : {
        ok:    'text-green-400',
        warn:  'text-yellow-400',
        error: 'text-red-400',
      }[line.type] ?? 'text-on-surface-variant'

  return (
    <div className="flex gap-3 leading-relaxed">
      <span className="text-outline-variant/60 shrink-0 tabular-nums">[{line.ts}]</span>
      <span className={`${style} break-all whitespace-pre-wrap`}>
        {line.text}
      </span>
    </div>
  )
}

export function TerminalLog() {
  const logLines = usePipelineStore(s => s.logLines)
  const clearLog  = usePipelineStore(s => s.clearLog)
  const scrollRef = useRef<HTMLDivElement>(null)

  // Auto-scroll to bottom on new lines
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [logLines.length])

  return (
    <div className="h-48 bg-surface-container-lowest border-t border-outline-variant/10 flex flex-col font-mono text-xs shadow-[0_-4px_20px_rgba(0,0,0,0.4)] z-10">

      {/* Header bar */}
      <div className="flex items-center justify-between px-4 py-2 bg-surface-container-high border-b border-outline-variant/10">
        <div className="flex gap-1.5">
          <div className="w-2.5 h-2.5 rounded-full bg-error/40" />
          <div className="w-2.5 h-2.5 rounded-full bg-tertiary/40" />
          <div className="w-2.5 h-2.5 rounded-full bg-primary/40" />
        </div>
        <span className="text-[9px] uppercase tracking-widest text-outline font-bold">
          execution_log
        </span>
        <button
          id="btn-clear-log"
          onClick={clearLog}
          className="text-outline hover:text-on-surface text-[10px] uppercase font-bold tracking-tighter transition-colors"
        >
          Clear
        </button>
      </div>

      {/* Log lines */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto p-4 space-y-0.5 custom-scrollbar"
      >
        {logLines.map((l, i) => (
          <LogLineRow key={i} line={l} />
        ))}
        {logLines.length === 0 && (
          <span className="text-outline/50 italic">No output yet. Run a step to see logs.</span>
        )}
      </div>
    </div>
  )
}
