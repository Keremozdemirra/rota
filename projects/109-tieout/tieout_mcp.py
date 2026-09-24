#!/usr/bin/env python3
"""tieout as an MCP server: an agent asks which numbers in a deliverable tie out.

Protocol version 2025-06-18, JSON-RPC 2.0 over stdin and stdout, one message per
line, standard library only. Two tools:

  tie_out          every number in a .docx, .pptx, .md or .txt file against .xlsx and .csv sources
  extract_numbers  every number in a deliverable, read and classified, without sources

Only local files are read; nothing is sent anywhere (link checking is a CLI option
and is not offered here).

Run it:   tieout mcp            (or: python3 tieout_mcp.py)
Claude Code:
  claude mcp add tieout -- uvx tieout@0.1.0 mcp
"""
from __future__ import annotations

import json
import os
import sys

import tieout

PROTOCOL = "2025-06-18"
MAX_LIMIT = 1000
MAX_SOURCES = 50
MAX_CANDIDATES = 5
PRIORITY = {"untied": 0, "ambiguous": 1, "tied": 2, "extracted": 3, "excluded": 4}

_COMMON = ("Number reading: locale detected per document (1,234.5 vs 1.234,5) unless `locale` is set; negatives in "
           "parentheses; %, ‰, pp, bps; currency symbols and ISO codes; scale words and suffixes (k, m, mn, bn, tn, "
           "thousand, million, billion, Tsd., Mio., Mrd.); multiples (3.1x); ranges (10–12%). Excluded, with the reason: "
           "years, dates, times, page and slide numbers, footnote markers, list numbering, phone numbers, labels "
           "(Scope 3, Figure 2), codes (CO2, Q3, FY25), ordinals, digits inside links or DOIs. Reads .docx paragraphs, "
           "tables, footnotes, endnotes, text boxes, headers and footers; .pptx slides, tables, speaker notes, SmartArt "
           "and the values cached in chart XML; .md and .txt by line. No PDF: convert with `pdftotext -layout`. "
           "Local files only, up to 200 MB each; nothing is sent over the network.")

TOOLS = [
    {"name": "tie_out",
     "description": (
         "Tie out a report or deck against its source workbooks: for every number in the deliverable, find the source "
         "cells it could have come from, allowing for rounding (Excel rounding at 15 significant digits, half up or half "
         "even), percentages (61% ties to 0.6134), scale (€4.2bn ties to 4,213,500,000; a cell under a '€m' row label or "
         "column header counts in millions) and sign conventions. Returns `summary` (counts: tied, untied, ambiguous, "
         "excluded, excluded_by_reason) and `numbers`, untied first, each with: written (as in the file), where "
         "(slide/paragraph/table cell/footnote/line), context, status, and for tied or ambiguous numbers the candidate "
         "cells (file, sheet!cell or csv row/col, value, row and column labels, how: exact/rounded/percentage/scaled, "
         "the arithmetic). status: tied = one source value matches (at most 5 cells); ambiguous = several different "
         "values or more than 5 cells match; untied = nothing matches, with the nearest source value within ±10% when "
         "there is one; excluded = not a figure, with the reason. A tie means a matching value exists in the sources, "
         "not that it is the right line: check the labels. " + _COMMON),
     "inputSchema": {"type": "object", "properties": {
         "deliverable_path": {"type": "string", "description": "Path to the .docx, .pptx, .md or .txt file."},
         "source_paths": {"type": "array", "items": {"type": "string"},
                          "description": "Paths to the source .xlsx/.xlsm or .csv/.tsv files (up to 50)."},
         "locale": {"type": "string", "enum": ["auto", "en", "de"],
                    "description": "Number format of the deliverable: en = 1,234.5; de = 1.234,5. Default auto."},
         "min_digits": {"type": "integer", "minimum": 1, "maximum": 20,
                        "description": "Ignore numbers written with fewer digits than this. Default 1."},
         "source_units": {"type": "array", "items": {"type": "string", "enum": ["thousand", "million", "billion"]},
                          "description": "Also read source numbers that carry no unit label as thousands/millions/billions."},
         "include_excluded": {"type": "boolean", "description": "Also return excluded numbers. Default false."},
         "limit": {"type": "integer", "minimum": 1, "maximum": MAX_LIMIT,
                   "description": "Most numbers returned, untied and ambiguous first. Default 200."}},
         "required": ["deliverable_path", "source_paths"]},
     "annotations": {"title": "Tie out a deliverable", "readOnlyHint": True, "openWorldHint": False}},
    {"name": "extract_numbers",
     "description": (
         "List every number in a report or deck without tying it to a source: written (as in the file), where, context, "
         "read_as (value, decimals, scale and where the scale came from, unit, currency, sign, qualifier such as "
         "'around' or 'more than', range role) and status: extracted, or excluded with the reason. Also returns the "
         "detected number format with the evidence counted. " + _COMMON),
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string", "description": "Path to the .docx, .pptx, .md or .txt file."},
         "locale": {"type": "string", "enum": ["auto", "en", "de"], "description": "Default auto."},
         "min_digits": {"type": "integer", "minimum": 1, "maximum": 20, "description": "Default 1."},
         "limit": {"type": "integer", "minimum": 1, "maximum": MAX_LIMIT, "description": "Default 500."}},
         "required": ["path"]},
     "annotations": {"title": "Extract numbers", "readOnlyHint": True, "openWorldHint": False}},
]


