import { expect, test } from 'claude-code/testing'
import type { On } from 'claude-code'

const VIEW = {
  hasSurvey: false,
  isCollapsed: false,
  isWorking: false,
  maxRows: 6,
  bodyColumns: 80,
  scroll: { offset: 0, bodyRows: 6 },
  view: {},
} as const

const BAND = { plugin: 'context-strip', component: 'AbovePrompt', requestId: 'band', props: VIEW } as const

/** A summary breakdown whose 33K buffer puts auto-compact at 84% of a 200K window. */
const BREAKDOWN = {
  categories: [
    { name: 'Messages', tokens: 84_000, color: 'text', isDeferred: false, kind: 'used' },
    { name: 'Autocompact buffer', tokens: 33_000, color: 'inactive', isDeferred: false, kind: 'buffer' },
  ],
  totalTokens: 84_000,
  maxTokens: 200_000,
  rawMaxTokens: 200_000,
  autocompactSource: 'model-default',
  percentage: 42,
  gridRows: [],
  model: 'claude-opus-5-5',
}

/** `tasks` undefined: loaded, never used. */
type Checklist = { tasks?: { status: string }[]; isPaneOpen: boolean }

/**
 * Stands for the engine beneath the mod: the context figures it reports, and,
 * when `checklist` is given, the checklist mod's values (absent: not loaded).
 */
function engine(on: On, percent: () => number | undefined, checklist?: Checklist) {
  on('session.usage', () =>
    ({
      value: {
        startedAt: 0,
        context: { tokens: undefined, window: 200_000, percent: percent(), breakdown: BREAKDOWN },
        rateLimits: [],
      },
    }) as never,
  )
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('session.measure', (_, e) => ({ changed: e.changed }))
  on('ui.invalidate', () => ({ value: undefined }) as never)
  on('command.list', () =>
    ({
      value: checklist === undefined ? [] : [{ name: 'checklist', description: '', source: 'plugin', plugin: 'checklist' }],
    }) as never,
  )
  on('state.get', ($, e, next) => {
    // The checklist's keys aren't in this mod's contract, so `e` is typed as this mod's own.
    const ref = e as { plugin: string; key: string }
    if (ref.plugin !== 'checklist') return next(e)
    if (checklist === undefined) return { value: { value: undefined, version: 0 } } as never
    if (checklist.tasks === undefined) return { value: { value: undefined, version: 0 } } as never
    const value = ref.key === 'board' ? { tasks: checklist.tasks, nextId: 9 } : checklist.isPaneOpen
    return { value: { value, version: 1 } } as never
  })
  // The engine's own drawing, where the mod passes.
  on('ui.render', ($, e) => {
    const { Text } = $.ui.resolve(e)
    return <Text>engine</Text>
  })
}

const OPEN_ITEMS = [{ status: 'next' }, { status: 'next' }, { status: 'proposed' }, { status: 'done' }]

test('with no checklist, the strip is the context alone, on every surface', async ($, on) => {
  engine(on, () => 42)
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })

  for (const surface of ['terminal', 'desktop', 'mobile'] as const) {
    const ui = await $.ui.mount({ ...BAND, surface })
    expect((await ui.find({ type: 'Text', text: /Context/ }))?.text).toBe('Context: 42%')
    expect(await ui.find({ type: 'Text', text: /up next/ })).toBeUndefined()
    await ui.unmount()
  }
})

test('with open checklist items and its pane closed, both share the strip', async ($, on) => {
  engine(on, () => 42, { tasks: OPEN_ITEMS, isPaneOpen: false })
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })

  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect((await ui.find({ type: 'Text', text: /up next/ }))?.text).toBe('2 up next · 1 proposed')
  expect((await ui.find({ type: 'Text', text: /Context/ }))?.text).toBe('Context: 42%')
  await ui.unmount()
})

test('the checklist part shows before the first context reading', async ($, on) => {
  engine(on, () => undefined, { tasks: OPEN_ITEMS, isPaneOpen: false })
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })

  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect((await ui.find({ type: 'Text', text: /up next/ }))?.text).toBe('2 up next · 1 proposed')
  expect(await ui.find({ type: 'Text', text: /Context/ })).toBeUndefined()
  await ui.unmount()
})

test('with the checklist pane open, the strip still shows its summary', async ($, on) => {
  engine(on, () => 42, { tasks: OPEN_ITEMS, isPaneOpen: true })
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })

  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect((await ui.find({ type: 'Text', text: /up next/ }))?.text).toBe('2 up next · 1 proposed')
  expect((await ui.find({ type: 'Text', text: /Context/ }))?.text).toBe('Context: 42%')
  await ui.unmount()
})

test('a checklist never used shows, so it can be opened', async ($, on) => {
  engine(on, () => 42, { isPaneOpen: false })
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })

  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect((await ui.find({ type: 'Text', text: /nothing open/ }))?.text).toBe('nothing open')
  await ui.unmount()
})

