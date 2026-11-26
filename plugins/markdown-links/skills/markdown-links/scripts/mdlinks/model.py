from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List


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
