"""FIRDS answers: a hit with venues, a miss, paging, bond and derivative details, and drift in the payload."""
import copy

import fakenet
import support
from support import fm


class Hit(support.OfflineTest):
    def test_share_with_venues(self):
        r = fm.isin_lookup("DE0005140008")
        self.assertTrue(r["found"])
        inst = r["instrument"]
        # Two of the six live venue records use this name, the others one each.
        self.assertRemote(inst["full_name"], "DEUTSCHE BANK AG NAMENS-AKTIEN O.N.")
        self.assertEqual(inst["cfi_code"], "ESVUFR")
        self.assertEqual(inst["issuer_or_venue_operator_lei"], "7LTWFZYICNSX8D621K86")
        self.assertEqual(inst["notional_currency"], "EUR")
        self.assertEqual((inst["upcoming_rca"], inst["rca_mic"]), ("DE", "FRAA"))
        self.assertNotIn("details", inst)  # a share: the derivative sign flag "No" is not passed on
        s = r["venue_summary"]
        self.assertEqual((s["records"], s["not_terminated"], s["terminated"], s["cancelled"]), (8, 4, 2, 2))
        self.assertEqual(s["as_of"], "2026-09-24")
        self.assertEqual([v["mic"] for v in r["venues"]], ["CEUX", "JBUL", "RFQN", "XETA"])

    def test_far_future_termination_is_not_terminated(self):
        rfqn = [v for v in fm.isin_lookup("DE0005140008")["venues"] if v["mic"] == "RFQN"][0]
        self.assertEqual(rfqn["termination"], "9999-12-31T23:59:59Z")
        self.assertEqual(rfqn["state"], "not_terminated")
        self.assertEqual(rfqn["status"], "Modified")

    def test_dates_as_firds_gives_them(self):
        # Xetra reports 1899-12-31 for the approval and request dates; it is passed on unchanged.
        xeta = [v for v in fm.isin_lookup("DE0005140008")["venues"] if v["mic"] == "XETA"][0]
        self.assertEqual(xeta, {"mic": "XETA", "status": "Unchanged", "admission_or_first_trade": "1999-08-30T05:00:00Z",
                                "issuer_requested_admission": "Yes", "issuer_approval": "1899-12-31T23:00:00Z",
                                "admission_request": "1899-12-31T23:00:00Z", "publication_from": "2023-02-07T00:00:00Z",
                                "state": "not_terminated"})

    def test_include_terminated_lists_everything_in_order(self):
        r = fm.isin_lookup("DE0005140008", include_terminated=True)
        self.assertEqual([(v["mic"], v["state"]) for v in r["venues"]],
                         [("CEUX", "not_terminated"), ("JBUL", "not_terminated"), ("RFQN", "not_terminated"),
                          ("XETA", "not_terminated"), ("TNLK", "terminated"), ("XTXM", "terminated"),
                          ("BAAD", "cancelled"), ("VFSI", "cancelled")])
        self.assertEqual(r["venue_summary"]["listed"], "all")

    def test_attribution_and_disclaimer(self):
        r = fm.isin_lookup("DE0005140008")
        self.assertEqual(len(r["sources"]), 1)
        self.assertIn("Source: ESMA, Financial Instruments Reference Data System (FIRDS)", r["sources"][0])
        self.assertIn("retrieved 2026-09-24", r["sources"][0])
        self.assertTrue(r["disclaimer"].startswith(
            "This document has been drafted using material downloaded from ESMA’s website. ESMA does not endorse"))

    def test_one_request_with_the_register_default_filter(self):
        fm.isin_lookup("DE0005140008")
        self.assertEqual(self.net.routes(), ["firds/DE0005140008"])
        self.assertIn("fq=latest_received_flag%3A1", self.net.requests[0])
        self.assertTrue(self.net.user_agents[0].startswith("firds-mcp/"))

    def test_bond_details_under_esma_labels(self):
        r = fm.isin_lookup("XS1910948592")
        inst = r["instrument"]
        # "N.V.  LS-Notes" (BERB) and "N.V. LS-Notes" (DUSD) count as one name.
        self.assertRemote(inst["full_name"], "Volkswagen Intl Finance N.V. LS-Notes 2018(31)")
        details = inst["details"]
        self.assertEqual(details["Maturity date"], "2031-11-17T00:00:00Z")
        self.assertEqual(details["Fixed rate"], "4.125")
        self.assertEqual(details["Total issued nominal amount"], "450000000")
        self.assertEqual(details["Currency of nominal value"], "GBP")
        self.assertEqual(details["Seniority of the bond"], "SNDB")
        self.assertEqual(details["Seniority of the bond, meaning (RTS 23 field 23)"], "Senior Debt")
        self.assertNotIn("Strike price - Sign", details)
        # A termination date in 2031 is not a termination yet.
        states = {v["mic"]: v["state"] for v in fm.isin_lookup("XS1910948592", include_terminated=True)["venues"]}
        self.assertEqual(states, {"XLUX": "not_terminated", "DUSD": "not_terminated", "TWEM": "not_terminated",
                                  "BERB": "terminated", "MAEL": "terminated"})

    def test_derivative_whose_lei_is_the_venue_operator(self):
        r = fm.isin_lookup("DE000C1D9NG7", include_terminated=True)
        inst = r["instrument"]
        self.assertEqual(inst["issuer_or_venue_operator_lei"], "529900UT4DG0LG5R9O07")  # EUREX Frankfurt AG
        self.assertIn("venue operator", r["issuer_lei_note"])
        self.assertEqual(inst["details"]["Expiry date"], "2018-11-16T00:00:00Z")
        self.assertEqual(inst["details"]["Price multiplier"], "100")
        self.assertEqual(inst["details"][fm.DETAIL_FIELDS["drv_underlng_isin"]], "ES0113900J37")
        self.assertEqual(r["venues"][0]["state"], "terminated")
        self.assertEqual(fm.isin_lookup("DE000C1D9NG7")["venues"], [])

    def test_several_leis_across_venues_are_all_reported(self):
        payload = fakenet.fixture_json("firds/DE0005140008")
        payload["response"]["docs"][2]["lei"] = "529900NNUPAGGOMPXZ31"  # a changed copy, as a venue might send
        self.net.script("firds/DE0005140008", (200, payload, {}))
        r = fm.isin_lookup("DE0005140008")
        self.assertEqual(r["instrument"]["issuer_or_venue_operator_lei"], "7LTWFZYICNSX8D621K86")
        self.assertEqual(r["lei_reported_by_venues"], [{"lei": "7LTWFZYICNSX8D621K86", "records": 5},
                                                       {"lei": "529900NNUPAGGOMPXZ31", "records": 1}])

    def test_unicode_names_survive(self):
        payload = fakenet.fixture_json("firds/IE00B4L5Y983")
        for doc in payload["response"]["docs"]:
            if doc.get("gnr_full_name"):
                doc["gnr_full_name"] = "Société Générale Émission 株式会社"
        self.net.script("firds/IE00B4L5Y983", (200, payload, {}))
        self.assertRemote(fm.isin_lookup("IE00B4L5Y983")["instrument"]["full_name"],
                          "Société Générale Émission 株式会社")


