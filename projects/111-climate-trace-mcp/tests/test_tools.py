"""The six tools against recorded answers: labels on every figure, and the failure modes seen live."""
import copy
import unittest
from datetime import date

try:
    from . import ctfixtures as fx
except ImportError:
    import ctfixtures as fx

from climate_trace_mcp import provenance as prov
from climate_trace_mcp.client import ApiError, Client, NotFound, RateLimited
from climate_trace_mcp.countries import CountryError
from climate_trace_mcp.tools import Service, ToolError, _lei_ok

TODAY = date(2026, 9, 24)
ATTRIBUTION = "Source: Climate TRACE (climatetrace.org), CC BY 4.0, retrieved 2026-09-24"


class ToolTest(fx.HomeIsolated):
    def setUp(self):
        super().setUp()
        self.srv = fx.FixtureServer().__enter__()
        self.addCleanup(self.srv.__exit__, None, None, None)
        fx.standard_routes(self.srv)
        self.client = Client(base=self.srv.base, timeout=2, today=lambda: "2026-09-24")
        self.svc = Service(client=self.client, today=lambda: TODAY)

    def assertLabelled(self, fig, year, gas="co2e_100yr"):
        """The contract: value, unit, gas and GWP horizon, year, modelled, source dataset."""
        self.assertEqual(fig["estimate_type"], "modelled")
        self.assertEqual(fig["gas"], gas)
        self.assertEqual(fig["unit"], prov.GASES[gas]["unit"])
        self.assertEqual(fig["gwp_horizon"], prov.GASES[gas]["gwp_horizon"])
        self.assertEqual(fig["year"], year)
        self.assertTrue(fig["source_dataset"].startswith("Climate TRACE"))
        self.assertIn("value", fig)


