"""The five queries on the fixture cache; expected numbers are computed from the fixture CSV directly."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _support import PLACEHOLDERS, Isolated, build_fixture_db, eu_ets, fixture_rows  # noqa: E402

VOEST = "529900FGOWZKLBZ81V67"  # voestalpine Stahl GmbH at GLEIF; three installations in the fixtures


def yearly(reg: str, iid: str) -> dict:
    return {int(r["PERIOD_YEAR"]): r for r in fixture_rows("operators_yearly_activity_daily.csv.gz")
            if (r["REGISTRY_CODE"], r["INSTALLATION_IDENTIFIER"]) == (reg, iid) and r["PERIOD_YEAR"].isdigit()}


class QueryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = Isolated().__enter__()
        build_fixture_db(cls.env.cache)
        cls.ds = eu_ets.Dataset()

    @classmethod
    def tearDownClass(cls):
        cls.env.__exit__()

    # --- search
    def test_search_ignores_accents_and_case(self):
        for q in ("hüttenwerk", "HUTTENWERK", "Huttenwerk"):
            r = self.ds.search_installations(q)  # also inside "Wiegand-Glashüttenwerke"
            self.assertEqual({(i["country"], i["installation_id"]) for i in r["installations"]}, {("DE", 69), ("DE", 262)}, q)
        r = self.ds.search_installations("Hüttenwerk duisburg")  # every word must match
        self.assertEqual([(i["country"], i["installation_id"]) for i in r["installations"]], [("DE", 69)])

    def test_search_filters(self):
        r = self.ds.search_installations("", country="Germany", activity="steel")
        self.assertEqual({i["installation_id"] for i in r["installations"]}, {69, 53})
        self.assertEqual(r["activities"], [{"code": 24, "label": "Production of pig iron or steel"}])
        self.assertEqual(self.ds.search_installations("linz", country="at")["matches"], 3)
        self.assertEqual(self.ds.search_installations("", activity="22,24")["matches"], 4)
        r = self.ds.search_installations("duisburg", limit="1")
        self.assertEqual((r["matches"], r["returned"], r["installations"][0]["installation_id"]), (2, 1, 69))

    def test_search_empty_result_and_bad_arguments(self):
        self.assertEqual(self.ds.search_installations("no such works")["matches"], 0)
        self.assertEqual(self.ds.search_installations("Mustermann")["matches"], 0)  # withheld names are not searchable
        for kwargs, msg in (({"query": ""}, "give a query"), ({"query": "x", "country": "Atlantis"}, "unknown country"),
                            ({"query": "x", "limit": 0}, "between 1 and 100"), ({"query": "x", "limit": True}, "whole number"),
                            ({"query": "x", "activity": "unobtainium"}, "no activity matches"),
                            ({"query": "x", "activity": "99"}, "unknown activity"), ({"query": ["x"]}, "must be text")):
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(eu_ets.UsageError, msg):
                self.ds.search_installations(**kwargs)

    # --- history
    def test_history_values_match_the_registry_file(self):
        r = self.ds.installation_history("DE-69")
        raw = yearly("DE", "69")
        by = {y["year"]: y for y in r["years"]}
        self.assertEqual(by[2024]["verified_emissions"], int(raw[2024]["VERIFIED_EMISSIONS"]))
        self.assertEqual(by[2024]["free_allocation"], sum(int(raw[2024][c]) for c in ("ALLOCATION", "ALLOCATION_RES", "ALLOCATION_TRA")))
        self.assertEqual(by[2024]["surrendered"], int(raw[2024]["SURR_ALL"]))
        self.assertEqual(by[2024]["compliance_code"], "A")
        self.assertIsNone(by[2023]["compliance_code"])  # only the 2024 compliance file is in the fixtures
        self.assertIsNone(by[2027]["verified_emissions"])  # not reported yet
        self.assertEqual(by[2027]["free_allocation"], int(raw[2027]["ALLOCATION"]))
        self.assertIn("A", r["compliance_codes"])

    def test_history_ambiguous_id_lists_candidates(self):
        r = self.ds.installation_history(69)
        self.assertFalse(r["found"])
        self.assertEqual(sorted((c["country"], c["installation_id"]) for c in r["candidates"]), [("AT", 69), ("DE", 69)])
        for ref, country in (("69", "DE"), ("de_69", None), ("DE 69", "Germany")):
            self.assertEqual(self.ds.installation_history(ref, country)["installation"]["name"], "Integriertes Hüttenwerk Duisburg")

    def test_history_missing_years_are_reported(self):
        r = self.ds.installation_history("AT-14")
        self.assertEqual(r["years_without_values"], [2008, 2009])
        self.assertEqual([y["year"] for y in r["years"]][:4], [2005, 2006, 2007, 2010])

    def test_history_range_unknown_and_bad_ids(self):
        r = self.ds.installation_history("AT-16", from_year=2020, to_year=2022)
        self.assertEqual([y["year"] for y in r["years"]], [2020, 2021, 2022])
        self.assertFalse(self.ds.installation_history("DE-999")["found"])
        for args, msg in ((("DE-69",), {"from_year": 2025, "to_year": 2020}), (("XX-1",), {})):
            with self.assertRaises(eu_ets.UsageError):
                self.ds.installation_history(*args, **msg)
        with self.assertRaisesRegex(eu_ets.UsageError, "installation id"):
            self.ds.installation_history("Duisburg")

    def test_history_of_an_excluded_aircraft_operator(self):
        r = self.ds.installation_history("AT-201836")
        by = {y["year"]: y for y in r["years"]}
        self.assertEqual(by[2024]["compliance_code"], "EXCLUDED SINCE 2021")
        self.assertTrue(by[2021]["excluded"])

    # --- LEI
    def test_lei_totals_are_sums_over_the_installations(self):
        r = self.ds.company_by_lei("5299-00FGOWZKLBZ81V-67", from_year=2013, to_year=2025)
        self.assertTrue(r["found"])
        self.assertEqual(sorted(i["installation_id"] for i in r["installations"]), [14, 16, 17])
        t = {x["year"]: x for x in r["yearly_totals"]}
        for year in (2013, 2025):
            rows = [yearly("AT", i).get(year) for i in ("14", "16", "17")]
            rows = [x for x in rows if x]
            self.assertEqual(t[year]["verified_emissions"], sum(int(x["VERIFIED_EMISSIONS"]) for x in rows))
            self.assertEqual(t[year]["surrendered"], sum(int(x["SURR_ALL"]) for x in rows))
        self.assertEqual(min(t), 2013)
        self.assertNotIn("years", r["installations"][0])
        self.assertIn("years", self.ds.company_by_lei(VOEST, detail=True)["installations"][0])

    def test_lei_not_in_the_registry(self):
        r = self.ds.company_by_lei("549300QGIICV4ZFTKX83")  # ThyssenKrupp Steel Europe AG: no LEI in the registry
        self.assertFalse(r["found"])
        self.assertIn("not proof", r["message"])

    def test_lei_with_failing_check_digits_is_searched_with_a_warning(self):
        r = self.ds.company_by_lei("2138-00HRXSGIERQSMT-06")
        self.assertTrue(r["found"])
        self.assertFalse(r["lei_check_digits_ok"])
        self.assertTrue(any("check digits" in n for n in r["notes"]))

    def test_lei_bad_input(self):
        for bad in ("123", "", None, 12345678901234567890, "529900FGOWZKLBZ81V6X"):
            with self.subTest(bad=bad), self.assertRaises(eu_ets.UsageError):
                self.ds.company_by_lei(bad)

    # --- top emitters
    def test_top_emitters_ranking_and_total(self):
        r = self.ds.top_emitters(country="DE", activity=24)
        self.assertEqual(r["year"], 2025)  # the latest year with verified emissions
        ve = {i: int(yearly("DE", i)[2025]["VERIFIED_EMISSIONS"]) for i in ("69", "53")}
        self.assertEqual([i["installation_id"] for i in r["installations"]], [69, 53] if ve["69"] > ve["53"] else [53, 69])
        self.assertEqual(r["total_verified_emissions"], sum(ve.values()))
        self.assertTrue(any("30 September 2026" in n for n in r["notes"]))

    def test_top_emitters_other_years(self):
        r = self.ds.top_emitters(year=2024, limit=3)
        self.assertEqual(r["returned"], 3)
        self.assertEqual(r["installations"][0]["compliance_code"], "A")
        self.assertEqual(self.ds.top_emitters(year=2028)["matching_installations"], 0)
        with self.assertRaises(eu_ets.UsageError):
            self.ds.top_emitters(year=1999)

    def test_maritime_note(self):
        r = self.ds.top_emitters(activity="maritime", year=2025)
        self.assertTrue(any("Art. 3gb" in n for n in r["notes"]))

    # --- info and every output
    def test_dataset_info(self):
        r = self.ds.dataset_info()
        self.assertEqual((r["licence"], r["terms_url"]), ("CC BY 4.0", "https://commission.europa.eu/legal-notice_en"))
        self.assertEqual(r["counts"]["installations"], 15)
        self.assertEqual(r["compliance_years"], [2024])
        self.assertNotIn("ACCOUNT_HOLDER_NAME", r["columns_kept"]["operators_daily"])
        self.assertIn("Art. 3(a)", r["units"]["free_allocation"])

    def test_every_output_carries_the_attribution_and_no_personal_data(self):
        outputs = [self.ds.search_installations("", country="DE"), self.ds.search_installations("linz"),
                   self.ds.installation_history("DE-223104"), self.ds.installation_history(69),
                   self.ds.company_by_lei(VOEST, detail=True), self.ds.company_by_lei("549300QGIICV4ZFTKX83"),
                   self.ds.top_emitters(limit=100), self.ds.top_emitters(activity="maritime", year=2024), self.ds.dataset_info()]
        for r in outputs:
            self.assertTrue(r["source"].startswith("Source: European Commission, EU ETS Union Registry, CC BY 4.0, retrieved 2026-09-24"))
            self.assertEqual(r["snapshot_date"], "2026-09-24")
            blob = json.dumps(r, ensure_ascii=False)
            for p in PLACEHOLDERS:
                self.assertNotIn(p, blob)
        self.assertIn("derived", outputs[4]["source"])
        withheld = self.ds.installation_history("DE-223104")
        self.assertEqual((withheld["installation"]["name"], withheld["installation"]["city"]), (eu_ets.WITHHELD, None))


if __name__ == "__main__":
    unittest.main()
