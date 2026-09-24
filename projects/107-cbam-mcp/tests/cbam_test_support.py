"""Shared by the tests: a fetcher that answers from the recorded fixtures, and a data directory built from them.

The fixtures are trimmed copies of real answers recorded on 2026-09-24 (see
fixtures/build_fixtures.py). No test touches the network or the real $HOME.
"""
from __future__ import annotations

import os
import sys
import tempfile
import urllib.parse
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cbam_mcp import refresh  # noqa: E402

TODAY = "2026-09-24"
XLSX_HEADERS = {"content-disposition": 'inline; filename="DV correcting act_final update_06.08.xlsx"'}


def fixture(name: str) -> bytes:
    return (FIX / name).read_bytes()


class FakeFetcher:
    """Answers like refresh.fetch, from fixture files; `fail` maps a key to an exception or bytes."""

    def __init__(self, fail: dict | None = None, override: dict | None = None):
        self.fail = fail or {}
        self.override = override or {}
        self.calls: list[tuple[str, str]] = []

    def key(self, url: str, data: bytes | None) -> str:
        if url == refresh.SPARQL_ENDPOINT:
            query = urllib.parse.parse_qs((data or b"").decode()).get("query", [""])[0]
            if "act_consolidated_consolidates" in query:
                return "sparql_consolidated"
            if "GROUP_CONCAT" in query:
                return "sparql_later_acts"
            year = "2026" if "cn2026/cn2026" in query else "2025"
            return f"sparql_cn{year}_parents" if "VALUES ?id" in query else f"sparql_cn{year}"
        if url.endswith("02023R0956-20251020"):
            return "consolidated"
        if url == refresh.EXCEL_URL:
            return "excel"
        if url == refresh.EXCEL_PAGE:
            return "page"
        if url.endswith(refresh.OJ_VALUES_CELEX):
            return "oj"
        return "unknown"

    FILES = {"sparql_consolidated": "sparql_consolidated.json", "sparql_later_acts": "sparql_later_acts.json",
             "sparql_cn2026": "sparql_cn2026_trimmed.json", "sparql_cn2025": "sparql_cn2025_trimmed.json",
             "sparql_cn2026_parents": "sparql_cn2026_parents.json", "sparql_cn2025_parents": "sparql_cn2025_parents.json",
             "consolidated": "consolidated_trimmed.xhtml", "excel": "default_values_trimmed.xlsx",
             "page": "commission_page_trimmed.html", "oj": "oj_1740_trimmed.xhtml"}

    def __call__(self, url, *, accept="*/*", data=None, timeout=60, max_bytes=0, **_):
        key = self.key(url, data)
        self.calls.append((key, url))
        if key in self.fail:
            outcome = self.fail[key]
            if isinstance(outcome, Exception):
                raise outcome
            return refresh.Fetched(outcome, {}, url)
        if key in self.override:
            return refresh.Fetched(self.override[key], XLSX_HEADERS if key == "excel" else {}, url)
        if key == "unknown":
            raise refresh.FetchError(f"{url}: HTTP 404")
        return refresh.Fetched(fixture(self.FILES[key]), XLSX_HEADERS if key == "excel" else {}, url)


def build(directory: Path, fetcher: FakeFetcher | None = None, check_oj: bool = True, **kw) -> int:
    """Run the real refresh against the fixtures. The CN fixtures are trimmed, so the size floor is lowered."""
    with mock.patch.object(refresh, "MIN_CN_CONCEPTS", 50):
        return refresh.run(directory, fetcher=fetcher or FakeFetcher(), check_oj=check_oj, today=TODAY,
                           log=lambda *a: None, **kw)


_shared: Path | None = None


def shared_data_dir() -> Path:
    """One fixture-built data directory for the lookup tests (read-only use)."""
    global _shared
    if _shared is None:
        _shared = Path(tempfile.mkdtemp(prefix="cbam-mcp-test-data-"))
        code = build(_shared)
        if code != 0:
            raise RuntimeError(f"building the fixture data directory returned {code}")
    return _shared


class DataEnv:
    """Point the lookups at the fixture data directory and HOME at a scratch directory."""

    def __init__(self, directory: Path | None = None):
        self.directory = directory or shared_data_dir()
        self.home = tempfile.mkdtemp(prefix="cbam-mcp-test-home-")
        self.patch = mock.patch.dict(os.environ, {"CBAM_MCP_DATA_DIR": str(self.directory), "HOME": self.home})

    def __enter__(self):
        self.patch.start()
        return self.directory

    def __exit__(self, *exc):
        self.patch.stop()
        return False
