"""MCP server on stdio: JSON-RPC 2.0, protocol version 2025-06-18, one message
per line. Same shape as the reference server in agent-vitals: tool results
carry `content` (text) and `structuredContent`; a tool that fails returns
`isError: true`; an unknown method is a JSON-RPC error.
"""
from __future__ import annotations

import json
import sys

from . import __version__, lookup

PROTOCOL = "2025-06-18"

_DATE = {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$",
         "description": "Optional day to answer for, YYYY-MM-DD (default: today, UTC). Not earlier than the "
                        "consolidated version the snapshot starts from."}

TOOLS = [
    {"name": "eudr_scope",
     "description": ("Is a CN code a relevant product under the EU Deforestation Regulation (EU) 2023/1115? Looks the "
                     "code up in Annex I (consolidated text plus later amending acts, from a dated CELLAR snapshot) and "
                     "returns status relevant_product (listed), partly_ex (an 'ex' entry: only goods matching the "
                     "entry's description), heading_with_listed_codes (a chapter or heading with listed codes under "
                     "it, which are returned) or not_listed; the commodity; the Annex entry text; entries that apply "
                     "later or were removed; the legal acts and date checked. Accepts 2, 4, 6, 8 or 10 digits "
                     "('1801 00 00', '18010000', '1801.00.00'). Does not classify goods. Information, not legal advice."),
     "inputSchema": {"type": "object", "properties": {
         "cn_code": {"type": "string", "description": "CN/HS code, e.g. '1801 00 00', '4401', '0201 30 00'"},
         "date": _DATE}, "required": ["cn_code"], "additionalProperties": False}},
    {"name": "commodity_codes",
     "description": ("All Annex I entries of one relevant commodity of Regulation (EU) 2023/1115 (cattle, cocoa, "
                     "coffee, oil palm, rubber, soya, wood) on a date: CN codes, 'ex' flags, the Annex description and "
                     "exclusions, plus entries that apply later or were replaced, and the table notes (species, "
                     "samples). From a dated CELLAR snapshot. Information, not legal advice."),
     "inputSchema": {"type": "object", "properties": {
         "commodity": {"type": "string", "enum": ["cattle", "cocoa", "coffee", "oil palm", "rubber", "soya", "wood"]},
         "date": _DATE}, "required": ["commodity"], "additionalProperties": False}},
    {"name": "application_dates",
     "description": ("From when the obligations of Regulation (EU) 2023/1115 apply, by operator type, with the "
                     "article that sets each date (Article 38(2) and (3), as last replaced), its wording, conditions "
                     "(established by 31 December 2024; timber under the EU Timber Regulation), the Article 2 "
                     "definition, related dates (entry into force, EUTR repeal, later Annex I entries) and the history "
                     "of postponements. Dates are YYYY-MM-DD; 'unverified' when the snapshot could not verify them. "
                     "Information, not legal advice."),
     "inputSchema": {"type": "object", "properties": {
         "operator_type": {"type": "string", "description": (
             "all (default), large, medium, sme, micro, small, micro or small, natural person, "
             "micro or small primary operator, downstream operator, trader, operator")}},
         "additionalProperties": False}},
    {"name": "country_risk",
     "description": ("Risk level the Commission assigned to a country under Article 29 of Regulation (EU) 2023/1115 "
                     "(Implementing Regulation (EU) 2025/1093): low or high if listed in its Annex, standard if not "
                     "listed (Article 1(2)); not_determined for territories the EU authority table records under "
                     "another country; unknown_country with suggestions if the input matches nothing. Input: ISO "
                     "3166-1 alpha-2, alpha-3 or English name. From a dated CELLAR snapshot. Information, not legal "
                     "advice."),
     "inputSchema": {"type": "object", "properties": {
         "country": {"type": "string", "description": "e.g. 'BR', 'BRA', 'Brazil', 'Viet Nam'"}},
         "required": ["country"], "additionalProperties": False}},
    {"name": "sources",
     "description": ("The legal acts behind every answer: CELEX numbers, consolidated version, amending acts applied, "
                     "corrigenda, pending proposals, retrieval date, SHA-256 of each downloaded file, verification "
                     "status, licence and attribution."),
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
]

HANDLERS = {
    "eudr_scope": lookup.eudr_scope,
    "commodity_codes": lookup.commodity_codes,
    "application_dates": lookup.application_dates,
    "country_risk": lookup.country_risk,
    "sources": lookup.sources,
}


def _reply(out, id_, result=None, error=None) -> None:
    msg = {"jsonrpc": "2.0", "id": id_}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    # ASCII escapes keep the wire format independent of the console encoding.
    out.write(json.dumps(msg, ensure_ascii=True) + "\n")
    out.flush()


def _tool_error(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": True}


def call_tool(name, arguments) -> dict:
    fn = HANDLERS.get(name)
    if fn is None:
        return None
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        return _tool_error("arguments must be an object")
    allowed = set(next(t for t in TOOLS if t["name"] == name)["inputSchema"]["properties"])
    unknown = sorted(set(arguments) - allowed)
    if unknown:
        return _tool_error(f"unknown argument(s): {', '.join(unknown)[:120]}; allowed: {', '.join(sorted(allowed)) or 'none'}")
    try:
        result = fn(**arguments)
    except TypeError as e:
        return _tool_error(f"bad arguments: {e}")
    except lookup.InputError as e:
        return _tool_error(str(e))
    except lookup.DataError as e:
        return _tool_error(f"snapshot unavailable: {e}")
    return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=1)}],
            "structuredContent": result, "isError": False}


def handle(req, out) -> None:
    if not isinstance(req, dict):
        _reply(out, None, error={"code": -32600, "message": "invalid request"})
        return
    method = req.get("method")
    id_ = req.get("id")
    params = req.get("params") or {}
    if not isinstance(params, dict):
        if id_ is not None:
            _reply(out, id_, error={"code": -32602, "message": "params must be an object"})
        return
    if method == "initialize":
        _reply(out, id_, {"protocolVersion": PROTOCOL, "capabilities": {"tools": {}},
                          "serverInfo": {"name": "eudr-scope-mcp", "version": __version__},
                          "instructions": ("EU Deforestation Regulation (EU) 2023/1115: Annex I scope by CN code, "
                                           "application dates, country risk levels, from a dated snapshot of the "
                                           "legal texts. Quote the legal act and the date checked; it is information, "
                                           "not legal advice.")})
    elif method in ("notifications/initialized", "notifications/cancelled") or (method == "ping" and id_ is None):
        return
    elif method == "ping":
        _reply(out, id_, {})
    elif method == "tools/list":
        _reply(out, id_, {"tools": TOOLS})
    elif method == "tools/call":
        name = params.get("name")
        result = call_tool(name, params.get("arguments"))
        if result is None:
            _reply(out, id_, error={"code": -32602, "message": f"unknown tool {str(name)[:60]!r}"})
        else:
            _reply(out, id_, result)
    elif id_ is not None:
        _reply(out, id_, error={"code": -32601, "message": f"method not found: {str(method)[:60]}"})


def serve(inp=None, out=None) -> int:
    inp = inp or sys.stdin
    out = out or sys.stdout
    for line in inp:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            _reply(out, None, error={"code": -32700, "message": "parse error"})
            continue
        try:
            handle(req, out)
        except Exception as e:  # a bug must not take the server down mid-session
            if isinstance(req, dict) and req.get("id") is not None:
                _reply(out, req.get("id"), error={"code": -32603, "message": f"internal error: {type(e).__name__}"})
    return 0
