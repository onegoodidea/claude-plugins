# markdown-links Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Claude Code plugin whose one Python script converts, writes, checks, and moves Markdown note links so they work in any viewer, plus a skill that teaches the rules and a hook that checks every note Claude edits.

**Architecture:** A small Python package, `mdlinks`, beside a thin entry script inside the skill folder. Each module has one job: finding the root, parsing links, encoding paths, resolving targets, and one module per command. The hook is a hidden `hook` subcommand that `hooks/hooks.json` runs after `Write`, `Edit`, and `MultiEdit`.

**Tech Stack:** Python 3.9+, standard library only, `unittest`.

**Spec:** `docs/superpowers/specs/2026-11-26-markdown-links-design.md`

## Global Constraints

- Python 3.9 or newer, standard library only, no network.
- Public repository: every test fixture is made-up notes built in a temporary directory.
- The plugin never uses the word “vault” (code, messages, docs, tests). Obsidian is named only in `init` and the README’s credit and coexistence notes.
- Exit codes: `0` clean, `1` errors found or the command refused, `2` usage error.
- Every reported problem is one line starting `error:` or `warning:`, then the file path relative to the root, `:line`, and a message. `--json` prints a list of `{"level", "file", "line", "message"}` objects instead.
- No file is ever modified except the link text and targets being rewritten. Line endings (LF or CRLF), a UTF-8 BOM, and all other bytes are preserved.
- Only folders with `.markdown-links.json` at or above the path are acted on.
- All file paths in this plan are relative to `plugins/markdown-links/` unless they start with the repo root (`.claude-plugin/`, `README.md`, `docs/`).

## Review Focus

1. **CRLF files and a UTF-8 BOM.** `convert` and `mv` must leave both exactly as they were. Test in Task 5 (`test_convert_preserves_crlf_and_bom`).
2. **Wikilinks in tables, where the alias pipe is escaped** (`[[Note\|Alias]]`). The alias is `Alias`, and the output has no `|`. Test in Task 2 (`test_escaped_pipe_alias_in_table`) and Task 5 (`test_convert_table_alias`).
3. **Filenames with parentheses, `#`, `%`, or curly apostrophes** (`App Review (beta).md`, `St. Ann’s.md`). Encoding must produce a target every viewer resolves: `(` becomes `%28`, `#` becomes `%23`, `%` becomes `%25`, `’` becomes `%E2%80%99`. Test in Task 1 (`test_encode_special_characters`).
4. **A case-only rename on macOS’s case-insensitive disk** (`mv note.md Note.md`). It must not refuse with “destination exists”, and the file must end up with the new case. Test in Task 7 (`test_mv_case_only_rename`).
5. **Hook payloads that aren’t a normal note edit:** a missing `file_path`, a deleted file, a non-UTF-8 file, malformed JSON. The hook exits `0` silently and never prints a traceback. Test in Task 8 (`test_hook_ignores_odd_payloads`).

---

## File Structure

```
plugins/markdown-links/
  .claude-plugin/plugin.json
  hooks/hooks.json
  README.md
  skills/markdown-links/
    SKILL.md
    scripts/
      markdown-links.py        # entry: puts scripts/ on sys.path, calls mdlinks.cli.main
      mdlinks/
        __init__.py
        model.py               # dataclasses shared by every module
        root.py                # find the root, read config, index files
        paths.py               # relative paths and percent-encoding
        parse.py               # find links and headings, skipping code and comments
        resolve.py             # resolve wikilinks and Markdown link targets
        check.py               # check one file or the whole root
        convert.py             # body wikilinks and non-relative links to note-relative links
        link.py                # print a link from one note to another
        move.py                # plan and apply a move or rename
        hook.py                # PostToolUse entry
        cli.py                 # argparse, output, exit codes
  tests/
    helpers.py                 # make_root(tmp, files) and sys.path setup
    test_root_paths.py
    test_parse.py
    test_resolve.py
    test_check.py
    test_convert.py
    test_link.py
    test_move.py
    test_hook.py
```

Run every test from `plugins/markdown-links/`: `python3 -m unittest discover -s tests -v`.

---

### Task 1: Scaffold, shared model, root, and paths

**Files:**
- Create: `skills/markdown-links/scripts/markdown-links.py`, `skills/markdown-links/scripts/mdlinks/__init__.py`, `mdlinks/model.py`, `mdlinks/root.py`, `mdlinks/paths.py`
- Test: `tests/helpers.py`, `tests/test_root_paths.py`

