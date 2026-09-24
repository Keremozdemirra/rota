"""The bundled text: lookups, and the parser and refresh against trimmed recorded CELLAR responses."""
import datetime as dt
import http.client
import json
import socket
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import FIXTURES, Isolated  # noqa: E402

from vsme_kit import ojparse, refresh, standard  # noqa: E402


class Lookups(unittest.TestCase):
    def test_basic_module_2026(self):
        res = standard.disclosures("basic")
        self.assertEqual([d["code"] for d in res["disclosures"]], [f"B{i}" for i in range(1, 12)])
        b3 = res["disclosures"][2]
        self.assertEqual((b3["title"], b3["paragraphs"], b3["in_value_chain_cap"]),
                         ("Energy and greenhouse gas emissions", ["32", "33"], True))
        self.assertFalse(res["disclosures"][1]["in_value_chain_cap"])  # B2
        self.assertIn("retrieved 2026-09-24", res["attribution"])

    def test_licence_basis_is_the_eur_lex_notice_not_cc_by(self):
        # review 2026-09-24, item 1: OJ texts are re-used under the EUR-Lex notice and Decision 2011/833/EU
        for edition in standard.EDITIONS:
            snap = standard.load(edition)
            line = standard.attribution(snap)
            self.assertNotIn("CC BY", line)
            self.assertIn("EUR-Lex legal notice and Commission Decision 2011/833/EU (Articles 4 and 6)", line)
            self.assertEqual(snap["licence"]["terms"], "https://eur-lex.europa.eu/content/legal-notice/legal-notice.html")
            self.assertNotIn("licence", snap["licence"])
            self.assertIn("re-use the legal documents published in EUR-Lex", snap["licence"]["quote"])
            self.assertIn("All documents shall be available for reuse", snap["licence"]["policy_quote"])

    def test_changes_line_mentions_the_footnote_markers(self):
        # review item 7: "(2)" and similar markers stay while the footnotes are left out
        self.assertIn("footnote markers", standard.load("2025")["changes"])
        para13 = next(p for p in standard.load("2025")["annex_i"] if p["n"] == "13")
        self.assertIn("(2)", para13["text"])

    def test_comprehensive_module_2025(self):
        res = standard.disclosures("comprehensive", "2025")
        self.assertEqual([d["code"] for d in res["disclosures"]], [f"C{i}" for i in range(1, 10)])
        self.assertTrue(any(p["n"] == "5" for p in res["module_rules"]))

    def test_b3_verbatim_with_guidance(self):
        res = standard.disclosure("b3", "2025", guidance=True)
        self.assertEqual([p["n"] for p in res["paragraphs"]], ["29", "30", "31"])
        self.assertTrue(res["paragraphs"][0]["text"].startswith(
            "The undertaking shall disclose its total energy consumption in MWh"))
        self.assertEqual([p["n"] for p in res["related_paragraphs"]], ["50", "51", "52", "53"])
        scope_table = next(p for p in res["guidance"] if p["n"] == "27")
        self.assertIn("Scope 1 | 45", scope_table["text"])
        self.assertEqual(res["other_edition"]["paragraphs"], ["32", "33"])
        self.assertIn("no longer producing any legal effects", res["status"])

    def test_formula_images_are_marked_not_invented(self):
        res = standard.disclosure("B8", "2025", guidance=True)
        para = next(p for p in res["guidance"] if p["n"] == "118")
        self.assertIn(ojparse.IMAGE, para["text"])

    def test_value_chain_cap_rows(self):
        res = standard.disclosure("C7")
        self.assertEqual([r["reference"] for r in res["value_chain_cap"]],
                         ["Para 62, point (a), subpoints from (i) to (v)", "Para 62, point (c), first sentence"])
        self.assertTrue(all(not r["cap_10_or_fewer_employees"] and r["cap_more_than_10_employees"]
                            for r in res["value_chain_cap"]))

    def test_dates_come_from_the_act(self):
        s = standard.status()
        self.assertEqual(s["2026"]["entry_into_force"], "2026-09-24")
        self.assertIn("2027-01-01", s["2026"]["value_chain_cap_applies"])

    def test_bad_input(self):
        for code in ("B12", "C10", "D1", "", "B", None, 3, "B3; rm -rf /"):
            with self.assertRaises(standard.LookupError_):
                standard.disclosure(code)
        with self.assertRaises(standard.LookupError_):
            standard.disclosures("everything")
        with self.assertRaises(standard.LookupError_):
            standard.disclosure("B1", "2024")

    def test_unicode_survives(self):
        text = standard.disclosure("B8")["title"]
        self.assertEqual(text, "Workforce – General characteristics")


