from __future__ import annotations

from pathlib import Path
from typing import List

from . import parse, paths, resolve
from . import root as rootmod
from .model import Finding, Link, Root


def _is_note(path: Path) -> bool:
    return path.name.lower().endswith(".md")


def _shown(link: Link) -> str:
    return link.raw if len(link.raw) <= 60 else link.raw[:57] + "..."


def _candidates(root: Root, hits: List[Path]) -> str:
    names = [rootmod.rel(root, p) for p in hits[:3]]
    more = ", ..." if len(hits) > 3 else ""
    return ", ".join(names) + more


def _check_markdown_link(root: Root, note: Path, rel: str, link: Link) -> List[Finding]:
    target = resolve.md_target(root, note, link.target)
    shown = _shown(link)
    if target.path is None:
        return [Finding("error", rel, link.line, f"broken link: {shown}")]
    out: List[Finding] = []
    if not target.exact_case:
        out.append(Finding("error", rel, link.line,
                           f"case differs from the file on disk: {shown}"))
    if not target.note_relative:
        out.append(Finding("error", rel, link.line,
                           f"not relative to this note; run convert: {shown}"))
    if target.outside_root:
        out.append(Finding("warning", rel, link.line,
                           f"points outside the root: {shown}"))
    if link.anchor and not link.block_ref and _is_note(target.path):
        wanted = paths.decode(link.anchor).casefold()
        try:
            text = parse.read(target.path)[0]
        except (UnicodeDecodeError, OSError):
            return out
        if wanted not in {h.casefold() for h in parse.headings(text)}:
            out.append(Finding("warning", rel, link.line,
                               f"no heading matches the anchor: {shown}"))
    return out


def _check_wikilink(root: Root, note: Path, rel: str, link: Link) -> List[Finding]:
    shown = _shown(link)
    if link.in_frontmatter:
        hits = [note] if link.target == "" else resolve.wikilink(root, link.target)
        if len(hits) == 1:
            return []
        if not hits:
            return [Finding("error", rel, link.line, f"wikilink matches no file: {shown}")]
        return [Finding("error", rel, link.line,
                        f"wikilink is ambiguous ({_candidates(root, hits)}): {shown}")]

    if link.block_ref:
        return [Finding("warning", rel, link.line,
                        f"block reference has no Markdown equivalent: {shown}")]
    hits = [note] if link.target == "" else resolve.wikilink(root, link.target)
    if len(hits) != 1:
        if not hits:
            return [Finding("warning", rel, link.line, f"wikilink matches no file: {shown}")]
        return [Finding("warning", rel, link.line,
                        f"wikilink is ambiguous ({_candidates(root, hits)}): {shown}")]
    if link.kind == "embed" and _is_note(hits[0]):
        return [Finding("warning", rel, link.line,
                        f"note transclusion has no Markdown equivalent: {shown}")]
    return [Finding("error", rel, link.line, f"use a Markdown link: {shown}")]


def check_file(root: Root, note: Path) -> List[Finding]:
    rel = rootmod.rel(root, note)
    try:
        text, _ = parse.read(note)
    except UnicodeDecodeError:
        return [Finding("warning", rel, 1, "not valid UTF-8; skipped")]
    findings: List[Finding] = []
    for link in parse.find_links(text):
        if link.kind in ("wiki", "embed"):
            findings.extend(_check_wikilink(root, note, rel, link))
        else:
            findings.extend(_check_markdown_link(root, note, rel, link))
    return findings


def check_root(root: Root) -> List[Finding]:
    findings: List[Finding] = []
    for note in root.notes:
        findings.extend(check_file(root, note))
    return findings