**Interfaces:**
- Produces:
  - `model.Finding(level: str, file: str, line: int, message: str)`, a frozen dataclass. `level` is `"error"` or `"warning"`; `file` is a POSIX path relative to the root.
  - `model.format_finding(f: Finding) -> str` returns `f"{f.level}: {f.file}:{f.line}: {f.message}"`. Every module that prints a finding uses it.
  - `model.Root(path: Path, exclude: list[str], notes: list[Path], files: list[Path], by_name: dict[str, list[Path]])`. `notes` are `.md` files and `files` are all other files, both absolute and sorted. `by_name` maps a lowercased name to its paths: for notes the name without `.md`, for other files the full filename, and for notes the full filename with `.md` too.
  - `root.CONFIG_NAME = ".markdown-links.json"`
  - `root.find_root(path: Path) -> Path | None` walks up from `path`, or from its parent if it’s a file, and returns the first folder containing `CONFIG_NAME`.
  - `root.load(root_path: Path) -> Root` reads the config (missing `exclude` means `[]`) and walks the tree, skipping dot-folders and excluded folders (matched by root-relative path prefix).
  - `root.rel(root: Root, path: Path) -> str` gives the root-relative POSIX path.
  - `paths.relative(from_note: Path, target: Path) -> str` gives the POSIX path from `from_note`’s folder to `target`, with no `./` prefix.
  - `paths.encode(posix_path: str) -> str` encodes each segment with `urllib.parse.quote(segment, safe="")`.
  - `paths.decode(target: str) -> str` is `urllib.parse.unquote`.
  - `paths.encode_anchor(text: str) -> str` encodes like a segment but keeps `^`.
  - `tests/helpers.make_root(tmp: Path, files: dict[str, str | bytes], config: dict | None = {"exclude": []}) -> Path` writes the files (`str` as UTF-8 exactly as given), then the config unless it’s `None`, and returns the root path. The module also inserts `skills/markdown-links/scripts` into `sys.path`.

- [ ] **Step 1: Write the failing tests** in `tests/test_root_paths.py`:
  - `test_find_root_walks_up`: a root with `a/b/Note.md`. `find_root(root/"a/b/Note.md") == root`, and `find_root` of a temp folder with no config is `None`.
  - `test_load_skips_dot_and_excluded`: files `Note.md`, `.obsidian/x.md`, `Templates/T.md`, `img/pic.png`, and config `{"exclude": ["Templates"]}`. `notes == [root/"Note.md"]`, `files == [root/"img/pic.png"]`, `by_name["note"] == [root/"Note.md"]`, `by_name["note.md"] == [root/"Note.md"]`, `by_name["pic.png"] == [root/"img/pic.png"]`.
  - `test_shared_names_listed`: `A/Tasks.md` and `B/Tasks.md` give `len(by_name["tasks"]) == 2`.
  - `test_relative_paths`: from `Journal/2026/10/D.md` to `Ideas/I.md` is `"../../../Ideas/I.md"`; from `A/x.md` to `A/y.md` is `"y.md"`; from `x.md` to `A/y.md` is `"A/y.md"`.
  - `test_encode_special_characters`: `encode("App Review (beta).md") == "App%20Review%20%28beta%29.md"`, `encode("St. Ann’s.md") == "St.%20Ann%E2%80%99s.md"`, `encode("C# 100%.md") == "C%23%20100%25.md"`, and `encode("../A b/c.md") == "../A%20b/c.md"`.
  - `test_encode_anchor`: `encode_anchor("Some Heading") == "Some%20Heading"` and `encode_anchor("^abc") == "^abc"`.
- [ ] **Step 2: Run** `python3 -m unittest tests.test_root_paths -v`. Expected: it fails with an `ImportError` for `mdlinks`.
- [ ] **Step 3: Implement** the interfaces above. `markdown-links.py` holds only `sys.path.insert(0, str(Path(__file__).parent))`, then `from mdlinks.cli import main` and `sys.exit(main(sys.argv[1:]))`. Leave `cli.py` as a stub, `def main(argv): return 2`, until Task 4.
- [ ] **Step 4: Run** `python3 -m unittest tests.test_root_paths -v`. Expected: all pass.
- [ ] **Step 5: Commit** with `git add plugins/markdown-links && git commit -m "markdown-links: root discovery, file index, and path encoding"`.

### Task 2: Parser

**Files:**
- Create: `mdlinks/parse.py`
- Test: `tests/test_parse.py`

