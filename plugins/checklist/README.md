# Checklist

A Claude Code plugin that keeps a pane beside the chat listing a session’s follow-ups, so when you come back to a session days later you can see what you talked about doing and haven’t gotten to yet.

Claude adds follow-ups it suggests as **Proposed**. You accept the ones you want, and they move to **Up next**. What’s being worked on shows under **Now**, and finished items move to **Done**, most recent first. Each session keeps its own list.

## Install

At the prompt of a Claude Code terminal session:

```
/plugin install checklist --marketplace onegoodidea/claude-plugins
```

Answer `y` to add the marketplace, then pick a scope (user scope makes it available in every session).

From a shell:

```
claude plugin install checklist --marketplace onegoodidea/claude-plugins
```

In the Claude desktop app, where `/plugin` doesn’t run: click **+** next to the prompt box, then **Plugins**, **Add marketplace** with `onegoodidea/claude-plugins`, then **Add plugin**. A plugin installed from a terminal at user scope also loads in the desktop app’s sessions.

## Using it

- **Open the pane:** it opens on its own when the list has open items. Otherwise run `/checklist`, or click the band above the prompt (“Checklist: 2 up next”), which shows while the pane is closed.
- **Add a task:** type in the “Add a task” field under Up next and press Enter. It goes straight to Up next, and the field stays ready for the next one.
- **Edit an item:** double-click its text. Enter saves; Esc, Cancel, or clicking away backs out.
- **Reorder Up next:** drag an item up or down.
- **Buttons:**
  - Now: ⏸ (back to the top of Up next), ✓, ×
  - Up next: Start, ✓, ×
  - Proposed: Accept, ×
  - Done: ×
- **Remove an item:** press × once; it turns into “Remove?”. Press it again within 3 seconds to remove.
- **Ask Claude:** “drop #3,” “move #6 to the top,” “mark #2 done,” and so on. Claude manages the list with the `mcp__checklist__tasks` tool.
- **New Task cards:** in the desktop app, cards Claude proposes for separate sessions show up as Proposed items, and dismissing a card removes its item.

### Commands

| Command | What it does |
| --- | --- |
| `/checklist` | Opens the pane. |
| `/checklist review` | Has Claude walk through the open items with you: keep, drop, or turn into a separate session. |
| `/checklist wrap <factor>` | Tunes line wrapping in the desktop app (default 1.2; higher fits more on a line). |

Before a `/clear` empties a list with open items, the first `/clear` starts that review instead. A second `/clear` within 10 minutes goes through.

## Limits

- **Editing:** double-click only, so it needs a mouse. The mobile app has no text fields and can’t edit.
- **Add field:** the app’s own text field, so it’s narrow and has a ↵ button.
- **Dragging:** moves a row at a time.
- **Wrapping:** the desktop app draws a proportional font, which the plugin can’t measure, so it estimates line length. If lines break too early or run long, adjust `/checklist wrap`.

## Development

The plugin is a set of Claude Code function hooks. `hooks/register.tsx` wires the hooks, `hooks/pane.tsx` draws the pane, `hooks/list.tsx` draws each group’s text (and handles double-click and drag), and `hooks/board.ts` holds the list logic.

From the repository root:

```
claude plugin validate plugins/checklist
claude plugin test plugins/checklist
```

To run it from a local checkout, add the `plugins/checklist` folder to `CLAUDE_CODE_PLUGIN_DIRS` in the `env` block of `~/.claude/settings.json`.

Licensed under MIT; see [LICENSE](../../LICENSE).
