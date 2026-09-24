"""Which lines changed: parsing recorded `git diff --unified=0` output, and asking a real git."""
import argparse
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import FIXTURES, Isolated  # noqa: E402

import diff_mutants as dm  # noqa: E402


def read_fixture(name: str) -> str:
    return (FIXTURES / name).read_bytes().decode("utf-8", "surrogateescape")


class ParseRecorded(unittest.TestCase):
    def setUp(self):
        self.files = dm.parse_diff(read_fixture("git-diff-change.diff"))

    def lines(self, path):
        return sorted(self.files[path]["lines"])

    def test_modified_file_new_side_lines_only(self):
        # @@ -6,3 +6,2 @@ and @@ -12,0 +12,4 @@
        self.assertEqual(self.lines("mod.py"), [6, 7, 12, 13, 14, 15])

    def test_new_file_and_rename(self):
        self.assertEqual(self.lines("fresh.py"), [1, 2])
        self.assertEqual(self.lines("after_rename.py"), [1])
        self.assertNotIn("before_rename.py", self.files)

    def test_deleted_binary_and_mode_only_files_are_absent(self):
        for path in ("gone.py", "blob.bin", "script.py"):
            self.assertNotIn(path, self.files)

    def test_added_lines_that_look_like_headers_are_content(self):
        # `+++y`, `++++ b/fake.py`, `+@@ -1 +1 @@` and `+diff --git a/x b/x` are four added lines of plus.py
        self.assertEqual(self.lines("plus.py"), [2, 3, 4, 5])
        self.assertNotIn("fake.py", self.files)
        self.assertNotIn("x", self.files)

    def test_quoted_and_odd_paths(self):
        self.assertEqual(self.lines('quo"te.py'), [1])
        self.assertEqual(self.lines("tab\\there.py"), [1])      # a backslash in the name
        self.assertEqual(self.lines("with space.py"), [1])        # git appends a TAB after it
        self.assertEqual(self.lines("pakete/größe.py"), [1])      # raw UTF-8 with core.quotepath=off

    def test_no_newline_marker_and_other_suffixes(self):
        self.assertEqual(self.lines("nonl.py"), [1])
        self.assertEqual(self.lines("notes.txt"), [2])  # parsed; filtered to .py later

    def test_symlink_mode_is_kept(self):
        self.assertEqual(self.files["link.py"]["mode"], "120000")
        self.assertEqual(self.files["mod.py"]["mode"], "100644")

    def test_names_that_are_not_utf8_or_hold_a_tab(self):
        files = dm.parse_diff(read_fixture("git-diff-names.diff"))
        self.assertEqual(sorted(files["real\ttab.py"]["lines"]), [2])
        latin = "caf\udce9.py"  # byte 0xE9 kept by surrogateescape, as os.fsdecode would
        self.assertEqual(sorted(files[latin]["lines"]), [2])

    def test_empty_and_garbage_input(self):
        self.assertEqual(dm.parse_diff(""), {})
        self.assertEqual(dm.parse_diff("not a diff\n@@ nonsense @@\n+++ b/x.py\n"), {})


class Unquote(unittest.TestCase):
    def test_plain_path_is_unchanged(self):
        self.assertEqual(dm.unquote_path("a/b.py"), "a/b.py")

    def test_c_escapes_and_octal_bytes(self):
        self.assertEqual(dm.unquote_path('"b/a\\tb\\"c\\\\d.py"'), 'b/a\tb"c\\d.py')
        self.assertEqual(dm.unquote_path('"b/gr\\303\\266\\303\\237e.py"'), "b/größe.py")
        self.assertEqual(dm.unquote_path('"b/caf\\351.py"'), "b/caf\udce9.py")


class TestPaths(unittest.TestCase):
    def test_test_code_is_recognised(self):
        for path in ("tests/test_x.py", "test/helpers.py", "pkg/tests/data/util.py", "test_x.py", "x_test.py",
                     "conftest.py", "src/pkg/conftest.py"):
            self.assertTrue(dm.is_test_path(path), path)

    def test_source_code_is_not(self):
        for path in ("calc.py", "src/pkg/testing.py", "contest.py", "attest.py", "tests.py", "src/latest/x.py"):
            self.assertFalse(dm.is_test_path(path), path)

    def test_unsafe_paths(self):
        for path in ("../x.py", "/etc/x.py", "a/../../x.py", "", "a\x00.py"):
            self.assertFalse(dm.safe_rel(path), path)
        self.assertTrue(dm.safe_rel("a/b.py"))


def args(**kw):
    ns = argparse.Namespace(staged=False, base=None, exclude=[])
    for k, v in kw.items():
        setattr(ns, k, v)
    return ns


