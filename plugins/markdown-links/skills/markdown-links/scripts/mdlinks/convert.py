from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional, Tuple

from . import check, parse, paths, resolve
from . import root as rootmod
from .model import Finding, Link, Root

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".avif", ".bmp"}


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
    """The Markdown text for a wiki or embed link, or a warning for why it stays."""
    path, warning = check.classify_body_wikilink(root, note, rel, link)
    if path is None:
        return None, warning
    if link.target == "":
        enc = "#" + paths.encode_anchor(paths.decode(link.anchor or ""))
    else:
        enc = _encoded(note, path, link.anchor)
    if link.kind == "embed":
        if os.path.splitext(path.name)[1].lower() in _IMAGE_EXTS:
            return f"![]({enc})", None
        return f"[{_escape(path.name)}]({enc})", None
    label = link.alias if link.alias is not None else (link.target or link.anchor or "")
    return f"[{_escape(label)}]({enc})", None


def _target_offset(link: Link) -> int:
    """Offset of the written target inside link.raw."""
    if link.kind == "refdef":
        i = link.raw.index("]:") + 2
        while link.raw[i] in " \t":
            i += 1
        return i
    return (1 if link.kind == "image" else 0) + 1 + len(link.text or "") + 2


def _repair_replacement(root: Root, note: Path, link: Link) -> Optional[str]:
    """link.raw with its target made note-relative, or None to leave it alone."""
    found = resolve.md_target(root, note, link.target)
    if found.path is None or found.note_relative:
        return None
    new_path = paths.encode(paths.relative(note, found.path))
    if link.angle:
        new_path = paths.decode(new_path)
    anchor = "" if link.anchor is None else "#" + link.anchor
    written = ("<" + link.target + anchor + ">") if link.angle else link.target + anchor
    start = _target_offset(link)
    if link.raw[start:start + len(written)] != written:
        return None
    new = ("<" + new_path + anchor + ">") if link.angle else new_path + anchor
    return link.raw[:start] + new + link.raw[start + len(written):]


def convert_text(root: Root, note: Path, text: str) -> Tuple[str, int, List[Finding]]:
    rel = rootmod.rel(root, note)
    edits: List[Tuple[int, int, str]] = []
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
            edits.append((link.start, link.end, new))
    for start, end, new in reversed(edits):
        text = text[:start] + new + text[end:]
    return text, len(edits), warnings


def convert_all(root: Root, dry_run: bool) -> Tuple[List[str], List[Finding], int]:
    changed: List[str] = []
    findings: List[Finding] = []
    total = 0
    for note in root.notes:
        rel = rootmod.rel(root, note)
        try:
            text, bom = parse.read(note)
        except UnicodeDecodeError:
            findings.append(Finding("warning", rel, 1, "not valid UTF-8; skipped"))
            continue
        new, count, warnings = convert_text(root, note, text)
        findings.extend(warnings)
        if count:
            changed.append(rel)
            total += count
            if not dry_run:
                parse.write(note, new, bom)
    return changed, findings, total


def convert_root(root: Root, dry_run: bool) -> Tuple[List[str], List[Finding]]:
    changed, findings, _ = convert_all(root, dry_run)
    return changed, findings