class SearchAssetsTest(ToolTest):
    def test_german_steel_plants_2024(self):
        res = self.svc.search_assets(country="Germany", subsector="iron-and-steel", year=2024, limit=5)
        self.assertEqual(self.srv.requests[0]["query"], {"year": "2024", "gas": "co2e_100yr", "gadmId": "DEU",
                                                         "subsectors": "iron-and-steel", "limit": "5"})
        self.assertEqual(res["count"], 5)
        top = res["assets"][0]
        self.assertEqual((top["asset_id"], top["name"]), (1566771, "ThyssenKrupp Steel Duisburg steel plant"))
        self.assertAlmostEqual(top["emissions"]["value"], 15212775.994, places=2)
        self.assertEqual(top["emissions_factor"], {"value": 1.9, "unit": "t of CO2e_100yr per t of steel"})
        for a in res["assets"]:
            self.assertLabelled(a["emissions"], 2024)
            self.assertIn("TransitionZero", a["emissions"]["source_dataset"])
        self.assertEqual(res["attribution"], ATTRIBUTION)
        self.assertEqual(res["estimate_type"], "modelled")
        self.assertIn("modelled estimates", res["caveat"])
        self.assertTrue(res["licence"].startswith("CC BY 4.0"))
        self.assertNotIn("licence_note", res)
        self.assertEqual(res["source_datasets"]["iron-and-steel"]["data_leads_as_of"], "2026-09-24")
        # Unicode names arrive intact.
        self.assertIn("Hüttenwerke Krupp Mannesmann (HKM) steel plant", [a["name"] for a in res["assets"]])

    def test_name_search_is_local_and_accent_insensitive(self):
        self.srv.route("/sources", fx.fixture("sources_DEU_iron-and-steel_2024.json"),
                       {"year": 2024, "gas": "co2e_100yr", "gadmId": "DEU", "subsectors": "iron-and-steel",
                        "limit": 100, "offset": 0})
        cases = {"Hüttenwerke Mannesmann": [1566772], "Huettenwerke HKM": [1566772],
                 "huttenwerke": [1566772, 1566773]}  # also "AG der Dillinger Hüttenwerke"
        for q, ids in cases.items():
            res = self.svc.search_assets(name=q, country="DE", subsector="iron-and-steel", year=2024)
            self.assertEqual([a["asset_id"] for a in res["assets"]], ids, q)
            self.assertTrue(res["complete"])
        self.assertTrue(all("name" not in r["query"] for r in self.srv.requests))

    def test_name_search_matches_transliterated_polish_names(self):
        self.srv.route("/sources", fx.fixture("sources_POL_electricity-generation_2024.json"),
                       {"year": 2024, "gas": "co2e_100yr", "gadmId": "POL", "subsectors": "electricity-generation",
                        "limit": 100, "offset": 0})
        res = self.svc.search_assets(name="Bełchatów", country="Poland", subsector="electricity-generation", year=2024)
        self.assertEqual([a["name"] for a in res["assets"]], ["Belchatow power station"])
        self.assertEqual(res["assets"][0]["asset_type"], "coal")

    def test_name_search_stops_after_500_assets_and_says_so(self):
        base = fx.load_json("sources_DEU_iron-and-steel_2024.json")[0]
        for page in range(6):
            rows = []
            for i in range(100):
                r = dict(base, id=page * 100 + i, name="Plant %d" % (page * 100 + i))
                rows.append(r)
            self.srv.route("/sources", fx.Reply(rows), {"year": 2024, "gas": "co2e_100yr", "limit": 100, "offset": page * 100})
        res = self.svc.search_assets(name="nowhere", year=2024)
        self.assertEqual((res["count"], res["scanned"], res["complete"]), (0, 500, False))
        self.assertEqual(len(self.srv.requests), 5)
        self.assertTrue(any("top 500" in n for n in res["notes"]))

    def test_invalid_input_sends_nothing(self):
        bad = [dict(year=2019), dict(year=2027), dict(year="2024x"), dict(limit=0), dict(limit=101), dict(limit=True),
               dict(country="Atlantis"), dict(subsector="Iron and steel; DROP"), dict(name="!!!"),
               dict(sector="power", subsector="iron-and-steel")]
        for kwargs in bad:
            with self.assertRaises((ToolError, CountryError), msg=kwargs):
                self.svc.search_assets(**kwargs)
        self.assertEqual(self.srv.requests, [])

    def test_unknown_sector_is_checked_against_the_api_list_and_never_sent(self):
        with self.assertRaises(ToolError) as cm:
            self.svc.search_assets(country="DE", sector="nonsense", year=2024)
        self.assertIn("valid sectors", cm.exception.message)
        self.assertEqual(self.srv.paths(), ["/v7/definitions/sectors"])
        self.assertTrue(all("nonsense" not in str(r["query"]) for r in self.srv.requests))

    def test_rejected_input_is_echoed_with_secrets_masked(self):
        for kwargs in (dict(subsector="token=abc123"), dict(limit="--password hunter2"), dict(year="https://u:p4ss@x.org")):
            with self.assertRaises(ToolError) as cm:
                self.svc.search_assets(**kwargs)
            for secret in ("abc123", "hunter2", "p4ss"):
                self.assertNotIn(secret, cm.exception.message)
        self.assertEqual(self.srv.requests, [])

    def test_new_subsector_in_the_live_list_is_accepted(self):
        self.srv.route("/definitions/subsectors", fx.Reply(fx.load_json("definitions_subsectors.json") + ["hydrogen-plants"]))
        self.srv.route("/sources", fx.fixture("null.json"), {"year": 2024, "gas": "co2e_100yr", "subsectors": "hydrogen-plants", "limit": 20})
        res = self.svc.search_assets(subsector="hydrogen-plants", year=2024)
        self.assertEqual(res["count"], 0)
        self.assertEqual(res["query"]["subsector"], "hydrogen-plants")

    def test_null_answer_is_an_empty_result_with_a_reason(self):
        self.srv.route("/sources", fx.fixture("null.json"),
                       {"year": 2024, "gas": "co2e_100yr", "gadmId": "POL", "subsectors": "other-energy-use", "limit": 20})
        res = self.svc.search_assets(country="POL", subsector="other-energy-use", year=2024)
        self.assertEqual(res["assets"], [])
        self.assertTrue(any("no asset-level data for other-energy-use" in n for n in res["notes"]))
        self.assertEqual(res["attribution"], ATTRIBUTION)

    def test_edgar_data_lead_record_flags_non_commercial_terms(self):
        self.srv.route("/sources", fx.fixture("sources_DEU_cropland-fires_2024.json"),
                       {"year": 2024, "gas": "co2e_100yr", "gadmId": "DEU", "subsectors": "cropland-fires", "limit": 2})
        res = self.svc.search_assets(country="DEU", subsector="cropland-fires", year=2024, limit=2)
        a = res["assets"][0]
        self.assertEqual(a["source_type"], "gadm-aggregation")
        self.assertIsNone(a["asset_type"])  # the API sends ""
        self.assertIn("data leads named by the API: EDGAR", a["emissions"]["source_dataset"])
        self.assertTrue(a["emissions"]["non_commercial_terms_may_apply"])
        self.assertIn("CC BY-NC-ND 4.0", res["licence_note"])
        self.assertEqual(res["source_datasets"]["cropland-fires"]["edgar_named_by"], "API data lead")

    def test_current_year_is_marked_partial(self):
        self.srv.route("/sources", fx.fixture("sources_DEU_iron-and-steel_2024.json"),
                       {"year": 2026, "gas": "co2e_100yr", "gadmId": "DEU", "limit": 20})
        res = self.svc.search_assets(country="DEU", year=2026)
        self.assertTrue(any("current calendar year" in n for n in res["notes"]))

    def test_schema_drift_unknown_fields_ignored_missing_fields_reported(self):
        rows = copy.deepcopy(fx.load_json("sources_DEU_iron-and-steel_2024.json")[:3])
        rows[0]["newField"] = {"nested": True}
        del rows[1]["emissionsQuantity"]
        rows[2]["emissionsQuantity"] = "8456275"
        rows[2]["gas"] = "co2"
        self.srv.route("/sources", fx.Reply(rows), {"year": 2024, "gas": "co2e_100yr", "limit": 3})
        res = self.svc.search_assets(year=2024, limit=3)
        a0, a1, a2 = res["assets"]
        self.assertNotIn("newField", a0)
        self.assertNotIn("missing_fields", a0)
        self.assertIsNone(a1["emissions"]["value"])
        self.assertIn("emissionsQuantity", a1["missing_fields"])
        self.assertIn("emissionsQuantity (not a number)", a2["missing_fields"])
        self.assertTrue(any(m.startswith("gas (the API answered co2") for m in a2["missing_fields"]))

    def test_a_non_list_answer_is_a_bad_payload(self):
        self.srv.route("/sources", fx.Reply({"unexpected": "object"}), {"year": 2024, "gas": "co2e_100yr", "limit": 20})
        with self.assertRaises(ApiError) as cm:
            self.svc.search_assets(year=2024)
        self.assertEqual(cm.exception.kind, "bad_payload")

    def test_rate_limit_reaches_the_caller_with_retry_after(self):
        # Synthetic 429, never provoked against the real API.
        self.srv.route("/sources", fx.Reply({"detail": "slow down"}, 429, headers={"Retry-After": "12"}))
        with self.assertRaises(RateLimited) as cm:
            self.svc.search_assets(year=2024)
        self.assertEqual(cm.exception.as_dict()["retry_after"], "12")