class MissAndPaging(support.OfflineTest):
    def test_miss(self):
        r = fm.isin_lookup("XS0000000009")
        self.assertEqual(r["found"], False)
        self.assertIn("no current record", r["note"])
        self.assertIn("Source: ESMA", r["sources"][0])

    def test_all_records_cancelled(self):
        payload = fakenet.fixture_json("firds/DE0005140008")
        payload["response"]["docs"] = [d for d in payload["response"]["docs"] if d["status"] == "CANC"]
        payload["response"]["numFound"] = 2
        self.net.script("firds/DE0005140008", (200, payload, {}))
        r = fm.isin_lookup("DE0005140008")
        self.assertTrue(r["found"])
        self.assertIn("cancelled", r["note"])
        self.assertEqual(r["venue_summary"]["cancelled"], 2)

    def test_pages_until_the_cap(self):
        fm.FIRDS_ROWS, fm.FIRDS_MAX_PAGES = 4, 2
        r = fm.isin_lookup("DE0005140008", include_terminated=True)
        self.assertEqual(self.net.routes(), ["firds/DE0005140008_rows4_start0", "firds/DE0005140008_rows4_start4"])
        self.assertEqual(r["venue_summary"]["records"], 8)
        self.assertTrue(r["venue_summary"]["records_truncated"])
        self.assertEqual(r["venue_summary"]["records_found"], 92)
        self.assertEqual(self.sleeps, [0.5])  # half a second between ESMA requests


class Drift(support.OfflineTest):
    def assertSourceError(self, kind, isin="DE0005140008"):
        with self.assertRaises(fm.SourceError) as cm:
            fm.isin_lookup(isin)
        self.assertEqual(cm.exception.kind, kind)
        self.assertEqual(cm.exception.source, "ESMA")
        return cm.exception

    def test_no_response_object(self):
        payload = fakenet.fixture_json("firds/DE0005140008")
        payload["result"] = payload.pop("response")
        self.net.script("firds/DE0005140008", (200, payload, {}))
        self.assertIn("undocumented endpoint may have changed", self.assertSourceError("schema").detail)

    def test_renamed_fields(self):
        payload = fakenet.fixture_json("firds/DE0005140008")
        payload["response"]["docs"] = [{"ISIN_CODE": d["isin"], "VENUE": d["mic"]} for d in payload["response"]["docs"]]
        self.net.script("firds/DE0005140008", (200, payload, {}))
        self.assertSourceError("schema")

    def test_records_for_another_isin(self):
        payload = copy.deepcopy(fakenet.fixture_json("firds/XS1910948592"))
        self.net.script("firds/DE0005140008", (200, payload, {}))
        self.assertIn("none for DE0005140008", self.assertSourceError("schema").detail)

    def test_solr_error_status(self):
        payload = fakenet.fixture_json("firds/DE0005140008")
        payload["responseHeader"]["status"] = 500
        self.net.script("firds/DE0005140008", (200, payload, {}))
        self.assertSourceError("schema")

    def test_http_400_with_solr_error_body(self):
        status, body, _ = fakenet.load("firds/bad_query")
        self.net.script("firds/DE0005140008", (status, body, {}))
        self.assertIn("HTTP 400", self.assertSourceError("http").detail)

    def test_endpoint_gone(self):
        self.net.script("firds/DE0005140008", (404, b"<html>Not Found</html>", {}))
        self.assertIn("may have moved", self.assertSourceError("http").detail)

    def test_numfound_not_a_number(self):
        payload = fakenet.fixture_json("firds/DE0005140008")
        payload["response"]["numFound"] = "8"
        self.net.script("firds/DE0005140008", (200, payload, {}))
        self.assertSourceError("schema")


if __name__ == "__main__":
    import unittest
    unittest.main()
