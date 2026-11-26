from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Tuple

from . import check as checkmod
from . import resolve
from . import root as rootmod
from .model import format_finding


def run(payload_text: str) -> Tuple[int, str]:
    """PostToolUse entry: (exit code, stderr text). Silent (0, "") on anything odd."""
    try:
        return _run(payload_text)
    except Exception:
        return 0, ""


def _run(payload_text: str) -> Tuple[int, str]:
    payload = json.loads(payload_text)
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
