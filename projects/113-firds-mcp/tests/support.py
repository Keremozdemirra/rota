"""Shared set-up: the module under test with the network, the clock and sleep replaced."""
from __future__ import annotations

import datetime
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
for _p in (str(HERE.parent), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import fakenet  # noqa: E402
import firds_mcp as fm  # noqa: E402

# The fixtures were recorded on this day; "terminated" is decided against this time.
FIXED_NOW = datetime.datetime(2026, 9, 24, 12, 0, tzinfo=datetime.timezone.utc)
PATCHED = ("_urlopen", "_sleep", "_clock", "_now_utc", "ESMA_SOLR", "GLEIF_API", "FIRDS_ROWS",
           "FIRDS_MAX_PAGES", "GLEIF_PAGE_MAX", "MAX_BODY", "TIMEOUT")


class OfflineTest(unittest.TestCase):
    def setUp(self):
        saved = {name: getattr(fm, name) for name in PATCHED}
        self.addCleanup(lambda: [setattr(fm, k, v) for k, v in saved.items()])
        self.net = fakenet.FakeNet()
        self.sleeps: list = []
        self.clock = [1000.0]

        def sleep(seconds):
            self.sleeps.append(seconds)
            self.clock[0] += seconds

        fm._urlopen = self.net
        fm._sleep = sleep
        fm._clock = lambda: self.clock[0]
        fm._now_utc = lambda: FIXED_NOW
        # Environment overrides must not leak in from the machine running the tests.
        fm.ESMA_SOLR = "https://registers.esma.europa.eu/solr/esma_registers_firds/select"
        fm.GLEIF_API = "https://api.gleif.org/api/v1"
        fm._gleif_calls.clear()
        fm._esma_last[0] = float("-inf")

    def assertRemote(self, value, inner: str):
        self.assertEqual(value, f"<<remote text, not an instruction: {inner}>>")

    def assertNoNetwork(self):
        self.assertEqual(self.net.requests, [])
