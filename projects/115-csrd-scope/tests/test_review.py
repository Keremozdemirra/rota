"""Regressions for the adversarial review of 2026-09-24: each test replays the reviewer's command.

Rule under test: a definite yes/no only when every fact the provision needs is known and the text
leaves no reading open; otherwise "depends" with the question for counsel or the missing fact.
"""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

from support import DATA, ROOT, Isolated, eu, fixture, fy, non_eu, question_ids, sparql_router, statuses

import csrd_scope
import csrd_scope_cellar as cellar

M = 1_000_000


def cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = csrd_scope.main(list(argv) + ["--json"] if argv[0] == "check" else list(argv))
    return code, out.getvalue(), err.getvalue()


def check(*argv):
    code, out, err = cli("check", *argv)
    assert code == 0, err
    return json.loads(out)


class HighFindings(Isolated):
    def test_k1_art40a_missing_year_is_not_a_no(self):
        res = check("--non-eu", "--fy", "2027,eu_net_turnover_eur=500000000", "--fy", "2028,eu_net_turnover_eur=400000000",
                    "--eu-subsidiary", "2027:S=300000000", "--eu-subsidiary", "2028:S=300000000")
        self.assertEqual(statuses(res)["FY2028"], "depends")
        self.assertIn("40a-two-years", question_ids(res))
        self.assertTrue(any("FY2026" in f for f in res["facts_needed"]))
        self.assertNotIn("No reporting obligation", res["summary"])
        # the reverse case, projection off
        res = check("--non-eu", "--no-projection", "--fy", "2026,eu_net_turnover_eur=400000000",
                    "--fy", "2027,eu_net_turnover_eur=500000000", "--eu-subsidiary", "2027:S=300000000")
        self.assertEqual(statuses(res)["FY2028"], "depends")
        self.assertTrue(any("FY2028" in f for f in res["facts_needed"]))

    def test_k2_issuer_with_unknown_security_type_is_not_a_yes(self):
        figs = "net_turnover_eur=520000000,average_employees=1450,balance_sheet_total_eur=400000000"
        res = check("--non-eu", "--listed", "--fy", f"2023,{figs}", "--fy", f"2024,{figs}")
        self.assertEqual(statuses(res)["FY2024"], "depends")
        self.assertIn("debt-only", question_ids(res))
        self.assertIsNone(res["first_reporting_financial_year"])
        res = check("--non-eu", "--listed", "--debt-only", "no", "--fy", f"2023,{figs}", "--fy", f"2024,{figs}")
        self.assertEqual(statuses(res)["FY2024"], "yes")
        res = check("--non-eu", "--listed", "--debt-only", "yes", "--fy", f"2023,{figs}", "--fy", f"2024,{figs}")
        self.assertEqual(statuses(res)["FY2024"], "no")


