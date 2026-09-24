#!/usr/bin/env python3
"""csrd-scope as an MCP server: CSRD scope answers with article citations, over stdio.

JSON-RPC 2.0, protocol version 2025-06-18, one message per line on stdin and stdout.
Standard library only. Answers come from the bundled snapshot of the legal texts; the
server makes no network requests.

Client config (Claude Code):  claude mcp add csrd-scope -- uvx --from csrd-scope csrd-scope-mcp
"""
from __future__ import annotations

import json
import sys

import csrd_scope as core

PROTOCOL = "2025-06-18"

_FY_ITEM = {
    "type": "object",
    "properties": {
        "year": {"type": "integer", "minimum": core.MIN_YEAR, "maximum": core.MAX_YEAR,
                 "description": "Calendar year in which the financial year starts (FY2027 = the year starting in 2027)."},
        "net_turnover_eur": {"type": "number", "minimum": 0, "description": "Net turnover in EUR (Art. 2(5) Directive 2013/34/EU)."},
        "average_employees": {"type": "number", "minimum": 0, "description": "Average number of employees during the financial year, as national law computes it."},
        "balance_sheet_total_eur": {"type": "number", "minimum": 0, "description": "EUR; needed only for the large-undertaking test of FY2024-FY2026."},
        "group_net_turnover_eur": {"type": "number", "minimum": 0, "description": "Consolidated, EUR (parents only)."},
        "group_average_employees": {"type": "number", "minimum": 0, "description": "Consolidated (parents only)."},
        "group_balance_sheet_total_eur": {"type": "number", "minimum": 0, "description": "Consolidated, EUR (parents only)."},
        "eu_net_turnover_eur": {"type": "number", "minimum": 0,
                                "description": "Third-country undertakings only: net turnover generated in the EU at group level (or individual level without a group), EUR."},
        "eu_subsidiaries": {"type": "array", "maxItems": core.MAX_ENTITIES, "description": "Third-country undertakings only: EU subsidiaries and their net turnover in this year.",
                            "items": {"type": "object", "properties": {"name": {"type": "string"}, "net_turnover_eur": {"type": "number", "minimum": 0}},
                                      "required": ["net_turnover_eur"], "additionalProperties": False}},
        "eu_branches": {"type": "array", "maxItems": core.MAX_ENTITIES, "description": "Third-country undertakings only: EU branches and their net turnover in this year.",
                        "items": {"type": "object", "properties": {"name": {"type": "string"}, "net_turnover_eur": {"type": "number", "minimum": 0}},
                                  "required": ["net_turnover_eur"], "additionalProperties": False}},
    },
    "required": ["year"],
    "additionalProperties": False,
}

