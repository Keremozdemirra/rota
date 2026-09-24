"""refresh: rebuilding the snapshot from recorded source files, and every way a download goes wrong."""
from __future__ import annotations

import email.message
import hashlib
import http.client
import io
import json
import socket
import sys
import tempfile
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import TODAY, FakeFetch, IsolatedTestCase, build_snapshot, fixture, flat_url, recorded_answers  # noqa: E402

from ghg_factors_mcp import __main__ as cli  # noqa: E402
from ghg_factors_mcp import provenance as P  # noqa: E402
from ghg_factors_mcp import refresh as R  # noqa: E402


class Rebuild(IsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name) / "data"

    def manifest(self) -> dict:
        return json.loads((self.out / "manifest.json").read_text(encoding="utf-8"))

    def test_all_sources_from_recorded_files(self):
        report = build_snapshot(self.out)
        self.assertEqual(report["failed"], {})
        self.assertEqual(sorted(report["ok"]), ["desnz-2025", "desnz-2026", "ember", "uba"])
        m = self.manifest()["sources"]
        d = m["desnz-2026"]
        self.assertEqual((d["version"], d["status"], d["updated"], d["rows"], d["retrieved"]),
                         ("1.2", "Final", "2026-07-10", 51, TODAY))
        self.assertEqual(d["raw_sha256"], hashlib.sha256(fixture("desnz_flat_2026_trimmed.xlsx")).hexdigest())
        self.assertEqual(d["raw_url"], flat_url(2026))
        self.assertEqual(m["ember"]["last_modified"], "Tue, 22 Sep 2026 16:24:55 GMT")
        csv_text = (self.out / "desnz_2026.csv").read_text(encoding="utf-8")
        self.assertIn("1_101_1011_8_3,Scope 1,Fuels,Liquid fuels,Diesel (average biofuel blend),,,litres,"
                      "kg CO2e of CH4 per unit,0.00029\n", csv_text)
        self.assertIn("29_600_4002_13_1,Scope 3,Hotel stay,Hotel stay,Argentina,,,Room per night,kg CO2e,\n", csv_text)
        ember = (self.out / "ember_yearly_intensity.csv").read_text(encoding="utf-8")
        self.assertIn("Lesotho,LSO,Country or economy,2024,,0.0,0.0\n", ember)
        self.assertIn("Türkiye,TUR,Country or economy,2025,475.776,168.358,353.86\n", ember)
        uba = json.loads((self.out / "uba_strommix.json").read_text(encoding="utf-8"))
        self.assertEqual([(v["year"], v["g_co2_per_kwh"]) for v in uba["values"]], [(2023, 379), (2024, 353), (2025, 344)])
        sources_md = (self.out / "SOURCES.md").read_text(encoding="utf-8")
        for needle in (P.DESNZ["attribution_statement"], d["raw_sha256"], "CC BY 4.0", "§ 12a EGovG",
                       "IEA-EDGAR CO2", "https://www.ipcc.ch/copyright/"):
            self.assertIn(needle, sources_md)

    def test_only_the_expected_hosts_are_contacted(self):
        fake = FakeFetch(recorded_answers())
        R.refresh(self.out, get=fake, today=TODAY)
        hosts = {u.split("/")[2] for u in fake.calls}
        self.assertEqual(hosts, {"www.gov.uk", "assets.publishing.service.gov.uk", "files.ember-energy.org",
                                 "www.umweltbundesamt.de"})

    def test_rebuild_is_byte_for_byte_reproducible(self):
        other = Path(self.tmp.name) / "again"
        build_snapshot(self.out)
        build_snapshot(other)
        for f in sorted(p.name for p in self.out.iterdir()):
            self.assertEqual((self.out / f).read_bytes(), (other / f).read_bytes(), f)

    def test_failed_source_keeps_its_previous_snapshot(self):
        build_snapshot(self.out)
        before = (self.out / "ember_yearly_intensity.csv").read_bytes()
        answers = recorded_answers()
        answers[P.EMBER_CSV] = R.RefreshError("cannot reach files.ember-energy.org: [Errno -3] name resolution")
        answers[P.UBA_PAGE] = b"<html><body><p>Seite umgebaut, keine Zahlen.</p></body></html>"
        report = build_snapshot(self.out, answers)
        self.assertEqual(sorted(report["failed"]), ["ember", "uba"])
        self.assertIn("cannot reach", report["failed"]["ember"])
        self.assertIn("page may have changed", report["failed"]["uba"])
        self.assertEqual((self.out / "ember_yearly_intensity.csv").read_bytes(), before)
        m = self.manifest()["sources"]
        self.assertEqual(m["ember"]["rows"], 13)
        self.assertEqual(m["uba"]["rows"], 3)
        self.assertEqual(sorted(p.name for p in self.out.iterdir() if p.name.startswith(".")), [])  # no temp files

    def test_flat_file_url_on_another_host_is_never_fetched(self):
        answers = recorded_answers()
        doc = json.loads(fixture("desnz_content_api_2026.json"))
        for a in doc["details"]["attachments"]:
            if "flat file" in a["title"].lower():
                a["url"] = "https://assets.example.net/ghg-conversion-factors-2026-flat-format.xlsx"
        answers[P.DESNZ_API.format(year=2026)] = json.dumps(doc).encode()
        fake = FakeFetch(answers)
        report = R.refresh(self.out, get=fake, today=TODAY, only={"desnz-2026"})
        self.assertIn("refused", report["failed"]["desnz-2026"])
        self.assertFalse(any("example.net" in u for u in fake.calls))

    def test_content_api_answers_that_are_not_a_publication(self):
        for body, why in ((b"null", "no attachment list"), (b"<html>maintenance</html>", "not JSON"),
                          (b"\xff\xfe\x00\x00", "not UTF-8"), (b'{"details": {"attachments": []}}', "found 0")):
            answers = recorded_answers()
            answers[P.DESNZ_API.format(year=2026)] = body
            report = build_snapshot(self.out, answers)
            self.assertIn(why, report["failed"].get("desnz-2026", ""), body)

    def test_attachment_for_the_wrong_year(self):
        answers = recorded_answers()
        answers[flat_url(2025)] = fixture("desnz_flat_2026_trimmed.xlsx")
        report = build_snapshot(self.out, answers)
        self.assertIn("expected year 2025", report["failed"]["desnz-2025"])

    def test_malformed_xlsx(self):
        answers = recorded_answers()
        answers[flat_url(2026)] = b"PK\x03\x04 this is not really a zip archive"
        report = build_snapshot(self.out, answers)
        self.assertRegex(report["failed"]["desnz-2026"], "^DESNZ 2026 flat file: not an xlsx")

    def test_404_on_the_content_api(self):
        answers = recorded_answers()
        del answers[P.DESNZ_API.format(year=2025)]
        report = build_snapshot(self.out, answers)
        self.assertIn("HTTP 404", report["failed"]["desnz-2025"])
        self.assertIn("desnz-2026", report["ok"])


