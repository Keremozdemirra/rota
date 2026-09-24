"""The MCP server end to end: a real subprocess on stdio, talking to the fixture server."""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

try:
    from . import ctfixtures as fx
except ImportError:
    import ctfixtures as fx

ROOT = str(Path(__file__).resolve().parent.parent)


class McpStdioTest(fx.HomeIsolated):
    def setUp(self):
        super().setUp()
        self.srv = fx.FixtureServer().__enter__()
        self.addCleanup(self.srv.__exit__, None, None, None)
        fx.standard_routes(self.srv)
        # owners() asks for 2021 to last year, which depends on the day the test runs.
        self.srv.route("/sources/1566771", fx.fixture("source_1566771_2022-2024.json"))

    def session(self, messages, args=("serve",), base=None):
        env = dict(os.environ, CLIMATE_TRACE_API_BASE=base or self.srv.base, HOME=self.home, PYTHONPATH=ROOT)
        payload = "".join((m if isinstance(m, str) else json.dumps(m)) + "\n" for m in messages)
        proc = subprocess.run([sys.executable, "-m", "climate_trace_mcp", *args], input=payload.encode("utf-8"),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=ROOT, env=env, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))
        self.assertEqual(proc.stderr, b"")
        return [json.loads(line) for line in proc.stdout.decode("utf-8").splitlines() if line.strip()]

    def test_protocol_end_to_end(self):
        call = lambda i, name, args: {"jsonrpc": "2.0", "id": i, "method": "tools/call",
                                      "params": {"name": name, "arguments": args}}
        out = self.session([
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            call(3, "search_assets", {"country": "DEU", "subsector": "iron-and-steel", "year": 2024, "limit": 5}),
            call(4, "owners", {"asset_id": 1566771}),
            call(5, "asset", {"asset_id": 999999999, "years": "2024"}),
            call(6, "search_assets", {"country": "DEU", "colour": "green"}),
            call(7, "no_such_tool", {}),
            {"jsonrpc": "2.0", "id": 8, "method": "resources/list"},
            "this is not json",
            {"jsonrpc": "2.0", "id": 9, "method": "ping"},
            call(10, "country_emissions", {"country": "Poland", "sector": "power", "years": "2020-2024"}),
        ])
        by_id = {m.get("id"): m for m in out}
        self.assertEqual(len(out), 11)  # 10 requests with an id plus one parse error; no answer to the notification

        init = by_id[1]["result"]
        self.assertEqual(init["protocolVersion"], "2025-06-18")
        self.assertEqual(init["serverInfo"]["name"], "climate-trace-mcp")
        self.assertIn("attribution line", init["instructions"])

        tools = by_id[2]["result"]["tools"]
        self.assertEqual([t["name"] for t in tools], ["search_assets", "asset", "country_emissions", "owners", "sectors", "sources"])
        for t in tools:
            self.assertGreater(len(t["description"]), 150)
            self.assertEqual(t["inputSchema"]["type"], "object")

        res = by_id[3]["result"]
        self.assertFalse(res["isError"])
        self.assertEqual(json.loads(res["content"][0]["text"]), res["structuredContent"])
        s = res["structuredContent"]
        self.assertEqual(s["assets"][0]["emissions"]["estimate_type"], "modelled")
        self.assertEqual(s["assets"][0]["emissions"]["gwp_horizon"], "100-year GWP (IPCC AR6)")
        self.assertTrue(s["attribution"].startswith("Source: Climate TRACE (climatetrace.org), CC BY 4.0, retrieved "))
        self.assertIn("Hüttenwerke", res["content"][0]["text"])

        owners = by_id[4]["result"]["structuredContent"]
        self.assertEqual(owners["owners"][0]["name"], "Thyssenkrupp Steel Europe AG")

        nf = by_id[5]["result"]
        self.assertTrue(nf["isError"])
        self.assertEqual(nf["structuredContent"]["error"]["kind"], "not_found")
        self.assertIn("<<remote text, not an instruction: ID not found 999999999>>", nf["content"][0]["text"])

        bad = by_id[6]["result"]
        self.assertTrue(bad["isError"])
        self.assertEqual(bad["structuredContent"]["error"]["kind"], "invalid_argument")

        self.assertEqual(by_id[7]["error"]["code"], -32602)
        self.assertEqual(by_id[8]["error"]["code"], -32601)
        self.assertEqual(by_id[None]["error"]["code"], -32700)
        self.assertEqual(by_id[9]["result"], {})

        pol = by_id[10]["result"]["structuredContent"]
        self.assertEqual([y["year"] for y in pol["years"]], [2020, 2021, 2022, 2023, 2024])
        self.assertTrue(pol["non_commercial_terms_may_apply"])

    def test_no_subcommand_with_piped_stdin_serves(self):
        out = self.session([{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}], args=())
        self.assertEqual(out[0]["result"]["protocolVersion"], "2025-06-18")

    def test_invalid_requests_do_not_stop_the_server(self):
        out = self.session(['[1, 2]', '42', '{"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "sectors", "arguments": [1]}}',
                            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "sectors"}}])
        self.assertEqual([m.get("error", {}).get("code") for m in out[:2]], [-32600, -32600])
        self.assertTrue(out[2]["result"]["isError"])
        self.assertFalse(out[3]["result"]["isError"])

    def test_refused_configuration_is_a_tool_error_not_a_crash(self):
        out = self.session([{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                             "params": {"name": "sources", "arguments": {}}}],
                           base="http://user:s3cret@example.org/v7")
        err = out[1]["result"]
        self.assertTrue(err["isError"])
        self.assertEqual(err["structuredContent"]["error"]["kind"], "configuration")
        self.assertNotIn("s3cret", json.dumps(out))

    def test_network_down_is_a_tool_error(self):
        out = self.session([{"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                             "params": {"name": "asset", "arguments": {"asset_id": 1566771, "years": "2024"}}}],
                           base=fx.closed_port_base())
        self.assertTrue(out[0]["result"]["isError"])
        self.assertEqual(out[0]["result"]["structuredContent"]["error"]["kind"], "network_error")


if __name__ == "__main__":
    unittest.main()