class AssetTest(ToolTest):
    def test_asset_series_with_owners(self):
        res = self.svc.asset(1566771, years="2022-2024")
        self.assertEqual([e["year"] for e in res["emissions"]], [2022, 2023, 2024])
        for e in res["emissions"]:
            self.assertLabelled(e, e["year"])
            self.assertEqual(e["confidence"], "medium")
            self.assertEqual(e["subsector_rank_global"], 25)
        self.assertAlmostEqual(res["emissions"][2]["value"], 15212775.994, places=2)
        self.assertEqual(res["years_without_data"], [])
        self.assertEqual(res["owners"], [{"name": "Thyssenkrupp Steel Europe AG", "climate_trace_owner_id": "E100001000542",
                                          "lei": None, "lei_source": None}])
        self.assertIn("4 entries, 1 distinct", res["owners_note"])
        self.assertEqual((res["country"], res["country_name"]), ("DEU", "Germany"))
        self.assertEqual(res["attribution"], ATTRIBUTION)
        # The range totals sum capacity over years; they are deliberately not passed on.
        self.assertNotIn("totals", res)

    def test_a_year_without_an_entry_is_listed_not_zero(self):
        data = fx.load_json("source_1566771_2022-2024.json")
        data["emissions"] = [e for e in data["emissions"] if e["year"] != 2023]  # constructed: 2023 dropped
        self.srv.route("/sources/1566771", fx.Reply(data), {"start": 2022, "end": 2024, "timeGranularity": "year", "gas": "co2e_100yr"})
        res = self.svc.asset(1566771, years=[2022, 2023, 2024])
        self.assertEqual(res["years_without_data"], [2023])
        self.assertEqual([e["year"] for e in res["emissions"]], [2022, 2024])
        self.assertTrue(any("not a zero" in n for n in res["notes"]))

    def test_record_from_an_edgar_led_subsector_with_null_owners(self):
        res = self.svc.asset("10936838", years="2023-2024")
        self.assertEqual(res["subsector"], "cropland-fires")
        self.assertEqual(res["owners"], [])
        self.assertTrue(res["source_dataset"]["non_commercial_terms_may_apply"])
        self.assertIn("IEA-EDGAR CO2", res["licence_note"])
        self.assertEqual(res["emissions"][0]["confidence"], "very low")

    def test_wrong_typed_fields_are_drift_not_a_crash(self):
        data = fx.load_json("source_1566771_2022-2024.json")
        data.update(emissions=5, confidence="high", subsectorRanks={"2024": 1}, owners="Thyssenkrupp", name=["x"])
        self.srv.route("/sources/1566771", fx.Reply(data), {"start": 2024, "end": 2024, "timeGranularity": "year", "gas": "co2e_100yr"})
        res = self.svc.asset(1566771, years=2024)
        self.assertEqual((res["emissions"], res["years_without_data"], res["owners"]), ([], [2024], []))
        self.assertIsNone(res["name"])

    def test_not_found(self):
        with self.assertRaises(NotFound) as cm:
            self.svc.asset(999999999, years=2024)
        self.assertIn("ID not found 999999999", cm.exception.message)

    def test_invalid_input_sends_nothing(self):
        for kwargs in (dict(asset_id=0), dict(asset_id="12a"), dict(asset_id=1.5), dict(asset_id=1, years="2020"),
                       dict(asset_id=1, years="2024-2022"), dict(asset_id=1, years="last year"),
                       dict(asset_id=1, gas="pm2_5"), dict(asset_id=1, years=[2021, 2031])):
            with self.assertRaises(ToolError, msg=kwargs):
                self.svc.asset(**kwargs)
        self.assertEqual(self.srv.requests, [])


