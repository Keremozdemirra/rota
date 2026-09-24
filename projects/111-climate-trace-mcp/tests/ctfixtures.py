"""A local HTTP server that replays recorded Climate TRACE API answers.

Tests run the real client code (urllib, status codes, headers, timeouts,
broken connections) against 127.0.0.1, never against the network.

Fixtures in tests/fixtures, recorded 2026-09-24 from https://api.climatetrace.org/v7:
- sources_*.json: GET /v7/sources, first 2-5 rows kept.
- source_*.json: GET /v7/sources/{id}, complete answers (1566771 has owners;
  10936838 is a cropland-fires record, whose data lead the API names as EDGAR,
  with "owners": null).
- emissions_POL_power_{year}.json: GET /v7/sources/emissions?gadmId=POL&sectors=power;
  the monthly series of the sector and subsector blocks are dropped, the totals'
  series is kept. 2014 is the API's answer for a year before its data starts;
  2026 is the partial current year.
- emissions_POL_ignored-sector_2024.json: the answer to sectors=nonsense, which
  the API ignored (it returned the whole country); subsector block dropped.
- emissions_POL_all_2024.json: the whole country, all sectors.
- problem_404.json, problem_400_gas.json: the API's RFC 7807 error bodies.
- null.json: the API's answer when no rows match (a bare `null`).
- definitions_*.json: GET /v7/definitions/...; openapi_head.yaml: the info block
  of GET /v7/docs/openapi.json (YAML).
Synthetic, built in the tests and marked there: HTTP 429 and 5xx answers (never
provoked against the real API), malformed, empty and non-UTF-8 bodies, NaN,
dropped connections, an owner carrying an LEI.
"""
from __future__ import annotations

import http.server
import json
import os
import socket
import tempfile
import threading
import time
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def load_json(name: str):
    return json.loads(load_bytes(name).decode("utf-8"))


class Reply:
    def __init__(self, body=b"", status=200, headers=None, delay=0.0, drop=False, short=False):
        self.body = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self.status = status
        ctype = "application/problem+json; charset=utf-8" if status >= 400 else "application/json; charset=utf-8"
        self.headers = {"Content-Type": ctype}
        self.headers.update(headers or {})
        self.delay = delay
        self.drop = drop  # close the connection without answering
        self.short = short  # promise more bytes than are sent


def fixture(name: str, status: int = 200, **kw) -> Reply:
    return Reply(load_bytes(name), status, **kw)


class _QuietServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False  # a handler still sleeping for a timeout test must not hold up the next test

    def handle_error(self, request, client_address):
        pass  # the client hanging up early (timeouts, dropped connections) is the point of those tests


class FixtureServer:
    """Routes are keyed by path plus the exact query (as a dict of strings), or by path alone."""

    def __init__(self):
        self.routes = {}
        self.requests = []
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                parts = urllib.parse.urlsplit(self.path)
                query = dict(urllib.parse.parse_qsl(parts.query, keep_blank_values=True))
                server.requests.append({"path": parts.path, "query": query, "headers": dict(self.headers)})
                reply = server.routes.get((parts.path, frozenset(query.items()))) or server.routes.get((parts.path, None))
                if reply is None:
                    reply = Reply({"detail": "no fixture for %s?%s" % (parts.path, parts.query), "status": 599}, 599)
                if reply.delay:
                    time.sleep(reply.delay)
                if reply.drop:
                    self.close_connection = True
                    return
                self.send_response(reply.status)
                for k, v in reply.headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(reply.body) + (100 if reply.short else 0)))
                self.end_headers()
                self.wfile.write(reply.body)
                if reply.short:
                    self.close_connection = True

            def log_message(self, *args):
                pass

        self.httpd = _QuietServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()

    @property
    def base(self) -> str:
        return "http://127.0.0.1:%d/v7" % self.httpd.server_address[1]

    def route(self, path: str, reply: Reply, query=None) -> None:
        key = None if query is None else frozenset((k, str(v)) for k, v in query.items())
        self.routes[("/v7" + path, key)] = reply

    def paths(self) -> list:
        return [r["path"] for r in self.requests]


def closed_port_base() -> str:
    """A loopback URL where nothing listens: the network is down."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return "http://127.0.0.1:%d/v7" % port


def standard_routes(srv: FixtureServer) -> None:
    """The recorded answers under the queries that produced them."""
    srv.route("/sources", fixture("sources_DEU_iron-and-steel_2024.json"),
              {"year": 2024, "gas": "co2e_100yr", "gadmId": "DEU", "subsectors": "iron-and-steel", "limit": 5})
    srv.route("/sources/1566771", fixture("source_1566771_2022-2024.json"),
              {"start": 2022, "end": 2024, "timeGranularity": "year", "gas": "co2e_100yr"})
    srv.route("/sources/10936838", fixture("source_10936838_2023-2024.json"),
              {"start": 2023, "end": 2024, "timeGranularity": "year", "gas": "co2e_100yr"})
    srv.route("/sources/999999999", fixture("problem_404.json", 404))
    for y in range(2020, 2025):
        srv.route("/sources/emissions", fixture("emissions_POL_power_%d.json" % y),
                  {"year": y, "gas": "co2e_100yr", "gadmId": "POL", "sectors": "power"})
    srv.route("/definitions/sectors", fixture("definitions_sectors.json"))
    srv.route("/definitions/subsectors", fixture("definitions_subsectors.json"))
    srv.route("/docs/openapi.json", fixture("openapi_head.yaml"))


class HomeIsolated(unittest.TestCase):
    """Nothing in this package reads $HOME; every test still runs with HOME in a scratch directory."""

    def setUp(self):
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        patcher = mock.patch.dict(os.environ, {"HOME": home.name, "USERPROFILE": home.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.home = home.name
