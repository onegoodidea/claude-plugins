// The session's values (\$.state, and \$.store where they last), and the
// actions on them that more than one hook takes: saving the list, opening the
// pane, editing, and the “Remove?” timer.

import { atom, read, update } from 'claude-code'

// Each file that reads or writes one of the session's values declares its own
// reference to it (the engine reads only references written in the file that
// uses them). The values themselves are declared once, in types/index.d.ts.
import type { EngineInterface, Timer } from 'claude-code'

import type { Board } from '../types'
import { EMPTY, isOpen } from './board'

export const PANE = 'checklist'
export const TITLE = 'Checklist'
export const TOOL = 'mcp__checklist__tasks'
export const CLEAR_GRACE_MS = 10 * 60 * 1000

// The values this file reads and writes (all of them: see types/index.d.ts).
const board = atom({ plugin: 'checklist', key: 'board' } as const, EMPTY)
const isPaneOpen = atom({ plugin: 'checklist', key: 'isPaneOpen' } as const, false)
const isClosedByPerson = atom({ plugin: 'checklist', key: 'isClosedByPerson' } as const, false)
const editingId = atom({ plugin: 'checklist', key: 'editingId' } as const, 0)

// Wrapping on desktop is this much wider than the cell count (a
// proportional font fits more characters than cells); `/checklist wrap`.
export const DEFAULT_WRAP_FACTOR = 1.2
// How long “Remove?” waits for a second press before it's × again.
export const REMOVE_CONFIRM_MS = 3000

// The session's store keys, from its id, read once per load.
let sessionId: string | undefined
/** A /clear goes on under a new session id: forget the old one. */
export function forgetSessionId() {
  sessionId = undefined
}

async function ensureSessionId($: EngineInterface) {
  sessionId ??= await $.session.id()
  return sessionId
}
export async function storeKey($: EngineInterface) {
  return `session:${await ensureSessionId($)}`
}
export async function closedKey($: EngineInterface) {
  return `closed:${await ensureSessionId($)}`
}

// The desktop app doesn't redraw the band when a value it read changes, so
// every change asks for a redraw too.
export function redraw($: EngineInterface) {
  $.ui.invalidate('ui.render')
}

export async function save($: EngineInterface, change: (current: Board) => Board): Promise<Board> {
  await update($, board, current => change(current))
  const after = await read($, board)
  await $.store.set(await storeKey($), after)
  redraw($)
  return after
}

export async function setPaneOpen($: EngineInterface, isOpen: boolean) {
  await update($, isPaneOpen, () => isOpen)
  redraw($)
}

export async function setClosedByPerson($: EngineInterface, isClosed: boolean) {
  await update($, isClosedByPerson, () => isClosed)
  await $.store.set(await closedKey($), isClosed)
}

export async function openPane($: EngineInterface) {
  await setClosedByPerson($, false)
  const opened = await $.ui.open({ id: PANE, title: TITLE })
  await setPaneOpen($, opened.isPlaced)
}

/** For a handler that opens the pane without waiting on it. */
export function openPaneSoon($: EngineInterface) {
  void openPane($).catch(() => undefined)
}

// Which pane held the keyboard at its last drawing, to catch the moment it
// lets go (Esc, or a click outside the pane) while an item is being edited.
const hadKeys = new Map<string, boolean>()

export async function startEditing($: EngineInterface, id: number) {
  await update($, editingId, () => id)
  redraw($)
  $.ui.focus({ requestId: PANE, key: `editing-${id}` }).catch(() => undefined)
}

export async function stopEditing($: EngineInterface) {
  await update($, editingId, () => 0)
  redraw($)
}

/**
 * Called while drawing a pane that may hold an edit field: when the pane has
 * just let go of the keyboard, cancel the edit (after the drawing, since a
 * drawing can't write state).
 */
export function cancelEditOnBlur($: EngineInterface, pane: string, isFocused: boolean, isEditing: boolean) {
  const had = hadKeys.get(pane)
  hadKeys.set(pane, isFocused)
  if (isEditing && had === true && !isFocused) $.clock.after(0, () => void stopEditing($).catch(() => undefined))
}

/**
 * Opens the pane when items are open and the person hasn't closed it. Run at
 * the session's start and again when a surface attaches: after a restart the
 * desktop app connects after the start, and an open before then goes nowhere.
 */
export async function openIfWanted($: EngineInterface) {
  // A pane opened before a surface could place it is placed when one
  // attaches: record that, so the band hides.
  const isPlaced = (await $.ui.panes()).some(pane => pane.id === PANE && pane.isPlaced)
  await setPaneOpen($, isPlaced)
  if (isPlaced) return
  const hasOpen = (await read($, board)).tasks.some(isOpen)
  if (!hasOpen || (await read($, isClosedByPerson))) return
  await openPane($)
}

/** A command can't submit a prompt while it runs, so send it just after. */
export function submitSoon($: EngineInterface, text: string) {
  $.clock.after(50, () => void $.prompt.submit({ text }).catch(() => undefined))
}

// The timer that turns “Remove?” back into ×. One at a time: a newer press
// cancels the older timer, so it can't revert the newer “Remove?” early.
let removeConfirmTimer: Timer | undefined

/** Starts the timer, cancelling any earlier one. */
export function setRemoveConfirmTimer(timer: Timer) {
  removeConfirmTimer?.cancel()
  removeConfirmTimer = timer
}

export function cancelRemoveConfirmTimer() {
  removeConfirmTimer?.cancel()
  removeConfirmTimer = undefined
}
