"""What goes wrong on the wire: rate limits, server errors, resets, timeouts, broken bodies."""
import datetime
import email.utils
import gzip
import http.client
import socket
import urllib.error

import fakenet
import support
from support import fm

DB = "7LTWFZYICNSX8D621K86"
RECORD = f"gleif/{DB}"
# GLEIF's real 429 body was not recorded (asking 61 times a minute to see it would be the abuse the
# limit exists to stop). The tests depend on the status code and Retry-After only.
TOO_MANY = {"errors": [{"status": "429", "title": "Too Many Requests"}]}


class RateLimit(support.OfflineTest):
    def test_429_honours_retry_after_then_succeeds(self):
        self.net.script(RECORD, (429, TOO_MANY, {"Retry-After": "3"}))
        self.assertTrue(fm.lei_record(DB)["found"])
        self.assertEqual(self.sleeps, [3.0])
        self.assertEqual(len(self.net.requests), 2)

    def test_429_backs_off_2_then_4_seconds_then_gives_up(self):
        self.net.script(RECORD, *[(429, TOO_MANY, {})] * 3)
        with self.assertRaises(fm.SourceError) as cm:
            fm.lei_record(DB)
        self.assertEqual((cm.exception.source, cm.exception.kind), ("GLEIF", "rate_limited"))
        self.assertEqual(self.sleeps, [2.0, 4.0])
        self.assertEqual(len(self.net.requests), 3)

    def test_retry_after_is_capped(self):
        self.net.script(RECORD, (429, TOO_MANY, {"Retry-After": "3600"}))
        fm.lei_record(DB)
        self.assertEqual(self.sleeps, [fm.MAX_RETRY_WAIT])

    def test_retry_after_as_http_date(self):
        when = support.FIXED_NOW + datetime.timedelta(seconds=5)
        self.net.script(RECORD, (429, TOO_MANY, {"Retry-After": email.utils.format_datetime(when, usegmt=True)}))
        fm.lei_record(DB)
        self.assertEqual(self.sleeps, [5.0])

    def test_retry_after_garbage_falls_back_to_backoff(self):
        self.net.script(RECORD, (429, TOO_MANY, {"Retry-After": "soon"}))
        fm.lei_record(DB)
        self.assertEqual(self.sleeps, [2.0])

    def test_gleif_window_never_exceeds_60_a_minute(self):
        for _ in range(60):
            fm._throttle("GLEIF")
        self.assertEqual(self.sleeps, [])
        fm._throttle("GLEIF")  # the 61st inside the same minute waits for the oldest to age out
        self.assertEqual(self.sleeps, [60.0])
        self.clock[0] += 30
        fm._throttle("GLEIF")
        self.assertEqual(len(self.sleeps), 1)

    def test_esma_requests_are_spaced(self):
        fm._throttle("ESMA")
        fm._throttle("ESMA")
        self.assertEqual(self.sleeps, [0.5])


