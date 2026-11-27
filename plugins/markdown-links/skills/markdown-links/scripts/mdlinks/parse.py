from __future__ import annotations

import bisect
import re
from pathlib import Path
from typing import List, Optional, Tuple

from . import paths
from .model import Link

_BOM = b"\xef\xbb\xbf"

_FRONTMATTER = re.compile(r"\A---[ \t]*\r?\n(?:.*?\r?\n)?---[ \t]*(?=\r?\n|\Z)", re.DOTALL)
# Any indent (fences sit inside list items) after any blockquote markers. A backtick
# fence's info string has no backtick, so ```js``` on one line is inline code.
_FENCE_OPEN = re.compile(r"^[ \t]*(?:>[ \t]*)*(`{3,}(?!.*`)|~{3,})")
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_INLINE_CODE = re.compile(r"(?<!`)(`+)(?!`)((?:(?!\r?\n[ \t]*\r?\n).)+?)(?<!`)\1(?!`)", re.DOTALL)

_WIKI = re.compile(r"(!?)\[\[([^\[\]\n]+?)\]\]")
_MD = re.compile(
    r"(!?)\[((?:[^\[\]\n]|\[[^\]\n]*\])*)\]"
    r"\((<[^>\n]*>|[^()\s]*(?:\([^()\s]*\)[^()\s]*)*)"
    r"(?:[ \t]+(?:\"[^\"\n]*\"|'[^'\n]*'))?[ \t]*\)"
)
# The destination may be followed only by an optional title, then the end of the line.
_REFDEF = re.compile(
    r"^ {0,3}\[([^\]\n]+)\]:[ \t]*(<[^>\n]*>|\S+)"
    r"(?=(?:[ \t]+(?:\"[^\"\n]*\"|'[^'\n]*'|\([^()\n]*\)))?[ \t]*\r?$)",
    re.MULTILINE,
)
_HEADING = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*\r?$", re.MULTILINE)
_ALIAS_SPLIT = re.compile(r"\\?\|")
_EXTERNAL = re.compile(r"^(?:[a-zA-Z][a-zA-Z0-9+.-]*:|//)")

Span = Tuple[int, int]


def frontmatter_span(text: str) -> Optional[Span]:
    base = 1 if text.startswith("\ufeff") else 0
    m = _FRONTMATTER.match(text[base:])
    return (base, base + m.end()) if m else None


def _fence_spans(text: str) -> List[Span]:
    spans: List[Span] = []
    open_start = -1
    ch = ""
    length = 0
    pos = 0
    for line in text.splitlines(keepends=True):
        start, end = pos, pos + len(line)
        pos = end
        body = line.rstrip("\r\n")
        if open_start < 0:
            m = _FENCE_OPEN.match(body)
            if m:
                open_start, ch, length = start, m.group(1)[0], len(m.group(1))
        else:
            stripped = re.sub(r"^[ \t]*(?:>[ \t]*)*", "", body)
            m = re.match(r"([`~]{3,})[ \t]*$", stripped)
            if m and m.group(1)[0] == ch and len(m.group(1)) >= length:
                spans.append((open_start, end))
                open_start = -1
    if open_start >= 0:
        spans.append((open_start, len(text)))
    return spans


def _inside(pos: int, spans: List[Span]) -> bool:
    return any(s <= pos < e for s, e in spans)


def _mask(text: str, spans: List[Span]) -> str:
    """Blank out spans (keeping newlines) so later scans cannot pair across them."""
    chars = list(text)
    for s, e in spans:
        for i in range(s, e):
            if chars[i] not in "\r\n":
                chars[i] = " "
    return "".join(chars)


def _skip_spans(text: str, fm: Optional[Span]) -> List[Span]:
    """Fenced code, HTML comments, and inline code outside the frontmatter."""
    spans = _fence_spans(text)
    if fm:
        spans = [sp for sp in spans if sp[0] >= fm[1]]
    block = list(spans)
    for m in _COMMENT.finditer(text):
        if not _inside(m.start(), block) and not (fm and m.start() < fm[1]):
            block.append((m.start(), m.end()))
    masked = _mask(text, block + ([fm] if fm else []))
    inline = [(m.start(), m.end()) for m in _INLINE_CODE.finditer(masked)]
    return sorted(block + inline)


