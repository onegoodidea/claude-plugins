from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


@dataclass(frozen=True)
class Finding:
    level: str  # "error" or "warning"
    file: str  # POSIX path relative to the root
    line: int
    message: str


def format_finding(f: Finding) -> str:
    return f"{f.level}: {f.file}:{f.line}: {f.message}"


@dataclass
class Root:
    path: Path
    exclude: List[str]
    notes: List[Path]  # .md files, absolute and sorted
    files: List[Path]  # all other files, absolute and sorted
    by_name: Dict[str, List[Path]]  # lowercased name -> paths


@dataclass
class Link:
    kind: str  # "md", "image", "refdef", "wiki", or "embed"
    start: int  # character offset into the full text
    end: int
    line: int  # 1-based
    raw: str  # text[start:end]
    target: str  # path part as written, without the anchor
    anchor: Optional[str]  # text after "#", without the "#"
    alias: Optional[str]  # wikilink alias
    text: Optional[str]  # Markdown link text, image alt, or refdef id
    in_frontmatter: bool
    angle: bool  # target written as <...>

    @property
    def block_ref(self) -> bool:
        return self.anchor is not None and self.anchor.startswith("^")


@dataclass(frozen=True)
class MdTarget:
    path: Optional[Path]  # None when nothing matched
    exact_case: bool  # False when only a case-insensitive match was found
    outside_root: bool  # resolved path is not under the root
    note_relative: bool  # False when read from the root or found by name