def fake(answers):
    """Stands in for refresh._open: answers keyed by URL, an exception, an int (HTTP error) or (status, headers, body)."""
    calls = []

    def _open(request, timeout):
        calls.append(request.full_url)
        a = answers.get(request.full_url, 404)
        if isinstance(a, list):
            a = a.pop(0) if len(a) > 1 else a[0]
        if isinstance(a, BaseException):
            raise a
        if isinstance(a, int):
            raise urllib.error.HTTPError(request.full_url, a, "status", {}, None)
        return a
    _open.calls = calls
    return _open


URL25 = "https://publications.europa.eu/resource/celex/32025H1710"
URL26 = "https://publications.europa.eu/resource/celex/32026R1560"
XHTML = {"Content-Type": "application/xhtml+xml;charset=UTF-8"}


class Refresh(Isolated):
    def setUp(self):
        super().setUp()
        p = mock.patch.object(refresh, "RETRY_DELAY", 0)
        p.start()
        self.addCleanup(p.stop)
        self.body25 = (FIXTURES / "cellar-32025H1710-trimmed.xhtml").read_bytes()
        self.body26 = (FIXTURES / "cellar-32026R1560-trimmed.xhtml").read_bytes()

    def serve(self, answers):
        f = fake(answers)
        p = mock.patch.object(refresh, "_open", f)
        p.start()
        self.addCleanup(p.stop)
        return f

    def test_rebuilds_both_snapshots(self):
        self.serve({URL25: (200, XHTML, self.body25), URL26: (200, XHTML, self.body26)})
        lines = refresh.run(self.tmp / "out", today=dt.date(2026, 9, 24))
        self.assertEqual(len(lines), 2)
        snap = json.loads((self.tmp / "out" / "standard-2026.json").read_text(encoding="utf-8"))
        self.assertEqual(snap["entry_into_force"], "2026-09-24")
        self.assertEqual(len(snap["value_chain_cap"]), 23)
        self.assertEqual(snap["oj"], "OJ L, 2026/1560, 21.9.2026")

    def test_network_down_and_timeouts_retry_then_fail(self):
        for exc in (urllib.error.URLError("down"), socket.timeout("slow"), http.client.IncompleteRead(b"x"),
                    ConnectionResetError("reset")):
            f = self.serve({URL26: exc})
            with self.assertRaises(refresh.RefreshError):
                refresh.run(self.tmp / "out")
            self.assertEqual(len(f.calls), refresh.RETRIES + 1)

    def test_rate_limit_is_retried(self):
        f = self.serve({URL26: [429, (200, XHTML, self.body26)], URL25: (200, XHTML, self.body25)})
        refresh.run(self.tmp / "out")
        self.assertEqual(f.calls.count(URL26), 2)

    def test_404_is_not_retried(self):
        f = self.serve({URL26: 404})
        with self.assertRaises(refresh.RefreshError):
            refresh.run(self.tmp / "out")
        self.assertEqual(len(f.calls), 1)

    def test_empty_wrong_type_and_malformed_bodies(self):
        for answer, fragment in (((200, XHTML, b""), "empty"),
                                 ((200, {"Content-Type": "application/pdf"}, b"%PDF"), "expected XHTML"),
                                 ((200, XHTML, b"<html><body>"), "not well-formed"),
                                 ((200, XHTML, b"\xff\xfe\x00garbage"), "not well-formed"),
                                 ((200, XHTML, b"<html xmlns='http://www.w3.org/1999/xhtml'><body/></html>"), "header")):
            self.serve({URL26: answer})
            with self.assertRaises(refresh.RefreshError) as ctx:
                refresh.run(self.tmp / "out")
            self.assertIn(fragment, str(ctx.exception))

    def test_redirect_to_another_host_is_refused(self):
        handler = refresh._SameHostHttps()
        with self.assertRaises(refresh.RefreshError):
            handler.redirect_request(None, None, 303, "See Other", {}, "https://example.org/x")

    def test_structure_change_is_an_error_not_an_empty_snapshot(self):
        broken = self.body26.replace(b'id="anx_II"', b'id="anx_X"')
        self.serve({URL26: (200, XHTML, broken)})
        with self.assertRaises(refresh.RefreshError):
            refresh.run(self.tmp / "out")


class Parser(unittest.TestCase):
    def test_points_tables_and_headings(self):
        root = ojparse.parse((FIXTURES / "cellar-32025H1710-trimmed.xhtml").read_bytes())
        paras = {p["n"]: p for p in ojparse.paragraphs(ojparse.annex(root, "I"))}
        self.assertIn("  (i) OPTION A: Basic Module (only); or", paras["24"]["text"].split("\n"))
        self.assertIn("Fuels | | |", paras["29"]["text"].split("\n"))
        self.assertEqual(paras["50"]["related"], ["B3"])
        self.assertIsNone(paras["50"]["code"])

    def test_entities_are_refused(self):
        with self.assertRaises(ojparse.ParseError):
            ojparse.parse(b'<!DOCTYPE x [<!ENTITY a "b">]><x>&a;</x>')


if __name__ == "__main__":
    unittest.main()
