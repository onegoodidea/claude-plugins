import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register, SessionContextUsage } from 'claude-code'

import type { ChecklistBoard, Reading } from '../types'

const reading = atom({ plugin: 'context-strip', key: 'reading' } as const, null)

/** Points below the compaction line at which the context part turns to a warning. */
const WARN_WITHIN = 10

/** The context part's text: "Context: 42%". */
export function label(percent: number): string {
  return `Context: ${percent}%`
}

/** Whether the reading is close enough to the compaction line to warn. */
export function isNear(r: Reading): boolean {
  if (r.percent === undefined) return false
  return r.percent >= (r.compactAt ?? 100) - WARN_WITHIN
}

/** "1 now · 2 up next · 3 proposed", as the checklist mod's own band words it. */
export function checklistSummary(board: ChecklistBoard): string {
  const count = (status: string) => board.tasks.filter(task => task.status === status).length
  const parts = [
    [count('in_progress'), 'now'],
    [count('next'), 'up next'],
    [count('proposed'), 'proposed'],
  ] as const
  return parts
    .filter(([n]) => n > 0)
    .map(([n, words]) => `${n} ${words}`)
    .join(' · ')
}

/** Reads the window, plus a free local estimate of where auto-compact starts. */
async function measure($: EngineInterface, context?: SessionContextUsage): Promise<void> {
  let ctx = context
  let compactAt: number | undefined
  try {
    const usage = await $.session.usage({ breakdown: 'summary' })
    ctx = ctx ?? usage.context
    const b = usage.context.breakdown
    if (b && ctx.window > 0) {
      const buffer = b.categories
        .filter(c => c.kind === 'buffer')
        .reduce((sum, c) => sum + c.tokens, 0)
      if (buffer > 0) compactAt = Math.round(((b.rawMaxTokens - buffer) / ctx.window) * 100)
    }
  } catch {
    // No breakdown (no session bound yet): keep the plain figures.
    if (!ctx) ctx = (await $.session.usage()).context
  }
  const next: Reading = { percent: ctx.percent, compactAt }
  await update($, reading, () => next)
  // The desktop app doesn't redraw the band when a value it read changes.
  $.ui.invalidate('ui.render')
}

// Whether the checklist mod is loaded, by its /checklist command; looked up
// when first needed and again after each turn, as plugins can load later.
let hasChecklist: boolean | undefined

async function isChecklistLoaded($: EngineInterface): Promise<boolean> {
  hasChecklist ??= (await $.command.list()).some(
    c => c.name === 'checklist' && c.source === 'plugin' && (c.plugin === undefined || c.plugin === 'checklist'),
  )
  return hasChecklist
}

/**
 * The checklist's summary ("2 up next", or "nothing open"), shown whenever the
 * checklist mod is loaded; undefined when it isn't.
 */
async function checklistPart($: EngineInterface): Promise<string | undefined> {
  if (!(await isChecklistLoaded($))) return undefined
  // Another plugin's values are readable, never writable; the checklist mod's
  // contract isn't laid here (it's no dependency), so the read is untyped.
  const board = (await $.state.get({ plugin: 'checklist', key: 'board' } as never)) as { value?: unknown }
  const tasks = (board.value as ChecklistBoard | undefined)?.tasks
  const text = Array.isArray(tasks) ? checklistSummary({ tasks }) : ''
  return text === '' ? 'nothing open' : text
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const result = await next(e)
    await measure($).catch(() => undefined)
    return result
  })

  on('session.measure', async ($, e, next) => {
    hasChecklist = undefined
    if (e.changed.includes('context')) await measure($, e.context).catch(() => undefined)
    return next(e)
  })

  // The checklist's summary lives at this strip's left end, so its own row goes.
  on('ui.render', { component: 'AbovePromptList' }, async ($, e, next) => {
    if ((await checklistPart($).catch(() => undefined)) === undefined) return next(e)
    return next({ ...e, props: { ...e.props, rows: e.props.rows.filter(row => row.plugin !== 'checklist') } })
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.props.hasSurvey) return next(e)
    const r = await read($, reading)
    const percent = r?.percent
    const checklist = await checklistPart($).catch(() => undefined)
    if (percent === undefined && checklist === undefined) return next(e)

    const { Box, Button, Text } = $.ui.resolve(e)
    const context =
      percent === undefined ? null : r !== null && isNear(r) ? (
        <Text color="warning">{label(percent)}</Text>
      ) : (
        <Text dimColor>{label(percent)}</Text>
      )

    return (
      <Box flexDirection="row" justifyContent="space-between" width={e.props.bodyColumns}>
        {checklist === undefined ? (
          <Box />
        ) : (
          // /checklist opens the checklist's pane; this mod can't open another's.
          <Button
            key="open-checklist"
            plain
            onPress={() => void $.command.run({ command: 'checklist' }).catch(() => undefined)}
          >
            Checklist: <Text dimColor>{checklist}</Text>
          </Button>
        )}
        {context}
      </Box>
    )
  })
}
