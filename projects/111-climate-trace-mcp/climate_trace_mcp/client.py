"""GET requests to the Climate TRACE API (v7), with short timeouts and a small cache.

Every way a request can fail ends as an ApiError subclass carrying a short,
printable message, so the tools answer "the API rate-limited us, retry in 30 s"
instead of raising a traceback. The API is in beta and asks users to "keep
volume low" (https://climatetrace.org/data, checked 2026-09-24): hence the
cache, sequential requests and no automatic retries.
"""
from __future__ import annotations

import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from . import __version__
from .safety import clean, mask_url, remote_text

DEFAULT_BASE = "https://api.climatetrace.org/v7"
USER_AGENT = "climate-trace-mcp/%s (+https://github.com/Keremozdemirra/climate-trace-mcp)" % __version__
# Tool's choice. The slowest answer seen from here on 2026-09-24 was 8.7 s (a cold
# CDN cache); most took 0.2-1.5 s. Someone is waiting on the other side.
DEFAULT_TIMEOUT = 15.0
# Tool's choice. Climate TRACE publishes monthly data releases; within one
# process an answer an hour old is still current. 256 answers bound the memory.
CACHE_TTL = 3600.0
CACHE_MAX = 256
# Tool's choice. The largest answer this tool asks for is about 60 kB.
MAX_BODY = 5 * 1024 * 1024
_PATH = re.compile(r"^/[A-Za-z0-9/_.-]{1,200}$")


class ApiError(Exception):
    kind = "api_error"

    def __init__(self, message, endpoint=None, status=None, retry_after=None):
        super().__init__(message)
        self.message = message
        self.endpoint = endpoint
        self.status = status
        self.retry_after = retry_after

    def as_dict(self) -> dict:
        out = {"kind": self.kind, "message": self.message}
        if self.endpoint:
            out["endpoint"] = self.endpoint
        if self.status is not None:
            out["http_status"] = self.status
        if self.retry_after:
            out["retry_after"] = self.retry_after
        return out


class NotFound(ApiError):
    kind = "not_found"


class BadRequest(ApiError):
    kind = "bad_request"


class RateLimited(ApiError):
    kind = "rate_limited"


class ServerError(ApiError):
    kind = "server_error"


class NetworkError(ApiError):
    kind = "network_error"


class Timeout(ApiError):
    kind = "timeout"


class BadPayload(ApiError):
    kind = "bad_payload"


def _utc_today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _is_loopback(host) -> bool:
    if not host:
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def validated_base(value: str) -> str:
    """The API base URL: https anywhere, plain http only on this machine (tests)."""
    try:
        parts = urllib.parse.urlsplit(value.strip())
        host = parts.hostname
        _ = parts.port  # raises ValueError on a malformed port
    except ValueError:
        raise ValueError("CLIMATE_TRACE_API_BASE is not a valid URL: %s" % mask_url(value))
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("CLIMATE_TRACE_API_BASE must not contain credentials, a query or a fragment: %s" % mask_url(value))
    if not (parts.scheme == "https" and host) and not (parts.scheme == "http" and _is_loopback(host)):
        raise ValueError("CLIMATE_TRACE_API_BASE must be an https:// URL (http:// only for localhost): %s" % mask_url(value))
    return value.strip().rstrip("/")


def _timeout_from_env() -> float:
    try:
        t = float(os.environ.get("CLIMATE_TRACE_TIMEOUT", ""))
    except ValueError:
        return DEFAULT_TIMEOUT
    return t if 1.0 <= t <= 60.0 else DEFAULT_TIMEOUT


def _reject_constant(name):
    # json accepts NaN and Infinity, but they are not JSON and would break every
    # client downstream.
    raise ValueError("non-standard JSON constant %s" % name)


def _problem_detail(body: bytes) -> str:
    """The `detail` of an RFC 7807 problem body, which is what this API sends on errors."""
    try:
        data = json.loads(body.decode("utf-8", "replace"))
    except ValueError:
        return ""
    if isinstance(data, dict):
        for key in ("detail", "title", "message", "error"):
            if isinstance(data.get(key), str) and data[key].strip():
                return data[key]
    return ""


