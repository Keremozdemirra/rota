"""The only code that talks to the network: CELLAR, the Publications Office's
repository behind EUR-Lex. Used by `refresh`, never by a lookup.

Requests go to one host over HTTPS. CELEX numbers are checked against their
grammar before they become part of a URL or a query; a redirect to any other
host is refused, and CELLAR's redirects to plain http are upgraded to https.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

from . import __version__

HOST = "publications.europa.eu"
SPARQL = f"https://{HOST}/webapi/rdf/sparql"
USER_AGENT = f"eudr-scope-mcp/{__version__} (+https://github.com/Keremozdemirra/eudr-scope-mcp)"
TIMEOUT = 60
RETRIES = 2
RETRY_DELAY = 3.0  # seconds, doubled per attempt; tests set it to 0
MAX_BYTES = 20 * 1024 * 1024

# Sector digit, year, type letter(s), number; optionally a consolidation date
# (0...-YYYYMMDD) or a corrigendum suffix R(NN).
CELEX = re.compile(r"^[0-9]{5}[A-Z]{1,2}[0-9]{4}(?:-[0-9]{8}|R\([0-9]{2}\))?$")


class FetchError(RuntimeError):
    """The source could not be read; the message says why."""


def check_celex(celex: str) -> str:
    if not isinstance(celex, str) or not CELEX.match(celex):
        raise FetchError(f"not a CELEX number: {str(celex)[:40]!r}")
    return celex


def resource_url(celex: str) -> str:
    return f"https://{HOST}/resource/celex/{urllib.parse.quote(check_celex(celex), safe='()')}"


class _SameHostHttps(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parts = urllib.parse.urlsplit(newurl)
        if parts.hostname != HOST:
            raise FetchError(f"redirect to another host refused: {parts.hostname}")
        if parts.scheme == "http":
            newurl = urllib.parse.urlunsplit(("https",) + tuple(parts)[1:])
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_SameHostHttps())


def _open(request: urllib.request.Request, timeout: float):
    """(status, headers, body, final_url). Replaced by a fake in the tests."""
    with _opener.open(request, timeout=timeout) as resp:
        body = resp.read(MAX_BYTES + 1)
        return resp.status, dict(resp.headers.items()), body, resp.geturl()


def fetch(url: str, accept: str, data: bytes | None = None, language: str | None = None) -> dict:
    """GET (or POST when data is given) with bounded retries. Returns a record
    with the body, final URL, headers of interest and SHA-256."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or parts.hostname != HOST:
        raise FetchError(f"refusing to fetch {parts.scheme}://{parts.hostname}")
    headers = {"Accept": accept, "User-Agent": USER_AGENT}
    if language:
        headers["Accept-Language"] = language
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    last = None
    for attempt in range(RETRIES + 1):
        if attempt:
            time.sleep(RETRY_DELAY * (2 ** (attempt - 1)))
        request = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
        try:
            status, resp_headers, body, final = _open(request, TIMEOUT)
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code in (429, 500, 502, 503, 504):
                continue
            raise FetchError(f"{last} for {_short(url)}") from None
        except FetchError:
            raise
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError,
                http.client.HTTPException, OSError) as e:
            last = f"{type(e).__name__}: {getattr(e, 'reason', e)}"
            continue
        if status != 200:
            raise FetchError(f"HTTP {status} for {_short(url)}")
        if not body:
            raise FetchError(f"empty response from {_short(url)}")
        if len(body) > MAX_BYTES:
            raise FetchError(f"response larger than {MAX_BYTES} bytes from {_short(url)}")
        lowered = {k.lower(): v for k, v in resp_headers.items()}
        return {"url": url, "final_url": final, "body": body, "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
                "content_type": lowered.get("content-type"), "etag": lowered.get("etag"),
                "last_modified": lowered.get("last-modified")}
    raise FetchError(f"{last} for {_short(url)} after {RETRIES + 1} attempts")


def _short(url: str) -> str:
    return url if len(url) <= 120 else url[:117] + "..."


def text_of(record: dict) -> str:
    try:
        return record["body"].decode("utf-8")
    except UnicodeDecodeError as e:
        raise FetchError(f"response from {_short(record['url'])} is not UTF-8 ({e.reason})") from None


def sparql(query: str) -> list:
    """Rows of a SELECT query as dicts of plain strings."""
    record = fetch(SPARQL, "application/sparql-results+json", data=urllib.parse.urlencode({"query": query}).encode())
    try:
        doc = json.loads(text_of(record))
    except json.JSONDecodeError as e:
        raise FetchError(f"SPARQL response is not JSON ({e.msg})") from None
    if not isinstance(doc, dict) or not isinstance(doc.get("results"), dict) \
            or not isinstance(doc["results"].get("bindings"), list):
        raise FetchError("SPARQL response has no results.bindings list")
    rows = []
    for b in doc["results"]["bindings"]:
        if not isinstance(b, dict):
            raise FetchError("SPARQL binding is not an object")
        row = {}
        for k, v in b.items():
            if not isinstance(v, dict) or not isinstance(v.get("value"), str):
                raise FetchError(f"SPARQL value for {k!r} is malformed")
            row[k] = v["value"]
        rows.append(row)
    return rows


def xhtml(celex: str) -> dict:
    """The English XHTML manifestation of an act or consolidated text."""
    record = fetch(resource_url(celex), "application/xhtml+xml", language="eng")
    ctype = (record.get("content_type") or "").lower()
    if "html" not in ctype:
        raise FetchError(f"{celex}: expected XHTML, got {ctype or 'no content type'}")
    record["celex"] = celex
    return record
