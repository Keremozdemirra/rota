"""The command line: tables carry the labels, exit codes say what happened, refresh is reproducible."""
import contextlib
import hashlib
import io
import json
import os
import unittest
from pathlib import Path
from unittest import mock

try:
    from . import ctfixtures as fx
except ImportError:
    import ctfixtures as fx

from climate_trace_mcp import cli
from climate_trace_mcp import provenance as prov


class CliTest(fx.HomeIsolated):
    def setUp(self):
        super().setUp()
        self.srv = fx.FixtureServer().__enter__()
        self.addCleanup(self.srv.__exit__, None, None, None)
        fx.standard_routes(self.srv)
        self.base = self.srv.base

    def run_cli(self, *argv, base=None):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, {"CLIMATE_TRACE_API_BASE": base or self.base}), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_search_table_carries_units_labels_and_attribution(self):
        code, out, _ = self.run_cli("search", "--country", "DE", "--subsector", "iron-and-steel", "--year", "2024", "--limit", "5")
        self.assertEqual(code, 0)
        self.assertIn("1566771         15,212,776  DEU      BF/BOF  ThyssenKrupp Steel Duisburg steel plant", out)
        self.assertIn("Emissions: t CO2e, co2e_100yr, 100-year GWP (IPCC AR6). Modelled estimates.", out)
        self.assertIn("Source dataset, iron-and-steel: Climate TRACE, subsector iron-and-steel (data leads named by the API: TransitionZero, Global Energy Monitor)", out)
        self.assertRegex(out, r"Source: Climate TRACE \(climatetrace.org\), CC BY 4.0, retrieved \d{4}-\d{2}-\d{2}\n$")
        self.assertIn("rounded to whole tonnes", out)

    def test_country_table_marks_external_datasets(self):
        code, out, _ = self.run_cli("country", "Poland", "--sector", "power", "--years", "2020-2024")
        self.assertEqual(code, 0)
        self.assertRegex(out, r"other-energy-use \*\s+2,196,115\s+2,566,423\s+2,540,194\s+2,065,718\s+1,922,606")
        self.assertIn("reproduced from EDGAR", out)
        self.assertIn("CC BY-NC-ND 4.0", out)

    def test_json_output(self):
        code, out, _ = self.run_cli("asset", "1566771", "--years", "2022-2024", "--json")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["estimate_type"], "modelled")
        self.assertEqual(len(data["emissions"]), 3)

    def test_owners_text(self):
        self.srv.route("/sources/1566771", fx.fixture("source_1566771_2022-2024.json"))
        code, out, _ = self.run_cli("owners", "1566771")
        self.assertEqual(code, 0)
        self.assertIn("Thyssenkrupp Steel Europe AG (Climate TRACE owner id E100001000542; LEI: none returned by the API)", out)

    def test_sources_and_sectors_text(self):
        code, out, _ = self.run_cli("sources")
        self.assertEqual(code, 0)
        self.assertIn("IEA-EDGAR CO2", out)
        self.assertIn("What this is not:", out)
        code, out, _ = self.run_cli("sectors")
        self.assertEqual(code, 0)
        self.assertRegex(out, r"other-energy-use\s+country only\s+no data lead named\s+external \(terms\): EDGAR")

    def test_exit_codes(self):
        code, _, err = self.run_cli("country", "Atlantis")
        self.assertEqual(code, 1)
        self.assertIn("unknown country", err)
        code, _, err = self.run_cli("asset", "999999999", "--years", "2024")
        self.assertEqual(code, 1)
        self.assertIn("ID not found", err)
        code, _, err = self.run_cli("asset", "1566771", "--years", "2024", base=fx.closed_port_base())
        self.assertEqual(code, 2)
        self.assertIn("Could not reach", err)
        self.srv.route("/sources/1566771", fx.Reply(b"{not json"))
        code, _, err = self.run_cli("asset", "1566771", "--years", "2024")
        self.assertEqual(code, 2)
        code, _, err = self.run_cli("search", "--year", "2024", base="http://example.org/v7")
        self.assertEqual(code, 2)
        self.assertIn("https://", err)

    def test_refresh_writes_a_reproducible_snapshot(self):
        self.srv.route("/definitions/subsectors", fx.Reply(["other-energy-use", "iron-and-steel", "cropland-fires"]))
        for s in ("iron-and-steel", "cropland-fires", "other-energy-use"):
            self.srv.route("/definitions/subsectors/" + s, fx.fixture("definitions_subsector_%s.json" % s))
        target = Path(self.home) / "subsectors.json"
        hashes = []
        with mock.patch.object(prov.time, "sleep"):
            for _ in range(2):
                code, out, _ = self.run_cli("refresh", "--out", str(target))
                self.assertEqual(code, 0)
                info = json.loads(out)
                self.assertEqual(info["sha256"], hashlib.sha256(target.read_bytes()).hexdigest())
                hashes.append(info["sha256"])
        self.assertEqual(hashes[0], hashes[1])
        snap = prov.Snapshot.load(target)
        self.assertEqual(sorted(snap.subsectors), ["cropland-fires", "iron-and-steel", "other-energy-use"])
        self.assertEqual(snap.api_version, "7.2.0")
        self.assertEqual([lead["name"] for lead in snap.data_leads("cropland-fires")], ["EDGAR"])

    def test_refresh_refuses_bad_names_and_writes_nothing(self):
        self.srv.route("/definitions/subsectors", fx.Reply(["iron-and-steel", "../../etc"]))
        target = Path(self.home) / "subsectors.json"
        code, _, err = self.run_cli("refresh", "--out", str(target))
        self.assertEqual(code, 2)
        self.assertFalse(target.exists())
        self.assertTrue(all("etc" not in p for p in self.srv.paths()))

    def test_no_arguments_on_a_terminal_prints_help(self):
        with mock.patch("sys.stdin") as stdin:
            stdin.isatty.return_value = True
            code, out, _ = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("usage: climate-trace-mcp", out)


if __name__ == "__main__":
    unittest.main()
