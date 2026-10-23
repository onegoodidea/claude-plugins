# One Good Idea plugins for Claude Code

A Claude Code plugin marketplace from [One Good Idea](https://github.com/onegoodidea). Add it once, and new plugins show up here as they’re published.

## Plugins

| Plugin | What it does |
| --- | --- |
| [checklist](plugins/checklist) | A pane beside the chat that keeps a session’s follow-ups, so you can come back to a session and see what’s left: Now, Up next, Proposed, and Done. |

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

In the Claude desktop app, where `/plugin` doesn’t run: click **+** next to the prompt box, then **Plugins**, **Add marketplace** with `onegoodidea/claude-plugins`, then **Add plugin**.

## Updates

Plugins here have no fixed version: each update is a new commit. Claude Code doesn’t auto-update marketplaces outside Anthropic’s by default, so update from `/plugin`, or turn on auto-update for this marketplace there.

## License

MIT; see [LICENSE](LICENSE).
