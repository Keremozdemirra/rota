"""The MCP server end to end: a real subprocess, JSON-RPC over stdin/stdout, HOME in a temp dir."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

from support import ROOT

EXAMPLE = json.loads((ROOT / "examples" / "fictional-eu-manufacturer.json").read_text(encoding="utf-8"))


def session(*messages: str) -> list[dict]:
    with tempfile.TemporaryDirectory() as home:
        env = {**os.environ, "HOME": home, "USERPROFILE": home, "APPDATA": home, "XDG_CONFIG_HOME": home,
               "PYTHONIOENCODING": "utf-8"}
        proc = subprocess.run([sys.executable, str(ROOT / "csrd_scope_mcp.py")], input="\n".join(messages) + "\n",
                              capture_output=True, text=True, encoding="utf-8", timeout=60, cwd=home, env=env)
    assert proc.returncode == 0, proc.stderr
    assert proc.stderr == "", proc.stderr
    return [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]


def msg(id_, method, params=None) -> str:
    m = {"jsonrpc": "2.0", "method": method}
    if id_ is not None:
        m["id"] = id_
    if params is not None:
        m["params"] = params
    return json.dumps(m)


class McpStdio(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = session(
            msg(1, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}),
            msg(None, "notifications/initialized"),
            msg(2, "tools/list"),
            msg(3, "tools/call", {"name": "csrd_scope", "arguments": EXAMPLE}),
            msg(4, "tools/call", {"name": "csrd_scope", "arguments": {**EXAMPLE, "currency": "USD"}}),
            msg(5, "tools/call", {"name": "no_such_tool", "arguments": {}}),
            msg(6, "resources/list"),
            "{not json",
            json.dumps([{"jsonrpc": "2.0", "id": 7, "method": "ping"}]),
            msg(8, "tools/call", {"name": "csrd_scope", "arguments": ["not", "an", "object"]}),
            msg(9, "tools/call", {"name": "thresholds", "arguments": {}}),
            msg(10, "tools/call", {"name": "timeline"}),
            msg(11, "tools/call", {"name": "sources", "arguments": {"member_state": "FI"}}),
            msg(12, "tools/call", {"name": "sources", "arguments": {"member_state": "Narnia"}}),
            msg(13, "tools/call", {"name": "thresholds", "arguments": {"extra": 1}}),
            msg(14, "ping"),
        )
        cls.by_id = {m.get("id"): m for m in cls.out if m.get("id") is not None}

    def test_notifications_get_no_reply(self):
        # 16 messages sent; the notification gets no reply, everything else exactly one.
        self.assertEqual(len(self.out), 15)

    def test_initialize(self):
        r = self.by_id[1]["result"]
        self.assertEqual(r["protocolVersion"], "2025-06-18")
        self.assertEqual(r["serverInfo"]["name"], "csrd-scope")
        self.assertIn("tools", r["capabilities"])

    def test_tools_list_describes_units_and_limits(self):
        tools = {t["name"]: t for t in self.by_id[2]["result"]["tools"]}
        self.assertEqual(set(tools), {"csrd_scope", "thresholds", "timeline", "sources"})
        d = tools["csrd_scope"]["description"]
        for fragment in ("EUR only", "never converted", "questions_for_counsel", "not legal advice", "legal_basis_version"):
            self.assertIn(fragment, d)
        self.assertEqual(tools["csrd_scope"]["inputSchema"]["required"], ["currency", "eu_undertaking", "financial_years"])

    def test_call_returns_text_and_structured_content(self):
        r = self.by_id[3]["result"]
        self.assertFalse(r["isError"])
        sc = r["structuredContent"]
        self.assertEqual(sc["in_scope"], "yes")
        self.assertEqual(sc["first_reporting_financial_year"]["financial_year"], "FY2027")
        self.assertEqual(json.loads(r["content"][0]["text"]), sc)

    def test_bad_input_is_an_error_result(self):
        r = self.by_id[4]["result"]
        self.assertTrue(r["isError"])
        self.assertIn("never converts", r["content"][0]["text"])
        self.assertTrue(self.by_id[8]["result"]["isError"])
        self.assertTrue(self.by_id[12]["result"]["isError"])
        self.assertTrue(self.by_id[13]["result"]["isError"])

    def test_protocol_errors(self):
        self.assertEqual(self.by_id[5]["error"]["code"], -32602)
        self.assertEqual(self.by_id[6]["error"]["code"], -32601)
        codes = [m["error"]["code"] for m in self.out if m.get("id") is None and "error" in m]
        self.assertEqual(sorted(codes), [-32700, -32600])

    def test_reference_tools(self):
        self.assertFalse(self.by_id[9]["result"]["isError"])
        self.assertIn("thresholds", self.by_id[9]["result"]["structuredContent"])
        self.assertIn("reporting", self.by_id[10]["result"]["structuredContent"])
        fi = self.by_id[11]["result"]["structuredContent"]["national_law"]
        self.assertEqual(fi["member_state"], "FI")
        self.assertEqual(self.by_id[14]["result"], {})


if __name__ == "__main__":
    unittest.main()
