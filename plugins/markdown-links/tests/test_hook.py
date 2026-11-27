import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests import helpers
from mdlinks import hook

ENTRY = helpers.SCRIPTS / "markdown-links.py"


def payload(path, **extra):
    return json.dumps({"tool_input": {"file_path": str(path)}, **extra})


class HookTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name).resolve()

    def test_hook_errors_exit_2(self):
        root = helpers.make_root(self.tmp, {"a.md": "See [[Jane Doe]].\n", "Jane Doe.md": "x\n"})
        code, err = hook.run(payload(root / "a.md"))
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith("markdown-links: fix these links in a.md:\n"))
        self.assertIn("use a Markdown link", err)

    def test_hook_warnings_only_silent(self):
        root = helpers.make_root(self.tmp, {"a.md": "See [[Nope]].\n"})
        self.assertEqual(hook.run(payload(root / "a.md")), (0, ""))

    def test_hook_clean(self):
        root = helpers.make_root(self.tmp, {"a.md": "See [b](b.md).\n", "b.md": "x\n"})
        self.assertEqual(hook.run(payload(root / "a.md")), (0, ""))

    def test_hook_ignores_odd_payloads(self):
        root = helpers.make_root(self.tmp / "r", {
            "a.md": "[[Jane]]\n", "n.txt": "[[Jane]]\n", "bad.md": b"\xff\xfe bad",
            "gone.md": "x\n", "Jane.md": "x\n", "skip/e.md": "[[Jane]]\n",
        }, {"exclude": ["skip"]})
        (root / "gone.md").unlink()
        outside = helpers.make_root(self.tmp / "o", {"a.md": "[[Jane]]\n", "Jane.md": "x\n"}, None)
        cases = [
            "not json", "{}", "[]", '{"tool_input": "x"}', '{"tool_input": {"file_path": 5}}',
            payload(root / "n.txt"), payload(root / "gone.md"), payload(outside / "a.md"),
            payload(root / "bad.md"), payload(root / "skip" / "e.md"),
        ]
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(hook.run(text), (0, ""))

    def test_hook_malformed_config_is_silent(self):
        root = helpers.make_root(self.tmp, {"a.md": "[[Jane]]\n", "Jane.md": "x\n"}, None)
        (root / ".markdown-links.json").write_text("{nope", encoding="utf-8")
        self.assertEqual(hook.run(payload(root / "a.md")), (0, ""))

    def test_hook_relative_path_joins_cwd(self):
        root = helpers.make_root(self.tmp, {"d/a.md": "[[Jane]]\n", "Jane.md": "x\n"})
        code, err = hook.run(json.dumps({"cwd": str(root), "tool_input": {"file_path": "d/a.md"}}))
        self.assertEqual(code, 2)
        self.assertIn("in d/a.md:", err)

    def test_hook_via_subprocess(self):
        root = helpers.make_root(self.tmp, {"a.md": "See [[Jane Doe]].\n", "Jane Doe.md": "x\n"})
        proc = subprocess.run(
            [sys.executable, str(ENTRY), "hook"], input=payload(root / "a.md"),
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("use a Markdown link", proc.stderr)
        self.assertEqual(proc.stdout, "")


def bash(command, cwd):
    return json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)})


