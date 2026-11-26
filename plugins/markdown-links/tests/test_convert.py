import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path

from tests import helpers
from mdlinks import check, cli, convert, parse, root as rootmod


class ConvertTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

    def load(self, files, config={"exclude": []}):
        helpers.make_root(self.base, files, config)
        return rootmod.load(self.base)

    def convert(self, files, note, config={"exclude": []}):
        r = self.load(files, config)
        path = r.path / note
        text = parse.read(path)[0]
        return convert.convert_text(r, path, text)

    def test_convert_forms(self):
        files = {
            "N.md": "# H one\n",
            "Folder/Inner.md": "",
            "My Note.md": "",
            "Café Notes.md": "",
            "p.png": b"\x89PNG",
            "doc.pdf": b"%PDF",
            "a/b/x.md": (
                "[[N]] [[N|Al]] [[N#H one]]\n"
                "[[#H]] [[#H one]]\n"
                "![[p.png]] ![[doc.pdf]]\n"
                "[[Folder/Inner]]\n"
                "[[My Note]]\n"
                "[[Café Notes]]\n"
            ),
        }
        new, count, warnings = self.convert(files, "a/b/x.md")
        self.assertEqual(
            new,
            "[N](../../N.md) [Al](../../N.md) [N](../../N.md#H%20one)\n"
            "[H](#H) [H one](#H%20one)\n"
            "![](../../p.png) [doc.pdf](../../doc.pdf)\n"
            "[Folder/Inner](../../Folder/Inner.md)\n"
            "[My Note](../../My%20Note.md)\n"
            "[Café Notes](../../Caf%C3%A9%20Notes.md)\n",
        )
        self.assertEqual(count, 10)
        self.assertEqual(warnings, [])

    def test_convert_table_alias(self):
        new, count, _ = self.convert(
            {"N.md": "", "x.md": "| [[N\\|Al]] |\n"}, "x.md"
        )
        self.assertEqual(new, "| [Al](N.md) |\n")
        self.assertEqual(count, 1)

    def test_convert_leaves_alone(self):
        text = (
            "---\n"
            'rel: "[[N]]"\n'
            "---\n"
            "`[[N]]` in code\n"
            "```\n[[N]]\n```\n"
            "[[Dup]]\n"
            "[[Nope]]\n"
            "![[N]]\n"
            "[[N#^abc]]\n"
        )
        files = {"N.md": "", "A/Dup.md": "", "B/Dup.md": "", "x.md": text}
        new, count, warnings = self.convert(files, "x.md")
        self.assertEqual(new, text)
        self.assertEqual(count, 0)
        self.assertEqual(
            [(w.level, w.file, w.line) for w in warnings],
            [("warning", "x.md", 8), ("warning", "x.md", 9),
             ("warning", "x.md", 10), ("warning", "x.md", 11)],
        )
        self.assertIn("ambiguous", warnings[0].message)
        self.assertIn("matches no file", warnings[1].message)
        self.assertIn("transclusion", warnings[2].message)
        self.assertIn("block reference", warnings[3].message)

    def test_convert_repairs_non_relative(self):
        files = {
            "People/Jane Doe.md": "",
            "A/x.md": (
                "[J](Jane%20Doe.md)\n"
                "[J](/People/Jane%20Doe.md)\n"
                "[J](<Jane Doe.md#top>)\n"
                "[J](Jane%20Doe.md#top)\n"
                "![i](Jane%20Doe.md)\n"
                "[ref]: Jane%20Doe.md\n"
                "[ok](../People/Jane%20Doe.md)\n"
            ),
        }
        new, count, _ = self.convert(files, "A/x.md")
        self.assertEqual(
            new,
            "[J](../People/Jane%20Doe.md)\n"
            "[J](../People/Jane%20Doe.md)\n"
            "[J](<../People/Jane Doe.md#top>)\n"
            "[J](../People/Jane%20Doe.md#top)\n"
            "![i](../People/Jane%20Doe.md)\n"
            "[ref]: ../People/Jane%20Doe.md\n"
            "[ok](../People/Jane%20Doe.md)\n",
        )
        self.assertEqual(count, 6)

    def test_convert_only_links_change(self):
        pairs = [
            ("[[N]]", "[N](N.md)"),
            ("[[N|Al]]", "[Al](N.md)"),
            ("[J](Jane.md)", "[J](P/Jane.md)"),
        ]
        template = (
            "# Title  \n\n"
            "Prose with trailing spaces   \n"
            "\tTabbed {0} line, see {1}.\n\n"
            "- item {2}\n"
            "  - nested\t\n"
            "> [!note] Callout\n"
            "> body {0}\n\n"
            "| a | b |\n|---|---|\n| {1} | x |\n"
            "```\n[[N]]\n```\n"
            "no trailing newline {2}"
        )
        files = {"N.md": "", "P/Jane.md": "",
                 "x.md": template.format(*[p[0] for p in pairs])}
        new, count, _ = self.convert(files, "x.md")
        self.assertEqual(count, 3 + 3)
        back = new
        for original, rewritten in pairs:
            back = back.replace(rewritten, original)
        self.assertEqual(back, files["x.md"])
        self.assertNotEqual(new, files["x.md"])

    def test_convert_preserves_crlf_and_bom(self):
        r = self.load({"N.md": "", "x.md": b"\xef\xbb\xbf# T\r\n[[N]]\r\n"})
        changed, _ = convert.convert_root(r, dry_run=False)
        self.assertEqual(changed, ["x.md"])
        self.assertEqual(
            (self.base / "x.md").read_bytes(),
            b"\xef\xbb\xbf# T\r\n[N](N.md)\r\n",
        )

    def test_convert_skips_invalid_utf8(self):
        bad = b"[[N]]\n\xff\xfe\n"
        r = self.load({"N.md": "", "bad.md": bad, "ok.md": "[[N]]\n"})
        changed, findings = convert.convert_root(r, dry_run=False)
        self.assertEqual(changed, ["ok.md"])
        self.assertEqual((self.base / "bad.md").read_bytes(), bad)
        self.assertEqual(
            [(f.level, f.file, f.message) for f in findings],
            [("warning", "bad.md", "not valid UTF-8; skipped")],
        )

    def test_convert_dry_run_writes_nothing(self):
        files = {"N.md": "", "a.md": "[[N]]\n", "b.md": "plain\n", "c.md": "[[N|x]]\n"}
        r = self.load(files)
        for p in self.base.iterdir():
            os.utime(p, (1_000_000, 1_000_000))
        before = {p.name: (p.read_bytes(), p.stat().st_mtime) for p in self.base.iterdir()}
        changed, _ = convert.convert_root(r, dry_run=True)
        self.assertEqual(changed, ["a.md", "c.md"])
        after = {p.name: (p.read_bytes(), p.stat().st_mtime) for p in self.base.iterdir()}
        self.assertEqual(before, after)

    def test_convert_then_check_clean(self):
        files = {
            "N.md": "# H\n",
            "People/Jane Doe.md": "",
            "p.png": b"x",
            "A/x.md": "[[N#H]] [[N|Al]] ![[p.png]] [J](Jane%20Doe.md) [[#H]]\n# H\n",
        }
        r = self.load(files)
        convert.convert_root(r, dry_run=False)
        errors = [f for f in check.check_root(rootmod.load(self.base)) if f.level == "error"]
        self.assertEqual(errors, [])

    def test_cli_convert(self):
        self.load({"N.md": "", "x.md": "[[N]] [[Nope]]\n"})
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["convert", str(self.base)])
        self.assertEqual(code, 0)
        lines = out.getvalue().splitlines()
        self.assertEqual(lines[0], "converted 1 links in 1 files")
        self.assertIn("warning: x.md:1: wikilink matches no file: [[Nope]]", lines)
        self.assertEqual((self.base / "x.md").read_text(), "[N](N.md) [[Nope]]\n")

    def test_cli_convert_dry_run(self):
        self.load({"N.md": "", "x.md": "[[N]]\n"})
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["convert", "--dry-run", str(self.base)])
        self.assertEqual(code, 1)  # the wikilink is still an error
        self.assertEqual(out.getvalue().splitlines()[0], "would convert 1 links in 1 files")
        self.assertEqual((self.base / "x.md").read_text(), "[[N]]\n")


if __name__ == "__main__":
    unittest.main()
