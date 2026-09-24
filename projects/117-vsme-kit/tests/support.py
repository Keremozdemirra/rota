"""Shared by the tests: a home directory and working directory of their own, no network, synthetic workbooks."""
import io
import os
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

import xlsxgen  # noqa: E402
from vsme_kit import cli  # noqa: E402


def _refuse(*args, **kwargs):
    raise AssertionError("a test tried to reach the network")


class Isolated(unittest.TestCase):
    """HOME, USERPROFILE and the working directory point at a temporary directory; the network is refused."""

    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        home = self.tmp / "home"
        home.mkdir()
        for p in (mock.patch.dict(os.environ, {"HOME": str(home), "USERPROFILE": str(home)}),
                  mock.patch("pathlib.Path.home", return_value=home),
                  mock.patch("urllib.request.urlopen", _refuse),
                  mock.patch("vsme_kit.refresh._open", _refuse)):
            p.start()
            self.addCleanup(p.stop)

    def book(self, name="t.xlsx", **kwargs) -> Path:
        return xlsxgen.complete(**kwargs).save(self.tmp / name)

    def write(self, name, data: bytes) -> Path:
        p = self.tmp / name
        p.write_bytes(data)
        return p

    def run_cli(self, argv):
        """cli.main(argv) -> (exit code, stdout, stderr)."""
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out, \
                mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            code = cli.main([str(a) for a in argv])
        return code, out.getvalue(), err.getvalue()