**Interfaces:**
- Produces:
  - `model.Link(kind: str, start: int, end: int, line: int, raw: str, target: str, anchor: str | None, alias: str | None, text: str | None, in_frontmatter: bool, angle: bool)`.
    - `kind` is one of `"md"` (`[t](x)`), `"image"` (`![a](x)`), `"refdef"` (`[id]: x`), `"wiki"` (`[[x]]`), and `"embed"` (`![[x]]`).
    - `start` and `end` are character offsets into the full text, and `raw` is `text[start:end]`. `line` is 1-based.
    - `target` is the path part, still encoded as it was written, without the anchor. For wikilinks it’s the name.
    - `anchor` is the text after `#`, without the `#`.
    - `alias` is the wikilink alias, with an escaped `\|` handled.
    - `text` is the Markdown link text or image alt.
    - `angle` is true for `<…>` targets.
  - `model.Link.block_ref` is a property, true when `anchor` starts with `^`.
  - `parse.find_links(text: str) -> list[Link]` returns links in offset order. It finds wikilinks in frontmatter (`in_frontmatter=True`) and every kind in the body. It skips fenced code (backtick or tilde fences of three or more, including inside blockquotes, closed by a fence of the same character and at least the same length), inline code spans, and HTML comments. It excludes external targets, meaning any `scheme:` (`[a-zA-Z][a-zA-Z0-9+.-]*:`) and `//…`.
  - `parse.frontmatter_span(text: str) -> tuple[int, int] | None` gives the offsets of the frontmatter block, including both `---` lines, when the text starts with `---` followed by a newline (after an optional BOM, which `read` strips).
  - `parse.headings(text: str) -> list[str]` returns ATX heading texts (`#` to `######`) outside code and frontmatter, with trailing `#`s and whitespace stripped.
  - `parse.read(path: Path) -> tuple[str, bool]` returns the text decoded as UTF-8 with newlines untouched and a flag for whether a BOM was present. It raises `UnicodeDecodeError` on invalid UTF-8.
  - `parse.write(path: Path, text: str, bom: bool) -> None` writes the bytes back with no newline translation.

- [ ] **Step 1: Write the failing tests** in `tests/test_parse.py`, one assertion group each:
  - `test_md_link_and_anchor`: `"[A](x/A%20b.md#H%20one)"` gives `kind="md"`, `target="x/A%20b.md"`, `anchor="H%20one"`, `text="A"`.
  - `test_angle_target`: `"[A](<x/A b.md>)"` gives `target="x/A b.md"` and `angle=True`.
  - `test_image_and_refdef`: `"![p](img/p.png)"` gives `kind="image"`, and `"[id]: Notes/N.md"` on its own line gives `kind="refdef"` with `target="Notes/N.md"`.
  - `test_wiki_forms`: `[[N]]`, `[[N|Al]]`, `[[N#H]]`, `[[#H]]`, `[[N#^b1]]`, and `![[p.png]]` give the expected `target`, `alias`, `anchor`, `kind`, and `block_ref`. For `[[#H]]`, `target == ""`.
  - `test_escaped_pipe_alias_in_table`: `"| [[Note\|Alias]] | x |"` gives `target="Note"` and `alias="Alias"`, and `raw` contains the backslash.
  - `test_frontmatter_wikilinks_flagged`: frontmatter `participants:\n  - "[[Jane Doe]]"` gives one `wiki` link with `in_frontmatter=True`, and a Markdown-looking `"[x](y.md)"` in frontmatter is not returned.
  - `test_skips_code_and_comments`: links inside a ```` ``` ```` fence, a `~~~~` fence, a fence inside `> `, inline `` `[[x]]` ``, and `<!-- [[x]] -->` are not returned, while a link after the closing fence is.
  - `test_external_ignored`: `https:`, `mailto:`, `obsidian:`, and `//host` targets are not returned.
  - `test_line_numbers_crlf`: in `"a\r\nb [[N]]\r\n"`, the link’s `line` is `2`.
  - `test_headings`: `"# One\n```\n# not\n```\n## Two ##\n"` gives `["One", "Two"]`.
- [ ] **Step 2: Run** `python3 -m unittest tests.test_parse -v`. Expected: fails on `ImportError` for `find_links`.
- [ ] **Step 3: Implement** `parse.py`. Build a list of the spans to skip (frontmatter, fences, comments, and inline code), then run the link regexes over the full text and drop any match that starts inside a skipped span. For frontmatter, run only the wikilink regex. Working on offsets keeps rewriting simple in later tasks.
- [ ] **Step 4: Run** `python3 -m unittest tests.test_parse -v`. Expected: all pass.
- [ ] **Step 5: Commit** with `git add plugins/markdown-links && git commit -m "markdown-links: link and heading parser"`.

### Task 3: Resolver

**Files:**
- Create: `mdlinks/resolve.py`
- Test: `tests/test_resolve.py`

