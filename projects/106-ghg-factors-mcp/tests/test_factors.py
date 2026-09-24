"""Queries on a snapshot built offline from the recorded fixtures."""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import SnapshotTestCase, IsolatedTestCase  # noqa: E402

from ghg_factors_mcp import __main__ as cli  # noqa: E402
from ghg_factors_mcp import factors as F  # noqa: E402

DIESEL_L = "desnz-2026:1_101_1011_8_1"
GAS_GROSS = "desnz-2026:1_100_1004_6_1"
OGL = "Contains public sector information licensed under the Open Government Licence v3.0."


class Search(SnapshotTestCase):
    def test_diesel_per_litre_with_gas_split(self):
        r = F.search_factors("DESNZ 2026 factor for diesel (average biofuel blend) per litre, split into CO2, CH4 and N2O",
                             unit="litres")
        first = r["results"][0]
        self.assertEqual((first["factor_id"], first["scope"], first["region"], first["value"]),
                         (DIESEL_L, "Scope 1", "UK", 2.58354))
        self.assertEqual(first["unit"], "kg CO2e per litres")
        self.assertEqual({g: v["value"] for g, v in first["gases"].items()}, {"CO2": 2.55035, "CH4": 0.00029, "N2O": 0.0329})
        self.assertEqual(r["query"]["year"], 2026)
        self.assertTrue(r["attribution"][0].endswith(OGL))
        self.assertIn("UK-specific", r["note"])
        self.assertTrue(all(x["region"] == "UK" for x in r["results"]))

    def test_year_and_scope_written_in_the_text(self):
        r = F.search_factors("scope 3 diesel average biofuel blend 2025", unit="litre")
        self.assertEqual([x["factor_id"] for x in r["results"]], ["desnz-2025:11_101_1011_8_1"])

    def test_unit_filter_keeps_net_and_gross_apart(self):
        ids = [x["factor_id"] for x in F.search_factors("natural gas", unit="kWh (Gross CV)")["results"]]
        self.assertEqual(ids, [GAS_GROSS])
        both = {x["activity_unit"] for x in F.search_factors("natural gas", unit="kWh")["results"]}
        self.assertEqual(both, {"kWh (Gross CV)", "kWh (Net CV)"})
        mwh = F.search_factors("natural gas", unit="MWh")
        self.assertIn("same kind", mwh["note"])

    def test_en_dash_label_matches_a_hyphen_query(self):
        r = F.search_factors("crude tanker 120,000-199,999 dwt")
        self.assertEqual(r["results"][0]["name"],
                         "Freighting goods > Sea tanker > Crude tanker > 120,000–199,999 dwt")

    def test_blank_rows_come_back_as_null_with_a_note(self):
        hit = F.search_factors("hotel stay argentina")["results"][0]
        self.assertIsNone(hit["value"])
        self.assertIn("blank", hit["notes"][0])

    def test_unknown_words_empty_the_result_and_are_named(self):
        r = F.search_factors("unobtainium smelting")
        self.assertEqual((r["matches"], r["results"], r["query"]["unknown_words"]), (0, [], ["unobtainium", "smelting"]))
        r = F.search_factors("diesel hovercraft")  # one unknown word is enough: no diesel rows pretending to fit
        self.assertEqual((r["results"], r["query"]["unknown_words"]), ([], ["hovercraft"]))
        self.assertIn("'hovercraft'", r["note"])

    def test_words_about_the_request_are_not_matched(self):
        r = F.search_factors("please give me the natural gas kWh gross numbers")
        self.assertEqual(r["results"][0]["factor_id"], GAS_GROSS)
        self.assertEqual(r["query"]["words"], ["natural", "gas", "kwh", "gross"])

    def test_refusals(self):
        for kwargs, pattern in (({"text": "  "}, "empty"), ({"text": "CO2 factor per"}, "no searchable words"),
                                ({"text": "diesel", "year": 2019}, "not in the snapshot"),
                                ({"text": "diesel", "scope": "4"}, "unknown scope"),
                                ({"text": "diesel", "limit": "many"}, "limit")):
            with self.assertRaisesRegex(F.Refused, pattern):
                F.search_factors(**kwargs)


