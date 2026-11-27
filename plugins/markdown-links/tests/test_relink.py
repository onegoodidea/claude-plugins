import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests import helpers
from mdlinks import check, cli, relink, root as rootmod

HAVE_GIT = shutil.which("git") is not None


class RelinkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

    def make(self, files):
        helpers.make_root(self.base, files)
        return self.base

    def load(self):
        return rootmod.load(self.base)

    def git(self, *args):
        subprocess.run(
            ["git", "-C", str(self.base), "-c", "user.name=T", "-c", "user.email=t@example.com",
             "-c", "commit.gpgsign=false", *args],
            check=True, capture_output=True)

    def git_repo(self, files):
        self.make(files)
        self.git("init", "-q")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "start")

    def read(self, name):
        return (self.base / name).read_text(encoding="utf-8")

    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(list(argv))
        return code, out.getvalue()

    CALL = '---\nwith: "[[Jane Doe]]"\n---\nSee [Jane](../People/Jane%20Doe.md).\n'
    JANE = "Back to [Call](../Notes/Call.md).\n"

    @unittest.skipUnless(HAVE_GIT, "git not installed")
    def test_relink_git_rename(self):
        self.git_repo({"Notes/Call.md": self.CALL, "People/Jane Doe.md": self.JANE})
        (self.base / "Archive").mkdir()
        self.git("mv", "People/Jane Doe.md", "Archive/Jane Smith.md")
        root = self.load()
        self.assertEqual(
            relink.git_renames(root),
            {self.base / "People/Jane Doe.md": self.base / "Archive/Jane Smith.md"})
        changes, findings = relink.relink_all(root, False)
        self.assertEqual(findings, [])
        self.assertEqual(len(changes), 2)
        self.assertEqual(
            self.read("Notes/Call.md"),
            '---\nwith: "[[Jane Smith]]"\n---\nSee [Jane](../Archive/Jane%20Smith.md).\n')
        self.assertEqual(self.read("Archive/Jane Smith.md"), self.JANE)
        self.assertEqual(relink.count_broken(self.load()), 0)

    @unittest.skipUnless(HAVE_GIT, "git not installed")
    def test_git_renames_ignores_a_renames_off_config(self):
        self.git_repo({"Notes/Call.md": self.CALL, "People/Jane Doe.md": self.JANE})
        self.git("config", "status.renames", "false")
        (self.base / "Archive").mkdir()
        self.git("mv", "People/Jane Doe.md", "Archive/Jane Smith.md")
        self.assertEqual(
            relink.git_renames(self.load()),
            {self.base / "People/Jane Doe.md": self.base / "Archive/Jane Smith.md"})

    @unittest.skipUnless(HAVE_GIT, "git not installed")
    def test_relink_git_rename_outgoing(self):
        self.git_repo({"Notes/Call.md": self.CALL, "People/Jane Doe.md": self.JANE})
        (self.base / "Archive/Notes/Deep").mkdir(parents=True)
        self.git("mv", "Notes/Call.md", "Archive/Notes/Deep/Call.md")
        changes, findings = relink.relink_all(self.load(), False)
        self.assertEqual(findings, [])
        self.assertIn("[Jane](../../../People/Jane%20Doe.md)", self.read("Archive/Notes/Deep/Call.md"))
        # the incoming link from Jane Doe.md is repaired too
        self.assertIn("(../Archive/Notes/Deep/Call.md)", self.read("People/Jane Doe.md"))
        self.assertEqual(relink.count_broken(self.load()), 0)

    @unittest.skipUnless(HAVE_GIT, "git not installed")
    def test_renames_outside_the_root_are_dropped(self):
        self.make({"sub/.markdown-links.json": '{"exclude": []}', "sub/a.md": "", "other/b.md": ""})
        self.git("init", "-q")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "start")
        self.git("mv", "sub/a.md", "other/a.md")
        self.git("mv", "other/b.md", "sub/b.md")
        root = rootmod.load(self.base / "sub")
        self.assertEqual(relink.git_renames(root), {})

    def test_git_renames_empty_without_git_work_tree(self):
        self.make({"a.md": ""})
        self.assertEqual(relink.git_renames(self.load()), {})

    def test_relink_folder_by_suffix(self):
        self.make({"Research/Tasks.md": "", "Tasks.md": "", "Notes/a.md": "[t](../Research/Tasks.md)\n"})
        (self.base / "Archive").mkdir()
        os.rename(self.base / "Research", self.base / "Archive/Research")
        changes, findings = relink.relink_all(self.load(), False)
        self.assertEqual(findings, [])
        self.assertEqual(self.read("Notes/a.md"), "[t](../Archive/Research/Tasks.md)\n")
        self.assertEqual([(c.file, c.line, c.old, c.new) for c in changes],
                         [("Notes/a.md", 1, "[t](../Research/Tasks.md)",
                           "[t](../Archive/Research/Tasks.md)")])

    def test_relink_tie_left_alone(self):
        self.make({"Archive/A/Tasks.md": "", "Archive/B/Tasks.md": "",
                   "Notes/a.md": "[t](../Research/Tasks.md)\n"})
        changes, findings = relink.relink_all(self.load(), False)
        self.assertEqual(changes, [])
        self.assertEqual([(f.level, f.file, f.line, f.message) for f in findings],
                         [("error", "Notes/a.md", 1, "broken link: [t](../Research/Tasks.md)")])
        self.assertEqual(self.read("Notes/a.md"), "[t](../Research/Tasks.md)\n")

    def test_relink_no_candidate_reported(self):
        self.make({"a.md": "[gone](gone.md)\n---\n"})
        changes, findings = relink.relink_all(self.load(), False)
        self.assertEqual(changes, [])
        self.assertEqual([f.message for f in findings], ["broken link: [gone](gone.md)"])
        self.assertEqual(self.read("a.md"), "[gone](gone.md)\n---\n")

    def test_leftover_frontmatter_wikilink_uses_the_check_message(self):
        self.make({"a.md": '---\nwith: "[[Nobody]]"\n---\n'})
        root = self.load()
        _, findings = relink.relink_all(root, False)
        self.assertEqual([f.message for f in findings], ["wikilink matches no file: [[Nobody]]"])
        self.assertEqual(findings, [f for f in check.check_root(root) if f.level == "error"])

    def test_external_and_body_wikilinks_are_not_broken(self):
        self.make({"a.md": "[x](https://example.com/x.md) [[Nope]] [y](mailto:a@b.c)\n"})
        self.assertEqual(relink.count_broken(self.load()), 0)

    def test_relink_dry_run_writes_nothing(self):
        files = {"Notes/a.md": "[t](../Research/Tasks.md)\n", "Archive/Research/Tasks.md": ""}
        self.make(files)
        before = (self.base / "Notes/a.md").read_bytes()
        changes, findings = relink.relink_all(self.load(), True)
        self.assertEqual(len(changes), 1)
        self.assertEqual(findings, [])
        self.assertEqual((self.base / "Notes/a.md").read_bytes(), before)

    def test_relink_preserves_bytes(self):
        body = ("Top\r\n[a](<../People/Jane Doe.md>) and [b](../People/Jane%20Doe.md#Some%20Heading)"
                " \"title\"\r\nEnd\r\n")
        self.make({"Notes/a.md": b"\xef\xbb\xbf" + body.encode(), "Archive/Jane Doe.md": ""})
        relink.relink_all(self.load(), False)
        self.assertEqual(
            (self.base / "Notes/a.md").read_bytes(),
            b"\xef\xbb\xbf" + ("Top\r\n[a](<../Archive/Jane Doe.md>) and "
                               "[b](../Archive/Jane%20Doe.md#Some%20Heading) \"title\"\r\nEnd\r\n").encode())

    def test_relink_cli(self):
        self.make({"a.md": "fine\n"})
        self.assertEqual(self.run_cli("relink", str(self.base)),
                         (0, "relinked 0 links in 0 files\n"))

        self.make({"Notes/a.md": "[t](../Research/Tasks.md) [g](gone.md)\n",
                   "Archive/Research/Tasks.md": ""})
        code, out = self.run_cli("relink", "--dry-run", str(self.base))
        self.assertEqual(code, 1)
        self.assertEqual(out.splitlines(), [
            "would relink Notes/a.md:1: [t](../Research/Tasks.md) -> [t](../Archive/Research/Tasks.md)",
            "would relink 1 link in 1 file",
            "error: Notes/a.md:1: broken link: [g](gone.md)",
        ])
        self.assertIn("../Research/Tasks.md", self.read("Notes/a.md"))

        code, out = self.run_cli("relink", str(self.base))
        self.assertEqual(code, 1)
        self.assertEqual(out.splitlines()[0],
                         "relinked Notes/a.md:1: [t](../Research/Tasks.md) -> [t](../Archive/Research/Tasks.md)")

    def test_relink_cli_dry_run_exit_zero_when_nothing_broken(self):
        self.make({"a.md": "fine\n"})
        self.assertEqual(self.run_cli("relink", "--dry-run", str(self.base)),
                         (0, "would relink 0 links in 0 files\n"))

    def test_relink_cli_json(self):
        self.make({"Notes/a.md": "[t](../Research/Tasks.md) [g](gone.md)\n",
                   "Archive/Research/Tasks.md": ""})
        code, out = self.run_cli("relink", "--json", "--dry-run", str(self.base))
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out), {
            "changes": [{"file": "Notes/a.md", "line": 1, "old": "[t](../Research/Tasks.md)",
                         "new": "[t](../Archive/Research/Tasks.md)"}],
            "findings": [{"level": "error", "file": "Notes/a.md", "line": 1,
                          "message": "broken link: [g](gone.md)"}],
        })

    def test_relink_cli_refuses_a_subfolder(self):
        self.make({"sub/x.md": "[g](gone.md)\n"})
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["relink", str(self.base / "sub")])
        self.assertEqual(code, 1)
        self.assertEqual(out.getvalue(), "")
        self.assertEqual(err.getvalue(),
                         f"error: relink works on a whole root; run it on {self.base}\n")


if __name__ == "__main__":
    unittest.main()
