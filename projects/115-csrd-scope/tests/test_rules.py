"""The Directive's own logic as a table. Each case names the provision it tests.

Texts: Directive 2013/34/EU consolidated 02013L0034-20260318; Directive (EU) 2022/2464
consolidated 02022L2464-20260318; Directives (EU) 2025/794 and 2026/470; Delegated
Directive (EU) 2023/2775; Directive 2004/109/EC consolidated 02004L0109-20240109.
"""
import unittest

from support import DATA, Isolated, eu, fy, non_eu, question_ids, statuses

import csrd_scope

M = 1_000_000
BIG = dict(to=520 * M, emp=1450, bst=400 * M)          # above EUR 450m and 1 000 employees
MID = dict(to=310 * M, emp=820, bst=290 * M)           # large, > 500 employees, below the 2026/470 thresholds


def years(spec, *ys):
    return [fy(y, **spec) for y in ys]


# (name, provision tested, input, expected statuses by FY, expected first reporting FY, questions that must be asked)
CASES = [
    ("above both thresholds: in scope from FY2027",
     "Art. 19a(1) Dir. 2013/34/EU; Art. 5(2) first subpara. (b)(i) Dir. 2022/2464",
     eu(years(BIG, 2026, 2027)),
     {"FY2024": "no", "FY2025": "no", "FY2026": "no", "FY2027": "yes", "FY2028": "yes"}, "FY2027", set()),
    ("net turnover exactly EUR 450 000 000 does not exceed it",
     "Art. 19a(1): 'exceed a net turnover of EUR 450 000 000'",
     eu(years(dict(to=450 * M, emp=5000), 2026, 2027)),
     {"FY2027": "depends", "FY2028": "no"}, None, {"transposition-2027"}),
    ("exactly 1 000 employees does not exceed 1 000",
     "Art. 19a(1): 'an average number of 1 000 employees'",
     eu(years(dict(to=900 * M, emp=1000), 2026, 2027)),
     {"FY2027": "depends", "FY2028": "no"}, None, {"transposition-2027"}),
    ("one EUR and one employee above: in scope",
     "Art. 19a(1)",
     eu(years(dict(to=450 * M + 1, emp=1001), 2026, 2027)),
     {"FY2027": "yes"}, "FY2027", set()),
    ("only turnover exceeded: both criteria are required",
     "Art. 19a(1) ('and')",
     eu(years(dict(to=2000 * M, emp=900), 2026, 2027)),
     {"FY2027": "depends", "FY2028": "no"}, None, {"transposition-2027"}),
    ("group above, parent alone below: consolidated reporting",
     "Art. 29a(1); Art. 5(2) first subpara. (b)(ii)",
     eu([fy(y, to=10 * M, emp=50, group_net_turnover_eur=600 * M, group_average_employees=3000) for y in (2026, 2027)],
        parent_undertaking=True),
     {"FY2026": "no", "FY2027": "yes"}, "FY2027", set()),
    ("group exactly at both thresholds: no consolidated reporting",
     "Art. 29a(1)",
     eu([fy(y, to=10 * M, emp=50, group_net_turnover_eur=450 * M, group_average_employees=1000) for y in (2026, 2027)],
        parent_undertaking=True),
     {"FY2027": "depends", "FY2028": "no"}, None, {"transposition-2027"}),
    ("listed large PIE above 500 employees, below the new thresholds",
     "Art. 5(2) first subpara. (a)(i) and fifth subpara. Dir. 2022/2464 (as amended by 2026/470); Arts. 2(1), 3(4), 3(10)",
     eu(years(MID, 2023, 2024, 2025), listed_on_eu_regulated_market=True),
     {"FY2024": "yes", "FY2025": "depends", "FY2026": "depends", "FY2027": "depends", "FY2028": "no"}, "FY2024",
     {"derogation", "transposition-2027"}),
    ("listed large PIE above the new thresholds: the 2025-2026 option does not reach it",
     "Art. 5(2) fifth subparagraph ('which do not exceed')",
     eu(years(BIG, 2023, 2024, 2025), listed_on_eu_regulated_market=True),
     {"FY2024": "yes", "FY2025": "yes", "FY2026": "yes", "FY2027": "yes"}, "FY2024", set()),
    # Art. 3(10) in isolation: a third-country issuer is not a public-interest entity, so Art. 40 plays no part.
    ("becomes large in FY2024 only: Art. 3(10) keeps the earlier category that year",
     "Art. 3(10) two consecutive financial years; Art. 3(4) as amended by Delegated Dir. 2023/2775; Art. 5(2) third subpara. (a)",
     non_eu([fy(2022, to=30 * M, emp=600, bst=15 * M), fy(2023, to=30 * M, emp=600, bst=15 * M),
             fy(2024, to=60 * M, emp=600, bst=30 * M), fy(2025, to=60 * M, emp=600, bst=30 * M)],
            listed_on_eu_regulated_market=True, only_debt_securities_min_denomination_eur_100000=False),
     {"FY2024": "depends", "FY2025": "depends", "FY2026": "depends", "FY2027": "depends"}, None,
     {"two-dates", "derogation", "transposition-2027"}),
    ("falls below in FY2025: still large for FY2025 under Art. 3(10), not for FY2026",
     "Art. 3(10)",
     non_eu([fy(2023, to=60 * M, emp=600, bst=30 * M), fy(2024, to=60 * M, emp=600, bst=30 * M),
             fy(2025, to=30 * M, emp=600, bst=15 * M), fy(2026, to=30 * M, emp=600, bst=15 * M)],
            listed_on_eu_regulated_market=True, only_debt_securities_min_denomination_eur_100000=False),
     {"FY2024": "yes", "FY2025": "depends", "FY2026": "no"}, "FY2024", {"two-dates"}),
    ("EU listed PIE that is large only from FY2024: the size category changes that year",
     "Art. 3(10) ('derogations provided for in this Directive'); Commission Notice FAQ 2",
     eu([fy(2022, to=30 * M, emp=600, bst=15 * M), fy(2023, to=30 * M, emp=600, bst=15 * M),
         fy(2024, to=60 * M, emp=600, bst=30 * M)], listed_on_eu_regulated_market=True),
     {"FY2024": "depends"}, None, {"two-dates"}),
    ("FY2023 is large under the old thresholds but not the adjusted ones",
     "Delegated Dir. 2023/2775 Art. 2(1) (Member State option for FY2023); Art. 3(4) before and after",
     eu([fy(2023, to=45 * M, emp=600, bst=22 * M), fy(2024, to=45 * M, emp=600, bst=22 * M)],
        listed_on_eu_regulated_market=True),
     {"FY2024": "depends"}, None, {"fy2023-thresholds"}),
    ("listed SME: never in scope",
     "Art. 5(2) first subpara. (c) deleted by Dir. 2026/470 Art. 3(1)(a)(iii); (a)(i) needs a large undertaking with > 500 employees",
     eu(years(dict(to=30 * M, emp=200, bst=15 * M), 2023, 2024, 2025), listed_on_eu_regulated_market=True),
     {"FY2024": "no", "FY2025": "no", "FY2026": "no", "FY2027": "no", "FY2028": "no"}, None, set()),
    ("PIE with 600 employees but below the Art. 3(4) money criteria",
     "Art. 40 (PIE treated as large) against Art. 5(2)(a)(i) ('within the meaning of Article 3(4)')",
     eu(years(dict(to=10 * M, emp=600, bst=5 * M), 2023, 2024), listed_on_eu_regulated_market=True),
     {"FY2024": "depends"}, None, {"art40"}),
    ("credit institution in a legal form outside Annex I, above the thresholds",
     "Art. 1(3) Dir. 2013/34/EU (any legal form); Art. 2(1)(b) (PIE)",
     eu(years(dict(to=800 * M, emp=3000, bst=9000 * M), 2023, 2024), entity_type="credit_institution",
        legal_form_in_annex_i_or_ii=False),
     {"FY2024": "yes", "FY2025": "yes", "FY2026": "yes", "FY2027": "yes"}, "FY2024", {"crd-excluded"}),
    ("insurance undertaking below the thresholds: in the 2024 set, out from FY2027",
     "Art. 1(3); Art. 2(1)(c); Art. 5(2) fifth subparagraph",
     eu(years(dict(to=300 * M, emp=800, bst=2000 * M), 2023, 2024), entity_type="insurance_undertaking",
        legal_form_in_annex_i_or_ii=None),
     {"FY2024": "yes", "FY2025": "depends", "FY2027": "depends", "FY2028": "no"}, "FY2024", {"derogation", "transposition-2027"}),
    ("cooperative bank parent: only the group exceeds the thresholds",
     "Art. 1(3) ('provided that those undertakings ... exceed') with Art. 29a(1)",
     eu([fy(y, to=100 * M, emp=400, bst=900 * M, group_net_turnover_eur=900 * M, group_average_employees=4000,
            group_balance_sheet_total_eur=20000 * M) for y in (2026, 2027)],
        entity_type="credit_institution", legal_form_in_annex_i_or_ii=False, parent_undertaking=True),
     {"FY2027": "depends"}, None, {"bank-parent-form"}),
    ("UCITS above the thresholds: excluded",
     "Art. 1(4) Dir. 2013/34/EU; Art. 2(12)(f) Reg. 2019/2088",
     eu(years(BIG, 2026, 2027), entity_type="aif_or_ucits"),
     {"FY2024": "no", "FY2027": "no", "FY2028": "no"}, None, set()),
    ("financial holding parent: may choose not to report consolidated information",
     "Art. 29a(7a) (inserted by Dir. 2026/470); Art. 2(15)",
     eu([fy(y, to=5 * M, emp=20, group_net_turnover_eur=900 * M, group_average_employees=5000) for y in (2026, 2027)],
        parent_undertaking=True, financial_holding_undertaking=True),
     {"FY2027": "depends"}, None, {"fhu"}),
    ("subsidiary covered by its parent's consolidated report",
     "Art. 19a(9) and (10) (as amended by Dir. 2026/470)",
     eu(years(BIG, 2026, 2027), covered_by_parent_consolidated_sustainability_report=True),
     {"FY2027": "depends"}, None, {"subsidiary-exemption"}),
    ("listed large subsidiary: no exemption for FY2024, national law for FY2025-2026",
     "Art. 19a(10) before Dir. 2026/470 (02013L0034-20240528) and after",
     eu(years(BIG, 2023, 2024), listed_on_eu_regulated_market=True, covered_by_parent_consolidated_sustainability_report=True),
     {"FY2024": "yes", "FY2025": "depends"}, "FY2024", {"subsidiary-exemption", "subsidiary-exemption-listed"}),
    ("thresholds first exceeded in FY2027: a two-date national rule would change FY2027",
     "Art. 19a(1) 'on their balance sheet dates'; Art. 3(10) limited to Art. 3(1)-(7); Commission Notice FAQ 1-2",
     eu([fy(2026, to=400 * M, emp=1200), fy(2027, to=500 * M, emp=1200)]),
     {"FY2027": "depends", "FY2028": "yes"}, None, {"two-dates"}),
    ("financial year starting 1 July: FY2027 starts 2027-07-01",
     "Art. 5(2) first subpara. (b): 'financial years starting on or after 1 January 2027'",
     eu(years(BIG, 2026, 2027), financial_year_starts_on="07-01"),
     {"FY2026": "no", "FY2027": "yes"}, "FY2027", set()),
    ("third-country group: EU turnover above EUR 450m two years, EU subsidiary above EUR 200m",
     "Art. 40a(1) first, second and fifth subparagraphs; Art. 5(2) second subpara. (FY2028)",
     non_eu([fy(y, eu_net_turnover_eur=515 * M, eu_subsidiaries=[{"name": "Sub A", "net_turnover_eur": 262 * M}])
             for y in (2026, 2027)]),
     {"FY2024": "no", "FY2027": "no", "FY2028": "yes"}, "FY2028", {"40a-publisher", "eu-subsidiaries-own-scope"}),
    ("third-country group with EU turnover exactly EUR 450m",
     "Art. 40a(1) fifth subparagraph ('exceeding')",
     non_eu([fy(y, eu_net_turnover_eur=450 * M, eu_subsidiaries=[{"name": "Sub A", "net_turnover_eur": 300 * M}])
             for y in (2026, 2027)]),
     {"FY2028": "no"}, None, set()),
    ("EU subsidiary exactly EUR 200m and no branch",
     "Art. 40a(1) second subparagraph ('exceed a net turnover of EUR 200 000 000')",
     non_eu([fy(y, eu_net_turnover_eur=600 * M, eu_subsidiaries=[{"name": "Sub A", "net_turnover_eur": 200 * M}],
                eu_branches=[]) for y in (2026, 2027)]),
     {"FY2028": "no"}, None, set()),
    ("small EU subsidiary and a large EU branch",
     "Art. 40a(1) fourth subparagraph ('does not have a subsidiary undertaking as referred to in the first subparagraph')",
     non_eu([fy(y, eu_net_turnover_eur=600 * M, eu_subsidiaries=[{"name": "Sub A", "net_turnover_eur": 50 * M}],
                eu_branches=[{"name": "Branch B", "net_turnover_eur": 250 * M}]) for y in (2026, 2027)]),
     {"FY2028": "depends"}, None, {"40a-branch"}),
    ("no EU subsidiary, EU branch above EUR 200m",
     "Art. 40a(1) third and fourth subparagraphs",
     non_eu([fy(y, eu_net_turnover_eur=600 * M, eu_subsidiaries=[],
                eu_branches=[{"name": "Branch B", "net_turnover_eur": 250 * M}]) for y in (2026, 2027)]),
     {"FY2028": "yes"}, "FY2028", set()),
    ("EU turnover crosses EUR 450m in FY2027: the two readings of 'last two consecutive financial years' differ",
     "Art. 40a(1) fifth subparagraph",
     non_eu([fy(2026, eu_net_turnover_eur=400 * M, eu_subsidiaries=[{"name": "S", "net_turnover_eur": 300 * M}]),
             fy(2027, eu_net_turnover_eur=500 * M, eu_subsidiaries=[{"name": "S", "net_turnover_eur": 300 * M}]),
             fy(2028, eu_net_turnover_eur=500 * M, eu_subsidiaries=[{"name": "S", "net_turnover_eur": 300 * M}]),
             fy(2029, eu_net_turnover_eur=500 * M, eu_subsidiaries=[{"name": "S", "net_turnover_eur": 300 * M}])]),
     {"FY2028": "depends", "FY2029": "yes"}, None, {"40a-two-years"}),
    ("third-country financial holding undertaking",
     "Art. 40a(1) last subparagraph (inserted by Dir. 2026/470)",
     non_eu([fy(y, eu_net_turnover_eur=900 * M, eu_subsidiaries=[{"name": "S", "net_turnover_eur": 300 * M}])
             for y in (2026, 2027)], financial_holding_undertaking=True),
     {"FY2028": "depends"}, None, {"fhu-40a"}),
    ("third-country issuer on an EU regulated market above the thresholds",
     "Art. 4(5) Dir. 2004/109/EC; Art. 5(2) third subpara. (a) and (b) Dir. 2022/2464",
     non_eu(years(BIG, 2023, 2024), listed_on_eu_regulated_market=True,
            only_debt_securities_min_denomination_eur_100000=False),
     {"FY2024": "yes", "FY2025": "yes", "FY2027": "yes"}, "FY2024", {"issuer"}),
    ("third-country issuer of only large-denomination debt securities",
     "Art. 8(1)(b) Dir. 2004/109/EC",
     non_eu(years(BIG, 2023, 2024), listed_on_eu_regulated_market=True,
            only_debt_securities_min_denomination_eur_100000=True),
     {"FY2024": "no", "FY2027": "no"}, None, set()),
    ("not listed, designation by the Member State not stated",
     "Art. 2(1)(d) Dir. 2013/34/EU ('designated by Member States as public-interest entities')",
     eu(years(BIG, 2023, 2024), designated_pie=None),
     {"FY2024": "depends", "FY2027": "yes"}, None, {"designated-pie"}),
    ("not listed, not designated: no report before FY2027",
     "Art. 2(1) Dir. 2013/34/EU; Art. 5(2) first subpara. (a)",
     eu(years(BIG, 2023, 2024), designated_pie=False),
     {"FY2024": "no", "FY2026": "no", "FY2027": "yes"}, "FY2027", set()),
]


