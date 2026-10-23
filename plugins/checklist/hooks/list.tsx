import type { ClientModule } from 'claude-code'

// One group of the Checklist (Now, Up next, Proposed, Done), its text drawn
// by the surface itself so a double-click can be told apart, and, in Up
// next, so items can be dragged.
//
// The module lays the text out by hand (word wrap at the region's width) so
// it knows which rows each item takes; the pointer is reported in rows and
// columns, and that is how a press is matched to an item or an action.
//
// - With `draggable` (Up next), drag an item to reorder it. While dragging, a dimmed copy (the ghost)
//   takes the item's place and moves with the pointer, nudged right so it
//   reads as lifted. It snaps row by row. It's drawn in the list's flow, not
//   positioned over it: with the gap between items its row would be a
//   fraction, which the surface doesn't place.
// - Double-click an item to edit it (the hooks module draws the edit field).
//
// The circles and the buttons are the pane's own, drawn in columns beside
// this element so they look and behave like the app's: it posts which rows
// each item takes so they line up. With `glyph` (the terminal, which has no
// SVG) it draws that circle itself. `dim` draws the text dimmed.
//
// `widthFactor` widens the character count lines are wrapped at: the desktop
// draws a proportional font, most of whose letters are narrower than a cell,
// so wrapping at the cell count breaks lines early. 1 in the terminal.

type Item = { id: number; text: string }
type Props = {
  group: string
  items: Item[]
  draggable?: boolean
  glyph?: string
  dim?: boolean
  widthFactor?: number
  /** The rows the pane last received from this element (JSON), to post when they differ. */
  reported?: string
}
type State = {
  /** The pressed item's index, and where the pointer has taken it. */
  from?: number
  to?: number
  moved?: boolean
  /** The last click on an item's text, to tell a double-click. */
  lastClick?: { id: number; at: number }
}

const DOUBLE_CLICK_MS = 400
const FALLBACK_COLUMNS = 48

/** Word wrap: the first line `first` columns wide, the rest `rest` wide. */
function wrap(text: string, first: number, rest: number): string[] {
  const lines: string[] = []
  let line = ''
  const width = () => Math.max(4, lines.length === 0 ? first : rest)
  for (const word of text.split(/\s+/).filter(Boolean)) {
    let rest = word
    while (rest.length > 0) {
      const room = width() - (line === '' ? 0 : line.length + 1)
      if (rest.length <= room) {
        line = line === '' ? rest : `${line} ${rest}`
        rest = ''
      } else if (line !== '') {
        lines.push(line)
        line = ''
      } else {
        // A word longer than the line: break it. The width is read once: the
        // push makes the next line a wider "rest" line.
        const w = width()
        lines.push(rest.slice(0, w))
        rest = rest.slice(w)
      }
    }
  }
  if (line !== '' || lines.length === 0) lines.push(line)
  return lines
}

type Laid = { item: Item; prefix: string; lines: string[]; start: number }

/**
 * Each item's lines and the row it starts on, in the order given. `gap` is
 * the space between items, in rows (a fraction where the surface draws its
 * small spacing step finer than a row).
 */
function layout(items: readonly Item[], columns: number, mark: string, gap: number): Laid[] {
  let row = 0
  return items.map(item => {
    const prefix = `#${item.id} `
    const first = columns - mark.length - prefix.length
    const lines = wrap(item.text, first, columns - mark.length)
    const laid = { item, prefix, lines, start: row }
    row += lines.length + gap
    return laid
  })
}

function move<T>(list: readonly T[], from?: number, to?: number): T[] {
  const next = list.slice()
  if (from === undefined || to === undefined || from === to) return next
  const [moved] = next.splice(from, 1)
  if (moved !== undefined) next.splice(to, 0, moved)
  return next
}