def _split_anchor(path: str) -> Tuple[str, Optional[str]]:
    if "#" in path:
        target, anchor = path.split("#", 1)
        return target, anchor
    return path, None


def find_links(text: str) -> List[Link]:
    fm = frontmatter_span(text)
    skips = _skip_spans(text, fm)
    newlines = [i for i, c in enumerate(text) if c == "\n"]

    def line_of(pos: int) -> int:
        return bisect.bisect_left(newlines, pos) + 1

    found: List[Link] = []

    def add(kind, m, target, anchor, alias, label, angle, in_fm):
        if _EXTERNAL.match(target):
            return
        found.append(
            Link(kind, m.start(), m.end(), line_of(m.start()), m.group(0),
                 target, anchor, alias, label, in_fm, angle)
        )

    for m in _WIKI.finditer(text):
        in_fm = bool(fm and fm[0] <= m.start() < fm[1])
        if not in_fm and _inside(m.start(), skips):
            continue
        parts = _ALIAS_SPLIT.split(m.group(2), maxsplit=1)
        alias = parts[1] if len(parts) > 1 else None
        target, anchor = _split_anchor(parts[0].strip())
        add("embed" if m.group(1) else "wiki", m, target, anchor, alias, None, False, in_fm)

    def in_body(pos: int) -> bool:
        return not (fm and fm[0] <= pos < fm[1]) and not _inside(pos, skips)

    for m in _MD.finditer(text):
        if not in_body(m.start()):
            continue
        raw_target = m.group(3)
        angle = raw_target.startswith("<")
        path = raw_target[1:-1] if angle else raw_target
        target, anchor = _split_anchor(path)
        if target == "" and anchor is None:
            continue
        add("image" if m.group(1) else "md", m, target, anchor, None, m.group(2), angle, False)

    for m in _REFDEF.finditer(text):
        if not in_body(m.start()) or m.group(1).startswith("^"):
            continue
        raw_target = m.group(2)
        angle = raw_target.startswith("<")
        path = raw_target[1:-1] if angle else raw_target
        target, anchor = _split_anchor(path)
        add("refdef", m, target, anchor, None, m.group(1), angle, False)

    found.sort(key=lambda l: (l.start, l.end))
    result: List[Link] = []
    last_end = -1
    for link in found:
        if link.start < last_end:
            continue
        result.append(link)
        last_end = link.end
    return result


def _target_offset(link: Link) -> int:
    """Offset inside link.raw where the written target (or wikilink name) starts."""
    raw = link.raw
    if link.kind in ("wiki", "embed"):
        i = 3 if link.kind == "embed" else 2
        while raw[i].isspace():
            i += 1
        return i
    if link.kind == "refdef":
        i = raw.index("]:") + 2
        while raw[i] in " \t":
            i += 1
    else:
        i = (1 if link.kind == "image" else 0) + 1 + len(link.text or "") + 2
    return i + 1 if link.angle else i


def replace_target(link: Link, new_target: str) -> Optional[str]:
    """link.raw with only its target replaced; anchor, alias, title, and form are kept.

    new_target is the encoded path for a Markdown link (written decoded inside
    <...>) or the name for a wikilink. Returns None when the written target is
    not where it should be, so the caller leaves the link alone.
    """
    i = _target_offset(link)
    if link.raw[i:i + len(link.target)] != link.target:
        return None
    if link.angle:
        new_target = paths.decode(new_target)
    return link.raw[:i] + new_target + link.raw[i + len(link.target):]


def headings(text: str) -> List[str]:
    fm = frontmatter_span(text)
    spans = _fence_spans(text) + [(m.start(), m.end()) for m in _COMMENT.finditer(text)]
    if fm:
        spans.append(fm)
    out: List[str] = []
    for m in _HEADING.finditer(text):
        if _inside(m.start(), spans):
            continue
        title = re.sub(r"(?:^|[ \t]+)#+$", "", (m.group(2) or "").strip()).strip()
        out.append(title)
    return out


def read(path: Path) -> Tuple[str, bool]:
    data = Path(path).read_bytes()
    bom = data.startswith(_BOM)
    if bom:
        data = data[len(_BOM):]
    return data.decode("utf-8"), bom


def write(path: Path, text: str, bom: bool) -> None:
    data = text.encode("utf-8")
    Path(path).write_bytes((_BOM + data) if bom else data)
