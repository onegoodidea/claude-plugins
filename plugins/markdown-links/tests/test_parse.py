import tempfile
import unittest
from pathlib import Path

from tests import helpers  # noqa: F401  (sets sys.path)
from mdlinks import parse


def one(text):
    links = parse.find_links(text)
    assert len(links) == 1, links
    return links[0]


class ParseTests(unittest.TestCase):
    def test_md_link_and_anchor(self):
        text = "[A](x/A%20b.md#H%20one)"
        l = one(text)
        self.assertEqual((l.kind, l.target, l.anchor, l.text), ("md", "x/A%20b.md", "H%20one", "A"))
        self.assertEqual(l.raw, text[l.start:l.end])
        self.assertFalse(l.angle)

    def test_angle_target(self):
        l = one("[A](<x/A b.md>)")
        self.assertEqual(l.target, "x/A b.md")
        self.assertTrue(l.angle)

    def test_image_and_refdef(self):
        l = one("![p](img/p.png)")
        self.assertEqual((l.kind, l.target), ("image", "img/p.png"))
        l = one("intro\n\n[id]: Notes/N.md\n")
        self.assertEqual((l.kind, l.target, l.line), ("refdef", "Notes/N.md", 3))

    def test_wiki_forms(self):
        cases = [
            ("[[N]]", "wiki", "N", None, None, False),
            ("[[N|Al]]", "wiki", "N", None, "Al", False),
            ("[[N#H]]", "wiki", "N", "H", None, False),
            ("[[#H]]", "wiki", "", "H", None, False),
            ("[[N#^b1]]", "wiki", "N", "^b1", None, True),
            ("![[p.png]]", "embed", "p.png", None, None, False),
        ]
        for text, kind, target, anchor, alias, block in cases:
            with self.subTest(text=text):
                l = one(text)
                self.assertEqual((l.kind, l.target, l.anchor, l.alias, l.block_ref),
                                 (kind, target, anchor, alias, block))

    def test_escaped_pipe_alias_in_table(self):
        l = one("| [[Note\\|Alias]] | x |")
        self.assertEqual((l.target, l.alias), ("Note", "Alias"))
        self.assertIn("\\", l.raw)

    def test_frontmatter_wikilinks_flagged(self):
        text = '---\nparticipants:\n  - "[[Jane Doe]]"\nref: "[x](y.md)"\n---\nbody\n'
        l = one(text)
        self.assertEqual((l.kind, l.target, l.in_frontmatter), ("wiki", "Jane Doe", True))
        self.assertEqual(parse.frontmatter_span(text), (0, text.index("---\nbody") + 3))

    def test_skips_code_and_comments(self):
        text = (
            "```\n[[a]]\n```\n"
            "~~~~\n[[b]]\n~~~\n[[c]]\n~~~~\n"
            "> ```\n> [[d]]\n> ```\n"
            "`[[e]]` and <!-- [[f]] -->\n"
            "<!--\n[[g]]\n-->\n"
            "[[after]]\n"
        )
        self.assertEqual([l.target for l in parse.find_links(text)], ["after"])

    def test_external_ignored(self):
        text = "[a](https://x.com) [b](mailto:a@b.c) [[obsidian:open]] [c](//host/p) [d](obsidian://x)"
        self.assertEqual(parse.find_links(text), [])

    def test_line_numbers_crlf(self):
        self.assertEqual(one("a\r\nb [[N]]\r\n").line, 2)

    def test_headings(self):
        self.assertEqual(parse.headings("# One\n```\n# not\n```\n## Two ##\n"), ["One", "Two"])

    def test_headings_skip_frontmatter(self):
        self.assertEqual(parse.headings("---\n# c\n---\n# Real\n"), ["Real"])

    def test_read_write_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "n.md"
            p.write_bytes(b"\xef\xbb\xbf---\r\nt: 1\r\n---\r\n[[N]]\r\n")
            text, bom = parse.read(p)
            self.assertTrue(bom)
            self.assertTrue(text.startswith("---\r\n"))
            self.assertIsNotNone(parse.frontmatter_span("\ufeff" + text))
            parse.write(p, text, bom)
            self.assertEqual(p.read_bytes(), b"\xef\xbb\xbf---\r\nt: 1\r\n---\r\n[[N]]\r\n")
            p.write_bytes(b"\xff\xfe")
            with self.assertRaises(UnicodeDecodeError):
                parse.read(p)


if __name__ == "__main__":
    unittest.main()