**Interfaces:**
- Consumes: `Root`, `Link`, `paths.decode`.
- Produces:
  - `resolve.wikilink(root: Root, name: str) -> list[Path]` resolves a wikilink name.
    - Matching is case-insensitive, and `.md` is optional.
    - A name containing `/` keeps only the candidates whose root-relative path, with or without `.md`, ends with `/` + name or equals the name.
    - An empty name returns `[]`.
    - Notes are checked first, and other files only when the name has a non-`.md` extension.
  - `model.MdTarget(path: Path | None, exact_case: bool, outside_root: bool, note_relative: bool)`.
  - `resolve.md_target(root: Root, from_note: Path, target: str) -> MdTarget` resolves a Markdown link target.
    - It decodes the target, then resolves it against `from_note`’s folder one segment at a time, case-sensitively first and case-insensitively second (case-insensitive sets `exact_case=False`).
    - A leading `/` resolves from the root and sets `note_relative=False`.
    - A target that resolves only when read from the root, or that fails relative resolution but whose final segment names exactly one note or file in `by_name`, returns that path with `note_relative=False`.
    - `outside_root` is true when the resolved path isn’t under `root.path`.
    - A file in an excluded folder counts as not found.
    - An empty target (a same-note `#anchor`) returns `MdTarget(from_note, True, False, True)`.

- [ ] **Step 1: Write the failing tests** in `tests/test_resolve.py`, using a root with `People/Jane Doe.md`, `A/Tasks.md`, `B/Tasks.md`, `img/p.png`, `Templates/T.md`, and `exclude: ["Templates"]`:
  - `test_wikilink_by_name_case_insensitive`: `wikilink(r, "jane doe") == [root/"People/Jane Doe.md"]`, and `"Jane Doe.md"` gives the same.
  - `test_wikilink_shared_name_and_qualified`: `len(wikilink(r, "Tasks")) == 2`, and `wikilink(r, "A/Tasks") == [root/"A/Tasks.md"]`.
  - `test_wikilink_attachment_and_missing`: `"p.png"` gives `[root/"img/p.png"]`, and both `"Nope"` and `"T"` give `[]` (T is excluded).
  - `test_md_target_relative`: from `A/Tasks.md`, the target `"../People/Jane%20Doe.md"` gives that path, `exact_case=True`, and `note_relative=True`.
  - `test_md_target_case_mismatch`: `"../people/jane%20doe.md"` gives `exact_case=False`.
  - `test_md_target_not_note_relative`: from `A/Tasks.md`, both `"Jane%20Doe.md"` and `"/People/Jane%20Doe.md"` give the Jane path with `note_relative=False`.
  - `test_md_target_outside_and_missing`: `"../../x.md"` gives `outside_root=True` (create a file beside the root so it exists), and `"Missing.md"` gives `path=None`.
- [ ] **Step 2: Run** `python3 -m unittest tests.test_resolve -v`. Expected: fails on `ImportError`.
- [ ] **Step 3: Implement** `resolve.py` as specified.
- [ ] **Step 4: Run** `python3 -m unittest tests.test_resolve -v`. Expected: all pass.
- [ ] **Step 5: Commit** with `git add -A plugins/markdown-links .claude-plugin README.md && git commit -m "markdown-links: wikilink and Markdown target resolution"`.

### Task 4: `check`, `init`, and the CLI

**Files:**
- Create: `mdlinks/check.py`, `mdlinks/cli.py` (replaces the stub)
- Test: `tests/test_check.py`

**Interfaces:**
- Consumes: Tasks 1 to 3.
- Produces:
  - `check.check_file(root: Root, note: Path) -> list[Finding]`
  - `check.check_root(root: Root) -> list[Finding]` concatenates `check_file` for every note, in path order.
  - `cli.main(argv: list[str]) -> int` takes subcommands `init`, `check`, `convert`, `link`, `mv`, and the hidden `hook`. Later tasks add their subparsers here. It prints findings with `cli.print_findings(findings: list[Finding], as_json: bool) -> None`. `--json` is a top-level option, accepted before the subcommand, and `check`, `convert`, and `mv` report through `print_findings`. It returns `1` if any finding is an error, and returns `2` (via argparse) on usage errors or when the path has no root, with `error: no .markdown-links.json at or above <path>` on stderr.
  - `cli.init(folder: Path) -> list[str]` writes `{"exclude": []}` with a trailing newline if the config is missing. If `.obsidian/app.json` exists, it merges in `"useMarkdownLinks": true`, `"newLinkFormat": "relative"`, and `"alwaysUpdateLinks": true`, writing 2-space-indented JSON. It returns a description of each file it wrote.

`check_file` rules (the messages are free text, but must name the target):

| Condition | Level |
|---|---|
| `md`/`image`/`refdef` with `path=None` | error, “broken link” |
| … with `exact_case=False` | error, “case differs from the file on disk” |
| … with `note_relative=False` | error, “not relative to this note; run convert” |
| … with `outside_root=True` | warning |
| … with an `anchor` not in the target note’s `headings()` (decoded, case-insensitive; skip block refs and non-`.md` targets) | warning |
| body `wiki` resolving to exactly one file, not a block ref | error, “use a Markdown link” |
| body `wiki` resolving to 0 or 2+ | warning, listing up to 3 candidates |
| body `wiki` or `embed` with a block ref | warning |
| `embed` whose single match is a note | warning, “note transclusion” |
| `embed` whose single match is an attachment | error, “use a Markdown link” |
| frontmatter `wiki` resolving to 0 or 2+ | error |

