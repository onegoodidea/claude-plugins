import { expect, mock, test } from 'claude-code/testing'
import type { On } from 'claude-code'

const PANE = {
  plugin: 'checklist',
  component: 'Pane',
  requestId: 'checklist',
  props: {
    title: 'Checklist',
    isFocused: false,
    bodyColumns: 60,
    placement: 'dock',
    scroll: { offset: 0, bodyRows: 30 },
    view: {},
  },
} as const

const BAND = {
  plugin: 'checklist',
  component: 'AbovePrompt',
  requestId: 'band',
  props: {
    hasSurvey: false,
    isWorking: false,
    maxRows: 6,
    bodyColumns: 80,
    scroll: { offset: 0, bodyRows: 6 },
    view: {},
  },
} as const

const TOOL = 'mcp__checklist__tasks'

/** Stands for the engine beneath the mod; answers what the mod calls. */
function engine(on: On, sessionId: string, saved: Record<string, unknown> = {}, placed = true) {
  // What $.ui.panes answers; a test may change it (a surface attaching).
  const panes: { id: string; title: string; isShown: boolean; isFocused: boolean; isPlaced: boolean }[] = []
  const store: Record<string, unknown> = { ...saved }
  const opened: string[] = []
  const prompts: string[] = []
  const redraws: string[] = []

  on('ui.invalidate', (_, e) => {
    redraws.push(e.event)
    return { value: undefined }
  })
  on('store.get', (_, e) => ({ value: store[e.key] }))
  on('store.set', (_, e) => {
    store[e.key] = e.value
    return { value: undefined }
  })
  on('session.id', () => ({ value: sessionId }))
  on('command.register', () => ({ value: { command: 'checklist' } }))
  on('tool.register', () => ({ value: { tool: TOOL } }))
  on('ui.panes', () => ({ value: panes }))
  on('ui.open', (_, e) => {
    opened.push(e.id)
    return opened.length > 1 || placed
      ? { value: { isPlaced: true as const } }
      : { value: { isPlaced: false as const, reason: 'too narrow' } }
  })
  on('prompt.submit', (_, e) => {
    prompts.push(e.text)
    return { text: e.text }
  })
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('tool.call', () => ({ result: 'ok' }))
  return { store, opened, prompts, redraws, panes }
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Engine = any

const start = ($: Engine) =>
  $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })

const call = ($: Engine, input: object): Promise<string> =>
  $.tool.call(input).then((ran: { result: unknown }) => String(ran.result))

test('Claude adds, changes, and removes items; new ones start as proposed', async ($, on) => {
  const world = engine(on, 's1')
  await start($)

  const added = await call($, { tool: TOOL, add: [{ text: 'Write the README' }, { text: 'Add tests' }, { text: 'Ship it' }] })
  expect(added).toContain('#1 [proposed] Write the README')

  const changed = await call($, {
    tool: TOOL,
    update: [{ id: 1, status: 'in_progress' }, { id: 2, status: 'done', text: 'Add unit tests' }],
    remove: [3, 9],
  })
  expect(changed).toContain('No item #9 to remove.')
  expect(changed).toContain('#1 [in_progress] Write the README')
  expect(changed).not.toContain('Ship it')
  expect(world.store['session:s1']).toEqual(
    expect.objectContaining({ nextId: 4 }),
  )
  expect(world.opened).toContain('checklist')
  // The desktop app redraws the band only when asked.
  expect(world.redraws).toContain('ui.render')
})

test('the add field under Up next adds a task on Enter and starts over', async ($, on) => {
  engine(on, 's7')
  await start($)
  const ui = await $.ui.mount({ ...PANE, surface: 'desktop' })
  // With no tasks, Up next still shows, holding the field.
  expect((await ui.find({ type: 'Text', text: /^Up next/ }))?.text).toBe('Up next (0)')
  await ui.input({ key: 'add-task-0', text: '  Call the vendor  ' })
  expect(await call($, { tool: TOOL })).toBe('#1 [next] Call the vendor')
  expect(await ui.find({ key: 'add-task-1' })).toBeDefined()
  await ui.input({ key: 'add-task-1', text: '   ' })
  expect(await call($, { tool: TOOL })).toBe('#1 [next] Call the vendor')

  await call($, { tool: TOOL, update: [{ id: 1, status: 'done' }] })
  expect((await ui.find({ type: 'Text', text: /left to do/ }))?.text).toBe('Nothing left to do')
  await call($, { tool: TOOL, remove: [1] })
  expect((await ui.find({ type: 'Text', text: /No tasks/ }))?.text).toBe('No tasks yet')
  await ui.unmount()

  const phone = await $.ui.mount({ ...PANE, surface: 'mobile' })
  expect(await phone.find({ key: 'add-task-1' })).toBeUndefined()
  await phone.unmount()
})

