// What the model reads: the system prompt's guidance, the review prompt, and
// the tool's description and input schema.

import { STATUSES } from './board'
import { TOOL } from './state'

export const GUIDANCE = `# Checklist

A pane beside the chat, the Checklist, lists this session's follow-ups, kept with the ${TOOL} tool, so the person can see, days later, what was discussed but not yet done.

- When you suggest a follow-up, or the person mentions something to do later that is not being done now, add it with status "proposed". Write each as a short imperative phrase (under ~10 words).
- When the person accepts a proposed item ("yes, later", "add that"), set it to "next". When you start an item, set it to "in_progress"; when it is finished, "done". The pane shows in-progress items as "Now".
- When you start substantial work that isn't on the list, add one item for it as "in_progress": the task as the person would name it, not its steps. Set it to "done" when finished, or back to "next" if it's set aside unfinished.
- When the person asks to remove, reword, accept, reorder, or change an item, do it with the tool. They may refer to items by number ("drop #3").
- The pane already picks up New task cards on its own: don't add those to it. Don't add the steps of the app's per-request task list either.
- Don't add duplicates. Call the tool with no arguments to see the list, for example when a resumed session picks up again.`

export const REVIEW_PROMPT = `Review this session's open task items with me. Read the list with the ${TOOL} tool, then go through the in-progress, up-next, and proposed items. For each, ask whether to keep it, drop it, or turn it into a New task card (its own session), and apply my answers with the tool. Keep it quick: group them in one question where you can.`

export const DESCRIPTION = `Keeps the session's task list shown in the pane beside the chat. All fields are optional and apply in one call: "add" new items, "update" items by id (text or status), "remove" items by id. Statuses: "proposed" (suggested, not yet accepted by the person), "next" (accepted, not started), "in_progress", "done". Call with no arguments to read the list. "order" reorders items: pass ids in the order wanted ("move #4 to the top of Up next" is order [4]). Returns the full list with ids, each group in its order.`

export const INPUT_SCHEMA = {
  type: 'object',
  properties: {
    add: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          text: { type: 'string' },
          status: { type: 'string', enum: STATUSES },
        },
        required: ['text'],
      },
    },
    update: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          id: { type: 'integer' },
          text: { type: 'string' },
          status: { type: 'string', enum: STATUSES },
        },
        required: ['id'],
      },
    },
    remove: { type: 'array', items: { type: 'integer' } },
    order: {
      type: 'array',
      items: { type: 'integer' },
      description: 'Item ids in the order they should show; listed items go first in their group, in this order.',
    },
  },
}
