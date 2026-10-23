// How each status looks: its SVG circle, the terminal's glyph, and the label
// a screen reader gives the circle.

import type { TaskStatus } from '../types'

/** The terminal draws no SVG: it gets a glyph instead. */
export const GLYPH: Record<TaskStatus, string> = {
  in_progress: '◐',
  next: '○',
  proposed: '·',
  done: '●',
}

// 16px circles in the style of the app's task list: dashed for not started,
// half filled for in progress, a check for done. Gray follows the system theme.
const svg = (body: string) =>
  `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16" fill="none">` +
  `<style>.s{stroke:#2b2b2b}.f{fill:#2b2b2b}.m{stroke:#a3a3a3}` +
  `@media (prefers-color-scheme: dark){.s{stroke:#e5e5e5}.f{fill:#e5e5e5}.m{stroke:#6f6f6f}}</style>` +
  body +
  `</svg>`
export const ICON: Record<TaskStatus, string> = {
  next: svg(`<circle class="m" cx="8" cy="8" r="6.25" stroke-width="1.25" stroke-dasharray="2.4 2.2"/>`),
  proposed: svg(`<circle class="m" cx="8" cy="8" r="6.25" stroke-width="1" stroke-dasharray="0.8 2.2" stroke-linecap="round"/>`),
  in_progress: svg(
    `<circle class="s" cx="8" cy="8" r="6.25" stroke-width="1.25"/>` +
      `<path class="f" d="M8 3.75a4.25 4.25 0 0 1 0 8.5z"/>`,
  ),
  done: svg(
    `<circle class="m" cx="8" cy="8" r="6.25" stroke-width="1.25"/>` +
      `<path class="m" d="M5.2 8.2l1.9 1.9 3.7-3.8" stroke-width="1.25" stroke-linecap="round" stroke-linejoin="round"/>`,
  ),
}
export const ALT: Record<TaskStatus, string> = {
  next: 'Not started',
  proposed: 'Proposed',
  in_progress: 'In progress',
  done: 'Done',
}
