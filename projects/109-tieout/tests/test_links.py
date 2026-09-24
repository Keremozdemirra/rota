"""--check-links: what is requested, what is refused, and how every answer and failure is reported.

The doi.org bodies in tests/fixtures are real answers of https://doi.org/api/handles/<doi>, recorded
2026-09-24 (doi-found.json trimmed to its URL value). HTTP statuses and network failures are simulated
by a stand-in opener, so nothing here touches the network.
"""
import http.client
import io
import json
import socket
import ssl
import unittest
from unittest import mock
import urllib.error
import urllib.request

from tests.support import FIXTURES, IsolatedTestCase, docx, para, run_cli, tieout, rels, write_zip, W


class Response:
    def __init__(self, status, url, body=b""):
        self.status, self.url, self.body = status, url, body

    def read(self, n=-1):
        return self.body if n < 0 else self.body[:n]

    def geturl(self):
        return self.url

    def getcode(self):
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def http_error(url, code, body=b""):
    return urllib.error.HTTPError(url, code, "status", {}, io.BytesIO(body))


class Opener:
    """Answers by (method, url); anything else is a test failure."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def open(self, req, timeout=None):
        self.calls.append((req.get_method(), req.full_url, req.get_header("User-agent"), timeout))
        answer = self.answers.get((req.get_method(), req.full_url), self.answers.get(req.full_url))
        if answer is None:
            raise AssertionError(f"unexpected request {req.get_method()} {req.full_url}")
        if isinstance(answer, BaseException):
            raise answer
        if isinstance(answer, int):
            if answer >= 400:
                raise http_error(req.full_url, answer)
            return Response(answer, req.full_url)
        return answer


def link(target, kind="url"):
    return {"kind": kind, "target": target, "where": "paragraph 1"}


class Urls(IsolatedTestCase):
    URL = "https://example.org/report"

    def check(self, answers, target=URL):
        opener = Opener(answers)
        return tieout.check_link(link(target), 5, opener), opener

    def test_head_ok(self):
        out, op = self.check({("HEAD", self.URL): 200})
        self.assertEqual((out["status"], out["http_status"]), ("resolves", 200))
        self.assertEqual([c[0] for c in op.calls], ["HEAD"])
        self.assertTrue(op.calls[0][2].startswith("tieout/"))
        self.assertEqual(op.calls[0][3], 5)

    def test_head_refused_then_get(self):
        out, op = self.check({("HEAD", self.URL): 405, ("GET", self.URL): 200})
        self.assertEqual(out["status"], "resolves")
        self.assertEqual([c[0] for c in op.calls], ["HEAD", "GET"])

    def test_not_found_and_gone(self):
        self.assertEqual(self.check({self.URL: 404})[0]["status"], "does not resolve")
        self.assertEqual(self.check({self.URL: 410})[0]["status"], "does not resolve")

    def test_rate_limited_and_refused_are_not_verdicts(self):
        out = self.check({self.URL: 429})[0]
        self.assertEqual((out["status"], out["detail"]), ("could not check", "HTTP 429 (rate limited)"))
        self.assertEqual(self.check({self.URL: 403})[0]["status"], "could not check")
        self.assertEqual(self.check({self.URL: 503})[0]["status"], "could not check")

    def test_network_failures(self):
        cases = {
            urllib.error.URLError(socket.gaierror(-2, "Name or service not known")): ("does not resolve", "host name not found"),
            urllib.error.URLError(ConnectionRefusedError(111, "Connection refused")): ("could not check", "Connection refused"),
            socket.timeout("timed out"): ("could not check", "timed out"),
            TimeoutError(): ("could not check", "timed out"),
            http.client.IncompleteRead(b"partial"): ("could not check", "IncompleteRead"),
            http.client.RemoteDisconnected("closed"): ("could not check", "RemoteDisconnected"),
            http.client.BadStatusLine("garbage"): ("could not check", "BadStatusLine"),
            ssl.SSLError("certificate verify failed"): ("could not check", "SSLError"),
        }
        for exc, (status, detail) in cases.items():
            out = self.check({self.URL: exc})[0]
            self.assertEqual(out["status"], status, exc)
            self.assertIn(detail, out["detail"], exc)

    def test_body_that_fails_while_reading(self):
        class Broken(Response):
            def read(self, n=-1):
                raise http.client.IncompleteRead(b"")
        out = self.check({("HEAD", self.URL): 405, ("GET", self.URL): Broken(200, self.URL)})[0]
        self.assertEqual(out["status"], "could not check")

    def test_redirect_host_is_reported(self):
        out = self.check({("HEAD", self.URL): Response(200, "https://www.example.com/new")})[0]
        self.assertEqual(out["detail"], "HTTP 200, redirected to www.example.com")

    def test_urls_that_are_never_requested(self):
        for url, why in {"https://user:secret@example.org/x": "carries credentials",
                         "http://127.0.0.1:8080/admin": "private or local address",
                         "http://10.1.2.3/": "private or local address",
                         "http://[::1]/": "private or local address",
                         "http://localhost/x": "local host name",
                         "https://intranet/x": "local host name",
                         "https://files.corp/x": "local host name",
                         "ftp://example.org/x": "not an http(s) URL",
                         "https://example.org:99999/": "not a valid URL",
                         "https://exa mple.org/": "contains spaces"}.items():
            out, op = self.check({}, url)
            self.assertEqual(out["status"], "not checked", url)
            self.assertIn(why, out["detail"], url)
            self.assertEqual(op.calls, [], url)
        out, _ = self.check({}, "https://user:secret@example.org/x")
        self.assertNotIn("secret", json.dumps(out))

    def test_query_is_sent_but_not_shown(self):
        url = "https://example.org/data?token=abc123&id=7"
        out, op = self.check({url: 200}, url)
        self.assertEqual(op.calls[0][1], url)
        self.assertEqual(out["target"], "https://example.org/data?***")

    def test_redirect_to_a_private_address_is_refused(self):
        handler = tieout._SafeRedirects()
        req = urllib.request.Request("https://example.org/a")
        with self.assertRaisesRegex(urllib.error.URLError, "private or local address"):
            handler.redirect_request(req, None, 302, "Found", {}, "http://169.254.169.254/latest/meta-data")


class Dois(IsolatedTestCase):
    API = "https://doi.org/api/handles/"

    def body(self, name):
        return (FIXTURES / name).read_bytes()

    def test_registered(self):
        doi = "10.1038/nature14539"
        op = Opener({("GET", self.API + doi): Response(200, self.API + doi, self.body("doi-found.json"))})
        out = tieout.check_link(link(doi, "doi"), 5, op)
        self.assertEqual((out["status"], out["target"]), ("resolves", "doi:10.1038/nature14539"))

    def test_not_registered(self):
        doi = "10.5555/atlas.2025.017"
        op = Opener({("GET", self.API + doi): http_error(self.API + doi, 404, self.body("doi-not-found.json"))})
        out = tieout.check_link(link(doi, "doi"), 5, op)
        self.assertEqual((out["status"], out["detail"]), ("does not resolve", "DOI not registered at doi.org"))

    def test_odd_bodies(self):
        doi = "10.1000/1"
        for body in (b"", b"null", b"\xff\xfe\x00", b"[]", b"<html>"):
            op = Opener({("GET", self.API + doi): Response(200, self.API + doi, body)})
            self.assertEqual(tieout.check_link(link(doi, "doi"), 5, op)["status"], "could not check", body)
        op = Opener({("GET", self.API + doi): http_error(self.API + doi, 500, b'{"responseCode":2}')})
        self.assertEqual(tieout.check_link(link(doi, "doi"), 5, op)["status"], "could not check")

    def test_only_well_formed_dois_are_sent(self):
        op = Opener({})
        for doi in ("10.1000/a b", "10.12/abc", "10.1000/x?y=1", "10.1000/<script>"):
            self.assertEqual(tieout.check_link(link(doi, "doi"), 5, op)["status"], "not checked", doi)
        self.assertEqual(op.calls, [])


class Collect(IsolatedTestCase):
    def test_urls_dois_and_hyperlinks_in_document_order(self):
        body = (para("See https://example.org/a.pdf, and www.example.com/b.")
                + '<w:p><w:hyperlink r:id="rIdL"><w:r><w:t>the study</w:t></w:r></w:hyperlink></w:p>'
                + para("Smith (2024), doi:10.1016/j.x.2024.01.004. Also https://doi.org/10.1038/nature14539 and"
                       " https://example.org/a.pdf again."))
        path = docx(self.path("l.docx"), body, doc_rels=[("rIdL", "hyperlink", "https://example.net/s?id=3", "External")])
        found = tieout.collect_links(tieout.read_deliverable(path))
        self.assertEqual([(l["kind"], l["target"], l["where"]) for l in found], [
            ("url", "https://example.org/a.pdf", "paragraph 1"),
            ("url", "https://www.example.com/b", "paragraph 1"),
            ("url", "https://example.net/s?id=3", "paragraph 2"),
            ("doi", "10.1016/j.x.2024.01.004", "paragraph 3"),
            ("doi", "10.1038/nature14539", "paragraph 3"),
        ])


class StrictExitCodes(IsolatedTestCase):
    def report(self, statuses):
        return {"errors": [], "sources": [{"name": "m.xlsx"}], "summary": {"untied": 0},
                "links": [{"status": s} for s in statuses]}

    def test_codes(self):
        self.assertEqual(tieout.exit_code(self.report(["resolves"]), True), 0)
        self.assertEqual(tieout.exit_code(self.report(["resolves", "does not resolve"]), True), 1)
        self.assertEqual(tieout.exit_code(self.report(["could not check"]), True), 2)
        self.assertEqual(tieout.exit_code(self.report(["could not check", "does not resolve"]), True), 1)
        self.assertEqual(tieout.exit_code(self.report(["not checked"]), True), 0)
        self.assertEqual(tieout.exit_code(self.report(["does not resolve"]), False), 0)

    def test_cli_is_offline_without_the_flag(self):
        path = self.text_file("r.md", "Revenue 12.5%, see https://example.org/x\n")
        with mock.patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("network")):
            code, out, _ = run_cli([path])
        self.assertEqual(code, 0)
        self.assertNotIn("links", out)


if __name__ == "__main__":
    unittest.main()
