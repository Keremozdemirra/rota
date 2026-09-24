import http.client
import json
import os
import socket
import sys
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import support  # noqa: E402
from eudr_scope_mcp import cellar  # noqa: E402


class Sequence:
    """A fake _open that plays back a list of outcomes (exception or body)."""

    def __init__(self, *outcomes, ctype="application/sparql-results+json"):
        self.outcomes, self.ctype, self.calls = list(outcomes), ctype, 0

    def __call__(self, request, timeout):
        self.calls += 1
        item = self.outcomes.pop(0)
        if isinstance(item, BaseException):
            raise item
        return 200, {"Content-Type": self.ctype}, item, request.full_url


OK = json.dumps({"head": {"vars": ["x"]}, "results": {"bindings": [{"x": {"type": "literal", "value": "1"}}]}}).encode()


class Fetch(unittest.TestCase):
    def setUp(self):
        self.saved = (cellar._open, cellar.RETRY_DELAY)
        cellar.RETRY_DELAY = 0

    def tearDown(self):
        cellar._open, cellar.RETRY_DELAY = self.saved

    def run_with(self, *outcomes):
        cellar._open = Sequence(*outcomes)
        return cellar._open

    def test_network_down(self):
        self.run_with(*[urllib.error.URLError("Name or service not known")] * 3)
        with self.assertRaises(cellar.FetchError) as ctx:
            cellar.sparql("SELECT 1")
        self.assertIn("after 3 attempts", str(ctx.exception))

    def test_404_is_not_retried(self):
        fake = self.run_with(support.http_error(404), OK)
        with self.assertRaises(cellar.FetchError) as ctx:
            cellar.sparql("SELECT 1")
        self.assertIn("HTTP 404", str(ctx.exception))
        self.assertEqual(fake.calls, 1)

    def test_429_then_success(self):
        fake = self.run_with(support.http_error(429), support.http_error(503), OK)
        self.assertEqual(cellar.sparql("SELECT 1"), [{"x": "1"}])
        self.assertEqual(fake.calls, 3)

    def test_429_until_giving_up(self):
        self.run_with(*[support.http_error(429)] * 3)
        with self.assertRaises(cellar.FetchError):
            cellar.sparql("SELECT 1")

    def test_timeout_and_incomplete_read(self):
        self.run_with(socket.timeout("timed out"), http.client.IncompleteRead(b"{"), OK)
        self.assertEqual(cellar.sparql("SELECT 1"), [{"x": "1"}])

    def test_bad_status_line(self):
        self.run_with(*[http.client.BadStatusLine("garbage")] * 3)
        with self.assertRaises(cellar.FetchError):
            cellar.sparql("SELECT 1")

    def test_empty_body(self):
        self.run_with(b"")
        with self.assertRaises(cellar.FetchError):
            cellar.sparql("SELECT 1")

    def test_null_body(self):
        self.run_with(b"null")
        with self.assertRaises(cellar.FetchError):
            cellar.sparql("SELECT 1")

    def test_not_json(self):
        self.run_with(b"<html>Service Unavailable</html>")
        with self.assertRaises(cellar.FetchError):
            cellar.sparql("SELECT 1")

    def test_not_utf8(self):
        self.run_with(b'{"results": {"bindings": []}, "x": "\xff\xfe"}')
        with self.assertRaises(cellar.FetchError):
            cellar.sparql("SELECT 1")

    def test_malformed_bindings(self):
        for body in (b'{"results": {}}', b'{"results": {"bindings": {}}}', b'{"results": {"bindings": [1]}}',
                     b'{"results": {"bindings": [{"x": {"value": 3}}]}}', b"[]"):
            with self.subTest(body=body):
                self.run_with(body)
                with self.assertRaises(cellar.FetchError):
                    cellar.sparql("SELECT 1")

    def test_empty_result_is_an_empty_list(self):
        self.run_with(b'{"results": {"bindings": []}}')
        self.assertEqual(cellar.sparql("SELECT 1"), [])

    def test_xhtml_with_wrong_content_type(self):
        cellar._open = Sequence(b"%PDF-1.7", ctype="application/pdf")
        with self.assertRaises(cellar.FetchError):
            cellar.xhtml("32023R1115")

    def test_oversized_body(self):
        self.run_with(b"x" * (cellar.MAX_BYTES + 1))
        with self.assertRaises(cellar.FetchError):
            cellar.fetch(cellar.SPARQL, "application/json")


class Guards(unittest.TestCase):
    def test_celex_grammar(self):
        for good in ("32023R1115", "02023R1115-20251226", "32023R1115R(05)", "52026PC0661", "32025R1093"):
            self.assertEqual(cellar.check_celex(good), good)
        for bad in ("32023R1115/../x", "3202", "32023R1115 OR 1=1", '32023R1115"^^xsd:string', "", None, "02023R1115-2025"):
            with self.subTest(bad=bad), self.assertRaises(cellar.FetchError):
                cellar.check_celex(bad)

    def test_only_https_to_the_publications_office(self):
        for url in ("http://publications.europa.eu/resource/celex/32023R1115", "https://example.org/x",
                    "file:///etc/passwd", "https://publications.europa.eu.evil.example/x"):
            with self.subTest(url=url), self.assertRaises(cellar.FetchError):
                cellar.fetch(url, "text/html")

    def test_redirect_to_another_host_is_refused(self):
        handler = cellar._SameHostHttps()
        req = urllib.request.Request("https://publications.europa.eu/resource/celex/32023R1115")
        with self.assertRaises(cellar.FetchError):
            handler.redirect_request(req, None, 303, "See Other", {}, "https://evil.example/doc")

    def test_redirect_to_plain_http_is_upgraded(self):
        handler = cellar._SameHostHttps()
        req = urllib.request.Request("https://publications.europa.eu/resource/celex/32023R1115")
        new = handler.redirect_request(req, None, 303, "See Other", {},
                                       "http://publications.europa.eu/resource/cellar/abc.0006.03/DOC_1")
        self.assertEqual(new.full_url, "https://publications.europa.eu/resource/cellar/abc.0006.03/DOC_1")


if __name__ == "__main__":
    unittest.main()
