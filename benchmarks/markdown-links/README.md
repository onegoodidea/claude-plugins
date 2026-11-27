# markdown-links benchmark

Checks whether the `markdown-links` plugin changes how well Claude handles links in a folder of Markdown notes, and what it costs. Each case runs `claude -p` three ways:

- **plugin**: the plugin loaded with `--plugin-dir`.
- **plain**: no plugin and no instructions.
- **rule**: no plugin; the three lines in `rule.md` appended to the system prompt.

Every run starts from the same made-up notes folder (`fixture.py`: a git repo with people, a project, research notes, meetings, names with spaces and curly apostrophes, and two notes that share a filename). User settings, user CLAUDE.md, user skills and plugins, and MCP servers are left out (`--setting-sources project --strict-mcp-config`), so the arms differ only as listed.

## Cases

| Case | Prompt (short) | Passes when |
|---|---|---|
| `write` | Create a meeting note linking two people, a clinic, a project, and a research note | all five linked, attendees in frontmatter, no broken links |
| `rename` | Jane Doe is now Jane Smith; rename her note | renamed, no link uses the old name, no broken links |
| `folder` | Move `Research` into `Archive` | moved, the unrelated `Archive/Pricing.md` gains no links, no broken links |
| `delete` | Delete `Research/Pricing.md` | deleted, its links left in place and not repointed, and the reply asks what to do |
| `shell-move` | Move two meeting notes into `Archive/Meetings` with one shell command | moved, no broken links |
| `git-mv` | The same move, with `git mv` required | moved, no broken links |
| `finder-move` | “I moved Research into Archive in Finder. Make sure everything still works.” (the folder is already moved) | folder left where it is, no broken links |
| `typo` | Fix the spelling mistake in `Tasks.md` | fixed, nothing else changed (measures overhead) |

`linkcheck.py` grades links without importing the plugin: a body link passes when its percent-decoded path, resolved from its note, names an existing file.

## Running it

```bash
python3 run.py --trials 3 --jobs 3
```

```bash
python3 summarize.py results/<run>
```

Options: `--arms plugin,plain,rule`, `--cases write,rename`, `--model sonnet`. Each run is a full Claude Code session on your own account. Results, workspaces, and transcripts go to `results/`, which git ignores.

## Results, 2026-11-27 (Sonnet, 3 trials per case and arm)

| Case | plugin | plain | rule |
|---|---|---|---|
| write | 3/3 | 3/3 | 3/3 |
| rename | 3/3 | 3/3 | 3/3 |
| folder | 3/3 | 0/3: the moved note’s own outgoing link broke | 3/3 |
| delete | 3/3 | 1/3: didn’t ask what to do with the links | 3/3 |
| shell-move | 3/3 | 0/3: 5 broken links | 1/3: 3.3 broken links on average |
| git-mv | 3/3 (2 of 3 fixed by the hook naming `relink`) | 0/3: 5 broken links | 3/3 |
| finder-move | 3/3 | 3/3 | 3/3 |
| typo | 3/3 | 3/3 | 3/3 |
| **Total** | **24/24** | **13/24** | **22/24** |
| Cost per task (mean) | $0.083 | $0.074 | $0.080 |
| Turns per task (mean) | 5.7 | 4.4 | 5.3 |
| Time per task (mean) | 10.3 s | 9.5 s | 10.8 s |

The first `shell-move` version moved notes between folders at the same depth, where no relative link can break; it was replaced and its runs are left out above.