class GetFactor(SnapshotTestCase):
    def test_total_with_gases_and_the_other_year(self):
        r = F.get_factor(DIESEL_L)
        self.assertTrue(r["found"])
        self.assertEqual(r["gases"]["N2O"]["factor_id"], "desnz-2026:1_101_1011_8_4")
        prev = r["same_id_other_years"][0]
        self.assertEqual((prev["factor_id"], prev["value"], prev["change_to_this_year_pct"]),
                         ("desnz-2025:1_101_1011_8_1", 2.57082, 0.49))
        self.assertEqual(len(r["attribution"]), 2)

    def test_renamed_between_years(self):
        r = F.get_factor("desnz-2026:5_304_3119_4_1")
        self.assertIn("HGV (non-refrigerated, all diesel)", r["name"])
        self.assertIn("HGV (all diesel)", r["same_id_other_years"][0]["published_name"])

    def test_gas_row_points_back_to_its_total(self):
        r = F.get_factor("desnz-2026:1_101_1011_8_3")
        self.assertEqual((r["gas"], r["total"]["factor_id"]), ("CH4", DIESEL_L))
        self.assertEqual(sorted(r["other_gases"]), ["CO2", "N2O"])

    def test_bare_id_is_read_as_the_newest_set_and_says_so(self):
        r = F.get_factor("1_101_1011_8_1")
        self.assertEqual(r["factor_id"], DIESEL_L)
        self.assertIn("newest set", r["notes"][0])

    def test_uk_electricity_notes(self):
        r = F.get_factor("desnz-2026:7_400_4000_5_1")
        text = " ".join(r["notes"])
        self.assertIn("location-based", text)
        self.assertIn("not a market-based", text)
        self.assertIn("based on 2025 data", text)

    def test_unknown_ids(self):
        for fid in ("desnz-2026:9_999_9999_9_9", "desnz-2019:1_101_1011_8_1", "ember:DEU", "", "x" * 500):
            r = F.get_factor(fid)
            self.assertFalse(r["found"], fid)
            self.assertTrue(r["reason"])

    def test_grid_ids(self):
        self.assertEqual(F.get_factor("ember:POL:2025")["value"], 590.886)
        self.assertEqual(F.get_factor("uba:DEU:2025")["value"], 344.0)


