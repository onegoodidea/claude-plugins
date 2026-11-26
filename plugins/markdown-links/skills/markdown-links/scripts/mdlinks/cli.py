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
from . import root as rootmod
from .model import Finding, Root, format_finding

OBSIDIAN_SETTINGS = {
    "useMarkdownLinks": True,
    "newLinkFormat": "relative",
    "alwaysUpdateLinks": True,
}


def print_findings(findings: List[Finding], as_json: bool) -> None:
    if as_json:
        print(json.dumps([
            {"level": f.level, "file": f.file, "line": f.line, "message": f.message}
            for f in findings
        ], indent=2))
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

    Returns (root, 0), or (None, exit code) after printing the error: 2 when there is
    no root, 1 when the config is unusable.
    """
    path = Path(os.path.abspath(path))
    root_path = rootmod.find_root(path)
    if root_path is None:
        print(f"error: no {rootmod.CONFIG_NAME} at or above {path}", file=sys.stderr)
        return None, 2
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


def _counts(findings: List[Finding]) -> str:
    errors = sum(f.level == "error" for f in findings)
    return f"{errors} errors, {len(findings) - errors} warnings"


def _cmd_convert(args) -> int:
    root, code = open_root(Path(os.path.abspath(args.root)))
    if root is None:
        return code
    before = checkmod.check_root(root)
    changed, leftover, total = convertmod.convert_all(root, args.dry_run)
    after = before if args.dry_run else checkmod.check_root(rootmod.load(root.path))
    if not args.json:
        verb = "would convert" if args.dry_run else "converted"
        print(f"{verb} {total} links in {len(changed)} files")
        print(f"before: {_counts(before)}")
        if not args.dry_run:
            print(f"after: {_counts(after)}")
    print_findings(leftover, args.json)
    return _exit_code(after)


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="markdown-links", description="Keep links between Markdown notes portable."
    )
    parser.add_argument("--json", action="store_true", help="print findings as JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="create .markdown-links.json in a folder")
    p.add_argument("folder", nargs="?", default=".")
    p.set_defaults(func=_cmd_init)

    p = sub.add_parser("check", help="report broken or non-portable links")
    p.add_argument("path", nargs="?", default=".")
    p.set_defaults(func=_cmd_check)

    p = sub.add_parser("convert", help="turn wikilinks and non-relative links into note-relative links")
    p.add_argument("root", nargs="?", default=".")
    p.add_argument("--dry-run", action="store_true", help="report what would change; write nothing")
    p.set_defaults(func=_cmd_convert)

    p = sub.add_parser("link", help="print a note-relative link from one note to another")
    p.add_argument("from_note", help="the note the link will be written in (may not exist yet)")
    p.add_argument("to", help="a note name or a path to the target")
    p.add_argument("--text", help="link text (default: the target's name)")
    p.add_argument("--heading", help="heading text to link to")
    p.set_defaults(func=_cmd_link)
    return parser


def main(argv: List[str]) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
