"""The eu-ets command line: output, exit codes, and errors without tracebacks."""
import contextlib
import io
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _support import PLACEHOLDERS, Isolated, Registry, build_fixture_db, eu_ets  # noqa: E402


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = eu_ets.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class CliTest(unittest.TestCase):
    def setUp(self):
        self.env = Isolated().__enter__()
        build_fixture_db(self.env.cache)

    def tearDown(self):
        self.env.__exit__()

    def test_exit_codes(self):
        self.assertEqual(run("search", "duisburg")[0], 0)
        self.assertEqual(run("search", "nothing like this")[0], 1)
        self.assertEqual(run("history", "69")[0], 1)  # ambiguous: candidates, not an answer
        self.assertEqual(run("history", "DE-69")[0], 0)
        self.assertEqual(run("lei", "549300QGIICV4ZFTKX83")[0], 1)
        code, out, err = run("top", "--country", "Atlantis")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("unknown country", err)
        self.assertNotIn("Traceback", err)

    def test_tables_carry_units_notes_and_the_source_line(self):
        code, out, _ = run("top", "--country", "DE", "--activity", "steel")
        self.assertEqual(code, 0)
        self.assertIn("Integriertes Hüttenwerk Duisburg", out)
        self.assertIn("verified t CO2e", out)
        self.assertTrue(out.rstrip().splitlines()[-1].startswith("Source: European Commission, EU ETS Union Registry, CC BY 4.0"))
        code, out, _ = run("lei", "529900FGOWZKLBZ81V67", "--detail", "--from", "2020")
        self.assertIn("Yearly totals over these installations (derived)", out)
        self.assertNotIn("2,020", out)  # years are not numbers to format

    def test_json_output(self):
        code, out, _ = run("history", "AT-14", "--json")
        data = json.loads(out)
        self.assertEqual((code, data["years_without_values"]), (0, [2008, 2009]))

    def test_no_personal_data_in_any_command(self):
        for argv in (["search", "", "--country", "DE"], ["history", "DE-223104"], ["lei", "529900FGOWZKLBZ81V67", "--detail"],
                     ["top", "--limit", "100"], ["top", "--activity", "50", "--year", "2024"], ["info"], ["info", "--json"]):
            _, out, err = run(*argv)
            for p in PLACEHOLDERS:
                self.assertNotIn(p, out + err, argv)

    def test_cache_dir_option(self):
        other = self.env.path / "other"
        build_fixture_db(other)
        code, out, _ = run("--cache-dir", str(other), "info", "--json")
        self.assertEqual(json.loads(out)["database"], str(other / eu_ets.DB_NAME))

    def test_refresh_errors_are_one_line(self):
        with Registry() as reg:
            reg.faults["listing"] = [("status", 404)]
            code, out, err = run("refresh", "--listing-url", reg.listing_url)
        self.assertEqual(code, 2)
        self.assertIn("eu-ets: the registry listing answered HTTP 404", err)
        self.assertNotIn("Traceback", err)

    def test_refresh_without_compliance(self):
        with Registry() as reg:
            code, out, err = run("refresh", "--listing-url", reg.listing_url, "--no-compliance")
        self.assertEqual(code, 0, err)
        self.assertIn("Snapshot 2026-09-24: 25 installations", out)
        self.assertFalse(any("compliance" in p for p, _ in reg.requests))

    def test_a_5000_digit_activity_is_a_usage_error(self):
        code, out, err = run("top", "--activity", "9" * 5000)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("activity codes have one to three digits", err)
        self.assertNotIn("Traceback", err)

    def test_no_data_at_all(self):
        os.environ["EU_ETS_CACHE_DIR"] = str(self.env.path / "empty")
        code, out, err = run("info")
        self.assertEqual(code, 2)
        self.assertIn("run `eu-ets refresh`", err)


if __name__ == "__main__":
    unittest.main()