class Convert(SnapshotTestCase):
    def test_diesel_litres_exact_arithmetic(self):
        r = F.convert(1000, "litres", DIESEL_L)
        self.assertEqual((r["result"]["value_text"], r["result"]["unit"]), ("2583.54", "kg CO2e"))
        self.assertEqual(r["arithmetic"], "1000 litres × 2.58354 kg CO2e per litres = 2583.54 kg CO2e")
        self.assertEqual({g: v["value"] for g, v in r["gases"].items()}, {"CO2": 2550.35, "CH4": 0.29, "N2O": 32.9})
        self.assertIn("derived", r)
        self.assertTrue(r["attribution"][0].endswith(OGL))

    def test_float_amounts_do_not_drift(self):
        r = F.convert(0.1, "litre", DIESEL_L)
        self.assertEqual(r["result"]["value_text"], "0.258354")
        self.assertEqual(F.convert("1e3", "L", DIESEL_L)["result"]["value_text"], "2583.54")

    def test_kwh_against_gross_cv_is_refused_with_alternatives(self):
        with self.assertRaises(F.Refused) as ctx:
            F.convert(1000, "kWh", GAS_GROSS)
        msg, details = str(ctx.exception), ctx.exception.details
        self.assertIn("unit mismatch", msg)
        self.assertIn("unit='kWh (Gross CV)'", msg)
        self.assertEqual({a["activity_unit"] for a in details["alternatives"]},
                         {"cubic metres", "kWh (Net CV)", "tonnes"})

    def test_other_units_are_refused_not_guessed(self):
        for unit in ("gallons", "km", "kg", "GJ", "MWh (Net CV)"):
            with self.assertRaises(F.Refused, msg=unit):
                F.convert(10, unit, GAS_GROSS)

    def test_exact_decimal_steps_are_shown(self):
        r = F.convert(12.5, "MWh (gross cv)", GAS_GROSS)
        self.assertEqual(r["result"]["value_text"], "2278.875")
        self.assertTrue(r["arithmetic"].startswith("12.5 MWh (gross cv) = 12500 kWh (Gross CV); "))
        self.assertEqual(F.convert(2, "tonne", "desnz-2026:1_101_1011_15_1")["result"]["value_text"], "6208.32924")
        self.assertEqual(F.convert(1, "m3", DIESEL_L)["result"]["value_text"], "2583.54")

    def test_gas_parts_that_do_not_add_up_are_explained(self):
        # Diesel per kWh (Gross CV): DESNZ publishes 0.2452 in total and 0.24207 + 0.00002 + 0.0031 = 0.24519.
        r = F.convert(1000, "kWh (Gross CV)", "desnz-2026:1_101_1011_6_1")
        self.assertEqual(r["result"]["value_text"], "245.2")
        self.assertIn("add up to 245.19", r["gases_note"])
        self.assertNotIn("gases_note", F.convert(1, "tonnes", "desnz-2026:1_101_1011_15_1"))

    def test_secr_rows_give_energy(self):
        r = F.convert(100, "km", "desnz-2026:6_300_3000_4_5")
        self.assertEqual((r["result"]["value_text"], r["result"]["unit"]), ("42.076", "kWh (Net CV)"))
        self.assertIn("not an emission factor", " ".join(r["notes"]))

    def test_bad_amounts(self):
        for amount in ("1,000", "12 litres", True, None, float("nan"), float("inf"), [1]):
            with self.assertRaises(F.Refused, msg=repr(amount)):
                F.convert(amount, "litres", DIESEL_L)

    def test_blank_factor_is_refused(self):
        with self.assertRaisesRegex(F.Refused, "published blank"):
            F.convert(3, "Room per night", "desnz-2026:29_600_4002_13_1")

    def test_grid_conversions(self):
        r = F.convert(2.5, "MWh", "ember:POL:2025")
        self.assertEqual((r["result"]["value_text"], r["result"]["unit"]), ("1477.215", "kg CO2e"))
        self.assertIn("1477215 g CO2e", r["arithmetic"])
        self.assertIn("location-based", r["notes"][0])
        u = F.convert(1000, "kWh", "uba:DEU:2025")
        self.assertEqual((u["result"]["value_text"], u["result"]["unit"]), ("344", "kg CO2"))
        with self.assertRaisesRegex(F.Refused, "per kWh"):
            F.convert(1, "litres", "ember:POL:2025")
        with self.assertRaisesRegex(F.Refused, "without an emissions intensity"):
            F.convert(1, "kWh", "ember:LSO:2024")


