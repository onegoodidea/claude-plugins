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


def _staged(root: Root) -> Tuple[List[Tuple[str, str]], Set[str]]:
    """From git status: staged renames as (old, new) repo paths, and the paths that are new
    to the index (staged as added, or a rename or copy destination)."""
    entries = _status_entries(root)
    renames: List[Tuple[str, str]] = []
    new: Set[str] = set()
    i = 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if len(entry) < 4:
            continue
        x, y, path = entry[0], entry[1], entry[3:]
        if x in "RC" or y in "RC":  # these carry the original path as the next entry
            old = entries[i] if i < len(entries) else ""
            i += 1
            if x == "R" and old:
                renames.append((old, path))
        if x in "ARC" or y == "A":
            new.add(path)
    return renames, new


def _committed(root: Root) -> Tuple[List[Tuple[str, str]], Set[str]]:
    """From one git log, oldest commit first: committed renames as (old, new) repo paths, and
    every path any commit touched."""
    log = _git(root, "log", "-M", "--name-status", "--format=", "-z", "--reverse",
               config=("diff.renames=true", "log.showSignature=false"))
    tokens = [os.fsdecode(t) for t in (log or b"").split(b"\0") if t]
    renames: List[Tuple[str, str]] = []
    touched: Set[str] = set()
    i = 0
    while i < len(tokens):
        status = tokens[i].lstrip("\n")
        i += 1
        if status[:1] in ("R", "C"):
            old, new = tokens[i:i + 2] if i + 1 < len(tokens) else ("", "")
            i += 2
            if old and new:
                touched.update((old, new))
                if status[0] == "R":
                    renames.append((old, new))
        elif i < len(tokens):
            touched.add(tokens[i])
            i += 1
    return renames, touched


def _chain(steps: List[Tuple[str, str]]) -> Dict[str, List[str]]:
    """Renames in the order they happened -> newest path: every path it was renamed from,
    most recent first. A -> B -> C gives {C: [B, A]}."""
    olds: Dict[str, List[str]] = {}  # path -> its earlier paths, oldest first
    for old, new in steps:
        olds.setdefault(new, []).extend([*olds.pop(old, []), old])
    return {new: [p for p in reversed(was) if p != new] for new, was in olds.items()}


class GitView:
    """What git knows about the root's paths. Staged renames are read up front (one git
    status); committed renames and the paths git ever tracked come from one git log, read
    only when a link needs them (load_history). Outside a git work tree, or without git,
    there are no renames and no path was ever tracked."""

    def __init__(self, root: Root):
        self._root = root
        self._in_root = _git_paths(root)
        staged, self._new = _staged(root) if self._in_root else ([], set())
        self._staged = staged
        self.complete = self._in_root is None  # nothing more to read from git
        self._tracked: Set[str] = set()
        self._held: Set[str] = set()
        self._set_renames(staged)

    def _set_renames(self, steps: List[Tuple[str, str]]) -> None:
        self.renames: Dict[Path, Path] = {}  # absolute old path -> absolute newest path
        self.olds: Dict[Path, List[Path]] = {}  # absolute newest path -> old paths, recent first
        self._folded: Dict[str, Path] = {}
        if self._in_root is None:
            return
        for new, was in _chain(steps).items():
            new_abs = self._in_root(new)
            if new_abs is None:
                continue
            olds = [p for p in map(self._in_root, was) if p is not None]
            if olds:
                self.olds[new_abs] = olds
            for old in olds:
                self.renames[old] = new_abs
        self._folded = {paths.key(old): new for old, new in self.renames.items()}

    def renamed(self, path: Path) -> Optional[Path]:
        return self._folded.get(paths.key(path))

    def load_history(self) -> bool:
        """Read committed renames and tracked paths, once. True only on the call that read them."""
        if self.complete or self._in_root is None:
            return False
        self.complete = True
        committed, touched = _committed(self._root)
        index = _git(self._root, "ls-files", "-z", "--full-name") or b""
        in_index = {os.fsdecode(p) for p in index.split(b"\0") if p}
        self._tracked = {paths.key(p) for p in map(self._in_root, touched | in_index) if p is not None}
        self._held = {paths.key(p) for p in map(self._in_root, in_index - self._new) if p is not None}
        self._set_renames(committed + self._staged)
        return True

    def was_tracked(self, path: Path) -> bool:
        """Git ever had this path: in HEAD or the index, or touched by a commit."""
        self.load_history()
        return paths.key(path) in self._tracked

    def has(self, path: Path) -> bool:
        """Git has a file at this path already (in HEAD and the index), so it isn't where a
        moved file went."""
        self.load_history()
        return paths.key(path) in self._held


def git_renames(root: Root) -> Dict[Path, Path]:
    """Staged renames in the root's git work tree: absolute old path -> absolute new path."""
    return GitView(root).renames


