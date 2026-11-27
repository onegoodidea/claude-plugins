from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from . import paths, resolve
from .model import Root


class LinkError(Exception):
    pass


def _as_path(root: Root, to: str) -> Optional[Path]:
    """The file `to` names as a path (relative to the current directory, then the root)."""
    candidates = [Path(os.path.abspath(to))] if os.path.isabs(to) else [
        Path(os.path.abspath(to)),
        Path(os.path.abspath(root.path / to)),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _check_inside(root: Root, path: Path) -> None:
    under = resolve._under(root, path)
    if under is None:
        raise LinkError(f"{path} is outside the root {root.path}")
    if resolve._excluded(root, path):
        raise LinkError(f"{under} is in an excluded folder")


def make_link(
    root: Root,
    from_note: Path,
    to: str,
    text: Optional[str] = None,
    heading: Optional[str] = None,
) -> str:
    from_note = Path(os.path.abspath(from_note))
    if resolve._under(root, from_note.parent) is None:
        raise LinkError(f"{from_note} is outside the root {root.path}")

    target = _as_path(root, to)
    if target is not None:
        _check_inside(root, target)
        # A disk that ignores case or Unicode form accepts other spellings; link the real one.
        on_disk = resolve._walk(root, root.path, resolve._under(root, target).split("/"))
        if on_disk is not None:
            target = on_disk[0]
    else:
        found = resolve.wikilink(root, to)
        if not found:
            raise LinkError(f"no note matches {to!r}")
        if len(found) > 1:
            names = ", ".join(sorted(p.relative_to(root.path).as_posix() for p in found))
            raise LinkError(f"{to!r} is ambiguous: {names}")
        target = found[0]

    label = text if text is not None else (
        target.name[:-3] if resolve.is_note(target) else target.name
    )
    label = label.replace("[", "\\[").replace("]", "\\]")
    href = paths.encode(paths.relative(from_note, target))
    if heading:
        href += "#" + paths.encode_anchor(heading)
    return f"[{label}]({href})"
