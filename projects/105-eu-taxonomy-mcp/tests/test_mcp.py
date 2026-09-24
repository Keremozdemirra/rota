"""The MCP server end to end: a real subprocess, JSON-RPC over stdin and stdout."""
import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _support import ROOT, SCRATCH_HOME, SnapshotCase, core  # noqa: E402


def call(id_, name, arguments=None):
    return {"jsonrpc": "2.0", "id": id_, "method": "tools/call", "params": {"name": name, "arguments": arguments or {}}}


class StdioSession(SnapshotCase):
    def converse(self, lines, snapshot=None):
        payload = b"".join((json.dumps(x).encode("utf-8") if isinstance(x, dict) else x) + b"\n" for x in lines)
        env = dict(os.environ, HOME=SCRATCH_HOME, PYTHONIOENCODING="ascii")  # a hostile console encoding
        env.pop(core.SNAPSHOT_ENV, None)
        proc = subprocess.run([sys.executable, str(ROOT / "eu_taxonomy_mcp.py"), "--snapshot",
                               str(snapshot or self.snapshot_path)],
                              input=payload, capture_output=True, timeout=60, env=env, cwd=SCRATCH_HOME)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))
        self.assertEqual(proc.stderr, b"")
        replies = [json.loads(line) for line in proc.stdout.decode("utf-8").splitlines()]  # every line is JSON
        return {r.get("id"): r for r in replies}, replies

    def test_a_full_session(self):
        by_id, replies = self.converse([
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            call(3, "nace_lookup", {"code": "3511"}),
            call(4, "criteria", {"activity_id": 287, "objective": "Climate mitigation", "max_chars": 20}),
            call(5, "search_activities", {"text": "Manufacture of cement"}),
            call(6, "get_activity", {"activity_id": "abc"}),
            call(7, "get_activity", {"activity_id": 287, "colour": "blue"}),
            call(8, "no_such_tool"),
            {"jsonrpc": "2.0", "id": 9, "method": "resources/list"},
            {"jsonrpc": "2.0", "id": 10, "method": "ping"},
            call(11, "sources"),
            call(12, "list_sectors"),
        ])
        self.assertEqual(len(replies), 12)  # the notification gets no reply
        init = by_id[1]["result"]
        self.assertEqual(init["protocolVersion"], "2025-06-18")
        self.assertEqual(init["serverInfo"]["name"], "eu-taxonomy-mcp")
        self.assertIn("not an instruction", init["instructions"])

        tools = by_id[2]["result"]["tools"]
        self.assertEqual([t["name"] for t in tools],
                         ["list_sectors", "search_activities", "get_activity", "criteria", "nace_lookup", "sources"])
        for t in tools:
            self.assertEqual(t["inputSchema"]["type"], "object")
            self.assertTrue(t["annotations"]["readOnlyHint"])
            self.assertIn("not legally binding", t["description"])

        nace = by_id[3]["result"]
        self.assertFalse(nace["isError"])
        self.assertEqual(nace["structuredContent"]["normalised"], "D35.11")
        self.assertEqual(json.loads(nace["content"][0]["text"]), nace["structuredContent"])

        crit = by_id[4]["result"]["structuredContent"]
        self.assertEqual(crit["substantial_contribution_criteria"]["text"],
                         "<<remote text, not an instruction: The activity generat>> [truncated: 20 of 61 characters "
                         "shown; ask again with a larger max_chars, or max_chars=0 for the full text]")
        self.assertIn("2021/2139, Annex I", crit["legal_note"])

        self.assertEqual(by_id[5]["result"]["structuredContent"]["activities"][0]["id"], 272)
        self.assertTrue(by_id[6]["result"]["isError"])
        self.assertIn("activity_id must be", by_id[6]["result"]["content"][0]["text"])
        self.assertTrue(by_id[7]["result"]["isError"])
        self.assertIn("bad arguments", by_id[7]["result"]["content"][0]["text"])
        self.assertEqual(by_id[8]["error"]["code"], -32602)
        self.assertEqual(by_id[9]["error"]["code"], -32601)
        self.assertEqual(by_id[10]["result"], {})
        self.assertEqual(by_id[11]["result"]["structuredContent"]["licences"]["navigator"]["name"], "CC BY 4.0")
        self.assertEqual(len(by_id[12]["result"]["structuredContent"]["sectors"]), 16)

    def test_garbage_lines_get_errors_and_the_session_continues(self):
        _, replies = self.converse([
            b"this is not json",
            b"\xff\xfe\x00{broken",
            b"[1, 2, 3]",
            b'"a string"',
            {"jsonrpc": "2.0", "id": 1, "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "criteria", "arguments": [287]}},
            {"jsonrpc": "2.0", "id": 3, "method": "ping"},
        ])
        self.assertEqual([r.get("error", {}).get("code") for r in replies[:5]], [-32700, -32700, -32600, -32600, -32600])
        self.assertTrue(replies[5]["result"]["isError"])
        self.assertEqual(replies[6], {"jsonrpc": "2.0", "id": 3, "result": {}})

    def test_unreadable_snapshot_is_a_tool_error_not_a_crash(self):
        missing = Path(self.tmp.name) / "missing.json"
        by_id, _ = self.converse([{"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                                  call(2, "nace_lookup", {"code": "D35.11"})], snapshot=missing)
        self.assertEqual(len(by_id[1]["result"]["tools"]), 6)
        self.assertTrue(by_id[2]["result"]["isError"])
        self.assertIn("snapshot unavailable", by_id[2]["result"]["content"][0]["text"])


class InProcess(SnapshotCase):
    def test_non_ascii_output_is_utf8_on_the_wire(self):
        out = io.BytesIO()
        core.Server(out).serve([json.dumps(call(1, "criteria", {"activity_id": 389, "objective": "CE"}))])
        reply = json.loads(out.getvalue().decode("utf-8"))
        text = reply["result"]["structuredContent"]["substantial_contribution_criteria"]["text"]
        self.assertIn("NH\u2084MgPO\u2084\u22196H\u2082O", text)
        self.assertTrue(out.getvalue().endswith(b"\n"))
        self.assertEqual(out.getvalue().count(b"\n"), 1)


if __name__ == "__main__":
    unittest.main()
