// The Checklist mod's hooks: they wire the session, the tool, the commands,
// the pane, and the band to the pieces in board.ts, state.ts, and pane.tsx.

import { atom, read, update } from 'claude-code'
import type { Register } from 'claude-code'

import type { GroupRow } from '../types'
import { EMPTY, addTask, applyTasks, describe, isOpen, normalize, reorder, summary } from './board'
import type { TasksInput } from './board'
import { drawPane } from './pane'
import { DESCRIPTION, GUIDANCE, INPUT_SCHEMA, REVIEW_PROMPT } from './prompts'
import {
  CLEAR_GRACE_MS,
  DEFAULT_WRAP_FACTOR,
  PANE,
  TOOL,
  cancelRemoveConfirmTimer,
  closedKey,
  forgetSessionId,
  openIfWanted,
  openPane,
  openPaneSoon,
  redraw,
  save,
  setClosedByPerson,
  setPaneOpen,
  startEditing,
  stopEditing,
  storeKey,
  submitSoon,
} from './state'

// This file's references to the session's values (see state.ts).
const board = atom({ plugin: 'checklist', key: 'board' } as const, EMPTY)
const isPaneOpen = atom({ plugin: 'checklist', key: 'isPaneOpen' } as const, false)
const clearWarnedAt = atom({ plugin: 'checklist', key: 'clearWarnedAt' } as const, 0)
const isClosedByPerson = atom({ plugin: 'checklist', key: 'isClosedByPerson' } as const, false)
const groupRows = atom({ plugin: 'checklist', key: 'groupRows' } as const, {})
const wrapFactor = atom({ plugin: 'checklist', key: 'wrapFactor' } as const, DEFAULT_WRAP_FACTOR)
const confirmingRemoveId = atom({ plugin: 'checklist', key: 'confirmingRemoveId' } as const, 0)
const editingId = atom({ plugin: 'checklist', key: 'editingId' } as const, 0)

