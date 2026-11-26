from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from .model import Root

CONFIG_NAME = ".markdown-links.json"


def find_root(path: Path) -> Optional[Path]:
    path = Path(os.path.abspath(path))
    if path.is_file():
        path = path.parent
    for folder in [path, *path.parents]:
        if (folder / CONFIG_NAME).is_file():
            return folder
    return None


def rel(root: Root, path: Path) -> str:
    return Path(path).relative_to(root.path).as_posix()


def _excluded(rel_dir: str, exclude) -> bool:
    return any(rel_dir == e or rel_dir.startswith(e + "/") for e in exclude)


def load(root_path: Path) -> Root:
    root_path = Path(root_path)
    config = json.loads((root_path / CONFIG_NAME).read_text(encoding="utf-8"))
    exclude = [e.strip("/") for e in config.get("exclude", [])]
    found = []
    for dirpath, dirnames, filenames in os.walk(root_path):
        here = Path(dirpath)
        rel_here = here.relative_to(root_path).as_posix()
        dirnames[:] = [
            d
            for d in dirnames
            if not d.startswith(".")
            and not _excluded(d if rel_here == "." else f"{rel_here}/{d}", exclude)
        ]
        for name in filenames:
            if here == root_path and name == CONFIG_NAME:
                continue
            found.append(here / name)
    return index(root_path, exclude, found)


def index(root_path: Path, exclude, paths) -> Root:
    """A Root over the given files, without reading the disk."""
    notes = sorted(p for p in paths if p.name.lower().endswith(".md"))
    files = sorted(p for p in paths if not p.name.lower().endswith(".md"))
    by_name = {}
    for note in notes:
        by_name.setdefault(note.name.lower()[:-3], []).append(note)
        by_name.setdefault(note.name.lower(), []).append(note)
    for f in files:
        by_name.setdefault(f.name.lower(), []).append(f)
    return Root(root_path, exclude, notes, files, by_name)
