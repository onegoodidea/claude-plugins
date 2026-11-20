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

/** "1 background task", "3 background tasks". */
export function tasksLabel(count: number): string {
  return `${count} background ${count === 1 ? 'task' : 'tasks'}`
}

/**
 * The ids a task notification reports as ended: each `<task-id>` whose
 * `<status>` is anything but `running` (a monitor's events carry none).
 */
export function endedTaskIds(text: string): string[] {
  const ended: string[] = []
  for (const block of text.split('</task-notification>')) {
    const id = /<task-id>([^<]+)<\/task-id>/.exec(block)?.[1]?.trim()
    const status = /<status>([^<]+)<\/status>/.exec(block)?.[1]?.trim()
    if (id && status && status !== 'running') ended.push(id)
  }
  return ended
}

/** The output file a background shell's result names ("Output is being written to: …"). */
export function outputPath(text: string | undefined): string | undefined {
  return text === undefined ? undefined : /Output is being written to: (\S+?\.output)\b/.exec(text)?.[1]
}

// Background shells, monitors and workflows started in this process: task id to
// a shell's output file and, once found, the processes holding it. The engine
// lists agents but not these, so they're kept from the calls that started them
// until they end. A reload starts over.
type Tracked = { path?: string; pids?: string[]; since: number }
const tracked = new Map<string, Tracked>()

/** How long a new shell gets to open its output file before its absence counts. */
const GRACE_MS = 2000

const fileName = (path: string) => path.slice(path.lastIndexOf('/') + 1)

/**
 * The processes holding each file open, by file name, from `lsof -Fpn` output:
 * a "p<pid>" line starts each process, an "n<path>" line names each file. By
 * name, as lsof prints the resolved path (/private/tmp for /tmp).
 */
export function holders(lsof: string): Map<string, string[]> {
  const byFile = new Map<string, string[]>()
  let pid: string | undefined
  for (const line of lsof.split('\n')) {
    if (line.startsWith('p')) pid = line.slice(1)
    else if (line.startsWith('n') && pid !== undefined) {
      const name = fileName(line.slice(1))
      const pids = byFile.get(name) ?? []
      if (!pids.includes(pid)) pids.push(pid)
      byFile.set(name, pids)
    }
  }
  return byFile
}

/** The live pids in `ps -o pid=,stat=` output, a zombie (stat Z) left out. */
export function livePids(ps: string): Set<string> {
  const live = new Set<string>()
  for (const line of ps.split('\n')) {
    const [pid, stat] = line.trim().split(/\s+/)
    if (pid && stat && !stat.startsWith('Z')) live.add(pid)
  }
  return live
}

/**
 * Drops each tracked shell that has ended, stopped from the app included, whose
 * notification can wait for the next turn. A shell's processes are found once,
 * by who holds its output file open (`lsof`, a scan of every process's files),
 * and then checked by pid (`ps`, a hundredth of the cost). Without either
 * command, notifications still apply.
 */
async function pruneEndedShells($: EngineInterface): Promise<void> {
  const now = await $.clock.now()
  const shells = [...tracked].filter(([, t]) => t.path !== undefined && now - t.since >= GRACE_MS)

  const unfound = shells.filter(([, t]) => t.pids === undefined)
  if (unfound.length > 0) {
    // `lsof` exits 1, listing nothing, when no process holds any of them.
    const held = await $.process.run(['lsof', '-Fpn', ...unfound.map(([, t]) => t.path!)], { timeoutMs: 5000 })
    const byFile = holders(held.stdout)
    for (const [id, t] of unfound) {
      const pids = byFile.get(fileName(t.path!))
      if (pids === undefined) tracked.delete(id)
      else t.pids = pids
    }
  }

  const found = shells.filter(([id, t]) => tracked.has(id) && t.pids !== undefined && !unfound.some(([u]) => u === id))
  if (found.length > 0) {
    // `ps -p` exits 1, listing nothing, when none of them is alive.
    const pids = found.flatMap(([, t]) => t.pids!)
    const listed = await $.process.run(['ps', '-o', 'pid=,stat=', '-p', pids.join(',')], { timeoutMs: 5000 })
    const live = livePids(listed.stdout)
    for (const [id, t] of found) if (!t.pids!.some(pid => live.has(pid))) tracked.delete(id)
  }
}

