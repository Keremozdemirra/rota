"""Shared by the tests: synthetic fixtures, a home and cache that are not yours, and no network.

Every test built on `Isolated` runs with HOME, USERPROFILE, LOCALAPPDATA and
XDG_CACHE_HOME pointing at a temporary directory, `Path.home()` patched to it,
ESRS_DATAPOINTS_XLSX unset, ESRS_DATAPOINTS_CACHE set to a temporary cache, and
socket connections refused: this tool must never touch the network.
"""
import os
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
FIXTURES = HERE / "fixtures"
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

IG3 = FIXTURES / "ig3_style.xlsx"
CLEAN = FIXTURES / "revised_style_clean.xlsx"
MAPPING = FIXTURES / "revised_style_mapping.xlsx"
VARIANTS = FIXTURES / "header_variants.xlsx"


def _no_network(*args, **kwargs):
    raise AssertionError("this tool must not open network connections")


class Isolated(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.cache = self.tmp / "cache"
        env = {"HOME": str(self.home), "USERPROFILE": str(self.home), "LOCALAPPDATA": str(self.home / "local"),
               "XDG_CACHE_HOME": str(self.home / ".cache"), "ESRS_DATAPOINTS_CACHE": str(self.cache)}
        patches = [mock.patch.dict(os.environ, env), mock.patch("pathlib.Path.home", return_value=self.home),
                   mock.patch.object(socket.socket, "connect", _no_network),
                   mock.patch.object(socket, "create_connection", _no_network)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        os.environ.pop("ESRS_DATAPOINTS_XLSX", None)
        self.addCleanup(self._tmp.cleanup)

    def service(self, *paths, env=None):
        from esrs_datapoints_mcp.store import Store
        from esrs_datapoints_mcp.tools import Service
        store = Store(self.cache)
        for p in paths:
            store.add(p)
        return Service(store, env_value=env if env is not None else "")