class Grid(SnapshotTestCase):
    def test_poland_2025(self):
        r = F.grid_intensity("Poland", 2025)
        self.assertEqual((r["factor_id"], r["value"], r["unit"]), ("ember:POL:2025", 590.886, "g CO2e/kWh"))
        self.assertIn("location-based", r["scope2"])
        self.assertIn("not a market-based factor", r["scope2"])
        self.assertIn("lifecycle", r["basis"])
        self.assertIn("CC BY 4.0", r["attribution"][0])

    def test_every_grid_answer_says_location_based(self):
        for args in (("Germany", 2025, "all"), ("DEU", None, "uba"), ("EU", 2025, "ember"), ("UK", None, "ember")):
            r = F.grid_intensity(*args)
            for a in r.get("answers", [r]):
                self.assertTrue(a["scope2"].startswith("Location-based"), args)
                self.assertNotIn("market-based factor:", a["scope2"].replace("not a market-based factor:", ""))

    def test_gap_year_is_not_filled(self):
        r = F.grid_intensity("Lesotho", 2024)
        self.assertFalse(r["found"])
        self.assertIn("No other year is substituted", r["reason"])
        self.assertEqual([n["year"] for n in r["nearest_years_with_value"]], [2022])

    def test_no_year_means_latest_with_a_value(self):
        r = F.grid_intensity("lesotho")
        self.assertEqual(r["year"], 2022)
        self.assertIn("latest year with a value", r["notes"][0])

    def test_unicode_and_aliases(self):
        for name in ("Türkiye", "TURKIYE", "türkiye", "Turkey", "TUR"):
            self.assertEqual(F.grid_intensity(name, 2025)["factor_id"], "ember:TUR:2025", name)
        uk = F.grid_intensity("UK", 2025)
        self.assertEqual(uk["factor_id"], "ember:GBR:2025")
        self.assertNotIn("other_areas_matching", uk)  # "Ukraine" starts with "uk" but is not a match
        self.assertEqual(uk["see_also"]["factor_id"], "desnz-2026:7_400_4000_5_1")

    def test_ambiguous_and_unknown_names(self):
        self.assertEqual(F.grid_intensity("Congo")["other_areas_matching"], ["Congo (DRC)"])
        r = F.grid_intensity("Atlantis")
        self.assertFalse(r["found"])
        self.assertEqual(F.grid_intensity("Pola")["did_you_mean"], ["Poland"])
        self.assertEqual(F.grid_intensity("PL")["did_you_mean"], [])  # two-letter codes are not guessed

    def test_uba_germany_only(self):
        r = F.grid_intensity("Germany", 2025, "uba")
        self.assertEqual((r["value"], r["unit"]), (344.0, "g CO2/kWh"))
        self.assertIn("CO2 only", r["basis"])
        self.assertIn("Umweltbundesamt", r["attribution"][0])
        self.assertFalse(F.grid_intensity("Poland", 2025, "uba")["found"])
        self.assertFalse(F.grid_intensity("Germany", 2022, "uba")["found"])
        with self.assertRaises(F.Refused):
            F.grid_intensity("Germany", 2025, "entsoe")


class Sources(SnapshotTestCase):
    def test_sources_list_licences_and_exclusions(self):
        r = F.sources()
        self.assertEqual([s["id"] for s in r["sources"]], ["desnz-2026", "desnz-2025", "ember", "uba"])
        self.assertTrue(all(s["attribution"] and s["raw_sha256"] and s["retrieved"] for s in r["sources"]))
        self.assertEqual([x["source"].split(" ")[0] for x in r["excluded"]], ["IPCC", "PCAF", "IEA-EDGAR"])


class MissingSnapshot(IsolatedTestCase):
    def test_empty_data_dir(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"GHG_FACTORS_DATA": d}):
            F._cache.clear()
            with self.assertRaisesRegex(F.SnapshotError, "refresh"):
                F.search_factors("diesel")
            with mock.patch("sys.stderr", new_callable=io.StringIO) as err:
                self.assertEqual(cli.main(["get", DIESEL_L]), 2)
            self.assertIn("no readable snapshot", err.getvalue())
        F._cache.clear()

    def test_corrupt_manifest(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"GHG_FACTORS_DATA": d}):
            Path(d, "manifest.json").write_text('{"sources": [1, 2]}')
            F._cache.clear()
            with self.assertRaises(F.SnapshotError):
                F.sources()
        F._cache.clear()


class CommandLine(SnapshotTestCase):
    def run_cli(self, *argv):
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            code = cli.main(list(argv))
        return code, out.getvalue()

    def test_text_and_json_and_exit_codes(self):
        code, text = self.run_cli("convert", "1000", "litres", DIESEL_L)
        self.assertEqual(code, 0)
        self.assertIn("2583.54 kg CO2e", text)
        self.assertIn(OGL, text)
        code, text = self.run_cli("convert", "1000", "kWh", GAS_GROSS, "--json")
        self.assertEqual((code, json.loads(text)["refused"]), (1, True))
        code, text = self.run_cli("grid", "Lesotho", "--year", "2024")
        self.assertEqual(code, 1)
        self.assertIn("nearest with a value: 2022", text)
        code, text = self.run_cli("search", "unobtainium")
        self.assertEqual(code, 1)
        code, text = self.run_cli("grid", "Türkiye", "--json")
        self.assertEqual(json.loads(text)["area"], "Türkiye")


if __name__ == "__main__":
    import unittest
    unittest.main()