const RUNNING_AGENT = new Set(['pending', 'running', 'waiting'])

/** Every background task running now: the tracked ones plus the session's live agents. */
async function runningTasks($: EngineInterface): Promise<number> {
  const agents = await $.agent.list().catch(() => [])
  return tracked.size + agents.filter(a => RUNNING_AGENT.has(a.status)).length
}

// While anything runs, the strip redraws every few seconds so the count follows
// agents and tasks that end; the poll stops with the last one.
let poll: { cancel: () => void } | undefined
let lastCount = 0

async function refreshTasks($: EngineInterface): Promise<void> {
  await pruneEndedShells($).catch(() => undefined)
  const count = await runningTasks($)
  if (count !== lastCount) {
    lastCount = count
    $.ui.invalidate('ui.render')
  }
  if (count > 0 && poll === undefined) {
    poll = $.clock.every(3000, () => void refreshTasks($).catch(() => undefined))
  } else if (count === 0 && poll !== undefined) {
    poll.cancel()
    poll = undefined
  }
}

/**
 * Opens the app's own background tasks view: the desktop's Tasks pane, or the
 * terminal's /tasks dialog.
 */
async function openTasks($: EngineInterface, surface: string): Promise<void> {
  if (surface === 'desktop') {
    await $.tool.call({ tool: 'mcp__ccd_view__show_pane', pane: 'tasks' } as never)
  } else {
    await $.command.run({ command: 'tasks' })
  }
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const result = await next(e)
    await measure($).catch(() => undefined)
    await refreshTasks($).catch(() => undefined)
    return result
  })

  // A background shell (run_in_background, or moved there with ctrl+b), a monitor
  // or a workflow: its task id comes back in the call's result.
  on('tool.call', async ($, e, next) => {
    const ran = await next(e)
    if (ran.deny === undefined && ran.isError !== true) {
      const result = ran.result as { backgroundTaskId?: unknown; taskId?: unknown } | undefined
      const id =
        e.tool === 'Bash' ? result?.backgroundTaskId : e.tool === 'Monitor' || e.tool === 'Workflow' ? result?.taskId : undefined
      if (typeof id === 'string' && id !== '') {
        tracked.set(id, { path: e.tool === 'Bash' ? outputPath(ran.text) : undefined, since: await $.clock.now().catch(() => 0) })
      }
      if (e.tool === 'TaskStop') {
        const stopped = e.task_id ?? e.shell_id
        if (stopped !== undefined) tracked.delete(stopped)
      }
    }
    if (e.tool === 'Agent' || e.tool === 'Bash' || e.tool === 'Monitor' || e.tool === 'Workflow' || e.tool === 'TaskStop') {
      await refreshTasks($).catch(() => undefined)
    }
    return ran
  }).catch(($, e, next) => next(e))

  // A background task's notification says when it ended. It can arrive on its
  // own or ride along with the person's next prompt, so every submission is read.
  on('prompt.submit', async ($, e, next) => {
    const ended = endedTaskIds(e.text).filter(id => tracked.delete(id))
    if (ended.length > 0 || e.origin.kind === 'task-notification') await refreshTasks($).catch(() => undefined)
    return next(e)
  }).catch(($, e, next) => next(e))

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
    const tasks = await runningTasks($).catch(() => 0)
    if (percent === undefined && checklist === undefined && tasks === 0) return next(e)

    const { Box, Button, Text } = $.ui.resolve(e)
    const surface = e.surface
    const context =
      percent === undefined ? null : r !== null && isNear(r) ? (
        <Text color="warning">{label(percent)}</Text>
      ) : (
        <Text dimColor>{label(percent)}</Text>
      )
    const right =
      tasks === 0 ? (
        context
      ) : (
        <Box flexDirection="row" gap={2}>
          <Button key="open-tasks" plain label={tasksLabel(tasks)} onPress={() => void openTasks($, surface).catch(() => undefined)}>
            <Text dimColor>{tasksLabel(tasks)}</Text>
          </Button>
          {context}
        </Box>
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
        {right}
      </Box>
    )
  })
}
