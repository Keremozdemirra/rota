"""default_value and compare_origins over data built from the trimmed real Excel."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cbam_test_support import DataEnv  # noqa: E402
from cbam_mcp import legal, lookup  # noqa: E402
from cbam_mcp.codes import InputError  # noqa: E402


class DefaultValue(unittest.TestCase):
    def setUp(self):
        self.env = DataEnv()
        self.env.__enter__()

    def tearDown(self):
        self.env.__exit__()

    def test_code_below_a_table_line(self):
        r = lookup.default_value("7601 10 00", "India")
        self.assertEqual((r["status"], r["unit"]), ("found", "tCO2e per tonne of good"))
        line = r["lines"][0]
        self.assertEqual((line["table_line"], line["values_from_table"]), ("7601", "India"))
        self.assertEqual((line["total"], line["direct"], line["indirect"]), (1.87, 1.87, None))
        self.assertEqual(line["as_published"]["total"], "1,870")
        self.assertEqual(line["indirect_note"], "'N/A' in the table")
        self.assertEqual(line["production_route"], [{"code": "K", "meaning": "primary Aluminium"}])
        self.assertEqual(line["annex_iv_highest_default"]["value"], 3.198)

    def test_not_legally_binding_and_names_the_act(self):
        r = lookup.default_value("7601", "IN")
        self.assertIs(r["legally_binding"], False)
        self.assertIn("2025/2621", r["legally_binding_source"])
        self.assertIn("2026/1740", r["legally_binding_source"])
        self.assertEqual(r["legal_status_of_data"]["quote"], legal.EXCEL_NOTICE["quote"])
        self.assertIn("version 2 of 2026-08-06", r["data_version"])
        self.assertIn("CC BY 4.0", r["attribution"])
        self.assertIn("identical", r["checked_against_official_journal"])
        self.assertIn(legal.MARKUP_POINTER, r["notes"])

    def test_dash_uses_other_countries_with_the_rule(self):
        line = lookup.default_value("2523 21 00", "Türkiye")["lines"][0]
        self.assertEqual(line["values_from_table"], "Other Countries and Territories")
        self.assertEqual(line["fallback"]["rule"], legal.RULE_NO_VALUE)
        self.assertIn("'–'", line["fallback"]["reason"])

    def test_listed_country_without_the_line(self):
        line = lookup.default_value("7601", "Albania")["lines"][0]
        self.assertEqual(line["values_from_table"], "Other Countries and Territories")
        self.assertIn("has no line 7601", line["fallback"]["reason"])

    def test_country_missing_in_the_excel(self):
        r = lookup.default_value("7601", "Kosovo")
        line = r["lines"][0]
        self.assertEqual((line["values_from_table"], line["fallback"]["rule"]), ("Other Countries and Territories", legal.RULE_NOT_LISTED))
        self.assertIn("not a country name in the tables", r["warnings"][0])

    def test_typo_is_an_error_with_a_suggestion(self):
        with self.assertRaises(InputError) as cm:
            lookup.default_value("7601", "Indai")
        self.assertIn("India", str(cm.exception))

    def test_eu_and_annex_iii_origins_get_no_values(self):
        r = lookup.default_value("7601", "Germany")
        self.assertEqual((r["status"], r["lines"]), ("not_a_third_country", []))
        self.assertIn("Article 2(1)", r["explanation"])
        r = lookup.default_value("7601", "NO")
        self.assertEqual((r["status"], r["country"]), ("origin_outside_cbam", "Norway"))
        self.assertIn("point 1 of Annex III", r["explanation"])

    def test_electricity_is_not_in_the_excel(self):
        r = lookup.default_value("2716 00 00", "Serbia")
        self.assertEqual((r["status"], r["lines"]), ("not_in_this_data", []))
        self.assertEqual(r["rule"], legal.ELECTRICITY)
        self.assertIn("CC BY NC SA", r["licence_of_annex_iii"]["quote"])

    def test_hydrogen(self):
        line = lookup.default_value("2804 10 00", "India")["lines"][0]
        self.assertEqual((line["total"], line["goods_category"], line["production_route"]), (14.03, "Hydrogen", []))

    def test_taric_lines_under_one_cn_code(self):
        r = lookup.default_value("2523 10 00", "India")
        self.assertEqual([l["table_line"] for l in r["lines"]], ["2523 10 00 10", "2523 10 00 90"])
        self.assertIn("TARIC", r["warnings"][0])
        self.assertEqual([p["code"] for p in r["lines"][0]["production_route"]], ["B"])

    def test_ex_code_line_warns(self):
        r = lookup.default_value("2507 00 80", "Other")
        self.assertEqual(r["lines"][0]["table_line"], "2507 00 80 80")
        self.assertIn("only part of this code", r["warnings"][-1])

    def test_see_below_heading_resolves_to_sub_lines(self):
        r = lookup.default_value("7206", "India")
        self.assertEqual([l["table_line"] for l in r["lines"]], ["7206 10 00", "7206 90 00"])
        r = lookup.default_value("7610 90", "India")
        self.assertEqual([l["table_line"] for l in r["lines"]], ["7610 90", "7610 90 10", "7610 90 90"])

    def test_out_of_scope_code_has_no_line(self):
        r = lookup.default_value("7317 00", "India")
        self.assertEqual((r["status"], r["scope_status"]), ("no_line", "not_in_scope"))


class Compare(unittest.TestCase):
    def setUp(self):
        self.env = DataEnv()
        self.env.__enter__()

    def tearDown(self):
        self.env.__exit__()

    def test_india_versus_turkiye(self):
        r = lookup.compare_origins("7601 10 00", ["India", "TR", "Kosovo", "Norway"])
        line = r["lines"][0]
        rows = {c["country"]: c for c in line["by_country"]}
        self.assertEqual((rows["India"]["total"], rows["Türkiye"]["total"]), (1.87, 1.7))
        self.assertEqual(rows["Kosovo"]["values_from_table"], "Other Countries and Territories")
        self.assertEqual(rows["Norway"]["status"], "origin_outside_cbam")
        self.assertEqual(line["other_countries_and_territories"]["total"], 2.203)
        self.assertIs(r["legally_binding"], False)

    def test_bad_countries(self):
        r = lookup.compare_origins("7601", "India, Indai")
        self.assertEqual(len(r["lines"][0]["by_country"]), 1)
        self.assertIn("India", r["countries_not_recognised"][0])
        for bad in ([], None, ["India"] * 31, 5):
            with self.assertRaises(InputError):
                lookup.compare_origins("7601", bad)


if __name__ == "__main__":
    unittest.main()