// Each group's text is drawn by a list element (./list.tsx), keyed by group;
// its circles and buttons are the pane's own, beside it.
const UP_NEXT = { in: 'list-next' } as const
const NOW = { in: 'list-in_progress' } as const

async function click(ui: Engine, x: number, y: number, scope: { in: string } = UP_NEXT) {
  await ui.pointer({ type: 'down', x, y, button: 'left', ...scope })
  await ui.pointer({ type: 'up', x, y, button: 'left', ...scope })
}

test('proposed items take Accept and ×; Up next items take Start, ✓ and ×', async ($, on) => {
  engine(on, 's2')
  await start($)
  await call($, { tool: TOOL, add: [{ text: 'Idea one' }, { text: 'Idea two' }, { text: 'Idea three' }] })

  const ui = await $.ui.mount({ ...PANE, surface: 'desktop' })
  expect((await ui.find({ type: 'Text', text: /Proposed/ }))?.text).toBe('Proposed (3)')
  await ui.press({ key: 'accept-1' })
  await ui.press({ key: 'accept-2' })
  // × asks first, then removes.
  await ui.press({ key: 'remove-3' })
  expect((await ui.find({ key: 'remove-3' }))?.text).toBe('Remove?')
  expect(await call($, { tool: TOOL })).toContain('#3 [proposed] Idea three')
  await ui.press({ key: 'remove-3' })
  expect((await ui.find({ type: 'Text', text: /Up next/ }))?.text).toBe('Up next (2)')

  await ui.resize({ columns: 60, rows: 2, ...UP_NEXT })
  expect(await ui.find({ type: 'Text', text: /Idea one/, ...UP_NEXT })).toBeDefined()
  await ui.press({ key: 'start-1' })
  expect(await call($, { tool: TOOL })).toContain('#1 [in_progress] Idea one')
  // Pause sends it back to the top of Up next; Start again.
  await ui.press({ key: 'pause-1' })
  expect((await call($, { tool: TOOL })).split('\n')[0]).toBe('#1 [next] Idea one')
  await ui.press({ key: 'start-1' })
  await ui.press({ key: 'done-2' })
  expect(await call($, { tool: TOOL })).toContain('#2 [done] Idea two')
  await ui.unmount()

  const terminal = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect((await terminal.find({ type: 'Text', text: /Idea two/, in: 'list-done' }))?.text).toBe('● #2 Idea two')
  await terminal.unmount()
})

