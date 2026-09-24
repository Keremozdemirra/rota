"""refresh: the download failures that happen, and a run against recorded answers. No network."""
import hashlib
import http.client
import io
import json
import socket
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cbam_test_support import FakeFetcher, build, fixture  # noqa: E402
from cbam_mcp import refresh  # noqa: E402
from cbam_mcp.refresh import FetchError  # noqa: E402


class FakeResponse:
    def __init__(self, body=b"ok", status=200, headers=None, read_error=None):
        self.body, self.status, self.read_error = body, status, read_error
        self.headers = headers or {"Content-Type": "text/plain"}

    def read(self, n=-1):
        if self.read_error:
            raise self.read_error
        return self.body if n < 0 else self.body[:n]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def http_error(code, headers=None):
    return urllib.error.HTTPError("https://x.test/", code, "error", headers or {}, io.BytesIO(b""))


class Fetch(unittest.TestCase):
    def fetch(self, *outcomes, **kw):
        sleeps = []
        with mock.patch("urllib.request.urlopen", side_effect=list(outcomes)) as urlopen:
            try:
                return refresh.fetch("https://x.test/", sleep=sleeps.append, **kw), sleeps, urlopen.call_count
            except FetchError as e:
                return e, sleeps, urlopen.call_count

    def test_ok(self):
        got, sleeps, calls = self.fetch(FakeResponse(b"body", headers={"Content-Disposition": "inline"}))
        self.assertEqual((got.body, got.headers["content-disposition"], sleeps, calls), (b"body", "inline", [], 1))

    def test_network_down_is_retried_once_then_reported(self):
        err, sleeps, calls = self.fetch(urllib.error.URLError("Name or service not known"),
                                        urllib.error.URLError("Name or service not known"))
        self.assertIn("network error", str(err))
        self.assertEqual((calls, sleeps), (2, [3]))

    def test_404_is_not_retried(self):
        err, sleeps, calls = self.fetch(http_error(404))
        self.assertIn("HTTP 404", str(err))
        self.assertEqual((calls, sleeps), (1, []))

    def test_429_waits_retry_after_then_succeeds(self):
        got, sleeps, calls = self.fetch(http_error(429, {"Retry-After": "7"}), FakeResponse(b"late"))
        self.assertEqual((got.body, sleeps, calls), (b"late", [7], 2))

    def test_429_twice_is_rate_limited(self):
        err, sleeps, _ = self.fetch(http_error(429), http_error(429))
        self.assertIn("rate limited", str(err))
        self.assertEqual(sleeps, [3])

    def test_long_retry_after_is_not_obeyed(self):
        _, sleeps, _ = self.fetch(http_error(503, {"Retry-After": "3600"}), FakeResponse())
        self.assertEqual(sleeps, [3])

    def test_timeout(self):
        err, _, _ = self.fetch(socket.timeout("timed out"), TimeoutError())
        self.assertIn("timed out", str(err))

    def test_incomplete_read_and_reset(self):
        err, _, calls = self.fetch(FakeResponse(read_error=http.client.IncompleteRead(b"par")),
                                   ConnectionResetError("reset by peer"))
        self.assertIn("connection failed", str(err))
        self.assertEqual(calls, 2)

    def test_bad_bodies(self):
        for resp, expected in ((FakeResponse(b"", status=202), "HTTP 202"), (FakeResponse(b"  \n"), "empty"),
                               (FakeResponse(b"x" * 50), "larger than")):
            err, _, calls = self.fetch(resp, max_bytes=10)
            self.assertIsInstance(err, FetchError)
            self.assertIn(expected, str(err))
            self.assertEqual(calls, 1)


class Masking(unittest.TestCase):
    def test_credentials_and_query_strings_never_reach_messages(self):
        secret = "s3cr3t" + "x" * 12  # built at runtime: no token-shaped literal in the repository
        err = FetchError(f"https://user:{secret}@proxy.test/file?token={secret}&a=1: HTTP 404")
        self.assertNotIn(secret, str(err))
        self.assertEqual(str(err), "https://***@proxy.test/file?*** HTTP 404")
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError(f"http://u:{secret}@p:3128 refused")):
            with self.assertRaises(FetchError) as cm:
                refresh.fetch(f"https://x.test/f?key={secret}", sleep=lambda s: None)
        self.assertNotIn(secret, str(cm.exception))


