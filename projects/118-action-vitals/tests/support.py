"""Shared by the tests: a stand-in for git ls-remote, a local stand-in for GitHub, and a home that is not yours.

Every test built on `Isolated` runs with HOME, USERPROFILE and TMPDIR pointing at
a temporary directory, `Path.home()` and `Path.cwd()` patched, no GitHub token in
the environment, `subprocess.run` replaced by `FakeGit`, and name resolution
refused for any host but 127.0.0.1: a request to the real network fails the test.
"""
from __future__ import annotations

import datetime as dt
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
FIXTURES = HERE / "fixtures"
CENSUS = str(FIXTURES / "census.json")
TODAY = dt.date(2026, 9, 24)
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import action_vitals as av  # noqa: E402

# Recorded with git ls-remote on 2026-09-24 (see the first lines of each file).
LS = {f"https://github.com/{name.replace('-', '/', 1)}": (FIXTURES / "ls-remote" / f"{name}.txt").read_text(encoding="utf-8")
      for name in ("actions-checkout", "actions-setup-python")}
LS["https://github.com/pypa/gh-action-pypi-publish"] = \
    (FIXTURES / "ls-remote" / "pypa-gh-action-pypi-publish.txt").read_text(encoding="utf-8")
CHECKOUT_V6 = "d23441a48e516b6c34aea4fa41551a30e30af803"  # v6 and v6.1.0 in the recording
SETUP_PY_V5 = "a26af69be951a213d495a4c3e4e4022e16d87065"  # v5 and v5.6.0
PYPA_V1_14_2 = "dc37677b2e1c63e2034f94d8a5b11f265b73ba33"  # the commit behind the annotated tag v1.14.2
SHA_A = "a" * 40
SHA_B = "b" * 40


def ls_lines(tags=None, heads=None) -> str:
    """ls-remote output for a made-up repository."""
    out = [f"{sha}\trefs/heads/{h}" for h, sha in (heads or {}).items()]
    out += [f"{sha}\trefs/tags/{t}" for t, sha in (tags or {}).items()]
    return "\n".join(out) + "\n"


def action_yml(name: str) -> str:
    return (FIXTURES / "actions" / name).read_text(encoding="utf-8")


def github(name: str) -> dict:
    return json.loads((FIXTURES / "github" / name).read_text(encoding="utf-8"))


def repo_doc(full_name: str, pushed="2026-09-20T10:00:00Z", archived=False, spdx="MIT") -> dict:
    """A 200 answer for GET /repos/{full_name}, built on GitHub's documented example."""
    doc = github("hello-world.200.json")
    body = dict(doc["body"], full_name=full_name, name=full_name.split("/")[1], pushed_at=pushed, archived=archived,
                license=None if spdx is None else {"key": spdx.lower(), "spdx_id": spdx})
    return dict(doc, body=body)


class FakeGit:
    """Stands in for subprocess.run when the command is `git ls-remote`. Answers by URL:
    a str is the output, an int an exit code (128 = git's 'could not read Username'), an exception is raised.
    A URL with no answer is a repository git cannot see."""

    def __init__(self, answers=None):
        self.answers = dict(answers or {})
        self.calls = []

    def __call__(self, cmd, **kw):
        self.calls.append((list(cmd), kw))
        url = cmd[-1]
        answer = self.answers.get(url, 128)
        if isinstance(answer, BaseException):
            raise answer
        if isinstance(answer, int):
            err = b"fatal: could not read Username for 'https://github.com': terminal prompts disabled\n" \
                if answer == 128 else b"fatal: unable to access: Could not resolve host: github.com\n"
            return subprocess.CompletedProcess(cmd, answer, b"", err)
        if isinstance(answer, tuple):  # (exit code, stderr)
            return subprocess.CompletedProcess(cmd, answer[0], b"", answer[1])
        return subprocess.CompletedProcess(cmd, 0, answer.encode("utf-8"), b"")

    @property
    def urls(self):
        return [c[-1] for c, _ in self.calls]


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        pass  # a client that timed out and left is what the timeout tests are for


