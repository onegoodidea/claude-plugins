/** One reading of the context window, as the strip draws it. */
export type Reading = {
  /** tokens / window, 0 to 100; absent before the first response. */
  percent?: number
  /** Where auto-compact starts, as a percentage of the window; absent when unknown. */
  compactAt?: number
}

/** The part of the checklist mod's state the strip reads (it never writes it). */
export type ChecklistBoard = {
  tasks: { status: 'proposed' | 'next' | 'in_progress' | 'done' }[]
}

declare module 'claude-code' {
  interface PluginState {
    'context-strip': { reading: Reading | null }
  }
}
