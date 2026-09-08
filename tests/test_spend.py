#!/usr/bin/env python3
"""Tests for spend.py's choice of transcript.

The tool's whole value is that a receipt's number belongs to the session that
wrote the receipt. On 2026-09-08 a lane reported 8,710k that belonged to another
session: the code warned on stderr and the caller was piping through tail. So
these cases are about refusing, not about arithmetic.
"""
import io
import json
import os
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import spend  # noqa: E402

HOUR = 3600


def write_transcript(root, name, calls=1, age_seconds=0):
    """A transcript with `calls` usage rows, last modified `age_seconds` ago."""
    path = os.path.join(root, name + ".jsonl")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8") as fh:
        for _ in range(calls):
            fh.write(json.dumps({"message": {"usage": {
                "input_tokens": 10, "cache_read_input_tokens": 100,
                "cache_creation_input_tokens": 5, "output_tokens": 2}}}) + "\n")
    stamp = time.time() - age_seconds
    os.utime(path, (stamp, stamp))
    return path


class ResolveTranscript(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_refuses_when_two_transcripts_are_fresh(self):
        a = write_transcript(self.root, "proj/aaaa", age_seconds=60)
        b = write_transcript(self.root, "proj/bbbb", age_seconds=120)
        with self.assertRaises(spend.Ambiguous) as caught:
            spend.resolve_transcript(root=self.root)
        self.assertEqual(sorted(caught.exception.candidates), sorted([a, b]))

    def test_session_passes_through_even_when_ambiguous(self):
        write_transcript(self.root, "proj/aaaa", age_seconds=60)
        mine = write_transcript(self.root, "proj/bbbb", age_seconds=120)
        self.assertEqual(spend.resolve_transcript(mine, root=self.root), mine)

    def test_one_fresh_transcript_is_unambiguous(self):
        mine = write_transcript(self.root, "proj/aaaa", age_seconds=60)
        write_transcript(self.root, "proj/bbbb", age_seconds=9 * HOUR)
        self.assertEqual(spend.resolve_transcript(root=self.root), mine)

    def test_falls_back_to_newest_when_nothing_is_fresh(self):
        write_transcript(self.root, "proj/old", age_seconds=20 * HOUR)
        newer = write_transcript(self.root, "proj/newer", age_seconds=8 * HOUR)
        self.assertEqual(spend.resolve_transcript(root=self.root), newer)

    def test_two_stale_transcripts_do_not_refuse(self):
        # Nothing has run for hours, so no live lane can be confused with another.
        write_transcript(self.root, "proj/a", age_seconds=7 * HOUR)
        write_transcript(self.root, "proj/b", age_seconds=8 * HOUR)
        self.assertIsNotNone(spend.resolve_transcript(root=self.root))

    def test_ignores_subagent_transcripts(self):
        mine = write_transcript(self.root, "proj/aaaa", age_seconds=60)
        write_transcript(self.root, "proj/subagents/bbbb", age_seconds=30)
        self.assertEqual(spend.resolve_transcript(root=self.root), mine)

    def test_no_transcripts_at_all(self):
        self.assertIsNone(spend.resolve_transcript(root=self.root))

    def test_the_window_edge_is_the_window(self):
        write_transcript(self.root, "proj/a", age_seconds=60)
        write_transcript(self.root, "proj/b", age_seconds=spend.FRESH_WINDOW + 60)
        self.assertIsNotNone(spend.resolve_transcript(root=self.root))


class MainExitCodes(unittest.TestCase):
    """The refusal has to reach a caller that reads stdout and the exit code."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self._projects = spend.PROJECTS
        spend.PROJECTS = self.root
        self._argv = sys.argv

    def tearDown(self):
        spend.PROJECTS = self._projects
        sys.argv = self._argv
        self.tmp.cleanup()

    def run_main(self, *args):
        sys.argv = ["spend"] + list(args)
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = spend.main()
        return code, buf.getvalue()

    def test_refusal_exits_2_and_names_candidates_on_stdout(self):
        write_transcript(self.root, "proj/aaaaaaaa", age_seconds=60)
        write_transcript(self.root, "proj/bbbbbbbb", age_seconds=120)
        code, out = self.run_main()
        self.assertEqual(code, 2)
        self.assertIn("refusing to guess", out)
        self.assertIn("aaaaaaaa", out)
        self.assertIn("bbbbbbbb", out)
        self.assertNotIn("receipt figure", out)

    def test_session_measures_and_exits_0(self):
        write_transcript(self.root, "proj/aaaaaaaa", calls=3, age_seconds=60)
        mine = write_transcript(self.root, "proj/bbbbbbbb", calls=4, age_seconds=120)
        code, out = self.run_main("--session", mine)
        self.assertEqual(code, 0)
        self.assertIn("receipt figure", out)
        self.assertIn("4 calls", out)

    def test_mark_also_refuses_when_ambiguous(self):
        # A mark taken from the wrong session poisons the later --from-call.
        write_transcript(self.root, "proj/aaaaaaaa", age_seconds=60)
        write_transcript(self.root, "proj/bbbbbbbb", age_seconds=120)
        code, out = self.run_main("--mark")
        self.assertEqual(code, 2)
        self.assertNotIn("mark:", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
