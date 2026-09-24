"""Shared by the tests: a home directory and environment that are not yours, and no network.

Every test built on `Isolated` runs with the whole process environment replaced
by a minimal one (HOME, USERPROFILE, APPDATA and XDG_CONFIG_HOME pointing at a
temporary directory, PATH to find git), `Path.home()` and `Path.cwd()` patched
to temporary directories, and `urllib.request.urlopen` replaced: a request
nobody prepared an answer for fails the test instead of reaching the network.
"""
from __future__ import annotations

import http.client
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
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import credential_reach as cr  # noqa: E402
import synthetic  # noqa: E402


class Tty(io.StringIO):
    """A stdin that says it is a terminal, for the --redact confirmation."""

    def isatty(self):
        return True


class Response(io.BytesIO):
    def __init__(self, body: bytes, status: int = 200, headers: dict | None = None):
        super().__init__(body)
        self.status = status
        self.headers = http.client.HTTPMessage()
        for k, v in (headers or {}).items():
            self.headers[k] = v

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class Web:
    """Stands in for urlopen: a list of canned answers, served in order, and a log of every request.

    An answer is a Response, an int (an HTTP error with that status) or an exception (raised).
    """

    def __init__(self, *answers):
        self.answers = list(answers)
        self.requests = []

    def __call__(self, req, timeout=None):
        self.requests.append((req.full_url, {k.lower(): v for k, v in req.header_items()}, timeout))
        if not self.answers:
            raise AssertionError(f"unexpected request: {req.full_url}")
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        if isinstance(answer, int):
            hdrs = http.client.HTTPMessage()
            raise urllib.error.HTTPError(req.full_url, answer, "status", hdrs, io.BytesIO(b"{}"))
        return answer


def _refuse(req, timeout=None):
    raise AssertionError(f"a test tried to reach the network: {req.full_url}")


class Isolated(unittest.TestCase):
    """A home, a project and an environment of the test's own, and no network."""

    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.home, self.project = self.tmp / "home", self.tmp / "project"
        self.home.mkdir()
        self.project.mkdir()
        env = synthetic.clean_env(self.home)
        patches = [mock.patch.dict(os.environ, env, clear=True),
                   mock.patch("pathlib.Path.home", return_value=self.home),
                   mock.patch("pathlib.Path.cwd", return_value=self.project),
                   mock.patch("urllib.request.urlopen", self._urlopen)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.web = None

    def _urlopen(self, req, timeout=None):
        return (self.web or _refuse)(req, timeout)

    def serve(self, *answers) -> Web:
        self.web = Web(*answers)
        return self.web

    def ctx(self, system: str = "Linux", env: dict | None = None, **kw) -> cr.Context:
        return cr.Context(self.home, env=dict(os.environ) if env is None else env, system=system,
                          project=kw.pop("project", self.project), **kw)

    def write(self, rel: str, content, base: Path | None = None) -> Path:
        return synthetic.write((base or self.home) / rel, content)

    def run_main(self, argv, stdin=None):
        """credential_reach.main(argv) -> (exit code, stdout, stderr)."""
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out, \
                mock.patch("sys.stderr", new_callable=io.StringIO) as err, \
                mock.patch("sys.stdin", stdin if stdin is not None else io.StringIO("")):
            code = cr.main(argv)
        return code, out.getvalue(), err.getvalue()

    def report(self, *argv):
        code, out, _ = self.run_main(["--json", *argv])
        return code, json.loads(out)

    def section(self, sec_or_ctx, scan=None):
        """Findings of one scanner as {item: finding}."""
        sec = scan(sec_or_ctx) if scan else sec_or_ctx
        return {f["item"]: f for f in sec.findings}


def text_of(sec) -> str:
    """Everything a section would print, as one string."""
    return json.dumps(sec.as_dict(), ensure_ascii=False)