- [ ] **Step 1: Write the failing tests** in `tests/test_check.py`. Use one note per case so each test asserts the exact `(level, line)` pairs: `test_broken_md_link`, `test_case_mismatch`, `test_not_note_relative`, `test_outside_root_warning`, `test_missing_heading_warning`, `test_resolvable_body_wiki_is_error`, `test_ambiguous_body_wiki_is_warning`, `test_block_ref_warning`, `test_transclusion_warning`, `test_attachment_embed_error`, `test_frontmatter_wiki_missing_and_ambiguous_are_errors`, `test_shared_names_alone_are_clean` (two `Tasks.md` files and no links give `[]`), and `test_clean_note` (correct body links and a resolving frontmatter wikilink give `[]`). Add CLI tests: `test_cli_exit_codes` (`main(["check", str(root)])` returns `1` with an error, `0` clean, and `2` for a folder with no config), `test_cli_json` (capture stdout and check that `json.loads` gives a list of dicts with the four keys), and `test_init_writes_config_and_obsidian_settings` (keeps the other keys already in `app.json`, and a second `init` leaves the config unchanged).
- [ ] **Step 2: Run** `python3 -m unittest tests.test_check -v`. Expected: fails.
- [ ] **Step 3: Implement** `check.py` and `cli.py`. `print_findings` writes `format_finding` lines to stdout, or a JSON list with `--json`.
- [ ] **Step 4: Run** `python3 -m unittest discover -s tests -v`. Expected: all pass.
- [ ] **Step 5: Commit** with `git add -A plugins/markdown-links .claude-plugin README.md && git commit -m "markdown-links: check, init, and command line"`.

### Task 5: `convert`

**Files:**
- Create: `mdlinks/convert.py`; Modify: `mdlinks/cli.py` (add the `convert` subparser with `[root]` and `--dry-run`)
- Test: `tests/test_convert.py`

**Interfaces:**
- Consumes: `find_links`, `wikilink`, `md_target`, `paths.relative`, `paths.encode`, `paths.encode_anchor`, `read`/`write`, and `check_root` (for the before and after counts).
- Produces:
  - `convert.convert_text(root: Root, note: Path, text: str) -> tuple[str, int, list[Finding]]` returns the new text, the number of links rewritten, and warnings for the links it left.
  - `convert.convert_root(root: Root, dry_run: bool) -> tuple[list[str], list[Finding]]` returns the root-relative paths it changed (or would change) and the warnings it left.

Rewrites (body only, by replacing `text[start:end]` from last to first):
- A `wiki` that resolves to one file and isn’t a block ref becomes `[label](enc)`.
  - `label` is the `alias`, else the `target` exactly as written (a `[[Folder/N]]` keeps `Folder/N`), else, for `[[#H]]`, the anchor text.
  - `enc` is `encode(relative(note, path))`, plus `#` + `encode_anchor(decode(anchor))` when there’s an anchor. For `[[#H]]` it’s `#` + that anchor alone.
- An `embed` of an image (`png jpg jpeg gif svg webp avif bmp`) becomes `![](enc)`, and any other attachment becomes `[filename](enc)`.
- An `md`, `image`, or `refdef` whose `md_target` has `note_relative=False` and a single resolved path gets its target replaced by `enc`, keeping the anchor and the link text.
- A `]` in the label is escaped as `\]`.

- [ ] **Step 1: Write the failing tests** in `tests/test_convert.py`:
  - `test_convert_forms`: a single note containing each form, with exact expected output text, covering `[[N]]`, `[[N|Al]]`, `[[N#H one]]`, `[[#H]]`, `![[p.png]]`, `![[doc.pdf]]`, `[[Folder/N]]`, nested `../../`, spaces, and a non-ASCII name.
  - `test_convert_table_alias`: `| [[N\|Al]] |` becomes `| [Al](N.md) |`.
  - `test_convert_leaves_alone`: frontmatter wikilinks, code, an ambiguous name, an unresolved name, a transclusion, and a block ref are byte-identical afterward, and each appears in the returned warnings except frontmatter and code.
  - `test_convert_repairs_non_relative`: `[J](Jane%20Doe.md)` and `[J](/People/Jane%20Doe.md)` in `A/x.md` both become `[J](../People/Jane%20Doe.md)`.
  - `test_convert_only_links_change`: after converting a long note with mixed prose, lists, callouts, and links, the result is equal to the input once each rewritten span is replaced back with its original.
  - `test_convert_preserves_crlf_and_bom`: a file written as bytes `b"\xef\xbb\xbf# T\r\n[[N]]\r\n"` becomes exactly `b"\xef\xbb\xbf# T\r\n[N](N.md)\r\n"`.
  - `test_convert_dry_run_writes_nothing`: file modification times and contents are unchanged, and the list of files that would change is returned.
  - `test_convert_then_check_clean`: on a root where every link resolves, `check_root` returns no errors after `convert`.