def is_broken(root: Root, note: Path, link: Link) -> bool:
    """A body Markdown link to a file that isn't there, or is there only with different case
    (a case-only rename), or a frontmatter wikilink that matches no file. relink, its leftover
    report, and the Bash hook share this."""
    if link.kind in ("md", "image", "refdef"):
        if link.target == "":
            return False
        found = resolve.md_target(root, note, link.target)
        return found.path is None or not found.exact_case
    if link.kind in ("wiki", "embed") and link.in_frontmatter:
        return link.target != "" and not resolve.wikilink(root, link.target)
    return False


def _readable_links(note: Path) -> Optional[Tuple[str, bool, List[Link]]]:
    try:
        text, bom = parse.read(note)
    except (UnicodeDecodeError, OSError):
        return None
    return text, bom, parse.find_links(text)


def count_broken(root: Root, counts: Optional[Callable[[Path, Link], bool]] = None) -> int:
    """Broken links in the root; with counts, only the links it accepts."""
    total = 0
    for note in root.notes:
        read = _readable_links(note)
        if read:
            total += sum((counts is None or counts(note, link)) and is_broken(root, note, link)
                         for link in read[2])
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


def _by_filename(
    root: Root, named: Path, allowed: Callable[[Path], bool] = lambda path: True,
) -> Tuple[Optional[Path], bool]:
    """Of the allowed files with that name, the one sharing the most trailing path segments
    (None on a tie), and whether any file was allowed."""
    if not named.name:
        return None, False
    wanted = paths.fold(named.name)
    tail = _segments(root, named)
    scored = []
    for cand in dict.fromkeys(root.by_name.get(wanted, [])):
        if paths.fold(cand.name) == wanted and cand.is_file() and allowed(cand):
            scored.append((_shared_tail(_segments(root, cand), tail), cand))
    if not scored:
        return None, False
    best = max(s for s, _ in scored)
    winners = [c for s, c in scored if s == best]
    return (winners[0] if len(winners) == 1 else None), True


def _renamed_target(
    root: Root, note: Path, link: Link, git: GitView,
) -> Tuple[Optional[Path], Path]:
    """Step 1 of the repair order: where the link points once the note's own recorded move is
    accounted for, or where git renamed its target. Also returns the path the link names,
    for the by-name step."""
    olds = git.olds.get(note, [])  # where this note was before git moved it, most recent first
    for old_note in olds:
        found = resolve.md_target(root, old_note, link.target).path
        if found is not None:
            return found, old_note
    named = _named(root, olds[0] if olds else note, link.target)
    moved = git.renamed(named)
    if moved is not None and moved.is_file():
        return moved, named
    return None, named


def _repaired_target(root: Root, note: Path, link: Link, git: GitView) -> Tuple[Optional[Path], bool]:
    """Where a broken body link should point (None to leave it), and whether the path it
    names is a file deleted in git."""
    found = resolve.md_target(root, note, link.target).path
    if found is not None:  # there, but only with different case: the spelling on disk
        return found, False
    target, named = _renamed_target(root, note, link, git)
    if target is None and git.load_history():  # committed renames too, read once
        target, named = _renamed_target(root, note, link, git)
    if target is not None:
        return target, False
    if not git.was_tracked(named):
        return _by_filename(root, named)[0], False
    # A move leaves the file at a path git hasn't recorded; a deletion doesn't.
    target, any_new = _by_filename(root, named, lambda path: not git.has(path))
    return target, not any_new


def _old_root(root: Root, git: GitView) -> Optional[Root]:
    """The root's files with each renamed one back at its earlier paths, for frontmatter
    wikilinks written before the rename."""
    if not git.renames:
        return None
    kept = [p for p in root.notes + root.files if p not in git.olds]
    return rootmod.index(root.path, root.exclude, list(dict.fromkeys(kept + list(git.renames))))


def _new_wikilink(root: Root, old_root: Optional[Root], git: GitView, link: Link) -> Optional[str]:
    if old_root is None:
        return None
    hits = resolve.wikilink(old_root, link.target)
    if len(hits) != 1:
        return None
    new = git.renames.get(hits[0])
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
    git = GitView(root)
    old_roots: Dict[bool, Optional[Root]] = {}  # keyed by whether git history was read

    def old_root() -> Optional[Root]:
        if git.complete not in old_roots:
            old_roots[git.complete] = _old_root(root, git)
        return old_roots[git.complete]

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
                new = _new_wikilink(root, old_root(), git, link)
                if new is None and git.load_history():  # committed renames too, read once
                    new = _new_wikilink(root, old_root(), git, link)
            else:
                target, deleted = _repaired_target(root, note, link, git)
                if deleted:
                    message = "broken link (deleted in git)"
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
