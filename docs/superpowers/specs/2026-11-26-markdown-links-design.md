# markdown-links: design

Status: draft, not yet approved.

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

A **root** is a folder containing `.markdown-links.json`. Every command resolves the root by walking up from the path it’s given; a path with no root above it is out of scope. Filenames must be unique within a root (case-insensitive, ignoring `.md`), and links resolve within it.

`.markdown-links.json` holds settings. This version needs one:

```json
{ "exclude": ["Templates", "Archive/old"] }
```

`exclude` lists folders, relative to the root, that commands skip. Hidden folders (`.git`, `.obsidian`, `.trash`, any dot-folder) are always skipped. An excluded folder is invisible to every command: its files aren’t checked, converted, or moved, and they aren’t link targets or filename duplicates. So a link into an excluded folder reports as broken; exclude only folders nothing links to, such as templates. (Builder’s call.)

**Uniqueness covers notes only.** Two `.md` files with the same name (case-insensitive) in a root are an error. Attachments (any other file) may share names across folders; a body link to one is a path, so it’s never ambiguous, and a wikilink to a shared attachment name is reported as ambiguous. (Builder’s call.)

**Wikilink resolution** follows the common convention: by filename, case-insensitive, `.md` optional. A path-qualified wikilink (`[[Folder/Note]]`) resolves to the note whose path ends with that path. (Builder’s call.)

### Link rules

- **Body links:** `[text](relative/path.md)`, relative to the note containing the link, each path segment percent-encoded (spaces as `%20`, non-ASCII as UTF-8 escapes). No `./` prefix for same-folder links. Anchors follow the path: `[text](Note.md#Some%20Heading)`. Attachments use the same form; images use `![alt](path)`.
- **Frontmatter links:** quoted wikilinks, `"[[Note Name]]"`, by filename without `.md`, optionally with `|alias` or `#heading`. Lists of them are fine. They must resolve to exactly one note in the root.
- **Skipped when parsing:** fenced code blocks (any fence length, including inside blockquotes), inline code, and HTML comments. External links (`http:`, `https:`, `mailto:`, and other schemes) are never checked or rewritten.
- **Recognized when reading:** inline links, angle-bracket targets (`[x](<a b.md>)`), reference-style definitions, and both encoded and unencoded targets. Writing always uses the encoded form.
- **Block references** (`[[Note#^abc123]]`, `[[#^abc123]]`) have no portable equivalent. `convert` leaves them, and `check` reports them as warnings, not errors, so the hook stays quiet. (Builder’s call.)
- **Markdown links that aren’t note-relative** (a bare filename for a note in another folder, or a root-absolute `/People/Jane.md`) are errors in `check`. `convert` repairs them when the filename resolves to exactly one note, rewriting them to note-relative paths; a leading `/` is read as the root. (Builder’s call.)
- **Heading anchors** are checked against the target note’s headings, matched on the decoded heading text, case-insensitive. A missing heading is a warning, not an error. (Builder’s call.)

### Commands

`markdown-links.py <command> [args]`. Exit codes: `0` clean, `1` errors found or the command refused, `2` usage error. Every problem is one line starting `error:` or `warning:`, with the file path relative to the root. `--json` gives machine-readable output on every command that reports.

- **`init <folder>`** writes `.markdown-links.json` (empty `exclude`) if missing. If `<folder>/.obsidian/app.json` exists, it sets `useMarkdownLinks: true`, `newLinkFormat: "relative"`, and `alwaysUpdateLinks: true` there, so links made in Obsidian match. That’s the plugin’s only mention of Obsidian.
- **`check [path]`** checks the whole root, or one file when `path` is a file. Errors:
  - a body link whose target doesn’t exist, or exists only with different case;
  - a body wikilink that resolves to exactly one note (it should have been a Markdown link);
  - a frontmatter wikilink that resolves to no note or to more than one;
  - duplicate filenames in the root (whole-root check only).
  Warnings:
  - a body wikilink that resolves to no note or to several (left for the owner);
  - a note transclusion `![[Note]]`;
  - a body link that leaves the root.
