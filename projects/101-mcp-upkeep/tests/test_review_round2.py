"""Regression tests for the second adversarial review (2026-09-24), one class per finding."""
import fnmatch
import importlib
import json
import os
import re
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import ROOT, Isolated, Web, bash  # noqa: E402

import mcp_upkeep  # noqa: E402
import mcp_upkeep_hook as hook  # noqa: E402

# built at run time: no file holds anything shaped like a real key
NOTION = "ntn_" + "4" * 46


class R1_WriteAndEditBothFire(Isolated):
    """[high] `Edit(...)` rules do not fire for Write calls, the usual way a new .mcp.json appears."""

    def fires(self, tool, path):
        hooks = json.loads((ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]["PostToolUse"]
        out = []
        for group in hooks:
            if not re.fullmatch(group["matcher"], tool):
                continue
            for h in group["hooks"]:
                m = re.fullmatch(r"(\w+)\(//\*\*/(.+)\)", h.get("if", ""))
                # the documented behaviour: one rule, one tool; `//**/` matches at any depth
                if m and m.group(1) == tool and fnmatch.fnmatchcase(Path(path).name, m.group(2)):
                    out.append(h["if"])
        return out

    def test_each_call_fires_exactly_one_handler(self):
        for tool in ("Write", "Edit"):
            for path in ("/p/.mcp.json", "/home/u/.cursor/mcp.json", "/home/u/.codeium/windsurf/mcp_config.json",
                         "/home/u/Library/Application Support/Claude/claude_desktop_config.json"):
                self.assertEqual(len(self.fires(tool, path)), 1, (tool, path))
            self.assertEqual(self.fires(tool, "/p/notes.txt"), [])


class R2_WholeCommandLineInCommand(Isolated):
    """[medium] a `command` holding the whole command line printed its key in the table and in JSON."""

    def test_config(self):
        cfg = self.write_config({"mcpServers": {
            "notion": {"command": f"npx -y @notionhq/notion-mcp-server {NOTION}"},
            "odd": {"command": f"some-binary {NOTION}"},
            "posarg": {"command": "npx", "args": ["-y", "@o/server", NOTION]}}})
        outs = {mode: self.run_main([*flag, "--offline", "--config", str(cfg)])[1]
                for mode, flag in (("text", []), ("markdown", ["--markdown"]), ("json", ["--json"]))}
        for mode, out in outs.items():
            self.assertNotIn(NOTION[:12], out, mode)
        servers = {s["name"]: s for s in json.loads(outs["json"])["servers"]}
        self.assertEqual((servers["notion"]["command"], servers["notion"]["kind"], servers["notion"]["package"]),
                         ("npx", "npm", "@notionhq/notion-mcp-server"))
        self.assertEqual(servers["notion"]["args"], ["-y", "@notionhq/notion-mcp-server", "***"])
        self.assertEqual((servers["odd"]["command"], servers["odd"]["args"]), ("some-binary", ["***"]))
        self.assertEqual(servers["posarg"]["args"], ["-y", "@o/server", "***"])
        row = next(line for line in outs["text"].splitlines() if line.startswith("odd"))
        self.assertIn("some-binary", row)

    def test_target_and_hook(self):
        out = self.run_main(["--offline", "--json", f"npx -y @notionhq/notion-mcp-server {NOTION}"])[1]
        self.assertNotIn(NOTION[:12], out)
        self.assertEqual(json.loads(out)["servers"][0]["package"], "@notionhq/notion-mcp-server")
        npm = {"dist-tags": {"latest": "1.0.0"}, "versions": {"1.0.0": {"deprecated": "moved"}}}
        self.serve({"https://registry.npmjs.org/@notionhq%2Fnotion-mcp-server": npm})
        for cmd in (f'claude mcp add notion "npx -y @notionhq/notion-mcp-server {NOTION}"',
                    "claude mcp add-json notion '" + json.dumps({"command": f"npx -y @notionhq/notion-mcp-server {NOTION}"}) + "'"):
            said = json.dumps(self.run_hook(bash(cmd)))
            self.assertIn("deprecated", said, cmd)
            self.assertNotIn(NOTION[:12], said, cmd)


class R3_SymlinkLoop(Isolated):
    """[low] a config that is a symlink to itself crashed with RuntimeError on Python 3.9 to 3.12."""

    def test_loop(self):
        link = self.cwd / ".mcp.json"
        try:
            link.symlink_to(".mcp.json")
        except (OSError, NotImplementedError):
            self.skipTest("symlinks not available here")
        code, out, err = self.run_main(["--offline", "--strict"])
        self.assertEqual(code, 0)
        self.assertEqual(self.run_main(["--offline", "--config", str(link)])[0], 2)


class R4_DocumentedWrappers(Isolated):
    """[low] the hook ignored wrappers Claude Code strips, and handled ones that never reach it."""

    def test_stripped_wrappers_are_seen(self):
        for prefix in ("nice -n 5", "nice", "stdbuf -oL", "stdbuf -o L", "noglob", "builtin", "command", "xargs",
                       "time -p", "nohup", "timeout 30"):
            got = hook.parse_add(f"{prefix} claude mcp add x -- npx -y pkg")
            self.assertEqual([(e["name"], e["args"]) for e in got], [("x", ["-y", "pkg"])], prefix)

    def test_forms_claude_code_does_not_strip(self):
        for cmd in ("xargs -n1 claude mcp add x -- npx -y pkg", "command -v claude mcp add x -- npx pkg",
                    "sudo claude mcp add x -- npx -y pkg", "env FOO=1 claude mcp add x -- npx -y pkg"):
            self.assertEqual(hook.parse_add(cmd), [], cmd)


class R5_TimeoutSetting(Isolated):
    """[low] MCP_UPKEEP_HOOK_TIMEOUT=6s raised at import: a hook error on every call."""

    def test_bad_value_falls_back(self):
        for value in ("6s", "", "nan", "-1", "1e9"):
            with mock.patch.dict(os.environ, {"MCP_UPKEEP_HOOK_TIMEOUT": value}):
                importlib.reload(hook)
                self.assertEqual(hook.request_timeout(), 6.0, value)
                self.assertIsNone(self.run_hook(bash("ls")))
        with mock.patch.dict(os.environ, {"MCP_UPKEEP_HOOK_TIMEOUT": "3"}):
            self.assertEqual(hook.request_timeout(), 3.0)
        importlib.reload(hook)


class R6_TimeBudget(Isolated):
    """[low] no total time budget; and shlex took 35 s on a 1 MB command."""

    def test_budget_stops_checking_and_keeps_what_it_found(self):
        clock = {"t": 0.0}

        class Slow(Web):
            def __call__(self, req, timeout=None):
                try:
                    return super().__call__(req, timeout)
                finally:
                    clock["t"] += 6  # every request takes 6 seconds

        npm = {"dist-tags": {"latest": "1.0.0"}, "versions": {"1.0.0": {"deprecated": "moved"}}}
        self.web = Slow({f"https://registry.npmjs.org/pkg{i}": npm for i in range(1, 6)})
        p = self.tmp / ".mcp.json"
        p.write_text(json.dumps({"mcpServers": {f"s{i}": {"command": "npx", "args": ["-y", f"pkg{i}"]} for i in range(1, 6)}}))
        with mock.patch.object(mcp_upkeep.time, "monotonic", lambda: clock["t"]):
            out = self.run_hook({"hook_event_name": "PostToolUse", "tool_name": "Write",
                                 "tool_input": {"file_path": str(p), "content": p.read_text()}})
        self.assertEqual(len(self.web.requests), 3)  # at 0, 6 and 12 s; nothing started after 15
        self.assertEqual(self.web.timeouts, [6.0, 6.0, 3.0])
        context = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("'s1'", context)
        self.assertNotIn("'s5'", context)

    def test_long_command_is_not_parsed(self):
        start = time.monotonic()
        self.assertEqual(hook.parse_add("claude mcp add x -- npx -y pkg " + "a " * 500000), [])
        self.assertLess(time.monotonic() - start, 1.0)


class R7_ExitCodeSentence(Isolated):
    """[low] the README said exit 0 "always, without --strict", but a bad --config exits 2."""

    def test_readme(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertNotIn("(always, without `--strict`)", readme)
        self.assertIn("a bad `--config` path, which exit 2", readme)


if __name__ == "__main__":
    unittest.main()
