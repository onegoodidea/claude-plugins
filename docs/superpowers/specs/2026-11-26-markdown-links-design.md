# markdown-links: design

Status: approved 2026-11-26. Amended 2026-11-27: `relink` and the hook after `Bash` moves.

## Intent

Folders of Markdown notes often start life in a notes app and pick up that app’s link syntax: `[[wikilinks]]` resolved by filename. Those links only work inside the app. Outside it (GitHub, editors without extensions, the Claude desktop app’s file viewer), they’re dead text. The owner wants notes that are plain Markdown and work anywhere, edited mostly by Claude rather than in a notes app.

`markdown-links` is a Claude Code plugin that keeps links between Markdown notes portable and correct without any notes app running. It converts existing wikilinks once, tells Claude how to write links, checks links after every edit Claude makes, and moves or renames notes without breaking links. It works on any folder, on any machine with the plugin installed.

## Goals

- Note bodies use standard relative Markdown links that resolve in any Markdown viewer.
- Frontmatter keeps quoted wikilinks (`"[[Jane Doe]]"`), which mark a value as a reference to a note rather than a plain string.
- A one-time `convert` turns body wikilinks into Markdown links, changing nothing but the links.
- Claude can write a correct link to another note without working out the relative path itself.
- Moving or renaming a note or folder keeps every link into and out of it correct.
- Mistakes are caught in the turn they happen: after Claude writes or edits a note, a hook reports broken links and stray body wikilinks.
- One Python script holds all the logic; the hook, the skill, routines, and a shell all call it.

## Non-goals (this version)

- Renaming files to remove spaces or change case. Spaces stay; links encode them.
- GitHub-style heading slugs. Heading anchors keep the heading text, encoded (`#My%20Heading`).
- Converting note transclusions (`![[Some Note]]`). They’re reported, not converted.
- Catching moves done outside the script (`mv` or `git mv` in Bash, Finder). The skill tells Claude to use the script; `check` finds what a stray move broke.
- Putting the script on the shell `PATH` or installing a git pre-commit hook. Both are possible later; this version documents how to call the script by its path.
- Index files, backlinks sections, or any other note-structure conventions.

## Anti-goals

These would make it a failure even if links technically work:

- Rewriting anything other than links: no reflowing, no whitespace or list changes, no frontmatter reformatting. A `convert` diff contains only link changes.
- Guessing. An ambiguous or unresolved link is left as it is and reported, never pointed at a best guess.
- Acting on folders that haven’t opted in. Without a marker file, every command but `init` refuses, and the hook does nothing.
- Sending note content anywhere. Standard library only, no network.

## Constraints

- Python 3.9 or newer, standard library only. Must run on macOS and Linux; Windows should work but isn’t a target.
- Public repository: tests and examples use made-up notes only.
- Plugin layout follows this marketplace: `plugins/markdown-links/.claude-plugin/plugin.json`, listed in `.claude-plugin/marketplace.json` and the root README’s plugin table.
- The plugin never uses the word “vault.” It talks about notes and roots. Obsidian is named once, in the `init` behavior below.

## Approaches considered

- **A. Python throughout (chosen).** All logic in `markdown-links.py`; the hook is a plain `PostToolUse` command in `hooks/hooks.json`. One language and one copy of the link rules; Python 3 is already present where routines run. It differs from this marketplace’s other plugins, which are TypeScript hook modules.
- **B. TypeScript throughout.** Logic in a hook module like the other plugins, with a command-line wrapper. Matches the marketplace, but command-line use needs Node or Bun on every machine, and the hook-module API is built for panes and status lines this plugin doesn’t need.
- **C. TypeScript hook calling the Python script.** Dropped: two languages for no gain over A.

The owner chose A.

## Decisions

### Roots

A **root** is a folder containing `.markdown-links.json`. Every command resolves the root by walking up from the path it’s given; a path with no root above it is out of scope. Links resolve within the root.

`.markdown-links.json` holds settings. This version needs one:

```json
{ "exclude": ["Templates", "Archive/old"] }
```

`exclude` lists folders, relative to the root, that commands skip. Hidden folders (`.git`, `.obsidian`, `.trash`, any dot-folder) are always skipped. An excluded folder is invisible to every command: its files aren’t checked, converted, or moved, and they aren’t link targets. So a link into an excluded folder reports as broken; exclude only folders nothing links to, such as templates. (Builder’s call.)

**Filenames don’t have to be unique.** Several folders can each have a `README.md`, `AGENTS.md`, `CLAUDE.md`, or `Tasks.md`. Body links are paths, so a shared name never makes them ambiguous. A shared name matters only to a wikilink that names it, which is reported where it occurs (see below), so `check` has no separate duplicate-name error.

