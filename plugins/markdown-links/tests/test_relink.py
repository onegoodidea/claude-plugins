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
            ["git", "-C", str(self.base), "-c", "user.name=t", "-c", "user.email=t@t",
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

    DELETED = {"Old/Tasks.md": "", "Tasks.md": "", "Notes/a.md": "[t](../Old/Tasks.md)\n"}

    def assert_tracked_not_new(self, deleted, kept):
        view = relink.GitView(self.load())
        self.assertTrue(view.was_tracked(self.base / deleted))
        self.assertTrue(view.has(self.base / kept))

    def assert_left_as_deleted(self):
        changes, findings = relink.relink_all(self.load(), False)
        self.assertEqual(changes, [])
        self.assertEqual([(f.level, f.file, f.line, f.message) for f in findings],
                         [("error", "Notes/a.md", 1,
                           "broken link (deleted in git): [t](../Old/Tasks.md)")])
        self.assertEqual(self.read("Notes/a.md"), "[t](../Old/Tasks.md)\n")

    @unittest.skipUnless(HAVE_GIT, "git not installed")
    def test_relink_skips_git_rm(self):
        self.git_repo(self.DELETED)
        self.git("rm", "-q", "Old/Tasks.md")
        self.assert_tracked_not_new("Old/Tasks.md", "Tasks.md")
        self.assert_left_as_deleted()
        self.assertEqual(relink.count_broken(self.load()), 1)

    @unittest.skipUnless(HAVE_GIT, "git not installed")
    def test_relink_skips_committed_delete(self):
        self.git_repo(self.DELETED)
        self.git("rm", "-q", "Old/Tasks.md")
        self.git("commit", "-q", "-m", "remove")
        self.assert_tracked_not_new("Old/Tasks.md", "Tasks.md")
        self.assert_left_as_deleted()

    @unittest.skipUnless(HAVE_GIT, "git not installed")
    def test_relink_shell_mv_still_repairs(self):
        self.git_repo({"People/Jane Doe.md": "", "Notes/a.md": "[j](../People/Jane%20Doe.md)\n"})
        (self.base / "Archive").mkdir()
        os.rename(self.base / "People/Jane Doe.md", self.base / "Archive/Jane Doe.md")
        view = relink.GitView(self.load())
        self.assertTrue(view.was_tracked(self.base / "People/Jane Doe.md"))
        self.assertFalse(view.has(self.base / "Archive/Jane Doe.md"))
        changes, findings = relink.relink_all(self.load(), False)
        self.assertEqual(findings, [])
        self.assertEqual(self.read("Notes/a.md"), "[j](../Archive/Jane%20Doe.md)\n")

    @unittest.skipUnless(HAVE_GIT, "git not installed")
    def test_relink_committed_rename_not_deleted(self):
        self.git_repo({"People/Jane Doe.md": "", "Notes/a.md": "[j](../People/Jane%20Doe.md)\n"})
        (self.base / "Archive").mkdir()
        self.git("mv", "People/Jane Doe.md", "Archive/Jane Doe.md")
        self.git("commit", "-q", "-m", "move")
        view = relink.GitView(self.load())
        self.assertEqual(view.renames, {})  # committed renames wait for load_history
        self.assertTrue(view.load_history())
        self.assertEqual(view.renames,
                         {self.base / "People/Jane Doe.md": self.base / "Archive/Jane Doe.md"})
        changes, findings = relink.relink_all(self.load(), False)
        self.assertEqual(findings, [])
        self.assertEqual(self.read("Notes/a.md"), "[j](../Archive/Jane%20Doe.md)\n")

    @unittest.skipUnless(HAVE_GIT, "git not installed")
    def test_staged_rename_is_not_a_staged_deletion(self):
        self.git_repo({"People/Jane Doe.md": "", "Notes/a.md": "[j](../People/Jane%20Doe.md)\n"})
        (self.base / "Archive").mkdir()
        self.git("mv", "People/Jane Doe.md", "Archive/Jane Doe.md")
        view = relink.GitView(self.load())
        self.assertFalse(view.has(self.base / "Archive/Jane Doe.md"))
        changes, findings = relink.relink_all(self.load(), False)
        self.assertEqual(findings, [])
        self.assertEqual(self.read("Notes/a.md"), "[j](../Archive/Jane%20Doe.md)\n")

    def test_git_view_empty_without_git_work_tree(self):
        self.make({"a.md": ""})
        view = relink.GitView(self.load())
        self.assertFalse(view.load_history())
        self.assertFalse(view.was_tracked(self.base / "a.md"))
        self.assertEqual(view.renames, {})

    @unittest.skipUnless(HAVE_GIT, "git not installed")
    def test_committed_log_runs_once_and_only_when_needed(self):
        self.git_repo({**self.DELETED, "Notes/b.md": "[t](../Old/Tasks.md)\n",
                       "Notes/c.md": "[t](../Tasks.md)\n"})
        self.git("rm", "-q", "Old/Tasks.md")
        calls = []
        real = relink._git

        def spy(root, *args, **kw):
            calls.append(args)
            return real(root, *args, **kw)

        relink._git = spy
        self.addCleanup(setattr, relink, "_git", real)
        relink.relink_all(self.load(), True)
        self.assertEqual(sum(a[0] == "log" for a in calls), 1)
        calls.clear()
        self.git("checkout", "-q", "HEAD", "--", "Old/Tasks.md")
        relink.relink_all(self.load(), True)
        self.assertEqual(sum(a[0] == "log" for a in calls), 0)

    @unittest.skipUnless(HAVE_GIT, "git not installed")
    def test_relink_shell_rm_not_repointed(self):
        self.git_repo({"ProjectA/README.md": "[Tasks](Tasks.md)\n", "ProjectA/Tasks.md": "a\n",
                       "ProjectB/Tasks.md": "b\n"})
        os.remove(self.base / "ProjectA/Tasks.md")
        changes, findings = relink.relink_all(self.load(), False)
        self.assertEqual(changes, [])
        self.assertEqual([(f.file, f.line, f.message) for f in findings],
                         [("ProjectA/README.md", 1, "broken link (deleted in git): [Tasks](Tasks.md)")])
        self.assertEqual(self.read("ProjectA/README.md"), "[Tasks](Tasks.md)\n")

    @unittest.skipUnless(HAVE_GIT, "git not installed")
    def test_relink_shell_mv_prefers_the_file_git_does_not_have(self):
        # Old/Jane Doe.md ties on trailing segments, but git has it at its path; the move's
        # destination is untracked, so it is the only candidate.
        self.git_repo({"People/Jane Doe.md": "j\n", "Old/Jane Doe.md": "o\n",
                       "Notes/a.md": "[j](../People/Jane%20Doe.md)\n"})
        (self.base / "Archive").mkdir()
        os.rename(self.base / "People/Jane Doe.md", self.base / "Archive/Jane Doe.md")
        changes, findings = relink.relink_all(self.load(), False)
        self.assertEqual(findings, [])
        self.assertEqual(self.read("Notes/a.md"), "[j](../Archive/Jane%20Doe.md)\n")

    NOTE_TEXT = "Some text long enough for git to see the rename.\nA second line.\n"

    @unittest.skipUnless(HAVE_GIT, "git not installed")
    def test_relink_committed_shell_rename(self):
        self.git_repo({"People/Jane Doe.md": self.NOTE_TEXT, "Projects/Tasks.md": self.NOTE_TEXT + "t\n",
                       "Notes/a.md": "[j](../People/Jane%20Doe.md) [t](../Projects/Tasks.md)\n"})
        (self.base / "Archive/Old").mkdir(parents=True)
        os.rename(self.base / "People/Jane Doe.md", self.base / "Archive/Jane Smith.md")
        os.rename(self.base / "Projects/Tasks.md", self.base / "Archive/Old/Tasks.md")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "move")
        changes, findings = relink.relink_all(self.load(), False)
        self.assertEqual(findings, [])
        self.assertEqual(self.read("Notes/a.md"),
                         "[j](../Archive/Jane%20Smith.md) [t](../Archive/Old/Tasks.md)\n")

    @unittest.skipUnless(HAVE_GIT, "git not installed")
    def test_relink_chained_committed_renames(self):
        self.git_repo({"A.md": self.NOTE_TEXT, "Notes/n.md": "[x](../A.md)\n"})
        self.git("mv", "A.md", "B.md")
        self.git("commit", "-q", "-m", "a to b")
        (self.base / "Later").mkdir()
        self.git("mv", "B.md", "Later/C.md")
        self.git("commit", "-q", "-m", "b to c")
        changes, findings = relink.relink_all(self.load(), False)
        self.assertEqual(findings, [])
        self.assertEqual(self.read("Notes/n.md"), "[x](../Later/C.md)\n")

    @unittest.skipUnless(HAVE_GIT, "git not installed")
    def test_relink_never_tracked_bare_filename_by_name(self):
        self.git_repo({"Notes/a.md": "[Tasks](Tasks.md)\n", "ProjectB/Tasks.md": "b\n"})
        changes, findings = relink.relink_all(self.load(), False)
        self.assertEqual(findings, [])
        self.assertEqual(self.read("Notes/a.md"), "[Tasks](../ProjectB/Tasks.md)\n")

    @unittest.skipUnless(HAVE_GIT, "git not installed")
    def test_relink_frontmatter_after_committed_rename(self):
        self.git_repo({"Old Name.md": self.NOTE_TEXT,
                       "Notes/a.md": '---\nabout: "[[Old Name|the note]]"\n---\nBody.\n'})
        self.git("mv", "Old Name.md", "New Name.md")
        self.git("commit", "-q", "-m", "rename")
        changes, findings = relink.relink_all(self.load(), False)
        self.assertEqual(findings, [])
        self.assertEqual(self.read("Notes/a.md"), '---\nabout: "[[New Name|the note]]"\n---\nBody.\n')

    @unittest.skipUnless(HAVE_GIT, "git not installed")
    def test_relink_no_commits_yet_uses_never_tracked_rules(self):
        self.make({"Notes/a.md": "[t](../Research/Tasks.md)\n", "Archive/Research/Tasks.md": ""})
        self.git("init", "-q")
        changes, findings = relink.relink_all(self.load(), False)
        self.assertEqual(findings, [])
        self.assertEqual(self.read("Notes/a.md"), "[t](../Archive/Research/Tasks.md)\n")

    @unittest.skipUnless(HAVE_GIT, "git not installed")
    def test_relink_without_git_on_path_uses_never_tracked_rules(self):
        self.git_repo({"ProjectA/README.md": "[Tasks](Tasks.md)\n", "ProjectA/Tasks.md": "a\n",
                       "ProjectB/Tasks.md": "b\n"})
        os.remove(self.base / "ProjectA/Tasks.md")
        real = relink.shutil.which
        relink.shutil.which = lambda name: None
        self.addCleanup(setattr, relink.shutil, "which", real)
        changes, findings = relink.relink_all(self.load(), False)
        self.assertEqual(findings, [])
        self.assertEqual(self.read("ProjectA/README.md"), "[Tasks](../ProjectB/Tasks.md)\n")

    def git_mv_case_only(self, old, new):
        try:
            self.git("mv", old, new)
        except subprocess.CalledProcessError:  # a filesystem that needs a step in between
            self.git("mv", old, "case-rename.tmp")
            self.git("mv", "case-rename.tmp", new)

    @unittest.skipUnless(HAVE_GIT, "git not installed")
    def test_relink_case_only_rename(self):
        self.git_repo({"note.md": self.NOTE_TEXT, "a.md": "[n](note.md) [h](note.md#Top)\n"})
        self.git_mv_case_only("note.md", "Note.md")
        root = self.load()
        self.assertEqual(relink.count_broken(root), 2)
        changes, findings = relink.relink_all(root, False)
        self.assertEqual(findings, [])
        self.assertEqual(self.read("a.md"), "[n](Note.md) [h](Note.md#Top)\n")
        self.assertEqual([f for f in check.check_root(self.load()) if f.level == "error"], [])

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

    def test_relink_same_folder_target_moved(self):
        self.make({"AGENTS.md": "[Blueprint](Blueprint.md)\n",
                   "Blueprint.md": "[Start](Start.md)\n", "Start.md": ""})
        (self.base / "Archive").mkdir()
        os.rename(self.base / "Blueprint.md", self.base / "Archive/Blueprint.md")
        self.assertEqual(relink.count_broken(self.load()), 2)
        changes, findings = relink.relink_all(self.load(), False)
        self.assertEqual(findings, [])
        self.assertEqual(self.read("AGENTS.md"), "[Blueprint](Archive/Blueprint.md)\n")
        self.assertEqual(self.read("Archive/Blueprint.md"), "[Start](../Start.md)\n")
        self.assertEqual(relink.count_broken(self.load()), 0)

    @unittest.skipUnless(HAVE_GIT, "git not installed")
    def test_relink_same_folder_git_rm_not_repointed(self):
        self.git_repo({"Decisions.md": "", "Home.md": "[Decisions](Decisions.md)\n"})
        self.make({"Ideas/Old/Decisions.md": ""})
        self.git("rm", "-q", "Decisions.md")
        changes, findings = relink.relink_all(self.load(), False)
        self.assertEqual(changes, [])
        self.assertEqual([(f.level, f.file, f.line, f.message) for f in findings],
                         [("error", "Home.md", 1,
                           "broken link (deleted in git): [Decisions](Decisions.md)")])
        self.assertEqual(self.read("Home.md"), "[Decisions](Decisions.md)\n")

    @unittest.skipUnless(HAVE_GIT, "git not installed")
    def test_relink_git_rm_untracked_same_name_not_repointed(self):
        self.git_repo({"Projects/Tasks.md": "t\n", "Notes/a.md": "[t](../Projects/Tasks.md)\n"})
        self.make({"Drafts/Tasks.md": "new, not yet committed\n"})
        self.git("rm", "-q", "Projects/Tasks.md")
        changes, findings = relink.relink_all(self.load(), False)
        self.assertEqual(changes, [])
        self.assertEqual([(f.file, f.line, f.message) for f in findings],
                         [("Notes/a.md", 1, "broken link (deleted in git): [t](../Projects/Tasks.md)")])
        self.assertEqual(self.read("Notes/a.md"), "[t](../Projects/Tasks.md)\n")

    @unittest.skipUnless(HAVE_GIT, "git not installed")
    def test_relink_committed_delete_untracked_same_name_not_repointed(self):
        self.git_repo({"Projects/Tasks.md": "t\n", "Notes/a.md": "[t](../Projects/Tasks.md)\n"})
        self.git("rm", "-q", "Projects/Tasks.md")
        self.git("commit", "-q", "-m", "remove")
        self.make({"Drafts/Tasks.md": "new, not yet committed\n"})
        changes, findings = relink.relink_all(self.load(), False)
        self.assertEqual(changes, [])
        self.assertEqual([f.message for f in findings],
                         ["broken link (deleted in git): [t](../Projects/Tasks.md)"])

    BODY = "A note with enough text for git to see the rename.\nAnother line here.\n"

    def renamed_notes_with_fixed_links(self):
        """Notes moved in an earlier commit, their links fixed in that same commit."""
        self.git_repo({
            "Decisions.md": "d\n", "Field Notes.md": "a\n", "Home.md": "[Decisions](Decisions.md)\n",
            "Blueprint.md": self.BODY + "[Decisions](Decisions.md)\n",
            "Research/R.md": self.BODY + "[Decisions](../Decisions.md) [A](../Field%20Notes.md)\n",
        })
        (self.base / "Archive/Research").mkdir(parents=True)
        self.git("mv", "Blueprint.md", "Archive/Blueprint.md")
        self.git("mv", "Research/R.md", "Archive/Research/R.md")
        self.make({
            "Archive/Blueprint.md": self.BODY + "[Decisions](../Decisions.md)\n",
            "Archive/Research/R.md": self.BODY + "[Decisions](../../Decisions.md) [A](../../Field%20Notes.md)\n",
        })
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "move")
        self.assertEqual(relink.count_broken(self.load()), 0)

    @unittest.skipUnless(HAVE_GIT, "git not installed")
    def test_relink_renamed_note_shell_rm_reported_deleted(self):
        self.renamed_notes_with_fixed_links()
        self.make({"Ideas/Old/Decisions.md": "unrelated\n"})
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "idea")
        os.remove(self.base / "Decisions.md")
        changes, findings = relink.relink_all(self.load(), False)
        self.assertEqual(changes, [])
        self.assertEqual(sorted((f.file, f.message) for f in findings), [
            ("Archive/Blueprint.md", "broken link (deleted in git): [Decisions](../Decisions.md)"),
            ("Archive/Research/R.md", "broken link (deleted in git): [Decisions](../../Decisions.md)"),
            ("Home.md", "broken link (deleted in git): [Decisions](Decisions.md)"),
        ])
        self.assertEqual(self.read("Archive/Blueprint.md"), self.BODY + "[Decisions](../Decisions.md)\n")

    @unittest.skipUnless(HAVE_GIT, "git not installed")
    def test_relink_renamed_note_gets_a_later_rename(self):
        self.renamed_notes_with_fixed_links()
        # A.md sorts first, and its broken link makes relink read the git history before
        # it gets to the renamed note.
        self.make({"A.md": "[g](gone.md)\n"})
        (self.base / "Ideas").mkdir()
        self.git("mv", "Field Notes.md", "Ideas/Field Notes Draft.md")
        changes, findings = relink.relink_all(self.load(), False)
        self.assertEqual([(f.file, f.message) for f in findings], [("A.md", "broken link: [g](gone.md)")])
        self.assertEqual(self.read("Archive/Research/R.md"), self.BODY +
                         "[Decisions](../../Decisions.md) [A](../../Ideas/Field%20Notes%20Draft.md)\n")

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