- [ ] **Step 2: Run** `python3 -m unittest tests.test_convert -v`. Expected: fails.
- [ ] **Step 3: Implement** `convert.py` and its CLI. The CLI prints `converted N links in M files` (or `would convert` with `--dry-run`), then the error and warning counts before and after, then the leftover warnings.
- [ ] **Step 4: Run** `python3 -m unittest discover -s tests -v`. Expected: all pass.
- [ ] **Step 5: Commit** with `git add -A plugins/markdown-links .claude-plugin README.md && git commit -m "markdown-links: convert wikilinks and repair non-relative links"`.

### Task 6: `link`

**Files:**
- Create: `mdlinks/link.py`; Modify: `mdlinks/cli.py` (add `link <from-note> <to> [--text T] [--heading H]`)
- Test: `tests/test_link.py`

**Interfaces:**
- Produces: `link.make_link(root: Root, from_note: Path, to: str, text: str | None = None, heading: str | None = None) -> str`. It raises `link.LinkError(message)` when `to` is missing or ambiguous; the message lists the candidates. `to` is tried first as a path (relative to the current directory, then to the root) and otherwise resolved with `resolve.wikilink`. `from_note` doesn’t have to exist yet, but its folder must be inside the root.

- [ ] **Step 1: Write the failing tests:**
  - `test_link_depths`: from `x.md`, `A/x.md`, and `A/B/C/x.md` to the name `"Jane Doe"`, the output is `[Jane Doe](People/Jane%20Doe.md)`, `[Jane Doe](../People/Jane%20Doe.md)`, and `[Jane Doe](../../../People/Jane%20Doe.md)`.
  - `test_link_text_and_heading`: `--text "Jane"` with `--heading "Contact info"` gives `[Jane](People/Jane%20Doe.md#Contact%20info)`.
  - `test_link_ambiguous_and_missing`: the name `"Tasks"` raises `LinkError` naming `A/Tasks.md` and `B/Tasks.md`. Through the CLI, the same case exits `1` with an `error:` line.
  - `test_link_by_path`: `to="B/Tasks.md"` resolves.
  - `test_link_output_resolves`: running `md_target` on every link produced above resolves it with `note_relative=True`.
- [ ] **Step 2: Run** `python3 -m unittest tests.test_link -v`. Expected: fails.
- [ ] **Step 3: Implement** `link.py` and its CLI. On success it prints just the link and a newline.
- [ ] **Step 4: Run** `python3 -m unittest discover -s tests -v`. Expected: all pass.
- [ ] **Step 5: Commit** with `git add -A plugins/markdown-links .claude-plugin README.md && git commit -m "markdown-links: link command"`.

### Task 7: `mv`

**Files:**
- Create: `mdlinks/move.py`; Modify: `mdlinks/cli.py` (add `mv <src> <dst> [--dry-run]`)
- Test: `tests/test_move.py`

**Interfaces:**
- Produces:
  - `move.MovePlan(moves: list[tuple[Path, Path]], edits: dict[Path, str], boms: dict[Path, bool])`. `moves` maps every file in the moved set, old path to new. `edits` are keyed by each file’s path after the move.
  - `move.plan_move(root: Root, src: Path, dst: Path) -> MovePlan` raises `move.MoveError` when `src` is missing or excluded, when `dst` is outside the root, or when `dst` exists and isn’t the same file under a different case (compare `os.path.samefile`). If `dst` is an existing folder and `src` is a file, the target is `dst/src.name`, matching `mv`.
  - `move.apply(root: Root, plan: MovePlan) -> list[str]` returns the root-relative paths it changed.

Plan algorithm:
1. Build the old-to-new mapping for every file under `src`.
2. For every note in the root, after its own move, find its body links. Resolve each `md`, `image`, or `refdef` link against the *old* layout with `md_target`. If the link resolves and either its target or the note itself moved, replace the path part with `encode(relative(new_note, new_target))`, keeping the anchor and any `angle` form.
3. For wikilinks (frontmatter and body), resolve each against the old index. If its single old match moved and the basename changed, rewrite the name to the new basename, keeping `|alias` and `#anchor`. Then, if the name would be ambiguous in the new index (or the old name was path-qualified), qualify it with the new root-relative path without `.md`.
4. A bare wikilink that resolved to one note before and is ambiguous after the move gets qualified with that note’s new root-relative path.
5. Rewrite by offsets, last to first, keeping the BOM and line endings.