**Wikilink resolution** follows the common convention: by filename, case-insensitive, `.md` optional. A path-qualified wikilink (`[[Folder/Note]]`) resolves to the note whose path ends with that path. A bare wikilink to a name more than one note shares (`[[Tasks]]` with two `Tasks.md` files) is ambiguous; the fix is to qualify it (`[[Project A/Tasks]]`). The same rule applies to attachments. (Builder’s call.)

### Link rules

- **Body links:** `[text](relative/path.md)`, relative to the note containing the link, each path segment percent-encoded (spaces as `%20`, non-ASCII as UTF-8 escapes). No `./` prefix for same-folder links. Anchors follow the path: `[text](Note.md#Some%20Heading)`. Attachments use the same form; images use `![alt](path)`.
- **Frontmatter links:** quoted wikilinks, `"[[Note Name]]"`, by filename without `.md`, optionally with `|alias` or `#heading`. Lists of them are fine. They must resolve to exactly one note in the root.
- **Skipped when parsing:** fenced code blocks (any fence length, including inside blockquotes), inline code, and HTML comments. External links (`http:`, `https:`, `mailto:`, and other schemes) are never checked or rewritten.
- **Recognized when reading:** inline links, angle-bracket targets (`[x](<a b.md>)`), reference-style definitions, and both encoded and unencoded targets. Writing always uses the encoded form.
- **Block references** (`[[Note#^abc123]]`, `[[#^abc123]]`) have no portable equivalent. `convert` leaves them, and `check` reports them as warnings, not errors, so the hook stays quiet. (Builder’s call.)
- **Root-absolute Markdown links** (`/People/Jane.md`) are errors in `check`. `convert` rewrites them to note-relative paths, reading the leading `/` as the root. (Builder’s call.)
- **A bare filename** (`[Decisions](Decisions.md)`) is a same-folder link like any other: if no file of that name sits next to the note, it’s a broken link, never resolved by searching the root for that name. `relink` repairs it with the same git-aware rules as any broken link, so a same-folder target that moved is found and one deleted in git isn’t replaced by an unrelated file of the same name. (Amended 2026-11-27; this replaces `convert`’s earlier by-name repair of bare filenames.)
- **Heading anchors** are checked against the target note’s headings, matched on the decoded heading text, case-insensitive. A missing heading is a warning, not an error. (Builder’s call.)

### Commands

`markdown-links.py <command> [args]`. Exit codes: `0` clean, `1` errors found or the command refused, `2` usage error. Every problem is one line starting `error:` or `warning:`, with the file path relative to the root. `--json` gives machine-readable output on every command that reports.

- **`init <folder>`** writes `.markdown-links.json` (empty `exclude`) if missing. If `<folder>/.obsidian/app.json` exists, it sets `useMarkdownLinks: true`, `newLinkFormat: "relative"`, and `alwaysUpdateLinks: true` there, so links made in Obsidian match. That’s the plugin’s only mention of Obsidian.
- **`check [path]`** checks the whole root, or one file when `path` is a file. Errors:
  - a body link whose target doesn’t exist, or exists only with different case;
  - a body wikilink that resolves to exactly one note (it should have been a Markdown link);
  - a frontmatter wikilink that resolves to no note or to more than one.
  Warnings:
  - a body wikilink that resolves to no note or to several (left for the owner);
  - a note transclusion `![[Note]]`;
  - a body link that leaves the root.
- **`convert [root]`** rewrites every body wikilink that resolves to exactly one file: `[[Name]]` → `[Name](path)`, `[[Name|Alias]]` → `[Alias](path)`, `[[Name#Heading]]` → `[Name](path#Heading)`, `[[#Heading]]` → `[Heading](#Heading)`, `![[image.png]]` → `![](path)`, and an embedded non-note attachment such as a PDF → `[file.pdf](path)`. Note transclusions, ambiguous links, and unresolved links are left alone and listed. Frontmatter is untouched. `--dry-run` lists changes without writing. Prints counts before and after.
- **`link <from-note> <to>`** prints a correct body link from one note to another. `<to>` is a note name (resolved by filename in the root) or a path. Link text defaults to the target’s filename without `.md`; `--text "…"` overrides it; `--heading "…"` adds an anchor. Errors if `<to>` is ambiguous or missing.
- **`mv <src> <dst>`** moves a file or folder within one root and keeps links correct:
  - links in other notes that point into the moved set are rewritten to the new paths;
  - relative links inside the moved notes that point outside the set are rewritten for their new location (links within the set already move together);
  - when a note’s filename changes, frontmatter wikilinks to it (`[[Old]]`, `[[Old|x]]`, `[[Old#h]]`) and any remaining body wikilinks to it are updated everywhere in the root. If the new name is shared with another note, the rewritten wikilinks are path-qualified so they stay unambiguous;
  - when a move or rename makes an existing bare wikilink ambiguous (a second `Tasks.md` arrives where one was), those wikilinks are path-qualified to the note they pointed at before.
  It refuses, changing nothing, if the destination exists or leaves the root. It computes every edit before touching the disk. `--dry-run` lists the move and every edit. Inside a git work tree it moves with `git mv` so history follows; otherwise with a plain rename. It prints every file it changed.
