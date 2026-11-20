# Context strip

A Claude Code plugin that shows how full a session’s context window is in a row directly above the prompt, so you can check it at a glance without opening the session rail.

The row reads **Context: 14%** at its right end. It turns to the warning color within 10 points of where auto-compact starts. Nothing shows until the session’s first response reports a reading.

## With the checklist plugin

When the [checklist](../checklist) plugin is loaded too, the strip carries its summary at the left end, so the two share one row:

```
Checklist: 2 up next · 1 proposed                          Context: 14%
```

- It shows whether the checklist pane is open or closed.
- With no open items (or a checklist that hasn’t been used yet), it reads **Checklist: nothing open**.
- Click it to open the checklist pane. A click during a turn opens the pane once the turn ends.
- The checklist’s own row above the prompt is hidden while the strip carries its summary.

Without the checklist plugin, the strip shows the context percentage alone.

## Install

At the prompt of a Claude Code terminal session:

```
/plugin install context-strip --marketplace onegoodidea/claude-plugins
```

Answer `y` to add the marketplace, then pick a scope (user scope makes it available in every session).

From a shell:

```
claude plugin install context-strip --marketplace onegoodidea/claude-plugins
```

In the Claude desktop app, where `/plugin` doesn’t run: click **+** next to the prompt box, then **Plugins**, **Add marketplace** with `onegoodidea/claude-plugins`, then **Add plugin**. A plugin installed from a terminal at user scope also loads in the desktop app’s sessions.

## Limits

- **Updates:** the percentage moves after each turn, when Claude Code measures the session, not while a turn runs.
- **Checklist coupling:** the strip reads the checklist plugin’s saved list (`board`) and matches its summary wording. If those change in the checklist plugin, update `hooks/register.tsx` here too.

## Development

The plugin is a set of Claude Code function hooks in `hooks/register.tsx`.

From the repository root:

```
claude plugin validate plugins/context-strip
claude plugin test plugins/context-strip
```

To run it from a local checkout, add the `plugins/context-strip` folder to `CLAUDE_CODE_PLUGIN_DIRS` in the `env` block of `~/.claude/settings.json`.

Licensed under MIT; see [LICENSE](../../LICENSE).
