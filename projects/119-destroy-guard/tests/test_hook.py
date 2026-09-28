"""destroy_guard_hook.py: payloads in, one `ask` or silence out, exit code 0 whatever happens."""
import io
import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import ROOT, Isolated, minutes_ago  # noqa: E402

import destroy_guard as dg  # noqa: E402
import destroy_guard_hook as hook  # noqa: E402


class Payloads(Isolated):
    def run_raw(self, data: bytes):
        stdin = io.TextIOWrapper(io.BytesIO(data), encoding="utf-8")
        with mock.patch("sys.stdin", stdin), mock.patch("sys.stdout", new_callable=io.StringIO) as out, \
                mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            code = hook.main()
        return code, out.getvalue(), err.getvalue()

    def test_garbage_is_silent(self):
        for data in (b"", b"not json", b"[]", b"null", b'"x"', b'{"tool_input": 5}', b"\xff\xfe\x00",
                     b'{"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": 5}}',
                     b'{"hook_event_name": "PreToolUse", "tool_name": "Bash"}'):
            with self.subTest(data=data):
                code, out, _ = self.run_raw(data)
                self.assertEqual((code, out), (0, ""))

    def test_other_events_and_tools_are_silent(self):
        self.assertIsNone(self.hook("terraform destroy", event="PostToolUse"))
        self.assertIsNone(self.hook("terraform destroy", tool="Write"))
        self.assertIsNone(self.hook("ls -la"))
        self.assertIsNone(self.hook("terraform plan"))

    def test_ask_shape(self):
        out = self.hook("terraform destroy -auto-approve")
        self.assertEqual(set(out), {"hookSpecificOutput"})
        hso = out["hookSpecificOutput"]
        self.assertEqual(set(hso), {"hookEventName", "permissionDecision", "permissionDecisionReason",
                                    "additionalContext"})
        self.assertEqual((hso["hookEventName"], hso["permissionDecision"]), ("PreToolUse", "ask"))
        self.assertIn("backup -- terraform destroy -auto-approve", hso["permissionDecisionReason"])
        self.assertIn(hso["permissionDecisionReason"], hso["additionalContext"])

    def test_powershell(self):
        out = self.hook(r"cd C:\infra; terraform destroy", tool="PowerShell")
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "ask")

    def test_covered_is_silent_and_stale_asks_with_age(self):
        op = self.ops("terraform destroy")[0]
        self.write_backup(op["targets"], created=minutes_ago(45))
        reason = self.hook("terraform destroy")["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("45 min old", reason)
        self.write_backup(op["targets"], created=minutes_ago(1))
        self.assertIsNone(self.hook("terraform destroy"))
        self.assertIsNone(self.hook("cd . && TF_LOG=1 terraform destroy -auto-approve"))  # same target

    def test_one_uncovered_operation_is_enough_to_ask(self):
        op = self.ops("terraform destroy")[0]
        self.write_backup(op["targets"])
        self.kubeconfig()
        reason = self.hook("terraform destroy && kubectl delete ns prod")["hookSpecificOutput"][
            "permissionDecisionReason"]
        self.assertIn("`kubectl delete` deletes namespace prod", reason)
        self.assertNotIn("`terraform destroy`", reason)

    def test_reason_masks_secrets(self):
        key = "AKIA" + "X" * 16
        pw = "pw" + "9" * 14
        self.git_repo()
        reason = json.dumps(self.hook(f"AWS_SECRET_ACCESS_KEY={key} terraform destroy -var db_password={pw} && "
                                      f"git push -f https://bot:{pw}@git.example/x.git main"))
        self.assertNotIn(key, reason)
        self.assertNotIn(pw, reason)

    def test_internal_error_passes_and_is_logged(self):
        with mock.patch.object(dg, "evaluate", side_effect=RuntimeError("boom https://u:pw@x.example/y")):
            self.assertIsNone(self.hook("terraform destroy"))
        self.assertIn("internal error", self.hook_stderr)
        self.assertIn("RuntimeError", self.hook_stderr)
        self.assertNotIn("pw@", self.hook_stderr)

    def test_missing_or_bogus_cwd(self):
        for cwd in (None, 5, str(self.tmp / "gone")):
            payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash",
                       "tool_input": {"command": "terraform destroy"}, "cwd": cwd}
            with mock.patch("os.getcwd", return_value=str(self.project)):
                code, out, _ = self.run_raw(json.dumps(payload).encode())
            self.assertEqual(code, 0)
            self.assertIn(str(self.project), json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"])

    def test_one_answer_per_tool_call(self):
        # a plugin copy and a settings copy of the hook both run; only the first to claim the call answers
        self.assertIsNotNone(self.hook("terraform destroy", tool_use_id="toolu_same"))
        self.assertIsNone(self.hook("terraform destroy", tool_use_id="toolu_same"))
        self.assertIsNotNone(self.hook("terraform destroy", tool_use_id="toolu_other"))
        claims = self.tmp / f"destroy-guard-{os.getuid() if hasattr(os, 'getuid') else 'user'}"
        self.assertEqual(sorted(p.name for p in claims.iterdir()), ["toolu_other", "toolu_same"])
        if os.name == "posix":
            self.assertEqual(claims.stat().st_mode & 0o777, 0o700)
        old = time.time() - hook.CLAIM_MAX_AGE - 5
        os.utime(claims / "toolu_same", (old, old))
        self.assertIsNotNone(self.hook("ls; terraform destroy", tool_use_id="toolu_third"))
        self.assertNotIn("toolu_same", [p.name for p in claims.iterdir()])  # old claims are swept
        for i, cmd in enumerate(("ls -la", "git status", "terraform plan")):
            self.assertIsNone(self.hook(cmd, tool_use_id=f"toolu_plain{i}"))
        self.assertFalse(any(p.name.startswith("toolu_plain") for p in claims.iterdir()))  # a claim only to answer

    def test_quick_test_sees_through_quotes_and_escapes(self):
        for cmd in ("terr''aform destroy", "ku\\bectl delete ns prod", 'g"i"t push --force', "$'\\x74erraform' destroy"):
            with self.subTest(cmd=cmd):
                self.assertTrue(dg.quick(cmd))
                self.assertIsNotNone(self.hook(cmd, cwd=self.project))
        self.assertFalse(dg.quick("ls -la && echo done"))

    def test_context_carries_every_backup_command(self):
        self.kubeconfig()
        cmd = " && ".join(f"kubectl delete configmap config-{i:03d} -n prod" for i in range(20))
        hso = self.hook(cmd)["hookSpecificOutput"]
        self.assertLessEqual(len(hso["permissionDecisionReason"]), dg.MAX_REASON)
        self.assertIn("kubectl delete configmap config-019 -n prod` on its own first", hso["additionalContext"])
        self.assertLess(len(hso["additionalContext"]), 10000)

    def test_hook_runs_nothing(self):
        with mock.patch("subprocess.run", side_effect=AssertionError("the hook ran a command")), \
                mock.patch("subprocess.Popen", side_effect=AssertionError("the hook ran a command")):
            self.kubeconfig()
            self.git_repo()
            for cmd in ("terraform destroy", "kubectl delete ns prod", "helm uninstall web", "git push -f"):
                self.assertIsNotNone(self.hook(cmd))
        self.assertFalse((self.project / ".destroy-guard").exists())  # and writes nothing


class AsAProcess(Isolated):
    def test_script_over_stdin_and_stdout(self):
        payload = json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": str(self.project),
                              "tool_input": {"command": "helm uninstall web -n prod"}})
        start = time.monotonic()
        p = subprocess.run([sys.executable, str(ROOT / "destroy_guard_hook.py")], input=payload.encode(),
                           capture_output=True, env=dict(os.environ), timeout=60)
        elapsed = time.monotonic() - start
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout)["hookSpecificOutput"]["permissionDecision"], "ask")
        self.assertLess(elapsed, 10)
        p = subprocess.run([sys.executable, str(ROOT / "destroy_guard_hook.py")], input=b"{", capture_output=True,
                           timeout=60)
        self.assertEqual((p.returncode, p.stdout), (0, b""))

    def test_ask_reaches_a_stdout_that_is_not_utf8(self):
        # a Windows pipe encodes stdout in the ANSI code page; the answer must not depend on it
        (self.project / "şube-配置").mkdir()
        payload = json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": str(self.project),
                              "tool_input": {"command": "cd şube-配置 && terraform destroy"}})
        env = dict(os.environ, PYTHONIOENCODING="cp1252")
        p = subprocess.run([sys.executable, str(ROOT / "destroy_guard_hook.py")], input=payload.encode(),
                           capture_output=True, env=env, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stderr, b"")
        out = json.loads(p.stdout.decode("ascii"))["hookSpecificOutput"]
        self.assertEqual(out["permissionDecision"], "ask")
        self.assertIn("şube-配置", out["permissionDecisionReason"])

    @unittest.skipUnless(hasattr(os, "mkfifo"), "named pipes")
    def test_a_named_pipe_does_not_stall_the_hook(self):
        # opening a FIFO blocks until a writer comes; a hook that times out gives no answer at all
        (self.project / ".terraform").mkdir()
        os.mkfifo(self.project / ".terraform" / "environment")
        (self.home / ".kube").mkdir()
        os.mkfifo(self.home / ".kube" / "config")
        (self.project / ".git").mkdir()
        os.mkfifo(self.project / ".git" / "HEAD")
        d = self.project / ".destroy-guard" / "backups" / "20260924T100000Z-aaaaaaaaaaaa"
        d.mkdir(parents=True)
        os.chmod(d, 0o700)
        os.mkfifo(d / "manifest.json")
        payload = json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": str(self.project),
                              "tool_input": {"command": "terraform destroy; kubectl delete ns x; git push -f"}})
        start = time.monotonic()
        p = subprocess.run([sys.executable, str(ROOT / "destroy_guard_hook.py")], input=payload.encode(),
                           capture_output=True, env=dict(os.environ), timeout=30)
        self.assertLess(time.monotonic() - start, 10)
        self.assertEqual(json.loads(p.stdout)["hookSpecificOutput"]["permissionDecision"], "ask")

    def test_broken_install_passes_silently(self):
        # the hook script without its module next to it: exit 0, nothing on stdout, one line on stderr
        lone = self.tmp / "lone"
        lone.mkdir()
        (lone / "destroy_guard_hook.py").write_bytes((ROOT / "destroy_guard_hook.py").read_bytes())
        payload = json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": str(self.project),
                              "tool_input": {"command": "terraform destroy"}})
        env = dict(os.environ, PYTHONPATH="")
        p = subprocess.run([sys.executable, "-S", str(lone / "destroy_guard_hook.py")], input=payload.encode(),
                           capture_output=True, env=env, cwd=str(lone), timeout=60)
        self.assertEqual((p.returncode, p.stdout), (0, b""))
        self.assertIn(b"internal error", p.stderr)


if __name__ == "__main__":
    unittest.main()