- **`relink [root]`** repairs links left broken by a move made some other way: `git mv`, shell `mv`, a file manager, or a notes app. It works on a whole root, like `convert`. A link is broken when its target doesn’t exist, or exists only with different case (a case-only rename); for the case-only kind the repair is simply the spelling on disk. For each other broken body Markdown link (inline, image, or reference definition), it looks for where the file went, in this order (rules amended 2026-11-27 after the second review):
  1. **A rename git recorded.** Inside a git work tree: staged renames (what `git mv` leaves until the next commit) and renames in the commit history (`git log -M`, chained, so `A` → `B` → `C` sends a link to `A` to `C`). A link to an old path is pointed at the new one. A note that was itself renamed has its links read from its old location first, so its outgoing links are repaired too.
  2. **The same filename.** The files in the root with the target’s filename (case-insensitive, Unicode-normalized). Of those, the one that shares the most trailing path segments with the path the link names wins. After `Research/` moves under `Archive/`, a link to `Research/Tasks.md` goes to `Archive/Research/Tasks.md`, not to a root `Tasks.md`. A tie, or no file of that name, leaves the link alone and reports it. Inside a git work tree, which files may be candidates depends on whether git ever tracked the path the link names:
     - **Never tracked** (a hand-typed link, or a shortest-path link written by a notes app): every file of that name is a candidate.
     - **Deleted in git** (staged for deletion with `git rm`, or deleted in a commit, and not a rename source): no candidates. The link is reported as `broken link (deleted in git): …`.
     - **Otherwise tracked** (in `HEAD` and deleted only in the working tree, as a shell `rm` or a shell `mv` leaves it): only files git doesn’t have at their path yet (untracked, or staged as added) are candidates, because a move leaves the file at a new path git hasn’t recorded, and a deletion doesn’t. With no such candidate, the link is reported as `broken link (deleted in git): …`.
     So `git rm`, a shell `rm`, and a committed deletion are never pointed at another file of the same name, and a shell `mv` is still repaired.
  A frontmatter wikilink that matches no note is repaired only from a recorded git rename (staged or committed): `[[Old]]` becomes `[[New]]`, keeping any alias or heading, path-qualified if the new name is shared. Anything else is reported, not guessed. Rewritten links are note-relative and encoded; link text, anchors, and every other byte stay as written. `--dry-run` lists changes without writing. Output matches `convert`: one line per change (`relinked <file>:<line>: <old> -> <new>`, or `would relink` on a dry run), a count line, then the broken links it couldn’t repair as `error:` lines. Exits `1` if any broken link remains (on a dry run, if any was there to begin with).

### The hook

`hooks/hooks.json` registers a `PostToolUse` command for `Write`, `Edit`, and `MultiEdit`. It reads the hook payload from stdin and takes the edited file path. If the file isn’t `.md`, or has no root above it, it exits `0` silently. Otherwise it runs `check <file>`. On errors it exits `2` with the error lines on stderr, which Claude Code shows to Claude in the same turn. Warnings alone exit `0` and print nothing, so legacy notes with unresolved wikilinks don’t nag on every edit.

A single-file check has to finish in about a second on a root of 5,000 notes. That covers walking the root to build the filename index.

The hook also runs after `Bash`, to catch moves and deletions Claude makes from the shell. It costs nothing unless the command contains `mv` or `rm` as a command word (`mv …`, `git mv …`, `rm …`, or `git rm …`, found by a pattern match on the command text; amended 2026-11-27 to add `rm`) and doesn’t run `markdown-links.py`, which keeps links right on its own. When it does, it finds the roots at or above the payload’s `cwd` and at or above each path in the command that exists after it ran (or whose parent folder does), up to 5 roots. In each, it counts only the broken links this command could have caused (amended 2026-11-27): a broken link (as `relink` defines it) counts when the path it names, or the note that holds it, is at or under a path written in the command (each word resolved against `cwd`). A link that was already broken for another reason, such as a link to a deleted note the user chose to keep, doesn’t make an unrelated `mv` or `rm` speak. If any root has some, it exits `2` with one line per such root and nothing else: `markdown-links: <N> broken links in <root>; run: python3 "<script>" relink "<root>"`. It never lists the links themselves (`relink` does), so a move costs Claude one line, and a clean move costs nothing. It has to finish in 2 seconds on a root of 5,000 notes.