class RealGit(Isolated):
    def test_base_mode_reads_head_blobs_and_lines(self):
        repo = self.repo({"a.py": "x = 1\n", "tests/test_a.py": "def test_a():\n    assert True\n"})
        self.commit(repo, {"a.py": "x = 1\ny = 2\n", "tests/test_a.py": "def test_a():\n    assert 1\n"})
        p = dm.plan(repo, args(base="HEAD~1"))
        self.assertEqual(p["sources"]["a.py"][1], {2})
        self.assertEqual(p["tests"]["tests/test_a.py"][1], {2})
        self.assertEqual(p["report"]["compared"]["mode"], "base")

    def test_three_dot_semantics_ignore_what_the_base_did_since(self):
        repo = self.repo({"a.py": "x = 1\n", "b.py": "y = 1\n"})
        self.git(repo, "checkout", "-q", "-b", "feature")
        self.commit(repo, {"a.py": "x = 1\nx2 = 2\n"})
        self.git(repo, "checkout", "-q", "main")
        self.commit(repo, {"b.py": "y = 1\ny2 = 2\n"})
        self.git(repo, "checkout", "-q", "feature")
        p = dm.plan(repo, args(base="main"))
        self.assertEqual(set(p["sources"]), {"a.py"})

    def test_default_base_is_main(self):
        repo = self.repo({"a.py": "x = 1\n"})
        self.git(repo, "checkout", "-q", "-b", "feature")
        self.commit(repo, {"a.py": "x = 2\n"})
        p = dm.plan(repo, args())
        self.assertEqual(p["report"]["compared"]["base"], "main")
        self.assertEqual(p["sources"]["a.py"][1], {1})

    def test_no_default_base(self):
        repo = self.repo({"a.py": "x = 1\n"})
        self.git(repo, "branch", "-m", "trunk")
        with self.assertRaisesRegex(dm.Stop, "no base to compare with"):
            dm.plan(repo, args())

    def test_on_the_base_itself_there_is_nothing_to_compare(self):
        repo = self.repo({"a.py": "x = 1\n"})
        p = dm.plan(repo, args(base="main"))
        self.assertEqual(p["sources"], {})
        self.assertIn("--base HEAD~1", " ".join(p["report"]["notes"]))

    def test_bad_base_values(self):
        repo = self.repo({"a.py": "x = 1\n"})
        for bad in ("-p", "--output=/tmp/x", "nope", "a b", ""):
            with self.assertRaises(dm.Stop, msg=bad):
                dm.plan(repo, args(base=bad))

    def test_staged_mode_uses_the_index_not_the_working_tree(self):
        repo = self.repo({"a.py": "x = 1\n"})
        self.write(repo, {"a.py": "x = 1\ny = 2\n"})
        self.git(repo, "add", "a.py")
        self.write(repo, {"a.py": "x = 1\ny = 2\nz = 3\n"})  # unstaged on top
        p = dm.plan(repo, args(staged=True))
        data, lines = p["sources"]["a.py"]
        self.assertEqual((data, lines), (b"x = 1\ny = 2\n", {2}))
        self.assertIn("the working tree differs from the index", " ".join(p["report"]["notes"]))

    def test_staged_in_a_repository_without_commits(self):
        root = self.tmp / "fresh"
        root.mkdir()
        self.git(root, "init", "-q", "-b", "main")
        self.write(root, {"a.py": "x = 1\n"})
        self.git(root, "add", "a.py")
        p = dm.plan(root, args(staged=True))
        self.assertEqual(p["sources"]["a.py"][1], {1})
        with self.assertRaisesRegex(dm.Stop, "no commit yet"):
            dm.plan(root, args(base="main"))

    def test_only_python_and_not_excluded(self):
        repo = self.repo({"a.py": "x = 1\n", "notes.md": "a\n", "scripts/tool.py": "y = 1\n"})
        self.commit(repo, {"a.py": "x = 2\n", "notes.md": "b\n", "scripts/tool.py": "y = 2\n"})
        p = dm.plan(repo, args(base="HEAD~1", exclude=["scripts/*"]))
        self.assertEqual(set(p["sources"]), {"a.py"})

    def test_deleted_file_and_symlink_are_skipped(self):
        repo = self.repo({"a.py": "x = 1\n", "b.py": "y = 1\n"})
        (repo / "b.py").unlink()
        (repo / "link.py").symlink_to("a.py")
        self.git(repo, "add", "-A")
        self.git(repo, "commit", "-q", "-m", "c")
        p = dm.plan(repo, args(base="HEAD~1"))
        self.assertEqual(p["sources"], {})
        self.assertIn("link.py is a symbolic link", " ".join(p["report"]["notes"]))

    def test_odd_file_names_end_to_end(self):
        names = ["with space.py", "tab\there.py", 'quo"te.py', "größe.py"]
        repo = self.repo({n: "x = 1\n" for n in names})
        self.commit(repo, {n: "x = 1\ny = 2\n" for n in names})
        p = dm.plan(repo, args(base="HEAD~1"))
        self.assertEqual(sorted(p["sources"]), sorted(names))
        for n in names:
            self.assertEqual(p["sources"][n], (b"x = 1\ny = 2\n", {2}))

    def test_not_a_repository(self):
        plain = self.tmp / "plain"
        plain.mkdir()
        with self.assertRaisesRegex(dm.Stop, "not inside a git working tree"):
            dm.toplevel(plain)
        with self.assertRaisesRegex(dm.Stop, "no such directory"):
            dm.toplevel(self.tmp / "missing")

    def test_git_missing(self):
        from unittest import mock
        with mock.patch("subprocess.run", side_effect=FileNotFoundError("git")):
            with self.assertRaisesRegex(dm.Stop, "git is not installed"):
                dm.git(self.tmp, "status")

    def test_git_timeout(self):
        import subprocess
        from unittest import mock
        with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 1)):
            with self.assertRaisesRegex(dm.Stop, "did not finish"):
                dm.git(self.tmp, "-c", "x=y", "diff")


if __name__ == "__main__":
    unittest.main()
