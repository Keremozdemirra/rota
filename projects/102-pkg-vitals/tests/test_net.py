"""The HTTP layer against a local server: the failures real registries and networks produce."""
import json
import os
import socket
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import Case, Server, pkg_vitals as pv  # noqa: E402

ROUTES = {
    "/ok": (200, {"a": 1}, {}),
    "/gz": (200, {"a": "gzip"}, {"gzip": True}),
    "/missing": (404, {"error": "Not found"}, {}),
    "/limited": (429, {"message": "slow down"}, {}),
    "/empty": (200, b"", {}),
    "/null": (200, b"null", {}),
    "/list": (200, b"[1, 2]", {}),
    "/latin1": (200, '{"a": "café"}'.encode("latin-1"), {}),
    "/badgzip": (200, b"not gzip at all", {"claims_gzip": True}),
    "/slow": (200, {"a": 1}, {"delay": 1.5}),
    "/dropped": (200, {}, {"drop": True}),
    "/badstatus": (200, {}, {"raw": b"HTTP/1.1 banana\r\n\r\n"}),
    "/short": (200, b'{"a": 1', {"length": 500}),
    "/moved": (301, b"", {"location": "/ok"}),
    "/utf8": (200, {"name": "café ✓"}, {}),
}


class Http(Case):
    def setUp(self):
        super().setUp()
        self.server = Server(dict(ROUTES))
        self.server.__enter__()
        self.addCleanup(self.server.__exit__, None, None, None)
        patch = mock.patch.dict(os.environ, {"NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"})
        patch.start()
        self.addCleanup(patch.stop)

    def net(self, **kw):
        return pv.Net(env={}, **kw)

    def get(self, path, **kw):
        return self.net(**kw).get(self.server.base + path)

    def test_json_and_gzip(self):
        self.assertEqual(self.get("/ok"), {"a": 1})
        self.assertEqual(self.get("/gz"), {"a": "gzip"})
        self.assertEqual(self.server.headers[-1].get("Accept-Encoding"), "gzip")
        self.assertIn("pkg-vitals/", self.server.headers[-1].get("User-Agent"))

    def test_http_errors_carry_the_status(self):
        self.assertEqual(self.get("/missing"), {"_error": 404})
        self.assertEqual(self.get("/limited"), {"_error": 429})

    def test_bodies_that_are_not_a_json_object(self):
        for path in ("/empty", "/null", "/list", "/latin1", "/badgzip"):
            self.assertEqual(self.get(path), {"_error": "malformed"}, path)

    def test_broken_answers(self):
        for path in ("/dropped", "/badstatus", "/short"):
            self.assertIn("_error", self.get(path), path)

    def test_timeout_marks_the_host_down(self):
        net = self.net(timeout=0.3)
        start = time.monotonic()
        self.assertEqual(net.get(self.server.base + "/slow"), {"_error": "timeout"})
        self.assertEqual(net.get(self.server.base + "/ok"), {"_error": "unreachable"})
        self.assertLess(time.monotonic() - start, 1.4)

    def test_refused_connection(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        self.assertIn("_error", self.net(timeout=2).get(f"http://127.0.0.1:{port}/x"))

    def test_redirect_is_followed(self):
        self.assertEqual(self.get("/moved"), {"a": 1})

    def test_unicode(self):
        self.assertEqual(self.get("/utf8"), {"name": "café ✓"})

    def test_answers_are_cached(self):
        net = self.net()
        net.get(self.server.base + "/ok")
        net.get(self.server.base + "/ok")
        self.assertEqual(self.server.hits.count("/ok"), 1)

    def test_time_budget(self):
        net = self.net(budget=0.6)
        time.sleep(0.2)
        self.assertEqual(net.get(self.server.base + "/ok"), {"_error": "out of time"})
        self.assertEqual(self.server.hits, [])

    def test_census_from_a_file_url(self):
        f = self.home / "servers.json"
        f.write_text(json.dumps({"generated_at": "2026-09-23T09:49:03+00:00",
                                 "repositories": [{"full_name": "o/n", "pushed_at": "2026-09-01", "archived": False}]}))
        net = pv.Net(env={"PKG_VITALS_CENSUS": f.as_uri(), "PKG_VITALS_GITHUB_API": self.server.base + "/missing"})
        net.github_down = True
        self.assertEqual(net.github("o/n")["source"], "agent-vitals census 2026-09-23")
        self.assertEqual(net.github("x/y"), {"error": "GitHub API unavailable and not in the census"})

    def test_github_token_goes_only_to_the_github_api(self):
        net = pv.Net(env={"PKG_VITALS_GITHUB_API": self.server.base + "/gh"}, token="test-token")
        net.github("o/n")
        net.get(self.server.base + "/ok")
        self.assertEqual(self.server.headers[0].get("Authorization"), "Bearer test-token")
        self.assertIsNone(self.server.headers[1].get("Authorization"))

    def test_github_lookup_needs_a_valid_slug(self):
        net = pv.Net(env={"PKG_VITALS_GITHUB_API": self.server.base + "/gh"})
        for slug in ("../../x", "o/n/extra", "-o/n", "o/..", "o n/x"):
            self.assertEqual(net.github(slug), {"error": "not an owner/name"}, slug)
        self.assertEqual(self.server.hits, [])


if __name__ == "__main__":
    unittest.main()
