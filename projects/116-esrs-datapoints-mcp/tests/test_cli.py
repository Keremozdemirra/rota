"""The command line: output, JSON, exit codes."""
import contextlib
import io
import json

from support import CLEAN, IG3, MAPPING, Isolated

from esrs_datapoints_mcp.cli import main
from esrs_datapoints_mcp.text import WRAP_CLOSE, WRAP_OPEN


class Cli(Isolated):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--cache-dir", str(self.cache), *argv])
        return code, out.getvalue(), err.getvalue()

    def test_index_then_query(self):
        code, out, _ = self.run_cli("index", str(IG3), str(MAPPING))
        self.assertEqual(code, 0)
        self.assertIn("indexed ig3: 17 datapoints", out)
        code, out, _ = self.run_cli("search", "scope 3", "--standard", "E1")
        self.assertEqual(code, 0)
        self.assertIn("3 match(es)", out)
        self.assertIn(WRAP_OPEN.rstrip(), out)
        self.assertIn(WRAP_CLOSE, out)
        self.assertIn("Binding text: Commission Delegated Regulation (EU) 2023/2772", out)
        code, out, _ = self.run_cli("search", "scope", "--voluntary", "--json")
        data = json.loads(out)
        self.assertEqual([d["id"] for d in data["datapoints"]], ["E1-6_03"])
        self.assertEqual(self.run_cli("datapoint", "E1-6_02")[0], 0)
        self.assertEqual(self.run_cli("dr", "E1-6")[0], 0)
        code, out, _ = self.run_cli("diff", "E1")
        self.assertEqual(code, 0)
        self.assertIn("efrag_mapping", out)
        self.assertEqual(self.run_cli("status")[0], 0)

    def test_exit_codes(self):
        self.run_cli("index", str(IG3))
        self.assertEqual(self.run_cli("search", "nothing-like-this-anywhere")[0], 1)
        self.assertEqual(self.run_cli("datapoint", "E9-9_99")[0], 1)
        self.assertEqual(self.run_cli("dr", "E9-9")[0], 1)
        code, _, err = self.run_cli("diff", "E1")
        self.assertEqual(code, 2)
        self.assertIn("two indexed versions", err)
        code, _, err = self.run_cli("search", "x", "--limit", "0")
        self.assertEqual(code, 2)
        self.assertEqual(self.run_cli("forget", "not-a-key")[0], 1)
        self.assertEqual(self.run_cli("forget", "--all")[0], 0)
        self.assertEqual(self.run_cli("status")[0], 2)

    def test_index_missing_or_broken_file_is_an_error_not_silence(self):
        code, _, err = self.run_cli("index", str(self.tmp / "typo.xlsx"))
        self.assertEqual(code, 2)
        self.assertIn("No file at", err)
        self.assertIn("efrag.org", err)
        code, _, err = self.run_cli("search", "scope")
        self.assertEqual(code, 2)
        self.assertIn("No ESRS datapoint workbook is indexed", err)

    def test_sources_needs_no_index(self):
        code, out, _ = self.run_cli("sources")
        self.assertEqual(code, 0)
        self.assertIn("efrag.org/en/disclaimer", out)
        self.assertIn("2026/1563", out)

    def test_both_2026_variants_and_version_selection(self):
        self.run_cli("index", str(IG3), str(CLEAN), str(MAPPING))
        code, out, _ = self.run_cli("search", "placeholder", "--in", "revised-2030-01-01-clean", "--json")
        self.assertEqual({d["version"] for d in json.loads(out)["datapoints"]}, {"revised-2030-01-01-clean"})
        code, out, _ = self.run_cli("diff", "E1", "--to", "revised-2030-01-01-clean", "--min-similarity", "0.95",
                                    "--json")
        self.assertEqual(json.loads(out)["to_version"], "revised-2030-01-01-clean")
