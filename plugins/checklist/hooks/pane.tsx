// Drawing the Checklist pane: its groups (Now, Up next, Proposed, Done), each
// drawn by a list element (./list.tsx) with the pane's own circles and buttons
// beside it, the add field under Up next, and the empty-list message.

import { atom, read, update } from 'claude-code'
import type { EngineInterface, RenderChildren, RenderInput } from 'claude-code'

import type { GroupRow, Task, TaskStatus } from '../types'
import { EMPTY, addTask, isOpen, newestDone, nudge, reorder, setStatus } from './board'
import { ALT, GLYPH, ICON } from './look'
import {
  DEFAULT_WRAP_FACTOR,
  PANE,
  REMOVE_CONFIRM_MS,
  cancelEditOnBlur,
  cancelRemoveConfirmTimer,
  redraw,
  save,
  setRemoveConfirmTimer,
  stopEditing,
} from './state'

// This file's references to the session's values (see state.ts).
const board = atom({ plugin: 'checklist', key: 'board' } as const, EMPTY)
const groupRows = atom({ plugin: 'checklist', key: 'groupRows' } as const, {})
const wrapFactor = atom({ plugin: 'checklist', key: 'wrapFactor' } as const, DEFAULT_WRAP_FACTOR)
const addCount = atom({ plugin: 'checklist', key: 'addCount' } as const, 0)
const confirmingRemoveId = atom({ plugin: 'checklist', key: 'confirmingRemoveId' } as const, 0)
const editingId = atom({ plugin: 'checklist', key: 'editingId' } as const, 0)