TOOLS = [
    {"name": "csrd_scope",
     "description": (
         "Decides whether an undertaking is in scope of EU CSRD sustainability reporting and from which financial year, "
         "applying Directive 2013/34/EU (Arts. 1, 2, 3, 19a, 29a, 40a) as amended by Directive (EU) 2026/470 and the "
         "application dates of Art. 5(2) Directive (EU) 2022/2464 as amended by Directives (EU) 2025/794 and 2026/470 "
         "(consolidated versions of 18 March 2026). Amounts in EUR only (never converted); employees are the average "
         "number during the financial year. Returns in_scope (yes/no/depends), first_reporting_financial_year, one result "
         "per financial year from FY2024, the rules applied with article citations and quoted provisions, "
         "questions_for_counsel where national law or legal judgement decides, facts_needed, notified national measures "
         "for member_state, and legal_basis_version (CELEX, consolidated version dates, date checked). EU-directive level "
         "only, not legal advice; no network access. Later figures repeat the latest year unless "
         "assume_latest_figures_continue is false."),
     "inputSchema": {
         "type": "object",
         "properties": {
             "currency": {"type": "string", "enum": ["EUR"], "description": "Must be EUR: convert other currencies yourself and state the EUR figures."},
             "eu_undertaking": {"type": "boolean", "description": "True if governed by the law of an EU Member State; false for a third-country undertaking."},
             "financial_years": {"type": "array", "minItems": 1, "maxItems": core.MAX_YEARS, "items": _FY_ITEM,
                                 "description": "One entry per financial year. Give the year before the first year of interest too: Art. 3(10) compares two years."},
             "name": {"type": "string", "maxLength": 200},
             "member_state": {"type": "string", "description": "Two-letter code of the EU Member State (e.g. DE, FR, EL); used for notified national measures and Annex I/II legal forms."},
             "legal_form_in_annex_i_or_ii": {"type": ["boolean", "null"],
                                             "description": "EU undertakings: true if the legal form is listed in Annex I or II (e.g. AG, GmbH, SA, SARL, BV, NV, S.p.A.); null if unknown (call sources with member_state to see the list)."},
             "entity_type": {"type": "string", "enum": list(core.ENTITY_TYPES), "description": "Credit institutions and insurance undertakings are covered in any legal form; AIFs and UCITS are excluded."},
             "listed_on_eu_regulated_market": {"type": "boolean", "description": "Transferable securities admitted to trading on an EU regulated market."},
             "only_debt_securities_min_denomination_eur_100000": {"type": ["boolean", "null"]},
             "designated_pie": {"type": ["boolean", "null"], "description": "Designated a public-interest entity by its Member State (Art. 2(1)(d))."},
             "parent_undertaking": {"type": "boolean", "description": "Parent of a group; give group_* figures."},
             "financial_holding_undertaking": {"type": "boolean"},
             "covered_by_parent_consolidated_sustainability_report": {"type": "boolean"},
             "financial_year_starts_on": {"type": "string", "pattern": "^(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$", "description": "MM-DD, default 01-01."},
             "assume_latest_figures_continue": {"type": "boolean", "description": "Default true."},
         },
         "required": ["currency", "eu_undertaking", "financial_years"],
         "additionalProperties": False,
     }},
    {"name": "thresholds",
     "description": "The CSRD scope thresholds in force (EUR amounts, employee counts, the financial years they apply to), each with the article and quoted provision, plus exclusions. No input.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "timeline",
     "description": "Who reports for which financial year (2024-2026 set, the 2025-2026 Member State option, FY2027 thresholds, FY2028 third-country rules), how the dates changed (Directives 2022/2464, 2025/794, 2026/470) and the transposition deadlines, with citations. No input.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "sources",
     "description": "The legal basis used: acts, CELEX numbers, consolidated versions, amendments and corrigenda since 2024, the date checked, licence and attribution. With member_state: the national measures that Member State notified (EUR-Lex/CELLAR; not proof of complete transposition) and its legal forms in Annexes I and II.",
     "inputSchema": {"type": "object", "properties": {"member_state": {"type": "string", "description": "Two-letter code of an EU Member State."}},
                     "additionalProperties": False}},
]


def _call(name: str, args: dict):
    data = core.Data()
    if name == "csrd_scope":
        return core.assess(args, data)
    if set(args) - ({"member_state"} if name == "sources" else set()):
        raise core.InputError([f"unknown argument(s) for {name}: {', '.join(core.clean(str(k), 40) for k in sorted(args))}"])
    if name == "thresholds":
        return core.thresholds(data)
    if name == "timeline":
        return core.timeline(data)
    return core.sources(args.get("member_state"), data)


HANDLERS = {t["name"] for t in TOOLS}


def reply(id_, result=None, error=None) -> None:
    msg = {"jsonrpc": "2.0", "id": id_}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def handle(req) -> None:
    if not isinstance(req, dict):
        reply(None, error={"code": -32600, "message": "invalid request: expected a JSON object"})
        return
    method = req.get("method")
    id_ = req.get("id")
    params = req.get("params") or {}
    if method == "initialize":
        reply(id_, {"protocolVersion": PROTOCOL, "capabilities": {"tools": {}},
                    "serverInfo": {"name": "csrd-scope", "version": core.VERSION,
                                   "description": "Is an undertaking in scope of the EU CSRD, and from which financial year? With article citations."}})
    elif isinstance(method, str) and method.startswith("notifications/"):
        return
    elif method == "ping":
        if id_ is not None:
            reply(id_, {})
    elif method == "tools/list":
        reply(id_, {"tools": TOOLS})
    elif method == "tools/call":
        name = params.get("name") if isinstance(params, dict) else None
        if name not in HANDLERS:
            reply(id_, error={"code": -32602, "message": f"unknown tool {core.clean(str(name), 60)!r}"})
            return
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            reply(id_, {"content": [{"type": "text", "text": "arguments must be an object"}], "isError": True})
            return
        try:
            result = _call(name, args)
            reply(id_, {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=1)}],
                        "structuredContent": result, "isError": False})
        except core.InputError as e:
            reply(id_, {"content": [{"type": "text", "text": "input error: " + "; ".join(e.errors)}], "isError": True})
        except FileNotFoundError as e:
            reply(id_, {"content": [{"type": "text", "text": str(e)}], "isError": True})
        except Exception as e:  # a bug must not kill the server; the agent sees the error
            reply(id_, {"content": [{"type": "text", "text": f"internal error: {type(e).__name__}"}], "isError": True})
    elif id_ is not None:
        reply(id_, error={"code": -32601, "message": f"method not found: {core.clean(str(method), 60)}"})


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            reply(None, error={"code": -32700, "message": "parse error"})
            continue
        handle(req)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
