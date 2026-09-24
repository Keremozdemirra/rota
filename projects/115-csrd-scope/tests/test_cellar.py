"""CELLAR access: recorded answers (trimmed real responses of 2026-09-24) and the failures that happen."""
import contextlib
import http.client
import io
import json
import os
import socket
import tempfile
import unittest
import urllib.error

from support import DATA, FIXTURES, Isolated, fixture, sparql_router

import csrd_scope
import csrd_scope_cellar as cellar

EXCERPT = (FIXTURES / "doc-02013L0034-art19a-excerpt.xhtml").read_text(encoding="utf-8")
ANNEXES = (FIXTURES / "doc-02013L0034-annexes-excerpt.xhtml").read_text(encoding="utf-8")


class Sparql(Isolated):
    def test_recorded_answer_is_parsed(self):
        self.serve(sparql_router())
        rows = cellar.sparql(cellar.Q_CONSOLIDATED)
        self.assertIn({"base": "32013L0034", "celex": "02013L0034-20260318", "date": "2026-03-18",
                       "base@type": "http://www.w3.org/2001/XMLSchema#string",
                       "celex@type": "http://www.w3.org/2001/XMLSchema#string",
                       "date@type": "http://www.w3.org/2001/XMLSchema#date"}, rows)

    def test_failures_become_source_errors(self):
        cases = {
            "network down": urllib.error.URLError(OSError(101, "Network is unreachable")),
            "404": 404, "429": 429, "500": 500,
            "timeout": socket.timeout("timed out"),
            "incomplete read": http.client.IncompleteRead(b"{", 100),
            "bad status line": http.client.BadStatusLine("xx"),
            "empty body": b"",
            "null body": b"null",
            "not json": b"<html>maintenance</html>",
            "not utf-8": b"\xff\xfe\x00{",
            "bindings not a list": b'{"results": {"bindings": {}}}',
            "value not a string": b'{"results": {"bindings": [{"x": {"value": 3}}]}}',
        }
        for name, answer in cases.items():
            with self.subTest(name):
                self.serve(lambda url, a=answer: a)
                with self.assertRaises(cellar.SourceError) as cm:
                    cellar.sparql(cellar.Q_CONSOLIDATED)
                if name == "429":
                    self.assertIn("429", str(cm.exception))
                    self.assertIn("retry after 120", str(cm.exception))

    def test_malformed_celex_is_never_requested(self):
        for bad in ("32013L0034; DROP", "../etc/passwd", "32013L0034?x=1", "", None):
            with self.subTest(bad=bad):
                with self.assertRaises(cellar.SourceError):
                    cellar.fetch_document(bad)
        self.assertEqual(self.web.urls, [])

    def test_document_must_be_utf8(self):
        self.serve(lambda url: b"\xc3\x28 not utf-8")
        with self.assertRaises(cellar.SourceError):
            cellar.fetch_document("32026L0470")


class Text(unittest.TestCase):
    def test_normalise_drops_consolidation_markers(self):
        self.assertIn("►", EXCERPT)
        t = cellar.normalise(EXCERPT)
        self.assertNotIn("►", t)
        self.assertNotIn("◄", t)
        q = cellar.extract(t, "Undertakings which, on their balance sheet dates, exceed a net turnover of EUR 450 000 000",
                           "performance and position.")
        self.assertEqual(q, DATA.quotes["AD-19a-1"]["text"])

    def test_extract_refuses_missing_or_runaway_quotes(self):
        t = cellar.normalise(EXCERPT)
        self.assertIsNone(cellar.extract(t, "text that is not there", None))
        self.assertIsNone(cellar.extract(t, "Undertakings which", "an ending that is not there"))
        self.assertIsNone(cellar.extract("start " + "x" * 5000 + " end", "start", "end"))

    def test_annexes_parse_to_27_member_states(self):
        names = {m["name"]: m["alpha2"] for m in DATA.ms["member_states"]}
        a = cellar.parse_annexes(cellar.normalise(ANNEXES), names)
        self.assertEqual(len(a["annex_i"]), 27)
        self.assertEqual(len(a["annex_ii"]), 27)
        self.assertEqual(a["annex_i"]["DE"], "die Aktiengesellschaft, die Kommanditgesellschaft auf Aktien, die Gesellschaft mit beschränkter Haftung")
        self.assertIn("partnership en nom collectif", a["annex_ii"]["MT"])  # a dash inside the entry does not split it
        self.assertEqual(a["not_eu_member_states"], ["annex_i: United Kingdom", "annex_ii: United Kingdom"])
        self.assertEqual(a, {k: DATA.forms[k] for k in ("annex_i", "annex_ii", "not_eu_member_states")})

    def test_annexes_missing_is_an_error(self):
        with self.assertRaises(cellar.SourceError):
            cellar.parse_annexes("no annexes here", {"Germany": "DE"})


