"""The command line: exit codes, text and JSON output, and no tracebacks on bad input."""
import contextlib
import io
import json
import os
import tempfile
import unittest
import urllib.error

from support import ROOT, Isolated, fixture, sparql_router

import csrd_scope

EXAMPLES = ROOT / "examples"


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = csrd_scope.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class Cli(Isolated):
    def test_check_examples(self):
        expected = {"fictional-eu-manufacturer.json": "first reporting financial year FY2027",
                    "fictional-listed-wave1.json": "FY2025-FY2026: depends",
                    "fictional-non-eu-group.json": "first reporting financial year FY2028"}
        for name, fragment in expected.items():
            with self.subTest(name):
                code, out, err = run("check", "--input", str(EXAMPLES / name))
                self.assertEqual(code, 0, err)
                self.assertIn(fragment, out)
                self.assertIn("CC BY 4.0", out)
                self.assertIn("Not legal advice", out)

    def test_check_json(self):
        code, out, _ = run("check", "--input", str(EXAMPLES / "fictional-eu-manufacturer.json"), "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["in_scope"], "yes")

    def test_check_from_flags(self):
        code, out, err = run("check", "--eu", "--legal-form", "yes", "--member-state", "FR",
                             "--fy", "2026,net_turnover_eur=480_000_000,average_employees=1200",
                             "--fy", "2027,net_turnover_eur=480000000,average_employees=1200", "--json")
        self.assertEqual(code, 0, err)
        res = json.loads(out)
        self.assertEqual(res["first_reporting_financial_year"]["financial_year"], "FY2027")
        code, out, err = run("check", "--non-eu", "--fy", "2026,eu_net_turnover_eur=600000000",
                             "--fy", "2027,eu_net_turnover_eur=600000000", "--eu-subsidiary", "2027:Beta GmbH=300000000",
                             "--eu-subsidiary", "2026:Beta GmbH=300000000", "--json")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["first_reporting_financial_year"]["financial_year"], "FY2028")

    def test_bad_input_exits_2_with_a_message(self):
        cases = [
            ("check", "--input", str(ROOT / "no-such-file.json")),
            ("check", "--eu", "--fy", "2027,net_turnover_eur=450m"),
            ("check", "--eu", "--fy", "twenty"),
            ("check", "--eu", "--fy", "2027,colour=blue"),
            ("check", "--non-eu", "--eu-subsidiary", "Beta=3"),
            ("check", "--fy", "2027,net_turnover_eur=1"),
            ("sources", "--member-state", "XX"),
        ]
        for argv in cases:
            with self.subTest(argv=argv):
                code, out, err = run(*argv)
                self.assertEqual(code, 2)
                self.assertNotIn("Traceback", err)
                self.assertTrue(err.strip())

    def test_input_files_that_are_not_an_undertaking(self):
        p = ROOT / "tests" / "fixtures" / "sparql-acts.json"
        code, _, err = run("check", "--input", str(p))
        self.assertEqual(code, 2)
        self.assertIn("unknown field(s): head, results", err)
        for content, fragment in (("[1, 2]", "JSON object"), ("{not json", "not valid JSON"), ("", "not valid JSON")):
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, dir=os.environ["HOME"]) as f:
                f.write(content)
            code, _, err = run("check", "--input", f.name)
            self.assertEqual(code, 2)
            self.assertIn(fragment, err)
        with tempfile.NamedTemporaryFile("wb", suffix=".json", delete=False, dir=os.environ["HOME"]) as f:
            f.write(b"\xff\xfe{")
        code, _, err = run("check", "--input", f.name)
        self.assertEqual(code, 2)
        self.assertIn("cannot read", err)

    def test_reference_commands(self):
        for argv in (("thresholds",), ("timeline",), ("sources",), ("sources", "--member-state", "de"), ("thresholds", "--json")):
            with self.subTest(argv=argv):
                code, out, err = run(*argv)
                self.assertEqual(code, 0, err)
                self.assertIn("CC BY 4.0", out)
        self.assertEqual(run()[0], 2)

    def test_verify_sources_exit_codes(self):
        self.serve(sparql_router())
        self.assertEqual(run("verify-sources")[0], 0)
        cons = fixture("sparql-consolidated.json")
        cons["results"]["bindings"].append({"base": {"type": "literal", "value": "32022L2464"},
                                            "celex": {"type": "literal", "value": "02022L2464-20261105"},
                                            "date": {"type": "literal", "value": "2026-11-05"}})
        self.serve(sparql_router({"consolidated": json.dumps(cons).encode()}))
        code, out, _ = run("verify-sources")
        self.assertEqual(code, 1)
        self.assertIn("02022L2464-20261105", out)
        self.serve(lambda url: urllib.error.URLError("offline"))
        code, _, err = run("verify-sources")
        self.assertEqual(code, 2)
        self.assertIn("could not check", err)
        self.serve(lambda url: 429)
        self.assertEqual(run("verify-sources")[0], 2)


if __name__ == "__main__":
    unittest.main()
