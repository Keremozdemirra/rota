"""The MCP protocol end to end: a real server process spoken to over stdin and stdout."""
import io
import json
import os
import subprocess
import sys

from support import IG3, MAPPING, ROOT, Isolated

from esrs_datapoints_mcp.mcp import TOOLS, Server, validate
from esrs_datapoints_mcp.store import Store
from esrs_datapoints_mcp.tools import Service


def talk(messages, env):
    lines = "\n".join(m if isinstance(m, str) else json.dumps(m) for m in messages) + "\n"
    proc = subprocess.run([sys.executable, "-m", "esrs_datapoints_mcp"], input=lines.encode("utf-8"),
                          capture_output=True, env=env, cwd=str(ROOT), timeout=60)
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    return [json.loads(line) for line in proc.stdout.decode("utf-8").splitlines() if line.strip()]


class Stdio(Isolated):
    def env(self, files):
        env = dict(os.environ)
        env.update({"PYTHONPATH": str(ROOT), "ESRS_DATAPOINTS_XLSX": os.pathsep.join(str(f) for f in files),
                    "PYTHONIOENCODING": "ascii"})
        return env

    def test_session(self):
        out = talk([
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "search", "arguments": {"text": "scope 3", "standard": "E1"}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
             "params": {"name": "datapoint", "arguments": {"id": "E1-9_02"}}},
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
             "params": {"name": "diff_versions", "arguments": {"standard": "E1"}}},
            {"jsonrpc": "2.0", "id": 6, "method": "tools/call",
             "params": {"name": "search", "arguments": {"text": "x", "limit": "ten"}}},
            {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "nope", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 8, "method": "resources/list"},
            "{not json",
            [1, 2],
            {"jsonrpc": "2.0", "id": 9, "method": "ping"},
        ], self.env([IG3, MAPPING]))
        by_id = {m.get("id"): m for m in out}
        self.assertEqual(by_id[1]["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(by_id[1]["result"]["serverInfo"]["name"], "esrs-datapoints-mcp")
        self.assertEqual([t["name"] for t in by_id[2]["result"]["tools"]],
                         ["index_status", "search", "datapoint", "disclosure_requirement", "diff_versions", "sources"])
        res = by_id[3]["result"]
        self.assertFalse(res["isError"])
        self.assertEqual(res["structuredContent"]["matches"], 3)
        self.assertEqual(json.loads(res["content"][0]["text"]), res["structuredContent"])
        dp = by_id[4]["result"]["structuredContent"]["datapoints"][0]
        self.assertIn("résumé", dp["name"])  # UTF-8 on the wire whatever the locale says
        self.assertEqual(by_id[5]["result"]["structuredContent"]["summary"]["added"], 1)
        self.assertTrue(by_id[6]["result"]["isError"])
        self.assertIn("limit must be an integer", by_id[6]["result"]["content"][0]["text"])
        self.assertEqual(by_id[7]["error"]["code"], -32602)
        self.assertEqual(by_id[8]["error"]["code"], -32601)
        self.assertEqual(by_id[9]["result"], {})
        codes = [m["error"]["code"] for m in out if m.get("id") is None and "error" in m]
        self.assertEqual(codes, [-32700, -32600])
        self.assertNotIn(None, [m.get("jsonrpc") for m in out])

    def test_no_workbook_is_an_error_result_with_directions(self):
        out = talk([{"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                     "params": {"name": "search", "arguments": {"text": "scope"}}},
                    {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                     "params": {"name": "index_status", "arguments": {}}},
                    {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "sources"}}],
                   self.env([self.tmp / "not-downloaded-yet.xlsx"]))
        self.assertTrue(out[0]["result"]["isError"])
        self.assertIn("efrag.org", out[0]["result"]["content"][0]["text"])
        status = out[1]["result"]["structuredContent"]
        self.assertFalse(out[1]["result"]["isError"])
        self.assertIn("No file at", status["problems"][0]["error"])
        self.assertFalse(out[2]["result"]["isError"])


class InProcess(Isolated):
    def test_every_tool_schema_rejects_unknown_arguments(self):
        for tool in TOOLS:
            args = {k: "x" for k in tool["inputSchema"].get("required", [])}
            self.assertIn("unknown argument", validate(tool["inputSchema"], {**args, "bogus": 1}), tool["name"])
            self.assertLess(len(tool["description"]), 1500)
        self.assertIn("missing required", validate(TOOLS[2]["inputSchema"], {}))
        self.assertIn("between", validate(TOOLS[1]["inputSchema"], {"limit": 500}))
        self.assertIn("boolean", validate(TOOLS[1]["inputSchema"], {"voluntary": "true"}))
        self.assertIsNone(validate(TOOLS[1]["inputSchema"], {"text": "x", "voluntary": None}))

    def test_unexpected_exception_becomes_an_error_result(self):
        buf = io.StringIO()
        svc = Service(Store(self.cache), env_value=str(IG3))
        server = Server(svc, out=buf)
        server.handlers["search"] = lambda **kw: 1 / 0
        server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": "search", "arguments": {"text": "x"}}})
        reply = json.loads(buf.getvalue())
        self.assertTrue(reply["result"]["isError"])
        self.assertIn("ZeroDivisionError", reply["result"]["content"][0]["text"])
