from __future__ import annotations

import os
import shutil
import subprocess
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import parse, paths, resolve
from . import root as rootmod
from .model import Finding, Link, Root


class MoveError(Exception):
    pass


class ApplyError(MoveError):
    """A failure after the disk began to change; the message says what completed."""


@dataclass
class MovePlan:
    moves: List[Tuple[Path, Path]]  # every file in the moved set, old path -> new
    edits: Dict[Path, str]  # new text, keyed by each file's path after the move
    boms: Dict[Path, bool]
    src: Path  # the file or folder renamed on disk
    dst: Path
    warnings: List[Finding] = field(default_factory=list)


def _shown(root: Root, path: Path) -> str:
    under = resolve._under(root, path)
    return str(path) if under is None else under


def _hidden_or_excluded(root: Root, path: Path) -> bool:
    parts = path.relative_to(root.path).parts
    return any(p.startswith(".") for p in parts) or resolve._excluded(root, path)


def _exact_case(root: Root, path: Path) -> bool:
    current = root.path
    for part in path.relative_to(root.path).parts:
        if part not in os.listdir(current):
            return False
        current = current / part
    return True


def _disk_case_folders(root: Root, dst: Path) -> Path:
    """dst with each existing folder spelled as on disk, for case-insensitive disks."""
    if resolve._under(root, dst) in (None, "."):
        return dst
    current = root.path
    parts = dst.relative_to(root.path).parts
    for part in parts[:-1]:
        if current.is_dir() and (current / part).is_dir():
            entries = os.listdir(current)
            if part not in entries:
                part = next(e for e in entries if os.path.samefile(current / e, current / part))
        current = current / part
    return current / parts[-1]


def _case_only(src: Path, dst: Path) -> bool:
    """dst names src itself, spelled with different case (or Unicode form)."""
    def fold(p: Path) -> str:
        return unicodedata.normalize("NFC", str(p)).casefold()

    return (
        src != dst
        and fold(src) == fold(dst)
        and os.path.lexists(dst)
        and os.path.samefile(src, dst)
    )


def _check_source(root: Root, src: Path) -> str:
    src_rel = resolve._under(root, src)
    if src_rel is None:
        raise MoveError(f"{src} is outside the root {root.path}")
    if src_rel == ".":
        raise MoveError("cannot move the root itself")
    if not os.path.lexists(src):
        raise MoveError(f"no such file or folder: {src_rel}")
    if not _exact_case(root, src):
        raise MoveError(f"case differs from the file on disk: {src_rel}")
    if _hidden_or_excluded(root, src):
        raise MoveError(f"{src_rel} is hidden or in an excluded folder")
    if src.is_dir():
        inner = [e for e in root.exclude if e.startswith(src_rel + "/")]
        if inner:
            raise MoveError(f"{src_rel} holds the excluded folder {inner[0]}")
    return src_rel


def _check_destination(root: Root, src: Path, dst: Path) -> None:
    dst_rel = resolve._under(root, dst)
    if dst_rel is None or dst_rel == ".":
        raise MoveError(f"{dst} is outside the root {root.path}")
    if dst == src:
        raise MoveError(f"{dst_rel} is the source itself")
    if os.path.lexists(dst) and not _case_only(src, dst):
        raise MoveError(f"{dst_rel} already exists")
    for parent in dst.parents:
        if not os.path.lexists(parent):
            continue
        if not parent.is_dir():
            raise MoveError(f"{_shown(root, parent)} is not a folder")
        if os.path.samefile(parent, src):
            raise MoveError(f"cannot move {_shown(root, src)} into itself")
    if src.is_file() and resolve.is_note(src) != resolve.is_note(dst):
        raise MoveError(f"{dst_rel} would change whether {_shown(root, src)} is a note (.md)")


def _moved_files(src: Path, dst: Path) -> Dict[Path, Path]:
    """Every file that moves, hidden ones included, old path -> new."""
    if not src.is_dir():
        return {src: dst}
    moved = {}
    for dirpath, _, filenames in os.walk(src):
        for name in filenames:
            old = Path(dirpath) / name
            moved[old] = dst / old.relative_to(src)
    return moved


def _wiki_name(root: Root, path: Path, qualified: bool) -> str:
    """How a wikilink names path: root-relative when qualified; notes drop .md."""
    name = rootmod.rel(root, path) if qualified else path.name
    return name[:-3] if resolve.is_note(path) else name


def _wiki_edit(root: Root, new_root: Root, moved: Dict[Path, Path], link: Link) -> Optional[str]:
    if link.target == "":
        return None
    hits = resolve.wikilink(root, link.target)
    if len(hits) != 1:
        return None
    old = hits[0]
    new = moved.get(old, old)
    qualified = "/" in link.target.strip("/")
    name = link.target
    if new != old and (
        qualified or _wiki_name(root, old, False) != _wiki_name(new_root, new, False)
    ):
        name = _wiki_name(new_root, new, qualified)
    if resolve.wikilink(new_root, name) != [new]:
        name = _wiki_name(new_root, new, True)
    return None if name == link.target else parse.replace_target(link, name)


