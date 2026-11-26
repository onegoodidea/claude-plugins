from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import check, parse, paths, resolve
from . import root as rootmod
from .model import Finding, Link, Root

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".avif", ".bmp"}
_SIZE = re.compile(r"\d+(?:x\d+)?")  # an embed alias that sets a size: 300 or 300x200


@dataclass(frozen=True)
class Change:
    file: str  # POSIX path relative to the root
    line: int
    old: str  # the link as written
    new: str  # the link convert writes


def _escape(label: str) -> str:
    return label.replace("]", "\\]")


def _encoded(note: Path, target: Path, anchor: Optional[str]) -> str:
    enc = paths.encode(paths.relative(note, target))
    if anchor is not None:
        enc += "#" + paths.encode_anchor(paths.decode(anchor))
    return enc


def _wiki_replacement(
    root: Root, note: Path, rel: str, link: Link
) -> Tuple[Optional[str], Optional[Finding]]:
    """The Markdown text for a wiki or embed link (None when it stays), and any warning."""
    path, warning = check.classify_body_wikilink(root, note, rel, link)
    if path is None:
        return None, warning
    if link.target == "":
        enc = "#" + paths.encode_anchor(paths.decode(link.anchor or ""))
    else:
        enc = _encoded(note, path, link.anchor)
    if link.kind == "embed":
        alias, warning = link.alias, None
        if alias is not None and _SIZE.fullmatch(alias.strip()):
            alias = None
            warning = Finding("warning", rel, link.line,
                              f"image size dropped: {check._shown(link)}")
        if os.path.splitext(path.name)[1].lower() in _IMAGE_EXTS:
            return f"![{_escape(alias or '')}]({enc})", warning
        return f"[{_escape(alias or path.name)}]({enc})", warning
    label = link.alias if link.alias is not None else (link.target or link.anchor or "")
    return f"[{_escape(label)}]({enc})", None


def _repair_replacement(root: Root, note: Path, link: Link) -> Optional[str]:
    """link.raw with its target made note-relative, or None to leave it alone."""
    found = resolve.md_target(root, note, link.target)
    if found.path is None or found.note_relative:
        return None
    return parse.replace_target(link, paths.encode(paths.relative(note, found.path)))


def _edits(root: Root, note: Path, text: str) -> Tuple[List[Tuple[Link, str]], List[Finding]]:
    """Each link convert rewrites with its new text, and the warnings for links it leaves."""
    rel = rootmod.rel(root, note)
    edits: List[Tuple[Link, str]] = []
    warnings: List[Finding] = []
    for link in parse.find_links(text):
        if link.kind in ("wiki", "embed"):
            if link.in_frontmatter:
                continue
            new, warning = _wiki_replacement(root, note, rel, link)
            if warning:
                warnings.append(warning)
        else:
            new = _repair_replacement(root, note, link)
        if new is not None and new != link.raw:
            edits.append((link, new))
    return edits, warnings


def _apply(text: str, edits: List[Tuple[Link, str]]) -> str:
    for link, new in reversed(edits):
        text = text[:link.start] + new + text[link.end:]
    return text


def convert_text(root: Root, note: Path, text: str) -> Tuple[str, int, List[Finding]]:
    edits, warnings = _edits(root, note, text)
    return _apply(text, edits), len(edits), warnings


def convert_all(
    root: Root, dry_run: bool
) -> Tuple[List[Change], List[Finding], Dict[Path, str]]:
    """Every link change, the warnings for links left alone, and each changed note's new text."""
    changes: List[Change] = []
    findings: List[Finding] = []
    texts: Dict[Path, str] = {}
    for note in root.notes:
        rel = rootmod.rel(root, note)
        try:
            text, bom = parse.read(note)
        except UnicodeDecodeError:
            findings.append(Finding("warning", rel, 1, "not valid UTF-8; skipped"))
            continue
        edits, warnings = _edits(root, note, text)
        findings.extend(warnings)
        if not edits:
            continue
        changes.extend(Change(rel, link.line, link.raw, new) for link, new in edits)
        texts[note] = _apply(text, edits)
        if not dry_run:
            parse.write(note, texts[note], bom)
    return changes, findings, texts


def convert_root(root: Root, dry_run: bool) -> Tuple[List[str], List[Finding]]:
    changes, findings, _ = convert_all(root, dry_run)
    return list(dict.fromkeys(c.file for c in changes)), findings
