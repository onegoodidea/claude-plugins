# Markdown links

A Claude Code plugin that keeps links between Markdown notes portable. Notes written in a notes app pick up `[[wikilinks]]` that only work inside that app. This plugin converts them to relative Markdown links that work on GitHub, in any editor, and in the Claude desktop app’s file viewer. It then keeps them correct as Claude writes, edits, and moves notes.

- **Convert once:** body wikilinks become relative Markdown links. Nothing else in the files changes.
- **Write links correctly:** Claude asks the script for a link instead of working out a relative path.
- **Catch mistakes in the same turn:** after Claude writes or edits a `.md` file, a hook reports broken links and stray body wikilinks.
- **Move without breaking:** `mv` moves or renames a note or folder and rewrites every affected link.

Python 3.9 or newer, standard library only, no network.

## Install

At the prompt of a Claude Code terminal session:

```
/plugin install markdown-links --marketplace onegoodidea/claude-plugins
```

Answer `y` to add the marketplace, then pick a scope (user scope makes it available in every session).

From a shell:

```
claude plugin install markdown-links --marketplace onegoodidea/claude-plugins
```

In the Claude desktop app, where `/plugin` doesn’t run: click **+** next to the prompt box, then **Plugins**, **Add marketplace** with `onegoodidea/claude-plugins`, then **Add plugin**.

## Roots

The plugin acts only on a **root**: a folder containing `.markdown-links.json`. Every command finds the root by walking up from the path it’s given, and links resolve within it. Outside a root, every command except `init` refuses and the hook does nothing.

The file holds one setting, `exclude`, a list of folders (relative to the root) that commands skip:

```json
{ "exclude": ["Templates", "Archive/old"] }
```

Dot-folders such as `.git` are always skipped. An excluded folder is invisible: its files aren’t checked, converted, moved, or linkable, so a link into one reports as broken. Exclude only folders nothing links to.

## Link rules

- **Body links** are `[text](relative/path.md)`, relative to the note containing the link, with each path segment percent-encoded (`%20` for spaces, UTF-8 escapes for non-ASCII). Same-folder links have no `./`. Anchors keep the heading text, encoded: `Note.md#Some%20Heading`. Images use `![alt](path)`.
- **Frontmatter links** stay quoted wikilinks, `"[[Note Name]]"`, by filename without `.md`. They mark a value as a reference to a note. Each must match exactly one note.
- **Skipped:** fenced code blocks, inline code, and HTML comments. External links (`https:`, `mailto:`, and other schemes) are never checked or rewritten.
- **Wikilink matching** is by filename, case-insensitive, with `.md` optional. `[[Folder/Note]]` matches the note whose path ends that way. A bare name shared by several notes is ambiguous, so qualify it.
- **Block references** (`[[Note#^abc123]]`) have no portable form. `convert` leaves them and `check` reports them as warnings.
- **Root-absolute** Markdown links (`/People/Jane.md`) are errors. `convert` rewrites them relative to the note. A bare filename (`[Decisions](Decisions.md)`) is a same-folder link like any other, never matched by name elsewhere in the root. Any link that doesn’t resolve from its note is broken: `convert` leaves it for you, and `relink` repairs it if its target moved, or if it’s a bare filename for a note in another folder (the shortest-path links a notes app writes).

## Commands

Every problem prints as one line, `error:` or `warning:`, then the file path relative to the root, the line number, and a message. Exit codes: `0` clean, `1` errors found or the command refused, `2` usage error. Add `--json`, before or after the command, for machine-readable output: `check` prints a list of `{"level", "file", "line", "message"}` objects, and `convert` and `mv` print an object holding their changes and findings.

### `init [folder]`

Creates `.markdown-links.json` in the folder if it’s missing. If the folder has `.obsidian/app.json`, it also sets Obsidian to write relative Markdown links and update links on rename, so links made in Obsidian match.

```
markdown-links.py init ~/Notes
```

### `check [path]`

Checks the whole root, or one file when `path` is a file.

```
markdown-links.py check ~/Notes
```

```
warning: Bad.md:1: wikilink matches no file: [[Nope]]
error: Bad.md:1: broken link: [x](Missing.md)
```

Errors: a body link to a missing file (or one that differs only in case or Unicode form), a root-absolute link (`/People/Jane.md`), a body wikilink that matches exactly one note (it should be a Markdown link), and a frontmatter wikilink that matches no note or more than one. Warnings: unresolved or ambiguous body wikilinks, note transclusions (`![[Note]]`), block references, a missing heading anchor, and links that leave the root.

### `convert [root] [--dry-run]`

Rewrites every body wikilink that matches exactly one file, and rewrites root-absolute Markdown links (`/People/Jane.md`) to note-relative paths. `[[Name|Alias]]` becomes `[Alias](path)`, `[[Name#Heading]]` becomes `[Name](path#Heading)`, `![[image.png]]` becomes `![](path)`, and an embedded attachment such as a PDF becomes `[file.pdf](path)`. An embed’s alias becomes the image’s alt text (`![[image.png|A chart]]` becomes `![A chart](path)`) or the attachment’s link text; a size such as `|300` or `|300x200` has no Markdown form, so it’s dropped with a warning. Frontmatter, code, ambiguous, unresolved, and transcluded links are left alone and listed.

