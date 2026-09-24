"""The MCP server, end to end over stdin and stdout, as a client would run it."""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import FIXTURES, ROOT, Case  # noqa: E402


class Stdio(Case):
    def session(self, *messages):
        env = dict(os.environ, HOME=str(self.home))
        lines = "".join((m if isinstance(m, str) else json.dumps(m)) + "\n" for m in messages)
        proc = subprocess.run([sys.executable, str(ROOT / "xlsx_review.py"), "mcp"], input=lines.encode("utf-8"),
                              capture_output=True, env=env, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        msgs = [json.loads(x) for x in proc.stdout.decode("utf-8").splitlines()]
        self.unaddressed = [m for m in msgs if m.get("id") is None]
        return {m.get("id"): m for m in msgs}

    def call(self, i, name, arguments):
        return {"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": name, "arguments": arguments}}

    def test_protocol(self):
        out = self.session(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            self.call(3, "diff_workbooks", {"before_path": str(FIXTURES / "budget_before.xlsx"),
                                            "after_path": str(FIXTURES / "budget_after.xlsx"), "limit": 5}),
            self.call(4, "check_workbook", {"path": str(FIXTURES / "budget_after.xlsx")}),
            self.call(5, "explain_cell", {"path": str(FIXTURES / "excel_shared_formulas.xlsx"), "sheet": "calc", "cell": "$C$6"}),
            self.call(6, "check_workbook", {"path": str(self.tmp / "missing.xlsx")}),
            self.call(7, "check_workbook", {"path": 42}),
            self.call(8, "explain_cell", {"path": str(FIXTURES / "budget_before.xlsx"), "sheet": "Model", "cell": "A0"}),
            self.call(9, "nope", {}),
            {"jsonrpc": "2.0", "id": 10, "method": "resources/list"},
            {"jsonrpc": "2.0", "id": 11, "method": "ping"},
            "this is not json",
            [1, 2, 3],
        )
        self.assertEqual(out[1]["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual([t["name"] for t in out[2]["result"]["tools"]], ["diff_workbooks", "check_workbook", "explain_cell"])
        diff = out[3]["result"]
        self.assertFalse(diff["isError"])
        self.assertEqual(json.loads(diff["content"][0]["text"]), diff["structuredContent"])
        self.assertEqual(diff["structuredContent"]["summary"]["errors"], 1)
        check = out[4]["result"]["structuredContent"]
        self.assertEqual(check["counts"]["error"], 1)
        explain = out[5]["result"]["structuredContent"]
        self.assertEqual((explain["sheet"], explain["cell"], explain["content"]["formula"]), ("Calc", "C6", "=A6*B6"))
        for i in (6, 7, 8):
            self.assertTrue(out[i]["result"]["isError"], out[i])
        self.assertIn("file not found", out[6]["result"]["content"][0]["text"])
        self.assertEqual(out[9]["error"]["code"], -32602)
        self.assertEqual(out[10]["error"]["code"], -32601)
        self.assertEqual(out[11]["result"], {})
        self.assertEqual(sorted(m["error"]["code"] for m in self.unaddressed), [-32700, -32600])
