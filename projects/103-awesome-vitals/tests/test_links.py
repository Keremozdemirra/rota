"""Link extraction: every link shape an awesome list uses, and everything that is not an entry."""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]
import awesome_vitals as av  # noqa: E402
from fakegithub import CENSUS, FIXTURES  # noqa: E402


def repos(text):
    entries, _ = av.collect([("list.md", text)])
    return {e["repository"]: [loc["line"] for loc in e["locations"]] for e in entries}


class Sample(unittest.TestCase):
    """tests/fixtures/sample.md, a constructed list with one line per link shape."""

    @classmethod
    def setUpClass(cls):
        text = (FIXTURES / "sample.md").read_text(encoding="utf-8")
        cls.entries, cls.ignored = av.collect([("sample.md", text)])
        cls.lines = {e["repository"]: [loc["line"] for loc in e["locations"]] for e in cls.entries}

    def test_every_link_shape_is_found_with_its_lines(self):
        self.assertEqual(self.lines, {
            "example-org/awesome-example": [3],        # the link around a CI badge, not the badge
            "octocat/Hello-World": [10, 21, 23],       # plain, other case, /releases; first spelling kept
            "octocat/archived-example": [11],          # /tree/main/src
            "octocat/unlicensed-example": [12],        # /blob/...#usage
            "octocat/other-licence-example": [13],     # #readme
            "octocat/renamed-example": [14],           # .git
            "octocat/gone-example": [15],              # next to a shields.io badge
            "TransformerOptimus/SuperAGI": [16],       # <autolink>
            "lharries/whatsapp-mcp": [17],             # bare, trailing comma
            "punkpeye/awesome-mcp-servers": [18],      # bare, trailing full stop
            "anthropics/skills": [19],                 # no scheme
            "n8n-io/n8n": [19],                        # www.
            "punkpeye/awesome-mcp-clients": [20],      # href, ?tab=
            "Keremozdemirra/agent-vitals": [24],
            "octocat/reference-style": [48],           # reference definition
        })

    def test_links_that_are_not_entries_are_counted_by_reason(self):
        self.assertEqual(self.ignored, {
            av.IMAGE_LINK: 3,     # badge image on github.com, markdown image, <img src>
            av.PROFILE: 3,        # github.com/octocat twice, github.com/example-org?tab=
            av.SITE_PAGE: 5,      # orgs, topics, sponsors, marketplace, apps
            av.CONVERSATION: 2,   # /issues/42 and /pull/7 of other repositories
        })

    def test_code_comments_gists_and_other_hosts_are_left_out(self):
        seen = " ".join(self.lines)
        for name in ("fenced-only", "tilde-fenced-only", "inline-code-only", "commented-out", "commented-block",
                     "raw-only", "pages-only", "image-only", "html-image", "6cad326836d38bd3a7ae"):
            self.assertNotIn(name, seen)


class Fences(unittest.TestCase):
    def test_fence_inside_a_list_item_and_longer_fences(self):
        text = ("- item\n"
                "    ```bash\n"
                "    git clone https://github.com/o/in-list-fence\n"
                "    ```\n"
                "````md\n"
                "```\n"
                "https://github.com/o/inner-fence-is-text\n"
                "````\n"
                "- [after](https://github.com/o/after)\n")
        self.assertEqual(repos(text), {"o/after": [9]})

    def test_tilde_fence_is_not_closed_by_backticks_and_unclosed_fence_runs_to_the_end(self):
        text = "~~~\n```\nhttps://github.com/o/a\n~~~\n[b](https://github.com/o/b)\n```\nhttps://github.com/o/c\n"
        self.assertEqual(repos(text), {"o/b": [5]})

    def test_triple_backticks_on_one_line_are_inline_code_not_a_fence(self):
        text = "```https://github.com/o/code```\n[x](https://github.com/o/x)\n"
        self.assertEqual(repos(text), {"o/x": [2]})