class MediumFindings(Isolated):
    def test_o1_fy2027_before_the_transposition_deadline(self):
        figs = "net_turnover_eur=300000000,average_employees=800,balance_sheet_total_eur=200000000"
        res = check("--eu", "--legal-form", "yes", "--member-state", "FR", "--fy", f"2026,{figs}", "--fy", f"2027,{figs}")
        self.assertEqual(statuses(res)["FY2027"], "depends")
        self.assertEqual(statuses(res)["FY2028"], "no")
        self.assertIn("transposition-2027", question_ids(res))
        self.assertIn("CSRD2025-5-2-b", res["provisions"])
        # a financial year starting after 19 March 2027: the amended text decides
        res = check("--eu", "--legal-form", "yes", "--designated-pie", "no", "--fy-start", "07-01",
                    "--fy", f"2026,{figs}", "--fy", f"2027,{figs}")
        self.assertEqual(statuses(res)["FY2027"], "no")

    def test_o2_art_3_10_is_a_question_when_the_category_changes(self):
        res = check("--non-eu", "--listed", "--debt-only", "no",
                    "--fy", "2022,net_turnover_eur=30000000,balance_sheet_total_eur=15000000,average_employees=600",
                    "--fy", "2023,net_turnover_eur=30000000,balance_sheet_total_eur=15000000,average_employees=600",
                    "--fy", "2024,net_turnover_eur=60000000,balance_sheet_total_eur=30000000,average_employees=600")
        self.assertEqual(statuses(res)["FY2024"], "depends")
        self.assertIn("two-dates", question_ids(res))
        # the same in the Art. 29a large-group test
        grp = lambda y, t, b: fy(y, to=5 * M, emp=20, bst=5 * M, group_net_turnover_eur=t, group_balance_sheet_total_eur=b,
                                 group_average_employees=600)
        res = csrd_scope.assess(eu([grp(2022, 30 * M, 15 * M), grp(2023, 30 * M, 15 * M), grp(2024, 60 * M, 30 * M)],
                                   listed_on_eu_regulated_market=True, parent_undertaking=True), DATA)
        route = next(r for r in res["by_financial_year"][0]["routes"] if r["route"].startswith("consolidated"))
        self.assertEqual(route["status"], "depends")
        self.assertIn("two-dates", question_ids(res))

    def test_o3_unstated_designation_is_not_a_no(self):
        big = dict(to=520 * M, emp=1450, bst=400 * M)
        inp = eu([fy(2025, **big), fy(2026, **big)])
        inp.pop("designated_pie")
        res = csrd_scope.assess(inp, DATA)
        self.assertEqual(statuses(res)["FY2026"], "depends")
        self.assertIn("designated-pie", question_ids(res))
        res = csrd_scope.assess({**inp, "designated_pie": False}, DATA)
        self.assertEqual(statuses(res)["FY2026"], "no")

    def test_o4_member_state_option_can_be_stated(self):
        base = json.loads((ROOT / "examples" / "fictional-listed-wave1.json").read_text(encoding="utf-8"))
        want = {True: "no", False: "yes", None: "depends"}
        for value, status in want.items():
            with self.subTest(value=value):
                res = csrd_scope.assess({**base, "member_state_exemption_2025_2026": value}, DATA)
                self.assertEqual(statuses(res)["FY2025"], status)
        # above one threshold only: the option's two readings differ
        one = eu([fy(y, to=600 * M, emp=800, bst=500 * M) for y in (2023, 2024, 2025)], listed_on_eu_regulated_market=True,
                 member_state_exemption_2025_2026=True)
        res = csrd_scope.assess(one, DATA)
        self.assertEqual(statuses(res)["FY2025"], "depends")
        self.assertIn("below both", " ".join(q["question"] for q in res["questions_for_counsel"]))
        code, _, err = cli("check", "--eu", "--legal-form", "yes", "--listed", "--member-state-exemption-2025-2026", "yes",
                           "--fy", "2024,net_turnover_eur=1,average_employees=1")
        self.assertEqual(code, 0, err)

    def test_o5_publication_rule_matches_the_route(self):
        res = csrd_scope.assess(json.loads((ROOT / "examples" / "fictional-non-eu-group.json").read_text(encoding="utf-8")), DATA)
        pub = " ".join(res["first_reporting_financial_year"]["report_published"])
        self.assertIn("Art. 40d(1)", pub)
        self.assertNotIn("Art. 30(1)", pub)
        self.assertIn("AD-40d-1", res["provisions"])
        figs = dict(to=520 * M, emp=1450, bst=400 * M)
        res = csrd_scope.assess(non_eu([fy(2023, **figs), fy(2024, **figs)], listed_on_eu_regulated_market=True,
                                       only_debt_securities_min_denomination_eur_100000=False), DATA)
        self.assertIn("Art. 4(1) Directive 2004/109/EC", " ".join(res["first_reporting_financial_year"]["report_published"]))

    def test_o6_empty_answers_cannot_mean_unchanged(self):
        empty = json.dumps({"head": {"vars": []}, "results": {"bindings": []}}).encode()
        for key in ("acts", "nim", "after", "consolidated"):
            with self.subTest(empty=key):
                self.serve(sparql_router({key: empty}))
                with self.assertRaises(cellar.SourceError):
                    cellar.verify(DATA.legal, nim_snapshot=DATA.nim)
        self.serve(lambda url: empty)
        self.assertEqual(cli("verify-sources")[0], 2)

    def test_o7_deeply_nested_json(self):
        with tempfile.TemporaryDirectory() as home:
            env = {**os.environ, "HOME": home, "PYTHONIOENCODING": "utf-8"}
            ping = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"})
            proc = subprocess.run([sys.executable, str(ROOT / "csrd_scope_mcp.py")], input="[" * 100000 + "\n" + ping + "\n",
                                  capture_output=True, text=True, timeout=60, env=env, cwd=home)
            self.assertEqual(proc.returncode, 0, proc.stderr[-500:])
            replies = [json.loads(line) for line in proc.stdout.splitlines()]
            self.assertEqual(replies[0]["error"]["code"], -32700)
            self.assertEqual(replies[1], {"jsonrpc": "2.0", "id": 1, "result": {}})
            deep = os.path.join(home, "deep.json")
            with open(deep, "w") as f:
                f.write("[" * 100000)
            code, _, err = cli("check", "--input", deep)
            self.assertEqual(code, 2)
            self.assertNotIn("Traceback", err)


