"""vsme-kit as an MCP server: JSON-RPC 2.0 over stdin/stdout, one message per line, protocol 2025-06-18.

Four tools: vsme_disclosures, disclosure, check_template, editions. The first two
answer from the bundled Official Journal text; check_template reads one local
xlsx file. Nothing is sent over the network.
"""
from __future__ import annotations

import json
import sys

from . import VERSION, standard, template
from .xlsx import WorkbookError

PROTOCOL = "2025-06-18"
EDITION = {"type": "string", "enum": list(standard.EDITIONS),
           "description": "2026 = Annex I to Delegated Regulation (EU) 2026/1560 (in force since 2026-09-24, default); "
                          "2025 = Annex I to Recommendation (EU) 2025/1710, the text EFRAG's Digital Template up to 1.3.0 implements."}

TOOLS = [
    {"name": "vsme_disclosures",
     "description": "Lists the disclosures of the voluntary sustainability reporting standard for SMEs (Basic Module "
                    "B1-B11, Comprehensive Module C1-C9) with titles and paragraph numbers, the module rules quoted "
                    "verbatim, and (2026 edition) whether each disclosure is in the value chain cap. Text is the "
                    "Official Journal's, retrieved 2026-09-24; answers carry the source and licence line to pass on.",
     "inputSchema": {"type": "object", "properties": {
         "module": {"type": "string", "enum": list(standard.MODULES), "description": "basic, comprehensive or all (default)"},
         "edition": EDITION}}},
    {"name": "disclosure",
     "description": "What one disclosure asks, quoted verbatim with paragraph numbers (e.g. B3 energy and GHG "
                    "emissions: MWh and tCO2eq). Also returns related paragraphs, the paragraph numbers of the same "
                    "code in the other edition, the value chain cap rows (2026) or, with guidance=true, the Annex II "
                    "guidance paragraphs (2025). Formulas shown as images in the Official Journal are not reproduced.",
     "inputSchema": {"type": "object", "properties": {
         "code": {"type": "string", "description": "B1 to B11 or C1 to C9"},
         "edition": EDITION,
         "guidance": {"type": "boolean", "description": "2025 edition only: include Annex II guidance paragraphs"}},
         "required": ["code"]}},
    {"name": "check_template",
     "description": "Checks a filled EFRAG VSME Digital Template (local .xlsx, versions 1.0.0-1.3.0) and reports each "
                    "disclosure B1-C9 as filled, missing, not applicable, omitted (classified or sensitive) or "
                    "inconsistent, listing missing datapoints and arithmetic or unit inconsistencies (totals, Scope 1+2, "
                    "intensity, percentages over 100 %, negative quantities), each with the paragraph of Recommendation "
                    "(EU) 2025/1710 it rests on. Percentages in the template are fractions (0.25 = 25 %). Reads the file "
                    "only; returns no free text from it except short marked quotes. Not assurance.",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string", "description": "path of the .xlsx file on this machine"}}, "required": ["path"]}},
    {"name": "editions",
     "description": "Which edition of the standard is which: the acts, Official Journal references, entry into force "
                    "(2026-09-24) and the date the value chain cap applies, read from Delegated Regulation (EU) 2026/1560.",
     "inputSchema": {"type": "object", "properties": {}}},
]


def _vsme_disclosures(module="all", edition=standard.DEFAULT):
    return standard.disclosures(module, edition)


def _disclosure(code, edition=standard.DEFAULT, guidance=False):
    return standard.disclosure(code, edition, bool(guidance))


def _check_template(path):
    if not isinstance(path, str) or not path.strip():
        raise ValueError("path must be a non-empty string")
    return template.check(path)


def _editions():
    return standard.status()


HANDLERS = {"vsme_disclosures": _vsme_disclosures, "disclosure": _disclosure, "check_template": _check_template,
            "editions": _editions}


def reply(id_, result=None, error=None) -> None:
    msg = {"jsonrpc": "2.0", "id": id_}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _error_result(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": True}


def handle(req) -> None:
    if not isinstance(req, dict):
        reply(None, error={"code": -32600, "message": "invalid request"})
        return
    method, id_ = req.get("method"), req.get("id")
    params = req.get("params") if isinstance(req.get("params"), dict) else {}
    if method == "initialize":
        reply(id_, {"protocolVersion": PROTOCOL, "capabilities": {"tools": {}},
                    "serverInfo": {"name": "vsme-kit", "version": VERSION,
                                   "description": "The EU voluntary sustainability reporting standard for SMEs: "
                                                  "the text, and a check of EFRAG's VSME Digital Template."}})
    elif method in ("notifications/initialized", "notifications/cancelled") or (method == "ping" and id_ is None):
        return
    elif method == "ping":
        reply(id_, {})
    elif method == "tools/list":
        reply(id_, {"tools": TOOLS})
    elif method == "tools/call":
        name = params.get("name")
        fn = HANDLERS.get(name)
        if not fn:
            reply(id_, error={"code": -32602, "message": f"unknown tool {str(name)[:40]!r}"})
            return
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            reply(id_, _error_result("arguments must be an object"))
            return
        try:
            result = fn(**args)
            reply(id_, {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=1)}],
                        "structuredContent": result, "isError": False})
        except TypeError as e:
            reply(id_, _error_result(f"bad arguments: {e}"))
        except (standard.LookupError_, ValueError) as e:
            reply(id_, _error_result(str(e)))
        except WorkbookError as e:
            reply(id_, _error_result(f"cannot check the file: {e}"))
        except Exception as e:  # never let one call take the server down
            reply(id_, _error_result(f"{type(e).__name__}: {e}"))
    elif id_ is not None:
        reply(id_, error={"code": -32601, "message": f"method not found: {str(method)[:60]}"})


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
