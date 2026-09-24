import hashlib
import io
import json
import os
import re
import socket
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import support  # noqa: E402
from eudr_scope_mcp import cellar, cli, refresh  # noqa: E402


def build(fake=None):
    with support.Patched(fake or support.FakeCellar()):
        return refresh.build(today=support.TODAY)


class FullRun(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fake = support.FakeCellar()
        cls.result = build(cls.fake)

    def test_uses_latest_consolidated_version_and_applies_later_act(self):
        a = self.result["annex_i"]
        self.assertEqual(a["consolidated"]["celex"], "02023R1115-20251226")
        self.assertEqual(a["consolidated"]["amended_by"], ["32024R3234", "32025R2650"])
        self.assertEqual([x["celex"] for x in a["amendments_applied"]], ["32026R2102"])
        self.assertEqual(a["amendments_applied"][0]["entry_into_force"], "2026-09-18")
        self.assertEqual(a["status"], "verified")

    def test_annex_history(self):
        entries = {e["label"]: e for e in self.result["annex_i"]["entries"]}
        self.assertEqual(entries["ex 4101"]["valid_to"], "2026-09-17")
        self.assertEqual(entries["ex 4101"]["removed_by"]["provision"], "Annex, point (6)(c)")
        self.assertEqual(entries["2101 11 00"]["valid_from"], "2027-12-30")
        self.assertEqual(entries["ex 0102"]["valid_from"], "2026-09-18")
        self.assertIsNone(entries["1801"]["valid_from"])
        self.assertEqual(len(self.result["annex_i"]["table_notes"]), 2)  # points (1) and (5) in the fixture

    def test_dates_read_from_text_and_history(self):
        d = self.result["application_dates"]
        self.assertEqual(d["status"], "verified")
        a38 = d["article_38"]
        self.assertEqual((a38["entry_into_force"], a38["p2_date"], a38["p3_date"], a38["p3_established_by"]),
                         ("2023-06-29", "2026-12-30", "2027-06-30", "2024-12-31"))
        self.assertEqual(a38["set_by"], {"celex": "32025R2650", "provision": "Article 1, point (25)"})
        self.assertEqual([(h["celex"], h["p2_date"], h["p3_date"]) for h in d["history"]],
                         [("32023R1115", "2024-12-30", "2025-06-30"), ("32024R3234", "2025-12-30", "2026-06-30"),
                          ("32025R2650", "2026-12-30", "2027-06-30")])
        self.assertEqual(d["article_37"]["p2_until"], "2029-12-31")
        self.assertEqual([p["celex"] for p in d["pending_proposals"]], ["52026PC0661"])
        self.assertTrue(all(not c["english"] for c in d["corrigenda"]))

    def test_country_list(self):
        c = self.result["country_risk"]
        self.assertEqual(c["status"], "verified")
        self.assertEqual(c["act"]["entry_into_force"], "2025-05-26")
        self.assertEqual({x["iso3"] for x in c["high"]}, {"BLR", "PRK", "MMR", "RUS"})
        self.assertIn({"annex_name": "Solomon Island", "iso2": "SB", "iso3": "SLB",
                       "matched_by": "fixed mapping (see SOURCES.md)"}, c["low"])

    def test_documents_are_hashed(self):
        docs = self.result["documents"]
        self.assertEqual({d["celex"] for d in docs},
                         {"02023R1115-20251226", "32023R1115", "32024R3234", "32025R2650", "32026R2102", "32025R1093"})
        for d in docs:
            body = (support.FIXTURES / support.DOCS[d["celex"]]).read_bytes()
            self.assertEqual(d["sha256"], hashlib.sha256(body).hexdigest())

    def test_only_publications_office_urls_were_requested(self):
        self.assertTrue(all(k.startswith(("sparql:", "doc:")) for k in self.fake.calls))

    def test_write_produces_consistent_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = refresh.write(self.result, Path(tmp))
            names = sorted(os.listdir(tmp))
            self.assertEqual(names, ["SOURCES.md", "annex_i.json", "application_dates.json", "countries.json",
                                     "country_risk.json", "manifest.json"])
            for name, digest in manifest["files"].items():
                self.assertEqual(hashlib.sha256((Path(tmp) / name).read_bytes()).hexdigest(), digest)
            sources = (Path(tmp) / "SOURCES.md").read_text(encoding="utf-8")
            for d in manifest["documents"]:
                self.assertIn(d["sha256"], sources)
            self.assertIn("32026R2102", sources)
            self.assertIn("Decision 2011/833/EU", sources)


class Failures(unittest.TestCase):
    """A failed refresh returns 2 and leaves the previous snapshot as it was."""

    def run_refresh(self, fake):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "annex_i.json"
            marker.write_text('{"old": true}', encoding="utf-8")
            log = []
            with support.Patched(fake):
                code = refresh.run(tmp, today=support.TODAY, log=log.append)
            self.assertEqual(marker.read_text(encoding="utf-8"), '{"old": true}')
            self.assertEqual(sorted(os.listdir(tmp)), ["annex_i.json"])
            return code, " ".join(log)

    def test_network_down(self):
        code, log = self.run_refresh(support.FakeCellar(
            {"sparql:work_32023R1115": urllib.error.URLError("Temporary failure in name resolution")}))
        self.assertEqual(code, 2)
        self.assertIn("nothing written", log)

    def test_timeout_on_a_document(self):
        code, _ = self.run_refresh(support.FakeCellar({"doc:32026R2102": socket.timeout("timed out")}))
        self.assertEqual(code, 2)

    def test_404_on_a_document(self):
        code, log = self.run_refresh(support.FakeCellar({"doc:02023R1115-20251226": support.http_error(404)}))
        self.assertEqual(code, 2)
        self.assertIn("HTTP 404", log)

    def test_rate_limited_throughout(self):
        code, _ = self.run_refresh(support.FakeCellar({"sparql:nal": support.http_error(429)}))
        self.assertEqual(code, 2)

    def test_malformed_sparql(self):
        code, _ = self.run_refresh(support.FakeCellar({"sparql:related_32023R1115": b'{"head": {}}'}))
        self.assertEqual(code, 2)

    def test_empty_sparql_result(self):
        empty = b'{"head": {"vars": []}, "results": {"bindings": []}}'
        code, log = self.run_refresh(support.FakeCellar({"sparql:consolidated_32023R1115": empty}))
        self.assertEqual(code, 2)
        self.assertIn("no consolidated version", log)

    def test_document_without_annex(self):
        code, _ = self.run_refresh(support.FakeCellar(
            edits={"doc:02023R1115-20251226": lambda t: t.replace('id="anx_I"', 'id="anx_X"')}))
        self.assertEqual(code, 2)

    def test_non_utf8_document(self):
        code, log = self.run_refresh(support.FakeCellar({"doc:32025R1093": b"<html>\xff\xfe</html>"}))
        self.assertEqual(code, 2)
        self.assertIn("not UTF-8", log)

    def test_amendment_that_does_not_match_the_table(self):
        lq = chr(0x2018)
        code, log = self.run_refresh(support.FakeCellar(
            edits={"doc:32026R2102": lambda t: t.replace(lq + "1802  Cocoa shells", lq + "1809  Cocoa shells")}))
        self.assertEqual(code, 2)
        self.assertIn("(6)(d)", log)

    def test_entry_into_force_disagrees_with_metadata(self):
        def edit(t):
            return t.replace("on the day following that of its publication", "on the twentieth day following that of its publication")
        code, log = self.run_refresh(support.FakeCellar(edits={"doc:32026R2102": edit}))
        self.assertEqual(code, 2)
        self.assertIn("entry into force", log)

    def test_country_name_not_in_authority_table(self):
        code, log = self.run_refresh(support.FakeCellar(
            edits={"doc:32025R1093": lambda t: t.replace("Austria, China", "Austria, Atlantis, China")}))
        self.assertEqual(code, 2)
        self.assertIn("Atlantis", log)


class Unverified(unittest.TestCase):
    def test_cellar_metadata_disagrees_with_the_text(self):
        work = support.load("sparql_work_32023R1115.json")
        work["results"]["bindings"] = [b for b in work["results"]["bindings"] if b["o"]["value"] != "2027-06-30"]
        result = build(support.FakeCellar({"sparql:work_32023R1115": json.dumps(work).encode()}))
        d = result["application_dates"]
        self.assertEqual(d["status"], "unverified")
        self.assertTrue(any("Article 38(3)" in r for r in d["status_reasons"]))

    def test_unconsolidated_act_touching_article_38(self):
        # Pretend the consolidated text did not yet include 2025/2650, and that
        # 2025/2650 did not touch Annex I: its Article 38 change is then unapplied.
        def cons(t):
            return re.sub(r'(title="32025R2650"\s*>)' + chr(0x25BA) + r"(M2</a>)", r"\1\2", t)

        def act(t):
            return re.sub(r"in Annex I, in the table, the line", "in the table, the line", t)
        result = build(support.FakeCellar(edits={"doc:02023R1115-20251226": cons, "doc:32025R2650": act}))
        d = result["application_dates"]
        self.assertEqual(result["annex_i"]["consolidated"]["amended_by"], ["32024R3234"])
        self.assertEqual(d["status"], "unverified")
        self.assertTrue(any("Article 38 is amended by 32025R2650" in r for r in d["status_reasons"]))
        self.assertTrue(any("Article 2" in w for w in d["warnings"]))

    def test_amended_country_list_is_not_shipped(self):
        related = support.load("sparql_related_32025R1093.json")
        related["results"]["bindings"] = [{
            "rel": {"type": "literal", "value": "amends"},
            "celex": {"type": "literal", "value": "32026R9999"},
            "date": {"type": "literal", "value": "2026-09-01"}}]
        result = build(support.FakeCellar({"sparql:related_32025R1093": json.dumps(related).encode()}))
        c = result["country_risk"]
        self.assertEqual(c["status"], "unverified")
        self.assertEqual((c["low"], c["high"]), ([], []))


class CommandLine(unittest.TestCase):
    def test_refresh_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp, support.Patched(support.FakeCellar()):
            saved = sys.stderr
            sys.stderr = io.StringIO()
            try:
                code = cli.main(["refresh", "--out", tmp, "--dry-run"])
                err = sys.stderr.getvalue()
            finally:
                sys.stderr = saved
            self.assertEqual(code, 0)
            self.assertEqual(os.listdir(tmp), [])
            self.assertIn("dry run", err)

    def test_refresh_requires_out(self):
        saved = sys.stderr
        sys.stderr = io.StringIO()
        try:
            with self.assertRaises(SystemExit) as ctx:
                cli.main(["refresh"])
        finally:
            sys.stderr = saved
        self.assertEqual(ctx.exception.code, 2)

    def test_no_network_outside_refresh(self):
        def forbidden(*a, **k):
            raise AssertionError("network used by a lookup")
        saved = cellar._open
        cellar._open = forbidden
        try:
            with support.SnapshotEnv(support.shared_snapshot()):
                from eudr_scope_mcp import lookup
                lookup.eudr_scope("1801")
                lookup.country_risk("BR")
                lookup.application_dates("all")
                lookup.sources()
        finally:
            cellar._open = saved


if __name__ == "__main__":
    unittest.main()