test('Up next: drag reorders, a double-click edits, long items wrap', async ($, on) => {
  engine(on, 's3')
  await start($)
  await call($, {
    tool: TOOL,
    add: [
      { text: 'First', status: 'next' },
      { text: 'Second, a much longer item that has to wrap onto more than one line here', status: 'next' },
      { text: 'Third', status: 'next' },
    ],
  })

  // Wrap at the cell count, so the line breaks below are exact.
  expect((await ($ as Engine).command.run({ command: 'checklist', args: 'wrap 1' })).text).toBe('Wrap factor set to 1.')
  const ui = await $.ui.mount({ ...PANE, surface: 'desktop' })
  await ui.resize({ columns: 60, rows: 4, ...UP_NEXT })
  // Second wraps to two rows (1-2), so Third starts on row 3.
  expect((await ui.find({ type: 'Text', text: /one line here/, ...UP_NEXT }))?.text).toBe('than one line here')
  // The pane draws an SVG circle per item beside the element, from the rows it reported.
  const circles = await ui.findAll({ type: 'Svg' })
  expect(circles.filter(c => (c.props as { alt: string }).alt === 'Not started')).toHaveLength(3)
  expect((await ui.find({ type: 'Text', text: /○/, ...UP_NEXT }))).toBeUndefined()

  // Drag First down onto Third.
  await ui.pointer({ type: 'down', x: 5, y: 0, button: 'left', ...UP_NEXT })
  await ui.pointer({ type: 'move', x: 5, y: 3, button: 'left', ...UP_NEXT })
  expect(await ui.find({ type: 'Text', text: /≡ #1/, ...UP_NEXT })).toBeDefined()
  await ui.pointer({ type: 'up', x: 5, y: 3, button: 'left', ...UP_NEXT })
  const order = (await call($, { tool: TOOL })).split('\n').map(line => line.slice(0, 2))
  expect(order).toEqual(['#2', '#3', '#1'])

  // A double-click on Third's text (now row 2) opens its edit field.
  await click(ui, 5, 2)
  await click(ui, 5, 2)
  expect(await ui.find({ key: 'editing-3' })).toBeDefined()
  await ui.input({ key: 'editing-3', text: 'Third, renamed' })
  expect(await call($, { tool: TOOL })).toContain('#3 [next] Third, renamed')

  // A wider factor fits more on a line: at 1.5, the long item fits on one.
  await ($ as Engine).command.run({ command: 'checklist', args: 'wrap 1.5' })
  expect(await ui.find({ type: 'Text', text: /^than one line here/, ...UP_NEXT })).toBeUndefined()
  expect((await ($ as Engine).command.run({ command: 'checklist', args: 'wrap 9' })).text).toContain('Wrap factor is 1.5')

  // × beside the drag element removes, on a second press.
  await ui.press({ key: 'remove-2' })
  await ui.press({ key: 'remove-2' })
  expect(await call($, { tool: TOOL })).not.toContain('#2 ')
  await ui.unmount()
})

test('Now items: a double-click edits, with Cancel; Now can’t be dragged', async ($, on) => {
  engine(on, 's8')
  await start($)
  await call($, {
    tool: TOOL,
    add: [
      { text: 'Draft the brief', status: 'in_progress' },
      { text: 'Review it', status: 'in_progress' },
    ],
  })

  const ui = await $.ui.mount({ ...PANE, surface: 'desktop' })
  await ui.resize({ columns: 60, rows: 2, ...NOW })
  expect((await ui.find({ type: 'Text', text: /^Now/ }))?.text).toBe('Now (2)')

  // A drag does nothing here.
  await ui.pointer({ type: 'down', x: 5, y: 0, button: 'left', ...NOW })
  await ui.pointer({ type: 'move', x: 5, y: 1, button: 'left', ...NOW })
  await ui.pointer({ type: 'up', x: 5, y: 1, button: 'left', ...NOW })
  expect((await call($, { tool: TOOL })).split('\n')[0]).toBe('#1 [in_progress] Draft the brief')

  await click(ui, 5, 0, NOW)
  await click(ui, 5, 0, NOW)
  // While one item is edited, the others stay in a list element (below it
  // here), so they keep their wrapping.
  expect(await ui.find({ type: 'Text', text: /Review it/, in: 'list-in_progress-below' })).toBeDefined()
  await ui.input({ key: 'editing-1', text: 'Draft the client brief' })
  expect(await call($, { tool: TOOL })).toContain('#1 [in_progress] Draft the client brief')
  await ui.resize({ columns: 60, rows: 2, ...NOW })
  await click(ui, 5, 0, NOW)
  await click(ui, 5, 0, NOW)
  await ui.press({ key: 'cancel-1' })
  expect(await ui.find({ key: 'editing-1' })).toBeUndefined()
  await ui.unmount()
})

/** Lets Date.now() move on, so two done times differ. */
function waitAMillisecond() {
  const start = Date.now()
  while (Date.now() === start) {
    // spin
  }
}

test('Done lists the most recently finished first', async ($, on) => {
  engine(on, 's9')
  await start($)
  await call($, { tool: TOOL, add: [{ text: 'Alpha', status: 'next' }, { text: 'Beta', status: 'next' }, { text: 'Gamma', status: 'next' }] })
  await call($, { tool: TOOL, update: [{ id: 2, status: 'done' }] })
  waitAMillisecond()
  await call($, { tool: TOOL, update: [{ id: 1, status: 'done' }] })
  waitAMillisecond()
  const ui = await $.ui.mount({ ...PANE, surface: 'desktop' })
  await ui.press({ key: 'done-3' })
  const lines = (await call($, { tool: TOOL })).split('\n')
  expect(lines).toEqual(['#3 [done] Gamma', '#1 [done] Alpha', '#2 [done] Beta'])
  // Back to Up next drops the time; done again, it's newest.
  await call($, { tool: TOOL, update: [{ id: 2, status: 'next' }] })
  await call($, { tool: TOOL, update: [{ id: 2, status: 'done' }] })
  expect((await call($, { tool: TOOL })).split('\n')[0]).toBe('#2 [done] Beta')
  await ui.unmount()
})

test('a New task card becomes a proposed item, and dismissing it removes it', async ($, on) => {
  on('tool.call', { tool: 'mcp__ccd_session__start_session' }, () => ({ result: 'Proposed. task_id: task_ab12cd34' }))
  const world = engine(on, 's4')
  await start($)

  await call($, { tool: 'mcp__ccd_session__start_session', initiation: 'own_initiative', title: 'Refactor the parser' })
  expect(await call($, { tool: TOOL })).toContain('#1 [proposed] Refactor the parser')
  expect((world.store['session:s4'] as { tasks: { cardId?: string }[] }).tasks[0]?.cardId).toBe('task_ab12cd34')

  await call($, { tool: 'mcp__ccd_session__dismiss_task', task_id: 'task_ab12cd34' })
  expect(await call($, { tool: TOOL })).toBe('The list is empty.')
})

test('the band shows open items while the pane is closed, and opens it', async ($, on) => {
  // The resumed session's pane opens unplaced, so the band stands in for it.
  const world = engine(
    on,
    's5',
    { 'session:s5': { tasks: [{ id: 1, text: 'Old item', status: 'suggested' }], nextId: 2 } },
    false,
  )
  await start($)

  const band = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect((await band.find({ type: 'Text', text: /up next/ }))?.text).toBe('1 up next')
  world.opened.length = 0
  await band.press({ key: 'open-checklist' })
  expect(world.opened).toEqual(['checklist'])
  await band.unmount()

  // The first version's "suggested" reads as up next.
  expect(await call($, { tool: TOOL })).toContain('#1 [next] Old item')
})

test('/clear with open items asks for a review first; a second /clear goes through', async ($, on) => {
  const world = engine(on, 's6')
  const clock = mock.clock(on, { now: 1_000_000 })
  let cleared = 0
  on('command.run', { command: 'clear' }, () => {
    cleared += 1
    return { text: 'cleared' }
  })
  await start($)
  await call($, { tool: TOOL, add: [{ text: 'Keep me', status: 'next' }] })

  const first = await ($ as Engine).command.run({ command: 'clear', args: '' })
  expect(first.text).toContain('1 open checklist item.')
  expect(cleared).toBe(0)
  await clock.advance(100)
  expect(world.prompts[0]).toContain('/clear')

  await ($ as Engine).command.run({ command: 'clear', args: '' })
  expect(cleared).toBe(1)
})

test('a first word longer than a line is drawn whole, across lines', async ($, on) => {
  engine(on, 's10')
  await start($)
  await ($ as Engine).command.run({ command: 'checklist', args: 'wrap 1' })
  await call($, { tool: TOOL, add: [{ text: 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 tail', status: 'next' }] })
  const ui = await $.ui.mount({ ...PANE, surface: 'desktop' })
  await ui.resize({ columns: 20, rows: 3, ...UP_NEXT })
  const lines = (await ui.findAll({ type: 'Text', ...UP_NEXT }))
    .map(line => line.text)
    .filter(text => !/^#\d+ $/.test(text))
  expect(lines.join('').replace(/^#1 /, '').replace(/\s/g, '')).toBe('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789tail')
  await ui.unmount()
})

test('a pane placed when a surface attaches hides the band', async ($, on) => {
  const world = engine(on, 's11', { 'session:s11': { tasks: [{ id: 1, text: 'Open item', status: 'next' }], nextId: 2 } }, false)
  on('session.attach', (_, e) => ({ clientId: e.clientId }))
  // With the band left to it, the engine draws its own (here, a stand-in).
  on('ui.render', ($, e) => {
    const { Text } = $.ui.resolve(e)
    return <Text>engine</Text>
  })
  await start($)
  const band = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await band.find({ key: 'open-checklist' })).toBeDefined()
  // The desktop attaches and places the waiting pane.
  world.panes.push({ id: 'checklist', title: 'Checklist', isShown: true, isFocused: false, isPlaced: true })
  await ($ as Engine).session.attach({ surface: 'desktop', clientId: 'desktop:default' })
  expect(await band.find({ key: 'open-checklist' })).toBeUndefined()
  await band.unmount()
})

test('a newer “Remove?” isn’t cut short by an older one’s timer', async ($, on) => {
  engine(on, 's12')
  const clock = mock.clock(on, { now: 0 })
  await start($)
  await call($, { tool: TOOL, add: [{ text: 'One', status: 'proposed' }, { text: 'Two', status: 'proposed' }] })
  const ui = await $.ui.mount({ ...PANE, surface: 'desktop' })
  await ui.press({ key: 'remove-1' })
  await clock.advance(1000)
  await ui.press({ key: 'remove-2' })
  await clock.advance(1000)
  await ui.press({ key: 'remove-1' })
  // The first press's timer would have fired at 3 s.
  await clock.advance(2500)
  expect((await ui.find({ key: 'remove-1' }))?.text).toBe('Remove?')
  await clock.advance(1000)
  expect((await ui.find({ key: 'remove-1' }))?.text).toBe('×')
  expect(await call($, { tool: TOOL })).toContain('#1 [proposed] One')
  await ui.unmount()
})

test('renaming a done item keeps its place in Done', async ($, on) => {
  engine(on, 's13', {
    'session:s13': {
      tasks: [
        { id: 1, text: 'Older, no time', status: 'done' },
        { id: 2, text: 'Newer', status: 'done', doneAt: 5 },
      ],
      nextId: 3,
    },
  })
  await start($)
  await call($, { tool: TOOL, update: [{ id: 1, text: 'Older, renamed' }] })
  expect((await call($, { tool: TOOL })).split('\n')).toEqual(['#2 [done] Newer', '#1 [done] Older, renamed'])
})

test('a damaged saved list keeps what it can, and the tool still works', async ($, on) => {
  engine(on, 's14', {
    'session:s14': {
      tasks: [null, { id: 'x', text: 'No id' }, { id: 3, text: 'Keep', status: 'done' }, { id: 2, status: 'odd' }],
      nextId: 1,
    },
  })
  await start($)
  expect((await call($, { tool: TOOL })).split('\n')).toEqual(['#2 [next] ', '#3 [done] Keep'])
  // Ids carry on past the highest in use, not from the stale nextId.
  expect(await call($, { tool: TOOL, add: [{ text: 'New' }] })).toContain('#4 [proposed] New')
})

test('/checklist review with nothing open, and unknown arguments', async ($, on) => {
  const world = engine(on, 's15')
  await start($)
  const command = (args: string) => ($ as Engine).command.run({ command: 'checklist', args })
  expect((await command('review')).text).toBe('Nothing open to review.')
  expect(world.prompts).toEqual([])
  world.opened.length = 0
  expect((await command('oops')).text).toContain('Usage: /checklist')
  expect(world.opened).toEqual([])
})

test('a pane the person closed stays closed after a restart; the band leads back', async ($, on) => {
  const world = engine(on, 's16', {
    'session:s16': { tasks: [{ id: 1, text: 'Open item', status: 'next' }], nextId: 2 },
    'closed:s16': true,
  })
  await start($)
  expect(world.opened).toEqual([])
  const band = await $.ui.mount({ ...BAND, surface: 'desktop' })
  await band.press({ key: 'open-checklist' })
  expect(world.opened).toEqual(['checklist'])
  expect(world.store['closed:s16']).toBe(false)
  await band.unmount()
})
