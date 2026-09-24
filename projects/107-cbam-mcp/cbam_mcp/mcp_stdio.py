"""cbam-mcp as an MCP server: JSON-RPC 2.0 over stdin/stdout, one message per line.

Protocol version 2025-06-18, standard library only, the same shape as the
agent-vitals reference server: `initialize`, `tools/list`, `tools/call`
returning text content plus `structuredContent`, tool failures as results with
`isError: true`, unknown methods as JSON-RPC errors. Nothing is sent over the
network while serving; the answers come from the bundled snapshots.
"""
from __future__ import annotations

import json
import sys

from . import __version__, lookup
from .codes import InputError

PROTOCOL = "2025-06-18"

_CN = {"type": "string", "description": "CN code, 2 to 8 digits (or a 10-digit TARIC code), with or without "
                                        "spaces or dots: '7208 51 20', '72085120', '7208.51.20', '7208'"}
_READ_ONLY = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}

TOOLS = [
    {"name": "cbam_scope", "title": "CBAM scope of a CN code",
     "description": (
         "Whether goods under a CN code are in the scope of the EU Carbon Border Adjustment Mechanism, from Annex I "
         "of Regulation (EU) 2023/956 as amended by Regulation (EU) 2025/2083 (consolidated text of 2025-10-20). "
         "Returns status 'in_scope', 'partially_in_scope' or 'not_in_scope' with the reason; the deciding Annex I "
         "line (goods category, greenhouse gases, exceptions, 'ex' flag); whether Annex II limits the goods to "
         "direct emissions; the de minimis texts (Article 2a, Annex VII) where they apply; the CN 2026 description. "
         "'partially_in_scope' means an 'ex' line (only part of the code is covered: read the line's text) or a "
         "heading whose sub-codes differ. For codes shorter than 8 digits it lists the CN 2026 sub-codes in and out "
         "of scope (up to `limit` per list). Not legally binding; information, not legal advice."),
     "inputSchema": {"type": "object", "properties": {
         "cn_code": _CN,
         "limit": {"type": "integer", "minimum": 1, "maximum": 500, "description": "sub-codes listed per status, default 50"}},
         "required": ["cn_code"], "additionalProperties": False},
     "annotations": _READ_ONLY},
    {"name": "default_value", "title": "CBAM default value for a CN code and origin",
     "description": (
         "CBAM default values for goods under a CN code from one country of origin, from the Commission's Excel of "
         "definitive-period default values (the binding values are in Annex I to Implementing Regulation (EU) "
         "2025/2621 as replaced by Implementing Regulation (EU) 2026/1740). Returns per matching table line: "
         "direct, indirect and total embedded emissions in tCO2e per tonne of good as listed (before the increase "
         "Annex I sets for the certificate calculation, which this tool does not apply), the production-route "
         "letter and its meaning, the 'Other countries and territories' values where Annex I says to use them "
         "(country not listed, no line, or '–'), and the Annex IV value for precursors whose country of "
         "production is unknown. EU Member States and the Annex III origins (e.g. Norway, Switzerland) get an "
         "explanation instead of values. No values for electricity (2716) and no indirect-emission factors: those "
         "are Annexes II and III of Implementing Regulation (EU) 2025/2621, not in the Excel. Not legally binding."),
     "inputSchema": {"type": "object", "properties": {
         "cn_code": _CN,
         "country": {"type": "string", "description": "country of origin: name as in the tables ('Türkiye', "
                                                      "'Korea, Republic of (South Korea)'), a common name ('Turkey'), "
                                                      "or an ISO 3166-1 alpha-2 code ('TR')"}},
         "required": ["cn_code", "country"], "additionalProperties": False},
     "annotations": _READ_ONLY},
    {"name": "compare_origins", "title": "Compare CBAM default values across origins",
     "description": (
         "The CBAM default values of one CN code for several countries of origin side by side (up to 30), with the "
         "'Other countries and territories' row and the Annex IV value, in tCO2e per tonne of good as listed in the "
         "Commission's Excel (not legally binding; binding: Implementing Regulation (EU) 2025/2621 as corrected by "
         "2026/1740). Each country shows where its values come from, including the fallback rule when used."),
     "inputSchema": {"type": "object", "properties": {
         "cn_code": _CN,
         "countries": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 30,
                       "description": "country names or ISO 3166-1 alpha-2 codes"}},
         "required": ["cn_code", "countries"], "additionalProperties": False},
     "annotations": _READ_ONLY},
    {"name": "cn_describe", "title": "Combined Nomenclature description",
     "description": (
         "The Combined Nomenclature description of a code in CN 2026 or CN 2025: label, self-explanatory text, "
         "the hierarchy above it (section, chapter, heading, subheading), its sub-codes, and whether the other year "
         "differs. Covers chapters 25, 28, 31, 72, 73, 76 and headings 2601 and 2716 (where the CBAM goods are); "
         "other codes return found=false. Not legally binding: the binding CN is the Official Journal text of "
         "Commission Implementing Regulation (EU) 2025/1926 (CN 2026) or 2024/2522 (CN 2025)."),
     "inputSchema": {"type": "object", "properties": {
         "cn_code": _CN,
         "year": {"type": "integer", "enum": [2025, 2026], "description": "CN version, default 2026"}},
         "required": ["cn_code"], "additionalProperties": False},
     "annotations": _READ_ONLY},
    {"name": "sources", "title": "Sources, versions and licences",
     "description": (
         "Where the answers come from: for each bundled dataset the URL, version label, retrieval date, SHA-256, "
         "row counts, legal status, licence and attribution line, the result of the check against the Official "
         "Journal text, and the later amending or correcting acts found in CELLAR at the last refresh."),
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
     "annotations": _READ_ONLY},
]

