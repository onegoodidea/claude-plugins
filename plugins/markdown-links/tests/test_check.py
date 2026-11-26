import contextlib
import io
import json
import tempfile
import unicodedata
import unittest
from pathlib import Path

from tests import helpers
from mdlinks import check, cli, root as rootmod


class CheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

    def run_check(self, files, config={"exclude": []}, note="n.md"):
        root_dir = self.base / "root"
        root_dir.mkdir(exist_ok=True)
        helpers.make_root(root_dir, files, config)
        r = rootmod.load(root_dir)
        return [(f.level, f.line) for f in check.check_file(r, r.path / note)]

    def test_broken_md_link(self):
        self.assertEqual(self.run_check({"n.md": "a\n[x](nope.md)\n"}), [("error", 2)])

    def test_case_mismatch(self):
        got = self.run_check({"n.md": "[x](jane.md)\n", "Jane.md": ""})
        self.assertEqual(got, [("error", 1)])

    def test_unicode_form_mismatch_is_like_case(self):
        nfd = unicodedata.normalize("NFD", "Café.md")
        fm = '---\nup: "[[Caf\u00e9]]"\n---\n'
        files = {nfd: "", "n.md": fm + "[c](Caf%C3%A9.md)\n[[Caf\u00e9]]\n"}
        root_dir = self.base / "root"
        root_dir.mkdir()
        helpers.make_root(root_dir, files)
        r = rootmod.load(root_dir)
        got = [(f.level, f.line, f.message) for f in check.check_file(r, r.path / "n.md")]
        self.assertEqual(got, [
            ("error", 4, "case differs from the file on disk: [c](Caf%C3%A9.md)"),
            ("error", 5, "use a Markdown link: [[Caf\u00e9]]"),
        ])

    def test_not_note_relative(self):
        got = self.run_check({"a/n.md": "\n[x](b/t.md)\n", "b/t.md": ""}, note="a/n.md")
        self.assertEqual(got, [("error", 2)])

    def test_unresolved_path_link_is_broken(self):
        root_dir = self.base / "root"
        root_dir.mkdir()
        text = "[old](../Gamma/Tasks.md)\n[root](Alpha/Tasks.md)\n"
        helpers.make_root(root_dir, {"Alpha/Tasks.md": "", "Beta/B.md": text})
        r = rootmod.load(root_dir)
        got = [(f.level, f.line, f.message) for f in check.check_file(r, r.path / "Beta/B.md")]
        self.assertEqual(got, [
            ("error", 1, "broken link: [old](../Gamma/Tasks.md)"),
            ("error", 2, "broken link: [root](Alpha/Tasks.md)"),
        ])

    def test_outside_root_warning(self):
        (self.base / "out.md").write_text("")
        root_dir = self.base / "root"
        got = self.run_check({"n.md": "[x](../out.md)\n"})
        self.assertEqual(got, [("warning", 1)])
        self.assertTrue(root_dir.is_dir())

    def test_missing_heading_warning(self):
        files = {"n.md": "[a](t.md#Gone)\n[b](t.md#Here%20Now)\n", "t.md": "# Here now\n"}
        self.assertEqual(self.run_check(files), [("warning", 1)])

    def test_resolvable_body_wiki_is_error(self):
        got = self.run_check({"n.md": "x\n[[T]]\n", "T.md": ""})
        self.assertEqual(got, [("error", 2)])

    def test_ambiguous_body_wiki_is_warning(self):
        got = self.run_check({"n.md": "[[T]]\n[[Missing]]\n", "a/T.md": "", "b/T.md": ""})
        self.assertEqual(got, [("warning", 1), ("warning", 2)])

    def test_block_ref_warning(self):
        got = self.run_check({"n.md": "[[T#^abc]]\n![[T#^abc]]\n", "T.md": ""})
        self.assertEqual(got, [("warning", 1), ("warning", 2)])

    def test_transclusion_warning(self):
        self.assertEqual(self.run_check({"n.md": "![[T]]\n", "T.md": ""}), [("warning", 1)])

    def test_attachment_embed_error(self):
        got = self.run_check({"n.md": "![[p.png]]\n", "p.png": b"png"})
        self.assertEqual(got, [("error", 1)])

    def test_frontmatter_wiki_missing_and_ambiguous_are_errors(self):
        fm = "---\nup: \"[[Missing]]\"\nalso: \"[[T]]\"\nok: \"[[U]]\"\n---\n"
        files = {"n.md": fm, "a/T.md": "", "b/T.md": "", "U.md": ""}
        self.assertEqual(self.run_check(files), [("error", 2), ("error", 3)])

    def test_shared_names_alone_are_clean(self):
        self.assertEqual(self.run_check({"n.md": "hi\n", "a/Tasks.md": "", "b/Tasks.md": ""}), [])

    def test_clean_note(self):
        files = {
            "n.md": "---\nup: \"[[U]]\"\n---\n[x](U.md#Top)\n![i](p.png)\n",
            "U.md": "# Top\n",
            "p.png": b"png",
        }
        self.assertEqual(self.run_check(files), [])

    def test_undecodable_note_is_skipped_with_warning(self):
        root_dir = self.base / "root"
        helpers.make_root(root_dir, {"bad.md": b"\xff\xfe\x00", "n.md": "[x](nope.md)\n"})
        r = rootmod.load(root_dir)
        got = [(f.level, f.file, f.line) for f in check.check_root(r)]
        self.assertEqual(got, [("warning", "bad.md", 1), ("error", "n.md", 1)])


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

    def run_main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_cli_exit_codes(self):
        bad = self.base / "bad"
        helpers.make_root(bad, {"n.md": "[x](nope.md)\n"})
        self.assertEqual(self.run_main(["check", str(bad)])[0], 1)
        good = self.base / "good"
        helpers.make_root(good, {"n.md": "hi\n"})
        self.assertEqual(self.run_main(["check", str(good)])[0], 0)
        none = self.base / "none"
        none.mkdir()
        code, _, err = self.run_main(["check", str(none)])
        self.assertEqual(code, 2)
        self.assertIn("error: no .markdown-links.json at or above", err)

    def test_cli_malformed_config(self):
        for content in ["{nope", "[]", '{"exclude": "x"}', '{"exclude": [1]}']:
            d = self.base / "c"
            helpers.make_root(d, {"n.md": "hi\n"}, None)
            (d / ".markdown-links.json").write_text(content)
            code, out, err = self.run_main(["check", str(d)])
            self.assertEqual(code, 1, content)
            self.assertTrue(err.startswith("error: "), err)
            self.assertIn(".markdown-links.json", err)

    def test_cli_json(self):
        d = self.base / "j"
        helpers.make_root(d, {"n.md": "[x](nope.md)\n"})
        code, out, _ = self.run_main(["--json", "check", str(d)])
        data = json.loads(out)
        self.assertEqual(code, 1)
        self.assertEqual(set(data[0]), {"level", "file", "line", "message"})

    def test_init_writes_config_and_obsidian_settings(self):
        d = self.base / "i"
        (d / ".obsidian").mkdir(parents=True)
        (d / ".obsidian" / "app.json").write_text('{"vimMode": true}')
        wrote = cli.init(d)
        self.assertEqual(len(wrote), 2)
        self.assertEqual((d / ".markdown-links.json").read_text(), '{"exclude": []}\n')
        app = json.loads((d / ".obsidian" / "app.json").read_text())
        self.assertEqual(app, {"vimMode": True, "useMarkdownLinks": True,
                               "newLinkFormat": "relative", "alwaysUpdateLinks": True})
        (d / ".markdown-links.json").write_text('{"exclude": ["x"]}\n')
        self.assertEqual(cli.init(d), [])
        self.assertEqual((d / ".markdown-links.json").read_text(), '{"exclude": ["x"]}\n')


if __name__ == "__main__":
    unittest.main()
