"""The MCP server: JSON-RPC handling, tool schemas, and a real session over stdio."""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys

from tests.support import ROOT, E, Isolated


def rpc(method, id_=1, **params):
    msg = {"jsonrpc": "2.0", "method": method, "params": params}
    if id_ is not None:
        msg["id"] = id_
    return msg


class Protocol(Isolated):
    def test_initialize(self):
        r = E.handle(rpc("initialize", protocolVersion="2025-06-18", capabilities={},
                         clientInfo={"name": "test", "version": "0"}))
        self.assertEqual(r["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(r["result"]["capabilities"], {"tools": {}})
        self.assertEqual(r["result"]["serverInfo"]["name"], "eiopa-rfr")
        self.assertIn("attribution", r["result"]["instructions"])

    def test_tools_list(self):
        tools = E.handle(rpc("tools/list"))["result"]["tools"]
        self.assertEqual([t["name"] for t in tools], ["list_releases", "get_curve", "get_rate", "get_parameters", "compare"])
        for t in tools:
            self.assertEqual(t["inputSchema"]["type"], "object", t["name"])
            self.assertGreater(len(t["description"]), 150, t["name"])
        rate = next(t for t in tools if t["name"] == "get_rate")
        self.assertEqual(rate["inputSchema"]["required"], ["currency", "maturity_years"])
        self.assertIn("basis points", rate["description"])
        self.assertIn("percent", rate["description"])

    def test_tool_call_returns_text_and_structured_content(self):
        r = E.handle(rpc("tools/call", name="get_rate",
                         arguments={"currency": "EUR", "maturity_years": 10, "date": "2026-08"}))["result"]
        self.assertFalse(r["isError"])
        self.assertEqual(r["structuredContent"]["no_va"]["rate"], 0.03268)
        self.assertEqual(json.loads(r["content"][0]["text"]), r["structuredContent"])

    def test_tool_errors_are_results_not_protocol_errors(self):
        cases = [{"currency": "XYZ", "maturity_years": 10, "date": "2026-08"},   # unknown currency
                 {"currency": "EUR", "maturity_years": 10, "date": "2031-01"},   # month not published
                 {"currency": "EUR"},                                            # missing argument
                 {"currency": "EUR", "maturity_years": 10, "colour": "red"}]     # unknown argument
        for args in cases:
            r = E.handle(rpc("tools/call", name="get_rate", arguments=args))
            self.assertNotIn("error", r, args)
            self.assertTrue(r["result"]["isError"], args)
            self.assertTrue(r["result"]["content"][0]["text"], args)
        r = E.handle(rpc("tools/call", name="get_rate", arguments=["EUR", 10]))
        self.assertTrue(r["result"]["isError"])

    def test_unexpected_exceptions_do_not_kill_the_server(self):
        from unittest import mock
        with mock.patch.object(E, "get_listing", side_effect=KeyError("boom")):
            r = E.handle(rpc("tools/call", name="list_releases", arguments={}))
        self.assertTrue(r["result"]["isError"])
        self.assertIn("unexpected KeyError", r["result"]["content"][0]["text"])

    def test_json_rpc_errors(self):
        self.assertEqual(E.handle(rpc("tools/call", name="nope"))["error"]["code"], -32602)
        self.assertEqual(E.handle(rpc("resources/list"))["error"]["code"], -32601)
        self.assertEqual(E.handle({"jsonrpc": "2.0", "id": 3})["error"]["code"], -32600)
        self.assertEqual(E.handle([rpc("ping")])["error"]["code"], -32600)
        self.assertEqual(E.handle(rpc("ping")), {"jsonrpc": "2.0", "id": 1, "result": {}})

    def test_notifications_get_no_answer(self):
        self.assertIsNone(E.handle(rpc("notifications/initialized", id_=None)))
        self.assertIsNone(E.handle(rpc("notifications/cancelled", id_=None, requestId=1)))
        self.assertIsNone(E.handle(rpc("some/unknown", id_=None)))

    def test_serve_loop_handles_bad_lines(self):
        stdin = io.StringIO("\n".join([json.dumps(rpc("ping", 1)), "{not json", "", json.dumps(rpc("ping", 2))]) + "\n")
        stdout = io.BytesIO()
        self.assertEqual(E.serve(stdin, stdout), 0)
        lines = [json.loads(x) for x in stdout.getvalue().decode().splitlines()]
        self.assertEqual([(x.get("id"), "error" in x) for x in lines], [(1, False), (None, True), (2, False)])
        self.assertEqual(lines[1]["error"]["code"], -32700)


class StdioSession(Isolated):
    """A real server process, spoken to over stdin/stdout, with nothing but the local cache."""

    def test_end_to_end(self):
        E.get_rate("EUR", 10, "2026-08")  # fill the isolated cache through the fake website
        E.get_rate("EUR", 10, "2026-07")
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH",)}
        env.update({"EIOPA_RFR_OFFLINE": "1", "PYTHONIOENCODING": "utf-8"})
        messages = [
            rpc("initialize", 1, protocolVersion="2025-06-18", capabilities={}, clientInfo={"name": "t", "version": "0"}),
            rpc("notifications/initialized", None),
            rpc("tools/list", 2),
            rpc("tools/call", 3, name="get_rate", arguments={"currency": "EUR", "maturity_years": 10, "date": "2026-08"}),
            rpc("tools/call", 4, name="compare", arguments={"currency": "EUR", "maturity_years": 10,
                                                            "date_a": "2026-07", "date_b": "2026-08"}),
            rpc("tools/call", 5, name="get_rate", arguments={"currency": "XYZ", "maturity_years": 10, "date": "2026-08"}),
            rpc("tools/call", 6, name="get_parameters", arguments={"currency": "USD", "date": "latest"}),
            rpc("no/such/method", 7),
        ]
        stdin = "\n".join(json.dumps(m) for m in messages) + "\n{broken\n"
        proc = subprocess.run([sys.executable, str(ROOT / "eiopa_rfr.py"), "mcp"], input=stdin.encode("utf-8"),
                              capture_output=True, env=env, cwd=str(self.tmp), timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        self.assertEqual(proc.stderr, b"")
        replies = [json.loads(line) for line in proc.stdout.decode("utf-8").splitlines()]
        by_id = {r.get("id"): r for r in replies}
        self.assertEqual(len(replies), 8)  # 7 requests with an id + 1 parse error; the notification has no reply
        self.assertEqual(by_id[1]["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(len(by_id[2]["result"]["tools"]), 5)
        rate = by_id[3]["result"]["structuredContent"]
        self.assertEqual((rate["no_va"]["rate_percent"], rate["with_va"]["rate_percent"]), (3.268, 3.408))
        self.assertIn("EIOPA_RFR_20260831.zip", rate["attribution"])
        change = by_id[4]["result"]["structuredContent"]
        self.assertEqual(change["no_va"]["change"]["bp"], 10.9)
        self.assertTrue(by_id[5]["result"]["isError"])
        self.assertIn("XYZ is not among", by_id[5]["result"]["content"][0]["text"])
        params = by_id[6]["result"]["structuredContent"]
        self.assertEqual((params["curve"]["code"], params["with_va"]["va_bp"]), ("US", 33))
        self.assertIn("offline mode", params["date"]["note"])
        self.assertEqual(by_id[7]["error"]["code"], -32601)
        self.assertEqual(by_id[None]["error"]["code"], -32700)
