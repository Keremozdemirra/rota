"""The command line end to end: the sample list against the local API stand-in and the census fixture."""
import datetime as dt
import io
import json
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
from fakegithub import CENSUS, FIXTURES, TOKEN, FakeGitHub  # noqa: E402

TODAY = dt.date(2026, 9, 24)
SAMPLE = str(FIXTURES / "sample.md")


def run(args, server=None, env=None):
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.dict(os.environ, env or {}, clear=False), redirect_stdout(out), redirect_stderr(err):
        if env is None:
            os.environ.pop("GITHUB_TOKEN", None)
            os.environ.pop("GH_TOKEN", None)
        if "--census" not in args:
            args = args + ["--census", CENSUS]
        code = av.main(args, today=TODAY,
                       api=server.url if server else "http://127.0.0.1:9", proxies={})
    return code, out.getvalue(), err.getvalue()


def section(text, title):
    """The rows under one group heading of the text report."""
    lines = text.split("\n")
    start = lines.index(title) + 1
    rows = []
    for line in lines[start:]:
        if not line.startswith("  "):
            break
        rows.append(line)
    return rows


class FullReport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with FakeGitHub() as server:
            cls.code, cls.out, cls.err = run([SAMPLE], server)
            cls.requests = list(server.requests)

    def test_groups_rows_and_lines(self):
        out = self.out
        self.assertEqual(self.code, 0)  # without --strict
        self.assertEqual(len(section(out, "archived (1)")), 1)
        self.assertRegex(section(out, "archived (1)")[0], r"^  11 +octocat/archived-example +2026-09-01 +23d +MIT +GitHub API")
        self.assertIn("HTTP 404: deleted, or private", section(out, "gone (1)")[0])
        self.assertIn("now octocat/Hello-World", section(out, "renamed (1)")[0])
        abandoned = "\n".join(section(out, "abandoned (4)"))
        for row in ("10, 21, 23  octocat/Hello-World", "TransformerOptimus/SuperAGI", "lharries/whatsapp-mcp",
                    "octocat/renamed-example"):
            self.assertIn(row, abandoned)
        self.assertIn("census 2026-09-23", abandoned)
        self.assertIn("punkpeye/awesome-mcp-clients", section(out, "stale (2)")[1])
        self.assertEqual(len(section(out, "no licence file (2)")), 2)
        self.assertEqual(len(section(out, "non-standard licence (2)")), 2)
        unchecked = section(out, "not checked (2)")
        self.assertIn("GitHub API answered 403; not in the census", unchecked[0])
        self.assertEqual([r.split()[1] for r in unchecked], ["example-org/awesome-example", "octocat/reference-style"])

    def test_summary_and_sources(self):
        self.assertIn("17 links to 15 repositories", self.out)
        self.assertIn("15 repositories · 1 archived · 1 gone · 1 renamed · 4 abandoned · 2 stale · 2 no licence file"
                      " · 2 non-standard licence · 2 not checked · 2 with no finding", self.out)
        self.assertIn("Facts: 7 from the GitHub API, 6 from the agent-vitals census of 2026-09-23, 2 not checked.", self.out)
        self.assertIn("GitHub API answered 403 for 8 repositories.", self.out)
        self.assertIn("Not entries, not checked: 5 links to GitHub pages that are not repositories, 3 images, "
                      "3 links to profiles or organisations, 2 links to issues, pull requests, discussions or commits.",
                      self.out)

    def test_one_request_per_repository_plus_the_redirect(self):
        self.assertEqual(len(self.requests), 16)


