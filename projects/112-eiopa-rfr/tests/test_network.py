"""http_get against a fake opener: every way a fetch from EIOPA has failed or can fail."""
from __future__ import annotations

import email.message
import http.client
import socket
import urllib.error
import urllib.request
from unittest import mock

from tests.support import E, Isolated, fixture

PAGE = E.RFR_PAGE


def headers(**values) -> email.message.Message:
    msg = email.message.Message()
    for k, v in values.items():
        msg[k.replace("_", "-")] = v
    return msg


class Response:
    def __init__(self, body: bytes, chunk: int = 1 << 16, fail_after: BaseException | None = None, **hdrs):
        self.body, self.chunk, self.pos, self.fail_after = body, chunk, 0, fail_after
        self.headers = headers(**hdrs)

    def read(self, n=-1):
        if self.fail_after is not None and self.pos >= len(self.body):
            raise self.fail_after
        piece = self.body[self.pos:self.pos + min(n if n > 0 else len(self.body), self.chunk)]
        self.pos += len(piece)
        return piece

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def http_error(code: int, **hdrs) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(PAGE, code, "error", headers(**hdrs), None)


class Opener:
    """Answers each open() with the next scripted response or exception."""

    def __init__(self, *script):
        self.script = list(script)
        self.requests = []

    def open(self, request, timeout=None):
        self.requests.append((request.full_url, request.get_header("User-agent"), timeout))
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class HttpGet(Isolated):
    fake_web = False

    def use_opener(self, *script) -> Opener:
        opener = Opener(*script)
        p = mock.patch.object(E, "_OPENER", opener)
        p.start()
        self.addCleanup(p.stop)
        return opener

    def fetch_error(self, *script, **kwargs) -> E.FetchError:
        self.use_opener(*script)
        with self.assertRaises(E.FetchError) as ctx:
            E.http_get(PAGE, "EIOPA's RFR page", **kwargs)
        return ctx.exception

    def test_body_is_read_in_chunks(self):
        opener = self.use_opener(Response(fixture("rfr_page.html"), chunk=1000))
        self.assertEqual(E.http_get(PAGE, "page"), fixture("rfr_page.html"))
        url, agent, timeout = opener.requests[0]
        self.assertEqual((url, timeout), (PAGE, E.PAGE_TIMEOUT))
        self.assertTrue(agent.startswith("eiopa-rfr/"))

    def test_network_down(self):
        e = self.fetch_error(urllib.error.URLError(ConnectionRefusedError(111, "Connection refused")))
        self.assertTrue(e.network)
        self.assertEqual(str(e), "could not reach www.eiopa.europa.eu for EIOPA's RFR page: Connection refused")

    def test_dns_failure(self):
        e = self.fetch_error(urllib.error.URLError(socket.gaierror(-2, "Name or service not known")))
        self.assertIn("Name or service not known", str(e))

    def test_timeout_while_connecting(self):
        e = self.fetch_error(urllib.error.URLError(socket.timeout("timed out")))
        self.assertTrue(e.network)
        self.assertIn("timed out", str(e))

    def test_timeout_while_reading(self):
        e = self.fetch_error(Response(b"<html>", fail_after=socket.timeout("timed out")))
        self.assertIn("did not answer within 30 s", str(e))

    def test_not_found(self):
        e = self.fetch_error(http_error(404))
        self.assertEqual(e.status, 404)
        self.assertIn("HTTP 404", str(e))

    def test_rate_limited_then_served(self):
        self.use_opener(http_error(429, Retry_After="10.000"), Response(b"ok"))
        self.assertEqual(E.http_get(PAGE, "page"), b"ok")
        self.assertEqual(self.sleeps, [10.0])

    def test_rate_limited_twice(self):
        e = self.fetch_error(http_error(429, Retry_After="10.000"), http_error(429, Retry_After="10.000"))
        self.assertEqual(e.status, 429)
        self.assertIn("HTTP 429, Retry-After 10.000 s", str(e))
        self.assertEqual(self.sleeps, [10.0])

    def test_long_or_odd_retry_after_is_capped(self):
        self.use_opener(http_error(429, Retry_After="3600"), Response(b"ok"))
        E.http_get(PAGE, "page")
        self.use_opener(http_error(503, Retry_After="Wed, 21 Oct 2026 07:28:00 GMT"), Response(b"ok"))
        E.http_get(PAGE, "page")
        self.use_opener(http_error(429), Response(b"ok"))
        E.http_get(PAGE, "page")
        self.assertEqual(self.sleeps, [10.0, 3.0, 3.0])

    def test_server_error_is_not_retried(self):
        e = self.fetch_error(http_error(500))
        self.assertEqual((e.status, self.sleeps), (500, []))

    def test_incomplete_read(self):
        e = self.fetch_error(Response(b"PK\x03\x04", fail_after=http.client.IncompleteRead(b"PK", 3000)))
        self.assertIn("broke while fetching", str(e))
        self.assertIn("IncompleteRead", str(e))

    def test_bad_status_line_and_disconnect(self):
        for exc in (http.client.BadStatusLine("HTTP/1.1 ???"), http.client.RemoteDisconnected("closed"),
                    ConnectionResetError(104, "reset")):
            e = self.fetch_error(exc)
            self.assertTrue(e.network, exc)

    def test_declared_size_too_large(self):
        e = self.fetch_error(Response(b"x", Content_Length=str(E.MAX_PAGE_BYTES + 1)))
        self.assertIn("larger than 8 MB", str(e))

    def test_streamed_size_too_large(self):
        e = self.fetch_error(Response(b"x" * 5000, chunk=1000), max_bytes=4096)
        self.assertIn("not downloaded", str(e))

    def test_redirect_off_eiopas_host_is_refused(self):
        handler = E._SameHostRedirect()
        req = urllib.request.Request(PAGE)
        with self.assertRaises(E.FetchError):
            handler.redirect_request(req, None, 302, "Found", {}, "https://evil.example/EIOPA_RFR_20260831.zip")
        followed = handler.redirect_request(req, None, 302, "Found", {}, "/tools-and-data/elsewhere_en")
        self.assertEqual(followed.full_url, "https://www.eiopa.europa.eu/tools-and-data/elsewhere_en")

    def test_only_https_on_eiopas_host(self):
        for bad in ("http://www.eiopa.europa.eu/x", "https://eiopa.europa.eu.evil.example/x", "ftp://www.eiopa.europa.eu/x",
                    "https://user:secret@www.eiopa.europa.eu/x", "https://www.eiopa.europa.eu:8443/x",
                    "https://www.eiopa.europa.eu:99999/x", "file:///etc/passwd"):
            with self.assertRaises(E.FetchError, msg=bad):
                E.checked_url(bad)
        self.assertEqual(E.checked_url("/document/download/x_en?filename=a.zip#top", PAGE),
                         "https://www.eiopa.europa.eu/document/download/x_en?filename=a.zip")
        self.assertEqual(E.checked_url("HTTPS://WWW.EIOPA.EUROPA.EU/a"), "https://www.eiopa.europa.eu/a")

    def test_empty_200_page_means_no_release_list(self):
        self.use_opener(Response(b""), Response(b""))
        with self.assertRaises(E.FetchError) as ctx:
            E.fetch_listing()
        self.assertIn("no release could be read", str(ctx.exception))

    def test_a_429_page_served_with_status_200_is_not_cached_as_a_release(self):
        with self.assertRaises(E.FetchError):
            E.store_release(fixture("throttled_429.html"), {"file": "EIOPA_RFR_20260831.zip"}, None)
        self.assertFalse((self.cache / "releases").exists())
