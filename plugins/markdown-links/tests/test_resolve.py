import tempfile
import unicodedata
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
        t = resolve.md_target(self.r, self.tasks, "/People/Jane%20Doe.md")
        self.assertEqual(t.path, self.jane)
        self.assertFalse(t.note_relative)
        self.assertIsNone(resolve.md_target(self.r, self.tasks, "Jane%20Doe.md").path)

    def test_md_target_outside_and_missing(self):
        t = resolve.md_target(self.r, self.tasks, "../../x.md")
        self.assertTrue(t.outside_root)
        self.assertIsNotNone(t.path)
        self.assertIsNone(resolve.md_target(self.r, self.tasks, "Missing.md").path)

    def test_md_target_excluded_and_same_note(self):
        self.assertIsNone(resolve.md_target(self.r, self.tasks, "../Templates/T.md").path)
        t = resolve.md_target(self.r, self.tasks, "")
        self.assertEqual((t.path, t.exact_case, t.outside_root, t.note_relative), (self.tasks, True, False, True))

    def test_bare_filename_not_found_by_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            helpers.make_root(tmp, {"Notes/a.md": "", "Other/Tasks.md": ""})
            r = rootmod.load(Path(tmp))
            self.assertIsNone(resolve.md_target(r, r.path / "Notes/a.md", "Tasks.md").path)


class UnicodeFormTests(unittest.TestCase):
    """A file stored decomposed (NFD) and a link written composed (NFC)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.nfd = unicodedata.normalize("NFD", "Café.md")
        helpers.make_root(self.tmp.name, {self.nfd: "", "Sub/n.md": ""})
        self.r = rootmod.load(Path(self.tmp.name))
        self.cafe = self.r.path / self.nfd
        self.note = self.r.path / "Sub/n.md"

    def test_wikilink_matches_across_forms(self):
        self.assertEqual(resolve.wikilink(self.r, unicodedata.normalize("NFC", "Café")), [self.cafe])
        self.assertEqual(resolve.wikilink(self.r, unicodedata.normalize("NFD", "café")), [self.cafe])

    def test_md_target_form_mismatch_is_like_case(self):
        t = resolve.md_target(self.r, self.note, "../Caf%C3%A9.md")
        self.assertEqual((t.path, t.exact_case, t.note_relative), (self.cafe, False, True))
        t = resolve.md_target(self.r, self.note, "../Cafe%CC%81.md")
        self.assertEqual((t.path, t.exact_case), (self.cafe, True))
        t = resolve.md_target(self.r, self.note, "/Caf%C3%A9.md")
        self.assertEqual((t.path, t.exact_case, t.note_relative), (self.cafe, False, False))
        self.assertIsNone(resolve.md_target(self.r, self.note, "Caf%C3%A9.md").path)


if __name__ == "__main__":
    unittest.main()
