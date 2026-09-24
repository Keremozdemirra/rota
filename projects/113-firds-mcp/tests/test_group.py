"""isin_to_group: FIRDS and GLEIF in one answer, and what happens when one half fails."""
import urllib.error

import fakenet
import support
from support import fm


class Chain(support.OfflineTest):
    def test_share_with_reporting_exception(self):
        r = fm.isin_to_group("DE0005140008")
        self.assertTrue(r["found"])
        self.assertEqual(r["instrument"]["issuer_or_venue_operator_lei"], "7LTWFZYICNSX8D621K86")
        self.assertRemote(r["issuer"]["legal_name"], "DEUTSCHE BANK AKTIENGESELLSCHAFT")
        self.assertEqual(r["ultimate_parent"]["reason"], "NO_KNOWN_PERSON")
        self.assertEqual(r["venues"]["not_terminated"], ["CEUX", "JBUL", "RFQN", "XETA"])
        self.assertEqual(r["venues"]["counts"], {"not_terminated": 4, "terminated": 2, "cancelled": 2})
        self.assertEqual(len(r["sources"]), 2)
        self.assertTrue(r["sources"][0].startswith("Source: ESMA"))
        self.assertTrue(r["sources"][1].startswith("Source: GLEIF"))
        self.assertIn("ESMA does not endorse this publication", r["disclaimer"])
        self.assertEqual(len(self.net.requests), 4)  # 1 ESMA + record + 2 exceptions

    def test_bond_from_a_finance_subsidiary(self):
        r = fm.isin_to_group("XS1910948592")
        self.assertEqual(r["issuer"]["lei"], "5299004PWNHKYTR23649")
        self.assertEqual(r["direct_parent"]["entity"]["lei"], "529900NNUPAGGOMPXZ31")
        self.assertEqual(r["ultimate_parent"]["entity"]["lei"], "529900NNUPAGGOMPXZ31")
        self.assertEqual(r["instrument"]["details"]["Maturity date"], "2031-11-17T00:00:00Z")

    def test_fund_goes_through_its_manager(self):
        r = fm.isin_to_group("IE00B4L5Y983")
        self.assertEqual(r["issuer"]["category"], "FUND")
        self.assertEqual(r["direct_parent"]["reason"], "NON_CONSOLIDATING")
        self.assertRemote(r["fund_manager"]["entity"]["legal_name"], "BLACKROCK ASSET MANAGEMENT IRELAND LIMITED")
        self.assertEqual(r["fund_manager_ultimate_parent"]["entity"]["lei"], "529900VBK42Y5HHRMD23")
        self.assertRemote(r["fund_manager_ultimate_parent"]["entity"]["legal_name"], "BlackRock, Inc.")
        self.assertEqual(r["umbrella_fund"]["entity"]["lei"], "549300PZLRJB7M8H1057")
        self.assertLessEqual(len(self.net.requests), 10)

    def test_firds_miss_asks_nobody_else(self):
        r = fm.isin_to_group("XS0000000009")
        self.assertEqual(r["found"], False)
        self.assertEqual(self.net.routes(), ["firds/XS0000000009"])

    def test_lei_failing_the_check_is_not_sent(self):
        payload = fakenet.fixture_json("firds/DE0005140008")
        for doc in payload["response"]["docs"]:
            if doc.get("lei"):
                doc["lei"] = "7LTWFZYICNSX8D621K87"
        self.net.script("firds/DE0005140008", (200, payload, {}))
        r = fm.isin_to_group("DE0005140008")
        self.assertIn("fails the ISO 17442 check", r["issuer"]["note"])
        self.assertEqual(self.net.routes(), ["firds/DE0005140008"])
        self.assertEqual(len(r["sources"]), 1)

    def test_no_lei_in_firds(self):
        payload = fakenet.fixture_json("firds/DE0005140008")
        for doc in payload["response"]["docs"]:
            doc.pop("lei", None)
        self.net.script("firds/DE0005140008", (200, payload, {}))
        self.assertEqual(fm.isin_to_group("DE0005140008")["issuer"], {"note": "FIRDS gives no LEI for this instrument"})

    def test_lei_unknown_to_gleif(self):
        self.net.script("gleif/7LTWFZYICNSX8D621K86", (404, fakenet.fixture_json("gleif/529900ZZZZZZZZZZZZ46"), {}))
        r = fm.isin_to_group("DE0005140008")
        self.assertIn("GLEIF has no LEI record", r["issuer"]["note"])
        self.assertNotIn("direct_parent", r)


class HalfFails(support.OfflineTest):
    def test_gleif_down_keeps_the_firds_part(self):
        down = urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))
        self.net.script("gleif/7LTWFZYICNSX8D621K86", down, down)
        r = fm.isin_to_group("DE0005140008")
        self.assertIn("GLEIF: cannot connect", r["gleif_error"])
        self.assertEqual(r["venues"]["counts"]["not_terminated"], 4)
        self.assertEqual(len(r["sources"]), 1)  # nothing from GLEIF, so no GLEIF line
        self.assertIn("disclaimer", r)

    def test_gleif_fails_halfway(self):
        self.net.script("gleif/7LTWFZYICNSX8D621K86_ultimate-parent-reporting-exception", (500, b"", {}),
                        (500, b"", {}))
        r = fm.isin_to_group("DE0005140008")
        self.assertIn("HTTP 500", r["gleif_error"])
        self.assertEqual(r["issuer"]["lei"], "7LTWFZYICNSX8D621K86")
        self.assertEqual(len(r["sources"]), 2)

    def test_firds_down_is_an_error_result(self):
        self.net.script("firds/DE0005140008", urllib.error.URLError(OSError("Network is unreachable")),
                        urllib.error.URLError(OSError("Network is unreachable")))
        result = fm.call_tool("isin_to_group", {"isin": "DE0005140008"})
        self.assertTrue(result["isError"])
        self.assertEqual(result["structuredContent"]["error"]["kind"], "network")
        self.assertIn("ESMA could not answer", result["content"][0]["text"])


if __name__ == "__main__":
    import unittest
    unittest.main()
