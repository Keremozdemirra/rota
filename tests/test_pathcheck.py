#!/usr/bin/env python3
"""Tests for pathcheck.py. Each case is one thing the checker must not get wrong."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import pathcheck  # noqa: E402

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "pathcheck", "sample.md")


class PathCheck(unittest.TestCase):
    def setUp(self):
        self.rows = list(pathcheck.check_file(FIX))
        self.cited = {p for _, p, _ in self.rows}

    def test_finds_the_missing_paths(self):
        self.assertIn("~/definitely/not/here.md", self.cited)
        self.assertIn("~/also/not/here.md", self.cited)

    def test_does_not_flag_a_path_that_exists(self):
        self.assertNotIn("~/agents/rota/tools/pathcheck.py", self.cited)

    def test_strips_trailing_prose_punctuation(self):
        # A trailing period must not turn a real path into a missing one.
        self.assertFalse(any(p.endswith("..") or p.endswith(".py.") for p in self.cited))

    def test_reports_a_dangling_symlink(self):
        hits = [r for r in self.rows if r[1].endswith("dangling-link")]
        self.assertEqual(len(hits), 1)
        self.assertIn("dangling symlink", hits[0][2])

    def test_glob_with_a_real_parent_passes(self):
        self.assertNotIn("~/agents/rota/tools/*.py", self.cited)

    def test_glob_with_a_missing_parent_fails(self):
        self.assertIn("~/nowhere/at/all/*.py", self.cited)

    def test_ignores_urls_and_bare_fractions(self):
        for p in self.cited:
            self.assertFalse(p.startswith("http"))
            self.assertNotEqual(p, "3/4")

    def test_placeholder_templates_are_not_claims(self):
        # <title>.md and {a,b} describe where a class of file lives. There is
        # nothing on disk for them to match, so flagging them is noise that
        # buries the real breaks.
        for p in self.cited:
            self.assertNotIn("<", p)
            self.assertNotIn("{", p)

    def test_unreadable_file_is_reported_not_swallowed(self):
        rows = list(pathcheck.check_file("/no/such/file/anywhere.md"))
        self.assertEqual(len(rows), 1)
        self.assertIn("unreadable", rows[0][2])


if __name__ == "__main__":
    unittest.main(verbosity=2)
