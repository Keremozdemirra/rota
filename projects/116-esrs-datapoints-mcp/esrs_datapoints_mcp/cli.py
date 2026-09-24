"""Command line. With no command it runs the MCP server on stdio, which is what MCP clients start.

Exit codes: 0 answered, 1 nothing found (no match, unknown ID or DR code),
2 could not answer (no index, missing or unreadable workbook, bad argument).
"""
from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .store import Store
from .text import WRAP_CLOSE, WRAP_OPEN, clean, is_wrapped
from .tools import DEFAULT_MIN_SIMILARITY, Service, ToolError
from .xlsx import XlsxError


def _plain(value) -> str:
    """Unwrap for the human table; the whole table is wrapped once instead."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, list):
        return ", ".join(_plain(v) for v in value)
    s = str(value)
    return s[len(WRAP_OPEN):-len(WRAP_CLOSE)] if is_wrapped(s) else s


def _cut(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def _source_lines(src: dict) -> list:
    lines = [f"Source: {v['version']} = {v['title']} [file {v['file']}, sha256 {v['sha256'][:12]}]"
             for v in src.get("versions", [])]
    lines.append(src["content"])
    lines.append(src["status"])
    for act in src.get("binding_text", []):
        if act:
            lines.append(f"Binding text: {act['act']} ({act['eli']})")
    return lines


def _flags(dp: dict) -> str:
    return "".join(ch for ch, on in (("V", dp.get("voluntary")), ("P", dp.get("phase_in")),
                                     ("C", dp.get("conditional"))) if on)


def _table(dps: list) -> list:
    rows = [("version", "id", "dr", "para", "flags", "data type", "name")]
    for dp in dps:
        rows.append((dp["version"], _plain(dp["id"]), _plain(dp.get("dr")), _cut(_plain(dp.get("paragraph")), 12),
                     _flags(dp), _cut(_plain(dp.get("data_type")), 20), _cut(_plain(dp.get("name")), 90)))
    widths = [max(len(r[i]) for r in rows) for i in range(6)]
    out = ["  ".join(r[i].ljust(widths[i]) for i in range(6)) + "  " + r[6] for r in rows]
    return [WRAP_OPEN.rstrip()] + out + [WRAP_CLOSE, "flags: V voluntary, P subject to phase-in, C conditional"]


def render(command: str, result: dict) -> str:
    lines = []
    if command == "status":
        for v in result["indexed"]:
            lines.append(f"{v['version']}: {v['title']}")
            lines.append(f"  file {v['path']} (sha256 {v['sha256'][:12]}, official file: {_plain(v['official_file'])},"
                         f" present: {_plain(v['source_file_present'])})")
            lines.append(f"  {v['datapoints']} datapoints: "
                         + ", ".join(f"{k} {n}" for k, n in v["by_standard"].items()))
            if v["columns_missing"]:
                lines.append(f"  columns this file lacks: {', '.join(v['columns_missing'])}")
        if not result["indexed"]:
            lines.append("No workbook indexed. " + result["how_to_index"])
        for p in result["problems"]:
            lines.append(f"problem: {p['path']}: {p['error']}")
        lines.append(f"cache: {result['cache_dir']}")
        lines.append("Official files this tool reads:")
        for f in result["supported_files"]:
            lines.append(f"  {f['title']}\n    {f['url']}")
    elif command == "search":
        lines.append(f"{result['matches']} match(es), showing {result['returned']}")
        if result["datapoints"]:
            lines += _table(result["datapoints"])
        lines += [f"note: {n}" for n in result["notes"]]
    elif command == "datapoint":
        if not result["found"]:
            lines.append(f"{_plain(result['id'])}: not found"
                         + (f"; close matches: {_plain(result.get('close_matches'))}" if result.get("close_matches")
                            else ""))
        lines.append(WRAP_OPEN.rstrip())
        for dp in result["datapoints"]:
            for k, v in dp.items():
                if isinstance(v, dict):
                    v = "; ".join(f"{kk}: {_plain(vv)}" for kk, vv in v.items() if vv)
                elif isinstance(v, list) and v and isinstance(v[0], dict):
                    v = "; ".join(f"{_plain(x['id'])} ({_plain(x.get('name'))})" for x in v)
                lines.append(f"{k}: {_plain(v)}")
            lines.append("")
        for x in result.get("listed_in_ig3_mapping_of", []):
            lines.append(f"listed in the IG 3 mapping of {_plain(x['id'])} ({x['version']}): {_plain(x.get('name'))}")
        lines.append(WRAP_CLOSE)
    elif command == "dr":
        if not result["found"]:
            lines.append(f"{_plain(result['disclosure_requirement'])}: not found"
                         + (f"; close matches: {_plain(result.get('close_matches'))}"
                            if result.get("close_matches") else ""))
        for v in result["versions"]:
            c = v["counts"]
            lines.append(f"{v['version']}: {c['datapoints']} datapoints ({c['voluntary']} voluntary, "
                         f"{c['conditional']} conditional, {c['phase_in']} phase-in); text: {v['legal_text']['eli']}")
            lines += _table(v["datapoints"])
    elif command == "diff":
        s = result["summary"]
        lines.append(f"{result['standard']}: {result['from_version']} ({s['old_datapoints']}) -> "
                     f"{result['to_version']} ({s['new_datapoints']})")
        lines.append("pairs by method: " + (", ".join(f"{k} {n}" for k, n in s["pairs_by_method"].items()) or "none")
                     + f"; changed {s['pairs_changed']}, unchanged {s['pairs_unchanged']}; "
                       f"removed {s['removed']}, added {s['added']}")
        lines.append(WRAP_OPEN.rstrip())
        for p in result["pairs"]:
            score = f" {p['score']}" if "score" in p else ""
            lines.append(f"{p['method']}{score}: {_plain(p['old_id'])} -> {_plain(p['new_id'])}"
                         f" [{', '.join(p['changed_fields']) or 'unchanged'}]")
        for x in result["removed"]:
            lines.append(f"removed: {_plain(x['id'])}  {_cut(_plain(x.get('name')), 90)}")
        for y in result["added"]:
            lines.append(f"added: {_plain(y['id'])}  {_cut(_plain(y.get('name')), 90)}")
        lines.append(WRAP_CLOSE)
        if result.get("truncated"):
            lines.append("lists cut at --limit")
    elif command == "sources":
        for f in result["official_files"]:
            lines.append(f"{f['title']}\n  page {f['page']}\n  file {f['url']}\n  sha256 {f['sha256']} "
                         f"(checked {f['checked']})")
        t = result["efrag_terms"]
        lines.append(f"EFRAG terms ({t['url']}, checked {t['checked']}): {t['says']}. {t['consequence']}")
        for key, act in result["legal_acts"].items():
            extra = f"; in force {act['entry_into_force']}; applies {act['applies']}" if "applies" in act else ""
            lines.append(f"{act['title']}: OJ {act['official_journal']}{extra}. {act['eli']}")
        lines.append(result["not_affiliated"])
        return "\n".join(lines)
    if "source" in result:
        lines += _source_lines(result["source"])
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="esrs-datapoints-mcp",
        description="Query EFRAG's ESRS datapoint list from your own downloaded copy. Without a command, runs the "
                    "MCP server on stdio.")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    ap.add_argument("--cache-dir", help="where indexes are kept (default: your user cache directory)")
    sub = ap.add_subparsers(dest="command")
    sub.add_parser("serve", help="run the MCP server on stdio (the default)")
    p = sub.add_parser("index", help="parse workbooks you downloaded and keep their index")
    p.add_argument("paths", nargs="+")
    p = sub.add_parser("status", help="what is indexed and where to download the official files")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("search", help="find datapoints by words in their name, with filters")
    p.add_argument("text", nargs="?", default="")
    p.add_argument("--standard")
    p.add_argument("--dr", dest="disclosure_requirement")
    p.add_argument("--data-type")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--voluntary", dest="voluntary", action="store_const", const=True)
    g.add_argument("--not-voluntary", dest="voluntary", action="store_const", const=False)
    g = p.add_mutually_exclusive_group()
    g.add_argument("--phase-in", dest="phase_in", action="store_const", const=True)
    g.add_argument("--no-phase-in", dest="phase_in", action="store_const", const=False)
    p.add_argument("--in", dest="version", metavar="VERSION")
    p.add_argument("--limit", type=int, default=25)
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("datapoint", help="one datapoint by ID")
    p.add_argument("id")
    p.add_argument("--in", dest="version", metavar="VERSION")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("dr", help="all datapoints of a disclosure requirement")
    p.add_argument("dr_code")
    p.add_argument("--in", dest="version", metavar="VERSION")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("diff", help="what changed for a standard between two indexed versions")
    p.add_argument("standard")
    p.add_argument("--from", dest="from_version")
    p.add_argument("--to", dest="to_version")
    p.add_argument("--min-similarity", type=float, default=DEFAULT_MIN_SIMILARITY)
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("sources", help="official download pages, file fingerprints, licence and legal acts")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("forget", help="remove an indexed version from the cache")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("key", nargs="?")
    g.add_argument("--all", action="store_true")
    return ap


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    args = build_parser().parse_args(argv)
    if args.command in (None, "serve"):
        from .mcp import Server
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stdin.reconfigure(encoding="utf-8", errors="replace")
        if sys.stdin.isatty():
            print("esrs-datapoints-mcp: waiting for MCP JSON-RPC messages on stdin. "
                  "For the command line, run: esrs-datapoints-mcp --help", file=sys.stderr)
        return Server(Service(Store(args.cache_dir))).serve()
    store = Store(args.cache_dir)
    try:
        if args.command == "index":
            code = 0
            for path in args.paths:
                try:
                    ix = store.add(path, origin="cli")
                    print(f"indexed {ix['key']}: {len(ix['datapoints'])} datapoints from {clean(path, 500)}")
                    print(f"  {ix['title']}")
                    if ix.get("columns_missing"):
                        print(f"  columns this file lacks: {', '.join(ix['columns_missing'])}")
                except (XlsxError, OSError) as e:
                    print(f"error: {clean(str(e), 1000)}", file=sys.stderr)
                    code = 2
            for p in store.problems:
                print(f"warning: {p['error']}", file=sys.stderr)
            return code
        if args.command == "forget":
            gone = store.forget(None if args.all else args.key)
            print("removed: " + (", ".join(gone) if gone else "nothing"))
            return 0 if gone else 1
        service = Service(store)
        if args.command == "status":
            result = service.index_status()
        elif args.command == "search":
            result = service.search(args.text, args.standard, args.disclosure_requirement, args.data_type,
                                    args.voluntary, args.phase_in, args.version, args.limit)
        elif args.command == "datapoint":
            result = service.datapoint(args.id, args.version)
        elif args.command == "dr":
            result = service.disclosure_requirement(args.dr_code, args.version)
        elif args.command == "diff":
            result = service.diff_versions(args.standard, args.from_version, args.to_version,
                                           args.min_similarity, args.limit)
        else:
            result = service.sources()
    except (ToolError, XlsxError) as e:
        print(f"error: {clean(str(e), 2000)}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=1) if args.json else render(args.command, result))
    if args.command == "search" and not result["matches"]:
        return 1
    if args.command in ("datapoint", "dr") and not result["found"]:
        return 1
    if args.command == "status" and not result["indexed"]:
        return 2
    return 0