class Parsers(IsolatedTestCase):
    def test_ember_format_change(self):
        text = fixture("ember_trimmed.csv").decode("utf-8").replace("Emissions intensity (gCO2e/kWh)", "Intensity")
        with self.assertRaisesRegex(R.RefreshError, "lacks columns"):
            R.parse_ember(text.encode("utf-8"))

    def test_ember_empty_non_utf8_and_non_numeric(self):
        with self.assertRaisesRegex(R.RefreshError, "lacks columns"):
            R.parse_ember(b"")
        with self.assertRaisesRegex(R.RefreshError, "not UTF-8"):
            R.parse_ember(fixture("ember_trimmed.csv").replace("Türkiye".encode(), b"T\xfcrkiye"))
        bad = fixture("ember_trimmed.csv").decode("utf-8").replace(",475.776,", ",n/a,")
        with self.assertRaisesRegex(R.RefreshError, "not a number"):
            R.parse_ember(bad.encode("utf-8"))

    def test_desnz_header_changed(self):
        data = fixture("desnz_flat_2026_trimmed.xlsx")
        with mock.patch.object(R, "_DESNZ_HEADER", R._DESNZ_HEADER + ["Source"]):
            with self.assertRaisesRegex(R.RefreshError, "header changed"):
                R.parse_desnz(data, 2026)

    def test_uba_reads_numbers_not_decimals_or_scripts(self):
        pairs, meta = R.parse_uba(fixture("uba_page_skeleton.html"))
        self.assertEqual(pairs, [{"year": 2023, "g_co2_per_kwh": 379}, {"year": 2024, "g_co2_per_kwh": 353},
                                 {"year": 2025, "g_co2_per_kwh": 344}])
        self.assertEqual(meta["years"], "2023-2025")

    def test_uba_implausible_figures_are_rejected(self):
        page = "<p>Je Kilowattstunde im Jahr 2025: 34 Gramm CO2. Zuvor 2024: 3530 Gramm.</p>".encode()
        with self.assertRaisesRegex(R.RefreshError, "could not read"):
            R.parse_uba(page)