test('a checklist with only done items says nothing is open', async ($, on) => {
  engine(on, () => 42, { tasks: [{ status: 'done' }], isPaneOpen: false })
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })

  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect((await ui.find({ type: 'Text', text: /nothing open/ }))?.text).toBe('nothing open')
  await ui.unmount()
})

test('with nothing to show, the band goes to the engine', async ($, on) => {
  engine(on, () => undefined)
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })

  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect((await ui.find({ type: 'Text' }))?.text).toBe('engine')
  await ui.unmount()
})

const ROWS = [
  { plugin: 'checklist', tree: { type: 'Text', props: {}, children: ['Checklist: 2 up next'] } },
  { plugin: 'context-strip', tree: { type: 'Text', props: {}, children: ['Context: 42%'] } },
]

test('the checklist’s own row goes while the strip carries its summary', async ($, on) => {
  engine(on, () => 42, { tasks: OPEN_ITEMS, isPaneOpen: false })
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })

  const list = { plugin: 'context-strip', component: 'AbovePromptList', requestId: 'band', surface: 'desktop' } as const
  const ui = await $.ui.mount({ ...list, props: { ...VIEW, rows: ROWS } } as never)
  // The test's core stacks the rows the hook leaves.
  expect(await ui.find({ type: 'Text', text: /Checklist/ })).toBeUndefined()
  expect((await ui.find({ type: 'Text', text: /Context/ }))?.text).toBe('Context: 42%')
  await ui.unmount()
})

test('without the checklist mod, the band’s rows are left as they are', async ($, on) => {
  engine(on, () => 42)
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })

  const list = { plugin: 'context-strip', component: 'AbovePromptList', requestId: 'band', surface: 'desktop' } as const
  const ui = await $.ui.mount({ ...list, props: { ...VIEW, rows: ROWS } } as never)
  expect((await ui.find({ type: 'Text', text: /Checklist/ }))?.text).toBe('Checklist: 2 up next')
  await ui.unmount()
})

test('a measurement moves the strip', async ($, on) => {
  let percent = 10
  engine(on, () => percent)
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  percent = 80
  await $.session.measure({
    context: { tokens: 160_000, window: 200_000, percent: 80 },
    rateLimits: [],
    changed: ['context'],
  } as never)

  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect((await ui.find({ type: 'Text', text: /Context/ }))?.text).toBe('Context: 80%')
  await ui.unmount()
})

const NOTIFY = { kind: 'task-notification' } as const

/** The Bash tool beneath the mod, answering a background run with its task id. */
function backgroundBash(on: On, taskId: string) {
  on('tool.call', { tool: 'Bash' }, () =>
    ({ result: { stdout: '', stderr: '', interrupted: false, backgroundTaskId: taskId } }) as never,
  )
}

test('with no background tasks, the strip shows no count', async ($, on) => {
  engine(on, () => 42)
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })

  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: /background/ })).toBeUndefined()
  await ui.unmount()
})

test('a background shell shows its count until its notification says it ended', async ($, on) => {
  engine(on, () => 42)
  backgroundBash(on, 'b1')
  on('prompt.submit', (_, e) => ({ text: e.text }) as never)
  on('agent.list', () => ({ value: [] }) as never)
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })

  await $.tool.call({ tool: 'Bash', command: 'sleep 60', run_in_background: true })
  let ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect((await ui.find({ type: 'Text', text: /background/ }))?.text).toBe('1 background task')
  expect((await ui.find({ type: 'Text', text: /Context/ }))?.text).toBe('Context: 42%')
  await ui.unmount()

  await $.prompt.submit({
    text: '<task-notification>\n<task-id>b1</task-id>\n<status>completed</status>\n</task-notification>',
    origin: NOTIFY,
  } as never)
  ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: /background/ })).toBeUndefined()
  await ui.unmount()
})

test('running agents count, idle and finished ones don’t', async ($, on) => {
  engine(on, () => 42)
  on('agent.list', () =>
    ({ value: [{ id: 'a', status: 'running' }, { id: 'b', status: 'waiting' }, { id: 'c', status: 'idle' }, { id: 'd', status: 'completed' }] }) as never,
  )
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })

  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect((await ui.find({ type: 'Text', text: /background/ }))?.text).toBe('2 background tasks')
  await ui.unmount()
})

test('the count shows even before the first context reading', async ($, on) => {
  engine(on, () => undefined)
  on('agent.list', () => ({ value: [{ id: 'a', status: 'running' }] }) as never)
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })

  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect((await ui.find({ type: 'Text', text: /background/ }))?.text).toBe('1 background task')
  await ui.unmount()
})

test('on the desktop, a click on the count opens the app’s Tasks pane', async ($, on) => {
  engine(on, () => 42)
  on('agent.list', () => ({ value: [{ id: 'a', status: 'running' }] }) as never)
  const shown: unknown[] = []
  on('tool.call', { tool: 'mcp__ccd_view__show_pane' } as never, (_, e) => {
    shown.push((e as { pane?: unknown }).pane)
    return { result: 'shown' } as never
  })
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })

  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  await ui.press({ key: 'open-tasks' })
  expect(shown).toEqual(['tasks'])
  await ui.unmount()
})

