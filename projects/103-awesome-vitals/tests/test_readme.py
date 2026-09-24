"""The README says what the tool does, and its pull-request example is what the tool prints."""
import datetime as dt
import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]
import awesome_vitals as av  # noqa: E402
from fakegithub import CENSUS, FIXTURES, FakeGitHub  # noqa: E402

README = (HERE.parent / "README.md").read_text(encoding="utf-8")
FLAT = " ".join(README.split())


def code_block(first_line):
    """The fenced block of the README whose first line is `first_line`, without the fences."""
    lines = README.split("\n")
    start = lines.index(first_line)
    end = lines.index("```", start)
    return lines[start:end]


class Review(unittest.TestCase):
    """Regressions from the review of 2026-09-24; the number is the finding's."""

    def test_8_the_abandoned_count_says_what_it_counts(self):
        # 2,385 is the census's `abandoned`: not archived and no push in over a year
        self.assertIn("2,385 not archived and with no push in over a year", FLAT)
        self.assertNotIn("2,385 with no push in over a year", FLAT)

    def test_9_census_mode_sends_nothing_to_the_api_and_says_no_more(self):
        out = io.StringIO()
        with self.assertRaises(SystemExit), redirect_stdout(out):
            av.main(["--help"])
        help_text = " ".join(out.getvalue().split())
        for text in (FLAT, help_text):
            self.assertNotRegex(text, r"nothing (sent )?to GitHub(?! API)")
        self.assertIn("nothing to the GitHub API", FLAT)
        self.assertIn("nothing sent to the GitHub API", help_text)

    def test_10_the_pull_request_example_is_what_the_tool_prints(self):
        # The README example ran on the agent-vitals checkout. Here the same git diff,
        # recorded that day, is replayed into a file whose line 18 is the one it added.
        command = "$ awesome-vitals --markdown --diff b25b498...HEAD --fail-on archived,gone -- README.md"
        expected = code_block(command)[1:]
        diff = (FIXTURES / "agent-vitals-32c031a.diff").read_bytes()
        lines = [""] * 288
        lines[17] = "[mcp-vitals](https://github.com/Keremozdemirra/mcp-vitals) reads your client configs"

        def git(cmd, **kw):
            return subprocess.CompletedProcess(cmd, 0, diff, b"")

        out, cwd = io.StringIO(), os.getcwd()
        with tempfile.TemporaryDirectory() as d:
            Path(d, "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
            try:
                os.chdir(d)
                with FakeGitHub(routes={}) as server, mock.patch("awesome_vitals.subprocess.run", git), \
                        mock.patch.dict(os.environ, {}, clear=False), redirect_stdout(out), redirect_stderr(io.StringIO()):
                    os.environ.pop("GITHUB_TOKEN", None)
                    os.environ.pop("GH_TOKEN", None)
                    code = av.main(command.split()[2:] + ["--census", CENSUS], today=dt.date(2026, 9, 24),
                                   api=server.url, proxies={})
            finally:
                os.chdir(cwd)
        self.assertEqual(out.getvalue().rstrip("\n").split("\n"), expected)
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