def _md_edit(
    root: Root, moved: Dict[Path, Path], note: Path, new_note: Path, link: Link
) -> Optional[str]:
    if link.target == "":
        return None
    found = resolve.md_target(root, note, link.target)
    if found.path is None:
        return None
    new_target = moved.get(found.path, found.path)
    if new_target == found.path and new_note == note:
        return None
    return parse.replace_target(link, paths.encode(paths.relative(new_note, new_target)))


def _rewrite(
    root: Root, new_root: Root, moved: Dict[Path, Path], note: Path, text: str
) -> str:
    new_note = moved.get(note, note)
    edits: List[Tuple[int, int, str]] = []
    for link in parse.find_links(text):
        if link.kind in ("wiki", "embed"):
            new = _wiki_edit(root, new_root, moved, link)
        else:
            new = _md_edit(root, moved, note, new_note, link)
        if new is not None and new != link.raw:
            edits.append((link.start, link.end, new))
    for start, end, new in reversed(edits):
        text = text[:start] + new + text[end:]
    return text


def plan_move(root: Root, src: Path, dst: Path) -> MovePlan:
    """Every move and edit for moving src to dst. Reads only; raises MoveError."""
    src = Path(os.path.abspath(src))
    dst = Path(os.path.abspath(dst))
    _check_source(root, src)
    if src.is_file() and dst.is_dir():
        dst = dst / src.name
    dst = _disk_case_folders(root, dst)
    _check_destination(root, src, dst)

    moved = _moved_files(src, dst)
    indexed = root.notes + root.files
    for old in indexed:
        if old in moved and _hidden_or_excluded(root, moved[old]):
            raise MoveError(f"{_shown(root, moved[old])} would be hidden or in an excluded folder")
    new_root = rootmod.index(root.path, root.exclude, [moved.get(p, p) for p in indexed])

    edits: Dict[Path, str] = {}
    boms: Dict[Path, bool] = {}
    warnings: List[Finding] = []
    for note in root.notes:
        new_note = moved.get(note, note)
        try:
            text, bom = parse.read(note)
        except UnicodeDecodeError:
            warnings.append(Finding("warning", rootmod.rel(root, new_note), 1,
                                    "not valid UTF-8; links not updated"))
            continue
        new_text = _rewrite(root, new_root, moved, note, text)
        if new_text != text:
            edits[new_note] = new_text
            boms[new_note] = bom
    return MovePlan(sorted(moved.items()), edits, boms, src, dst, warnings)


def _in_git(root: Root, src: Path) -> bool:
    """True when src is tracked in a git work tree, so git mv can move it."""
    if shutil.which("git") is None:
        return False

    def git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(root.path), *args],
                              capture_output=True, text=True)

    inside = git("rev-parse", "--is-inside-work-tree")
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return False
    return git("ls-files", "--error-unmatch", "--", str(src)).returncode == 0


def _temp_name(path: Path) -> Path:
    n = 0
    while True:
        tmp = path.with_name(f".{path.name}.markdown-links-{os.getpid()}-{n}")
        if not os.path.lexists(tmp):
            return tmp
        n += 1


def apply(root: Root, plan: MovePlan) -> List[str]:
    """Make the moves, then write the edits. Returns the root-relative paths edited.

    Raises MoveError, changing nothing, when the source is gone or the destination
    now exists; raises ApplyError, naming what completed, when a step fails after that.
    """
    src, dst = plan.src, plan.dst
    case_only = _case_only(src, dst)
    if not os.path.lexists(src):
        raise MoveError(f"no such file or folder: {_shown(root, src)}")
    if os.path.lexists(dst) and not case_only:
        raise MoveError(f"{_shown(root, dst)} already exists")

    use_git = _in_git(root, src)
    done: List[str] = []

    def fail(what: str, error: str) -> ApplyError:
        return ApplyError(f"{what} failed ({error}); completed: {', '.join(done) or 'nothing'}")

    def rename(a: Path, b: Path) -> None:
        step = f"{_shown(root, a)} -> {_shown(root, b)}"
        try:
            if use_git:
                subprocess.run(["git", "-C", str(root.path), "mv", "--", str(a), str(b)],
                               check=True, capture_output=True, text=True)
            else:
                os.replace(a, b)
        except subprocess.CalledProcessError as e:
            raise fail(f"git mv {step}", e.stderr.strip() or str(e))
        except OSError as e:
            raise fail(f"move {step}", str(e))
        done.append(f"moved {step}")

    if case_only:
        tmp = _temp_name(src)
        rename(src, tmp)
        rename(tmp, dst)
    else:
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise fail(f"creating {_shown(root, dst.parent)}", str(e))
        rename(src, dst)

    changed: List[str] = []
    for path in sorted(plan.edits):
        shown = rootmod.rel(root, path)
        try:
            parse.write(path, plan.edits[path], plan.boms[path])
        except OSError as e:
            raise fail(f"writing {shown}", str(e))
        done.append(f"updated {shown}")
        changed.append(shown)
    return changed