class DirectiveTable(Isolated):
    def test_cases(self):
        for name, provision, inp, expected, first, questions in CASES:
            with self.subTest(case=name, provision=provision):
                res = csrd_scope.assess(inp, DATA)
                got = statuses(res)
                for fy_label, want in expected.items():
                    self.assertEqual(got.get(fy_label), want, f"{fy_label}: {res['summary']}")
                frfy = res["first_reporting_financial_year"]
                self.assertEqual(frfy["financial_year"] if frfy else None, first, res["summary"])
                self.assertTrue(questions <= question_ids(res), f"missing {questions - question_ids(res)}")
                self.assertEqual(self.web.urls, [], "the assessment must not touch the network")

    def test_every_step_cites_a_quoted_provision(self):
        for name, _, inp, *_ in CASES:
            res = csrd_scope.assess(inp, DATA)
            for step in res["rules_applied"]:
                self.assertTrue(step["cites"], f"{name}: step without citation: {step['rule']}")
                for c in step["cites"]:
                    self.assertIn(c, res["provisions"], f"{name}: {c} not quoted")
            for q in res["questions_for_counsel"]:
                for c in q["cites"]:
                    self.assertIn(c, res["provisions"])

    def test_answer_carries_version_attribution_and_limits(self):
        res = csrd_scope.assess(CASES[0][2], DATA)
        v = res["legal_basis_version"]
        self.assertEqual(v["directive_2013_34_eu"]["consolidated_version"], "02013L0034-20260318")
        self.assertEqual(v["directive_2022_2464_eu"]["consolidated_version_date"], "2026-03-18")
        self.assertEqual(v["checked"], "2026-09-24")
        self.assertIn("CC BY 4.0", res["attribution"])
        self.assertIn("Derived", res["attribution"])
        self.assertIn("Not legal advice", res["what_this_is_not"])
        self.assertIn("CSDDD", res["what_this_is_not"])

    def test_first_year_unknown_when_an_earlier_year_depends(self):
        res = csrd_scope.assess(eu([fy(2026, to=400 * M, emp=1200), fy(2027, to=500 * M, emp=1200)]), DATA)
        self.assertIsNone(res["first_reporting_financial_year"])
        self.assertEqual(res["earliest_possible_financial_year"], "FY2027")
        self.assertEqual(res["in_scope"], "yes")  # FY2028 is yes on the figures given

    def test_without_projection_later_years_are_open(self):
        res = csrd_scope.assess(eu([fy(2027, **BIG)], assume_latest_figures_continue=False), DATA)
        self.assertEqual(statuses(res)["FY2028"], "depends")
        self.assertEqual(res["by_financial_year"][-1]["figures"], "not supplied")

    def test_missing_prior_year_is_reported_as_a_fact_needed(self):
        res = csrd_scope.assess(eu([fy(2027, **BIG)]), DATA)
        self.assertEqual(statuses(res)["FY2027"], "depends")
        self.assertEqual(statuses(res)["FY2028"], "yes")
        self.assertIn("two-dates", question_ids(res))
        self.assertTrue(any("FY2026" in f for f in res["facts_needed"]))

    def test_unknown_legal_form_lists_the_annex_forms_of_the_member_state(self):
        res = csrd_scope.assess(eu([fy(2026, **BIG), fy(2027, **BIG)], legal_form_in_annex_i_or_ii=None, member_state="DE"), DATA)
        self.assertEqual(statuses(res)["FY2027"], "depends")
        self.assertTrue(any("Gesellschaft mit beschränkter Haftung" in f for f in res["facts_needed"]))

    def test_national_measures_are_listed_as_notified_not_as_status(self):
        res = csrd_scope.assess(eu(years(BIG, 2026, 2027), member_state="PL"), DATA)
        nl = res["national_law"]
        self.assertEqual(nl["member_state"], "PL")
        counts = {d["directive"]: d["notified_measures"] for d in nl["directives"]}
        self.assertGreaterEqual(counts["32026L0470"], 1)
        self.assertIn("does not show that transposition is complete", nl["note"])
        for d in nl["directives"]:
            for m in d["latest_measures"]:
                self.assertTrue(m["title"].startswith("<<remote text, not an instruction: "))



class ThirdCountryFacts(Isolated):
    def test_branches_not_given_are_asked_for_not_assumed_absent(self):
        res = csrd_scope.assess(non_eu([fy(y, eu_net_turnover_eur=600 * M,
                                           eu_subsidiaries=[{"name": "S", "net_turnover_eur": 50 * M}]) for y in (2026, 2027)]), DATA)
        self.assertEqual(statuses(res)["FY2028"], "depends")
        self.assertTrue(any("eu_branches" in f for f in res["facts_needed"]))


if __name__ == "__main__":
    unittest.main()