HANDLERS = {"cbam_scope": lookup.cbam_scope, "default_value": lookup.default_value,
            "compare_origins": lookup.compare_origins, "cn_describe": lookup.cn_describe, "sources": lookup.sources}

INSTRUCTIONS = (
    "EU CBAM lookups from dated snapshots of the official sources. Every answer states the legally binding act, "
    "the data version and that the data is not legally binding. Default values are in tCO2e per tonne of good, "
    "as listed, before the increase Annex I sets for the certificate calculation. Information only, not legal advice.")


def _error_result(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": True}


def handle(req) -> dict | None:
    """The JSON-RPC response for one request, or None for a notification."""
    if not isinstance(req, dict):
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid request: expected a JSON object"}}
    method = req.get("method")
    id_ = req.get("id")
    params = req.get("params") if isinstance(req.get("params"), dict) else {}
    is_notification = "id" not in req

    def ok(result):
        return None if is_notification else {"jsonrpc": "2.0", "id": id_, "result": result}

    def err(code, message):
        return None if is_notification else {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}

    if not isinstance(method, str):
        return err(-32600, "invalid request: no method")
    if method == "initialize":
        return ok({"protocolVersion": PROTOCOL, "capabilities": {"tools": {}},
                   "serverInfo": {"name": "cbam-mcp", "title": "CBAM lookups", "version": __version__},
                   "instructions": INSTRUCTIONS})
    if method.startswith("notifications/"):
        return None
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": TOOLS})
    if method == "tools/call":
        name = params.get("name")
        fn = HANDLERS.get(name)
        if fn is None:
            return err(-32602, f"unknown tool {name!r}"[:200])
        args = params.get("arguments")
        if args is None:
            args = {}
        if not isinstance(args, dict):
            return ok(_error_result("bad arguments: expected an object"))
        try:
            result = fn(**args)
        except TypeError as e:
            return ok(_error_result(f"bad arguments: {e}"))
        except InputError as e:
            return ok(_error_result(str(e)))
        except lookup.DataError as e:
            return ok(_error_result(f"data unavailable: {e}"))
        except Exception as e:  # never let one bad question end the session
            return ok(_error_result(f"{type(e).__name__}: {e}"))
        return ok({"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=1)}],
                   "structuredContent": result, "isError": False})
    return err(-32601, f"method not found: {method}"[:200])


def serve(stdin=None, stdout=None) -> int:
    if stdin is None:
        stdin = sys.stdin
        # MCP messages are UTF-8; on Windows a pipe would otherwise use the ANSI code page.
        if hasattr(stdin, "reconfigure"):
            stdin.reconfigure(encoding="utf-8", errors="replace")
    if stdout is None:
        stdout = sys.stdout
        if hasattr(stdout, "reconfigure"):
            stdout.reconfigure(encoding="utf-8", newline="\n")
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            resp = handle(req)
        if resp is not None:
            stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            stdout.flush()
    return 0
