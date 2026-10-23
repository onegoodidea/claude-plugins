// The list itself, as pure functions over a board: reading a saved one,
// adding, ordering, changing status, and the text the tool answers with.

import type { Board, Task, TaskStatus } from '../types'

export const EMPTY: Board = { tasks: [], nextId: 1 }

export const STATUSES: readonly TaskStatus[] = ['proposed', 'next', 'in_progress', 'done']
export const OPEN: readonly TaskStatus[] = ['proposed', 'next', 'in_progress']

export type TasksInput = {
  add?: { text: string; status?: TaskStatus }[]
  update?: { id: number; text?: string; status?: TaskStatus }[]
  remove?: number[]
  order?: number[]
}

export const isStatus = (value: unknown): value is TaskStatus =>
  STATUSES.includes(value as TaskStatus)

export const isOpen = (task: Task) => OPEN.includes(task.status)

/**
 * Reads a saved board, including ones from the first version of this mod
 * ("suggested" for Up next). Entries that aren't tasks are dropped, so one bad
 * value can't break the session; `nextId` is kept past every id in use.
 */
export function normalize(saved: unknown): Board | undefined {
  const value = saved as { tasks?: unknown; nextId?: unknown } | null | undefined
  if (value === null || typeof value !== 'object' || !Array.isArray(value.tasks)) return undefined
  const tasks: Task[] = []
  for (const entry of value.tasks as unknown[]) {
    if (entry === null || typeof entry !== 'object') continue
    const raw = entry as Omit<Partial<Task>, 'status'> & { status?: unknown }
    if (typeof raw.id !== 'number' || !Number.isFinite(raw.id)) continue
    const status: TaskStatus = raw.status === 'suggested' ? 'next' : isStatus(raw.status) ? raw.status : 'next'
    const task: Task = { id: raw.id, text: String(raw.text ?? ''), status }
    if (typeof raw.cardId === 'string') task.cardId = raw.cardId
    if (status === 'done' && typeof raw.doneAt === 'number') task.doneAt = raw.doneAt
    tasks.push(task)
  }
  const pastLast = tasks.reduce((max, task) => Math.max(max, task.id + 1), 1)
  const saved_ = typeof value.nextId === 'number' ? value.nextId : 1
  return { tasks, nextId: Math.max(saved_, pastLast) }
}

export function addTask(current: Board, text: string, status: TaskStatus, cardId?: string): Board {
  const task: Task = withStatus({ id: current.nextId, text, status: 'next' }, status)
  if (cardId !== undefined) task.cardId = cardId
  return { ...current, tasks: [...current.tasks, task], nextId: current.nextId + 1 }
}

/** Listed ids first, in the order given; the rest keep their order after them. */
export function reorder(current: Board, ids: readonly number[]): Board {
  const rank = (task: Task) => {
    const at = ids.indexOf(task.id)
    return at === -1 ? ids.length : at
  }
  const tasks = current.tasks
    .map((task, index) => ({ task, index }))
    .sort((a, b) => rank(a.task) - rank(b.task) || a.index - b.index)
    .map(({ task }) => task)
  return { ...current, tasks }
}

/** Swaps an item with its neighbor in the same group (-1 up, 1 down). */
export function nudge(current: Board, id: number, direction: -1 | 1): Board {
  const tasks = current.tasks.slice()
  const at = tasks.findIndex(task => task.id === id)
  const task = tasks[at]
  if (task === undefined) return current
  let other = at + direction
  while (other >= 0 && other < tasks.length && tasks[other]?.status !== task.status) other += direction
  const neighbor = tasks[other]
  if (neighbor === undefined) return current
  tasks[other] = task
  tasks[at] = neighbor
  return { ...current, tasks }
}

/**
 * A task with a new status. Marking it done records when (`doneAt`), so Done
 * lists the most recently finished first; leaving Done drops it.
 */
export function withStatus(task: Task, status: TaskStatus, now = Date.now()): Task {
  // Unchanged keeps its place, a done item's included (a rename doesn't move it).
  if (status === task.status) return task
  const { doneAt: _dropped, ...rest } = task
  return status === 'done' ? { ...rest, status, doneAt: now } : { ...rest, status }
}

/** Done items, most recently finished first; ones finished before times were kept follow, newest first. */
export function newestDone(tasks: readonly Task[]): Task[] {
  const done = tasks.filter(task => task.status === 'done')
  const timed = done.filter(task => task.doneAt !== undefined).sort((a, b) => (b.doneAt ?? 0) - (a.doneAt ?? 0))
  const untimed = done.filter(task => task.doneAt === undefined).reverse()
  return [...timed, ...untimed]
}

export function setStatus(current: Board, id: number, status: TaskStatus): Board {
  return {
    ...current,
    tasks: current.tasks.map(task => (task.id === id ? withStatus(task, status) : task)),
  }
}

export function applyTasks(current: Board, input: TasksInput): { next: Board; notes: string[] } {
  const notes: string[] = []
  let next = current

  for (const id of input.remove ?? []) {
    if (!next.tasks.some(task => task.id === id)) notes.push(`No item #${id} to remove.`)
    next = { ...next, tasks: next.tasks.filter(task => task.id !== id) }
  }
  for (const change of input.update ?? []) {
    if (!next.tasks.some(task => task.id === change.id)) {
      notes.push(`No item #${change.id} to update.`)
      continue
    }
    const text = change.text?.trim()
    next = {
      ...next,
      tasks: next.tasks.map(task =>
        task.id === change.id
          ? withStatus({ ...task, text: text ? text : task.text }, isStatus(change.status) ? change.status : task.status)
          : task,
      ),
    }
  }
  for (const item of input.add ?? []) {
    const text = item.text?.trim()
    if (text) next = addTask(next, text, isStatus(item.status) ? item.status : 'proposed')
  }
  if (input.order !== undefined) {
    for (const id of input.order) {
      if (!next.tasks.some(task => task.id === id)) notes.push(`No item #${id} to order.`)
    }
    next = reorder(next, input.order)
  }

  return { next, notes }
}

export function describe(tasks: readonly Task[]): string {
  if (tasks.length === 0) return 'The list is empty.'
  const lines: string[] = []
  for (const status of ['in_progress', 'next', 'proposed', 'done'] as const) {
    const listed = status === 'done' ? newestDone(tasks) : tasks.filter(one => one.status === status)
    for (const task of listed) {
      lines.push(`#${task.id} [${status}] ${task.text}`)
    }
  }
  return lines.join('\n')
}

export function summary(tasks: readonly Task[]): string {
  const count = (status: TaskStatus) => tasks.filter(task => task.status === status).length
  const parts = [
    [count('in_progress'), 'now'],
    [count('next'), 'up next'],
    [count('proposed'), 'proposed'],
  ] as const
  return parts
    .filter(([n]) => n > 0)
    .map(([n, label]) => `${n} ${label}`)
    .join(' · ')
}