export async function drawPane($: EngineInterface, e: RenderInput<'Pane'>) {
  const { Box, Button, Text } = $.ui.resolve(e)
  const [{ tasks }, editing, confirming, reportedRows, factor, count] = await Promise.all([
    read($, board),
    read($, editingId),
    read($, confirmingRemoveId),
    read($, groupRows),
    read($, wrapFactor),
    read($, addCount),
  ])
  cancelEditOnBlur($, PANE, e.props.isFocused, editing !== 0)
  // Where the surface draws list elements (terminal, desktop), groups are
  // drawn by them; mobile has none, nor text fields.
  const hasLists = e.surface === 'terminal' || e.surface === 'desktop'

  const of = (status: TaskStatus) => tasks.filter(task => task.status === status)
  const upNext = of('next')
  const done = newestDone(tasks)

  const action = (key: string, text: string, press: () => unknown) => (
    <Button key={key} label={text} plain dimColor onPress={press} />
  )

  // × asks first: one press turns it into “Remove?”, a second removes the
  // item. Left alone, it goes back to × after a few seconds.
  const removeButton = (id: number) =>
    action(`remove-${id}`, confirming === id ? 'Remove?' : '×', async () => {
      cancelRemoveConfirmTimer()
      if ((await read($, confirmingRemoveId)) === id) {
        await update($, confirmingRemoveId, () => 0)
        await save($, current => ({ ...current, tasks: current.tasks.filter(one => one.id !== id) }))
        return
      }
      await update($, confirmingRemoveId, () => id)
      redraw($)
      setRemoveConfirmTimer(
        $.clock.after(REMOVE_CONFIRM_MS, () => {
          void (async () => {
            if ((await read($, confirmingRemoveId)) !== id) return
            await update($, confirmingRemoveId, () => 0)
            redraw($)
          })().catch(() => undefined)
        }),
      )
    })

  // Each item's buttons, by its status.
  const buttonsFor = (status: TaskStatus, id: number): RenderChildren => [
    status === 'proposed' && action(`accept-${id}`, 'Accept', () => save($, current => setStatus(current, id, 'next'))),
    status === 'next' &&
      action(`start-${id}`, 'Start', () => save($, current => setStatus(current, id, 'in_progress'))),
    status === 'in_progress' &&
      // Back to Up next, at the top: it was the one being worked on. ⏸ with
      // the text-style selector, so it's drawn like ✓ and ×, not as an emoji.
      action(`pause-${id}`, '⏸\uFE0E', () => save($, current => reorder(setStatus(current, id, 'next'), [id]))),
    (status === 'next' || status === 'in_progress') &&
      action(`done-${id}`, '✓', () => save($, current => setStatus(current, id, 'done'))),
    removeButton(id),
  ]

  // The edit row: the app's own text field, with Cancel. Enter saves.
  const editRow = (task: Task) => {
    const { Input } = $.ui.resolve(e as typeof e & { surface: 'desktop' })
    return (
      <Box key={`row-${task.id}`} flexDirection="row" alignItems="center" gap={1} padding="xs">
        <Box flexGrow={1} flexShrink={1}>
          <Input
            key={`editing-${task.id}`}
            value={task.text}
            submitLabel="↵"
            autoFocus
            onSubmit={async text => {
              const trimmed = text.trim()
              if (trimmed) {
                await save($, current => ({
                  ...current,
                  tasks: current.tasks.map(one => (one.id === task.id ? { ...one, text: trimmed } : one)),
                }))
              }
              await stopEditing($)
            }}
          />
        </Box>
        {action(`cancel-${task.id}`, 'Cancel', () => stopEditing($))}
      </Box>
    )
  }

  // Mobile's rows: the pane's own, an SVG circle beside wrapping text. It
  // can't drag, so Up next gets ↑ and ↓ to reorder; it can't edit.
  const mobileRow = (task: Task) => {
    const { Svg } = $.ui.resolve(e as typeof e & { surface: 'mobile' })
    return (
      <Box key={`row-${task.id}`} flexDirection="row" alignItems="flex-start" gap={1}>
        <Box flexGrow={1} flexShrink={1} flexDirection="row" alignItems="flex-start" gap={1}>
          <Box height={1} flexShrink={0} alignItems="center" justifyContent="center">
            <Svg source={ICON[task.status]} alt={ALT[task.status]} width={16} height={16} />
          </Box>
          <Text dimColor={task.status === 'done' || task.status === 'proposed'}>
            <Text dimColor tabular>
              #{task.id}
            </Text>{' '}
            {task.text}
          </Text>
        </Box>
        <Box flexDirection="row" gap={1} flexShrink={0}>
          {task.status === 'next' && upNext.length > 1 && (
            <Box flexDirection="row" gap={1}>
              {action(`up-${task.id}`, '↑', () => save($, current => nudge(current, task.id, -1)))}
              {action(`down-${task.id}`, '↓', () => save($, current => nudge(current, task.id, 1)))}
            </Box>
          )}
          {buttonsFor(task.status, task.id)}
        </Box>
      </Box>
    )
  }

  // The button column is as wide as its widest labels with “Remove?” in
  // place of ×, so asking doesn't narrow the list and rewrap its text.
  const BUTTONS_WIDTH: Record<TaskStatus, number> = {
    next: 'Start ✓ Remove?'.length + 1,
    in_progress: '⏸ ✓ Remove?'.length + 1,
    proposed: 'Accept Remove?'.length + 1,
    done: 'Remove?'.length + 1,
  }

  // One list element and its circle and button columns, for `items` of a
  // group; `key` names it (and the rows it reports).
  const segment = (key: string, status: TaskStatus, items: readonly Task[], draggable: boolean): RenderChildren => {
    if (items.length === 0) return null
    const { Client } = $.ui.resolve(e as typeof e & { surface: 'desktop' })
    const listed = items.map(({ id, text }) => ({ id, text }))

    // The rows each item takes in the element, in the order it shows them
    // (a drag's preview included), as it last reported. Until it reports
    // the current items, each counts as one line, in list order.
    const reported: GroupRow[] = reportedRows[key] ?? []
    const ids = new Set(listed.map(item => item.id))
    const isCurrent = reported.length === listed.length && reported.every(row => ids.has(row.id))
    const rows = isCurrent ? reported : listed.map(item => ({ id: item.id, lines: 1, isGap: false }))

    // A column beside the element, one block per item, each as tall as the
    // item and drawn with the same small gap; `first` fills its first row.
    const column = (first: (id: number) => RenderChildren, minWidth?: number) => (
      <Box flexDirection="column" flexShrink={0} gap="xs" minWidth={minWidth}>
        {rows.map(row => (
          <Box height={row.lines} flexDirection="column">
            {!row.isGap && first(row.id)}
          </Box>
        ))}
      </Box>
    )

    let circles: RenderChildren = null
    if (e.surface === 'desktop') {
      const { Svg } = $.ui.resolve(e)
      circles = column(() => (
        <Box height={1} alignItems="center" justifyContent="center">
          <Svg source={ICON[status]} alt={ALT[status]} width={16} height={16} />
        </Box>
      ))
    }
    const buttons = column(
      id => (
        <Box height={1} flexDirection="row" gap={1} alignItems="center" justifyContent="flex-end">
          {buttonsFor(status, id)}
        </Box>
      ),
      BUTTONS_WIDTH[status],
    )

    return (
      <Box flexDirection="row" alignItems="flex-start" gap={1}>
        {circles}
        <Client
          key={`list-${key}`}
          module="./list.tsx"
          props={{
            group: key,
            items: listed,
            draggable,
            // Props are plain data with no empty values: leave glyph out off the terminal.
            ...(e.surface === 'terminal' ? { glyph: GLYPH[status] } : {}),
            dim: status === 'done' || status === 'proposed',
            widthFactor: e.surface === 'desktop' ? factor : 1,
            // What the pane last received from it, so it reports again when
            // the pane lost or never got its rows.
            reported: JSON.stringify(reportedRows[key] ?? null),
          }}
          flexGrow={1}
        />
        {buttons}
      </Box>
    )
  }

  // A group: its heading, `top` (Up next's add field), and its items. With
  // list elements: one for the group, or, while one of its items is edited,
  // one above it, its edit row, and one below, so the others keep their
  // wrapping. On mobile: its own rows. With `top`, it shows even when empty.
  const group = (status: TaskStatus, heading: string, items: readonly Task[], top: RenderChildren = null) => {
    if (items.length === 0 && top === null) return null
    const at = items.findIndex(task => task.id === editing)
    const edited = items[at]
    let body: RenderChildren
    if (!hasLists) {
      body = (
        <Box flexDirection="column" gap="xs">
          {items.map(mobileRow)}
        </Box>
      )
    } else if (edited === undefined) {
      body = segment(status, status, items, status === 'next')
    } else {
      body = (
        <Box flexDirection="column" gap="xs">
          {segment(`${status}-above`, status, items.slice(0, at), false)}
          {editRow(edited)}
          {segment(`${status}-below`, status, items.slice(at + 1), false)}
        </Box>
      )
    }
    return (
      <Box flexDirection="column" marginBottom={1}>
        <Text bold>
          {heading} ({items.length})
        </Text>
        {top}
        <Box flexDirection="column" marginTop="xs">
          {body}
        </Box>
      </Box>
    )
  }

  // The field to add a task by hand, first under Up next: the app's own
  // text field, for real selection and paste. Enter adds the task to Up
  // next and the field is drawn anew, empty, with the focus back in it.
  // Mobile has no text fields.
  let field: RenderChildren = null
  if (hasLists) {
    const { Input } = $.ui.resolve(e as typeof e & { surface: 'desktop' })
    field = (
      // A little room on every side, so the desktop's focus ring isn't clipped.
      <Box padding="xs" marginTop="xs">
        <Input
          key={`add-task-${count}`}
          placeholder="Add a task"
          submitLabel="↵"
          onSubmit={async text => {
            const trimmed = text.trim()
            if (!trimmed) return
            await save($, current => addTask(current, trimmed, 'next'))
            await update($, addCount, n => n + 1)
            $.ui.focus({ requestId: PANE, key: `add-task-${await read($, addCount)}` }).catch(() => undefined)
          }}
        />
      </Box>
    )
  }

  const hasOpen = tasks.some(isOpen)
  // Docked beside the chat, the pane fills its height, so an empty list's
  // message sits in the middle of it.
  const fill = e.props.placement === 'dock' ? e.props.scroll.bodyRows : undefined

  return (
    <Box flexDirection="column" minHeight={fill}>
      {group('in_progress', 'Now', of('in_progress'))}
      {group('next', 'Up next', upNext, field)}
      {group('proposed', 'Proposed', of('proposed'))}
      {!hasOpen && (
        <Box flexGrow={1} alignItems="center" justifyContent="center" minHeight={3}>
          <Text>{done.length > 0 ? 'Nothing left to do' : 'No tasks yet'}</Text>
        </Box>
      )}
      {group('done', 'Done', done)}
    </Box>
  )
}