test('in the terminal, a click on the count runs /tasks', async ($, on) => {
  engine(on, () => 42)
  on('agent.list', () => ({ value: [{ id: 'a', status: 'running' }] }) as never)
  const ran: string[] = []
  on('command.run', (_, e) => {
    ran.push(e.command)
    return { text: '' }
  })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })

  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
  await ui.press({ key: 'open-tasks' })
  expect(ran).toEqual(['tasks'])
  await ui.unmount()
})

const OUTPUT = '/private/tmp/claude/tasks/b2.output'

/** What the stub host holds: the files open (by path), the live pids, the commands run. */
type Host = { held: Set<string>; alive: Set<string>; ran: string[] }

/**
 * A background shell whose result names its output file, a clock the test
 * moves, and `lsof` and `ps` answering from `host`. The shell is pid 100.
 */
function liveShell(on: On, clock: { now: number }, host: Host) {
  on('tool.call', { tool: 'Bash' }, () =>
    ({
      result: { stdout: '', stderr: '', interrupted: false, backgroundTaskId: 'b2' },
      text: `Command running in background with ID: b2. Output is being written to: ${OUTPUT}. You will be notified when it completes.`,
    }) as never,
  )
  on('tool.call', { tool: 'TaskStop' }, () => ({ result: { message: 'no such task', task_id: 'none', task_type: 'none' } }) as never)
  on('clock.now', () => ({ value: clock.now }) as never)
  on('process.run', (_, e) => {
    const argv = (e as { argv: string[] }).argv
    host.ran.push(argv[0] ?? '')
    if (argv[0] === 'lsof') {
      const open = argv.slice(2).filter(path => host.held.has(path))
      return { value: { exitCode: open.length > 0 ? 0 : 1, stdout: open.map(path => `p100\nf1\nn${path}\n`).join(''), stderr: '' } } as never
    }
    const live = (argv[argv.length - 1] ?? '').split(',').filter(pid => host.alive.has(pid))
    return { value: { exitCode: live.length > 0 ? 0 : 1, stdout: live.map(pid => `  ${pid} S\n`).join(''), stderr: '' } } as never
  })
  on('agent.list', () => ({ value: [] }) as never)
}


test('a shell stopped from the app leaves the count once its process is gone', async ($, on) => {
  engine(on, () => 42)
  const clock = { now: 1_000 }
  const host: Host = { held: new Set([OUTPUT]), alive: new Set(['100']), ran: [] }
  liveShell(on, clock, host)
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })

  await $.tool.call({ tool: 'Bash', command: 'sleep 60', run_in_background: true })
  clock.now += 5_000
  await $.tool.call({ tool: 'TaskStop', task_id: 'none' }) // makes the strip check again
  await $.tool.call({ tool: 'TaskStop', task_id: 'none' }) // makes the strip check again
  let ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect((await ui.find({ type: 'Text', text: /background/ }))?.text).toBe('1 background task')
  await ui.unmount()

  // Stopped: its process is gone, and no notification has come.
  host.held.clear()
  host.alive.clear()
  await $.tool.call({ tool: 'TaskStop', task_id: 'none' }) // makes the strip check again
  ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: /background/ })).toBeUndefined()
  await ui.unmount()
})

test('lsof runs once per shell, and ps does the checks after', async ($, on) => {
  engine(on, () => 42)
  const clock = { now: 1_000 }
  const host: Host = { held: new Set([OUTPUT]), alive: new Set(['100']), ran: [] }
  liveShell(on, clock, host)
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })

  await $.tool.call({ tool: 'Bash', command: 'sleep 60', run_in_background: true })
  clock.now += 5_000
  for (let i = 0; i < 4; i++) await $.tool.call({ tool: 'TaskStop', task_id: 'none' }) // makes the strip check again
  expect(host.ran).toEqual(['lsof', 'ps', 'ps', 'ps'])
})

test('a new shell isn’t dropped before it has opened its output file', async ($, on) => {
  engine(on, () => 42)
  const clock = { now: 1_000 }
  liveShell(on, clock, { held: new Set(), alive: new Set(), ran: [] })
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })

  await $.tool.call({ tool: 'Bash', command: 'sleep 60', run_in_background: true })
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect((await ui.find({ type: 'Text', text: /background/ }))?.text).toBe('1 background task')
  await ui.unmount()
})

test('a notification riding along with the person’s prompt still ends its task', async ($, on) => {
  engine(on, () => 42)
  backgroundBash(on, 'b3')
  on('prompt.submit', (_, e) => ({ text: e.text }) as never)
  on('agent.list', () => ({ value: [] }) as never)
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })

  await $.tool.call({ tool: 'Bash', command: 'sleep 60', run_in_background: true })
  await $.prompt.submit({
    text: 'I stopped them.\n<task-notification>\n<task-id>b3</task-id>\n<status>killed</status>\n</task-notification>',
    origin: { kind: 'user' },
  } as never)
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: /background/ })).toBeUndefined()
  await ui.unmount()
})
