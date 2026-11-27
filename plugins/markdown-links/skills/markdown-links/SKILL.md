---
name: markdown-links
description: "Use when writing, editing, linking, moving, or renaming Markdown notes, when working in a folder that contains .markdown-links.json, or when asked to convert wikilinks or fix broken links. Keeps links between notes as portable relative Markdown links."
---

# Markdown links

Notes in a folder with `.markdown-links.json` (the root) use relative Markdown links, not `[[wikilinks]]`. A hook checks every `.md` file you write or edit, and flags broken links after a shell `mv`. Folders without the marker file are left alone.

## Link rules

- Body links are `[text](relative/path.md)`, relative to the note containing the link. Percent-encode each path segment (spaces as `%20`). No `./` for same-folder links. Anchors keep the heading text, encoded: `Note.md#Some%20Heading`. Images are `![alt](path)`.
- Frontmatter keeps quoted wikilinks, `"[[Note Name]]"`, by filename without `.md`. They must match exactly one note.
- Code blocks, inline code, and HTML comments are skipped. External links (`https:`, `mailto:`) are never touched.
- Never write a wikilink in a note body.

## The script

It lives at `scripts/markdown-links.py` in this skill’s base directory, which is shown when the skill loads. Always call it with `python3` and the absolute path:

```
python3 "<base>/scripts/markdown-links.py" <command> ...
```

Commands: `init`, `check`, `convert`, `link`, `mv`, `relink`. Add `--json` for machine-readable output.

## Writing a link

Run `link` instead of working out the path yourself, then paste the output into the note:

```
python3 "<base>/scripts/markdown-links.py" link <from-note> <to>
```

`<to>` is a note name or a path. Add `--text "..."` to change the link text and `--heading "..."` to link to a heading. If it reports the name is ambiguous or missing, pass a path instead.

## Moving or renaming

Use `mv` to move or rename a note or folder. It uses `git mv` for tracked files. Never use shell `mv`.

```
python3 "<base>/scripts/markdown-links.py" mv [--dry-run] <src> <dst>
```

It rewrites links into and out of the moved notes and prints every file it changed. Use `--dry-run` first for a large move.

If a move happened another way (`git mv`, a file manager, a notes app), or a hook message names `relink` after a shell command, run `relink` on the root, then `check`:

```
python3 "<base>/scripts/markdown-links.py" relink <root>
python3 "<base>/scripts/markdown-links.py" check <root>
```

`relink` repairs links that now point nowhere and lists any it can’t. Add `--dry-run` to preview.

## After a hook error

The hook prints `error:` lines with a file, a line, and what is wrong. Fix the link each line names. Don’t silence the hook or edit its settings. Warnings (an unresolved wikilink, a missing heading) are left for the owner.

## Bulk edits

After editing many notes, run `check` on the root and fix every error:

```
python3 "<base>/scripts/markdown-links.py" check <root>
```

## Bringing in a new folder

1. `init <folder>`
2. `convert --dry-run <folder>`, then review each change it lists.
3. `convert <folder>`
4. `check <folder>`

Give `convert` the root folder itself; it refuses a subfolder. It changes only links. It leaves ambiguous, unresolved, and block-reference wikilinks alone, and broken links too, and lists them for the owner.