const List: ClientModule<Props, State> = (props, surface) => {
  const { Box, Text } = surface.elements
  const items = props.items ?? []
  const state = surface.state ?? {}
  const cells = surface.columns > 0 ? surface.columns : FALLBACK_COLUMNS
  // The characters a line holds, which wrapping counts in.
  const columns = Math.floor(cells * (props.widthFactor ?? 1))
  const mark = props.glyph ? `${props.glyph} ` : ''
  // The items are drawn with the surface's small spacing step between them.
  // Its size in rows isn't known up front: read it off the region's height
  // once laid out (the rows beyond the items' own lines, shared by the gaps).
  const lineCount = layout(items, columns, mark, 0).reduce((sum, one) => sum + one.lines.length, 0)
  const gap = items.length > 1 && surface.rows > lineCount ? (surface.rows - lineCount) / (items.length - 1) : 0
  const laid = layout(items, columns, mark, gap)

  /** The item whose block (its lines and the gap after) holds row `y`. */
  const indexAt = (y: number) => {
    const middle = y + 0.5
    const found = laid.findIndex(one => middle >= one.start && middle < one.start + one.lines.length + gap)
    if (found !== -1) return found
    return y < 0 ? 0 : laid.length - 1
  }

  surface.onPointer(event => {
    if (event.type === 'down' && event.button === 'left' && laid.length > 0) {
      const from = indexAt(event.y)
      surface.setState({ from, to: from, lastClick: state.lastClick })
    } else if (event.type === 'move' && event.button === 'left' && state.from !== undefined) {
      // A press that reaches another row is a drag, never a click; only a
      // draggable list shows it moving.
      const to = indexAt(event.y)
      if (to !== state.to) surface.setState({ ...state, to, moved: true })
    } else if (event.type === 'up' && state.from !== undefined) {
      const item = items[state.from]
      if (item === undefined) return surface.setState({})
      if (state.moved) {
        const to = state.to ?? state.from
        if (props.draggable && to !== state.from) surface.post({ kind: 'move', group: props.group, id: item.id, to })
        return surface.setState({})
      }
      const now = Date.now()
      const last = state.lastClick
      if (last !== undefined && last.id === item.id && now - last.at <= DOUBLE_CLICK_MS) {
        surface.post({ kind: 'edit', group: props.group, id: item.id })
        return surface.setState({})
      }
      surface.setState({ lastClick: { id: item.id, at: now } })
    } else if (event.type === 'leave' && state.from === undefined) {
      // Not while pressed: a drag may cross the edge and come back.
      surface.setState({ lastClick: state.lastClick })
    }
  })

  const dragged = props.draggable && state.moved && state.from !== undefined ? items[state.from] : undefined
  const shown = layout(move(items, state.from, dragged === undefined ? undefined : state.to), columns, mark, gap)

  // Tell the pane which rows each item takes, for its circles and buttons.
  const rows = shown.map(one => ({ id: one.item.id, lines: one.lines.length, isGap: one.item.id === dragged?.id }))
  const signature = JSON.stringify(rows)
  // Compared with what the pane holds, not with what was sent: a report it
  // lost (a restart, a post replaced in the same frame) is sent again.
  if (signature !== props.reported) surface.post({ kind: 'layout', group: props.group, rows })

  const firstLine = (one: Laid) => (
    <Text wrap="truncate" dimColor={props.dim}>
      {mark}
      <Text dimColor>{one.prefix}</Text>
      {one.lines[0]}
    </Text>
  )
  const moreLines = (one: Laid) =>
    one.lines.slice(1).map(line => (
      <Text wrap="truncate" dimColor={props.dim}>
        {' '.repeat(mark.length)}
        {line}
      </Text>
    ))

  return (
    <Box flexDirection="column" gap="xs">
      {shown.map(one =>
        one.item.id === dragged?.id ? (
          // The dragged item's place, where it would land: its ghost.
          <Box flexDirection="column" marginLeft={1}>
            {one.lines.map((line, index) => (
              <Text inverse dimColor wrap="truncate">
                {index === 0 ? `≡ ${one.prefix}` : '  '}
                {line}
              </Text>
            ))}
          </Box>
        ) : (
          <Box flexDirection="column">
            {firstLine(one)}
            {moreLines(one)}
          </Box>
        ),
      )}
    </Box>
  )
}

export default List