class Run(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cbam-mcp-refresh-"))

    def files(self):
        return {p.name: p.read_bytes() for p in sorted(self.tmp.iterdir())}

    def test_full_run_writes_every_file_with_hashes(self):
        fetcher = FakeFetcher()
        self.assertEqual(build(self.tmp, fetcher), 0)
        self.assertEqual(sorted(self.files()), ["SOURCES.md", "annex_i.json", "cn_2025.json", "cn_2026.json",
                                                "default_values.json", "later_acts.json"])
        annex = json.loads((self.tmp / "annex_i.json").read_text(encoding="utf-8"))
        values = json.loads((self.tmp / "default_values.json").read_text(encoding="utf-8"))
        self.assertEqual(annex["meta"]["sha256"], hashlib.sha256(fixture("consolidated_trimmed.xhtml")).hexdigest())
        self.assertEqual(annex["meta"]["celex"], "02023R0956-20251020")
        m = values["meta"]
        self.assertEqual((m["version"], m["version_date"], m["filename"]), ("2", "2026-08-06", "DV correcting act_final update_06.08.xlsx"))
        self.assertEqual(m["oj_check"]["rows_identical"], m["oj_check"]["rows_compared"])
        self.assertTrue(all(m["oj_check"]["quotes_found"].values()))
        self.assertTrue(m["page_check"]["this_file_listed"])
        sources = (self.tmp / "SOURCES.md").read_text(encoding="utf-8")
        for digest in (annex["meta"]["sha256"], m["sha256"]):
            self.assertIn(digest, sources)
        self.assertIn("Dated after 32026R1740 (2026-07-20): none", sources)
        self.assertIn("CC BY 4.0", sources)
        self.assertEqual([p for p in self.tmp.iterdir() if p.suffix == ".tmp"], [])

    def test_failed_source_keeps_its_previous_file(self):
        self.assertEqual(build(self.tmp), 0)
        before = self.files()
        down = FakeFetcher(fail={"excel": FetchError("https://taxation-customs.ec.europa.eu/...: network error")})
        self.assertEqual(build(self.tmp, down), 2)
        after = self.files()
        self.assertEqual(before["default_values.json"], after["default_values.json"])
        self.assertIn("SOURCES.md", after)

    def test_malformed_payloads_do_not_replace_data(self):
        self.assertEqual(build(self.tmp), 0)
        before = self.files()
        broken = FakeFetcher(fail={"excel": b"<html>Service temporarily unavailable</html>",
                                   "consolidated": b"<html><body><p>Maintenance</p></body></html>",
                                   "sparql_cn2026": b"\xff\xfe not utf-8", "sparql_cn2025": b'{"results": {"bindings": []}}'})
        self.assertEqual(build(self.tmp, broken), 2)
        after = self.files()
        for name in ("default_values.json", "annex_i.json", "cn_2026.json", "cn_2025.json"):
            self.assertEqual(before[name], after[name], name)

    def test_consolidation_lookup_failure_uses_pinned_text(self):
        fetcher = FakeFetcher(fail={"sparql_consolidated": FetchError("SPARQL: HTTP 500")})
        self.assertEqual(build(self.tmp, fetcher, check_oj=False), 0)
        annex = json.loads((self.tmp / "annex_i.json").read_text(encoding="utf-8"))
        self.assertEqual(annex["meta"]["celex"], refresh.PINNED_CONSOLIDATION)
        self.assertIn("pinned", annex["meta"]["notes"][0])

    def test_later_acts_failure_is_not_fatal(self):
        self.assertEqual(build(self.tmp), 0)
        before = (self.tmp / "later_acts.json").read_bytes()
        self.assertEqual(build(self.tmp, FakeFetcher(fail={"sparql_later_acts": FetchError("HTTP 429 (rate limited)")})), 0)
        self.assertEqual(before, (self.tmp / "later_acts.json").read_bytes())

    def test_official_journal_difference_exits_1(self):
        oj = fixture("oj_1740_trimmed.xhtml")
        self.assertIn(b"1,870", oj)
        changed = FakeFetcher(override={"oj": oj.replace(b"1,870", b"1,871", 1)})
        self.assertEqual(build(self.tmp, changed), 1)
        check = json.loads((self.tmp / "default_values.json").read_text(encoding="utf-8"))["meta"]["oj_check"]
        self.assertEqual(len(check["differences"]), 1)
        self.assertEqual(check["differences"][0]["official_journal"][0], "1,871")

    def test_check_survives_only_for_the_same_file(self):
        self.assertEqual(build(self.tmp), 0)
        self.assertEqual(build(self.tmp, check_oj=False), 0)
        values = json.loads((self.tmp / "default_values.json").read_text(encoding="utf-8"))
        self.assertIsNotNone(values["meta"]["oj_check"])

    def test_truncated_cn_answer_is_refused(self):
        self.assertEqual(build(self.tmp), 0)
        before = (self.tmp / "cn_2026.json").read_bytes()
        with mock.patch.object(refresh, "MIN_CN_CONCEPTS", 10_000):
            code = refresh.run(self.tmp, fetcher=FakeFetcher(), today="2026-09-24", only=["cn"], log=lambda *a: None)
        self.assertEqual(code, 2)
        self.assertEqual(before, (self.tmp / "cn_2026.json").read_bytes())

    def test_unwritable_directory(self):
        blocker = self.tmp / "a-file"
        blocker.write_text("x", encoding="utf-8")
        messages = []
        self.assertEqual(refresh.run(blocker / "data", fetcher=FakeFetcher(), log=messages.append), 2)
        self.assertIn("cannot write", messages[0])


if __name__ == "__main__":
    unittest.main()
