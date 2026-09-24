"""Shared by the tests: a home directory that is not yours, fake infrastructure tools, and hook/CLI runners.

Every test built on `Isolated` runs with HOME, USERPROFILE and XDG_CONFIG_HOME
pointing at a temporary directory, `Path.home()` patched, the variables that
change what destroy-guard targets removed from the environment, and
`urllib.request.urlopen` replaced so that any attempt to reach the network
fails the test (destroy-guard itself sends nothing).

`fake_tool` writes an executable Python script named like the real tool into
a bin directory on PATH. It answers from a list of rules: the first rule whose
`args` all appear, in order, in its arguments decides stdout, stderr and the
exit code. Every call is logged with its arguments, working directory and a
few environment variables, so tests can check what was run and where.
"""
import datetime as dt
import io
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import destroy_guard as dg  # noqa: E402

SCRUB = ("TF_WORKSPACE", "TF_DATA_DIR", "KUBECONFIG", "HELM_NAMESPACE", "HELM_KUBECONTEXT", "DESTROY_GUARD_DIR",
         "DESTROY_GUARD_MAX_AGE_MINUTES", "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GITHUB_TOKEN", "GH_TOKEN")

FAKE = r'''#!{python}
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
NAME = {name!r}
args = sys.argv[1:]
with open(os.path.join(HERE, "calls.jsonl"), "a", encoding="utf-8") as log:
    log.write(json.dumps({{"tool": NAME, "args": args, "cwd": os.getcwd(),
                          "env": {{k: os.environ.get(k) for k in ("TF_WORKSPACE", "CHECKPOINT_DISABLE", "TF_INPUT",
                                                                 "GIT_TERMINAL_PROMPT", "AWS_PROFILE")}}}}) + "\n")
with open(os.path.join(HERE, NAME + ".rules.json"), encoding="utf-8") as f:
    rules = json.load(f)

def matches(want, got):
    it = iter(got)
    return all(any(w == g for g in it) for w in want)

for rule in rules:
    if matches(rule.get("args", []), args):
        out = rule.get("stdout", "")
        sys.stdout.buffer.write(out.encode("latin-1") if rule.get("raw") else out.encode("utf-8"))
        sys.stderr.write(rule.get("stderr", ""))
        sys.exit(rule.get("rc", 0))
sys.stderr.write("fake " + NAME + ": no rule for " + " ".join(args) + "\n")
sys.exit(99)
'''


def state_json(resources=2, serial=7, lineage="3f2a9c1e-0000-4000-8000-000000000001", secret=None) -> str:
    """A Terraform state document of the shape `terraform state pull` prints."""
    res = [{"mode": "managed", "type": "aws_db_instance" if i == 0 else "aws_s3_bucket", "name": f"r{i}",
            "provider": "provider[\"registry.terraform.io/hashicorp/aws\"]",
            "instances": [{"attributes": {"id": f"id-{i}", "password": secret or "x"}}]} for i in range(resources)]
    return json.dumps({"version": 4, "terraform_version": "1.9.5", "serial": serial, "lineage": lineage,
                       "outputs": {}, "resources": res})


def k8s_object(kind, name, namespace=None, **extra) -> str:
    meta = {"name": name}
    if namespace:
        meta["namespace"] = namespace
    doc = {"apiVersion": "v1", "kind": kind, "metadata": meta}
    doc.update(extra)
    return json.dumps(doc)


def k8s_list(*objs) -> str:
    return json.dumps({"apiVersion": "v1", "kind": "List", "items": [json.loads(o) for o in objs]})


