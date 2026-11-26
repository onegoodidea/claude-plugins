import contextlib
import io
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests import helpers
from mdlinks import check, cli, move, root as rootmod


class MoveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(os.path.abspath(self.tmp.name))
        self.dir = self.base / "root"
        self.dir.mkdir()

    def load(self, files, config={"exclude": []}):
        helpers.make_root(self.dir, files, config)
        return rootmod.load(self.dir)

    def mv(self, files, src, dst, config={"exclude": []}):
        r = self.load(files, config)
        plan = move.plan_move(r, self.dir / src, self.dir / dst)
        move.apply(r, plan)
        return plan

    def text(self, name):
        return (self.dir / name).read_text(encoding="utf-8")

    def snapshot(self):
        out = {}
        for dirpath, _, filenames in os.walk(self.dir):
            for name in filenames:
                path = Path(dirpath) / name
                out[path.relative_to(self.dir).as_posix()] = path.read_bytes()
        return out

    def cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def assertClean(self):
        findings = check.check_root(rootmod.load(self.dir))
        self.assertEqual([f for f in findings if f.level == "error"], [])

    def test_mv_file_rewrites_inbound(self):
        self.mv(
            {"People/Jane Doe.md": "# Jane\n", "A/x.md": "See [J](../People/Jane%20Doe.md).\n"},
            "People/Jane Doe.md", "Contacts/Jane Doe.md",
        )
        self.assertEqual(self.text("A/x.md"), "See [J](../Contacts/Jane%20Doe.md).\n")
        self.assertFalse((self.dir / "People/Jane Doe.md").exists())
        self.assertEqual(self.text("Contacts/Jane Doe.md"), "# Jane\n")
        self.assertClean()

    def test_mv_file_rewrites_outbound(self):
        self.mv(
            {
                "People/Jane Doe.md": "",
                "A/x.md": "[J](../People/Jane%20Doe.md) [S](y.md)\n",
                "A/y.md": "",
            },
            "A/x.md", "A/B/x.md",
        )
        self.assertEqual(self.text("A/B/x.md"), "[J](../../People/Jane%20Doe.md) [S](../y.md)\n")
        self.assertClean()

    def test_mv_folder(self):
        y = "# Top\n[x](../x.md)\n"
        self.mv(
            {
                "People/Jane Doe.md": "[x](../A/x.md) [y](../A/sub/y.md#Top)\n",
                "A/x.md": "[J](../People/Jane%20Doe.md) [y](sub/y.md)\n",
                "A/sub/y.md": y,
                "A/p.png": b"\x89PNG",
                "Index.md": "![p](A/p.png)\n",
            },
            "A", "Archive/A",
        )
        self.assertEqual(
            self.text("People/Jane Doe.md"),
            "[x](../Archive/A/x.md) [y](../Archive/A/sub/y.md#Top)\n",
        )
        self.assertEqual(
            self.text("Archive/A/x.md"), "[J](../../People/Jane%20Doe.md) [y](sub/y.md)\n"
        )
        self.assertEqual(self.text("Archive/A/sub/y.md"), y)
        self.assertEqual(self.text("Index.md"), "![p](Archive/A/p.png)\n")
        self.assertFalse((self.dir / "A").exists())
        self.assertClean()

    def test_mv_folder_keeps_already_correct_links_as_written(self):
        x = "[a](./y.md) [b](sub/../y.md) [c](y.md)\n"
        plan = self.mv(
            {
                "A/x.md": x,
                "A/y.md": "",
                "A/sub/w.md": "",
                "A/z.md": "[j](Jane.md)\n",
                "People/Jane.md": "",
            },
            "A", "Archive/A",
        )
        self.assertEqual(self.text("Archive/A/x.md"), x)
        self.assertEqual(self.text("Archive/A/z.md"), "[j](../../People/Jane.md)\n")
        self.assertEqual(sorted(plan.edits), [self.dir / "Archive/A/z.md"])

    def test_mv_rename_updates_wikilinks(self):
        self.mv(
            {
                "People/Jane Doe.md": "",
                "M.md": (
                    '---\nwith: "[[Jane Doe]]"\n'
                    'also: ["[[Jane Doe|J]]", "[[Jane Doe#Bio]]"]\n---\n'
                    "Body [J](People/Jane%20Doe.md)\n"
                ),
            },
            "People/Jane Doe.md", "People/Jane Q Doe.md",
        )
        self.assertEqual(
            self.text("M.md"),
            '---\nwith: "[[Jane Q Doe]]"\n'
            'also: ["[[Jane Q Doe|J]]", "[[Jane Q Doe#Bio]]"]\n---\n'
            "Body [J](People/Jane%20Q%20Doe.md)\n",
        )
        self.assertClean()

    def test_mv_rename_into_shared_name_qualifies(self):
        self.mv(
            {
                "A/Tasks.md": "",
                "C/Todo.md": "",
                "M.md": '---\ntodo: "[[Todo]]"\ntasks: "[[Tasks]]"\n---\n',
            },
            "C/Todo.md", "C/Tasks.md",
        )
        self.assertEqual(
            self.text("M.md"), '---\ntodo: "[[C/Tasks]]"\ntasks: "[[A/Tasks]]"\n---\n'
        )
        self.assertClean()

    def test_mv_makes_existing_wikilink_ambiguous_qualifies(self):
        self.mv(
            {"A/Tasks.md": "", "C/Other.md": "", "M.md": '---\ntasks: "[[Tasks]]"\n---\n'},
            "C/Other.md", "C/Tasks.md",
        )
        self.assertEqual(self.text("M.md"), '---\ntasks: "[[A/Tasks]]"\n---\n')
        self.assertClean()

    def test_mv_qualified_wikilink_follows_folder(self):
        self.mv(
            {"A/Tasks.md": "", "B/Tasks.md": "", "M.md": '---\nt: "[[A/Tasks|T]]"\n---\n'},
            "A", "Archive/A",
        )
        self.assertEqual(self.text("M.md"), '---\nt: "[[Archive/A/Tasks|T]]"\n---\n')
        self.assertClean()

    def test_mv_case_only_rename(self):
        self.mv(
            {"note.md": "# N\n", "M.md": '---\nn: "[[note]]"\n---\n[n](note.md#N)\n'},
            "note.md", "Note.md",
        )
        names = os.listdir(self.dir)
        self.assertIn("Note.md", names)
        self.assertNotIn("note.md", names)
        self.assertEqual(self.text("M.md"), '---\nn: "[[Note]]"\n---\n[n](Note.md#N)\n')
        self.assertClean()

    def test_mv_case_only_folder_rename(self):
        self.mv({"a/x.md": "", "M.md": "[x](a/x.md)\n"}, "a", "A")
        self.assertIn("A", os.listdir(self.dir))
        self.assertNotIn("a", os.listdir(self.dir))
        self.assertEqual(self.text("M.md"), "[x](A/x.md)\n")
        self.assertClean()

    def test_mv_keeps_bom_crlf_and_link_forms(self):
        self.mv(
            {
                "N.md": "# H\n",
                "x.md": (
                    b"\xef\xbb\xbf---\r\nn: \"[[N]]\"\r\n---\r\n"
                    b"[a](<N.md#H>) [b](N.md \"t\")  \r\n"
                    b"[r]: N.md\r\n`[c](N.md)`\r\n"
                ),
            },
            "N.md", "Sub/N.md",
        )
        self.assertEqual(
            (self.dir / "x.md").read_bytes(),
            b"\xef\xbb\xbf---\r\nn: \"[[N]]\"\r\n---\r\n"
            b"[a](<Sub/N.md#H>) [b](Sub/N.md \"t\")  \r\n"
            b"[r]: Sub/N.md\r\n`[c](N.md)`\r\n",
        )
        self.assertClean()

    def test_mv_hidden_file_in_moved_folder(self):
        self.mv({"A/.att/p.png": b"\x89PNG", "M.md": "![p](A/.att/p.png)\n"}, "A", "B")
        self.assertEqual(self.text("M.md"), "![p](B/.att/p.png)\n")
        self.assertTrue((self.dir / "B/.att/p.png").is_file())
        self.assertClean()

    def test_mv_invalid_utf8_moved_unchanged_with_warning(self):
        bad = b"[n](../N.md) \xff\n"
        self.load({"A/bad.md": bad, "N.md": "[b](A/bad.md)\n"})
        code, out, err = self.cli("mv", str(self.dir / "A"), str(self.dir / "B"))
        self.assertEqual(code, 0, err)
        self.assertEqual((self.dir / "B/bad.md").read_bytes(), bad)
        self.assertEqual(self.text("N.md"), "[b](B/bad.md)\n")
        self.assertIn("warning: B/bad.md:1: not valid UTF-8; links not updated\n", out)
        self.assertClean()

    def test_mv_refusals_change_nothing(self):
        files = {
            "A/x.md": "[y](y.md)\n",
            "A/y.md": "",
            "B/z.md": "",
            "T/t.md": "",
            "A/Drafts/d.md": "",
        }
        r = self.load(files, {"exclude": ["T", "A/Drafts"]})
        before = self.snapshot()
        cases = [
            ("A/x.md", self.dir / "B/z.md"),  # destination exists
            ("A/x.md", self.base / "out.md"),  # outside the root
            ("A/missing.md", self.dir / "A/q.md"),  # missing source
            ("T/t.md", self.dir / "t.md"),  # excluded source
            ("A/x.md", self.dir / "T/x.md"),  # excluded destination
            ("A", self.dir / "C"),  # folder holds an excluded folder
            ("B", self.dir / "B/C"),  # folder into itself
            ("B", self.dir / "A"),  # existing folder
        ]
        for src, dst in cases:
            with self.subTest(src=src, dst=dst):
                with self.assertRaises(move.MoveError):
                    move.plan_move(r, self.dir / src, dst)
                code, out, err = self.cli("mv", str(self.dir / src), str(dst))
                self.assertEqual(code, 1)
                self.assertTrue(err.startswith("error: "), err)
        self.assertEqual(self.snapshot(), before)
        self.assertClean()

    def test_mv_file_into_existing_folder(self):
        self.mv(
            {"x.md": "", "B/z.md": "", "M.md": "[x](x.md)\n"}, "x.md", "B"
        )
        self.assertTrue((self.dir / "B/x.md").is_file())
        self.assertEqual(self.text("M.md"), "[x](B/x.md)\n")
        self.assertClean()

    def test_mv_uses_folder_case_on_disk(self):
        self.load({"x.md": "", "B/z.md": "", "M.md": "[x](x.md)\n"})
        if not (self.dir / "b").exists():
            self.skipTest("file system is case-sensitive")
        r = rootmod.load(self.dir)
        move.apply(r, move.plan_move(r, self.dir / "x.md", self.dir / "b/x.md"))
        self.assertEqual(sorted(os.listdir(self.dir / "B")), ["x.md", "z.md"])
        self.assertEqual(self.text("M.md"), "[x](B/x.md)\n")
        self.assertClean()

    def test_apply_rechecks_destination(self):
        r = self.load({"x.md": "", "M.md": "[x](x.md)\n"})
        plan = move.plan_move(r, self.dir / "x.md", self.dir / "y.md")
        (self.dir / "y.md").write_text("other", encoding="utf-8")
        before = self.snapshot()
        with self.assertRaises(move.MoveError):
            move.apply(r, plan)
        self.assertEqual(self.snapshot(), before)

    def test_apply_failure_reports_completed_moves(self):
        self.load({"x.md": "", "M.md": "[x](x.md)\n"})

        def full(*args):
            raise OSError("disk full")

        with mock.patch("mdlinks.move.parse.write", full):
            code, out, err = self.cli("mv", str(self.dir / "x.md"), str(self.dir / "y.md"))
        self.assertEqual(code, 1)
        self.assertEqual(
            err, "error: writing M.md failed (disk full); completed: moved x.md -> y.md\n"
        )
        self.assertTrue((self.dir / "y.md").is_file())
        self.assertEqual(self.text("M.md"), "[x](x.md)\n")

    def test_mv_cli_output(self):
        self.load({"People/Jane Doe.md": "", "A/x.md": "[J](../People/Jane%20Doe.md)\n"})
        code, out, err = self.cli(
            "mv", str(self.dir / "People/Jane Doe.md"), str(self.dir / "Contacts/Jane Doe.md")
        )
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(
            out, "moved People/Jane Doe.md -> Contacts/Jane Doe.md\nupdated A/x.md\n"
        )
        self.assertClean()

    def test_mv_dry_run_writes_nothing(self):
        self.load({"People/Jane Doe.md": "", "A/x.md": "[J](../People/Jane%20Doe.md)\n"})
        before = self.snapshot()
        code, out, err = self.cli(
            "mv", str(self.dir / "People/Jane Doe.md"),
            str(self.dir / "Contacts/Jane Doe.md"), "--dry-run",
        )
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(
            out,
            "would move People/Jane Doe.md -> Contacts/Jane Doe.md\nwould update A/x.md\n",
        )
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.dir / "Contacts").exists())
        self.assertClean()

    def test_mv_uses_git_when_in_repo(self):
        if shutil.which("git") is None:
            self.skipTest("git is not installed")
        self.load({"People/Jane Doe.md": "", "A/x.md": "[J](../People/Jane%20Doe.md)\n"})

        def git(*args):
            return subprocess.run(
                ["git", "-C", str(self.dir), *args],
                check=True, capture_output=True, text=True,
            ).stdout

        git("init", "-q")
        git("config", "user.name", "Test")
        git("config", "user.email", "test@example.com")
        git("config", "commit.gpgsign", "false")
        git("add", "-A")
        git("commit", "-q", "-m", "init")
        code, out, err = self.cli(
            "mv", str(self.dir / "People/Jane Doe.md"), str(self.dir / "Contacts/Jane Doe.md")
        )
        self.assertEqual((code, err), (0, ""))
        status = git("status", "--porcelain")
        renames = [l for l in status.splitlines() if l.startswith("R")]
        self.assertEqual(len(renames), 1, status)
        self.assertIn("Contacts/Jane Doe.md", renames[0])
        self.assertClean()


if __name__ == "__main__":
    unittest.main()
