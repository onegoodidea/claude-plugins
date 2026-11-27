from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional, Tuple

from . import paths
from .model import MdTarget, Root


def is_note(path: Path) -> bool:
    return path.name.lower().endswith(".md")


def wikilink(root: Root, name: str) -> List[Path]:
    """Resolve a wikilink name to notes (or, for non-.md names, other files)."""
    lname = paths.fold(name.strip().strip("/"))
    if not lname:
        return []
    base = lname[:-3] if lname.endswith(".md") else lname
    last = base.rsplit("/", 1)[-1]

    def matches(p: Path, whole: str) -> bool:
        r = paths.fold(p.relative_to(root.path).as_posix())
        if r.endswith(".md"):
            r = r[:-3]
        return "/" not in whole or r == whole or r.endswith("/" + whole)

    notes = [p for p in root.by_name.get(last, []) if is_note(p) and matches(p, base)]
    if notes:
        return notes
    ext = os.path.splitext(lname)[1]
    if ext and ext != ".md":
        flast = lname.rsplit("/", 1)[-1]

        def file_matches(p: Path) -> bool:
            r = paths.fold(p.relative_to(root.path).as_posix())
            return "/" not in lname or r == lname or r.endswith("/" + lname)

        return [p for p in root.by_name.get(flast, []) if not is_note(p) and file_matches(p)]
    return []


def _under(root: Root, path: Path) -> Optional[str]:
    """Root-relative POSIX path, or None when path is outside the root."""
    try:
        return path.relative_to(root.path).as_posix()
    except ValueError:
        return None


def _excluded(root: Root, path: Path) -> bool:
    r = _under(root, path)
    if r is None:
        return False
    return any(r == e or r.startswith(e + "/") for e in root.exclude)


def _walk(root: Root, start: Path, segments: List[str]) -> Optional[Tuple[Path, bool]]:
    """Resolve segments from start, one at a time: exact spelling first, then any case
    or Unicode form (reported as not exact, since GitHub matches bytes)."""
    current = Path(os.path.abspath(start))
    exact = True
    for seg in segments:
        if seg in ("", "."):
            continue
        if seg == "..":
            current = current.parent
            continue
        try:
            entries = os.listdir(current)
        except OSError:
            return None
        if seg in entries:
            current = current / seg
            continue
        folded = [e for e in entries if paths.fold(e) == paths.fold(seg)]
        if not folded:
            return None
        current = current / sorted(folded)[0]
        exact = False
    if not current.is_file() or _excluded(root, current):
        return None
    return current, exact


def md_target(root: Root, from_note: Path, target: str) -> MdTarget:
    decoded = paths.decode(target)
    if decoded == "":
        return MdTarget(from_note, True, False, True)

    def result(found: Tuple[Path, bool], note_relative: bool) -> MdTarget:
        path, exact = found
        return MdTarget(path, exact, _under(root, path) is None, note_relative)

    if decoded.startswith("/"):
        found = _walk(root, root.path, decoded.split("/"))
        return result(found, False) if found else MdTarget(None, True, False, False)

    # Everything else, a bare filename included, resolves only from the note's folder.
    found = _walk(root, Path(from_note).parent, decoded.split("/"))
    return result(found, True) if found else MdTarget(None, True, False, True)
