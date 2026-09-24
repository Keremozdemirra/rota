"""Recorded answers instead of the network, for in-process tests and for a local HTTP server.

Every request is routed to a fixture by the same rule the recorder used (see fixtures/README.md).
A request with no fixture and no scripted answer fails the test: nothing falls through to a
silent 404, so a test notices when the tool asks for something it should not.
"""
from __future__ import annotations

import email.message
import gzip
import http.server
import io
import json
import threading
import urllib.error
import urllib.parse
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def route(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qs(parts.query)
    if parts.path.endswith("/esma_registers_firds/select"):
        isin = query["q"][0].split(":", 1)[1]
        start, rows = query["start"][0], query["rows"][0]
        suffix = "" if (start == "0" and rows == "500") else f"_rows{rows}_start{start}"
        return f"firds/{isin}{suffix}"
    path = parts.path.split("/api/v1/", 1)[1]
    if not path.startswith("lei-records/"):
        raise AssertionError(f"unexpected GLEIF path {path}")
    rest = path[len("lei-records/"):].replace("/", "_")
    if "page[number]" in query:
        rest += f"_size{query['page[size]'][0]}_p{query['page[number]'][0]}"
    return f"gleif/{rest}"


def load(name: str):
    """(status, body bytes, content type) of a recorded answer."""
    for suffix, status, ctype in ((".json", 200, "application/json"), (".404.json", 404, "application/json"),
                                  (".404.html", 404, "text/html"), (".400.json", 400, "application/json")):
        p = FIXTURES / f"{name}{suffix}"
        if p.exists():
            return status, p.read_bytes(), ctype
    raise AssertionError(f"no fixture for {name}")


def fixture_json(name: str) -> dict:
    return json.loads(load(name)[1])


def _headers(ctype: str, extra: dict | None = None) -> email.message.Message:
    h = email.message.Message()
    h["Content-Type"] = ctype
    for k, v in (extra or {}).items():
        h[k] = v
    return h


class Response(io.BytesIO):
    def __init__(self, status: int, body: bytes, headers: email.message.Message):
        super().__init__(body)
        self.status = status
        self.headers = headers

    def getcode(self):
        return self.status


class FakeNet:
    """Stands in for urllib.request.urlopen."""

    def __init__(self):
        self.requests: list = []
        self.user_agents: list = []
        self._scripted: dict = {}

    def script(self, name: str, *answers):
        """Answers for a route, used in order before the fixture: an exception to raise, or
        (status, body bytes or dict, headers dict)."""
        self._scripted.setdefault(name, []).extend(answers)

    def routes(self) -> list:
        return [route(u) for u in self.requests]

    def __call__(self, req, timeout=None):
        url = req.full_url
        self.requests.append(url)
        self.user_agents.append(req.get_header("User-agent"))
        name = route(url)
        queue = self._scripted.get(name)
        if queue:
            answer = queue.pop(0)
            if isinstance(answer, BaseException):
                raise answer
            status, body, extra = answer
            if isinstance(body, (dict, list)) or body is None:
                body = json.dumps(body).encode()
            headers = _headers("application/json", extra)
        else:
            status, body, ctype = load(name)
            headers = _headers(ctype)
        if status != 200:
            raise urllib.error.HTTPError(url, status, "recorded", headers, io.BytesIO(body))
        return Response(status, body, headers)


def gzipped(name: str) -> tuple:
    return 200, gzip.compress(load(name)[1]), {"Content-Encoding": "gzip"}


class FixtureServer:
    """The same recorded answers over real HTTP on 127.0.0.1, for the stdio end-to-end test."""

    def __init__(self):
        self.requests: list = []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 (http.server's naming)
                outer.requests.append(self.path)
                try:
                    status, body, ctype = load(route(f"http://127.0.0.1{self.path}"))
                except AssertionError:
                    status, body, ctype = 500, b"no fixture", "text/plain"
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()