class Formats(unittest.TestCase):
    def test_json_is_complete_and_never_contains_the_token(self):
        with FakeGitHub() as server:
            code, out, _ = run([SAMPLE, "--json"], server, env={"GITHUB_TOKEN": TOKEN})
            sent = {h.get("authorization") for _, h in server.requests}
        doc = json.loads(out)
        self.assertEqual(sent, {"Bearer " + TOKEN})
        self.assertNotIn(TOKEN, out)
        self.assertEqual((code, doc["summary"]["repositories"], doc["summary"]["links"]), (0, 15, 17))
        by = {r["repository"]: r for r in doc["repositories"]}
        self.assertEqual(by["octocat/renamed-example"]["renamed_to"], "octocat/Hello-World")
        self.assertEqual(by["n8n-io/n8n"]["locations"], [{"file": SAMPLE, "line": 19}])
        self.assertEqual((doc["github"]["state"], doc["census"]["date"]), ("ok", "2026-09-23"))
        self.assertIsNone(doc["fail_on"])

    def test_census_url_credentials_are_masked(self):
        url = "https://reader:s3cret-value@127.0.0.1:9/servers.json?sig=abc123"
        code, out, _ = run([SAMPLE, "--only-lines", "16", "--json", "--source", "census", "--census", url])
        self.assertNotIn("s3cret-value", out)
        self.assertNotIn("abc123", out)
        self.assertEqual(json.loads(out)["census"]["url"], "https://***@127.0.0.1:9/servers.json?***")
        # an error message that echoes the URL, as a proxy's might
        self.assertEqual(av.mask_text("Tunnel connection failed: reader:s3cret-value@127.0.0.1:9/x?sig=abc123 refused"),
                         "Tunnel connection failed: ***@127.0.0.1:9/x?*** refused")

    def test_markdown_escapes_file_names_and_links_repositories(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "liste|données.md"
            p.write_text("- [x](https://github.com/octocat/archived-example) <b>\n", encoding="utf-8")
            with FakeGitHub() as server:
                code, out, _ = run([str(p), "--markdown", "--strict"], server)
        self.assertEqual(code, 1)
        self.assertIn("liste\\|données.md", out)
        self.assertIn("#### Archived (1)", out)
        self.assertIn("| 1 | [octocat/archived-example](https://github.com/octocat/archived-example) | "
                      "2026-09-01 (23 days) | MIT | GitHub API |  |", out)
        self.assertIn("This check fails on an entry that is archived or gone, or one that could not be checked: "
                      "1 matched, 0 not checked.", out)


class ExitCodes(unittest.TestCase):
    def test_strict_and_fail_on(self):
        with FakeGitHub() as server:
            self.assertEqual(run([SAMPLE, "--strict"], server)[0], 1)                      # archived, gone
            self.assertEqual(run([SAMPLE, "--fail-on", "no-license"], server)[0], 1)       # alias, implies --strict
            self.assertEqual(run([SAMPLE, "--only-lines", "24", "--strict"], server)[0], 0)  # agent-vitals only
            self.assertEqual(run([SAMPLE, "--only-lines", "24", "--fail-on", ""], server)[0], 0)
            self.assertEqual(run([SAMPLE, "--fail-on", "none"], server)[0], 0)

    def test_could_not_check_is_exit_2_and_a_finding_wins(self):
        # line 48 is octocat/reference-style: refused by the API stand-in and not in the census
        with FakeGitHub() as server:
            self.assertEqual(run([SAMPLE, "--only-lines", "48", "--strict"], server)[0], 2)
            self.assertEqual(run([SAMPLE, "--only-lines", "48", "--strict", "--fail-on", "none"], server)[0], 2)
            self.assertEqual(run([SAMPLE, "--only-lines", "48"], server)[0], 0)          # no --strict: a report
            self.assertEqual(run([SAMPLE, "--only-lines", "11,48", "--strict"], server)[0], 1)  # archived wins
            code, out, _ = run([SAMPLE, "--only-lines", "48", "--strict"], server)
        self.assertIn("This check fails on an entry that is archived or gone, or one that could not be checked: "
                      "0 matched, 1 not checked.", out)

    def test_network_down_and_no_census_is_exit_2(self):
        code, out, _ = run([SAMPLE, "--only-lines", "16", "--strict", "--census", "/nonexistent/census.json"])
        self.assertEqual(code, 2)
        self.assertIn("GitHub API unreachable", out)

    def test_unknown_finding_is_a_usage_error(self):
        for bad in ("archived,deprecated", "unchecked"):
            with self.assertRaises(SystemExit) as cm, redirect_stderr(io.StringIO()):
                av.main([SAMPLE, "--fail-on", bad])
            self.assertEqual(cm.exception.code, 2)

    def test_missing_file(self):
        code, out, err = run(["/nonexistent/README.md"])
        self.assertEqual((code, out), (2, ""))
        self.assertIn("cannot read /nonexistent/README.md", err)

    def test_empty_list(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "empty.md"
            p.write_text("# Nothing linked yet\n\nSee https://github.com/octocat for the author.\n", encoding="utf-8")
            with FakeGitHub() as server:
                code, out, _ = run([str(p), "--strict"], server)
        self.assertEqual((code, server.requests), (0, []))
        self.assertIn("No links to GitHub repositories found.", out)
        self.assertIn("Not entries, not checked: 1 link to a profile or organisation.", out)


class PullRequestMode(unittest.TestCase):
    def test_diff_reports_only_added_lines(self):
        # Constructed diff: a pull request that adds lines 11 and 15 of the sample and edits line 40.
        diff = ("diff --git a/sample.md b/sample.md\n--- a/sample.md\n+++ b/sample.md\n"
                "@@ -10,0 +11 @@\n+x\n@@ -13,0 +15 @@\n+x\n@@ -38 +40 @@\n-y\n+y\n").encode()
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, diff, b"")

        with tempfile.TemporaryDirectory() as d:
            cwd = os.getcwd()
            try:
                os.chdir(d)
                Path("sample.md").write_bytes(Path(SAMPLE).read_bytes())
                with FakeGitHub() as server, mock.patch("awesome_vitals.subprocess.run", fake_run):
                    code, out, _ = run(["sample.md", "--diff", "origin/main...HEAD", "--markdown"], server)
                    asked = server.paths()
            finally:
                os.chdir(cwd)
        self.assertEqual(calls[0][-4:], ["--relative", "origin/main...HEAD", "--", "sample.md"])
        self.assertEqual(asked, ["/repos/octocat/archived-example", "/repos/octocat/gone-example"])
        self.assertIn("lines added in origin/main...HEAD", out)
        self.assertIn("2 links to 2 repositories", out)
        self.assertEqual(code, 0)

    def test_diff_that_adds_no_entry(self):
        def fake_run(cmd, **kw):
            return subprocess.CompletedProcess(cmd, 0, b"", b"")
        with FakeGitHub() as server, mock.patch("awesome_vitals.subprocess.run", fake_run):
            code, out, _ = run([SAMPLE, "--diff", "a...b", "--markdown", "--strict"], server)
        self.assertEqual((code, server.requests), (0, []))
        self.assertIn("No links to GitHub repositories on those lines.", out)

    def test_git_failure_is_reported(self):
        def fake_run(cmd, **kw):
            return subprocess.CompletedProcess(cmd, 128, b"", b"fatal: bad revision 'abc...HEAD'\n")
        with mock.patch("awesome_vitals.subprocess.run", fake_run):
            code, out, err = run([SAMPLE, "--diff", "abc...HEAD"])
        self.assertEqual((code, out), (2, ""))
        self.assertIn("fetch-depth: 0", err)

    def test_only_lines(self):
        with FakeGitHub() as server:
            code, out, _ = run([SAMPLE, "--only-lines", f"{SAMPLE}:16-18", "--json"], server)
        self.assertEqual([r["repository"] for r in json.loads(out)["repositories"]],
                         ["TransformerOptimus/SuperAGI", "lharries/whatsapp-mcp", "punkpeye/awesome-mcp-servers"])


if __name__ == "__main__":
    unittest.main()