class FakeGitHub:
    """A local HTTP stand-in for api.github.com and raw.githubusercontent.com (under /raw).

    `routes` maps a path to a fixture file name (tests/fixtures/github), a dict
    {"status", "headers", "body"} (body: dict or str), {"raw": bytes as they go on the wire},
    or a list of those answered in turn (the last one repeats). Unknown paths get the sandbox's 403
    for the API and 404 for raw files."""

    def __init__(self, routes=None, delay=0.0):
        self.routes = {k.lower(): v for k, v in (routes or {}).items()}
        self.delay, self.requests = delay, []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                outer.requests.append((self.path, {k.lower(): v for k, v in self.headers.items()}))
                if outer.delay:
                    time.sleep(outer.delay)
                default = {"status": 404, "headers": {}, "body": "404: Not Found"} if self.path.startswith("/raw/") \
                    else "sandbox.403.json"
                fx = outer.routes.get(self.path.lower(), default)
                if isinstance(fx, list):
                    fx = fx.pop(0) if len(fx) > 1 else fx[0]
                fx = github(fx) if isinstance(fx, str) else fx
                if "raw" in fx:
                    self.wfile.write(fx["raw"])
                    return
                body = fx["body"]
                data = body if isinstance(body, bytes) else (body.encode("utf-8") if isinstance(body, str)
                                                            else json.dumps(body).encode("utf-8"))
                self.send_response(fx["status"])
                for k, v in fx.get("headers", {}).items():
                    self.send_header(k, v.replace("https://api.github.com", outer.url) if k.lower() == "location" else v)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.server = _Server(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()

    def paths(self):
        return [p for p, _ in self.requests]


def raw(owner_repo: str, sha: str, name: str = "action.yml", path: str = "") -> str:
    return f"/raw/{owner_repo}/{sha}/{path + '/' if path else ''}{name}"


def text_file(text: str) -> dict:
    return {"status": 200, "headers": {"Content-Type": "text/plain; charset=utf-8"}, "body": text}


_real_getaddrinfo = socket.getaddrinfo


def _local_only(host, *args, **kwargs):
    if host not in ("127.0.0.1", "localhost"):
        raise AssertionError(f"a test tried to reach the network: {host}")
    return _real_getaddrinfo(host, *args, **kwargs)


class Isolated(unittest.TestCase):
    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.home, self.cwd, self.tmpdir = self.tmp / "home", self.tmp / "cwd", self.tmp / "t"
        for d in (self.home, self.cwd, self.tmpdir):
            d.mkdir()
        env = {"HOME": str(self.home), "USERPROFILE": str(self.home), "TMPDIR": str(self.tmpdir)}
        self.git = FakeGit()
        patches = [mock.patch.dict(os.environ, env),
                   mock.patch("pathlib.Path.home", return_value=self.home),
                   mock.patch("pathlib.Path.cwd", return_value=self.cwd),
                   mock.patch("tempfile.tempdir", str(self.tmpdir)),
                   mock.patch("socket.getaddrinfo", _local_only),
                   mock.patch("action_vitals.subprocess.run", self.git),
                   mock.patch("action_vitals._today", return_value=TODAY)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        for var in ("GITHUB_TOKEN", "GH_TOKEN", "ACTION_VITALS_OFFLINE", "ACTION_VITALS_NO_RUNTIME"):
            os.environ.pop(var, None)  # restored with the rest of the environment by patch.dict

    def answer_git(self, answers: dict) -> FakeGit:
        self.git.answers.update(answers)
        return self.git

    def repo(self, files: dict, origin: str | None = None) -> Path:
        """A repository under the test's cwd: {relative path: text}."""
        root = self.cwd / "repo"
        for rel, text in files.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(text.encode("utf-8") if isinstance(text, str) else text)
        (root / ".github").mkdir(parents=True, exist_ok=True)
        if origin:
            (root / ".git").mkdir(exist_ok=True)
            (root / ".git" / "config").write_text(f'[core]\n\tbare = false\n[remote "origin"]\n\turl = {origin}\n'
                                                  f'\tfetch = +refs/heads/*:refs/remotes/origin/*\n', encoding="utf-8")
        return root

    def net(self, server=None, **kw) -> "av.Net":
        base = server.url if server else "http://127.0.0.1:9"
        kw.setdefault("census", CENSUS)
        return av.Net(api=base, raw=base + "/raw", proxies={}, timeout=kw.pop("timeout", 5), **kw)

    def run_main(self, argv, net=None):
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out, \
                mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            code = av.main([str(a) for a in argv], net=net)
        return code, out.getvalue(), err.getvalue()


def workflow(*steps: str, extra: str = "") -> str:
    """A workflow whose one job runs these `uses:` values, one step each."""
    body = "".join(f"      - uses: {s}\n" for s in steps)
    return f"name: ci\non: [push]\njobs:\n  test:\n    runs-on: ubuntu-24.04\n    steps:\n{body}{extra}"


def cleanup_home(path):
    shutil.rmtree(path, ignore_errors=True)
