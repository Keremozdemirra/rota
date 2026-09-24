"""Shared by the tests: throwaway git repositories, a home that is not yours, and a temp dir we can watch.

Every test built on `Isolated` runs with HOME, XDG_CONFIG_HOME and git's global config pointing into a
temporary directory (so no real ~/.gitconfig or credential is read), with the system git config ignored,
with a fixed commit identity, without an active virtualenv, and with `tempfile.tempdir` set to a directory
of its own, so a test can check that diff-mutants removed its temporary copy.
"""
import hashlib
import io
import os
import subprocess
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

import diff_mutants  # noqa: E402

PY = sys.executable
# The inner test command: the interpreter running this suite, stdlib unittest, quiet.
UNITTEST = f'"{PY}" -m unittest -q'


def snapshot(root: Path) -> dict:
    """Every file, link and directory under root (.git included) with its content hash and mode."""
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            p = Path(dirpath) / name
            rel = p.relative_to(root).as_posix()
            st = p.lstat()
            if p.is_symlink():
                out[rel] = ("link", os.readlink(p))
            elif p.is_dir():
                out[rel] = ("dir", st.st_mode)
            else:
                out[rel] = ("file", st.st_mode, hashlib.sha256(p.read_bytes()).hexdigest())
    return out


class Isolated(unittest.TestCase):
    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.home = self.tmp / "home"
        self.scratch = self.tmp / "scratch"   # where diff-mutants puts its copies during the test
        for d in (self.home, self.scratch):
            d.mkdir()
        gitconfig = self.tmp / "gitconfig"
        gitconfig.write_text("", encoding="utf-8")
        env = {"HOME": str(self.home), "USERPROFILE": str(self.home), "XDG_CONFIG_HOME": str(self.home / ".config"),
               "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": str(gitconfig),
               "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
               "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.invalid",
               "TMPDIR": str(self.scratch)}
        patches = [mock.patch.dict(os.environ, env), mock.patch("pathlib.Path.home", return_value=self.home),
                   mock.patch.object(tempfile, "tempdir", str(self.scratch))]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        for var in ("VIRTUAL_ENV", "CONDA_PREFIX", "PYTHONPATH", "PYTEST_ADDOPTS"):
            os.environ.pop(var, None)  # restored with the rest of the environment by patch.dict

    # -- repositories ----------------------------------------------------------

    def git(self, repo: Path, *args: str) -> str:
        p = subprocess.run(["git", "-C", str(repo), *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if p.returncode != 0:
            raise AssertionError(f"git {' '.join(args)} failed: {p.stderr.decode(errors='replace')}")
        return p.stdout.decode("utf-8", "surrogateescape")

    def repo(self, files: dict, name: str = "project") -> Path:
        """A repository with one commit holding `files` (path -> text or bytes)."""
        root = self.tmp / name
        root.mkdir()
        self.git(root, "init", "-q", "-b", "main")
        self.commit(root, files, "base")
        return root

    def write(self, root: Path, files: dict) -> None:
        for rel, content in files.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                p.write_bytes(content)
            else:
                p.write_bytes(content.encode("utf-8"))

    def commit(self, root: Path, files: dict, message: str = "change") -> None:
        self.write(root, files)
        self.git(root, "add", "-A")
        self.git(root, "commit", "-q", "-m", message)

    # -- running ----------------------------------------------------------------

    def run_main(self, argv):
        """diff_mutants.main(argv) -> (exit code, stdout, stderr)."""
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out, \
                mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            code = diff_mutants.main([str(a) for a in argv])
        return code, out.getvalue(), err.getvalue()

    def run_json(self, repo: Path, *args):
        import json
        code, out, err = self.run_main(["-C", repo, "--json", *args])
        return code, json.loads(out), err

    def leftovers(self) -> list:
        return sorted(p.name for p in self.scratch.iterdir())


# A small project: `clamp` arrives with one test that asserts and one that does not.
CALC_BASE = {
    "calc.py": "def add(a, b):\n    return a + b\n",
    "test_calc.py": "import unittest\n\nfrom calc import add\n\n\nclass T(unittest.TestCase):\n"
                    "    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n",
}
CALC_CHANGE = {
    "calc.py": "def add(a, b):\n    return a + b\n\n\ndef clamp(x, low=0, high=10):\n    if x < low:\n"
               "        return low\n    if x > high:\n        return high\n    return x\n",
    "test_calc.py": "import unittest\n\nfrom calc import add, clamp\n\n\nclass T(unittest.TestCase):\n"
                    "    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n\n"
                    "    def test_clamp_runs(self):\n        clamp(5)\n\n"
                    "    def test_clamp_low(self):\n        self.assertEqual(clamp(-3), 0)\n",
}
# Tests that kill every mutant of clamp except the equivalent `<` -> `<=` and `>` -> `>=`.
CALC_THOROUGH_TESTS = {
    "test_calc.py": "import unittest\n\nfrom calc import add, clamp\n\n\nclass T(unittest.TestCase):\n"
                    "    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n\n"
                    "    def test_clamp(self):\n        self.assertEqual(clamp(-3), 0)\n"
                    "        self.assertEqual(clamp(30), 10)\n        self.assertEqual(clamp(4), 4)\n"
                    "        self.assertEqual(clamp(10), 10)\n        self.assertEqual(clamp(0), 0)\n"
                    "        self.assertEqual(clamp(11), 10)\n        self.assertEqual(clamp(-1), 0)\n",
}