class Shapes(unittest.TestCase):
    def test_punctuation_suffixes_and_dot_names(self):
        text = ("See https://github.com/o/a. And (https://github.com/o/b). **https://github.com/o/c**\n"
                "https://github.com/o/d.git. https://github.com/o/.github https://github.com/o/e/ "
                "HTTPS://GITHUB.COM/o/f//github.com/o/g\n")
        self.assertEqual(sorted(repos(text)), ["o/.github", "o/a", "o/b", "o/c", "o/d", "o/e", "o/f"])

    def test_other_hosts_and_urls_nested_in_urls_are_not_repositories(self):
        text = ("https://web.archive.org/web/2020/https://github.com/o/archived-copy\n"
                "https://api.github.com/repos/o/api git@github.com:o/ssh.git https://notgithub.com/o/n\n"
                "https://github.com.evil.example/o/x mailto:user@github.com/o/y\n")
        self.assertEqual(repos(text), {})

    def test_multiple_files_keep_their_own_lines(self):
        entries, _ = av.collect([("a.md", "\n[x](https://github.com/o/r)\n"),
                                 ("b.md", "[x](https://github.com/O/R)\n")])
        self.assertEqual(entries, [{"repository": "o/r", "locations": [{"file": "a.md", "line": 2},
                                                                     {"file": "b.md", "line": 1}]}])


class Unicode(unittest.TestCase):
    def test_line_separators_inside_text_do_not_shift_line_numbers(self):
        # U+2028, form feed and NEL are line breaks to str.splitlines(), not to git or an editor
        text = "Café   naïve \x0c ok \x85\r\n「ツール」 [x](https://github.com/o/r) 🚀\r\n"
        self.assertEqual(repos(text), {"o/r": [2]})

    def test_byte_order_mark_and_invalid_utf8_do_not_stop_the_run(self):
        import io
        import tempfile
        from contextlib import redirect_stdout
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "liste.md"
            p.write_bytes(b"\xef\xbb\xbf[x](https://github.com/o/r)\n\xff\xfe caf\xe9\n[y](https://github.com/o/s)\n")
            out = io.StringIO()
            with redirect_stdout(out):
                code = av.main([str(p), "--json", "--source", "census", "--census", CENSUS])
        self.assertEqual(code, 0)
        self.assertIn('"line": 1', out.getvalue())
        self.assertIn('"line": 3', out.getvalue())