class ServerAndNetwork(support.OfflineTest):
    def test_503_is_retried_once(self):
        self.net.script(RECORD, (503, b"busy", {}))
        self.assertTrue(fm.lei_record(DB)["found"])
        self.assertEqual(self.sleeps, [1.0])

    def test_500_twice_is_an_error(self):
        self.net.script(RECORD, (500, b"", {}), (500, b"", {}))
        with self.assertRaises(fm.SourceError) as cm:
            fm.lei_record(DB)
        self.assertEqual((cm.exception.kind, cm.exception.detail), ("http", "HTTP 500"))

    def test_403_is_not_retried(self):
        self.net.script(RECORD, (403, b"forbidden", {}))
        with self.assertRaises(fm.SourceError) as cm:
            fm.lei_record(DB)
        self.assertEqual(cm.exception.detail, "HTTP 403")
        self.assertEqual(len(self.net.requests), 1)

    def test_network_down(self):
        down = urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))
        self.net.script(RECORD, down, down)
        with self.assertRaises(fm.SourceError) as cm:
            fm.lei_record(DB)
        self.assertEqual(cm.exception.kind, "network")
        self.assertIn("Connection refused", cm.exception.detail)
        self.assertEqual(len(self.net.requests), 2)

    def test_reset_once_is_retried(self):
        self.net.script(RECORD, ConnectionResetError(104, "Connection reset by peer"))
        self.assertTrue(fm.lei_record(DB)["found"])
        self.assertEqual(self.sleeps, [1.0])

    def test_proxy_credentials_are_masked(self):
        err = urllib.error.URLError("Tunnel connection failed via http://alice:hunter2@proxy.corp:3128/?key=x")
        self.net.script(RECORD, err, err)
        with self.assertRaises(fm.SourceError) as cm:
            fm.lei_record(DB)
        self.assertNotIn("hunter2", cm.exception.detail)
        self.assertNotIn("key=x", cm.exception.detail)
        self.assertIn("http://***@proxy.corp:3128/?***", cm.exception.detail)

    def test_masking_happens_before_the_cut(self):
        # A password longer than the kept length: cutting first would drop the "@" and keep the password.
        secret = "p" * 300
        err = urllib.error.URLError(f"Tunnel connection failed via http://alice:{secret}@proxy.corp:3128/")
        self.net.script(RECORD, err, err)
        with self.assertRaises(fm.SourceError) as cm:
            fm.lei_record(DB)
        self.assertNotIn("ppppp", cm.exception.detail)
        self.assertIn("http://***@proxy.corp:3128/", cm.exception.detail)

    def test_timeout_is_not_retried(self):
        self.net.script(RECORD, socket.timeout("timed out"))
        with self.assertRaises(fm.SourceError) as cm:
            fm.lei_record(DB)
        self.assertEqual(cm.exception.kind, "timeout")
        self.assertEqual(len(self.net.requests), 1)

    def test_timeout_wrapped_in_urlerror(self):
        self.net.script(RECORD, urllib.error.URLError(socket.timeout("timed out")))
        with self.assertRaises(fm.SourceError) as cm:
            fm.lei_record(DB)
        self.assertEqual(cm.exception.kind, "timeout")

    def test_incomplete_read_and_bad_status_line(self):
        for exc in (http.client.IncompleteRead(b'{"data": {'), http.client.BadStatusLine("HTTP/1.1 ??")):
            self.net.script(RECORD, exc, exc)
            with self.assertRaises(fm.SourceError) as cm:
                fm.lei_record(DB)
            self.assertEqual(cm.exception.kind, "network")
            self.assertIn(type(exc).__name__, cm.exception.detail)


class Bodies(support.OfflineTest):
    def assertBadPayload(self, body, fragment, headers=None):
        self.net.script(RECORD, (200, body, headers or {}))
        with self.assertRaises(fm.SourceError) as cm:
            fm.lei_record(DB)
        self.assertEqual(cm.exception.kind, "bad_payload")
        self.assertIn(fragment, cm.exception.detail)

    def test_empty(self):
        self.assertBadPayload(b"", "empty answer")
        self.assertBadPayload(b"  \n", "empty answer")

    def test_null(self):
        self.assertBadPayload(b"null", "not an object")

    def test_list(self):
        self.assertBadPayload(b"[1, 2]", "not an object")

    def test_not_utf8(self):
        self.assertBadPayload('{"data": "Société"}'.encode("latin-1"), "not UTF-8")

    def test_html_instead_of_json(self):
        self.assertBadPayload(b"<html><body>Maintenance</body></html>", "not JSON")

    def test_gzip_is_decoded(self):
        self.net.script(RECORD, fakenet.gzipped(RECORD))
        self.assertTrue(fm.lei_record(DB)["found"])

    def test_broken_gzip(self):
        self.assertBadPayload(b"\x1f\x8b not really gzip", "not valid gzip", {"Content-Encoding": "gzip"})

    def test_oversized_answers_are_refused(self):
        fm.MAX_BODY = 100
        self.assertBadPayload(b"{" + b" " * 200 + b"}", "larger than 100 bytes")

    def test_oversized_after_gzip(self):
        fm.MAX_BODY = 100
        self.assertBadPayload(gzip.compress(b"{" + b" " * 5000 + b"}"), "larger than 100 bytes",
                              {"Content-Encoding": "gzip"})

    def test_404_with_html_body(self):
        self.net.script(RECORD, (404, b"<html>Not Found</html>", {}))
        self.assertEqual(fm.lei_record(DB)["found"], False)


if __name__ == "__main__":
    import unittest
    unittest.main()
