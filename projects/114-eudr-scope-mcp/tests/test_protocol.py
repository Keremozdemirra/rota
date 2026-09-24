import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import support  # noqa: E402
from eudr_scope_mcp import protocol  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def exchange(*messages):
    out = io.StringIO()
    protocol.serve(io.StringIO("".join(m if isinstance(m, str) else json.dumps(m) + "\n" for m in messages)), out)
    return [json.loads(line) for line in out.getvalue().splitlines()]


class InProcess(unittest.TestCase):
    def setUp(self):
        self.env = support.SnapshotEnv(support.shared_snapshot())
        self.env.__enter__()

    def tearDown(self):
        self.env.__exit__(None, None, None)

    def call(self, name, arguments):
        return exchange({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                         "params": {"name": name, "arguments": arguments}})[0]["result"]

    def test_tool_list_has_five_tools_with_schemas(self):
        tools = exchange({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})[0]["result"]["tools"]
        self.assertEqual([t["name"] for t in tools],
                         ["eudr_scope", "commodity_codes", "application_dates", "country_risk", "sources"])
        for t in tools:
            if t["name"] != "sources":
                self.assertIn("not legal advice", t["description"])
            self.assertEqual(t["inputSchema"]["type"], "object")

    def test_errors_are_tool_results(self):
        for name, args in (("eudr_scope", {"cn_code": "abc"}), ("eudr_scope", {}), ("country_risk", {"country": ""}),
                           ("eudr_scope", {"cn_code": "1801", "extra": 1}), ("commodity_codes", "wood"),
                           ("application_dates", {"operator_type": "pirate"})):
            with self.subTest(name=name, args=args):
                r = self.call(name, args)
                self.assertTrue(r["isError"])
                self.assertNotIn("Traceback", r["content"][0]["text"])

    def test_structured_and_text_agree(self):
        r = self.call("eudr_scope", {"cn_code": "1801 00 00"})
        self.assertFalse(r["isError"])
        self.assertEqual(json.loads(r["content"][0]["text"]), r["structuredContent"])

    def test_json_rpc_errors(self):
        replies = exchange("not json\n", {"jsonrpc": "2.0", "id": 2, "method": "resources/list"},
                           {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "nope"}},
                           {"jsonrpc": "2.0", "method": "notifications/initialized"}, "[1, 2]\n",
                           {"jsonrpc": "2.0", "id": 4, "method": "tools/list", "params": [1]})
        self.assertEqual([r.get("error", {}).get("code") for r in replies], [-32700, -32601, -32602, -32600, -32602])


class OverStdio(unittest.TestCase):
    """The installed entry point, spoken to over stdin/stdout like a client would."""

    def test_end_to_end(self):
        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "eudr_scope", "arguments": {"cn_code": "4101"}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
             "params": {"name": "country_risk", "arguments": {"country": "Myanmar"}}},
            {"jsonrpc": "2.0", "id": 5, "method": "ping"},
        ]
        with tempfile.TemporaryDirectory() as home:
            env = dict(os.environ, HOME=home, PYTHONPATH=str(ROOT))
            env["EUDR_SCOPE_DATA_DIR"] = str(support.shared_snapshot())
            proc = subprocess.run([sys.executable, "-m", "eudr_scope_mcp"], cwd=home, env=env, timeout=60,
                                  input="".join(json.dumps(m) + "\n" for m in messages),
                                  capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        replies = {r["id"]: r for r in map(json.loads, proc.stdout.splitlines())}
        self.assertEqual(sorted(replies), [1, 2, 3, 4, 5])
        self.assertEqual(replies[1]["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(replies[1]["result"]["serverInfo"]["name"], "eudr-scope-mcp")
        self.assertEqual(len(replies[2]["result"]["tools"]), 5)
        scope = replies[3]["result"]["structuredContent"]
        self.assertEqual(scope["status"], "not_listed")
        self.assertEqual(scope["removed_earlier"][0]["annex_entry"], "ex 4101")
        self.assertEqual(replies[4]["result"]["structuredContent"]["risk"], "high")
        self.assertEqual(replies[5]["result"], {})
        self.assertTrue(proc.stdout.isascii())


if __name__ == "__main__":
    unittest.main()
