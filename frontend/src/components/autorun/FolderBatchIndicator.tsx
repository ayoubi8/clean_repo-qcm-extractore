interface FolderBatchIndicatorProps {
  config: {
    input_folder: string
    file_pattern: string
    output_base: string
  }
}

export function FolderBatchIndicator({ config }: FolderBatchIndicatorProps) {
  return (
    <div className="bg-secondary-container/10 border border-secondary/30 rounded-xl p-5 flex items-start gap-4 animate-in slide-in-from-top-2 duration-300">
      <div className="w-10 h-10 rounded-full bg-secondary/10 flex items-center justify-center shrink-0">
        <span className="material-symbols-outlined text-secondary">folder_managed</span>
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-[10px] font-black text-secondary uppercase tracking-[0.2em] mb-1">
          Folder Batch Mode Active
        </p>
        <p className="text-xs text-on-surface-variant leading-relaxed font-medium">
          Sequential processing of all matches in the source directory.
          Execution range and pre-flight settings are overridden.
        </p>
        
        <div className="mt-4 space-y-2 bg-surface-container-lowest/50 p-3 rounded-lg border border-outline-variant/10">
          <div className="flex items-center gap-2 text-[10px] font-mono text-outline">
            <span className="material-symbols-outlined text-sm">folder</span>
            <span className="truncate">{config.input_folder}</span>
          </div>
          <div className="flex items-center gap-4 text-[10px] font-mono text-outline">
            <div className="flex items-center gap-1">
              <span className="material-symbols-outlined text-sm">filter_list</span>
              {config.file_pattern}
            </div>
            <div className="flex items-center gap-1">
              <span className="material-symbols-outlined text-sm">output</span>
              {config.output_base}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
