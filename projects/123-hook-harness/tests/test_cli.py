"""The command line: exit codes, output formats, --strict, masking, and files that cannot be read."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import Isolated, hh, one_handler, py_handler, script  # noqa: E402

ASK = script('print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask", '
             '"permissionDecisionReason": "token " + os.environ.get("SECRETISH", "")}}))')


class ExitCodes(Isolated):
    def hooks(self, handler_extra=None, matcher="Bash|PowerShell", body=ASK):
        return self.plugin(one_handler("PreToolUse", matcher, py_handler("h.py", **(handler_extra or {}))), {"h.py": body})

    def test_lint(self):
        clean = self.hooks({"timeout": 20})
        self.assertEqual(self.main("lint", clean)[0], 0)
        self.assertEqual(self.main("lint", clean, "--strict")[0], 0)  # notes do not fail --strict
        warn = self.hooks({"timeout": 20000})
        self.assertEqual(self.main("lint", warn)[0], 0)
        self.assertEqual(self.main("lint", warn, "--strict")[0], 1)
        broken = self.tmp / "broken.json"
        broken.write_text("{", encoding="utf-8")
        code, out, _ = self.main("lint", broken, "--strict")
        self.assertEqual(code, 1)
        self.assertIn("broken.json:1:2: error [json-syntax]", out)

    def test_missing_files_are_exit_2(self):
        code, _out, err = self.main("lint", self.tmp / "nope.json")
        self.assertEqual(code, 2)
        self.assertIn("cannot read", err)
        hooks = self.hooks()
        self.assertEqual(self.main("run", hooks, self.tmp / "nope.json")[0], 2)
        self.assertEqual(self.main("lint", hooks, "--plugin-root", self.tmp / "no-such-dir")[0], 2)
        self.assertEqual(self.main()[0], 2)
        bad = self.tmp / "bad.json"
        bad.write_text("[1,", encoding="utf-8")
        code, _out, err = self.main("run", bad, self.cases([{"tool_name": "Bash"}]))
        self.assertEqual(code, 2)
        self.assertIn("cannot run cases", err)

    def test_run(self):
        hooks = self.hooks()
        ok = self.cases([{"name": "asks", "tool_name": "Bash", "tool_input": {"command": "x"}, "expect": {"decision": "ask"}}])
        self.assertEqual(self.main("run", hooks, ok)[0], 0)
        bad = self.cases([{"name": "asks", "tool_name": "Bash", "tool_input": {"command": "x"}, "expect": {"decision": "deny"}}])
        self.assertEqual(self.main("run", hooks, bad)[0], 1)
        self.assertEqual(self.main("run", hooks, ok, "--only", "zzz")[0], 2)

    def test_strict_run_fails_on_output_warnings(self):
        hooks = self.hooks(body=script('print("plain text")'))
        cases = self.cases([{"tool_name": "Bash", "tool_input": {"command": "x"}}])
        self.assertEqual(self.main("run", hooks, cases)[0], 0)
        code, out, _ = self.main("run", hooks, cases, "--strict")
        self.assertEqual(code, 1)
        self.assertIn("debug log only", out)

    def test_formats(self):
        hooks = self.hooks()
        cases = self.cases([{"name": "c|1", "tool_name": "Bash", "tool_input": {"command": "x"}, "expect": {"decision": "deny"}}])
        _c, md, _e = self.main("run", hooks, cases, "--markdown")
        self.assertIn("| c\\|1 | fail | PreToolUse Bash | 1 | ask |", md)
        _c, js, _e = self.main("run", hooks, cases, "--json")
        self.assertEqual(json.loads(js)["summary"], {"cases": 1, "passed": 0, "failed": 1, "errors": 0})
        _c, js, _e = self.main("lint", hooks, "--json")
        self.assertEqual(json.loads(js)["command"], "lint")
        _c, md, _e = self.main("lint", self.hooks({"timeout": 9999}), "--markdown")
        self.assertIn("| warning | `timeout-ms` |", md)

    def test_captured_output_cannot_pose_as_a_workflow_command(self):
        hooks = self.hooks(body=script('print("::error::injected"); sys.stderr.write("\\x1b[31m::warning::x\\n"); sys.exit(1)'))
        cases = self.cases([{"tool_name": "Bash", "tool_input": {"command": "x"}, "expect": {"decision": "ask"}}])
        _c, out, _e = self.main("run", hooks, cases)
        for line in out.splitlines():
            self.assertFalse(line.startswith("::"), line)
        self.assertNotIn("\x1b", out)


class Masking(Isolated):
    def test_secrets_are_masked_in_every_format(self):
        token = "ghp_" + "a" * 36
        key = "sk-" + "x" * 32
        hooks = self.plugin(one_handler("PreToolUse", "Bash", py_handler("h.py")), {"h.py": ASK})
        cases = self.cases([{"name": "n", "tool_name": "Bash", "env": {"SECRETISH": f"{token} API_KEY={key}"},
                             "tool_input": {"command": f"curl -H 'Authorization: Bearer {key}' https://u:p@h.example/x?t={key}"},
                             "expect": {"decision": "deny"}}])
        for fmt in ((), ("--json",), ("--markdown",), ("--verbose",)):
            _c, out, _e = self.main("run", hooks, cases, *fmt)
            for secret in (token, key, "u:p@"):
                self.assertNotIn(secret, out, fmt)

    def test_mask_before_truncating(self):
        long_url = "https://user:" + "p" * 400 + "@host.example/x"
        self.assertNotIn("ppp", hh.clean(long_url, 50))


if __name__ == "__main__":
    unittest.main()
