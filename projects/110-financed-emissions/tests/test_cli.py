"""The command line: exit codes, --strict, output formats, and the worked example end to end."""
import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import financed_emissions as fe  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
EXAMPLE = str(ROOT / "examples" / "portfolio.csv")


def cli(*args, stdin=None):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = fe.main(list(args))
    return code, out.getvalue(), err.getvalue()


class ExitCodes(unittest.TestCase):
    def test_clean_file(self):
        code, out, _ = cli(str(FIXTURES / "clean.csv"))
        self.assertEqual(code, 0)
        self.assertIn("Every position was computed", out)
        code, _, _ = cli(str(FIXTURES / "clean.csv"), "--strict")
        self.assertEqual(code, 0)

    def test_strict_exits_1_when_a_position_cannot_be_computed(self):
        code, out, _ = cli(str(FIXTURES / "one_failure.csv"))
        self.assertEqual(code, 0)
        code, out, _ = cli(str(FIXTURES / "one_failure.csv"), "--strict")
        self.assertEqual(code, 1)
        self.assertIn("P2", out)

    def test_strict_exits_1_on_a_flag(self):
        code, _, _ = cli(str(FIXTURES / "flag_only.csv"), "--strict")
        self.assertEqual(code, 1)

    def test_missing_file_is_2_not_empty(self):
        code, out, err = cli("/nonexistent/portfolio.csv", "--strict")
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("no such file", err)

    def test_unreadable_file_is_2(self):
        code, _, err = cli(str(FIXTURES / "clean.csv"), "--encoding", "no-such-codec")
        self.assertEqual(code, 2)
        self.assertIn("unknown encoding", err)

    def test_mixed_currencies_without_reporting_currency_is_2(self):
        code, _, err = cli(EXAMPLE)
        self.assertEqual(code, 2)
        self.assertIn("several currencies", err)

    def test_usage_errors(self):
        code, _, err = cli()
        self.assertEqual(code, 2)
        self.assertIn("give a portfolio CSV", err)
        code, _, err = cli("mcp", "extra")
        self.assertEqual(code, 2)
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                fe.main(["x.csv", "--json", "--markdown"])
        self.assertEqual(ctx.exception.code, 2)


class Outputs(unittest.TestCase):
    def test_json_is_valid_and_complete(self):
        code, out, _ = cli(EXAMPLE, "--currency", "EUR", "--json")
        self.assertEqual(code, 0)
        doc = json.loads(out)
        self.assertEqual(doc["method"]["edition"], "Third Edition")
        self.assertEqual(doc["positions_total"], 15)
        self.assertEqual(len(doc["not_computed"]), 2)
        self.assertAlmostEqual(doc["totals"]["financed_tco2e"]["scope1_2"], 50811.84498968, places=6)
        self.assertIn("arithmetic", doc["positions"][0])

    def test_markdown(self):
        code, out, _ = cli(EXAMPLE, "--currency", "EUR", "--markdown", "--explain")
        self.assertEqual(code, 0)
        self.assertIn("| Total | 15 (+1 not computed) | 209,755,000 | 50,811.84 |", out)
        self.assertIn("## Not computed (2)", out)
        self.assertIn("```", out)

    def test_explain_shows_numbers_substituted(self):
        code, out, _ = cli(EXAMPLE, "--currency", "EUR", "--explain")
        self.assertIn("= 12,000,000 / 4,800,000,000 = 0.0025", out)
        self.assertIn("financed scope 1 = 12,000,000 / 4,800,000,000 x 2,400,000 = 6,000.00 tCO2e [5.1, p. 44]", out)
        self.assertIn("= 5,000,000 / (0 + 25,000,000) = 0.2", out)
        self.assertIn("attribution factor = 1 (value at origination unknown", out)

    def test_every_formula_line_can_be_recomputed(self):
        # Each "a / b x c = d" line in --explain must hold when recomputed from the printed numbers.
        _, out, _ = cli(EXAMPLE, "--currency", "EUR", "--explain")
        pattern = re.compile(r"= ([\d,.]+) / ([\d,.]+) x ([\d,.]+) = ([\d,.]+) tCO2e")
        checked = 0
        for a, b, c, d in pattern.findall(out):
            n = [float(x.replace(",", "")) for x in (a, b, c, d)]
            self.assertAlmostEqual(n[0] / n[1] * n[2], n[3], delta=0.005 + 1e-9 * n[3])
            checked += 1
        self.assertGreater(checked, 25)

    def test_methods(self):
        code, out, _ = cli("--methods")
        self.assertEqual(code, 0)
        self.assertIn("sub_sovereign_debt", out)
        self.assertIn("capped at 1 (5.10, p. 154)", out)
        code, out, _ = cli("--methods", "--json")
        doc = json.loads(out)
        self.assertEqual(len(doc["asset_classes"]), 12)
        self.assertEqual({c["section"] for c in doc["asset_classes"]},
                         {"5.1", "5.2", "5.3", "5.4", "5.5", "5.6", "5.7", "5.8", "5.9", "5.10"})

    def test_version(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            with self.assertRaises(SystemExit):
                fe.main(["--version"])
        self.assertIn(fe.__version__, out.getvalue())


class Subprocess(unittest.TestCase):
    """The real entry point, as a user runs it, with HOME pointed away from the real one."""

    def run_cli(self, *args, stdin=None):
        with tempfile.TemporaryDirectory() as home:
            env = dict(os.environ, HOME=home, PYTHONIOENCODING="utf-8")
            return subprocess.run([sys.executable, str(ROOT / "financed_emissions.py"), *args], input=stdin,
                                  capture_output=True, cwd=str(ROOT), env=env, timeout=60)

    def test_example_end_to_end(self):
        proc = self.run_cli(EXAMPLE, "--currency", "EUR", "--strict")
        self.assertEqual(proc.returncode, 1)          # MG-02, DER-01 and the MG-03 flag
        text = proc.stdout.decode("utf-8")
        self.assertIn("Total", text)
        self.assertIn("50,811.84", text)

    def test_stdin(self):
        proc = self.run_cli("-", stdin=(FIXTURES / "clean.csv").read_bytes())
        self.assertEqual(proc.returncode, 0)
        self.assertIn(b"(stdin)", proc.stdout)


if __name__ == "__main__":
    unittest.main()
