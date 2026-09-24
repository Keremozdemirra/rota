"""The MCP protocol: unit tests of handle(), and one end-to-end session over stdin/stdout."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cbam_test_support import ROOT, DataEnv, shared_data_dir  # noqa: E402
from cbam_mcp import mcp_stdio  # noqa: E402


def call(name, args=None, id_=1):
    return mcp_stdio.handle({"jsonrpc": "2.0", "id": id_, "method": "tools/call",
                             "params": {"name": name, "arguments": args if args is not None else {}}})


class Handle(unittest.TestCase):
    def setUp(self):
        self.env = DataEnv()
        self.env.__enter__()

    def tearDown(self):
        self.env.__exit__()

    def test_initialize(self):
        r = mcp_stdio.handle({"jsonrpc": "2.0", "id": 0, "method": "initialize",
                              "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t"}}})
        self.assertEqual(r["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(r["result"]["serverInfo"]["name"], "cbam-mcp")
        self.assertIn("tools", r["result"]["capabilities"])

    def test_tools_list_describes_units_and_limits(self):
        tools = mcp_stdio.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]
        self.assertEqual([t["name"] for t in tools], ["cbam_scope", "default_value", "compare_origins", "cn_describe", "sources"])
        by = {t["name"]: t for t in tools}
        self.assertIn("tCO2e per tonne of good", by["default_value"]["description"])
        self.assertIn("Not legally binding", by["default_value"]["description"])
        self.assertIn("partially_in_scope", by["cbam_scope"]["description"])
        for t in tools:
            self.assertEqual(t["inputSchema"]["type"], "object")
            self.assertTrue(t["annotations"]["readOnlyHint"])

    def test_call_returns_text_and_structured_content(self):
        r = call("cbam_scope", {"cn_code": "7208 51 20"})["result"]
        self.assertFalse(r["isError"])
        self.assertEqual(r["structuredContent"]["status"], "in_scope")
        self.assertEqual(json.loads(r["content"][0]["text"]), r["structuredContent"])

    def test_tool_errors_are_results(self):
        cases = [("cbam_scope", {"cn_code": "72O8"}, "digits"),
                 ("default_value", {"cn_code": "7601"}, "bad arguments"),
                 ("default_value", {"cn_code": "7601", "country": "Indai"}, "did you mean"),
                 ("cn_describe", {"cn_code": "2716", "year": 1999}, "2025 or 2026"),
                 ("cbam_scope", {"cn_code": "7208", "colour": "red"}, "bad arguments")]
        for name, args, expected in cases:
            r = call(name, args)["result"]
            self.assertTrue(r["isError"], name)
            self.assertIn(expected, r["content"][0]["text"])
        r = mcp_stdio.handle({"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": "sources", "arguments": [1]}})
        self.assertTrue(r["result"]["isError"])

    def test_missing_data_is_an_error_result(self):
        with DataEnv(Path(tempfile.mkdtemp())):
            r = call("sources")["result"]
        self.assertTrue(r["isError"])
        self.assertIn("data unavailable", r["content"][0]["text"])

    def test_protocol_errors(self):
        self.assertEqual(call("no_such_tool")["error"]["code"], -32602)
        self.assertEqual(mcp_stdio.handle({"jsonrpc": "2.0", "id": 2, "method": "resources/list"})["error"]["code"], -32601)
        self.assertEqual(mcp_stdio.handle([1, 2])["error"]["code"], -32600)
        self.assertEqual(mcp_stdio.handle({"jsonrpc": "2.0", "id": 3})["error"]["code"], -32600)
        self.assertIsNone(mcp_stdio.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        self.assertIsNone(mcp_stdio.handle({"jsonrpc": "2.0", "method": "tools/list"}))
        self.assertEqual(mcp_stdio.handle({"jsonrpc": "2.0", "id": 4, "method": "ping"})["result"], {})


class EndToEnd(unittest.TestCase):
    def test_session_over_stdio(self):
        home = tempfile.mkdtemp(prefix="cbam-mcp-home-")
        env = {k: v for k, v in os.environ.items() if not k.startswith(("CBAM_MCP", "PYTHON"))}
        env.update({"HOME": home, "USERPROFILE": home, "CBAM_MCP_DATA_DIR": str(shared_data_dir()),
                    "PYTHONPATH": str(ROOT), "PYTHONIOENCODING": "latin-1"})
        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "compare_origins", "arguments": {"cn_code": "7601 10 00", "countries": ["India", "Türkiye"]}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "cbam_scope", "arguments": {"cn_code": "abc"}}},
            {"jsonrpc": "2.0", "id": 5, "method": "prompts/list"},
        ]
        stdin = "\n".join(json.dumps(m, ensure_ascii=False) for m in messages) + "\n{not json\n\n"
        proc = subprocess.run([sys.executable, "-m", "cbam_mcp"], input=stdin.encode("utf-8"), capture_output=True,
                              cwd=home, env=env, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))
        self.assertEqual(proc.stderr, b"")
        replies = [json.loads(line) for line in proc.stdout.decode("utf-8").splitlines()]
        by_id = {r["id"]: r for r in replies}
        self.assertEqual(len(replies), 6)  # five requests with an id, one parse error, no reply to the notification
        self.assertEqual(by_id[1]["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(len(by_id[2]["result"]["tools"]), 5)
        lines = by_id[3]["result"]["structuredContent"]["lines"][0]["by_country"]
        self.assertEqual([(c["country"], c["total"]) for c in lines], [("India", 1.87), ("Türkiye", 1.7)])
        self.assertTrue(by_id[4]["result"]["isError"])
        self.assertEqual(by_id[5]["error"]["code"], -32601)
        self.assertEqual(by_id[None]["error"]["code"], -32700)
        self.assertEqual(os.listdir(home), [])  # nothing written to, or needed from, the home directory


if __name__ == "__main__":
    unittest.main()
