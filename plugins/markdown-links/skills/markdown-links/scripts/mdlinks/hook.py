from __future__ import annotations

import fnmatch
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


GLOB = re.compile(r"[*?[]")
SHELL_PUNCTUATION = set("();<>|&")


def _command_paths(command: str, cwd: str) -> Tuple[List[str], List[str]]:
    """The paths the command's words name, read the way the shell would: ~ and $VAR expanded,
    and resolved against cwd as cd and pushd change it. Command names and redirections aren't
    paths. Returns the paths and the folders cd moved to."""
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        tokens = command.split()
    base = os.path.abspath(cwd or ".")
    found: List[str] = []
    folders: List[str] = []
    at_command = True  # the next word names a program
    changing_dir = False  # the next word is cd's folder
    for token in tokens:
        if token and set(token) <= SHELL_PUNCTUATION:
            if set(token) & set(";&|("):
                at_command, changing_dir = True, False
            continue
        word = os.path.expandvars(os.path.expanduser(token))
        if not word:
            continue
        if at_command:
            at_command = False
            changing_dir = word in ("cd", "pushd")
            continue
        path = os.path.normpath(os.path.join(base, word))
        if changing_dir:
            if not word.startswith("-"):
                base, changing_dir = path, False
                folders.append(path)
            continue
        found.append(path)
    return found, folders


def _bash_roots(words: List[str], cwd: str) -> List[Path]:
    folders = [cwd] if cwd else []
    for path in words:
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


class _Top:
    """A command path, normalized and folded; a word with glob characters matches as a
    pattern, one path segment at a time, as the shell would."""

    def __init__(self, path: str):
        self.key = paths.key(path).rstrip("/")
        self.segments = self.key.split("/")
        self.glob = GLOB.search(self.key) is not None

    def covers(self, key: str) -> bool:
        """key is at or under this path (or under a folder this pattern matches)."""
        if not self.glob:
            return key == self.key or key.startswith(self.key + "/")
        segments = key.split("/")
        return len(segments) >= len(self.segments) and all(
            _segment_matches(s, p) for s, p in zip(segments, self.segments))


def _segment_matches(segment: str, pattern: str) -> bool:
    return segment == pattern or (GLOB.search(pattern) is not None
                                  and fnmatch.fnmatchcase(segment, pattern))


def _wikilink_within(root_segments: List[str], target: str, tops: List[_Top]) -> bool:
    """A wikilink names a file by its trailing path, so it is under a command path that ends
    with the start of the target: People/ or Jane Doe.md for [[People/Jane Doe]]."""
    segments = paths.fold(target.strip().strip("/")).split("/")
    forms = [segments[:-1] + [segments[-1] + ".md"]] if not segments[-1].endswith(".md") else []
    if os.path.splitext(segments[-1])[1]:
        forms.append(segments)
    for top in tops:
        head, tail = top.segments[:len(root_segments)], top.segments[len(root_segments):]
        if len(head) < len(root_segments) or not all(
                _segment_matches(s, p) for s, p in zip(root_segments, head)):
            continue
        for form in forms:
            for k in range(1, min(len(tail), len(form)) + 1):
                if all(_segment_matches(f, p) for f, p in zip(form[:k], tail[-k:])):
                    return True
    return False


def _caused_by(root: Root, command_paths: List[str]) -> Callable[[Path, Link], bool]:
    """Whether a link could have been broken by a command naming these paths: the path it
    names, or the note that holds it, is at or under one of them. A path that is the root
    itself or above it is ignored, so cd <root> or find . doesn't count every link."""
    root_key = paths.key(root.path).rstrip("/")
    tops = [top for top in map(_Top, command_paths) if not top.covers(root_key)]
    root_segments = root_key.split("/")
    holder: Dict[Path, bool] = {}

    def counts(note: Path, link: Link) -> bool:
        if not tops:
            return False
        if note not in holder:
            holder[note] = any(top.covers(paths.key(note)) for top in tops)
        if holder[note]:
            return True
        if link.kind in ("wiki", "embed"):
            return _wikilink_within(root_segments, link.target, tops)
        named = paths.key(relink._named(root, note, link.target))
        return any(top.covers(named) for top in tops)

    return counts


def _run_bash(payload: dict) -> Tuple[int, str]:
    command = payload["tool_input"]["command"]
    if not isinstance(command, str) or not MOVE_OR_REMOVE.search(command) or "markdown-links.py" in command:
        return 0, ""
    cwd = payload.get("cwd")
    cwd = cwd if isinstance(cwd, str) else ""
    command_paths, folders = _command_paths(command, cwd)
    lines = []
    for root_path in _bash_roots(folders + command_paths, cwd):
        try:
            root = rootmod.load(root_path)
            broken = relink.count_broken(root, _caused_by(root, command_paths))
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
