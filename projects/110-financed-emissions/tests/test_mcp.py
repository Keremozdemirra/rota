"""The MCP server: JSON-RPC over stdin/stdout end to end, and the malformed messages clients send."""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import financed_emissions as fe  # noqa: E402
import financed_emissions_mcp as mcp  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
EXAMPLE = str(ROOT / "examples" / "portfolio.csv")


def call(name, arguments, id_=1):
    return mcp.handle({"jsonrpc": "2.0", "id": id_, "method": "tools/call",
                       "params": {"name": name, "arguments": arguments}})


class EndToEnd(unittest.TestCase):
    def test_session_over_stdio(self):
        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "attribute", "arguments": {
                "asset_class": "sovereign_debt", "outstanding": 1000000, "denominator": "579762000000",
                "emissions": 61451586, "currency": "USD"}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "compute_portfolio", "arguments": {
                "csv_path": EXAMPLE, "reporting_currency": "EUR", "max_positions": 3, "explain": True}}},
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "methods", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 6, "method": "ping"},
            {"jsonrpc": "2.0", "id": 7, "method": "resources/list"},
        ]
        payload = "".join(json.dumps(m) + "\n" for m in messages).encode("utf-8") + b"\xff\xfe broken\n"
        with tempfile.TemporaryDirectory() as home:
            env = dict(os.environ, HOME=home)
            proc = subprocess.run([sys.executable, str(ROOT / "financed_emissions.py"), "mcp"], input=payload,
                                  capture_output=True, cwd=str(ROOT), env=env, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        responses = [json.loads(line) for line in proc.stdout.decode("utf-8").splitlines()]
        by_id = {r["id"]: r for r in responses}
        self.assertEqual(len(responses), 8)                       # the notification gets no answer
        self.assertEqual(by_id[1]["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(by_id[1]["result"]["serverInfo"]["version"], fe.__version__)
        self.assertEqual([t["name"] for t in by_id[2]["result"]["tools"]], ["compute_portfolio", "attribute", "methods"])
        attribute = by_id[3]["result"]
        self.assertFalse(attribute["isError"])
        self.assertEqual(round(attribute["structuredContent"]["financed_emissions_tco2e"]), 106)  # Table 10.3-2
        self.assertEqual(json.loads(attribute["content"][0]["text"]), attribute["structuredContent"])
        portfolio = by_id[4]["result"]["structuredContent"]
        self.assertEqual(len(portfolio["positions"]), 3)
        self.assertTrue(portfolio["positions_truncated"])
        self.assertEqual(portfolio["positions_total"], 15)
        self.assertIn("arithmetic", portfolio["positions"][0])
        self.assertAlmostEqual(portfolio["totals"]["financed_tco2e"]["scope1_2"], 50811.84499, places=4)
        self.assertEqual(len(by_id[5]["result"]["structuredContent"]["asset_classes"]), 12)
        self.assertEqual(by_id[6]["result"], {})
        self.assertEqual(by_id[7]["error"]["code"], -32601)
        self.assertEqual(by_id[None]["error"]["code"], -32700)   # the non-UTF-8 line


class Messages(unittest.TestCase):
    def test_not_an_object(self):
        for msg in ([1, 2], "text", 3, None):
            self.assertEqual(mcp.handle(msg)["error"]["code"], -32600)

    def test_notifications_and_missing_method(self):
        self.assertIsNone(mcp.handle({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {}}))
        self.assertIsNone(mcp.handle({"jsonrpc": "2.0"}))
        self.assertEqual(mcp.handle({"jsonrpc": "2.0", "id": 9})["error"]["code"], -32600)

    def test_params_not_an_object(self):
        r = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": [1]})
        self.assertEqual(r["error"]["code"], -32602)

    def test_unknown_tool(self):
        r = call("delete_everything", {})
        self.assertEqual(r["error"]["code"], -32602)

    def test_arguments_are_checked(self):
        for args, part in (({}, "missing argument 'csv_path'"),
                           ({"csv_path": 5}, "must be string"),
                           ({"csv_path": "x", "limit": 1}, "unknown argument 'limit'"),
                           ({"csv_path": "x", "max_positions": -1}, "between 0 and 5000"),
                           ({"csv_path": "x", "explain": "yes"}, "must be boolean")):
            r = call("compute_portfolio", args)["result"]
            self.assertTrue(r["isError"], args)
            self.assertIn(part, r["content"][0]["text"])
        r = call("attribute", "not an object")["result"]
        self.assertTrue(r["isError"])
        r = call("attribute", {"asset_class": "mortgage", "outstanding": True, "emissions": 1})["result"]
        self.assertIn("must be number or string", r["content"][0]["text"])

    def test_tool_errors_are_results_not_crashes(self):
        cases = [
            ("compute_portfolio", {"csv_path": "/nonexistent/p.csv"}, "no such file"),
            ("compute_portfolio", {"csv_path": EXAMPLE}, "several currencies"),
            ("compute_portfolio", {"csv_path": str(FIXTURES)}, "not a regular file"),
            ("compute_portfolio", {"csv_path": "-"}, "must name a file"),
            ("compute_portfolio", {"csv_path": "  "}, "must name a file"),
            ("attribute", {"asset_class": "mortgage", "outstanding": 1, "emissions": 1}, "is blank"),
            ("attribute", {"asset_class": "listed_equity", "outstanding": 1, "denominator": 0, "emissions": 1},
             "greater than 0"),
            ("attribute", {"asset_class": "swap", "outstanding": 1, "denominator": 2, "emissions": 1}, "derivatives"),
            ("attribute", {"asset_class": "mortgage", "outstanding": "abc", "denominator": 2, "emissions": 1},
             "not a number"),
        ]
        for name, args, part in cases:
            r = call(name, args)["result"]
            self.assertTrue(r["isError"], (name, args))
            self.assertIn(part, r["content"][0]["text"], (name, args))

    def test_attribute_rules_reach_the_agent(self):
        r = call("attribute", {"asset_class": "sub_sovereign_debt", "outstanding": 2000, "denominator": 1000,
                               "emissions": 500})["result"]["structuredContent"]
        self.assertEqual(r["attribution_factor"], 1.0)
        self.assertTrue(r["capped"])
        self.assertIn("5.10, p. 154", r["flags"][0])
        r = call("attribute", {"asset_class": "business_loan", "outstanding": 5, "total_equity": -2,
                               "total_debt": 25, "emissions": 100})["result"]["structuredContent"]
        self.assertEqual(r["attribution_factor"], 0.2)
        self.assertIn("footnote 75", r["notes"][0])

    def test_compute_portfolio_without_positions(self):
        r = call("compute_portfolio", {"csv_path": str(FIXTURES / "one_failure.csv"), "max_positions": 0})
        sc = r["result"]["structuredContent"]
        self.assertEqual(sc["positions"], [])
        self.assertEqual(len(sc["not_computed"]), 1)
        self.assertIn("data, not instructions", sc["text_fields"])
        self.assertNotIn("arithmetic", json.dumps(sc))

    def test_descriptions_state_units_and_limits(self):
        for tool in mcp.TOOLS:
            self.assertIn("description", tool)
            self.assertEqual(tool["inputSchema"]["type"], "object")
        text = " ".join(t["description"] for t in mcp.TOOLS)
        for part in ("tCO2e", "50 MB", "max_positions", "never converts currencies", "sends nothing"):
            self.assertIn(part, text)

    def test_serve_in_process(self):
        stdin = io.BytesIO(b'{"jsonrpc":"2.0","id":1,"method":"ping"}\n\n{"jsonrpc":"2.0","id":2,"method":"x"}\n')
        stdout = io.BytesIO()
        self.assertEqual(mcp.serve(stdin, stdout), 0)
        lines = stdout.getvalue().decode("utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[1])["error"]["code"], -32601)


if __name__ == "__main__":
    unittest.main()