class FakeResponse(io.BytesIO):
    def __init__(self, body: bytes, headers=None):
        super().__init__(body)
        self.headers = email.message.Message()
        for k, v in (headers or {}).items():
            self.headers[k] = v

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Fetch(IsolatedTestCase):
    URL = "https://files.ember-energy.org/public-downloads/x.csv"

    def fetch_with(self, effect, max_bytes=1000):
        with mock.patch("urllib.request.urlopen", side_effect=effect) as urlopen:
            try:
                return R.fetch(self.URL, max_bytes)
            finally:
                self.calls = urlopen.call_count

    def assertFails(self, effect, pattern, max_bytes=1000):
        with self.assertRaisesRegex(R.RefreshError, pattern):
            self.fetch_with(effect, max_bytes)

    def test_ok(self):
        body, headers = self.fetch_with([FakeResponse(b"a,b\n1,2\n", {"Last-Modified": "x"})])
        self.assertEqual((body, headers["last-modified"]), (b"a,b\n1,2\n", "x"))

    def test_network_down(self):
        self.assertFails(urllib.error.URLError(socket.gaierror(-3, "Temporary failure in name resolution")),
                         "cannot reach files.ember-energy.org")

    def test_404(self):
        self.assertFails(urllib.error.HTTPError(self.URL, 404, "Not Found", email.message.Message(), None), "HTTP 404")

    def test_429_with_retry_after(self):
        hdrs = email.message.Message()
        hdrs["Retry-After"] = "120"
        self.assertFails(urllib.error.HTTPError(self.URL, 429, "Too Many Requests", hdrs, None),
                         "429 rate limited.*retry after 120 s")

    def test_incomplete_read(self):
        class Broken(FakeResponse):
            def read(self, n=-1):
                raise http.client.IncompleteRead(b"partial", 1000)
        self.assertFails([Broken(b"")], "broken HTTP response.*IncompleteRead")

    def test_bad_status_line(self):
        self.assertFails(http.client.BadStatusLine("HTTP/9.9 ???"), "broken HTTP response")

    def test_timeout(self):
        self.assertFails(socket.timeout("timed out"), "network error.*timed out")

    def test_empty_body(self):
        self.assertFails([FakeResponse(b"  \n")], "empty response")

    def test_too_large(self):
        self.assertFails([FakeResponse(b"x" * 20)], "larger than 10 bytes", max_bytes=10)

    def test_only_https(self):
        for url in ("http://files.ember-energy.org/x.csv", "file:///etc/passwd", "ftp://x/y"):
            with mock.patch("urllib.request.urlopen") as urlopen:
                with self.assertRaisesRegex(R.RefreshError, "only https"):
                    R.fetch(url, 10)
                urlopen.assert_not_called()


class Command(IsolatedTestCase):
    def test_refresh_command_reports_and_exit_codes(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(R, "fetch", FakeFetch(recorded_answers())), \
                 mock.patch("sys.stdout", new_callable=io.StringIO) as out:
                self.assertEqual(cli.main(["refresh", "--out", d]), 0)
            self.assertIn("desnz-2026: ok, 51 rows", out.getvalue())
            answers = recorded_answers()
            answers[P.EMBER_CSV] = R.RefreshError("HTTP 429 rate limited by files.ember-energy.org")
            with mock.patch.object(R, "fetch", FakeFetch(answers)), \
                 mock.patch("sys.stdout", new_callable=io.StringIO) as out:
                self.assertEqual(cli.main(["refresh", "--out", d, "--only", "ember"]), 2)
            self.assertIn("ember: FAILED, previous snapshot kept: HTTP 429", out.getvalue())

    def test_refresh_rejects_unknown_source_names(self):
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            self.assertEqual(cli.main(["refresh", "--out", "unused", "--only", "ipcc"]), 2)


if __name__ == "__main__":
    import unittest
    unittest.main()