class BashHookTest(unittest.TestCase):
    FILES = {
        "People/Jane Doe.md": "x\n",
        "Notes/Call.md": "See [Jane](../People/Jane%20Doe.md).\n",
        "Archive/.keep": "",
    }

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name).resolve()
        self.root = helpers.make_root(self.tmp / "root", self.FILES)

    def move(self):
        os.rename(self.root / "People/Jane Doe.md", self.root / "Archive/Jane Doe.md")

    def test_bash_hook_ignores_non_moves(self):
        self.move()
        self.assertEqual(hook.run(bash("ls -la", self.root)), (0, ""))
        self.assertEqual(hook.run(bash("echo summary; cat mvfile", self.root)), (0, ""))

    def test_bash_hook_names_relink(self):
        self.move()
        code, err = hook.run(bash('mv "People/Jane Doe.md" Archive/', self.root))
        self.assertEqual(code, 2)
        self.assertEqual(err.count("\n"), 1)
        script = helpers.SCRIPTS / "markdown-links.py"
        self.assertEqual(
            err,
            f'markdown-links: 1 broken link in {self.root}; '
            f'run: python3 "{script}" relink "{self.root}"\n')

    def test_bash_hook_plural(self):
        (self.root / "Notes/Other.md").write_text(
            "[a](../People/Jane%20Doe.md) [b](Gone.md)\n", encoding="utf-8")
        self.move()
        code, err = hook.run(bash("git mv a b", self.root))
        self.assertEqual(code, 2)
        self.assertIn("3 broken links in", err)

    def test_bash_hook_finds_root_from_path(self):
        self.move()
        outside = self.tmp / "elsewhere"
        outside.mkdir()
        command = f"git mv {self.root}/People/Jane\\ Doe.md {self.root}/Archive/Jane\\ Doe.md"
        code, err = hook.run(bash(command, outside))
        self.assertEqual(code, 2)
        self.assertIn(f"in {self.root};", err)

    def test_bash_hook_two_roots_one_line_each(self):
        other = helpers.make_root(self.tmp / "other", {"a.md": "[x](gone.md)\n"})
        self.move()
        code, err = hook.run(bash(f"mv {other}/a.md {self.root}/Archive/", self.tmp))
        self.assertEqual(code, 2)
        lines = err.splitlines()
        self.assertEqual(len(lines), 2)
        self.assertIn(f"in {other};", lines[0])
        self.assertIn(f"in {self.root};", lines[1])

    def test_bash_hook_clean_move_silent(self):
        self.assertEqual(hook.run(bash("mv People/Jane\\ Doe.md Archive/", self.root)), (0, ""))

    def test_bash_hook_skips_own_script(self):
        self.move()
        command = 'python3 "/x/markdown-links.py" mv People/Jane\\ Doe.md Archive/'
        self.assertEqual(hook.run(bash(command, self.root)), (0, ""))

    def test_bash_hook_outside_any_root_silent(self):
        outside = self.tmp / "plain"
        outside.mkdir()
        self.assertEqual(hook.run(bash("mv a.md b.md", outside)), (0, ""))

    def test_bash_hook_odd_payloads(self):
        self.move()
        cases = [
            {"tool_name": "Bash", "tool_input": {}, "cwd": str(self.root)},
            {"tool_name": "Bash", "tool_input": {"command": 5}, "cwd": str(self.root)},
            {"tool_name": "Bash", "tool_input": {"command": None}},
            {"tool_name": "Bash", "tool_input": "mv a b"},
            {"tool_name": "Bash"},
        ]
        for case in cases:
            with self.subTest(case=case):
                self.assertEqual(hook.run(json.dumps(case)), (0, ""))
        for command, cwd in [
            ('mv "a b', self.root), ("mv a b", self.tmp / "missing"), ("mv a b", ""),
        ]:
            with self.subTest(command=command, cwd=cwd):
                code, err = hook.run(bash(command, cwd))
                self.assertIn(code, (0, 2))
                if code == 2:
                    self.assertEqual(err.count("\n"), 1)
                    self.assertIn("1 broken link in", err)

    def test_bash_hook_at_most_five_roots(self):
        roots = [
            helpers.make_root(self.tmp / f"r{i}", {"a.md": "[x](gone.md)\n"}) for i in range(7)]
        command = "mv " + " ".join(f"{r}/a.md" for r in roots) + " dest"
        code, err = hook.run(bash(command, self.tmp))
        self.assertEqual(code, 2)
        self.assertEqual(len(err.splitlines()), 5)

    def test_bash_hook_via_subprocess(self):
        self.move()
        proc = subprocess.run(
            [sys.executable, str(ENTRY), "hook"], input=bash("mv a b", self.root),
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("relink", proc.stderr)
        self.assertEqual(proc.stdout, "")


if __name__ == "__main__":
    unittest.main()