- **`convert [root]`** rewrites every body wikilink that resolves to exactly one file: `[[Name]]` → `[Name](path)`, `[[Name|Alias]]` → `[Alias](path)`, `[[Name#Heading]]` → `[Name](path#Heading)`, `[[#Heading]]` → `[Heading](#Heading)`, `![[image.png]]` → `![](path)`, and an embedded non-note attachment such as a PDF → `[file.pdf](path)`. Note transclusions, ambiguous links, and unresolved links are left alone and listed. Frontmatter is untouched. `--dry-run` lists changes without writing. Prints counts before and after.
- **`link <from-note> <to>`** prints a correct body link from one note to another. `<to>` is a note name (resolved by filename in the root) or a path. Link text defaults to the target’s filename without `.md`; `--text "…"` overrides it; `--heading "…"` adds an anchor. Errors if `<to>` is ambiguous or missing.
- **`mv <src> <dst>`** moves a file or folder within one root and keeps links correct:
  - links in other notes that point into the moved set are rewritten to the new paths;
  - relative links inside the moved notes that point outside the set are rewritten for their new location (links within the set already move together);
  - when a note’s filename changes, frontmatter wikilinks to it (`[[Old]]`, `[[Old|x]]`, `[[Old#h]]`) and any remaining body wikilinks to it are updated everywhere in the root.
  It refuses, changing nothing, if the destination exists, leaves the root, or would create a duplicate filename. It computes every edit before touching the disk. `--dry-run` lists the move and every edit. Inside a git work tree it moves with `git mv` so history follows; otherwise with a plain rename. It prints every file it changed.

### The hook

`hooks/hooks.json` registers a `PostToolUse` command for `Write`, `Edit`, and `MultiEdit`. It reads the hook payload from stdin and takes the edited file path. If the file isn’t `.md`, or has no root above it, it exits `0` silently. Otherwise it runs `check <file>`. On errors it exits `2` with the error lines on stderr, which Claude Code shows to Claude in the same turn. Warnings alone exit `0` and print nothing, so legacy notes with unresolved wikilinks don’t nag on every edit.

A single-file check has to finish in about a second on a root of 5,000 notes. That covers walking the root to build the filename index.

### The skill

`skills/markdown-links/SKILL.md`, with the script alongside it at `skills/markdown-links/scripts/markdown-links.py`, so the skill can name it by its own base directory and the hook by `${CLAUDE_PLUGIN_ROOT}`. The skill’s description triggers on writing, editing, linking, moving, or renaming Markdown notes, or a folder containing `.markdown-links.json`. Its body:

- the link rules above, briefly;
- to write a body link, run `link` instead of composing the path by hand;
- to move or rename a note or folder, run `mv`, never shell `mv`, `git mv`, or a file-manager move;
- after a hook error, fix the link the error names; don’t silence the hook;
- run `check` on the root after bulk edits;
- to bring a new folder in: `init`, then `convert --dry-run`, review, `convert`, then `check`.

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
- `convert` leaves frontmatter, code, ambiguous, unresolved, transcluded, and block-reference links alone, and repairs non-relative Markdown links.
- Excluded folders are invisible; attachments may share names; path-qualified wikilinks resolve.
- `check` flags each error and warning class, and the hook exits `2` on errors and `0` otherwise.
- `mv` of a file, a rename, and a folder move each leave `check` clean; refusals change nothing; `--dry-run` writes nothing.
- `link` output resolves from notes at several depths.

## Left to the builder

- Internal structure of the script (one file is expected; split only if it gets unwieldy).
- Exact wording of messages and help text.
- How to make the per-file check fast enough (caching is allowed, but must never give a stale answer about whether a target exists).
- Whether `check` also reports unclosed frontmatter or other YAML problems it notices in passing.
