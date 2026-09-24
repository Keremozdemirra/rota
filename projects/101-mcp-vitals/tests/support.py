"""Shared by the tests: a stand-in for the network, recorded fixtures, and a home directory that is not yours.

Every test built on `Isolated` runs with HOME, USERPROFILE, APPDATA and
XDG_CONFIG_HOME pointing at a temporary directory, `Path.home()` and
`Path.cwd()` patched to temporary directories, no GitHub token in the
environment, and `urllib.request.urlopen` replaced: a request nobody
prepared an answer for fails the test instead of reaching the network.
"""
import datetime as dt
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
FIXTURES = HERE / "fixtures"
TODAY = dt.date(2026, 9, 24)
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import mcp_vitals  # noqa: E402


def fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class Web:
    """Stands in for urlopen: canned answers keyed by URL, and a log of every request made.

    An answer is a dict (served as JSON), bytes (served as is), an int (an HTTP
    error with that status) or an exception (raised). A URL with no answer is a 404.
    """

    def __init__(self, answers=None):
        self.answers = dict(answers or {})
        self.requests = []

    def __call__(self, req, timeout=None):
        url = req.full_url
        self.requests.append((url, {k.lower(): v for k, v in req.header_items()}))
        answer = self.answers.get(url, 404)
        if isinstance(answer, BaseException):
            raise answer
        if isinstance(answer, int):
            raise urllib.error.HTTPError(url, answer, "status", {}, None)
        if isinstance(answer, bytes):
            return Response(answer)
        return Response(json.dumps(answer).encode("utf-8"))

    @property
    def urls(self):
        return [u for u, _ in self.requests]


class FakeNet(mcp_vitals.Net):
    """A Net that answers from a dict keyed by URL, through the real Net.get."""

    def __init__(self, answers, census=True):
        super().__init__(False, None, census=census)
        self.web = Web(answers)

    def get(self, url, headers=None):
        with mock.patch("urllib.request.urlopen", self.web):
            return super().get(url, headers)


def _refuse(req, timeout=None):
    raise AssertionError(f"a test tried to reach the network: {req.full_url}")


class Isolated(unittest.TestCase):
    """A home, a working directory and an app-data folder of the test's own, and no network."""

    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.home, self.cwd = self.tmp / "home", self.tmp / "cwd"
        self.home.mkdir()
        self.cwd.mkdir()
        env = {"HOME": str(self.home), "USERPROFILE": str(self.home), "APPDATA": str(self.home / "AppData"),
               "XDG_CONFIG_HOME": str(self.home / ".config")}
        patches = [mock.patch.dict(os.environ, env),
                   mock.patch("pathlib.Path.home", return_value=self.home),
                   mock.patch("pathlib.Path.cwd", return_value=self.cwd),
                   mock.patch("urllib.request.urlopen", self._urlopen),
                   # a fixed day, so ages computed from recorded dates do not change as time passes
                   mock.patch("mcp_vitals._today", return_value=TODAY, create=True)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        for var in ("GITHUB_TOKEN", "GH_TOKEN", "MCP_VITALS_HOOK_TIMEOUT"):
            os.environ.pop(var, None)  # restored with the rest of the environment by patch.dict
        self.web = None

    def _urlopen(self, req, timeout=None):
        return (self.web or _refuse)(req, timeout)

    def serve(self, answers=None) -> Web:
        """Answer requests from now on from `answers`, and record them."""
        self.web = Web(answers)
        return self.web

    def run_main(self, argv):
        """mcp_vitals.main(argv) -> (exit code, stdout, stderr)."""
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out, \
                mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            code = mcp_vitals.main(argv)
        return code, out.getvalue(), err.getvalue()

    def run_hook(self, payload):
        """The hook's main() on a payload -> its parsed JSON answer, or None when it stays silent."""
        import mcp_vitals_hook
        with mock.patch("sys.stdin", io.StringIO(json.dumps(payload))), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            self.assertEqual(mcp_vitals_hook.main(), 0)
        text = out.getvalue().strip()
        return json.loads(text) if text else None

    def write_config(self, data, name="c.json") -> Path:
        p = self.tmp / name
        p.write_text(json.dumps(data), encoding="utf-8")
        return p


def bash(command: str, tool: str = "Bash") -> dict:
    return {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": {"command": command}}


def entry(command="", args=(), url="", name="s"):
    return {"client": "test", "config": "x", "name": name, "command": command, "args": list(args), "url": url}