// Matchers name tools and the pane literally, so the engine can read them
// from the source (the tool's equals TOOL, the pane's PANE).
export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    // The tool and command first: nothing loaded below can keep them away.
    await $.tool.register({
      name: 'tasks',
      description: DESCRIPTION,
      inputSchema: INPUT_SCHEMA,
      isDeferred: false,
    })
    await $.command.register({
      name: 'checklist',
      description: 'Show this session’s checklist; “review” walks through the open items',
      argumentHint: '[review | wrap <factor>]',
    })

    try {
      const savedFactor = await $.store.get('wrapFactor')
      if (typeof savedFactor === 'number') await update($, wrapFactor, () => savedFactor)
      const saved = normalize(await $.store.get(await storeKey($)))
      if (saved !== undefined) await update($, board, () => saved)
      const closed = await $.store.get(await closedKey($))
      await update($, isClosedByPerson, () => closed === true)
      await openIfWanted($)
    } catch {
      // A saved value that can't be read: start from an empty list.
    }

    return next(e)
  })

  on('session.attach', async ($, e, next) => {
    await openIfWanted($)
    return next(e)
  }).catch(($, e, next) => next(e))

  // A /clear starts a new conversation in the same process: start the list over.
  on('session.end', async ($, e, next) => {
    if (e.reason === 'clear') {
      // Ids start over at 1, so nothing may still point at an old one.
      await update($, board, () => EMPTY)
      await update($, clearWarnedAt, () => 0)
      await update($, editingId, () => 0)
      await update($, confirmingRemoveId, () => 0)
      await update($, groupRows, () => ({}))
      cancelRemoveConfirmTimer()
      forgetSessionId()
    }
    return next(e)
  })

  on('command.run', { command: 'checklist' }, async ($, e) => {
    const wrap = e.args.trim().match(/^wrap(?:\s+(\S+))?$/)
    if (wrap !== null) {
      const factor = Number(wrap[1])
      if (wrap[1] === undefined || !Number.isFinite(factor) || factor < 0.5 || factor > 2) {
        return { text: `Wrap factor is ${await read($, wrapFactor)}. Set it with /checklist wrap <0.5 to 2>; higher fits more on a line.` }
      }
      await update($, wrapFactor, () => factor)
      await $.store.set('wrapFactor', factor)
      redraw($)
      return { text: `Wrap factor set to ${factor}.` }
    }
    const args = e.args.trim()
    if (args === 'review') {
      if (!(await read($, board)).tasks.some(isOpen)) return { text: 'Nothing open to review.' }
      submitSoon($, REVIEW_PROMPT)
      return { text: 'Reviewing the open checklist items.' }
    }
    if (args !== '') {
      return { text: 'Usage: /checklist (opens the pane), /checklist review, or /checklist wrap <factor>.' }
    }
    await openPane($)
    return { text: 'Checklist opened.' }
  })

  // Before a /clear throws the list away, review what's open. A second /clear
  // within a few minutes goes through.
  on('command.run', { command: 'clear' }, async ($, e, next) => {
    const open = (await read($, board)).tasks.filter(isOpen)
    const now = await $.clock.now()
    if (open.length === 0 || now - (await read($, clearWarnedAt)) < CLEAR_GRACE_MS) {
      return next(e)
    }
    await update($, clearWarnedAt, () => now)
    submitSoon(
      $,
      `${REVIEW_PROMPT} I'm about to run /clear, which empties the list, so this is the last chance to keep anything.`,
    )
    return {
      text: `${open.length} open checklist ${open.length === 1 ? 'item' : 'items'}. Reviewing ${open.length === 1 ? 'it' : 'them'} first; run /clear again afterward to clear.`,
    }
  }).catch(($, e, next) => next(e))

  on('ui.close', async ($, e, next) => {
    if (e.id === PANE) {
      if (e.origin.kind === 'person') await setClosedByPerson($, true)
      await setPaneOpen($, false)
    }
    return next(e)
  }).catch(($, e, next) => next(e))

  on('prompt.compose', async ($, e, next) => {
    const composed = await next(e)
    if (!e.tools.includes(TOOL)) return composed
    return {
      sections: [
        ...composed.sections,
        { id: 'checklist:guidance', text: GUIDANCE, scope: 'session' as const },
      ],
    }
  })

  // The mod's own tool.
  on('tool.call', { tool: 'mcp__checklist__tasks' }, async ($, e) => {
    const input = e as unknown as TasksInput
    const wasEmpty = !(await read($, board)).tasks.some(isOpen)
    let notes: string[] = []
    const after = await save($, current => {
      const applied = applyTasks(current, input)
      notes = applied.notes
      return applied.next
    })
    // The first open item opens the pane, even one the person closed.
    if (wasEmpty && after.tasks.some(isOpen) && !(await read($, isPaneOpen))) openPaneSoon($)

    return { result: [...notes, describe(after.tasks)].join('\n') }
  })

  // New task cards become proposed items, and dismissing one removes its item.
  // Starting one leaves the item where it is: the work runs in another session.
  on('tool.call', { tool: 'mcp__ccd_session__start_session' }, async ($, e, next) => {
    const ran = await next(e)
    if (ran.deny !== undefined || ran.isError === true) return ran
    const input = e as unknown as { initiation?: string; title?: string }

    if (input.initiation === 'own_initiative' && input.title) {
      const cardId = JSON.stringify(ran.result ?? ran.text ?? '').match(/\btask_(?!id\b)[A-Za-z0-9]+/)?.[0]
      const title = input.title
      await save($, current => addTask(current, title, 'proposed', cardId))
    }
    return ran
  }).catch(($, e, next) => next(e))

  on('tool.call', { tool: 'mcp__ccd_session__dismiss_task' }, async ($, e, next) => {
    const ran = await next(e)
    const id = (e as unknown as { task_id?: string }).task_id
    if (id !== undefined && ran.deny === undefined && ran.isError !== true) {
      await save($, current => ({ ...current, tasks: current.tasks.filter(task => task.cardId !== id) }))
    }
    return ran
  }).catch(($, e, next) => next(e))

  on('ui.render', { component: 'Pane', requestId: 'checklist' }, ($, e) => drawPane($, e))

  // From a group's list element: the rows its items take, a double-click to
  // edit an item, a drop to move one (Up next).
  on('ui.message', { requestId: 'checklist' }, async ($, e) => {
    const message = e.data as { kind?: string; group?: string; id?: number; to?: number; rows?: unknown }
    if (message.kind === 'layout') {
      const { group, rows } = message
      if (typeof group === 'string' && Array.isArray(rows)) {
        await update($, groupRows, all => ({ ...all, [group]: rows as GroupRow[] }))
        redraw($)
      }
      return {}
    }
    const id = message.id
    if (typeof id !== 'number') return {}
    if (message.kind === 'edit') {
      await startEditing($, id)
    } else if (message.kind === 'move' && message.group === 'next' && typeof message.to === 'number') {
      const to = message.to
      await save($, current => {
        const ids = current.tasks.filter(task => task.status === 'next' && task.id !== id).map(task => task.id)
        ids.splice(Math.max(0, Math.min(ids.length, to)), 0, id)
        return reorder(current, ids)
      })
    }
    return {}
  })

  // While an item is edited, the focus moving to anything but its field
  // (Tab, a click on a button, the pane's close mark) cancels the edit.
  on('ui.focus', { requestId: 'checklist' }, async ($, e, next) => {
    const editing = await read($, editingId)
    if (editing !== 0 && e.element !== `editing-${editing}`) await stopEditing($)
    return next(e)
  }).catch(($, e, next) => next(e))

  // The band above the prompt, shown only while the pane is closed.
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.props.hasSurvey || (await read($, isPaneOpen))) return next(e)
    const { tasks } = await read($, board)
    if (!tasks.some(isOpen)) return next(e)

    const { Button, Text } = $.ui.resolve(e)
    return (
      <Button key="open-checklist" plain onPress={() => openPaneSoon($)}>
        Checklist: <Text dimColor>{summary(tasks)}</Text>
      </Button>
    )
  })
}
