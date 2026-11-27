from __future__ import annotations

import json
import os
import re
import shlex
from pathlib import Path
from typing import Callable, Dict, List, Tuple

from . import check as checkmod
from . import paths, resolve
from . import relink
from . import root as rootmod
from .model import Link, Root, format_finding


def run(payload_text: str) -> Tuple[int, str]:
    """PostToolUse entry: (exit code, stderr text). Silent (0, "") on anything odd."""
    try:
        return _run(payload_text)
    except Exception:
        return 0, ""


MOVE_OR_REMOVE = re.compile(r"(?:^|[\s;&|(])(?:git\s+)?(?:mv|rm)\s")
SCRIPT = Path(__file__).resolve().parent.parent / "markdown-links.py"
MAX_ROOTS = 5


def _words(command: str) -> List[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


def _bash_roots(words: List[str], cwd: str) -> List[Path]:
    folders = [cwd] if cwd else []
    for word in words:
        path = os.path.join(cwd, word) if cwd else word
        if os.path.exists(path):
            folders.append(path)  # find_root starts from a file's folder
        elif os.path.isdir(os.path.dirname(path)):
            folders.append(os.path.dirname(path))
    roots: List[Path] = []
    for folder in folders:
        found = rootmod.find_root(Path(folder))
        if found is not None and found not in roots:
            roots.append(found)
            if len(roots) == MAX_ROOTS:
                break
    return roots


def _wikilink_within(root_key: str, target: str, within: List[str]) -> bool:
    """A wikilink names a file by its trailing path, so it is under a command path when that
    path covers the root, or ends with the start of the target: People/ or Jane Doe.md for
    [[People/Jane Doe]]."""
    segments = paths.fold(target.strip().strip("/")).split("/")
    forms = [segments[:-1] + [segments[-1] + ".md"]] if not segments[-1].endswith(".md") else []
    if os.path.splitext(segments[-1])[1]:
        forms.append(segments)
    for top in within:
        if paths.at_or_under(root_key, top):
            return True
        if not paths.at_or_under(top, root_key):
            continue
        tail = top[len(root_key.rstrip("/")) + 1:].split("/")
        for form in forms:
            if any(tail[-k:] == form[:k] for k in range(1, min(len(tail), len(form)) + 1)):
                return True
    return False


def _caused_by(root: Root, within: List[str]) -> Callable[[Path, Link], bool]:
    """Whether a link could have been broken by a command naming these paths: the path it
    names, or the note that holds it, is at or under one of them."""
    root_key = paths.key(root.path)
    holder: Dict[Path, bool] = {}

    def counts(note: Path, link: Link) -> bool:
        if note not in holder:
            holder[note] = any(paths.at_or_under(paths.key(note), top) for top in within)
        if holder[note]:
            return True
        if link.kind in ("wiki", "embed"):
            return _wikilink_within(root_key, link.target, within)
        named = paths.key(relink._named(root, note, link.target))
        return any(paths.at_or_under(named, top) for top in within)

    return counts


def _run_bash(payload: dict) -> Tuple[int, str]:
    command = payload["tool_input"]["command"]
    if not isinstance(command, str) or not MOVE_OR_REMOVE.search(command) or "markdown-links.py" in command:
        return 0, ""
    cwd = payload.get("cwd")
    cwd = cwd if isinstance(cwd, str) else ""
    words = _words(command)
    within = [paths.key(os.path.abspath(os.path.join(cwd, w))) for w in words if w]
    lines = []
    for root_path in _bash_roots(words, cwd):
        try:
            root = rootmod.load(root_path)
            broken = relink.count_broken(root, _caused_by(root, within))
        except Exception:
            continue  # one unreadable root (bad config) shouldn't hide the others
        if broken:
            noun = "1 broken link" if broken == 1 else f"{broken} broken links"
            lines.append(
                f'markdown-links: {noun} in {root_path}; '
                f'run: python3 "{SCRIPT}" relink "{root_path}"')
    return (2, "\n".join(lines) + "\n") if lines else (0, "")


def _run(payload_text: str) -> Tuple[int, str]:
    payload = json.loads(payload_text)
    if payload.get("tool_name") == "Bash":
        return _run_bash(payload)
    file_path = payload["tool_input"]["file_path"]
    if not isinstance(file_path, str) or not file_path:
        return 0, ""
    if not file_path.lower().endswith(".md"):
        return 0, ""
    cwd = payload.get("cwd")
    if isinstance(cwd, str) and cwd:
        file_path = os.path.join(cwd, file_path)  # absolute file_path wins
    note = Path(os.path.abspath(file_path))
    if not note.is_file():
        return 0, ""
    root_path = rootmod.find_root(note)
    if root_path is None:
        return 0, ""
    root = rootmod.load(root_path)
    rel = rootmod.rel(root, note)
    if resolve._excluded(root, note) or any(p.startswith(".") for p in rel.split("/")[:-1]):
        return 0, ""
    errors = [f for f in checkmod.check_file(root, note) if f.level == "error"]
    if not errors:
        return 0, ""
    header = f"markdown-links: fix these links in {rel}:"
    return 2, "\n".join([header] + [format_finding(f) for f in errors]) + "\n"
