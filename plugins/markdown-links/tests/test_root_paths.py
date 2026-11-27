import tempfile
import unittest
from pathlib import Path

from tests import helpers  # noqa: F401  (sets up sys.path)
from tests.helpers import make_root

from mdlinks import paths, root as rootmod


class RootTests(unittest.TestCase):
    def test_find_root_walks_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp, {"a/b/Note.md": "hi"})
            self.assertEqual(rootmod.find_root(root / "a/b/Note.md"), root)
            self.assertEqual(rootmod.find_root(root / "a"), root)
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(rootmod.find_root(Path(tmp)))

    def test_load_skips_dot_and_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(
                tmp,
                {
                    "Note.md": "",
                    ".obsidian/x.md": "",
                    "Templates/T.md": "",
                    "img/pic.png": b"\x89PNG",
                },
                {"exclude": ["Templates"]},
            )
            loaded = rootmod.load(root)
            self.assertEqual(loaded.notes, [root / "Note.md"])
            self.assertEqual(loaded.files, [root / "img/pic.png"])
            self.assertEqual(loaded.by_name["note"], [root / "Note.md"])
            self.assertEqual(loaded.by_name["note.md"], [root / "Note.md"])
            self.assertEqual(loaded.by_name["pic.png"], [root / "img/pic.png"])
            self.assertEqual(rootmod.rel(loaded, root / "img/pic.png"), "img/pic.png")

    def test_shared_names_listed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp, {"A/Tasks.md": "", "B/Tasks.md": ""})
            self.assertEqual(len(rootmod.load(root).by_name["tasks"]), 2)


class PathTests(unittest.TestCase):
    def test_relative_paths(self):
        self.assertEqual(
            paths.relative(Path("Journal/2026/10/D.md"), Path("Ideas/I.md")),
            "../../../Ideas/I.md",
        )
        self.assertEqual(paths.relative(Path("A/x.md"), Path("A/y.md")), "y.md")
        self.assertEqual(paths.relative(Path("x.md"), Path("A/y.md")), "A/y.md")

    def test_encode_special_characters(self):
        self.assertEqual(paths.encode("App Review (beta).md"), "App%20Review%20%28beta%29.md")
        self.assertEqual(paths.encode("St. Ann’s.md"), "St.%20Ann%E2%80%99s.md")
        self.assertEqual(paths.encode("C# 100%.md"), "C%23%20100%25.md")
        self.assertEqual(paths.encode("../A b/c.md"), "../A%20b/c.md")
        self.assertEqual(paths.decode("A%20b.md"), "A b.md")

    def test_encode_anchor(self):
        self.assertEqual(paths.encode_anchor("Some Heading"), "Some%20Heading")
        self.assertEqual(paths.encode_anchor("^abc"), "^abc")


if __name__ == "__main__":
    unittest.main()
