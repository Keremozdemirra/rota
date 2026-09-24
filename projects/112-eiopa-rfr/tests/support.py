"""Shared test scaffolding: an isolated HOME and cache, and a fake EIOPA website.

Every test runs with HOME, the cache directory and pathlib.Path.home pointed
at a temporary directory, so nothing on the machine running the tests is read
or written. The fake website serves the trimmed copies of real EIOPA files in
tests/fixtures (see tests/fixtures/SOURCES.md).
"""
from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import eiopa_rfr as E  # noqa: E402


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def listing_urls() -> dict[str, str]:
    """reference date -> the random-id link the fixture pages give for it."""
    out = {}
    for name, url in (("rfr_page.html", E.RFR_PAGE), ("rfr_previous_releases.html", E.ARCHIVE_PAGE)):
        releases, _ = E.parse_listing_page(fixture(name), url, "test")
        for r in releases:
            out.setdefault(r["reference_date"], r["url"])
    return out


class FakeWeb:
    """Stands in for eiopa_rfr.http_get: URL -> bytes, or an exception to raise."""

    def __init__(self, routes: dict[str, object] | None = None) -> None:
        self.routes = dict(routes or {})
        self.calls: list[str] = []

    def __call__(self, url, what, *, timeout=None, max_bytes=None):
        self.calls.append(url)
        if url not in self.routes:
            raise E.FetchError(f"EIOPA answered HTTP 404 (not found) for {what}", status=404)
        value = self.routes[url]
        if isinstance(value, BaseException):
            raise value
        return value

    def count(self, fragment: str) -> int:
        return sum(1 for u in self.calls if fragment in u)


def standard_web() -> FakeWeb:
    """The RFR page, the previous-releases page and three trimmed releases."""
    urls = listing_urls()
    return FakeWeb({
        E.RFR_PAGE: fixture("rfr_page.html"),
        E.ARCHIVE_PAGE: fixture("rfr_previous_releases.html"),
        E.RSS_FEED: fixture("rss.xml"),
        urls["2026-08-31"]: fixture("EIOPA_RFR_20260831.zip"),
        urls["2026-07-31"]: fixture("EIOPA_RFR_20260731.zip"),
        urls["2022-12-31"]: fixture("december_2022.zip"),
        # 2023-01-31 is listed but not served: a 404 for a listed file
    })


class Isolated(unittest.TestCase):
    """Temporary HOME and cache for every test; network replaced by a FakeWeb."""

    fake_web = True

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.cache = self.tmp / "cache"
        env = {"HOME": str(self.home), "USERPROFILE": str(self.home), "EIOPA_RFR_CACHE": str(self.cache),
               "XDG_CACHE_HOME": str(self.home / ".cache"), "LOCALAPPDATA": str(self.home / "AppData")}
        for p in (mock.patch.dict(os.environ, env),  # restores the whole environment afterwards
                  mock.patch("pathlib.Path.home", return_value=self.home),
                  mock.patch.object(E, "_sleep", self._record_sleep)):
            p.start()
            self.addCleanup(p.stop)
        os.environ.pop("EIOPA_RFR_OFFLINE", None)
        self.sleeps: list[float] = []
        if self.fake_web:
            self.use_web(standard_web())

    def _record_sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)

    def use_web(self, web: FakeWeb) -> FakeWeb:
        p = mock.patch.object(E, "http_get", web)
        p.start()
        self.addCleanup(p.stop)
        self.web = web
        return web

    def go_offline(self) -> None:
        os.environ["EIOPA_RFR_OFFLINE"] = "1"


def rewrite_release(data: bytes, change) -> bytes:
    """Apply change(parts) to the parts of the Term_Structures workbook inside a release zip."""
    outer = zipfile.ZipFile(io.BytesIO(data))
    name = next(n for n in outer.namelist() if n.endswith("_Term_Structures.xlsx"))
    inner = zipfile.ZipFile(io.BytesIO(outer.read(name)))
    parts = {n: inner.read(n) for n in inner.namelist()}
    parts = change(parts) or parts
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n, b in parts.items():
            z.writestr(n, b)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(name, buf.getvalue())
    return out.getvalue()