class Isolated(unittest.TestCase):
    """A home, a project directory and a bin directory of the test's own, and no network."""

    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(os.path.realpath(tmp.name))
        self.home, self.project, self.bin = self.tmp / "home", self.tmp / "project", self.tmp / "bin"
        for d in (self.home, self.project, self.bin):
            d.mkdir()
        env = {"HOME": str(self.home), "USERPROFILE": str(self.home), "XDG_CONFIG_HOME": str(self.home / ".config"),
               "PATH": str(self.bin) + os.pathsep + os.environ.get("PATH", ""), "GIT_CONFIG_NOSYSTEM": "1"}
        patches = [mock.patch.dict(os.environ, env),
                   mock.patch("pathlib.Path.home", return_value=self.home),
                   mock.patch("urllib.request.urlopen", self._refuse)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        for var in SCRUB:
            os.environ.pop(var, None)  # restored with the rest of the environment by patch.dict

    @staticmethod
    def _refuse(*a, **k):
        raise AssertionError("destroy-guard tried to reach the network")

    # -------------------------------------------------------------- fakes

    def fake_tool(self, name: str, rules: list) -> None:
        script = self.bin / name
        script.write_text(FAKE.format(python=sys.executable, name=name), encoding="utf-8")
        script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        (self.bin / f"{name}.rules.json").write_text(json.dumps(rules), encoding="utf-8")

    def calls(self, tool=None) -> list:
        log = self.bin / "calls.jsonl"
        if not log.exists():
            return []
        rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
        return [r for r in rows if tool is None or r["tool"] == tool]

    def kubeconfig(self, context="kind-prod", path=None) -> Path:
        p = Path(path) if path else self.home / ".kube" / "config"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"apiVersion: v1\nkind: Config\ncurrent-context: {context}\nusers: []\n", encoding="utf-8")
        return p

    def git_repo(self, path=None, branch="main", config="") -> Path:
        """A work tree whose .git holds only what destroy-guard reads: HEAD and config."""
        top = Path(path) if path else self.project
        (top / ".git").mkdir(parents=True, exist_ok=True)
        (top / ".git" / "HEAD").write_text(f"ref: refs/heads/{branch}\n" if branch else "0" * 40 + "\n")
        (top / ".git" / "config").write_text(config or "[core]\n\tbare = false\n")
        return top

    # -------------------------------------------------------------- runners

    def cli(self, *argv):
        """destroy_guard.main(argv) -> (exit code, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with mock.patch("sys.stdout", out), mock.patch("sys.stderr", err):
            code = dg.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def hook(self, command, tool="Bash", cwd=None, event="PreToolUse"):
        """The hook's main() on a payload -> its parsed JSON answer, or None when it stays silent."""
        import destroy_guard_hook
        payload = {"hook_event_name": event, "tool_name": tool, "tool_input": {"command": command},
                   "cwd": str(cwd or self.project), "tool_use_id": "toolu_test"}
        stdin = io.TextIOWrapper(io.BytesIO(json.dumps(payload).encode("utf-8")), encoding="utf-8")
        with mock.patch("sys.stdin", stdin), mock.patch("sys.stdout", new_callable=io.StringIO) as out, \
                mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            self.assertEqual(destroy_guard_hook.main(), 0)
        self.hook_stderr = err.getvalue()
        text = out.getvalue().strip()
        return json.loads(text) if text else None

    def ops(self, command, shell="bash", cwd=None):
        return dg.analyse(command, shell, str(cwd or self.project))

    # -------------------------------------------------------------- hand-made backups

    def write_backup(self, targets, created=None, store=None, files=None, verified=True, mode=0o700, name=None):
        """A backup directory with a manifest, as the CLI writes it; returns its path."""
        store = Path(store) if store else self.project / ".destroy-guard"
        created = created or dg.now_utc()
        d = store / "backups" / (name or f"{created.strftime('%Y%m%dT%H%M%SZ')}-{os.urandom(6).hex()}")
        d.mkdir(parents=True)
        exports = []
        for fname, data in (files or {"export.json": b"{}"}).items():
            (d / fname).write_bytes(data)
            exports.append({"file": fname, "bytes": len(data), "sha256": dg.hashlib.sha256(data).hexdigest()})
        manifest = {"destroy_guard": dg.VERSION, "format": 1, "created_utc": created.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "command": "x", "label": "x", "what": "x", "targets": targets, "exports": exports,
                    "tool_versions": {}, "verified": verified}
        (d / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        os.chmod(d, mode)
        return d


def minutes_ago(n: float) -> dt.datetime:
    return dg.now_utc() - dt.timedelta(minutes=n)
