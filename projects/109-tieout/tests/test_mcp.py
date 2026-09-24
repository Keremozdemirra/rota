"""The MCP server, end to end over stdin and stdout, and its argument checks."""
import json
import os
import subprocess
import sys
import unittest

from tests.support import EXAMPLES, ROOT, IsolatedTestCase

import tieout_mcp


def session(lines, home):
    env = dict(os.environ, HOME=str(home), PYTHONIOENCODING="utf-8")
    p = subprocess.run([sys.executable, str(ROOT / "tieout.py"), "mcp"], input="\n".join(lines) + "\n",
                       capture_output=True, text=True, encoding="utf-8", env=env, timeout=120, cwd=str(ROOT))
    return [json.loads(line) for line in p.stdout.splitlines() if line.strip()], p


def call(id_, name, args):
    return json.dumps({"jsonrpc": "2.0", "id": id_, "method": "tools/call", "params": {"name": name, "arguments": args}})


class Protocol(IsolatedTestCase):
    def test_session(self):
        deck, model = str(EXAMPLES / "deck.pptx"), str(EXAMPLES / "model.xlsx")
        lines = [
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                        "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t"}}}),
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
            call(3, "tie_out", {"deliverable_path": deck, "source_paths": [model], "limit": 4}),
            call(4, "extract_numbers", {"path": deck, "limit": 2}),
            call(5, "tie_out", {"deliverable_path": str(EXAMPLES / "missing.pptx"), "source_paths": [model]}),
            call(6, "tie_out", {"deliverable_path": deck, "source_paths": "not-a-list.xlsx", "limit": 0}),
            call(7, "no_such_tool", {}),
            json.dumps({"jsonrpc": "2.0", "id": 8, "method": "resources/list"}),
            json.dumps({"jsonrpc": "2.0", "id": 9, "method": "ping"}),
            "this is not json",
            "[1, 2]",
        ]
        replies, proc = session(lines, self.home)
        by_id = {r.get("id"): r for r in replies if r.get("id") is not None}
        self.assertEqual(by_id[1]["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(by_id[1]["result"]["serverInfo"]["name"], "tieout")
        self.assertEqual([t["name"] for t in by_id[2]["result"]["tools"]], ["tie_out", "extract_numbers"])
        res = by_id[3]["result"]
        self.assertFalse(res["isError"])
        sc = res["structuredContent"]
        self.assertEqual(json.loads(res["content"][0]["text"]), sc)
        self.assertEqual([d["status"] for d in sc["numbers"]], ["untied", "untied", "untied", "untied"])
        self.assertEqual(sc["numbers_returned"], 4)
        self.assertGreater(sc["summary"]["tied"], 20)
        ext = by_id[4]["result"]["structuredContent"]
        self.assertEqual(len(ext["numbers"]), 2)
        self.assertNotIn("sources", ext)
        self.assertTrue(by_id[5]["result"]["isError"])
        self.assertIn("file not found", by_id[5]["result"]["content"][0]["text"])
        self.assertTrue(by_id[6]["result"]["isError"])
        self.assertIn("limit must be an integer", by_id[6]["result"]["content"][0]["text"])
        self.assertEqual(by_id[7]["error"]["code"], -32602)
        self.assertEqual(by_id[8]["error"]["code"], -32601)
        self.assertEqual(by_id[9]["result"], {})
        codes = [r["error"]["code"] for r in replies if r.get("id") is None]
        self.assertEqual(codes, [-32700, -32600])
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stderr, "")


class Arguments(IsolatedTestCase):
    def test_argument_checks(self):
        with self.assertRaisesRegex(tieout_mcp.ArgumentError, "deliverable_path"):
            tieout_mcp.tie_out(deliverable_path="", source_paths=["a.xlsx"])
        with self.assertRaisesRegex(tieout_mcp.ArgumentError, "source_paths"):
            tieout_mcp.tie_out(deliverable_path="a.pptx", source_paths=[])
        with self.assertRaisesRegex(tieout_mcp.ArgumentError, "source_units"):
            tieout_mcp.tie_out(deliverable_path="a.pptx", source_paths=["a.xlsx"], source_units=["lakh"])
        with self.assertRaisesRegex(tieout_mcp.ArgumentError, "locale"):
            tieout_mcp.extract_numbers(path="a.pptx", locale="fr")
        with self.assertRaisesRegex(tieout_mcp.ArgumentError, "min_digits"):
            tieout_mcp.extract_numbers(path="a.pptx", min_digits=True)

    def test_descriptions_state_returns_and_limits(self):
        for tool in tieout_mcp.TOOLS:
            self.assertIn("Returns" if tool["name"] == "tie_out" else "status", tool["description"])
            self.assertIn("200 MB", tool["description"])
            self.assertIn("No PDF", tool["description"])
            self.assertTrue(tool["annotations"]["readOnlyHint"])


if __name__ == "__main__":
    unittest.main()
