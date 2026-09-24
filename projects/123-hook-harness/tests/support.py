"""Shared helpers: an isolated HOME for every test, temporary plugins and hook scripts, the CLI in-process."""
from __future__ import annotations

import contextlib
import io
import json
import os
import shlex
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import hook_harness as hh  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PY = shlex.quote(sys.executable)


class Isolated(unittest.TestCase):
    """HOME, USERPROFILE and Path.home() point at an empty scratch directory, so nothing under the real home is read."""

    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.home = self.tmp / "home"
        self.home.mkdir()
        env = mock.patch.dict(os.environ, {"HOME": str(self.home), "USERPROFILE": str(self.home)})
        env.start()
        self.addCleanup(env.stop)
        home = mock.patch("pathlib.Path.home", return_value=self.home)
        home.start()
        self.addCleanup(home.stop)

    def plugin(self, hooks: dict, scripts: dict | None = None, name: str = "plugin") -> Path:
        """A plugin directory with hooks/hooks.json and the given scripts; returns the hooks.json path."""
        root = self.tmp / name
        (root / "hooks").mkdir(parents=True, exist_ok=True)
        for rel, text in (scripts or {}).items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        target = root / "hooks" / "hooks.json"
        target.write_text(json.dumps(hooks, indent=1), encoding="utf-8")
        return target

    def cases(self, cases, **top) -> Path:
        path = self.tmp / "cases.json"
        path.write_text(json.dumps(dict(top, cases=cases), indent=1), encoding="utf-8")
        return path

    def main(self, *argv) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = hh.main([str(a) for a in argv])
            except SystemExit as e:  # argparse
                code = e.code
        return code, out.getvalue(), err.getvalue()


def script(body: str) -> str:
    """A Python hook script: reads the payload into `payload`, then runs BODY."""
    return "import json, os, sys, time\npayload = json.load(sys.stdin)\n" + body + "\n"


def one_handler(event: str, matcher: str | None, handler: dict) -> dict:
    group = {"hooks": [handler]}
    if matcher is not None:
        group["matcher"] = matcher
    return {"hooks": {event: [group]}}


def py_handler(rel: str, **extra) -> dict:
    return dict({"type": "command", "command": f'{PY} "${{CLAUDE_PLUGIN_ROOT}}/{rel}"'}, **extra)


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))
