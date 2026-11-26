import json
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


if __name__ == "__main__":
    unittest.main()