class Review(unittest.TestCase):
    """Regressions from the review of 2026-09-24; the number is the finding's."""

    def test_1_github_site_sections_and_the_mcp_registry(self):
        text = ("[server](https://github.com/mcp/github/github-mcp-server)\n"
                "https://github.com/mcp and https://github.com/mcp/github\n"
                "Sign up: https://github.com/github-copilot/signup\n"
                "https://github.com/models https://github.com/solutions/ci-cd https://github.com/why-github/x\n"
                "https://github.com/marketplace/models/azure-openai/gpt-4o https://github.com/premium-support/x\n"
                "https://github.com/c/x https://github.com/partners/x https://github.com/readme/stories/x\n"
                "[course](https://github.com/skills/introduction-to-github)\n")  # skills is an organisation
        self.assertEqual(repos(text), {"github/github-mcp-server": [1], "skills/introduction-to-github": [7]})

    def test_5_hostile_lines_scan_in_linear_time(self):
        import time
        for line in ("<img " * 20000, "![" * 20000, 'src="' * 20000, "<source srcset='" * 8000, "[" * 20000 + "]",
                     "![a][" * 20000, "` " * 20000, "<!--" * 20000, "github.com/" * 20000, "_https://github.com/" * 5000):
            start = time.perf_counter()
            av.scan(line)
            self.assertLess(time.perf_counter() - start, 2.0, line[:16])

    def test_6_unclosed_fence_in_a_list_item_ends_with_the_item(self):
        text = ("- [one](https://github.com/o/one)\n"
                "  ```bash\n"
                "  git clone https://github.com/o/in-code\n"
                "- [two](https://github.com/o/two)\n"
                "```\n"
                "https://github.com/o/top-level-code\n")
        warnings = []
        entries, _ = av.collect([("list.md", text)], None, warnings)
        self.assertEqual([e["repository"] for e in entries], ["o/one", "o/two"])
        self.assertEqual(warnings, [{"file": "list.md", "line": 5,
                                     "message": "a code fence opened here is never closed; nothing after it was read"}])

    def test_6_comments_end_at_the_first_close_even_inside_backticks(self):
        text = ("<!-- note: `-->`\n"
                "[a](https://github.com/o/a)\n"
                "<!-->\n"
                "[b](https://github.com/o/b)\n"
                "<!--->\n"
                "[c](https://github.com/o/c)\n"
                "`<!--` starts a comment; [d](https://github.com/o/d)\n"
                "<!-- never closed\n"
                "[e](https://github.com/o/e)\n")
        warnings = []
        entries, _ = av.collect([("list.md", text)], None, warnings)
        self.assertEqual([e["repository"] for e in entries], ["o/a", "o/b", "o/c", "o/d"])
        self.assertEqual(warnings, [{"file": "list.md", "line": 8,
                                     "message": "an HTML comment opened here is never closed; nothing after it was read"}])

    def test_6_reference_style_badges_are_images(self):
        text = ("[![CI][ci-badge]][ci-runs] [![Stars][stars]][repo]\n"
                "\n"
                "[ci-badge]: https://github.com/o/r/actions/workflows/ci.yml/badge.svg\n"
                "[ci-runs]: https://github.com/o/r/actions\n"
                "[stars]: https://img.shields.io/github/stars/o/r\n"
                "[repo]: https://github.com/o/r\n"
                "![logo][Logo  Ref]\n"
                "[logo ref]: <https://github.com/o/logo-only/raw/main/logo.png>\n")
        entries, ignored = av.collect([("list.md", text)])
        self.assertEqual({e["repository"]: [loc["line"] for loc in e["locations"]] for e in entries}, {"o/r": [4, 6]})
        self.assertEqual(ignored, {av.IMAGE_LINK: 2})

    def test_6_every_src_and_srcset_value_is_an_image_even_across_lines(self):
        text = ('<source srcset="https://github.com/o/a/raw/x.png 1x, https://github.com/o/b/raw/y.png 2x">\n'
                "<img\n"
                '  src="https://github.com/o/c/raw/main/logo.png"\n'
                '  alt="">\n'
                "<img src=https://github.com/o/d/raw/main/x.png>\n")
        entries, ignored = av.collect([("list.md", text)])
        self.assertEqual((entries, ignored), ([], {av.IMAGE_LINK: 4}))

    def test_6_emphasised_bare_urls(self):
        text = "_https://github.com/o/r_ and *https://github.com/o/s* and [t](https://github.com/o/t_)\n"
        self.assertEqual(repos(text), {"o/r": [1], "o/s": [1], "o/t_": [1]})

    def test_10_only_single_items_are_conversations(self):
        text = ("https://github.com/o/a/issues https://github.com/o/b/issues/42\n"
                "https://github.com/o/c/security https://github.com/o/d/security/advisories/GHSA-1234-5678-9abc\n"
                "https://github.com/o/e/pulls https://github.com/o/f/pull/7/files\n"
                "https://github.com/o/g/discussions https://github.com/o/h/discussions/5\n"
                "https://github.com/o/i/commits/main https://github.com/o/j/commit/1a2b3c4\n"
                "https://github.com/o/k/compare/v1...v2\n")
        self.assertEqual(sorted(repos(text)), ["o/a", "o/c", "o/e", "o/g", "o/i"])


if __name__ == "__main__":
    unittest.main()