### The skill

`skills/markdown-links/SKILL.md`, with the script alongside it at `skills/markdown-links/scripts/markdown-links.py`, so the skill can name it by its own base directory and the hook by `${CLAUDE_PLUGIN_ROOT}`. The skill’s description triggers on writing, editing, linking, moving, or renaming Markdown notes, or a folder containing `.markdown-links.json`. Its body:

- the link rules above, briefly;
- to write a body link, run `link` instead of composing the path by hand;
- to move or rename a note or folder, run `mv`, which uses `git mv` for tracked files and rewrites links; never shell `mv`;
- if a move happened some other way (`git mv`, a file manager, a notes app), or the hook names `relink` after a shell command, run `relink` on the root, then `check`;
- links to a note deleted on purpose (`relink` reports them as `broken link (deleted in git)`, and frontmatter wikilinks to it as `wikilink matches no file`) stay as they are: no command rewrites them. At the end of the work, list them for the user and ask what each should become: removed along with its text, kept as plain text without the link, left as is, or pointed at another file (write the new target with `link`). Do only what the user chooses. In a non-interactive run, leave them and put the list in the run report (amended 2026-11-27);
- after a hook error, fix the link the error names; don’t silence the hook;
- run `check` on the root after bulk edits;
- to bring a new folder in: `init`, then `convert --dry-run`, review, `convert`, then `relink` (it repairs shortest-path links a notes app wrote, which are now broken same-folder links), then `check`.

### Adoption and coexistence

- **This plugin ships alone.** Changing any existing skills or routines that write wikilinks or move notes some other way is the adopter’s work, outside this repo. The README says so: update whatever writes links before running `init` on a folder, or the hook will report every wikilink those writers add.
- **Routines** that run as Claude Code sessions with the plugin installed call the script through the skill’s base directory, like any session. Calling it from outside Claude Code (cron, git hooks) is a non-goal for this version.
- **A notes app may stay open.** `init` sets Obsidian’s `alwaysUpdateLinks` so renames made inside Obsidian keep links current. Renames made by `mv` happen on disk, which Obsidian sees as a file disappearing and another appearing, not as a rename it should rewrite links for. The plan includes one manual check of this with Obsidian open: `mv` a note, then confirm Obsidian rewrote nothing. If it does rewrite, the README says to close it first. (Builder’s call.)

### Packaging and docs

- `plugins/markdown-links/.claude-plugin/plugin.json` with `name`, `description`, `author` (One Good Idea), and `license` (MIT).
- `plugins/markdown-links/README.md`: what it does, install, the link rules, the commands, how to call the script from a shell (its path inside the installed plugin), and credit for adapted code.
- An entry in the marketplace manifest and the root README table.
- The parsing approach (fence, inline-code, and frontmatter handling) may be adapted from `m4bwav/obsidian-notes`, which is MIT-licensed. Keep its copyright notice in the script header and credit it in the README.

### Tests

`unittest` only, in `plugins/markdown-links/tests/`, run with `python3 -m unittest`. Fixtures are made-up note folders built in temporary directories. At minimum:

- `convert` produces only link changes, byte for byte elsewhere, and handles aliases, headings, same-note headings, images, attachments, nested paths (`../../`), spaces, non-ASCII names, and links in tables and blockquotes.
- `convert` leaves frontmatter, code, ambiguous, unresolved, transcluded, and block-reference links alone, and rewrites root-absolute Markdown links.
- Excluded folders are invisible; attachments may share names; path-qualified wikilinks resolve.
- `check` flags each error and warning class, and the hook exits `2` on errors and `0` otherwise.
- `mv` of a file, a rename, and a folder move each leave `check` clean; refusals change nothing; `--dry-run` writes nothing.
- `link` output resolves from notes at several depths.
- `relink` repairs a `git mv` rename (body and frontmatter links, and the renamed note’s own links), a shell-moved folder by trailing-path match, and a moved note’s outgoing links; leaves a tie alone; writes nothing on `--dry-run`; preserves CRLF and a BOM; works outside git.
- The `Bash` hook is silent for a command without `mv` or `rm` even in a root with broken links, names `relink` in one line after a move or deletion that broke links, is silent after a clean move and after `markdown-links.py` commands, and ignores odd payloads.

## Left to the builder

- Internal structure of the script (one file is expected; split only if it gets unwieldy).
- Exact wording of messages and help text.
- How to make the per-file check fast enough (caching is allowed, but must never give a stale answer about whether a target exists).
- Whether `check` also reports unclosed frontmatter or other YAML problems it notices in passing.
