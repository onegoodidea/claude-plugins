import tempfile
import unittest
from pathlib import Path

from tests import helpers
from mdlinks import resolve, root as rootmod


class ResolveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.dir = base / "root"
        self.dir.mkdir()
        (base / "x.md").write_text("outside\n")
        helpers.make_root(
            self.dir,
            {
                "People/Jane Doe.md": "",
                "A/Tasks.md": "",
                "B/Tasks.md": "",
                "img/p.png": b"png",
                "Templates/T.md": "",
            },
            {"exclude": ["Templates"]},
        )
        self.r = rootmod.load(self.dir)
        self.jane = self.r.path / "People/Jane Doe.md"
        self.tasks = self.r.path / "A/Tasks.md"

    def test_wikilink_by_name_case_insensitive(self):
        self.assertEqual(resolve.wikilink(self.r, "jane doe"), [self.jane])
        self.assertEqual(resolve.wikilink(self.r, "Jane Doe.md"), [self.jane])

    def test_wikilink_shared_name_and_qualified(self):
        self.assertEqual(len(resolve.wikilink(self.r, "Tasks")), 2)
        self.assertEqual(resolve.wikilink(self.r, "A/Tasks"), [self.r.path / "A/Tasks.md"])

    def test_wikilink_attachment_and_missing(self):
        self.assertEqual(resolve.wikilink(self.r, "p.png"), [self.r.path / "img/p.png"])
        self.assertEqual(resolve.wikilink(self.r, "Nope"), [])
        self.assertEqual(resolve.wikilink(self.r, "T"), [])
        self.assertEqual(resolve.wikilink(self.r, ""), [])

    def test_md_target_relative(self):
        t = resolve.md_target(self.r, self.tasks, "../People/Jane%20Doe.md")
        self.assertEqual(t.path, self.jane)
        self.assertTrue(t.exact_case)
        self.assertTrue(t.note_relative)
        self.assertFalse(t.outside_root)

    def test_md_target_case_mismatch(self):
        t = resolve.md_target(self.r, self.tasks, "../people/jane%20doe.md")
        self.assertEqual(t.path, self.jane)
        self.assertFalse(t.exact_case)

    def test_md_target_not_note_relative(self):
        for target in ("Jane%20Doe.md", "/People/Jane%20Doe.md"):
            t = resolve.md_target(self.r, self.tasks, target)
            self.assertEqual(t.path, self.jane)
            self.assertFalse(t.note_relative)

    def test_md_target_outside_and_missing(self):
        t = resolve.md_target(self.r, self.tasks, "../../x.md")
        self.assertTrue(t.outside_root)
        self.assertIsNotNone(t.path)
        self.assertIsNone(resolve.md_target(self.r, self.tasks, "Missing.md").path)

    def test_md_target_excluded_and_same_note(self):
        self.assertIsNone(resolve.md_target(self.r, self.tasks, "../Templates/T.md").path)
        t = resolve.md_target(self.r, self.tasks, "")
        self.assertEqual((t.path, t.exact_case, t.outside_root, t.note_relative), (self.tasks, True, False, True))


if __name__ == "__main__":
    unittest.main()
