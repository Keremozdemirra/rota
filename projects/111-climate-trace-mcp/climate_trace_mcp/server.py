"""MCP server on stdio: JSON-RPC 2.0, protocol 2025-06-18, one JSON message per line.

Same shape as the reference server in agent-vitals: initialize, tools/list and
tools/call, results as text plus structuredContent, tool failures as
`isError: true` results, unknown methods as JSON-RPC errors. Reads and writes
bytes, so a console code page cannot corrupt UTF-8 names.
"""
from __future__ import annotations

import inspect
import json
import sys

from . import __version__
from .client import ApiError
from .countries import CountryError
from .safety import clean
from .tools import TOOLS, Service, ToolError, handlers

PROTOCOL = "2025-06-18"
INSTRUCTIONS = (
    "Climate TRACE figures are modelled estimates. When you report a number, give its unit, gas and GWP horizon, "
    "the year, say that it is a modelled estimate and which source dataset it comes from, and quote the "
    "attribution line from the tool result. When source_datasets or licence_note mention an external dataset or "
    "non-commercial terms, pass that on. Do not present a difference from a company's reported figures as an "
    "error in either.")


class Server:
    def __init__(self, service: Service | None = None, out=None):
        self._service = service
        self._out = out or sys.stdout.buffer

    @property
    def service(self) -> Service:
        # Created on first use: a configuration error then becomes a tool error
        # the client can show, not a server that dies before `initialize`.
        if self._service is None:
            self._service = Service()
        return self._service

    def reply(self, id_, result=None, error=None) -> None:
        msg = {"jsonrpc": "2.0", "id": id_}
        if error is not None:
            msg["error"] = error
        else:
            msg["result"] = result
        self._out.write(json.dumps(msg, ensure_ascii=False, allow_nan=False).encode("utf-8") + b"\n")
        self._out.flush()

    def call_tool(self, params: dict) -> dict:
        name = params.get("name")
        args = params.get("arguments")
        if args is None:
            args = {}
        if not isinstance(args, dict):
            return _error_result({"kind": "invalid_argument", "message": "arguments must be an object"})
        try:
            service = self.service
        except ValueError as e:  # a CLIMATE_TRACE_API_BASE the client refused
            return _error_result({"kind": "configuration", "message": str(e)})
        fn = handlers(service)[name]
        try:
            inspect.signature(fn).bind(**args)
        except TypeError as e:
            return _error_result({"kind": "invalid_argument", "message": "bad arguments for %s: %s" % (name, e)})
        try:
            result = fn(**args)
            text = json.dumps(result, ensure_ascii=False, indent=1, allow_nan=False)
        except (ToolError, ApiError) as e:
            return _error_result(e.as_dict())
        except CountryError as e:
            return _error_result({"kind": "invalid_argument", "message": str(e)})
        except Exception as e:  # a bug here must not take the server down with it
            return _error_result({"kind": "internal_error", "message": "%s: %s" % (type(e).__name__, clean(e, 200))})
        return {"content": [{"type": "text", "text": text}], "structuredContent": result, "isError": False}

    def handle(self, req) -> None:
        if not isinstance(req, dict):
            self.reply(None, error={"code": -32600, "message": "invalid request: expected a JSON object"})
            return
        method = req.get("method")
        id_ = req.get("id")
        params = req.get("params") if isinstance(req.get("params"), dict) else {}
        if method == "initialize":
            self.reply(id_, {"protocolVersion": PROTOCOL, "capabilities": {"tools": {}},
                             "serverInfo": {"name": "climate-trace-mcp", "title": "Climate TRACE MCP (unofficial)",
                                            "version": __version__},
                             "instructions": INSTRUCTIONS})
        elif id_ is None:
            return  # a notification (notifications/initialized and the like): no answer
        elif method == "ping":
            self.reply(id_, {})
        elif method == "tools/list":
            self.reply(id_, {"tools": TOOLS})
        elif method == "tools/call":
            if params.get("name") not in {t["name"] for t in TOOLS}:
                self.reply(id_, error={"code": -32602, "message": "unknown tool %r" % params.get("name")})
                return
            self.reply(id_, self.call_tool(params))
        else:
            self.reply(id_, error={"code": -32601, "message": "method not found: %s" % method})

    def serve(self, stream=None) -> int:
        stream = stream or sys.stdin.buffer
        for raw in stream:
            line = raw.strip()
            if not line:
                continue
            try:
                req = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                self.reply(None, error={"code": -32700, "message": "parse error"})
                continue
            self.handle(req)
        return 0


def _error_result(error: dict) -> dict:
    return {"content": [{"type": "text", "text": "Error (%s): %s" % (error.get("kind"), error.get("message"))}],
            "structuredContent": {"error": error}, "isError": True}


def main() -> int:
    try:
        return Server().serve()
    except (KeyboardInterrupt, BrokenPipeError):
        return 0