`apply` checks once more that no destination exists, then makes the moves, then writes `edits`. Inside a git work tree (`git -C root rev-parse --is-inside-work-tree` exits 0) it uses `git mv`, and for a case-only rename `git mv` through a temporary name. Otherwise it uses `os.replace`, with a temporary-name step for case-only renames. It makes parent folders as needed.

- [ ] **Step 1: Write the failing tests** in `tests/test_move.py`. Each one ends by asserting `check_root` has no errors:
  - `test_mv_file_rewrites_inbound`: moving `People/Jane Doe.md` to `Contacts/Jane Doe.md` updates `A/x.md`’s `[J](../People/Jane%20Doe.md)` to `[J](../Contacts/Jane%20Doe.md)`.
  - `test_mv_file_rewrites_outbound`: moving `A/x.md` (which links `../People/Jane%20Doe.md`) to `A/B/x.md` changes the link to `../../People/Jane%20Doe.md`.
  - `test_mv_folder`: moving `A` to `Archive/A` rewrites links in both directions, and links inside the folder are unchanged.
  - `test_mv_rename_updates_wikilinks`: renaming `Jane Doe.md` to `Jane Q Doe.md` changes frontmatter `"[[Jane Doe]]"` to `"[[Jane Q Doe]]"` and `"[[Jane Doe|J]]"` to `"[[Jane Q Doe|J]]"`.
  - `test_mv_rename_into_shared_name_qualifies`: renaming `C/Todo.md` to `C/Tasks.md` (with `A/Tasks.md` existing) turns `"[[Todo]]"` into `"[[C/Tasks]]"`.
  - `test_mv_makes_existing_wikilink_ambiguous_qualifies`: start with only `A/Tasks.md` and a frontmatter `"[[Tasks]]"` in another note. Renaming `C/Other.md` to `C/Tasks.md` turns that `"[[Tasks]]"` into `"[[A/Tasks]]"`.
  - `test_mv_case_only_rename`: `mv note.md Note.md` succeeds, `os.listdir` shows `Note.md`, and links are updated to the new case.
  - `test_mv_refusals_change_nothing`: an existing destination, a destination outside the root, and a missing source each raise `MoveError`, and every file’s bytes are unchanged.
  - `test_mv_dry_run_writes_nothing`.
  - `test_mv_uses_git_when_in_repo`: run `git init` in the temp root, commit, run `mv`, and check that `git status --porcelain` shows a rename (`R`). Skip if `git` isn’t found.
- [ ] **Step 2: Run** `python3 -m unittest tests.test_move -v`. Expected: fails.
- [ ] **Step 3: Implement** `move.py` and its CLI. The CLI prints `moved <src> -> <dst>` and then one `updated <path>` line per edited file. On `MoveError` it prints `error: <message>` and returns `1`.
- [ ] **Step 4: Run** `python3 -m unittest discover -s tests -v`. Expected: all pass.
- [ ] **Step 5: Commit** with `git add -A plugins/markdown-links .claude-plugin README.md && git commit -m "markdown-links: mv keeps links correct through moves and renames"`.

### Task 8: Hook

**Files:**
- Create: `mdlinks/hook.py`, `hooks/hooks.json`; Modify: `mdlinks/cli.py` (hidden `hook` subcommand, which reads stdin)
- Test: `tests/test_hook.py`

**Interfaces:**
- Produces: `hook.run(payload_text: str) -> tuple[int, str]` returns the exit code and the stderr text.
  - It reads `tool_input.file_path` from the JSON payload.
  - It returns `(0, "")` for invalid JSON, a missing path, a non-`.md` file, a file that doesn’t exist, no root, an excluded path, or any exception while reading or decoding the file.
  - Otherwise it runs `check_file`. With errors, it returns `(2, header + lines)`, where the header is `markdown-links: fix these links in <rel>:` and the lines are the errors only, one `format_finding` line each.
  - With only warnings, it returns `(0, "")`.