class Verify(Isolated):
    def test_unchanged(self):
        self.serve(sparql_router())
        res = cellar.verify(DATA.legal, nim_snapshot=DATA.nim)
        self.assertEqual(res["findings"], [])
        self.assertEqual(res["status"], "unchanged")

    def test_new_consolidated_version_and_english_corrigendum(self):
        cons = fixture("sparql-consolidated.json")
        cons["results"]["bindings"].append({"base": {"type": "literal", "value": "32013L0034"},
                                            "celex": {"type": "literal", "value": "02013L0034-20261201"},
                                            "date": {"type": "literal", "value": "2026-12-01"}})
        after = fixture("sparql-after.json")
        after["results"]["bindings"].append({"base": {"type": "literal", "value": "32026L0470"},
                                             "rel": {"type": "literal", "value": "corrects"},
                                             "celex": {"type": "literal", "value": "32026L0470R(02)"},
                                             "date": {"type": "literal", "value": "2026-10-01"}})
        langs = fixture("sparql-langs.json")
        langs["results"]["bindings"].append({"celex": {"type": "literal", "value": "32026L0470R(02)"},
                                             "lang": {"type": "literal", "value": "ENG"}})
        self.serve(sparql_router({"consolidated": json.dumps(cons).encode(), "after": json.dumps(after).encode(),
                                  "langs": json.dumps(langs).encode()}))
        res = cellar.verify(DATA.legal, nim_snapshot=DATA.nim)
        kinds = {f["kind"] for f in res["findings"]}
        self.assertEqual(res["status"], "changed")
        self.assertIn("new consolidated version", kinds)
        self.assertIn("new corrigendum to the English text", kinds)

    def test_network_down(self):
        self.serve(lambda url: urllib.error.URLError("down"))
        with self.assertRaises(cellar.SourceError):
            cellar.verify(DATA.legal)


class Refresh(Isolated):
    def test_refuses_to_write_when_a_quote_is_missing(self):
        self.serve(sparql_router())
        doc = {"url": "u", "resolved_url": "u", "bytes": 1, "sha256": "0" * 64, "text": EXCERPT}
        countries = [{"c": f"http://publications.europa.eu/resource/authority/country/{m['alpha3']}", "label": m["name"],
                      "n": m["alpha2"], "n@type": "http://publications.europa.eu/ontology/euvoc#ISO_3166_1_ALPHA_2"}
                     for m in DATA.ms["member_states"]]

        def run(q):
            return countries if "EU_COU" in q else cellar.sparql(q)
        with self.assertRaises(cellar.SourceError) as cm:
            cellar.build_snapshot("2026-09-24", run=run, fetch=lambda celex: doc)
        self.assertIn("not found", str(cm.exception))

    def test_cli_refresh_reports_failure_without_writing(self):
        self.serve(lambda url: urllib.error.URLError("down"))
        err = io.StringIO()
        with tempfile.TemporaryDirectory() as out, contextlib.redirect_stderr(err):
            self.assertEqual(csrd_scope.main(["refresh", "--out", out]), 2)
            self.assertEqual(os.listdir(out), [])
        self.assertIn("nothing written", err.getvalue())
        self.assertNotIn("SELECT", err.getvalue())


if __name__ == "__main__":
    unittest.main()
