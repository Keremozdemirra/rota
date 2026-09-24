"""End to end on the example files, output formats and exit codes."""
import json
import os
import subprocess
import sys
import unittest

from tests.support import EXAMPLES, ROOT, IsolatedTestCase, docx, para, run_cli, tieout

DECK = str(EXAMPLES / "deck.pptx")
REPORT = str(EXAMPLES / "bericht.docx")
MODEL = str(EXAMPLES / "model.xlsx")
MARKET = str(EXAMPLES / "marktdaten.csv")


def by_written(report):
    out = {}
    for d in report["numbers"]:
        out.setdefault(d["written"], []).append(d)
    return out


class Examples(IsolatedTestCase):
    @classmethod
    def setUpClass(cls):
        cls.deck = tieout.build_report(DECK, [MODEL, MARKET])
        cls.report = tieout.build_report(REPORT, [MODEL, MARKET])

    def test_deck_planted_errors(self):
        got = by_written(self.deck)
        self.assertEqual(got["€612m"][0]["status"], "untied")
        self.assertEqual(got["€612m"][0]["nearest"]["ref"], "model.xlsx › 'P&L'!C3")
        self.assertEqual(got["62%"][0]["status"], "untied")
        self.assertIn("rounds to 61", got["62%"][0]["nearest"]["detail"])
        self.assertEqual(got["1,080"][0]["status"], "untied")
        self.assertEqual(got["1,500"][0]["status"], "untied")
        self.assertEqual(got["14%"][0]["status"], "ambiguous")
        self.assertEqual(self.deck["summary"]["untied"], 4)

    def test_deck_ties(self):
        got = by_written(self.deck)
        self.assertEqual(got["€4.2bn"][0]["status"], "tied")
        self.assertEqual(got["€4.2bn"][0]["candidate_count"], 2)
        notes = [d for d in self.deck["numbers"] if d["where"] == "slide 2 notes" and d["written"] == "61.5%"]
        self.assertEqual(notes[0]["status"], "tied")
        chart = [d for d in self.deck["numbers"] if "chart" in d["where"] and d["status"] != "excluded"]
        self.assertEqual([(d["written"], d["status"]) for d in chart],
                         [("2,105.2", "tied"), ("1,187.4", "tied"), ("920.9", "tied")])
        table = [d for d in self.deck["numbers"] if "table 1" in d["where"] and d["status"] == "tied"]
        self.assertEqual(len(table), 13)
        hidden = [d for d in self.deck["numbers"] if "(hidden)" in d["where"]]
        self.assertEqual(hidden[0]["status"], "tied")
        self.assertEqual(got["€13.4bn"][0]["candidates"][0]["source"], "marktdaten.csv")

    def test_deck_exclusions(self):
        reasons = self.deck["summary"]["excluded_by_reason"]
        self.assertEqual(reasons[tieout.R_PAGE], 6)
        self.assertEqual(reasons[tieout.R_FOOTNOTE], 2)
        self.assertEqual(reasons[tieout.R_UNITLABEL], 1)

    def test_german_report(self):
        self.assertEqual(self.report["number_format"]["locale"], "de")
        got = by_written(self.report)
        self.assertEqual(got["4,2 Mrd. €"][0]["status"], "tied")
        self.assertEqual(got["15,3 %"][0]["status"], "untied")
        self.assertEqual(got["15,3 %"][0]["nearest"]["source"], "marktdaten.csv")
        self.assertEqual([d["status"] for d in got["1.310"]], ["tied", "tied"])
        self.assertEqual(got["1.310"][0]["read_as"]["value"], "1310")
        self.assertEqual(self.report["summary"]["untied"], 1)
        self.assertEqual(self.report["summary"]["ambiguous"], 0)

    def test_extract_only(self):
        rep = tieout.build_report(DECK, extract_only=True)
        self.assertEqual({d["status"] for d in rep["numbers"]}, {"extracted", "excluded"})
        self.assertEqual(rep["sources"], [])


