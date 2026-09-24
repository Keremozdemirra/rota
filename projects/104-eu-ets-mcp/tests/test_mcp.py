"""The MCP server end to end: a real process, JSON-RPC over stdin and stdout."""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _support import PLACEHOLDERS, ROOT, Isolated, build_fixture_db  # noqa: E402


def converse(messages, *cmd):
    lines = [m if isinstance(m, str) else json.dumps(m, ensure_ascii=False) for m in messages]
    proc = subprocess.run([sys.executable, *cmd], input="\n".join(lines) + "\n", capture_output=True, timeout=120,
                          cwd=str(ROOT), env=dict(os.environ, PYTHONIOENCODING="utf-8"), encoding="utf-8")
    replies = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    return replies, proc


def call(id_, name, arguments):
    return {"jsonrpc": "2.0", "id": id_, "method": "tools/call", "params": {"name": name, "arguments": arguments}}


class McpTest(unittest.TestCase):
    def setUp(self):
        self.env = Isolated().__enter__()
        build_fixture_db(self.env.cache)

    def tearDown(self):
        self.env.__exit__()

    def test_session(self):
        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            call(3, "search_installations", {"query": "hüttenwerk duisburg"}),
            call(4, "installation_history", {"installation_id": "69", "country": "DE", "from_year": 2020}),
            call(5, "company_by_lei", {"lei": "5299-00FGOWZKLBZ81V-67"}),
            call(6, "top_emitters", {"country": "DE", "activity": 24, "limit": 5}),
            call(7, "dataset_info", {}),
            call(8, "top_emitters", {"limit": 0}),
            call(9, "top_emitters", {"countries": "DE"}),
            call(10, "company_by_lei", {}),
            {"jsonrpc": "2.0", "id": 11, "method": "tools/call", "params": {"name": "top_emitters", "arguments": ["DE"]}},
            call(12, "no_such_tool", {}),
            {"jsonrpc": "2.0", "id": 13, "method": "resources/list"},
            "{this is not json",
            {"jsonrpc": "2.0", "id": 14, "method": "ping"},
            [{"jsonrpc": "2.0", "id": 15, "method": "ping"}],
            {"jsonrpc": "2.0", "id": 16, "method": "tools/list", "params": "x"},
        ]
        replies, proc = converse(messages, "eu_ets_mcp.py")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stderr, "")
        by = {r.get("id"): r for r in replies}
        self.assertEqual(len(replies), 17)  # every message but the notification gets exactly one reply
        init = by[1]["result"]
        self.assertEqual((init["protocolVersion"], init["serverInfo"]["name"]), ("2025-06-18", "eu-ets-mcp"))
        tools = by[2]["result"]["tools"]
        self.assertEqual([t["name"] for t in tools], ["search_installations", "installation_history", "company_by_lei",
                                                      "top_emitters", "dataset_info"])
        for t in tools:
            self.assertGreater(len(t["description"]), 150)
            self.assertEqual(t["inputSchema"]["type"], "object")
        for i in (3, 4, 5, 6, 7):
            res = by[i]["result"]
            self.assertFalse(res["isError"], res)
            self.assertEqual(json.loads(res["content"][0]["text"]), res["structuredContent"])
            self.assertIn("CC BY 4.0", res["structuredContent"]["source"])
            for p in PLACEHOLDERS:
                self.assertNotIn(p, res["content"][0]["text"])
        self.assertEqual(by[3]["result"]["structuredContent"]["installations"][0]["name"], "Integriertes Hüttenwerk Duisburg")
        self.assertEqual(by[4]["result"]["structuredContent"]["installation"]["installation_id"], 69)
        self.assertEqual(by[5]["result"]["structuredContent"]["installations_count"], 3)
        self.assertEqual(by[6]["result"]["structuredContent"]["installations"][0]["rank"], 1)
        for i, msg in ((8, "between 1 and 100"), (9, "unknown argument"), (10, "missing argument"), (11, "must be an object")):
            self.assertTrue(by[i]["result"]["isError"], i)
            self.assertIn(msg, by[i]["result"]["content"][0]["text"])
        self.assertEqual(by[12]["error"]["code"], -32602)
        self.assertEqual(by[13]["error"]["code"], -32601)
        # the unparseable line, then the batch (MCP 2025-06-18 has no JSON-RPC batching)
        self.assertEqual([r["error"]["code"] for r in replies if r.get("id") is None], [-32700, -32600])
        self.assertEqual(by[14]["result"], {})
        self.assertEqual(by[16]["error"]["code"], -32602)

    def test_serve_subcommand_and_missing_data(self):
        os.environ["EU_ETS_CACHE_DIR"] = str(self.env.path / "empty")
        replies, proc = converse([call(1, "dataset_info", {}), call(2, "search_installations", {"query": "x"})],
                                 "eu_ets.py", "serve")
        self.assertEqual(proc.returncode, 0)
        for r in replies:
            self.assertTrue(r["result"]["isError"])
            self.assertIn("eu-ets refresh", r["result"]["content"][0]["text"])
        self.assertEqual(proc.stderr, "")


if __name__ == "__main__":
    unittest.main()
