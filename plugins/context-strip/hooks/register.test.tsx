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
