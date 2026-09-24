"""Recorded fixtures, a network stand-in and a local HTTP server for the tests. No real network."""
from __future__ import annotations

import gzip
import http.server
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pkg_vitals  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
BASES = {  # public endpoint -> path prefix on the local server
    "https://registry.npmjs.org": "/npm",
    "https://api.npmjs.org/downloads/point": "/downloads",
    "https://pypi.org": "/pypi",
    "https://api.github.com": "/github",
}


# Variables that would change what a test sees if the developer running it happens to set them.
AMBIENT = {"GITHUB_TOKEN", "GH_TOKEN", "PIP_INDEX_URL", "PIP_NO_INDEX", "UV_INDEX_URL", "UV_DEFAULT_INDEX", "UV_INDEX",
           "npm_config_registry", "NPM_CONFIG_REGISTRY", "YARN_REGISTRY", "YARN_NPM_REGISTRY_SERVER", "BUN_CONFIG_REGISTRY"}


class Case(unittest.TestCase):
    """Every test runs with $HOME and Path.home() on an empty scratch directory, and without ambient tokens or
    registry settings, so nothing under the real home directory is ever read."""

    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        env = mock.patch.dict(os.environ, {"HOME": str(self.home), "USERPROFILE": str(self.home)})
        env.start()
        self.addCleanup(env.stop)
        for k in list(os.environ):
            if k in AMBIENT or k.startswith("PKG_VITALS_"):
                del os.environ[k]
        home = mock.patch("pathlib.Path.home", return_value=self.home)
        home.start()
        self.addCleanup(home.stop)
        (self.home / "tmp").mkdir()
        tmp_dir = mock.patch.object(tempfile, "tempdir", str(self.home / "tmp"))  # the hook's claim files land here
        tmp_dir.start()
        self.addCleanup(tmp_dir.stop)


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


CORGI = " [abbreviated]"  # key suffix for an answer to npm's abbreviated-metadata Accept header


def recorded(github: str = "sandbox") -> dict:
    """{url: (status, body)} for every fixture.

    github="sandbox" answers every GitHub API call as the recording sandbox did
    (403); github="live" serves the recorded repository objects instead, with
    the old left-pad URL answering like the new one, as GitHub redirects a
    transferred repository."""
    out = {}
    for f in sorted(FIXTURES.glob("*.json")):
        d = load(f.name)
        if "url" not in d or "status" not in d:  # a reference answer, not an HTTP exchange
            continue
        corgi = "install-v1" in (d.get("request_headers") or {}).get("Accept", "")
        if f.name.startswith("github-") and (github == "sandbox") != (f.name == "github-403-sandbox.json"):
            continue
        out[d["url"] + (CORGI if corgi else "")] = (d["status"], d["body"])
    if github == "live":
        out["https://api.github.com/repos/stevemao/left-pad"] = out["https://api.github.com/repos/left-pad/left-pad"]
    return out


class FakeNet(pkg_vitals.Net):
    """Answers from recorded fixtures by URL. Anything not recorded is a network failure, and is noted."""

    def __init__(self, extra: dict | None = None, github: str = "sandbox", census_body: dict | None = None, **kw):
        super().__init__(env={}, **kw)
        self.answers = recorded(github)
        self.answers.update(extra or {})
        self.requested: list[str] = []
        self.missing: list[str] = []
        if census_body is not None:
            self.answers[self.census_url] = (200, census_body)

    def get(self, url, headers=None):
        if "install-v1" in (headers or {}).get("Accept", ""):
            # a registry that ignores the Accept header answers with the full document, so fall back to that
            url = url + CORGI if url + CORGI in self.answers else url
        self.requested.append(url)
        if url not in self.answers:
            self.missing.append(url)
            return {"_error": "not recorded"}
        status, body = self.answers[url]
        if status != 200:
            return {"_error": status}
        return body if isinstance(body, dict) else {"_error": "malformed"}


def target(eco: str, token: str, cwd: str | None = None, scope: str = "project", index: str | None = None) -> dict:
    found = pkg_vitals._Found(cwd, {})
    found.add(eco, token, eco, scope, at_syntax=(eco == "pypi"), index=index)
    assert found.targets, found.skipped
    return found.targets[0]


class Server:
    """A local HTTP server. routes: path -> (status, body bytes or JSON-able, options).

    options: {"gzip": True} compresses the body, {"delay": s} waits before answering,
    {"drop": True} closes the connection without an answer."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.hits: list[str] = []
        self.headers: list[dict] = []
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                server.hits.append(self.path)
                server.headers.append(dict(self.headers))
                # an exact path, else the longest route ending in `*` that prefixes it
                prefixes = sorted((k for k in server.routes if k.endswith("*") and self.path.startswith(k[:-1])), key=len)
                default = server.routes[prefixes[-1]] if prefixes else (404, {"error": "Not found"}, {})
                status, body, opts = server.routes.get(self.path, default)
                if opts.get("delay"):
                    time.sleep(opts["delay"])
                if opts.get("drop"):
                    self.close_connection = True
                    return
                if "raw" in opts:  # bytes on the wire as they are, however broken
                    self.wfile.write(opts["raw"])
                    self.close_connection = True
                    return
                raw = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                if opts.get("location"):
                    self.send_header("Location", opts["location"])
                if opts.get("gzip"):
                    raw = gzip.compress(raw)
                if opts.get("gzip") or opts.get("claims_gzip"):
                    self.send_header("Content-Encoding", "gzip")
                self.send_header("Content-Length", str(opts.get("length", len(raw))))
                self.end_headers()
                try:
                    self.wfile.write(raw)
                except OSError:  # the client gave up first
                    pass

            def log_message(self, *args):
                pass

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.httpd.block_on_close = False  # a deliberately slow handler must not hold up the next test
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def __enter__(self):
        # a short poll interval: shutdown() waits up to one interval, once per test
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()

    def env(self) -> dict:
        """PKG_VITALS_* variables pointing every endpoint at this server, and no proxy for it."""
        return {"PKG_VITALS_NPM_REGISTRY": self.base + "/npm", "PKG_VITALS_NPM_DOWNLOADS": self.base + "/downloads",
                "PKG_VITALS_PYPI": self.base + "/pypi", "PKG_VITALS_GITHUB_API": self.base + "/github",
                "PKG_VITALS_CENSUS": self.base + "/census", "NO_PROXY": "127.0.0.1,localhost",
                "no_proxy": "127.0.0.1,localhost"}


def fixture_routes(github: str = "sandbox") -> dict:
    """Every recorded fixture as a route on the local server. In "sandbox" mode every GitHub API path answers
    what the recording sandbox answered for all of them: 403."""
    routes = {}
    if github == "sandbox":
        routes["/github/*"] = (403, load("github-403-sandbox.json")["body"], {})
    for url, (status, body) in recorded(github).items():
        for public, prefix in BASES.items():
            if url.startswith(public):
                routes[prefix + url[len(public):]] = (status, body if not isinstance(body, str) else body.encode(), {})
    return routes


def clean_env(extra: dict) -> dict:
    """The environment for a subprocess: no tokens, no proxy for the local server, a scratch HOME and TMPDIR."""
    env = {k: v for k, v in os.environ.items() if k not in AMBIENT and not k.startswith("PKG_VITALS_")}
    env.update(extra)
    if "HOME" in extra and "TMPDIR" not in extra:
        env["TMPDIR"] = str(Path(extra["HOME"]) / "tmp")
        Path(env["TMPDIR"]).mkdir(exist_ok=True)
    return env
