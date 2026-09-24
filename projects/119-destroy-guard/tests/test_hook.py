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


if __name__ == "__main__":
    unittest.main()
