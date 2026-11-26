from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List, Optional, Tuple

from . import check as checkmod
from . import convert as convertmod
from . import link as linkmod
from . import move as movemod
from . import root as rootmod
from .model import Finding, Root, format_finding

OBSIDIAN_SETTINGS = {
    "useMarkdownLinks": True,
    "newLinkFormat": "relative",
    "alwaysUpdateLinks": True,
}


def _finding_dict(f: Finding) -> dict:
    return {"level": f.level, "file": f.file, "line": f.line, "message": f.message}


def print_findings(findings: List[Finding], as_json: bool) -> None:
    if as_json:
        print(json.dumps([_finding_dict(f) for f in findings], indent=2))
    else:
        for f in findings:
            print(format_finding(f))


def _config_error(config: Path) -> Optional[str]:
    """Reason the config is unusable, or None when it is fine."""
    try:
        data = json.loads(config.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as e:
        return f"cannot read ({e})"
    except ValueError as e:
        return f"invalid JSON ({e})"
    if not isinstance(data, dict):
        return "must be a JSON object"
    exclude = data.get("exclude", [])
    if not isinstance(exclude, list) or not all(isinstance(e, str) for e in exclude):
        return '"exclude" must be a list of strings'
    return None


def open_root(path: Path) -> Tuple[Optional[Root], int]:
    """Find and load the root at or above path.

    Returns (root, 0), or (None, 1) after printing the error when there is no root
    or the config is unusable.
    """
    path = Path(os.path.abspath(path))
    root_path = rootmod.find_root(path)
    if root_path is None:
        print(f"error: no {rootmod.CONFIG_NAME} at or above {path}", file=sys.stderr)
        return None, 1
    config = root_path / rootmod.CONFIG_NAME
    reason = _config_error(config)
    if reason:
        print(f"error: {config}: {reason}", file=sys.stderr)
        return None, 1
    return rootmod.load(root_path), 0


def _exit_code(findings: List[Finding]) -> int:
    return 1 if any(f.level == "error" for f in findings) else 0


def init(folder: Path) -> List[str]:
    folder = Path(folder)
    wrote: List[str] = []
    config = folder / rootmod.CONFIG_NAME
    if not config.exists():
        config.write_text('{"exclude": []}\n', encoding="utf-8")
        wrote.append(f"wrote {config}")
    app = folder / ".obsidian" / "app.json"
    if app.is_file():
        data = json.loads(app.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"{app} is not a JSON object")
        merged = {**data, **OBSIDIAN_SETTINGS}
        if merged != data:
            app.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
            wrote.append(f"updated {app}")
    return wrote


def _cmd_init(args) -> int:
    folder = Path(os.path.abspath(args.folder))
    if not folder.is_dir():
        print(f"error: {folder} is not a folder", file=sys.stderr)
        return 1
    try:
        wrote = init(folder)
    except (ValueError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print("\n".join(wrote) if wrote else "already set up; nothing written")
    return 0


def _cmd_check(args) -> int:
    path = Path(os.path.abspath(args.path))
    root, code = open_root(path)
    if root is None:
        return code
    if path.is_file():
        if path not in root.notes:
            print(f"error: {path} is not a note in this root", file=sys.stderr)
            return 1
        findings = checkmod.check_file(root, path)
    else:
        findings = checkmod.check_root(root)
    print_findings(findings, args.json)
    return _exit_code(findings)


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" + ("" if count == 1 else "s")


def _tally(findings: List[Finding]) -> dict:
    errors = sum(f.level == "error" for f in findings)
    return {"errors": errors, "warnings": len(findings) - errors}


def _counts(findings: List[Finding]) -> str:
    t = _tally(findings)
    return f"{_plural(t['errors'], 'error')}, {_plural(t['warnings'], 'warning')}"


def _cmd_convert(args) -> int:
    path = Path(os.path.abspath(args.root))
    root, code = open_root(path)
    if root is None:
        return code
    if path != root.path:
        print(f"error: convert works on a whole root; run it on {root.path}", file=sys.stderr)
        return 1
    before = checkmod.check_root(root)
    changes, leftover, texts = convertmod.convert_all(root, args.dry_run)
    if args.dry_run:
        after = checkmod.check_root(root, texts)  # what a real run would leave
    else:
        after = checkmod.check_root(rootmod.load(root.path))
    findings = [f for f in after if f.level == "error"] + leftover
    if args.json:
        print(json.dumps({
            "changes": [{"file": c.file, "line": c.line, "old": c.old, "new": c.new}
                        for c in changes],
            "findings": [_finding_dict(f) for f in findings],
            "before": _tally(before),
            "after": _tally(after),
        }, indent=2))
    else:
        verb = "would convert" if args.dry_run else "converted"
        for c in changes:
            print(f"{verb} {c.file}:{c.line}: {c.old} -> {c.new}")
        files = len({c.file for c in changes})
        print(f"{verb} {_plural(len(changes), 'link')} in {_plural(files, 'file')}")
        print(f"before: {_counts(before)}")
        print(f"after: {_counts(after)}")
        print_findings(findings, False)
    return _exit_code(before if args.dry_run else after)  # a dry run leaves the disk as it was


def _cmd_link(args) -> int:
    from_note = Path(os.path.abspath(args.from_note))
    root, code = open_root(from_note.parent if not from_note.is_dir() else from_note)
    if root is None:
        return code
    try:
        md = linkmod.make_link(root, from_note, args.to, args.text, args.heading)
    except linkmod.LinkError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(json.dumps({"link": md}) if args.json else md)
    return 0


def _cmd_mv(args) -> int:
    src = Path(os.path.abspath(args.src))
    dst = Path(os.path.abspath(args.dst))
    root, code = open_root(src.parent)
    if root is None:
        return code
    try:
        plan = movemod.plan_move(root, src, dst)
        changed = [] if args.dry_run else movemod.apply(root, plan)
    except movemod.MoveError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    updated = [rootmod.rel(root, p) for p in sorted(plan.edits)] if args.dry_run else changed
    if args.json:
        print(json.dumps({
            "moves": [{"from": rootmod.rel(root, a), "to": rootmod.rel(root, b)}
                      for a, b in plan.moves],
            "updated": updated,
            "findings": [_finding_dict(f) for f in plan.warnings],
        }, indent=2))
        return 0
    moved, update = ("would move", "would update") if args.dry_run else ("moved", "updated")
    print(f"{moved} {rootmod.rel(root, plan.src)} -> {rootmod.rel(root, plan.dst)}")
    for rel in updated:
        print(f"{update} {rel}")
    print_findings(plan.warnings, False)
    return 0


def _cmd_hook(args) -> int:
    from . import hook

    code, err = hook.run(sys.stdin.read())
    if err:
        sys.stderr.write(err)
    return code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="markdown-links", description="Keep links between Markdown notes portable."
    )
    json_help = "print machine-readable JSON (before or after the command)"
    parser.add_argument("--json", action="store_true", help=json_help)
    # Also accepted after the command; SUPPRESS keeps a --json given before it.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=json_help)
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name: str, **kw) -> argparse.ArgumentParser:
        return sub.add_parser(name, parents=[common], **kw)

    p = add("init", help="create .markdown-links.json in a folder")
    p.add_argument("folder", nargs="?", default=".")
    p.set_defaults(func=_cmd_init)

    p = add("check", help="report broken or non-portable links")
    p.add_argument("path", nargs="?", default=".")
    p.set_defaults(func=_cmd_check)

    p = add("convert", help="turn wikilinks and non-relative links into note-relative links")
    p.add_argument("root", nargs="?", default=".")
    p.add_argument("--dry-run", action="store_true", help="report what would change; write nothing")
    p.set_defaults(func=_cmd_convert)

    p = add("link", help="print a note-relative link from one note to another")
    p.add_argument("from_note", help="the note the link will be written in (may not exist yet)")
    p.add_argument("to", help="a note name or a path to the target")
    p.add_argument("--text", help="link text (default: the target's name)")
    p.add_argument("--heading", help="heading text to link to")
    p.set_defaults(func=_cmd_link)

    p = add("mv", help="move or rename a note or folder and keep links correct")
    p.add_argument("src", help="the file or folder to move")
    p.add_argument("dst", help="the new path (an existing folder takes a file inside it)")
    p.add_argument("--dry-run", action="store_true", help="report what would change; write nothing")
    p.set_defaults(func=_cmd_mv)

    p = sub.add_parser("hook")  # PostToolUse entry; no help text on purpose
    p.set_defaults(func=_cmd_hook)
    return parser


def main(argv: List[str]) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
