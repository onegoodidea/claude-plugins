from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import check, convert, parse, paths, resolve
from . import root as rootmod
from .convert import Change
from .model import Finding, Link, Root
from .move import wiki_name


def _git(root: Root, *args: str) -> Optional[bytes]:
    try:
        done = subprocess.run(["git", "-C", str(root.path), *args], capture_output=True)
    except OSError:
        return None
    return done.stdout if done.returncode == 0 else None


def git_renames(root: Root) -> Dict[Path, Path]:
    """Staged renames in the root's git work tree: absolute old path -> absolute new path."""
    if shutil.which("git") is None:
        return {}
    top = _git(root, "rev-parse", "--show-toplevel")
    status = _git(root, "status", "--porcelain=v1", "-z")
    if not top or not status:
        return {}
    top_path = Path(os.path.realpath(os.fsdecode(top).strip()))
    real_root = Path(os.path.realpath(root.path))

    def in_root(git_path: str) -> Optional[Path]:
        try:
            return root.path / (top_path / git_path).relative_to(real_root)
        except ValueError:
            return None

    renames: Dict[Path, Path] = {}
    entries = [os.fsdecode(e) for e in status.split(b"\0")]
    i = 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if len(entry) < 4:
            continue
        x, y, new = entry[0], entry[1], entry[3:]
        if x in "RC" or y in "RC":  # these carry the original path as the next entry
            old = entries[i] if i < len(entries) else ""
            i += 1
            if x == "R" and old:
                old_abs, new_abs = in_root(old), in_root(new)
                if old_abs is not None and new_abs is not None:
                    renames[old_abs] = new_abs
    return renames


def is_broken(root: Root, note: Path, link: Link) -> bool:
    """A body Markdown link to a file that isn't there, or a frontmatter wikilink that
    matches no file. relink, its leftover report, and the Bash hook share this."""
    if link.kind in ("md", "image", "refdef"):
        return link.target != "" and resolve.md_target(root, note, link.target).path is None
    if link.kind in ("wiki", "embed") and link.in_frontmatter:
        return link.target != "" and not resolve.wikilink(root, link.target)
    return False


def _readable_links(note: Path) -> Optional[Tuple[str, bool, List[Link]]]:
    try:
        text, bom = parse.read(note)
    except (UnicodeDecodeError, OSError):
        return None
    return text, bom, parse.find_links(text)


def count_broken(root: Root) -> int:
    total = 0
    for note in root.notes:
        read = _readable_links(note)
        if read:
            total += sum(is_broken(root, note, link) for link in read[2])
    return total


def _named(root: Root, note: Path, target: str) -> Path:
    """The absolute path a link names, from note's folder, normalized."""
    decoded = paths.decode(target)
    if decoded.startswith("/"):
        return Path(os.path.normpath(root.path / decoded.lstrip("/")))
    return Path(os.path.normpath(Path(note).parent / decoded))


def _segments(root: Root, path: Path) -> List[str]:
    try:
        parts = path.relative_to(root.path).parts
    except ValueError:
        parts = path.parts
    return [paths.fold(p) for p in parts]


def _shared_tail(a: List[str], b: List[str]) -> int:
    n = 0
    while n < min(len(a), len(b)) and a[-1 - n] == b[-1 - n]:
        n += 1
    return n


def _by_filename(root: Root, named: Path) -> Optional[Path]:
    """The one file of that name sharing the most trailing path segments, or None."""
    if not named.name:
        return None
    wanted = paths.fold(named.name)
    tail = _segments(root, named)
    scored = []
    for cand in dict.fromkeys(root.by_name.get(wanted, [])):
        if paths.fold(cand.name) == wanted and cand.is_file():
            scored.append((_shared_tail(_segments(root, cand), tail), cand))
    if not scored:
        return None
    best = max(s for s, _ in scored)
    winners = [c for s, c in scored if s == best]
    return winners[0] if len(winners) == 1 else None


def _new_target(
    root: Root, note: Path, link: Link,
    renames: Dict[Path, Path], reverse: Dict[Path, Path],
) -> Optional[Path]:
    old_note = reverse.get(note)  # where this note was before git moved it
    base = old_note or note
    if old_note is not None:
        found = resolve.md_target(root, old_note, link.target).path
        if found is not None:
            return found
    named = _named(root, base, link.target)
    moved = renames.get(named)
    if moved is not None and moved.is_file():
        return moved
    return _by_filename(root, named)


def _new_wikilink(
    root: Root, old_root: Root, renames: Dict[Path, Path], link: Link
) -> Optional[str]:
    hits = resolve.wikilink(old_root, link.target)
    if len(hits) != 1:
        return None
    new = renames.get(hits[0])
    if new is None:
        return None
    name = wiki_name(root, new, "/" in link.target.strip("/"))
    if resolve.wikilink(root, name) != [new]:
        name = wiki_name(root, new, True)
    if resolve.wikilink(root, name) != [new]:
        return None
    return parse.replace_target(link, name)


def relink_all(root: Root, dry_run: bool) -> Tuple[List[Change], List[Finding]]:
    """Repair broken links after moves made outside mv. Returns the changes made (or that
    would be) and an error finding for each broken link left."""
    renames = git_renames(root)
    reverse = {new: old for old, new in renames.items()}
    old_root = None
    if renames:
        old_paths = [reverse.get(p, p) for p in root.notes + root.files]
        old_root = rootmod.index(root.path, root.exclude, old_paths)

    changes: List[Change] = []
    findings: List[Finding] = []
    for note in root.notes:
        read = _readable_links(note)
        if read is None:
            continue
        text, bom, links = read
        rel = rootmod.rel(root, note)
        edits: List[Tuple[Link, str]] = []
        for link in links:
            if not is_broken(root, note, link):
                continue
            new: Optional[str] = None
            if link.in_frontmatter:
                if old_root is not None:
                    new = _new_wikilink(root, old_root, renames, link)
            else:
                target = _new_target(root, note, link, renames, reverse)
                if target is not None:
                    new = parse.replace_target(link, paths.encode(paths.relative(note, target)))
            if new is None or new == link.raw:
                message = "wikilink matches no file" if link.in_frontmatter else "broken link"
                findings.append(Finding("error", rel, link.line, f"{message}: {check._shown(link)}"))
            else:
                edits.append((link, new))
        if not edits:
            continue
        changes.extend(Change(rel, link.line, link.raw, new) for link, new in edits)
        if not dry_run:
            parse.write(note, convert._apply(text, edits), bom)
    return changes, findings
