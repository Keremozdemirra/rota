"""Shared test helpers: an isolated environment and a loopback server that plays the registry.

The fixtures in tests/fixtures were cut from the Union Registry files of 2026-09-24
(operators_daily.csv.gz SHA-256 9b0da34a..., operators_yearly_activity_daily.csv.gz 76ed621b...,
compliance_2024_code_en.xlsx a8b2191b...): fifteen installations, their yearly rows and their
compliance rows. Account holder names, account labels, addresses and registration numbers were
replaced by placeholders (Mustermann, Musterstraße, HRB 00000) before anything was saved, one
shipping company was renamed to a placeholder person, and some rows were broken on purpose: a
short row, a non-numeric id, a registry name instead of a code, a duplicate, a Latin-1 byte, control
and bidi characters in a name, a year "20x5", "n/a" as a number, an orphan yearly row, a blank and a
broken compliance row. listing.json is the registry's listing as fetched on 2026-09-24.
"""
import gzip
import json
import os
import sys
import tempfile
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(ROOT))
import eu_ets  # noqa: E402

PLACEHOLDERS = ("Mustermann", "Musterstra", "Musterweg", "Musterstadt", "Musterhausen", "HRB 00000")
FILES = {
    "operators_daily.csv.gz": FIXTURES / "operators_daily.csv.gz",
    "operators_yearly_activity_daily.csv.gz": FIXTURES / "operators_yearly_activity_daily.csv.gz",
    "compliance_2024_code_en.xlsx": FIXTURES / "compliance_2024_code_en.xlsx",
}


def no_sleep(_seconds):
    return None


class Isolated:
    """HOME, the cache and the snapshot directory point into a fresh temporary directory; the real
    home directory is never read or written."""

    def __enter__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name)
        (self.path / "home").mkdir()
        self.cache = self.path / "cache"
        env = {"HOME": str(self.path / "home"), "USERPROFILE": str(self.path / "home"),
               "XDG_CACHE_HOME": str(self.path / "xdg"), "EU_ETS_CACHE_DIR": str(self.cache),
               "EU_ETS_SNAPSHOT_DIR": str(self.path / "no-snapshot"),
               "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"}
        self._env = mock.patch.dict(os.environ, env)
        self._env.start()
        self._home = mock.patch("pathlib.Path.home", return_value=self.path / "home")
        self._home.start()
        return self

    def __exit__(self, *exc):
        self._home.stop()
        self._env.stop()
        self._tmp.cleanup()


def build_fixture_db(cache: Path) -> Path:
    """The cache as a refresh from the fixtures would build it, without a server."""
    op, yr, cp = eu_ets.Stats(eu_ets.OPERATORS_FILE), eu_ets.Stats(eu_ets.YEARLY_FILE), eu_ets.Stats("compliance")
    comp = list(eu_ets.read_compliance_xlsx(FILES["compliance_2024_code_en.xlsx"], 2024, cp))
    sources = [{"kind": k, "file": n, "url": f"https://example.invalid/{n}", "bytes": FILES[n].stat().st_size,
                "sha256": eu_ets.sha256_file(FILES[n])} for k, n in (("operators", "operators_daily.csv.gz"),
                ("yearly", "operators_yearly_activity_daily.csv.gz"), ("compliance", "compliance_2024_code_en.xlsx"))]
    db = cache / eu_ets.DB_NAME
    eu_ets.build_database(
        db, eu_ets.read_operators(FILES["operators_daily.csv.gz"], op),
        lambda known: eu_ets.read_yearly(FILES["operators_yearly_activity_daily.csv.gz"], yr, known), comp,
        {"origin": "live", "listing_url": eu_ets.LISTING_URL, "retrieved_at": "2026-09-24T09:24:57Z"},
        lambda meta: dict(meta, snapshot_date=eu_ets._snapshot_date(op), sources=sources, errors=[]))
    return db


class Registry:
    """A loopback HTTP server serving the fixture listing and files, with faults on demand.

    faults maps a file name ("listing" for the listing) to a list of actions used one per request,
    the last one repeating: ("ok",), ("status", code, headers), ("sleep", seconds), ("body", bytes),
    ("cut", n) (announce the full length, send n bytes, close), ("norange",) (ignore Range),
    ("serve", bytes) (serve other bytes with a correct length).
    """

    def __init__(self):
        self.faults = {}
        self.requests = []
        self.files = dict(FILES)
        registry = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):  # noqa: N802
                registry.requests.append((self.path, dict(self.headers)))
                name = "listing" if self.path.startswith("/api/data-download") else eu_ets.file_name(self.path)
                actions = registry.faults.get(name) or [("ok",)]
                seen = sum(1 for p, _ in registry.requests if p == self.path) - 1
                action = actions[min(seen, len(actions) - 1)]
                kind = action[0]
                if kind == "sleep":
                    time.sleep(action[1])
                if kind == "status":
                    self.send_response(action[1])
                    for k, v in (action[2] if len(action) > 2 else {}).items():
                        self.send_header(k, v)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if name == "listing":
                    body = action[1] if kind == "body" else registry.listing_bytes()
                    self._send(200, body, {"Content-Type": "application/json"})
                    return
                if name not in registry.files:
                    self._send(404, b"not found", {})
                    return
                data = action[1] if kind == "serve" else registry.files[name].read_bytes()
                status, body, headers = 200, data, {"ETag": '"v1"'}
                rng = self.headers.get("Range")
                if rng and kind != "norange" and self.headers.get("If-Range", '"v1"') == '"v1"':
                    start = int(rng.split("=")[1].split("-")[0])
                    status, body = 206, data[start:]
                    headers["Content-Range"] = f"bytes {start}-{len(data) - 1}/{len(data)}"
                if kind == "cut":
                    self.send_response(status)
                    for k, v in headers.items():
                        self.send_header(k, v)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body[:action[1]])
                    self.wfile.flush()
                    self.close_connection = True
                    return
                self._send(status, body, headers)

            def _send(self, code, body, headers):
                self.send_response(code)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        class Server(ThreadingHTTPServer):
            daemon_threads = True

            def handle_error(self, request, client_address):
                pass  # a client that timed out and hung up is part of the test

        self.server = Server(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"
        self.listing_url = f"{self.base}/api/data-download"
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)

    def listing_bytes(self) -> bytes:
        entries = json.loads((FIXTURES / "listing.json").read_text(encoding="utf-8"))
        for e in entries:
            parts = urllib.parse.urlsplit(e["url"])
            e["url"] = urllib.parse.urlunsplit(("http", f"127.0.0.1:{self.port}", parts.path, parts.query, ""))
        return json.dumps(entries).encode()

    def paths(self, name: str) -> list:
        return [(p, h) for p, h in self.requests if eu_ets.file_name(p) == name]

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


def gz(text: str) -> bytes:
    return gzip.compress(text.encode("utf-8"), mtime=0)


def fixture_rows(name: str) -> list:
    """Fixture CSV rows as dicts, read without eu_ets, for independent expectations."""
    import csv
    import io
    text = gzip.decompress(FILES[name].read_bytes()).decode("utf-8", "replace")
    rows = list(csv.reader(io.StringIO(text)))
    return [dict(zip(rows[0], r)) for r in rows[1:] if len(r) == len(rows[0])]
