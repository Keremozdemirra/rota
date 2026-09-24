"""Shared test helpers. No test touches the network or the real $HOME.

Fixtures (tests/fixtures), trimmed from the real files retrieved 2026-09-24:
- desnz_flat_2026_trimmed.xlsx / desnz_flat_2025_trimmed.xlsx: the DESNZ flat
  files (SHA-256 a9a455ab... and 8bfdb45b...) cut down to 51 rows each; the
  XML of the kept parts, the front page and the kept rows is unchanged.
- desnz_content_api_2026.json / _2025.json: GOV.UK Content API answers, with
  only the fields refresh reads.
- ember_trimmed.csv: every row of a few areas and years from Ember's yearly
  CSV (SHA-256 ea214963...), verbatim, including Lesotho 2023-2024 whose
  intensity is blank.
- uba_page_skeleton.html: written for the tests, see the comment inside.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
FIXTURES = HERE / "fixtures"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ghg_factors_mcp import factors as F  # noqa: E402
from ghg_factors_mcp import provenance as P  # noqa: E402
from ghg_factors_mcp import refresh as R  # noqa: E402

TODAY = "2026-09-24"


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def flat_url(year: int) -> str:
    doc = json.loads(fixture(f"desnz_content_api_{year}.json"))
    return next(a["url"] for a in doc["details"]["attachments"] if "flat file" in a["title"].lower())


def recorded_answers() -> dict:
    return {
        P.DESNZ_API.format(year=2026): fixture("desnz_content_api_2026.json"),
        flat_url(2026): fixture("desnz_flat_2026_trimmed.xlsx"),
        P.DESNZ_API.format(year=2025): fixture("desnz_content_api_2025.json"),
        flat_url(2025): fixture("desnz_flat_2025_trimmed.xlsx"),
        P.EMBER_CSV: (fixture("ember_trimmed.csv"), {"last-modified": "Tue, 22 Sep 2026 16:24:55 GMT"}),
        P.UBA_PAGE: fixture("uba_page_skeleton.html"),
    }


class FakeFetch:
    """Stands in for refresh.fetch: answers from a dict of URL -> bytes, (bytes, headers) or exception."""

    def __init__(self, answers: dict):
        self.answers = answers
        self.calls: list[str] = []

    def __call__(self, url: str, max_bytes: int):
        self.calls.append(url)
        answer = self.answers.get(url, R.RefreshError(f"HTTP 404 from {url}"))
        if isinstance(answer, Exception):
            raise answer
        body, headers = answer if isinstance(answer, tuple) else (answer, {})
        if len(body) > max_bytes:
            raise R.RefreshError("too large")
        return body, headers


def build_snapshot(directory: Path, answers: dict | None = None) -> dict:
    return R.refresh(directory, get=FakeFetch(answers or recorded_answers()), today=TODAY)


class IsolatedTestCase(unittest.TestCase):
    """HOME points at a scratch directory for every test."""

    def setUp(self):
        self._home = tempfile.TemporaryDirectory()
        patcher = mock.patch.dict(os.environ, {"HOME": self._home.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._home.cleanup)


class SnapshotTestCase(IsolatedTestCase):
    """Queries against a snapshot built offline from the recorded fixtures."""

    @classmethod
    def setUpClass(cls):
        cls._dir = tempfile.TemporaryDirectory()
        cls.data = Path(cls._dir.name) / "data"
        cls.report = build_snapshot(cls.data)
        cls._env = mock.patch.dict(os.environ, {"GHG_FACTORS_DATA": str(cls.data)})
        cls._env.start()
        F._cache.clear()

    @classmethod
    def tearDownClass(cls):
        cls._env.stop()
        F._cache.clear()
        cls._dir.cleanup()
