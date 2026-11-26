import contextlib
import io
import json
import os
import tempfile
import unicodedata
import unittest
from pathlib import Path

from tests import helpers
from mdlinks import cli, link, resolve, root as rootmod

FILES = {
    "People/Jane Doe.md": "",
    "A/Tasks.md": "",
    "B/Tasks.md": "",
    "Secret/Hidden.md": "",
}


class LinkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(os.path.abspath(self.tmp.name))
        self.dir = self.base / "root"
        self.dir.mkdir()
        helpers.make_root(self.dir, FILES, {"exclude": ["Secret"]})
        self.root = rootmod.load(self.dir)

    def make(self, from_rel, to, **kw):
        return link.make_link(self.root, self.dir / from_rel, to, **kw)

    def cli(self, *argv, json_mode=False):
        out, err = io.StringIO(), io.StringIO()
        args = (["--json"] if json_mode else []) + list(argv)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(args)
        return code, out.getvalue(), err.getvalue()

    def test_link_depths(self):
        self.assertEqual(self.make("x.md", "Jane Doe"), "[Jane Doe](People/Jane%20Doe.md)")
        self.assertEqual(self.make("A/x.md", "Jane Doe"), "[Jane Doe](../People/Jane%20Doe.md)")
        self.assertEqual(
            self.make("A/B/C/x.md", "Jane Doe"), "[Jane Doe](../../../People/Jane%20Doe.md)"
        )

    def test_link_text_and_heading(self):
        self.assertEqual(
            self.make("x.md", "Jane Doe", text="Jane", heading="Contact info"),
            "[Jane](People/Jane%20Doe.md#Contact%20info)",
        )

    def test_link_ambiguous_and_missing(self):
        with self.assertRaises(link.LinkError) as cm:
            self.make("x.md", "Tasks")
        self.assertIn("A/Tasks.md", str(cm.exception))
        self.assertIn("B/Tasks.md", str(cm.exception))
        with self.assertRaises(link.LinkError):
            self.make("x.md", "Nobody")
        code, out, err = self.cli("link", str(self.dir / "x.md"), "Tasks")
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertTrue(err.startswith("error:"))
        code, out, err = self.cli("link", str(self.dir / "x.md"), "Tasks", json_mode=True)
        self.assertEqual(code, 1)
        self.assertIn("error:", err)

    def test_link_uses_on_disk_unicode_form(self):
        nfd = unicodedata.normalize("NFD", "Café.md")
        helpers.make_root(self.dir, {nfd: ""}, {"exclude": ["Secret"]})
        self.root = rootmod.load(self.dir)
        want = "[" + nfd[:-3] + "](Cafe%CC%81.md)"
        self.assertEqual(self.make("A.md", unicodedata.normalize("NFC", "Café")), want)
        self.assertEqual(self.make("A.md", unicodedata.normalize("NFC", "Café.md")), want)

    def test_link_by_path(self):
        self.assertEqual(self.make("x.md", "B/Tasks.md"), "[Tasks](B/Tasks.md)")
        self.assertEqual(self.make("A/x.md", str(self.dir / "B" / "Tasks.md")), "[Tasks](../B/Tasks.md)")

    def test_path_outside_root_or_excluded(self):
        outside = self.base / "out.md"
        outside.write_text("")
        with self.assertRaises(link.LinkError):
            self.make("x.md", str(outside))
        with self.assertRaises(link.LinkError):
            self.make("x.md", "Secret/Hidden.md")

    def test_from_note_outside_root(self):
        with self.assertRaises(link.LinkError):
            link.make_link(self.root, self.base / "x.md", "Jane Doe")

    def test_link_output_resolves(self):
        import re

        cases = [
            ("x.md", "Jane Doe", None),
            ("A/x.md", "Jane Doe", "Contact info"),
            ("A/B/C/x.md", "Jane Doe", None),
            ("x.md", "B/Tasks.md", None),
        ]
        for from_rel, to, heading in cases:
            md = self.make(from_rel, to, heading=heading)
            target = re.match(r"\[[^\]]*\]\(([^)#]*)", md).group(1)
            got = resolve.md_target(self.root, self.dir / from_rel, target)
            self.assertIsNotNone(got.path, md)
            self.assertTrue(got.note_relative, md)

    def test_cli_prints_link(self):
        code, out, _ = self.cli(
            "link", str(self.dir / "A" / "x.md"), "Jane Doe", "--text", "Jane", "--heading", "Hi there"
        )
        self.assertEqual((code, out), (0, "[Jane](../People/Jane%20Doe.md#Hi%20there)\n"))
        code, out, _ = self.cli("link", str(self.dir / "x.md"), "Jane Doe", json_mode=True)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), {"link": "[Jane Doe](People/Jane%20Doe.md)"})


if __name__ == "__main__":
    unittest.main()
