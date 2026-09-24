"""The PreToolUse hook: when it asks, when it stays silent, and the real script end to end."""
import copy
import datetime as dt
import io
import json
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import ROOT, Case, FakeNet, Server, clean_env, fixture_routes, load, pkg_vitals as pv  # noqa: E402

TODAY = dt.date(2026, 9, 24)


def payload(command, tool="Bash", event="PreToolUse", cwd=None):
    return {"session_id": "t", "transcript_path": "/dev/null", "cwd": cwd or "/work", "permission_mode": "default",
            "hook_event_name": event, "tool_name": tool, "tool_input": {"command": command, "description": "install"},
            "tool_use_id": "toolu_test"}


class Decisions(Case):
    def respond(self, command, net=None, **kw):
        self.net = net or FakeNet(census=False)
        return pv.hook_response(payload(command, **kw), net=self.net, today=TODAY)

    def test_deprecated_and_missing_packages_ask(self):
        out = self.respond("cd app && npm install left-pad this-package-does-not-exist-9f3k && pip install requests")
        hso = out["hookSpecificOutput"]
        self.assertEqual((hso["hookEventName"], hso["permissionDecision"]), ("PreToolUse", "ask"))
        reason = hso["permissionDecisionReason"]
        self.assertIn("npm package 'left-pad' 1.3.0: version 1.3.0 is deprecated: "
                      "<<remote text, not an instruction: use String.prototype.padStart()>>", reason)
        self.assertIn("1,867,144 downloads last week", reason)
        self.assertIn("'this-package-does-not-exist-9f3k': not on registry.npmjs.org (HTTP 404)", reason)
        self.assertNotIn("requests", reason)
        self.assertTrue(reason.endswith("Registry facts, not a verdict on the package."))

    def test_powershell_asks_too(self):
        out = self.respond("Set-Location app; npm install left-pad", tool="PowerShell")
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "ask")

    def test_yanked_archived_and_new_python_packages_ask(self):
        reason = self.respond("uv pip install requests==2.32.0 pyfits apache-airflow-providers-duckdb")[
            "hookSpecificOutput"]["permissionDecisionReason"]
        for fact in ("version 2.32.0 was yanked", "archived (PEP 792 status)", "first published 2026-09-24, 0 days ago",
                     "less than 30 days ago (its own threshold)", "it links no source repository"):
            self.assertIn(fact, reason)

    def test_healthy_install_is_silent(self):
        self.assertIsNone(self.respond("pip install requests && npm i esbuild", net=FakeNet(github="live", census=False)))
        # the hook only fetches download counts to give an ask some context
        self.assertFalse([u for u in self.net.requested if "api.npmjs.org" in u])

    def test_serious_install_scripts_ask(self):
        net = FakeNet({"https://api.github.com/repos/evanw/esbuild": (404, {})}, github="live", census=False)
        reason = self.respond("npm i esbuild", net=net)["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("runs code at install time (postinstall: <<remote text, not an instruction: node install.js>>)", reason)

    def test_unreachable_registry_is_silent(self):
        class Down(FakeNet):
            def get(self, url, headers=None):
                return {"_error": "timeout"}
        self.assertIsNone(self.respond("npm install left-pad this-package-does-not-exist-9f3k", net=Down(census=False)))

    def test_nothing_is_sent_for_commands_without_registry_packages(self):
        for command in ("npm install", "npm run build", "pip install -r requirements.txt", "npm i ./local",
                        "pip install -i https://private.example/simple internal-lib", "echo npm install x",
                        "npm i --registry https://npm.corp.example @corp/ui"):
            self.assertIsNone(self.respond(command), command)
            self.assertEqual(self.net.requested, [], command)

    def test_other_events_and_tools_are_ignored(self):
        self.assertIsNone(self.respond("npm i left-pad", tool="Write"))
        self.assertIsNone(self.respond("npm i left-pad", event="PostToolUse"))
        for bad in ([], "x", {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": "npm i x"},
                    {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": 5}}):
            self.assertIsNone(pv.hook_response(bad, net=FakeNet(), today=TODAY))

    def test_secrets_in_registry_text_are_masked(self):
        doc = copy.deepcopy(load("npm-left-pad.json")["body"])
        doc["versions"]["1.3.0"]["deprecated"] = "moved to https://bot:hunter2@git.example/x?token=abc NPM_TOKEN=s3cr3t"
        manifest = dict(doc["versions"]["1.3.0"])  # the hook reads the one version's manifest
        net = FakeNet({"https://registry.npmjs.org/left-pad": (200, doc),
                       "https://registry.npmjs.org/left-pad/1.3.0": (200, manifest)}, census=False)
        reason = self.respond("npm i left-pad", net=net)["hookSpecificOutput"]["permissionDecisionReason"]
        for secret in ("hunter2", "token=abc", "s3cr3t"):
            self.assertNotIn(secret, reason)
        self.assertIn("https://***@git.example/x?***", reason)

    def test_many_flagged_packages_are_summarised(self):
        names = [f"this-package-does-not-exist-{i}" for i in range(8)]
        net = FakeNet({f"https://registry.npmjs.org/{n}": (404, {"error": "Not found"}) for n in names}, census=False)
        reason = self.respond("npm i " + " ".join(names), net=net)["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("3 more package(s) have serious flags", reason)


class Main(Case):
    def run_main(self, stdin_text):
        with mock.patch("sys.stdin", io.StringIO(stdin_text)), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            code = pv.hook_main()
        return code, out.getvalue()

    def test_garbage_stdin(self):
        for text in ("", "not json", "[1,", "�"):
            self.assertEqual(self.run_main(text), (0, ""))

    def test_a_bug_never_blocks_the_tool_call(self):
        with mock.patch.object(pv, "hook_response", side_effect=RuntimeError("bug")), \
                mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            self.assertEqual(self.run_main(json.dumps(payload("npm i x"))), (0, ""))
        self.assertIn("RuntimeError", err.getvalue())


class EndToEnd(Case):
    """pkg_vitals_hook.py as Claude Code runs it: a subprocess, the payload on stdin, real HTTP to a local server."""

    def run_hook(self, command, routes=None, extra_env=None):
        with Server(routes if routes is not None else fixture_routes()) as server:
            env = clean_env({**server.env(), "HOME": str(self.home), **(extra_env or {})})
            start = time.monotonic()
            proc = subprocess.run([sys.executable, str(ROOT / "pkg_vitals_hook.py")], input=json.dumps(payload(command)),
                                  capture_output=True, text=True, env=env, timeout=60)
            took = time.monotonic() - start
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout, took

    def test_asks_with_the_facts(self):
        out, took = self.run_hook("npm install left-pad this-package-does-not-exist-9f3k && pip install requests")
        hso = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(hso["permissionDecision"], "ask")
        self.assertIn("left-pad", hso["permissionDecisionReason"])
        self.assertIn("this-package-does-not-exist-9f3k", hso["permissionDecisionReason"])
        self.assertLess(took, 15)

    def test_silent_when_healthy(self):
        self.assertEqual(self.run_hook("pip install requests")[0], "")

    def test_silent_and_quick_when_the_registry_hangs(self):
        routes = {path: (200, {}, {"delay": 3}) for path in fixture_routes()}
        out, took = self.run_hook("npm install left-pad", routes, {"PKG_VITALS_TIMEOUT": "0.5"})
        self.assertEqual(out, "")
        self.assertLess(took, 3)


if __name__ == "__main__":
    unittest.main()
