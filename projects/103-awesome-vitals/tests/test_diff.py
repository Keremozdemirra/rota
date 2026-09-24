"""Pull-request mode: parsing `git diff --unified=0`, running git, --only-lines."""
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]
import awesome_vitals as av  # noqa: E402
from fakegithub import FIXTURES  # noqa: E402

# Recorded: `git diff --unified=0 b25b498...32c031a -- README.md` in the agent-vitals
# repository, the commit that replaced a code sample with a link to mcp-vitals.
REAL = (FIXTURES / "agent-vitals-32c031a.diff").read_text(encoding="utf-8")


class ParseDiff(unittest.TestCase):
    def test_real_git_diff(self):
        # Checked against `git show 32c031a:README.md`: line 18 is the added
        # [mcp-vitals](https://github.com/Keremozdemirra/mcp-vitals) link. The
        # hunk "@@ -227,2 +210,0 @@" only removes lines and adds none.
        self.assertEqual(av.parse_diff(REAL), {"README.md": {17, 18, 19, 20, 21, 22, 25, 26, 29, 206, 208, 288}})

    def test_removed_and_added_lines_that_look_like_file_headers(self):
        # Constructed: a removed "-- signature" line prints as "--- signature",
        # an added "++ note" as "+++ note". Only the hunk counts tell them apart.
        text = ("diff --git a/list.md b/list.md\n--- a/list.md\n+++ b/list.md\n"
                "@@ -4,2 +4,2 @@\n--- signature\n-old\n+++ note\n+new\n"
                "@@ -9,0 +10 @@\n+[x](https://github.com/o/r)\n")
        self.assertEqual(av.parse_diff(text), {"list.md": {4, 5, 10}})

    def test_new_deleted_and_quoted_unicode_paths(self):
        # Constructed in git's own format: a new file, a deleted file, and a path
        # git quotes with octal escapes when core.quotePath is on.
        text = ("diff --git a/new.md b/new.md\nnew file mode 100644\nindex 0000000..e69de29\n"
                "--- /dev/null\n+++ b/new.md\n@@ -0,0 +1,2 @@\n+one\n+two\n"
                "diff --git a/old.md b/old.md\ndeleted file mode 100644\n--- a/old.md\n+++ /dev/null\n"
                "@@ -1 +0,0 @@\n-gone\n"
                'diff --git "a/donn\\303\\251es.md" "b/donn\\303\\251es.md"\n'
                '--- "a/donn\\303\\251es.md"\n+++ "b/donn\\303\\251es.md"\n'
                "@@ -3 +3 @@\n-a\n\\ No newline at end of file\n+b\n\\ No newline at end of file\n")
        self.assertEqual(av.parse_diff(text), {"new.md": {1, 2}, "données.md": {3}})

    def test_empty_diff(self):
        self.assertEqual(av.parse_diff(""), {})


class RunGit(unittest.TestCase):
    def test_command_line_and_result(self):
        calls = []

        def run(cmd, **kw):
            calls.append((cmd, kw))
            return subprocess.CompletedProcess(cmd, 0, REAL.encode("utf-8"), b"")

        self.assertEqual(av.git_added_lines("origin/main...HEAD", ["README.md"], run)["README.md"],
                         {17, 18, 19, 20, 21, 22, 25, 26, 29, 206, 208, 288})
        self.assertEqual(calls[0][0], ["git", "-c", "core.quotePath=false", "diff", "--no-color", "--no-ext-diff",
                                       "--no-textconv", "--unified=0", "--src-prefix=a/", "--dst-prefix=b/",
                                       "--relative", "origin/main...HEAD", "--", "README.md"])
        self.assertEqual(calls[0][1]["timeout"], 120)

    def test_shallow_clone_error_says_what_to_do(self):
        def run(cmd, **kw):
            return subprocess.CompletedProcess(cmd, 128, b"", b"fatal: origin/main...HEAD: no merge base\n")
        with self.assertRaises(RuntimeError) as cm:
            av.git_added_lines("origin/main...HEAD", ["README.md"], run)
        self.assertIn("fetch-depth: 0", str(cm.exception))

    def test_git_missing(self):
        def run(cmd, **kw):
            raise FileNotFoundError("git")
        with self.assertRaises(RuntimeError) as cm:
            av.git_added_lines("a...b", ["README.md"], run)
        self.assertIn("git is not on PATH", str(cm.exception))

    def test_option_like_range_never_reaches_git(self):
        def run(cmd, **kw):
            raise AssertionError("git must not run")
        for bad in ("--output=/tmp/x", "-p", ""):
            with self.assertRaises(ValueError):
                av.git_added_lines(bad, ["README.md"], run)


class OnlyLines(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(av.parse_only_lines("README.md:10-12, docs/x.md:5,7-8"),
                         {"README.md": [range(10, 13)], "docs/x.md": [range(5, 6)], None: [range(7, 9)]})

    def test_rejects_what_it_cannot_read(self):
        for bad in ("README.md:12-10", "README.md:x", "README.md:", "README.md:1-2-3"):
            with self.assertRaises(ValueError):
                av.parse_only_lines(bad)

    def test_selection_limits_entries_and_counts(self):
        text = (FIXTURES / "sample.md").read_text(encoding="utf-8")
        added = av.parse_diff("diff --git a/sample.md b/sample.md\n--- a/sample.md\n+++ b/sample.md\n"
                              "@@ -10,0 +11 @@\n+x\n@@ -20,0 +21,3 @@\n+x\n+x\n+x\n@@ -27,0 +28,2 @@\n+x\n+x\n")
        entries, ignored = av.collect([("./sample.md", text)], added)
        self.assertEqual({e["repository"]: [loc["line"] for loc in e["locations"]] for e in entries},
                         {"octocat/archived-example": [11], "OCTOCAT/hello-world": [21, 23]})  # first spelling on those lines
        self.assertEqual(ignored, {av.PROFILE: 2, av.SITE_PAGE: 2})  # line 28: two profiles; 29: topics, sponsors


if __name__ == "__main__":
    unittest.main()
