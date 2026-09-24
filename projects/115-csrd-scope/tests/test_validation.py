"""Strict input validation: every malformed input is refused with a message, never guessed at."""
import json
import unittest

from support import DATA, Isolated, eu, fy, non_eu

import csrd_scope

M = 1_000_000


GOOD = eu([fy(2027, to=500 * M, emp=1200)])


class Validation(Isolated):
    def assertRefused(self, inp, *fragments):
        try:
            csrd_scope.assess(inp, DATA)
        except csrd_scope.InputError as e:
            msg = " | ".join(e.errors)
            for f in fragments:
                self.assertIn(f, msg)
            return msg
        self.fail("accepted: " + json.dumps(inp)[:200])

    def test_currency_must_be_stated_as_eur(self):
        for cur in (None, "USD", "eur", "€", 978):
            inp = dict(GOOD)
            if cur is None:
                inp.pop("currency")
            else:
                inp["currency"] = cur
            self.assertRefused(inp, "never converts")

    def test_amounts_must_be_plain_numbers(self):
        for bad in ("450m", "480000000", True, [1], {"v": 1}):
            self.assertRefused(eu([{"year": 2027, "net_turnover_eur": bad, "average_employees": 1200}]), "must be a number")

    def test_out_of_range_and_non_finite_numbers(self):
        for bad in (-1, float("nan"), float("inf"), 1e16):
            self.assertRefused(eu([{"year": 2027, "net_turnover_eur": bad, "average_employees": 1200}]), "net_turnover_eur")
        self.assertRefused(eu([{"year": 2027, "net_turnover_eur": 1, "average_employees": 2e7}]), "average_employees")

    def test_years(self):
        self.assertRefused(eu([]), "financial_years")
        self.assertRefused(eu("2027"), "financial_years")
        self.assertRefused(eu([{"year": 1999}]), "year")
        self.assertRefused(eu([{"year": True}]), "year")
        self.assertRefused(eu([{"year": 2027.0}]), "year")
        self.assertRefused(eu([{"year": 2027}, {"year": 2027}]), "appears twice")
        self.assertRefused(eu([{"year": 2000 + i} for i in range(31)]), "at most 30")

    def test_unknown_fields_are_refused_not_ignored(self):
        self.assertRefused({**GOOD, "employees": 5}, "unknown field(s): employees")
        self.assertRefused(eu([{"year": 2027, "turnover": 5}]), "unknown field(s): turnover")

    def test_legal_form_required_for_eu_undertakings_of_other_types(self):
        inp = dict(GOOD)
        inp.pop("legal_form_in_annex_i_or_ii")
        self.assertRefused(inp, "legal_form_in_annex_i_or_ii")
        inp["entity_type"] = "credit_institution"
        csrd_scope.assess(inp, DATA)  # Art. 1(3): any legal form

    def test_flags_must_be_booleans(self):
        self.assertRefused({**GOOD, "listed_on_eu_regulated_market": "yes"}, "listed_on_eu_regulated_market")
        self.assertRefused({**GOOD, "eu_undertaking": 1}, "eu_undertaking")
        self.assertRefused({**GOOD, "entity_type": "bank"}, "entity_type")

    def test_fields_that_belong_to_the_other_kind_of_undertaking(self):
        self.assertRefused(eu([fy(2027, to=1, emp=1, eu_net_turnover_eur=5)]), "third-country")
        self.assertRefused(eu([fy(2027, to=1, emp=1, group_net_turnover_eur=5)]), "parent_undertaking")
        self.assertRefused(non_eu([fy(2027, eu_subsidiaries=[{"name": "x"}])]), "net_turnover_eur")
        self.assertRefused(non_eu([fy(2027, eu_branches="Branch")]), "eu_branches")

    def test_member_state_codes(self):
        self.assertRefused({**GOOD, "member_state": "UK"}, "member_state")
        self.assertRefused({**GOOD, "member_state": "XX"}, "member_state")
        res = csrd_scope.assess({**GOOD, "member_state": "el"}, DATA)
        self.assertEqual(res["national_law"]["member_state"], "GR")

    def test_financial_year_start(self):
        for bad in ("02-29", "13-01", "1-1", "2027-01-01", 101):
            self.assertRefused({**GOOD, "financial_year_starts_on": bad}, "financial_year_starts_on")

    def test_input_must_be_an_object(self):
        for bad in ([], "x", None, 3):
            self.assertRefused(bad, "JSON object")

    def test_all_problems_reported_at_once(self):
        msg = self.assertRefused({"currency": "USD", "eu_undertaking": "yes", "financial_years": [{"year": 1}]},
                                 "currency", "eu_undertaking", "year")
        self.assertGreaterEqual(msg.count("|"), 2)

    def test_names_are_masked_then_bounded_and_unicode_survives(self):
        secret = "p" * 12
        token = "t" * 24
        name = ("Société Générale d'Ünïcödé (fictional) https://user:" + secret + "@example.com/x?token=" + token
                + " --api-key=" + token + " API_KEY=" + token + "\x07‮" + "x" * 400)
        res = csrd_scope.assess({**GOOD, "name": name}, DATA)
        shown = res["undertaking"]
        self.assertTrue(shown.startswith("Société Générale d'Ünïcödé (fictional)"))
        for s in (secret, token, "\x07", "‮"):
            self.assertNotIn(s, json.dumps(res, ensure_ascii=False))
        self.assertLessEqual(len(shown), csrd_scope.MAX_NAME)

    def test_masking_runs_before_truncation(self):
        token = "k" * 30
        name = "x" * 170 + " https://u:" + token + "@host/"
        shown = csrd_scope.assess({**GOOD, "name": name}, DATA)["undertaking"]
        self.assertNotIn(token[:10], shown)


if __name__ == "__main__":
    unittest.main()
