from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple

from . import check, convert, parse, paths, resolve
from . import root as rootmod
from .convert import Change
from .model import Finding, Link, Root
from .move import wiki_name


def _git(root: Root, *args: str, config: Tuple[str, ...] = ()) -> Optional[bytes]:
    # --no-optional-locks keeps a read from taking the index lock (it can race a user's git).
    cmd = ["git", "--no-optional-locks"]
    for setting in config:
        cmd += ["-c", setting]
    try:
        done = subprocess.run([*cmd, "-C", str(root.path), *args], capture_output=True)
    except OSError:
        return None
    return done.stdout if done.returncode == 0 else None


def _git_paths(root: Root) -> Optional[Callable[[str], Optional[Path]]]:
    """A resolver from a path git prints (relative to the repo top level) to an absolute path
    under the root, or None for one outside it. None itself when there is no git work tree."""
    if shutil.which("git") is None:
        return None
    top = _git(root, "rev-parse", "--show-toplevel")
    if not top:
        return None
    top_path = Path(os.path.realpath(os.fsdecode(top).strip()))
    real_root = Path(os.path.realpath(root.path))

    def in_root(git_path: str) -> Optional[Path]:
        try:
            return root.path / (top_path / git_path).relative_to(real_root)
        except ValueError:
            return None

    return in_root


def _status_entries(root: Root) -> List[str]:
    status = _git(root, "status", "--porcelain=v1", "-z", config=("status.renames=true",))
    return [os.fsdecode(e) for e in status.split(b"\0")] if status else []


def git_renames(root: Root) -> Dict[Path, Path]:
    """Staged renames in the root's git work tree: absolute old path -> absolute new path."""
    in_root = _git_paths(root)
    entries = _status_entries(root)
    if in_root is None or not entries:
        return {}
    renames: Dict[Path, Path] = {}
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


def git_deleted(root: Root) -> Set[Path]:
    """Absolute paths under the root that git records as deleted on purpose: staged for
    deletion (not a rename source) or removed by a commit (renames don't count)."""
    in_root = _git_paths(root)
    if in_root is None:
        return set()
    deleted: Set[Path] = set()

    def add(git_path: str) -> None:
        path = in_root(git_path)
        if path is not None:
            deleted.add(path)

    entries = _status_entries(root)
    i = 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if len(entry) < 4:
            continue
        if entry[0] in "RC" or entry[1] in "RC":
            i += 1  # the original path follows; a rename source is not a deletion
        elif entry[0] == "D":
            add(entry[3:])
    log = _git(root, "log", "-M", "--diff-filter=D", "--name-only", "--format=", "-z")
    for name in (log or b"").split(b"\0"):
        if name:
            add(os.fsdecode(name))
    return deleted


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


def _renamed_target(
    root: Root, note: Path, link: Link,
    renames: Dict[Path, Path], reverse: Dict[Path, Path],
) -> Tuple[Optional[Path], Path]:
    """Steps 1 and 2 of the repair order that need no search: where the link points once the
    note's own move is accounted for, or where git renamed its target. Also returns the path
    the link names, for the by-name step."""
    old_note = reverse.get(note)  # where this note was before git moved it
    base = old_note or note
    if old_note is not None:
        found = resolve.md_target(root, old_note, link.target).path
        if found is not None:
            return found, base
    named = _named(root, base, link.target)
    moved = renames.get(named)
    if moved is not None and moved.is_file():
        return moved, named
    return None, named


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

    deleted: Optional[Set[Path]] = None  # read once, and only if a link gets to the by-name step

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
            message = "wikilink matches no file" if link.in_frontmatter else "broken link"
            if link.in_frontmatter:
                if old_root is not None:
                    new = _new_wikilink(root, old_root, renames, link)
            else:
                target, named = _renamed_target(root, note, link, renames, reverse)
                if target is None:
                    if deleted is None:
                        deleted = git_deleted(root)
                    if named in deleted:
                        message = "broken link (deleted in git)"
                    else:
                        target = _by_filename(root, named)
                if target is not None:
                    new = parse.replace_target(link, paths.encode(paths.relative(note, target)))
            if new is None or new == link.raw:
                findings.append(Finding("error", rel, link.line, f"{message}: {check._shown(link)}"))
            else:
                edits.append((link, new))
        if not edits:
            continue
        changes.extend(Change(rel, link.line, link.raw, new) for link, new in edits)
        if not dry_run:
            parse.write(note, convert._apply(text, edits), bom)
    return changes, findings
