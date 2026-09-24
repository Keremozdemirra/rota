"""The command line on the fixture data: output, JSON mode, exit codes."""
import contextlib
import io
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cbam_test_support import DataEnv  # noqa: E402
from cbam_mcp import main as cli  # noqa: E402


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class Cli(unittest.TestCase):
    def setUp(self):
        self.env = DataEnv()
        self.env.__enter__()

    def tearDown(self):
        self.env.__exit__()

    def test_scope_text(self):
        code, out, _ = run("scope", "7208", "51", "20")
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("7208 51 20: in scope"))
        self.assertIn("Legally binding   no.", out)
        self.assertIn("Source: EUR-Lex/CELLAR", out)

    def test_value_json(self):
        code, out, _ = run("value", "7601", "10", "00", "India", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["lines"][0]["total"], 1.87)

    def test_multi_word_country_and_compare(self):
        code, out, _ = run("value", "2804", "10", "00", "Other", "countries")
        self.assertEqual(code, 0)
        self.assertIn("from Other Countries and Territories", out)
        # Review finding 6: one argument is one country, commas included.
        code, out, _ = run("compare", "2523", "29", "00", "Congo, Democratic Republic of", "Congo", "--json")
        self.assertEqual(code, 0)
        rows = json.loads(out)["lines"][0]["by_country"]
        self.assertEqual([(r["country"], r["total"]) for r in rows], [("Congo, Democratic Republic of", 1.25), ("Congo", 0.93)])

    def test_corrupted_data_exits_2_without_traceback(self):
        import tempfile
        from cbam_test_support import shared_data_dir
        d = Path(tempfile.mkdtemp())
        for f in shared_data_dir().iterdir():
            (d / f.name).write_bytes(f.read_bytes())
        broken = json.loads((d / "default_values.json").read_text(encoding="utf-8"))
        broken["lines"] = [["7601"]]  # a row too short: parses as JSON, not as this tool's table
        (d / "default_values.json").write_text(json.dumps(broken), encoding="utf-8")
        (d / "annex_i.json").write_text(json.dumps({"meta": {}, "annex_i": "not a list"}), encoding="utf-8")
        with DataEnv(d):
            for argv in (("value", "7601", "India"), ("scope", "7208")):
                code, out, err = run(*argv)
                self.assertEqual(code, 2, argv)
                self.assertNotIn("Traceback", err)

    def test_sources_labels_and_no_local_path(self):
        code, out, _ = run("sources")
        self.assertEqual(code, 0)
        self.assertNotIn("Acts on 3", out)
        self.assertIn("Data directory: CBAM_MCP_DATA_DIR", out)
        self.assertNotIn(str(Path.cwd()), out)

    def test_describe_and_sources(self):
        self.assertIn("Electrical energy", run("describe", "2716", "00", "00")[1])
        self.assertIn("CN 2025", run("describe", "7308", "20", "00", "--year", "2025")[1])
        code, out, _ = run("sources")
        self.assertEqual(code, 0)
        self.assertIn("SHA-256", out)

    def test_errors_exit_2(self):
        for argv in (("value", "7601"), ("value", "India"), ("scope", "72x8"), ("compare", "7601"),
                     ("value", "7601", "Indai")):
            code, out, err = run(*argv)
            self.assertEqual(code, 2, argv)
            self.assertTrue(err.startswith("cbam-mcp: "), argv)

    def test_split_code(self):
        self.assertEqual(cli.split_code(["ex", "2507", "00", "80", "China"]), ("ex 2507 00 80", ["China"]))
        self.assertEqual(cli.split_code(["7601.10.00", "United", "States"]), ("7601.10.00", ["United", "States"]))


if __name__ == "__main__":
    unittest.main()
