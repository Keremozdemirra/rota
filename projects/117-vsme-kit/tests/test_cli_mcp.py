"""The command line (formats, exit codes) and the MCP server end to end over stdin/stdout."""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import ROOT, Isolated  # noqa: E402

from vsme_kit import mcp  # noqa: E402


class Cli(Isolated):
    def test_strict_exit_codes(self):
        clean = self.book("clean.xlsx")
        broken = self.book("broken.xlsx", overrides={"TotalGrossLocationBasedScope1AndScope2GHGEmissions": 999})
        self.assertEqual(self.run_cli(["check", clean, "--strict"])[0], 0)
        self.assertEqual(self.run_cli(["check", broken, "--strict"])[0], 1)
        self.assertEqual(self.run_cli(["check", broken])[0], 0)  # without --strict findings do not fail
        code, _, err = self.run_cli(["check", self.tmp / "typo.xlsx", "--strict"])
        self.assertEqual(code, 2)
        self.assertIn("no such file", err)
        self.assertNotIn("Traceback", err)

    def test_formats(self):
        path = self.book(overrides={"PercentageOfEmployeesCoveredByCollectiveBargainingAgreements": 1.25})
        code, out, _ = self.run_cli(["check", path, "--json"])
        report = json.loads(out)
        self.assertEqual(report["summary"]["inconsistent"], 1)
        code, md, _ = self.run_cli(["check", path, "--markdown"])
        self.assertIn("| code | disclosure | status | details |", md)
        self.assertIn("125 %", md)
        code, text, _ = self.run_cli(["check", path])
        self.assertIn("B10: employees covered by collective bargaining: 125 %", text)
        self.assertIn("not assurance", text)

    def test_lookup_commands(self):
        code, out, _ = self.run_cli(["disclosure", "B3", "--json"])
        self.assertEqual(json.loads(out)["paragraphs"][0]["n"], "32")
        code, out, _ = self.run_cli(["disclosures", "--module", "basic", "--edition", "2025", "--markdown"])
        self.assertIn("| B11 | Convictions and fines for corruption and bribery | 43 |", out)
        code, _, err = self.run_cli(["disclosure", "Z9"])
        self.assertEqual(code, 2)
        self.assertIn("unknown disclosure", err)

    def test_unicode_paths_and_values(self):
        path = self.book("rapport-énergie-ü.xlsx", overrides={"TotalEnergyConsumption": "1 250 MWh ≈"})
        code, out, _ = self.run_cli(["check", path, "--json"])
        self.assertEqual(code, 0)
        self.assertIn("number stored as text", out)


class McpStdio(Isolated):
    def test_protocol_end_to_end(self):
        path = self.book(overrides={"TotalEnergyConsumption": 900})
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "disclosure", "arguments": {"code": "B3", "edition": "2025"}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "check_template", "arguments": {"path": str(path)}}},
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "disclosure", "arguments": {"code": "X1"}}},
            {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "nope", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 7, "method": "resources/list"},
            {"jsonrpc": "2.0", "id": 8, "method": "tools/call", "params": {"name": "check_template", "arguments": {"path": str(self.tmp / "missing.xlsx")}}},
            {"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": "vsme_disclosures", "arguments": {"bogus": 1}}},
            # review item 6: a notification (no id) gets no response, even for tools/call
            {"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "editions", "arguments": {}}},
        ]
        stdin = "\n".join(json.dumps(r) for r in requests) + "\nnot json\n"
        env = dict(os.environ, PYTHONPATH=str(ROOT), HOME=str(self.tmp))
        proc = subprocess.run([sys.executable, "-m", "vsme_kit", "mcp"], input=stdin.encode(), capture_output=True,
                              env=env, cwd=str(self.tmp), timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        replies = [json.loads(line) for line in proc.stdout.decode().splitlines()]
        by_id = {r.get("id"): r for r in replies}
        self.assertEqual(by_id[1]["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual({t["name"] for t in by_id[2]["result"]["tools"]},
                         {"vsme_disclosures", "disclosure", "check_template", "editions"})
        b3 = by_id[3]["result"]
        self.assertFalse(b3["isError"])
        self.assertEqual(b3["structuredContent"]["paragraphs"][0]["n"], "29")
        self.assertEqual(json.loads(b3["content"][0]["text"])["code"], "B3")
        report = by_id[4]["result"]["structuredContent"]
        self.assertEqual({d["code"]: d["status"] for d in report["disclosures"]}["B3"], "inconsistent")
        self.assertTrue(by_id[5]["result"]["isError"])
        self.assertEqual(by_id[6]["error"]["code"], -32602)
        self.assertEqual(by_id[7]["error"]["code"], -32601)
        self.assertTrue(by_id[8]["result"]["isError"])
        self.assertIn("no such file", by_id[8]["result"]["content"][0]["text"])
        self.assertTrue(by_id[9]["result"]["isError"])
        self.assertEqual(replies[-1]["error"]["code"], -32700)
        self.assertNotIn(None, [r.get("jsonrpc") for r in replies])
        self.assertEqual([r.get("id") for r in replies], [1, 2, 3, 4, 5, 6, 7, 8, 9, None])  # None: the parse error only

    def test_tool_descriptions_state_returns_units_and_limits(self):
        text = " ".join(t["description"] for t in mcp.TOOLS)
        for needed in ("MWh", "tCO2eq", "fractions (0.25 = 25 %)", "1.0.0-1.3.0", "not reproduced", "Not assurance",
                       "Delegated Regulation (EU) 2026/1560", "depends"):
            self.assertIn(needed, text)


if __name__ == "__main__":
    unittest.main()
