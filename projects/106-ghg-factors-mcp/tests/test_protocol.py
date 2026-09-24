"""MCP over stdio, end to end in a subprocess, and the message handler on its own."""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import ROOT, SnapshotTestCase  # noqa: E402

from ghg_factors_mcp import protocol  # noqa: E402


def rpc(id_, method, params=None):
    msg = {"jsonrpc": "2.0", "id": id_, "method": method}
    if params is not None:
        msg["params"] = params
    return msg


def call(id_, name, **arguments):
    return rpc(id_, "tools/call", {"name": name, "arguments": arguments})


class EndToEnd(SnapshotTestCase):
    def test_session_over_stdio(self):
        lines = [
            rpc(1, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                  "clientInfo": {"name": "test", "version": "0"}}),
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            rpc(2, "tools/list"),
            call(3, "search_factors", text="diesel average biofuel blend", unit="litres", limit=1),
            call(4, "convert", amount=1000, unit="kWh", factor_id="desnz-2026:1_100_1004_6_1"),
            call(5, "grid_intensity", country="Türkiye", year=2025),
            rpc(6, "ping"),
            rpc(7, "resources/list"),
            call(8, "no_such_tool"),
        ]
        stdin = "".join(json.dumps(m, ensure_ascii=False) + "\n" for m in lines)
        stdin += "this is not json\n\n" + json.dumps([rpc(9, "ping")]) + "\n"
        env = {**os.environ, "GHG_FACTORS_DATA": str(self.data), "HOME": str(self.data.parent),
               "PYTHONPATH": str(ROOT), "PYTHONIOENCODING": "ascii"}
        proc = subprocess.run([sys.executable, "-m", "ghg_factors_mcp"], input=stdin.encode("utf-8"),
                              capture_output=True, env=env, cwd=str(self.data.parent), timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        out = [json.loads(line) for line in proc.stdout.decode("ascii").splitlines()]
        by_id = {m["id"]: m for m in out if m.get("id") is not None}
        self.assertEqual(len(out), 10)  # one reply per request; none for the notification or the blank line

        init = by_id[1]["result"]
        self.assertEqual((init["protocolVersion"], init["serverInfo"]["name"]), ("2025-06-18", "ghg-factors-mcp"))
        self.assertIn("tools", init["capabilities"])
        tools = {t["name"]: t for t in by_id[2]["result"]["tools"]}
        self.assertEqual(sorted(tools), ["convert", "get_factor", "grid_intensity", "search_factors", "sources"])
        self.assertIn("UK-specific", tools["search_factors"]["description"])
        self.assertIn("never a market-based", tools["grid_intensity"]["description"])

        search = by_id[3]["result"]
        self.assertFalse(search["isError"])
        hit = search["structuredContent"]["results"][0]
        self.assertEqual((hit["factor_id"], hit["value"], hit["region"]), ("desnz-2026:1_101_1011_8_1", 2.58354, "UK"))
        self.assertEqual(json.loads(search["content"][0]["text"]), search["structuredContent"])

        refused = by_id[4]["result"]
        self.assertTrue(refused["isError"])
        self.assertIn("unit mismatch", refused["structuredContent"]["reason"])

        grid = by_id[5]["result"]["structuredContent"]
        self.assertEqual((grid["area"], grid["value"]), ("Türkiye", 475.776))

        self.assertEqual(by_id[6]["result"], {})
        self.assertEqual(by_id[7]["error"]["code"], -32601)
        self.assertEqual(by_id[8]["error"]["code"], -32602)
        errors = [m["error"]["code"] for m in out if m.get("id") is None]
        self.assertEqual(errors, [-32700, -32600])


class Handler(SnapshotTestCase):
    def result(self, name, arguments):
        return protocol.handle(call(1, name, **arguments) if isinstance(arguments, dict)
                               else rpc(1, "tools/call", {"name": name, "arguments": arguments}))["result"]

    def test_notifications_get_no_reply(self):
        self.assertIsNone(protocol.handle({"jsonrpc": "2.0", "method": "notifications/cancelled",
                                           "params": {"requestId": 3}}))

    def test_bad_arguments_are_tool_errors(self):
        r = self.result("convert", {"amount": 1, "unit": "litres"})
        self.assertTrue(r["isError"])
        self.assertEqual(r["structuredContent"]["missing"], ["factor_id"])
        r = self.result("search_factors", {"text": "diesel", "country": "UK"})
        self.assertEqual(r["structuredContent"]["unknown"], ["country"])
        self.assertTrue(self.result("sources", ["not", "an", "object"])["isError"])

    def test_refusal_carries_alternatives(self):
        r = self.result("convert", {"amount": "1,5", "unit": "litres", "factor_id": "desnz-2026:1_101_1011_8_1"})
        self.assertTrue(r["isError"])
        self.assertTrue(r["structuredContent"]["refused"])

    def test_unexpected_exception_does_not_end_the_session(self):
        from unittest import mock
        with mock.patch.dict(protocol.HANDLERS, {"sources": mock.Mock(side_effect=KeyError("boom"))}):
            r = self.result("sources", {})
        self.assertTrue(r["isError"])
        self.assertIn("KeyError", r["structuredContent"]["error"])

    def test_serve_writes_ascii_json_lines(self):
        stdin = io.BytesIO((json.dumps(call(1, "grid_intensity", country="Turkiye", year=2025)) + "\n").encode())
        stdout = io.StringIO()
        self.assertEqual(protocol.serve(stdin, stdout), 0)
        line = stdout.getvalue()
        self.assertTrue(line.endswith("\n") and line.count("\n") == 1)
        line.encode("ascii")  # would raise on a raw non-ASCII character
        self.assertIn("T\\u00fcrkiye", line)

    def test_invalid_utf8_line(self):
        stdout = io.StringIO()
        protocol.serve(io.BytesIO(b'{"jsonrpc": "2.0", "id": 1, "method": "ping\xff"}\n'), stdout)
        self.assertEqual(json.loads(stdout.getvalue())["error"]["code"], -32700)


if __name__ == "__main__":
    import unittest
    unittest.main()