`hooks/hooks.json`:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write|Edit|MultiEdit",
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/skills/markdown-links/scripts/markdown-links.py\" hook"
          }
        ]
      }
    ]
  }
}
```

- [ ] **Step 1: Write the failing tests** in `tests/test_hook.py`:
  - `test_hook_errors_exit_2`: a payload for a note containing `[[Jane Doe]]` returns `2`, and the stderr text contains `use a Markdown link`.
  - `test_hook_warnings_only_silent`: a note with an unresolved `[[Nope]]` returns `(0, "")`.
  - `test_hook_clean`: returns `(0, "")`.
  - `test_hook_ignores_odd_payloads`: `"not json"`, `{}`, a `.txt` file, a deleted path, a file outside any root, and a file containing `b"\xff\xfe bad"` each return `(0, "")`.
  - `test_hook_via_subprocess`: run `python3 skills/markdown-links/scripts/markdown-links.py hook` with the payload on stdin, and check the exit code is `2` and stderr isn’t empty. This proves the entry script and `hooks.json` command work end to end.
- [ ] **Step 2: Run** `python3 -m unittest tests.test_hook -v`. Expected: fails.
- [ ] **Step 3: Implement** `hook.py`, the CLI wiring (write the stderr text, exit with the code), and `hooks.json`.
- [ ] **Step 4: Run** `python3 -m unittest discover -s tests -v`. Expected: all pass.
- [ ] **Step 5: Time it.** Generate 5,000 notes, each with 3 links, in a temp root, then time `python3 …/markdown-links.py hook` on one of them 5 times. The median must be 1.0 second or less. If it’s slower, profile and fix before committing; caching the file index is allowed only if it can never report a missing file as present. Record the median in the commit message.
- [ ] **Step 6: Commit** with `git add -A plugins/markdown-links .claude-plugin README.md && git commit -m "markdown-links: PostToolUse hook checks each edited note (median <N>s on 5,000 notes)"`.

### Task 9: Skill, packaging, and docs

**Files:**
- Create: `skills/markdown-links/SKILL.md`, `.claude-plugin/plugin.json`, `README.md`
- Modify: repo-root `.claude-plugin/marketplace.json` (add an entry), repo-root `README.md` (add a table row)

**Content decisions:**
- `plugin.json`: `{"name": "markdown-links", "description": "Keeps links between Markdown notes working everywhere: converts [[wikilinks]] to relative links, writes and checks links, and moves notes without breaking them.", "author": {"name": "One Good Idea"}, "license": "MIT"}`.
- `SKILL.md` frontmatter:
  - `name: markdown-links`.
  - A `description` that triggers on writing, editing, linking, moving, or renaming Markdown notes, on a folder containing `.markdown-links.json`, and on “convert wikilinks” or “fix broken links”.
- The `SKILL.md` body covers, in this order:
  - the link rules from the spec’s Link rules section, in brief;
  - the script path, `scripts/markdown-links.py` in this skill’s base directory, always called with `python3` and the absolute path;
  - when to use `link`;
  - that `mv` is the only way to move or rename a note, never shell `mv`, `git mv`, or a file manager;
  - what to do after a hook error;
  - running `check` after bulk edits;
  - the steps for bringing in a new folder.
  Keep it under 80 lines.
- `README.md`: what it does, install (copy the pattern from `plugins/checklist/README.md`), the link rules, each command with one example, how to call the script from a shell, and adoption.
  - The shell path is `~/.claude/plugins/cache/onegoodidea/markdown-links/<version>/skills/markdown-links/scripts/markdown-links.py`. Note that the version folder changes on update.
  - Adoption: update whatever writes links before `init`.
  - Coexistence with Obsidian goes in one line, filled in by Step 3.
  - Credit: “Parsing approach adapted from m4bwav/obsidian-notes (MIT).” The copyright line goes in the header of `parse.py` if code was adapted.
- Marketplace entry: `{"name": "markdown-links", "source": "./plugins/markdown-links", "description": "<same as plugin.json>"}`. Root README row: `| [markdown-links](plugins/markdown-links) | <one sentence> |`.

- [ ] **Step 1: Write the files** listed above.
- [ ] **Step 2: Check the wording rule.** Run `grep -rniw vault plugins/markdown-links`. Expected: no output.
- [ ] **Step 3: Manual check with Obsidian open.** Make a scratch folder of 3 notes, then `init` and `convert` it, and open it in Obsidian. Run `mv` on a note that another note links to, wait 5 seconds, then run `git diff` (or compare file hashes). Expected: only the edits `mv` printed. Write the outcome into the README’s coexistence line: either “Safe with Obsidian open” or “Close Obsidian before running mv.” This step needs the owner if it runs on a machine without Obsidian; ask rather than skip.
- [ ] **Step 4: Install locally and smoke-test.** Run `claude plugin marketplace add <path to this worktree>` (or point an existing marketplace at the worktree), then install `markdown-links`. In a new session, in a scratch root, ask Claude to write a note that links to another note. Expected: the skill loads, and the note it writes uses a relative Markdown link. Then ask it to write `[[Other]]` by hand. Expected: the hook’s error shows up in that turn.
- [ ] **Step 5: Run** `python3 -m unittest discover -s tests -v` one last time. Expected: all pass.
- [ ] **Step 6: Commit** with `git add -A plugins/markdown-links .claude-plugin README.md && git commit -m "markdown-links: skill, plugin manifest, README, and marketplace entry"`.
