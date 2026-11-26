from __future__ import annotations

import os
import urllib.parse
from pathlib import Path


def relative(from_note: Path, target: Path) -> str:
    """POSIX path from from_note's folder to target, with no ./ prefix."""
    start = os.path.dirname(str(from_note)) or "."
    return Path(os.path.relpath(str(target), start)).as_posix()


def encode(posix_path: str) -> str:
    return "/".join(urllib.parse.quote(seg, safe="") for seg in posix_path.split("/"))


def decode(target: str) -> str:
    return urllib.parse.unquote(target)


def encode_anchor(text: str) -> str:
    return urllib.parse.quote(text, safe="^")