class ArgumentError(ValueError):
    pass


def _path(value, name) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ArgumentError(f"{name} must be a non-empty string")
    if len(value) > 4096 or "\x00" in value:
        raise ArgumentError(f"{name} is not a usable path")
    return os.path.expanduser(value.strip())


def _choice(value, name, allowed, default):
    if value is None:
        return default
    if value not in allowed:
        raise ArgumentError(f"{name} must be one of {', '.join(allowed)}")
    return value


def _int(value, name, lo, hi, default):
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise ArgumentError(f"{name} must be an integer from {lo} to {hi}")
    return value


def _trim(report: dict, limit: int, include_excluded: bool) -> dict:
    nums = [d for d in report["numbers"] if include_excluded or d["status"] != "excluded"]
    nums.sort(key=lambda d: (PRIORITY.get(d["status"], 9), d["id"]))
    out = []
    for d in nums[:limit]:
        d = dict(d)
        if "candidates" in d:
            d["candidates"] = d["candidates"][:MAX_CANDIDATES]
        out.append(d)
    trimmed = {k: v for k, v in report.items() if k not in ("numbers", "links")}
    trimmed["numbers"] = out
    trimmed["numbers_returned"] = len(out)
    trimmed["numbers_matching_filter"] = len(nums)
    return trimmed


def tie_out(deliverable_path=None, source_paths=None, locale=None, min_digits=None, source_units=None,
            include_excluded=None, limit=None) -> dict:
    path = _path(deliverable_path, "deliverable_path")
    if isinstance(source_paths, str):
        source_paths = [source_paths]
    if not isinstance(source_paths, list) or not source_paths:
        raise ArgumentError("source_paths must be a non-empty list of paths")
    if len(source_paths) > MAX_SOURCES:
        raise ArgumentError(f"at most {MAX_SOURCES} source files")
    sources = [_path(p, "source_paths[]") for p in source_paths]
    units = source_units or []
    if not isinstance(units, list) or any(u not in ("thousand", "million", "billion") for u in units):
        raise ArgumentError("source_units must be a list of 'thousand', 'million' or 'billion'")
    report = tieout.build_report(path, sources, _choice(locale, "locale", ("auto", "en", "de"), "auto"),
                                 _int(min_digits, "min_digits", 1, 20, 1), units)
    return _trim(report, _int(limit, "limit", 1, MAX_LIMIT, 200), bool(include_excluded))


def extract_numbers(path=None, locale=None, min_digits=None, limit=None) -> dict:
    p = _path(path, "path")
    report = tieout.build_report(p, (), _choice(locale, "locale", ("auto", "en", "de"), "auto"),
                                 _int(min_digits, "min_digits", 1, 20, 1), extract_only=True)
    for key in ("sources",):
        report.pop(key, None)
    return _trim(report, _int(limit, "limit", 1, MAX_LIMIT, 500), True)


HANDLERS = {"tie_out": tie_out, "extract_numbers": extract_numbers}


# --------------------------------------------------------------- protocol
def reply(id_, result=None, error=None) -> None:
    msg = {"jsonrpc": "2.0", "id": id_}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _tool_error(id_, text: str) -> None:
    reply(id_, {"content": [{"type": "text", "text": text}], "isError": True})


def handle(req) -> None:
    if not isinstance(req, dict):
        reply(None, error={"code": -32600, "message": "invalid request: expected a JSON object"})
        return
    method = req.get("method")
    id_ = req.get("id")
    params = req.get("params") if isinstance(req.get("params"), dict) else {}
    if method == "initialize":
        reply(id_, {"protocolVersion": PROTOCOL, "capabilities": {"tools": {}},
                    "serverInfo": {"name": "tieout", "version": tieout.__version__,
                                   "description": "Tie every number in a report or deck back to the source cells it came from."}})
    elif method == "notifications/initialized" or (method == "ping" and id_ is None):
        return
    elif method == "ping":
        reply(id_, {})
    elif method == "tools/list":
        reply(id_, {"tools": TOOLS})
    elif method == "tools/call":
        name = params.get("name")
        fn = HANDLERS.get(name)
        if not fn:
            reply(id_, error={"code": -32602, "message": f"unknown tool {name!r}"})
            return
        args = params.get("arguments")
        if args is None:
            args = {}
        if not isinstance(args, dict):
            _tool_error(id_, "bad arguments: expected an object")
            return
        try:
            result = fn(**args)
        except ArgumentError as e:
            _tool_error(id_, f"bad arguments: {e}")
            return
        except TypeError as e:
            _tool_error(id_, f"bad arguments: {e}")
            return
        except Exception as e:  # a reader bug must not take the server down
            _tool_error(id_, f"{type(e).__name__}: {tieout.mask(str(e))}")
            return
        deliverable_failed = any(err["file"] == result.get("deliverable", {}).get("path") for err in result["errors"])
        if deliverable_failed:
            _tool_error(id_, "; ".join(err["error"] for err in result["errors"]))
            return
        reply(id_, {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=1)}],
                    "structuredContent": result, "isError": False})
    elif id_ is not None:
        reply(id_, error={"code": -32601, "message": f"method not found: {method}"})


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
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