class CountryEmissionsTest(ToolTest):
    def test_poland_power_2020_to_2024(self):
        res = self.svc.country_emissions("Poland", sector="power", years="2020-2024")
        self.assertEqual(len(self.srv.requests), 5)
        self.assertTrue(all(r["query"]["gadmId"] == "POL" and r["query"]["sectors"] == "power" for r in self.srv.requests))
        totals = {y["year"]: y["total"]["value"] for y in res["years"]}
        self.assertAlmostEqual(totals[2024], 127313186.463, places=2)
        self.assertAlmostEqual(totals[2020], 145785559.4, places=0)
        for y in res["years"]:
            self.assertLabelled(y["total"], y["year"])
            self.assertEqual(y["months_with_data"], 12)
            self.assertEqual({s["subsector"] for s in y["subsectors"]}, {"electricity-generation", "heat-plants", "other-energy-use"})
        oeu = res["source_datasets"]["other-energy-use"]
        self.assertEqual([d["dataset"] for d in oeu["external_datasets"]], ["EDGAR"])
        self.assertTrue(oeu["non_commercial_terms_may_apply"])
        self.assertTrue(res["non_commercial_terms_may_apply"])
        self.assertIn("other-energy-use", res["licence_note"])
        self.assertEqual(res["external_dataset_terms"]["EDGAR"]["licence_source"], "https://edgar.jrc.ec.europa.eu/dataset_ghg2026")
        self.assertFalse(res["source_datasets"]["electricity-generation"]["non_commercial_terms_may_apply"])
        self.assertEqual(res["attribution"], ATTRIBUTION)

    def test_ch4_carries_no_edgar_co2_flag(self):
        d = prov.describe(self.svc.snapshot, "other-energy-use", "ch4", "country")
        self.assertFalse(d["non_commercial_terms_may_apply"])
        self.assertEqual(d["external_datasets"][0]["dataset"], "EDGAR")
        # At asset level the terms' country-level datasets do not apply.
        self.assertEqual(prov.describe(self.svc.snapshot, "other-energy-use", "co2e_100yr", "source")["external_datasets"], [])

    def test_ignored_sector_filter_is_caught(self):
        # Real answer to sectors=nonsense: the whole country. Served here for sectors=power.
        self.srv.route("/sources/emissions", fx.fixture("emissions_POL_ignored-sector_2024.json"),
                       {"year": 2024, "gas": "co2e_100yr", "gadmId": "POL", "sectors": "power"})
        with self.assertRaises(ToolError) as cm:
            self.svc.country_emissions("POL", sector="power", years=2024)
        self.assertEqual(cm.exception.kind, "unexpected_response")
        self.assertIn("not the power total", cm.exception.message)

    def test_zero_without_monthly_values_is_no_data(self):
        # Real answer for 2014, before the API's data starts, served for 2015.
        self.srv.route("/sources/emissions", fx.fixture("emissions_POL_power_2014.json"),
                       {"year": 2015, "gas": "co2e_100yr", "gadmId": "POL", "sectors": "power"})
        res = self.svc.country_emissions("POL", sector="power", years="2015")
        self.assertIsNone(res["years"][0]["total"])
        self.assertIn("no monthly values", res["years"][0]["note"])

    def test_current_year_is_partial(self):
        self.srv.route("/sources/emissions", fx.fixture("emissions_POL_power_2026.json"),
                       {"year": 2026, "gas": "co2e_100yr", "gadmId": "POL", "sectors": "power"})
        res = self.svc.country_emissions("PL", sector="power", years=2026)
        y = res["years"][0]
        self.assertEqual((y["months_with_data"], y["partial_year"]), (6, True))
        self.assertTrue(any("current calendar year" in n for n in res["notes"]))

    def test_whole_country_breaks_down_by_sector_and_flags_external_datasets(self):
        self.srv.route("/sources/emissions", fx.fixture("emissions_POL_all_2024.json"),
                       {"year": 2024, "gas": "co2e_100yr", "gadmId": "POL"})
        res = self.svc.country_emissions("POL", years=2024)
        y = res["years"][0]
        self.assertEqual(res["breakdown_by"], "sector")
        self.assertIn("forestry-and-land-use", {s["sector"] for s in y["sectors"]})
        ext = {s["subsector"] for s in y["external_dataset_subsectors"]}
        self.assertTrue({"other-energy-use", "fluorinated-gases", "railways", "rice-cultivation"} <= ext)
        self.assertNotIn("iron-and-steel", res["source_datasets"])  # own models are summarised, not repeated
        self.assertIn("FAOSTAT", res["external_dataset_terms"])
        self.assertTrue(any("forestry-and-land-use" in n for n in res["notes"]))

    def test_totals_for_another_gas_or_of_the_wrong_type(self):
        data = fx.load_json("emissions_POL_power_2024.json")
        data["totals"]["summaries"][0]["gas"] = "co2"
        self.srv.route("/sources/emissions", fx.Reply(data), {"year": 2024, "gas": "co2e_100yr", "gadmId": "POL", "sectors": "power"})
        y = self.svc.country_emissions("POL", sector="power", years=2024)["years"][0]
        self.assertIsNone(y["total"])
        self.assertIn("another gas (co2)", y["note"])
        data["totals"] = {"summaries": 7, "timeseries": "monthly"}
        self.srv.route("/sources/emissions", fx.Reply(data), {"year": 2023, "gas": "co2e_100yr", "gadmId": "POL", "sectors": "power"})
        y = self.svc.country_emissions("POL", sector="power", years=2023)["years"][0]
        self.assertIsNone(y["total"])

    def test_answer_for_another_country_is_refused(self):
        data = fx.load_json("emissions_POL_power_2024.json")
        data["location"] = {"name": "Germany", "gadmId": "DEU", "country": "DEU"}
        self.srv.route("/sources/emissions", fx.Reply(data), {"year": 2024, "gas": "co2e_100yr", "gadmId": "POL", "sectors": "power"})
        with self.assertRaises(ToolError) as cm:
            self.svc.country_emissions("POL", sector="power", years=2024)
        self.assertEqual(cm.exception.kind, "unexpected_response")

    def test_invalid_input_sends_nothing(self):
        for kwargs in (dict(country="POL", years="2014"), dict(country="POL", years="2015-2027"),
                       dict(country="POL", years="2000-2030"), dict(country="Narnia"), dict(country="POL", gas="co2e"),
                       dict(country="POL", sector="power,waste")):
            with self.assertRaises((ToolError, CountryError), msg=kwargs):
                self.svc.country_emissions(**kwargs)
        self.assertTrue(all(p == "/v7/definitions/sectors" for p in self.srv.paths()))


