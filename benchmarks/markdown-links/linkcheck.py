#!/usr/bin/env python3
"""Independent link check for benchmark workspaces. Does not import the plugin.

A body link is fine when its destination, percent-decoded and resolved from the
note's folder, names an existing file. A raw space in a destination (outside
<...>) is broken, as in CommonMark. Body wikilinks are problems. Frontmatter
wikilinks must match exactly one note by filename. Code is skipped.

Usage: linkcheck.py <root>   (prints problems, exits 1 if any)
"""
import os
import re
import sys
import urllib.parse
from dataclasses import dataclass
from typing import List, Optional

INLINE = re.compile(r"!?\[(?:[^\]\\\n]|\\.)*\]\((<[^>\n]*>|[^)\n]*)\)")
REFDEF = re.compile(r"^ {0,3}\[[^\]\n]+\]:[ \t]*(<[^>\n]*>|\S+)", re.M)
WIKI = re.compile(r"!?\[\[([^\]\n]+)\]\]")
FENCE = re.compile(r"^[ \t]*(```|~~~)[^\n]*\n.*?^[ \t]*\1[ \t]*$", re.M | re.S)
CODE = re.compile(r"`[^`\n]*`")
SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
TITLE = re.compile(r'\s+"[^"]*"$')


@dataclass
class Link:
    note: str  # root-relative path of the note holding it
    kind: str  # "md" or "wiki-body" or "wiki-frontmatter"
    raw: str
    target: Optional[str]  # root-relative path it resolves to, or None


def notes(root: str) -> List[str]:
    out = []
    for d, dirs, files in os.walk(root):
        dirs[:] = sorted(x for x in dirs if not x.startswith("."))
        out += [os.path.join(d, f) for f in sorted(files) if f.endswith(".md")]
    return out


def _split_frontmatter(text: str):
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            return text[4:end], text[end + 4:]
    return "", text


def scan(root: str) -> List[Link]:
    root = os.path.abspath(root)
    all_notes = notes(root)
    by_name = {}
    for n in all_notes:
        by_name.setdefault(os.path.basename(n)[:-3].lower(), []).append(n)
    links: List[Link] = []
    for n in all_notes:
        rel = os.path.relpath(n, root)
        text = open(n, encoding="utf-8", errors="replace").read()
        fm, body = _split_frontmatter(text)
        for m in WIKI.finditer(fm):
            name = m.group(1).split("|")[0].split("#")[0].strip()
            hits = by_name.get(os.path.basename(name).lower(), [])
            links.append(Link(rel, "wiki-frontmatter", m.group(0),
                              os.path.relpath(hits[0], root) if len(hits) == 1 else None))
        body = CODE.sub("", FENCE.sub("", body))
        for m in WIKI.finditer(body):
            links.append(Link(rel, "wiki-body", m.group(0), None))
        dests = [m.group(1) for m in INLINE.finditer(body)] + [m.group(1) for m in REFDEF.finditer(body)]
        for dest in dests:
            raw = dest
            dest = dest.strip()
            if dest.startswith("<") and dest.endswith(">"):
                dest = dest[1:-1]
            else:
                dest = TITLE.sub("", dest)
                if " " in dest:
                    links.append(Link(rel, "md", raw, None))
                    continue
            if not dest or dest.startswith("#") or SCHEME.match(dest):
                continue
            path = urllib.parse.unquote(dest.split("#", 1)[0])
            target = os.path.normpath(os.path.join(os.path.dirname(n), path))
            ok = os.path.isfile(target) and target.startswith(root + os.sep)
            links.append(Link(rel, "md", raw, os.path.relpath(target, root) if ok else None))
    return links


def problems(links: List[Link]) -> List[str]:
    out = []
    for l in links:
        if l.kind == "wiki-body":
            out.append(f"{l.note}: wikilink in body: {l.raw}")
        elif l.target is None:
            what = "frontmatter wikilink matches no single note" if l.kind == "wiki-frontmatter" else "broken link"
            out.append(f"{l.note}: {what}: {l.raw}")
    return out


if __name__ == "__main__":
    found = problems(scan(sys.argv[1]))
    print("\n".join(found) if found else "clean")
    sys.exit(1 if found else 0)