class Client:
    def __init__(self, base=None, timeout=None, today=None, clock=None):
        self.base = validated_base(base or os.environ.get("CLIMATE_TRACE_API_BASE") or DEFAULT_BASE)
        self.base_path = urllib.parse.urlsplit(self.base).path.rstrip("/")
        self.timeout = float(timeout) if timeout else _timeout_from_env()
        self._today = today or _utc_today
        self._clock = clock or time.monotonic
        self._cache = {}
        self.requests_made = 0
        host = urllib.parse.urlsplit(self.base).hostname
        # A loopback base (the test server) must never go through a proxy.
        handlers = [urllib.request.ProxyHandler({})] if _is_loopback(host) else []
        self._opener = urllib.request.build_opener(*handlers)

    # ------------------------------------------------------------------ public
    def get(self, path: str, params=None):
        """(parsed JSON, retrieval date). JSON `null`, which this API sends for "no rows", is None."""
        text, retrieved = self._fetch(path, params)
        try:
            return json.loads(text, parse_constant=_reject_constant), retrieved
        except ValueError:
            raise BadPayload("The API answer is not valid JSON: %s" % remote_text(text[:80], 80), self._label(path))

    def get_text(self, path: str, params=None):
        """(body text, retrieval date), for the OpenAPI document, which is YAML."""
        return self._fetch(path, params)

    # ----------------------------------------------------------------- private
    def _label(self, path: str) -> str:
        return self.base_path + path

    def _fetch(self, path: str, params):
        if not _PATH.match(path) or ".." in path:
            raise ValueError("refusing to request an unexpected path")
        pairs = [(k, str(v)) for k, v in (params or {}).items() if v is not None]
        query = urllib.parse.urlencode(pairs)
        url = self.base + path + ("?" + query if query else "")
        endpoint = self._label(path)
        now = self._clock()
        hit = self._cache.get(url)
        if hit and hit[0] > now:
            return hit[2], hit[1]
        text = self._request(url, endpoint)
        retrieved = self._today()
        if len(self._cache) >= CACHE_MAX:
            oldest = min(self._cache, key=lambda k: self._cache[k][0])
            del self._cache[oldest]
        self._cache[url] = (now + CACHE_TTL, retrieved, text)
        return text, retrieved

    def _request(self, url: str, endpoint: str) -> str:
        self.requests_made += 1
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                raw = resp.read(MAX_BODY + 1)
                # read(n) returns a short body without complaint when the server
                # closes early; `length` is what Content-Length promised and is missing.
                missing = getattr(resp, "length", None)
        except urllib.error.HTTPError as e:
            raise self._http_error(e, endpoint)
        except urllib.error.URLError as e:
            reason = e.reason
            if isinstance(reason, (socket.timeout, TimeoutError)):
                raise Timeout("The Climate TRACE API did not answer within %g s" % self.timeout, endpoint)
            if isinstance(reason, ssl.SSLError):
                raise NetworkError("TLS error talking to the Climate TRACE API: %s" % clean(reason, 120), endpoint)
            raise NetworkError("Could not reach the Climate TRACE API: %s" % clean(reason, 120), endpoint)
        except (socket.timeout, TimeoutError):
            raise Timeout("The Climate TRACE API did not answer within %g s" % self.timeout, endpoint)
        except http.client.HTTPException as e:
            # IncompleteRead, BadStatusLine, RemoteDisconnected: the connection broke mid-answer.
            raise NetworkError("The connection to the Climate TRACE API broke (%s)" % type(e).__name__, endpoint)
        except OSError as e:
            raise NetworkError("Could not reach the Climate TRACE API: %s" % clean(e, 120), endpoint)
        if len(raw) > MAX_BODY:
            raise BadPayload("The API answer is larger than %d MB; not reading it" % (MAX_BODY // 1048576), endpoint)
        if isinstance(missing, int) and missing > 0:
            raise NetworkError("The connection to the Climate TRACE API broke (IncompleteRead)", endpoint)
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise BadPayload("The API answer is not valid UTF-8", endpoint)
        if not text.strip():
            raise BadPayload("The API answered with an empty body", endpoint)
        return text

    def _http_error(self, e: urllib.error.HTTPError, endpoint: str) -> ApiError:
        status = e.code
        try:
            body = e.read(20000) or b""
        except Exception:  # the error body is a courtesy; its absence changes nothing
            body = b""
        detail = _problem_detail(body)
        said = (": " + remote_text(detail, 160)) if detail else ""
        retry = clean(e.headers.get("Retry-After"), 40) if e.headers else ""
        if status == 404:
            return NotFound("Not found (HTTP 404)" + said, endpoint, status)
        if status == 429:
            wait = (" Retry after %s s." % retry) if retry.isdigit() else (" Retry after %s." % retry if retry else "")
            return RateLimited("The Climate TRACE API is limiting requests (HTTP 429)." + wait +
                               " It asks users to keep volume low.", endpoint, status, retry or None)
        if status == 400:
            return BadRequest("The API rejected the request (HTTP 400)" + said, endpoint, status)
        if status >= 500:
            return ServerError("The Climate TRACE API failed (HTTP %d)%s" % (status, said), endpoint, status, retry or None)
        return ApiError("The Climate TRACE API answered HTTP %d%s" % (status, said), endpoint, status)
