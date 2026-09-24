"""The command line: output, exit codes (0 answered, 1 not answerable, 2 could not fetch or read)."""
from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys

from tests.support import ROOT, E, FakeWeb, Isolated, fixture


class Cli(Isolated):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = E.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_rate(self):
        code, out, err = self.run_cli("rate", "EUR", "10", "--date", "2026-08")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("EUR (Euro) 10-year spot rate, reference date 2026-08-31", out)
        self.assertIn("without VA  3.268 %    0.03268    RFR_spot_no_VA!C20", out)
        self.assertIn("with VA     3.408 %    0.03408    RFR_spot_with_VA!C20", out)
        self.assertIn("  VA           -           14 bp", out)
        self.assertIn("EIOPA_RFR_20260831.zip, retrieved", out)
        self.assertTrue(out.isascii())

    def test_rate_as_json(self):
        code, out, _ = self.run_cli("rate", "USD", "30", "--date", "2026-08-31", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["no_va"]["cell"], "RFR_spot_no_VA!AQ40")

    def test_not_answerable_exits_1(self):
        for argv in (("rate", "XYZ", "10", "--date", "2026-08"), ("rate", "EUR", "10", "--date", "2031-01"),
                     ("rate", "EUR", "10.5"), ("params", "EUR", "--date", "August")):
            code, out, err = self.run_cli(*argv)
            self.assertEqual(code, 1, argv)
            self.assertEqual(out, "")
            self.assertTrue(err.startswith("eiopa-rfr: "), err)

    def test_could_not_fetch_exits_2(self):
        self.use_web(FakeWeb({E.RFR_PAGE: E.FetchError("could not reach www.eiopa.europa.eu for EIOPA's RFR page: "
                                                       "timed out", network=True)}))
        code, out, err = self.run_cli("rate", "EUR", "10")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("could not reach", err)
        self.assertNotIn("Traceback", err)

    def test_offline_without_cache_exits_2(self):
        code, _, err = self.run_cli("curve", "EUR", "--offline")
        self.assertEqual(code, 2)
        self.assertIn("offline mode", err)
        self.assertEqual(self.web.calls, [])

    def test_compare(self):
        code, out, _ = self.run_cli("compare", "EUR", "10", "2026-07", "2026-08")
        self.assertEqual(code, 0)
        self.assertIn("without VA  3.159 % -> 3.268 %   change +10.9 bp", out)
        self.assertIn("with VA     3.289 % -> 3.408 %   change +11.9 bp", out)
        self.assertIn("va_bp: 13 -> 14", out)
        self.assertIn("EIOPA does not endorse this publication", out)
        self.assertEqual(out.count("Source: EIOPA - European Insurance and Occupational Pensions Authority"), 2)

    def test_curve_and_params(self):
        code, out, _ = self.run_cli("curve", "EUR", "--date", "2026-08", "--variant", "both")
        self.assertEqual(code, 0)
        self.assertIn("\n    150  0.03338     0.03364\n", out)  # with VA re-extrapolated, own alpha
        code, out, _ = self.run_cli("params", "all", "--date", "2026-08")
        self.assertEqual(code, 0)
        self.assertIn("CO    Colombia                 10    50    4.2  0.145783      35    n/a", out)

    def test_releases(self):
        code, out, _ = self.run_cli("releases")
        self.assertEqual(code, 0)
        self.assertIn("2026-08-31  August 2026      EIOPA_RFR_20260831.zip        2026-09-03  3.13 MB", out)
        self.assertIn("9 releases, 2015-12-31 to 2026-08-31", out)

    def test_import_then_offline_query(self):
        path = self.tmp / "July.zip"
        path.write_bytes(fixture("EIOPA_RFR_20260731.zip"))
        code, out, _ = self.run_cli("import", str(path))
        self.assertEqual(code, 0)
        self.assertIn("reference date 2026-07-31, 7 curves", out)
        code, out, _ = self.run_cli("rate", "EUR", "10", "--date", "2026-07", "--offline", "--json")
        self.assertEqual((code, json.loads(out)["no_va"]["rate"]), (0, 0.03159))
        code, out, _ = self.run_cli("cache", "--json")
        self.assertEqual(json.loads(out)["releases"], ["2026-07-31"])

    def test_import_of_a_broken_file_exits_2(self):
        path = self.tmp / "broken.zip"
        path.write_bytes(fixture("EIOPA_RFR_20260731.zip")[:3000])
        code, _, err = self.run_cli("import", str(path))
        self.assertEqual(code, 2)
        self.assertIn("not a readable zip", err)

    def test_no_command_prints_help(self):
        code, out, _ = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("usage: eiopa-rfr", out)

    def test_script_entry_point(self):
        proc = subprocess.run([sys.executable, str(ROOT / "eiopa_rfr.py"), "--version"], capture_output=True,
                              env=dict(os.environ), timeout=60)
        self.assertEqual(proc.stdout.decode().strip(), f"eiopa-rfr {E.__version__}")
