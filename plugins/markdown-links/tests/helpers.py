import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "skills" / "markdown-links" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def make_root(tmp, files, config={"exclude": []}):
    """Write files (str as UTF-8 exactly as given) and the config; return the root."""
    root = Path(tmp)
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, str):
            content = content.encode("utf-8")
        path.write_bytes(content)
    if config is not None:
        (root / ".markdown-links.json").write_text(json.dumps(config), encoding="utf-8")
    return root