class OwnersTest(ToolTest):
    def test_owners_deduplicated_without_lei(self):
        self.srv.route("/sources/1566771", fx.fixture("source_1566771_2022-2024.json"),
                       {"start": 2021, "end": 2025, "timeGranularity": "year", "gas": "co2e_100yr"})
        res = self.svc.owners(1566771)
        self.assertEqual(len(res["owners"]), 1)
        self.assertIsNone(res["owners"][0]["lei"])
        self.assertEqual(res["ownership_shares"], "not provided by the API")
        self.assertTrue(any("not an LEI" in n for n in res["notes"]))
        self.assertIn("The API listed 4 owner entries for 1 distinct owner.", res["notes"])
        self.assertEqual(res["attribution"], ATTRIBUTION)

    def test_lei_shown_only_when_the_api_returns_a_valid_one(self):
        # Synthetic owner records: GLEIF's own published LEI, and the same with a wrong check digit.
        data = fx.load_json("source_1566771_2022-2024.json")
        data["owners"] = [{"id": "E1", "name": "Global Legal Entity Identifier Foundation", "lei": "506700GE1G29325QX363"},
                          {"id": "E2", "name": "Checksum Wrong GmbH", "lei": "506700GE1G29325QX364"}]
        self.srv.route("/sources/1566771", fx.Reply(data))
        res = self.svc.owners(1566771)
        self.assertEqual(res["owners"][0]["lei"], "506700GE1G29325QX363")
        self.assertEqual(res["owners"][0]["lei_source"], "Climate TRACE API field 'lei'")
        self.assertIsNone(res["owners"][1]["lei"])
        self.assertTrue(_lei_ok("506700GE1G29325QX363"))
        self.assertFalse(_lei_ok("E100001000542"))

    def test_null_and_missing_owners(self):
        data = fx.load_json("source_10936838_2023-2024.json")
        self.srv.route("/sources/10936838", fx.Reply(data))
        self.assertTrue(any("lists no owners" in n for n in self.svc.owners(10936838)["notes"]))
        del data["owners"]
        self.srv.route("/sources/10936839", fx.Reply(data))
        self.assertTrue(any("missing field" in n for n in self.svc.owners(10936839)["notes"]))


