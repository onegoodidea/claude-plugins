/** proposed: Claude suggested it, you haven't accepted. next: accepted, not started. */
export type TaskStatus = 'proposed' | 'next' | 'in_progress' | 'done'

export type Task = {
  id: number
  text: string
  status: TaskStatus
  /** The New task card this item mirrors, when it came from one. */
  cardId?: string
  /** When it was marked done (ms since the epoch), for Done's order. */
  doneAt?: number
}

export type Board = { tasks: Task[]; nextId: number }

/** How many rows an item takes in its group's list element, as it reports them. */
export type GroupRow = { id: number; lines: number; isGap: boolean }

declare module 'claude-code' {
  interface PluginState {
    'checklist': {
      /** The list, saved per session in the store. */
      board: Board
      /** Whether a surface has the pane placed; the band shows while it doesn't. */
      isPaneOpen: boolean
      /** When /clear last asked for a review first (ms), for its grace period. */
      clearWarnedAt: number
      /** The person closed the pane: it stays closed (the band leads back), across restarts too. */
      isClosedByPerson: boolean
      /** Bumped on each add from the pane, so the field is drawn anew and empty. */
      addCount: number
      /** The item being edited in the pane; 0 for none. */
      editingId: number
      /** The item whose × now asks “Remove?”; 0 for none. */
      confirmingRemoveId: number
      /** How much wider than the cell count lines wrap on desktop. */
      wrapFactor: number
      /** The rows each item takes in its list element, by list, as it last reported. */
      groupRows: Record<string, GroupRow[]>
    }
  }
}