class Outputs(IsolatedTestCase):
    def test_text(self):
        code, out, err = run_cli([DECK, MODEL, MARKET])
        self.assertEqual(code, 0)
        self.assertIn("number format: en", out)
        self.assertIn("untied     €612m", out)
        self.assertIn("--explain shows", out)
        self.assertNotIn("excluded ", out.split("\n\n")[1])

    def test_explain_lists_every_exclusion(self):
        code, out, _ = run_cli([DECK, MODEL, MARKET, "--explain"])
        report = tieout.build_report(DECK, [MODEL, MARKET])
        excluded = [d for d in report["numbers"] if d["status"] == "excluded"]
        self.assertEqual(out.count(" excluded "), len(excluded))
        for d in excluded:
            self.assertIn(d["reason"], out)
        self.assertIn("tie rule: |v| × 100 or |v| rounds to 62 at whole number", out)

    def test_markdown(self):
        code, out, _ = run_cli([REPORT, MODEL, MARKET, "--markdown"])
        self.assertIn("| # | Status | Number | Where | Source | Context |", out)
        self.assertIn("**15,3 %**", out)
        self.assertIn("**Summary:**", out)

    def test_json(self):
        code, out, _ = run_cli([REPORT, MODEL, MARKET, "--json"])
        data = json.loads(out)
        self.assertEqual(set(data), {"tool", "version", "checked_at", "deliverable", "sources", "number_format", "summary",
                                     "numbers", "links", "errors", "warnings"})
        first = next(d for d in data["numbers"] if d["status"] == "tied")
        self.assertEqual(set(first["candidates"][0]) >= {"source", "sheet", "cell", "value", "label", "how", "detail"}, True)

    def test_min_digits_and_locale(self):
        rep = tieout.build_report(DECK, [MODEL], min_digits=3)
        self.assertEqual(by_written(rep)["62%"][0]["reason"], "fewer than 3 digits (--min-digits)")
        rep = tieout.build_report(REPORT, [MODEL], locale="en")
        self.assertEqual(rep["number_format"], {"locale": "en", "basis": "set with --locale"})
        self.assertEqual(by_written(rep)["1.310"][0]["read_as"]["value"], "1.31")


class ExitCodes(IsolatedTestCase):
    def test_strict_fails_on_untied(self):
        self.assertEqual(run_cli([DECK, MODEL, MARKET, "--strict"])[0], 1)
        self.assertEqual(run_cli([DECK, MODEL, MARKET])[0], 0)

    def test_strict_passes_when_everything_ties(self):
        path = docx(self.path("ok.docx"), para("Revenue €4.2bn and EBITDA €598m in 2025 (margin 14.2%)."))
        self.assertEqual(run_cli([path, MODEL, "--strict"])[0], 0)

    def test_unreadable_inputs_exit_2(self):
        code, out, err = run_cli([self.path("missing.pptx"), MODEL])
        self.assertEqual(code, 2)
        self.assertIn("file not found", err)
        code, out, err = run_cli([DECK, self.path("typo.xlsx"), "--strict"])
        self.assertEqual(code, 2)
        self.assertIn("could not read", out)
        pdf = self.text_file("r.pdf", b"%PDF-1.7")
        code, _, err = run_cli([pdf, MODEL])
        self.assertEqual(code, 2)
        self.assertIn("pdftotext", err)

    def test_strict_without_sources_exit_2(self):
        self.assertEqual(run_cli([DECK, "--strict"])[0], 2)
        self.assertEqual(run_cli([DECK])[0], 0)

    def test_bad_arguments(self):
        with self.assertRaises(SystemExit) as ctx:
            run_cli([DECK, "--min-digits", "0"])
        self.assertEqual(ctx.exception.code, 2)

    def test_subprocess_and_stderr(self):
        env = dict(os.environ, HOME=str(self.home), PYTHONIOENCODING="utf-8")
        p = subprocess.run([sys.executable, str(ROOT / "tieout.py"), DECK, MODEL, "--strict", "--json"],
                           capture_output=True, text=True, encoding="utf-8", env=env, timeout=120)
        self.assertEqual(p.returncode, 1)
        self.assertEqual(json.loads(p.stdout)["summary"]["untied"] >= 4, True)
        p = subprocess.run([sys.executable, str(ROOT / "tieout.py"), "--version"], capture_output=True, text=True,
                           env=env, timeout=60)
        self.assertEqual(p.stdout.strip(), f"tieout {tieout.__version__}")


class Masking(IsolatedTestCase):
    def test_secrets_in_context_are_masked(self):
        path = self.text_file("s.md", "Revenue 12.5% per https://alice:hunter2@example.org/r?key=sk-SECRET and "
                                      "API_KEY=sk-OTHER token: abc123 12.5%\n")
        code, out, _ = run_cli([path, "--json"])
        self.assertNotIn("hunter2", out)
        self.assertNotIn("sk-SECRET", out)
        self.assertNotIn("sk-OTHER", out)
        self.assertNotIn("abc123", out)


if __name__ == "__main__":
    unittest.main()
