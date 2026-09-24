"""refresh against a fake backend serving trimmed real responses. No network."""
import argparse
import contextlib
import datetime as dt
import http.client
import io
import json
import re
import socket
import sys
import tempfile
import unittest
import unittest.mock
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _support import (API, FakeOpener, core, fetcher, fixture_snapshot, http_error, load, raw,  # noqa: E402
                      refresh)

NOW = dt.datetime(2026, 9, 24, 9, 22, 42, tzinfo=dt.timezone.utc)
ALLOWED_PATH = re.compile(r"^/(sectors|activities|activities/matches/all|activities/[1-9][0-9]{0,8}/matches)$")


class Refresh(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name) / "data"

    def tearDown(self):
        self.tmp.cleanup()

    def run_refresh(self, opener, per_activity=False):
        f = fetcher(opener)
        return refresh.run(self.out, f, per_activity=per_activity, now=NOW, clock=lambda: 0.0), f

    def assert_only_known_paths(self, opener):
        for url in opener.urls:
            self.assertTrue(url.startswith(API))
            self.assertRegex(url[len(API):], ALLOWED_PATH)

    # -- the paths that work
    def test_three_requests_build_the_snapshot_and_sources(self):
        opener = FakeOpener.healthy()
        summary, f = self.run_refresh(opener)
        self.assertEqual((summary["requests"], summary["mode"]), (3, "bulk"))
        self.assertEqual(f.sleeps, [1.0, 1.0])  # a pause before every request but the first
        self.assertTrue(all(h.get("User-agent", "").startswith("eu-taxonomy-mcp/") for h in opener.headers))
        c = summary["counts"]
        self.assertEqual((c["sectors"], c["activities"], c["criteria_sets"], c["dnsh_entries"]), (16, 7, 9, 45))
        self.assertEqual((c["activities_without_criteria"], c["activities_without_nace_codes"]), (1, 1))
        notes = (self.out / "SOURCES.md").read_text(encoding="utf-8")
        for name in ("sectors.json", "activities.json", "matches_all.json"):
            self.assertIn(refresh._sha256(raw(name)), notes)
        self.assertIn(summary["sha256"], notes)
        self.assertIn("CC BY 4.0", notes)
        self.assertEqual(core.Taxonomy.load(self.out / "taxonomy.json").retrieved, "2026-09-24")
        self.assert_only_known_paths(opener)

    def test_same_data_in_another_order_gives_the_same_bytes(self):
        shuffled = FakeOpener.healthy(**{
            "__sectors": json.dumps(load("sectors.json")[::-1]).encode(),
            "__activities": json.dumps(load("activities.json")[::-1]).encode(),
            "__activities__matches__all": json.dumps(load("matches_all.json")[::-1]).encode()})
        first, _ = self.run_refresh(FakeOpener.healthy())
        second, _ = self.run_refresh(shuffled)
        self.assertEqual(first["sha256"], second["sha256"])
        self.assertEqual(second["changes"], "no change in activities or criteria")

    def test_bulk_failure_falls_back_to_one_request_per_activity_with_identical_result(self):
        bulk, _ = self.run_refresh(FakeOpener.healthy())
        opener = FakeOpener.healthy(__activities__matches__all=http_error(API, 500, raw("error_500.json")))
        summary, f = self.run_refresh(opener)
        self.assertEqual(summary["mode"], "per-activity")
        self.assertEqual(summary["requests"], 2 + 2 + 7)  # sectors, activities, bulk twice, 7 activities
        self.assertEqual(summary["sha256"], bulk["sha256"])
        self.assertIn(5.0, f.sleeps)  # the pause before retrying the 500
        self.assert_only_known_paths(opener)

    def test_429_waits_as_told_then_succeeds(self):
        opener = FakeOpener.healthy(__sectors=[http_error(API, 429, b"", {"Retry-After": "7"}), raw("sectors.json")])
        summary, f = self.run_refresh(opener)
        self.assertEqual(summary["requests"], 4)
        self.assertIn(7.0, f.sleeps)

    def test_retry_after_is_capped(self):
        self.assertEqual(refresh._retry_after({"Retry-After": "86400"}), refresh.RETRY_AFTER_CAP)
        self.assertIsNone(refresh._retry_after({"Retry-After": "soon"}))
        self.assertIsNone(refresh._retry_after({"Retry-After": "\u00b2"}))
        self.assertEqual(refresh._retry_after({"Retry-After": "Thu, 01 Jan 1970 00:00:00 GMT"}), 0.0)
        self.assertIsNone(refresh._retry_after({}))

    # -- the paths that fail: nothing is written, the old snapshot stays
    def assert_fails_and_keeps_old(self, opener, message, per_activity=False):
        self.run_refresh(FakeOpener.healthy())
        before = (self.out / "taxonomy.json").read_bytes(), (self.out / "SOURCES.md").read_bytes()
        with self.assertRaises(refresh.RefreshError) as ctx:
            self.run_refresh(opener, per_activity=per_activity)
        self.assertIn(message, str(ctx.exception))
        self.assertEqual(before, ((self.out / "taxonomy.json").read_bytes(), (self.out / "SOURCES.md").read_bytes()))
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), ["SOURCES.md", "taxonomy.json"])
        return ctx.exception

    def test_backend_500_on_sectors(self):
        opener = FakeOpener.healthy(__sectors=http_error(API, 500, raw("error_500.json")))
        self.assert_fails_and_keeps_old(opener, "HTTP 500 (Internal Server Error, No message available)")
        self.assertEqual(len(opener.urls), 2)  # one retry, then stop

    def test_bodies_that_are_not_usable_json(self):
        cases = {b"": "empty response body", b"   \n": "empty response body", b"null": "JSON null",
                 b"\xff\xfe\x00{": "not UTF-8", raw("navigator_index_head.html"): "not JSON"}
        for body, message in cases.items():
            with self.subTest(message=message):
                self.assert_fails_and_keeps_old(FakeOpener.healthy(__sectors=body), message)

    def test_connection_failures(self):
        failures = {
            "IncompleteRead": http.client.IncompleteRead(b"[{\"id\":24"),
            "RemoteDisconnected": http.client.RemoteDisconnected("Remote end closed connection"),
            "BadStatusLine": http.client.BadStatusLine("HTTP/1.1 ???"),
            "timed out": socket.timeout("timed out"),
            "Name or service not known": urllib.error.URLError("[Errno -2] Name or service not known"),
            "Connection refused": ConnectionRefusedError(111, "Connection refused"),
        }
        for message, exc in failures.items():
            with self.subTest(message=message):
                opener = FakeOpener.healthy(__activities=exc)
                self.assert_fails_and_keeps_old(opener, message)
                self.assertEqual(sum(u.endswith("/activities") for u in opener.urls), 2)

    def test_404_is_reported_with_the_backend_code_and_not_retried(self):
        opener = FakeOpener.healthy(__activities__matches__all=http_error(API, 500),
                                    __activities__287__matches=http_error(API, 404, raw("error_404.json")))
        self.assert_fails_and_keeps_old(opener, "HTTP 404 (ACTIVITY_ID_NOT_FOUND")
        self.assertEqual(sum(u.endswith("/287/matches") for u in opener.urls), 1)

    def test_payloads_that_changed_shape(self):
        activities = load("activities.json")
        no_id = [dict(a) for a in activities]
        del no_id[0]["id"]
        unknown_sector = [dict(a, sector={"id": 999, "name": "x"}) if a["id"] == 287 else a for a in activities]
        cases = {
            "expected a JSON list, got dict": {"__activities": b'{"content": [], "totalPages": 0}'},
            "missing or invalid id": {"__activities": json.dumps(no_id).encode()},
            "sector 999 is not in /sectors": {"__activities": json.dumps(unknown_sector).encode()},
            "/sectors: empty list": {"__sectors": b"[]"},
        }
        for message, override in cases.items():
            with self.subTest(message=message):
                self.assert_fails_and_keeps_old(FakeOpener.healthy(**override), message)

    def test_criteria_for_an_unknown_activity_fail_both_ways(self):
        stray = load("matches_all.json")
        stray[0] = dict(stray[0], activity=dict(stray[0]["activity"], id=424242))
        opener = FakeOpener.healthy(__activities__matches__all=json.dumps(stray).encode(),
                                    __activities__272__matches=json.dumps(stray[:1]).encode())
        self.assert_fails_and_keeps_old(opener, "activity 424242 is not in /activities")

    def test_ids_from_the_backend_are_validated_before_use_in_a_url(self):
        tampered = load("activities.json")
        tampered[0] = dict(tampered[0], id="287/../../admin")
        opener = FakeOpener.healthy(__activities=json.dumps(tampered).encode())
        self.assert_fails_and_keeps_old(opener, "invalid id")
        self.assertFalse(any("admin" in u for u in opener.urls))

    def test_foreign_files_are_never_overwritten(self):
        self.out.mkdir(parents=True)
        (self.out / "SOURCES.md").write_text("# someone else's notes\n", encoding="utf-8")
        opener = FakeOpener.healthy()
        with self.assertRaises(refresh.RefreshError):
            self.run_refresh(opener)
        self.assertEqual(opener.urls, [])  # refused before sending anything
        self.assertEqual((self.out / "SOURCES.md").read_text(encoding="utf-8"), "# someone else's notes\n")

    # -- the command line
    def test_command_exits_2_on_failure_and_0_on_success(self):
        args = argparse.Namespace(out=str(self.out), delay=0, timeout=5, per_activity=False)
        err = io.StringIO()
        with unittest.mock.patch.object(refresh.urllib.request, "urlopen", FakeOpener.healthy(
                __sectors=urllib.error.URLError("offline"))), unittest.mock.patch.object(refresh.time, "sleep"), \
                contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(refresh.main(args), 2)
        self.assertIn("offline", err.getvalue())
        self.assertFalse(self.out.exists())
        out = io.StringIO()
        with unittest.mock.patch.object(refresh.urllib.request, "urlopen", FakeOpener.healthy()), \
                unittest.mock.patch.object(refresh.time, "sleep") as slept, \
                contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(out):
            self.assertEqual(refresh.main(args), 0)
        self.assertIn("3 requests (bulk)", out.getvalue())
        self.assertEqual({c.args[0] for c in slept.call_args_list}, {refresh.MIN_DELAY})  # --delay 0 is raised

    def test_out_is_required_outside_a_checkout(self):
        with unittest.mock.patch.object(core, "HERE", Path(self.tmp.name)):
            with self.assertRaises(refresh.RefreshError):
                refresh.resolve_out(None)
        self.assertEqual(refresh.resolve_out(str(self.out)), self.out)


class SnapshotShape(unittest.TestCase):
    def test_only_allowlisted_fields_enter_the_snapshot(self):
        activities = load("activities.json")
        activities[0]["modifiedBy"] = "Jane Doe"
        matches = load("matches_all.json")
        matches[0]["createdBy"] = "John Doe"
        sectors = refresh.check_sectors(load("sectors.json"))
        snap = refresh.build_snapshot(sectors, refresh.check_activities(activities, {s["id"] for s in sectors}),
                                      refresh.check_matches(matches, {a["id"] for a in activities}), "2026-09-24")
        text = refresh.serialize(snap).decode("utf-8")
        self.assertNotIn("Doe", text)

    def test_nace_whitespace_is_stripped_and_quirks_kept(self):
        snap = fixture_snapshot()
        codes = {a["id"]: a["naceCodes"] for a in snap["activities"]}
        self.assertEqual(codes[287], ["D35.11", "F42.22"])
        self.assertEqual(codes[360], ["M71.1.2", "M72.1"])
        self.assertEqual(codes[296], [])


if __name__ == "__main__":
    unittest.main()
