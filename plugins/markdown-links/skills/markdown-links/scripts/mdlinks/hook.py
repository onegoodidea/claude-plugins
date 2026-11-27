from __future__ import annotations

import json
import os
import re
import shlex
from pathlib import Path
from typing import List, Tuple

from . import check as checkmod
from . import resolve
from . import relink
from . import root as rootmod
from .model import format_finding


def run(payload_text: str) -> Tuple[int, str]:
    """PostToolUse entry: (exit code, stderr text). Silent (0, "") on anything odd."""
    try:
        return _run(payload_text)
    except Exception:
        return 0, ""


MOVE_OR_REMOVE = re.compile(r"(?:^|[\s;&|(])(?:git\s+)?(?:mv|rm)\s")
SCRIPT = Path(__file__).resolve().parent.parent / "markdown-links.py"
MAX_ROOTS = 5


def _bash_roots(command: str, cwd: str) -> List[Path]:
    try:
        words = shlex.split(command)
    except ValueError:
        words = command.split()
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


def _run_bash(payload: dict) -> Tuple[int, str]:
    command = payload["tool_input"]["command"]
    if not isinstance(command, str) or not MOVE_OR_REMOVE.search(command) or "markdown-links.py" in command:
        return 0, ""
    cwd = payload.get("cwd")
    lines = []
    for root_path in _bash_roots(command, cwd if isinstance(cwd, str) else ""):
        try:
            broken = relink.count_broken(rootmod.load(root_path))
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