class ReferenceToolsTest(ToolTest):
    def test_sectors_matches_the_live_lists(self):
        res = self.svc.sectors()
        self.assertEqual(res["live_check"]["status"], "matches snapshot")
        power = next(s for s in res["sectors"] if s["sector"] == "power")
        subs = {s["subsector"]: s for s in power["subsectors"]}
        self.assertEqual(subs["other-energy-use"]["external_datasets_per_terms"], [{"dataset": "EDGAR", "scope": "country-level emissions estimates"}])
        self.assertIn("WattTime", subs["electricity-generation"]["data_leads"])
        self.assertEqual(res["snapshot_retrieved"], "2026-09-24")

    def test_sectors_reports_drift_and_unreachable_api(self):
        self.srv.route("/definitions/subsectors", fx.Reply(["iron-and-steel", "hydrogen-plants"]))
        res = self.svc.sectors()
        self.assertEqual(res["live_check"]["status"], "differs from snapshot")
        self.assertIn("hydrogen-plants", res["live_check"]["new_in_api"])
        self.assertIn("cement", res["live_check"]["no_longer_in_api"])
        offline = Service(client=Client(base=fx.closed_port_base(), timeout=1), today=lambda: TODAY)
        self.assertEqual(offline.sectors()["live_check"]["status"], "could not check")

    def test_sources_reads_the_live_api_version(self):
        res = self.svc.sources()
        self.assertEqual(res["api_version_live"], "7.2.0")
        self.assertEqual(res["attribution"], ATTRIBUTION)
        self.assertEqual(res["estimate_type"], "modelled")
        self.assertIn("with the exception of external datasets", res["licence"]["quote"])
        edgar = next(d for d in res["external_datasets"]["datasets"] if d["dataset"] == "EDGAR")
        self.assertIn("CC BY-NC-ND 4.0", edgar["licence"])
        self.assertIn("other-energy-use", edgar["subsectors"])
        self.assertTrue(any("company" in w for w in res["what_this_is_not"]))
        offline = Service(client=Client(base=fx.closed_port_base(), timeout=1), today=lambda: TODAY)
        res = offline.sources()
        self.assertIsNone(res["api_version_live"])
        self.assertIn("network_error", res["api_version_note"])

    def test_snapshot_unreadable_degrades_to_live_lists(self):
        svc = Service(client=self.client, snapshot=prov.Snapshot.load(self.home + "/missing.json"), today=lambda: TODAY)
        self.srv.route("/sources", fx.fixture("null.json"), {"year": 2024, "gas": "co2e_100yr", "sectors": "power", "limit": 20})
        res = svc.search_assets(sector="power", year=2024)
        self.assertEqual(res["count"], 0)
        self.assertIn("snapshot_error", svc.sectors())


if __name__ == "__main__":
    unittest.main()