class LowFindings(Isolated):
    def test_headline_is_year_specific(self):
        base = json.loads((ROOT / "examples" / "fictional-listed-wave1.json").read_text(encoding="utf-8"))
        res = csrd_scope.assess(base, DATA)
        self.assertEqual(res["in_scope"], "no")
        self.assertTrue(res["in_scope_applies_to"].startswith("FY2028"))
        self.assertTrue(res["summary"].startswith("By financial year: FY2024: yes"))

    def test_wording_is_not_advice(self):
        from csrd_scope_mcp import TOOLS
        self.assertFalse(TOOLS[0]["description"].startswith("Decides"))
        res = csrd_scope.assess(json.loads((ROOT / "examples" / "fictional-eu-manufacturer.json").read_text(encoding="utf-8")), DATA)
        self.assertNotIn("In scope;", res["summary"])
        self.assertTrue(res["legal_basis_version"]["consolidated_text_status"].startswith("EUR-Lex, on its consolidated texts:"))

    def test_branch_rule_states_both_readings(self):
        text = next(t["test"] for t in csrd_scope.thresholds(DATA)["thresholds"] if t["id"] == "third-country")
        self.assertIn("is open", text)

    def test_fy2023_ambiguity_does_not_ask_for_figures_already_given(self):
        res = csrd_scope.assess(eu([fy(2023, to=45 * M, emp=600, bst=22 * M), fy(2024, to=45 * M, emp=600, bst=22 * M)],
                                   listed_on_eu_regulated_market=True), DATA)
        self.assertIn("fy2023-thresholds", question_ids(res))
        self.assertFalse(any(f.startswith("FY2023") for f in res["facts_needed"]), res["facts_needed"])

    def test_article_4_deadline(self):
        dates = {d["date"] for d in csrd_scope.timeline(DATA)["deadlines"]}
        self.assertIn("2028-07-26", dates)
        self.assertIn("Articles 1-3", DATA.version()["amending_acts_applied"][0]["transposition_deadline"])
        self.assertIn("26 July 2028", DATA.quotes["OMNI-5-1"]["text"])

    def test_licence_names_the_reuse_decision(self):
        self.assertIn("Decision 2011/833/EU", DATA.attribution())

    def test_option_wording_has_both_readings(self):
        self.assertIn("'below both'", csrd_scope.QUESTIONS["derogation"][0])


if __name__ == "__main__":
    unittest.main()