It works on a whole root: give it the root folder (or run it there), and it refuses a subfolder. It prints one line per link it changes, the error and warning counts before and after, then the errors left and the links it couldn’t convert. With `--dry-run` it writes nothing, and “after” is what a real run would leave.

```
markdown-links.py convert --dry-run ~/Notes
markdown-links.py convert ~/Notes
```

```
would convert Projects/Plan.md:3: [[Jane Doe]] -> [Jane Doe](../People/Jane%20Doe.md)
would convert Projects/Plan.md:7: ![[chart.png|Q3]] -> ![Q3](chart.png)
would convert 2 links in 1 file
before: 2 errors, 1 warning
after: 0 errors, 1 warning
warning: Projects/Plan.md:9: wikilink matches no file: [[Old Plan]]
```

### `link <from-note> <to> [--text TEXT] [--heading HEADING]`

Prints a correct body link from one note to another. `<to>` is a note name or a path. The link text defaults to the target’s name. It fails if `<to>` is ambiguous or missing.

```
markdown-links.py link Projects/Plan.md "Jane Doe" --text Jane --heading Intro
```

```
[Jane](../People/Jane%20Doe.md#Intro)
```

### `mv <src> <dst> [--dry-run]`

Moves or renames a file or folder within one root and keeps links correct:

- Links in other notes that point into the moved set are rewritten.
- Relative links inside the moved notes that point outside the set are rewritten for the new location.
- When a note’s filename changes, frontmatter wikilinks and remaining body wikilinks to it are updated across the root. If the new name is shared with another note, they’re path-qualified.
- If a move makes an existing bare wikilink ambiguous, those wikilinks are path-qualified to the note they pointed at before.

It refuses, changing nothing, if the destination exists or leaves the root. It computes every edit before touching the disk. Inside a git work tree it uses `git mv`, so history follows. It prints every file it changed.

```
markdown-links.py mv "People/Jane Doe.md" People/Jane.md
```

```
moved People/Jane Doe.md -> People/Jane.md
updated People/Jane.md
updated Projects/Plan.md
```

Moves done outside the script (shell `mv`, `git mv`, a file manager) aren’t caught as they happen. Use `relink` to repair them.

### `relink [root] [--dry-run] [--json]`

Repairs links broken by moves made outside `mv`: body Markdown links whose target is gone, and frontmatter wikilinks that match no note. It follows renames git recorded (staged or committed) when the root is in a work tree, and otherwise looks for a file with the same name. For a path git tracked, only a file git doesn’t have yet counts, so a deleted note’s links aren’t pointed at another note of the same name. A link whose target differs only in case is rewritten to the spelling on disk. It prints one line per link it changes, then an error for each broken link it couldn’t repair. With `--dry-run` it writes nothing. It never rewrites a link to a file deleted in git (reported as `broken link (deleted in git)`); the skill has Claude list those links and ask what to do with each.

```
markdown-links.py relink --dry-run ~/Notes
markdown-links.py relink ~/Notes
```

## How Claude uses it

The skill tells Claude to ask `link` for body links, to move and rename with `mv`, to run `relink` after a move made another way, to fix the link named in any hook error, and to run `check` after bulk edits. The hook runs `check` on each `.md` file Claude writes or edits. On errors it reports them to Claude in the same turn. It also runs after `Bash` commands that contain `mv`, `git mv`, `rm`, or `git rm`: if the command left broken links in a root, it prints one line naming the count and the `relink` command to run. Warnings alone stay quiet, so notes with old unresolved wikilinks don’t nag on every edit.

## Running it from a shell

The script is inside the installed plugin:

```
python3 ~/.claude/plugins/cache/onegoodidea/markdown-links/<version>/skills/markdown-links/scripts/markdown-links.py check ~/Notes
```

The `<version>` folder changes when the plugin updates. An alias or a symlink to the current one saves retyping.

## Adopting it on an existing folder

1. Update whatever else writes links into the folder (other skills, routines, scripts) so it writes relative Markdown links, or the hook will report every wikilink it adds. This plugin doesn’t change them.
2. `init` the folder.
3. `convert --dry-run`, review the list, then `convert`.
4. `relink`. It repairs the shortest-path links a notes app wrote (`[Jane](Jane%20Doe.md)` for a note in another folder), which are now broken same-folder links.
5. `check` and fix what’s left. Ambiguous and unresolved wikilinks are listed for you to fix by hand.

## With Obsidian open

Safe with Obsidian open. In a test with a notes folder open in Obsidian, `mv` of a linked note and of a whole folder left every note as `mv` wrote it; Obsidian changed only its own `.obsidian/workspace.json`.

## Credit

Parsing approach adapted from m4bwav/obsidian-notes (MIT).

Licensed under MIT; see [LICENSE](../../LICENSE).
