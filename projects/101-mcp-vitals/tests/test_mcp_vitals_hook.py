"""mcp_vitals_hook.py: parsing `claude mcp add`, config edits, and the hook responses. No network."""
import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import Isolated, bash, fixture  # noqa: E402

import mcp_vitals_hook as hook  # noqa: E402

GH = "https://api.github.com/repos/o/n"
NPM = "https://registry.npmjs.org/@o%2Fserver"
NPM_DOC = {"dist-tags": {"latest": "1.0.0"}, "time": {"1.0.0": "2025-01-01T00:00:00Z"},
           "versions": {"1.0.0": {"repository": {"url": "git+https://github.com/o/n.git"}}}}


def gh(pushed, archived=False, license=None):
    doc = fixture("github-repo-agent-vitals.json")
    doc.update(full_name="o/n", name="n", pushed_at=pushed, archived=archived, license=license)
    return doc


class ParseAdd(unittest.TestCase):
    def one(self, cmd, shell="bash"):
        got = hook.parse_add(cmd, shell)
        self.assertEqual(len(got), 1, got)
        return got[0]

    def test_double_dash(self):
        e = self.one("claude mcp add fs -- npx -y @modelcontextprotocol/server-filesystem /tmp")
        self.assertEqual((e["name"], e["command"], e["args"]), ("fs", "npx", ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]))

    def test_options_before_name(self):
        e = self.one("claude mcp add -s user -e API_KEY=abc -e OTHER=1 gh -- docker run -i ghcr.io/github/github-mcp-server")
        self.assertEqual((e["name"], e["command"]), ("gh", "docker"))
        self.assertNotIn("abc", json.dumps(e))

    def test_variadic_env(self):
        e = self.one("claude mcp add -e A=1 B=2 srv uvx pkg")
        self.assertEqual((e["name"], e["command"], e["args"]), ("srv", "uvx", ["pkg"]))

    def test_remote(self):
        e = self.one('claude mcp add --transport http -H "Authorization: Bearer t" linear https://mcp.linear.app/mcp')
        self.assertEqual((e["name"], e["url"], e["command"]), ("linear", "https://mcp.linear.app/mcp", ""))
        self.assertNotIn("Bearer", json.dumps(e))

    def test_add_json(self):
        e = self.one("""claude mcp add-json w '{"command":"uvx","args":["pkg"],"env":{"K":"secret"}}'""")
        self.assertEqual((e["name"], e["command"], e["args"]), ("w", "uvx", ["pkg"]))
        self.assertNotIn("secret", json.dumps(e))

    def test_compound_line(self):
        e = self.one("cd /x && claude mcp add a -- npx pkg && echo done")
        self.assertEqual(e["args"], ["pkg"])

    def test_wrappers_and_assignments(self):
        for cmd in ("FOO=1 claude mcp add a -- npx pkg", "sudo -u root claude mcp add a -- npx pkg",
                    "timeout -s KILL 30 claude mcp add a -- npx pkg", "/usr/local/bin/claude mcp add a -- npx pkg"):
            self.assertEqual(self.one(cmd)["args"], ["pkg"], cmd)

    def test_powershell(self):
        e = self.one(r"& 'C:\Users\me\.local\bin\claude.exe' mcp add fs -- node C:\Users\me\srv\index.js", "powershell")
        self.assertEqual((e["name"], e["command"], e["args"]), ("fs", "node", [r"C:\Users\me\srv\index.js"]))

    def test_not_an_add(self):
        for cmd in ("claude mcp list", "echo claude mcp add", "echo claude mcp add a b", "npx -y pkg", "claude mcp add",
                    "'unbalanced", "claude mcp add-from-claude-desktop", "claude"):
            self.assertEqual(hook.parse_add(cmd), [], cmd)


class Edits(Isolated):
    def test_only_servers_the_edit_touched(self):
        p = self.tmp / ".mcp.json"
        p.write_text(json.dumps({"mcpServers": {"old": {"command": "npx", "args": ["a"]},
                                                "new": {"command": "npx", "args": ["b"], "env": {"K": "secret"}}}}))
        got = hook.added_by_edit({"file_path": str(p), "old_string": "x", "new_string": '"new": {"command": "npx"'})
        self.assertEqual([s["name"] for s in got], ["new"])
        self.assertNotIn("secret", json.dumps(got))

    def test_other_files_ignored(self):
        self.assertEqual(hook.added_by_edit({"file_path": "/x/package.json", "content": "{}"}), [])


class Run(Isolated):
    def test_abandoned_server_asks(self):
        self.serve({NPM: NPM_DOC, GH: gh("2024-01-01T00:00:00Z", license={"spdx_id": "MIT"})})
        out = self.run_hook(bash("claude mcp add x -- npx -y @o/server"))
        hso = out["hookSpecificOutput"]
        self.assertEqual(hso["permissionDecision"], "ask")
        self.assertIn("abandoned", hso["permissionDecisionReason"])
        self.assertIn("o/n", hso["permissionDecisionReason"])

    def test_healthy_server_is_silent(self):
        self.serve({NPM: NPM_DOC, GH: gh("2026-09-20T00:00:00Z", license={"spdx_id": "MIT"})})
        self.assertIsNone(self.run_hook(bash("claude mcp add x -- npx -y @o/server")))

    def test_unreachable_network_is_silent(self):
        web = self.serve({NPM: NPM_DOC, GH: 403})
        self.assertIsNone(self.run_hook(bash("claude mcp add x -- npx -y @o/server")))
        self.assertNotIn("agent-vitals", " ".join(web.urls))  # the hook never waits for the 26 MB census

    def test_other_bash_is_silent(self):
        self.assertIsNone(self.run_hook(bash("ls -la")))

    def test_post_edit_gives_context(self):
        p = self.tmp / ".mcp.json"
        p.write_text(json.dumps({"mcpServers": {"x": {"command": "npx", "args": ["-y", "@o/server"]}}}))
        self.serve({NPM: NPM_DOC, GH: gh("2026-09-20T00:00:00Z", archived=True)})
        out = self.run_hook({"hook_event_name": "PostToolUse", "tool_name": "Write",
                             "tool_input": {"file_path": str(p), "content": p.read_text()}})
        self.assertIn("archived", out["hookSpecificOutput"]["additionalContext"])

    def test_garbage_stdin(self):
        for payload in ("not json", "[]", "null", '{"tool_input": 5}'):
            with mock.patch("sys.stdin", io.StringIO(payload)):
                self.assertEqual(hook.main(), 0)


if __name__ == "__main__":
    unittest.main()
