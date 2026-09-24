"""Command line: the MCP server (default), the five lookups, and refresh.

  eudr-scope-mcp                       MCP server on stdio
  eudr-scope-mcp scope 1801 00 00      is this CN code in Annex I?
  eudr-scope-mcp codes wood            Annex I entries of one commodity
  eudr-scope-mcp dates micro           application dates by operator type
  eudr-scope-mcp country BR            country risk level
  eudr-scope-mcp sources               legal acts, versions, hashes, licence
  eudr-scope-mcp refresh --out data    rebuild the snapshot from CELLAR

Exit codes: lookups 0 answered, 2 could not answer (bad input, missing
snapshot); refresh 0 written and verified, 1 written with parts marked
unverified, 2 failed and nothing written.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import __version__, lookup, protocol


def _print(text: str) -> None:
    try:
        sys.stdout.write(text + "\n")
    except UnicodeEncodeError:
        sys.stdout.write(text.encode("ascii", "backslashreplace").decode("ascii") + "\n")


def _footer(r: dict) -> list:
    if r.get("consolidated_version"):
        applied = r.get("amendments_applied_by_this_tool") or []
        lines = [f"Checked: {r.get('checked')} against consolidated text {r['consolidated_version']['celex']}"
                 + "".join(f" + {a['act']}" for a in applied)]
    else:
        lines = [f"Checked: {r.get('checked')} against {r['source_text']['celex']}"]
    if r.get("warning"):
        lines.append("Warning: " + r["warning"])
    lines += [r.get("attribution", ""), r.get("disclaimer", "")]
    return lines


def _clip(wrapped: str, limit: int = 200) -> str:
    """Shorten a long quoted note for the terminal; --json keeps the full text."""
    if len(wrapped) <= limit:
        return wrapped
    return wrapped[:limit - 3].rstrip() + "...>> (full text with --json)"


def _entry_line(v: dict) -> str:
    span = ""
    if v.get("valid_from"):
        span += f" from {v['valid_from']}"
    if v.get("valid_to"):
        span += f" until {v['valid_to']}"
    return f"  {v['annex_entry']} [{v['commodity']}]{span}: {v['description']}"


def render(command: str, r: dict) -> str:
    out = [r["answer"]]
    if command == "scope":
        for title, key in (("Annex I entry", "matches"), ("Listed under this code", "listed_under_this_code"),
                           ("Applies later", "applies_later"), ("Removed earlier", "removed_earlier")):
            if r.get(key):
                out.append(f"{title}:")
                for v in r[key]:
                    out.append(_entry_line(v))
                    out += [f"    {n}" for n in v["notes"]]
                    out.append(f"    source: {v['source']}" + (f"; removed by {v['removed_by']}" if v.get("removed_by") else ""))
        for n in r.get("table_notes", []):
            out.append(f"Table note {n['note']} ({n['applies_to']}): {_clip(n['text'])}")
        out.append(f"Legal basis: {r['legal_basis']}")
        out += [f"Note: {n}" for n in r.get("notes", [])]
    elif command == "codes":
        for title, key in (("Entries", "entries"), ("Apply later", "applies_later"),
                           ("Replaced or removed", "replaced_or_removed")):
            if r.get(key):
                out.append(f"{title}:")
                out += [_entry_line(v) for v in r[key]]
        for n in r.get("table_notes", []):
            out.append(f"Table note {n['note']} ({n['applies_to']}): {_clip(n['text'])}")
    elif command == "dates":
        for d in r["dates"]:
            out.append(f"  {d['applies_from']}  {d['provision']} - {d['who']} (set by {d['set_by']})")
            out += [f"      condition: {c}" for c in d.get("conditions", [])]
            if d.get("note"):
                out.append(f"      note: {d['note']}")
        out.append("Related dates:")
        out += [f"  {x['date']}  {x['provision']} - {x['what']}" for x in r["related_dates"]]
        out.append("History of Article 38:")
        out += [f"  {h['act']}, {h['provision']}: 38(2) {h['article_38_2']}, 38(3) {h['article_38_3']}"
                for h in r["history"]]
        for p in r.get("pending_proposals", []):
            out.append(f"Pending proposal {p['celex']} ({p['date']}): {p['note']}")
    elif command == "country":
        if r.get("basis"):
            out.append(f"Basis: {r['basis']['provision']}: {r['basis']['text']}")
    elif command == "sources":
        for a in r["acts"]:
            out.append(f"  {a['celex']}  {a['name']} - {a['role']}")
        for d in r["documents"]:
            out.append(f"  sha256 {d['sha256']}  {d['celex']} ({d['role']})")
        out.append(f"Licence: {r['licence']['cellar']}")
    return "\n".join(out + _footer(r))


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(prog="eudr-scope-mcp", description=(
        "EUDR (Regulation (EU) 2023/1115) scope and dates from a dated snapshot of the legal texts. "
        "Without a command, runs the MCP server on stdio."))
    parser.add_argument("--version", action="version", version=f"eudr-scope-mcp {__version__}")
    parser.add_argument("--data-dir", help=f"read the snapshot from this directory (or set {lookup.DATA_ENV})")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("serve", help="MCP server on stdio (the default)")
    p = sub.add_parser("scope", help="is a CN code in Annex I?")
    p.add_argument("cn_code", nargs="+", help="e.g. 1801 00 00, 18010000, 1801.00.00")
    p.add_argument("--date", help="YYYY-MM-DD (default today)")
    p = sub.add_parser("codes", help="Annex I entries of one commodity")
    p.add_argument("commodity", nargs="+", help="cattle, cocoa, coffee, oil palm, rubber, soya or wood")
    p.add_argument("--date", help="YYYY-MM-DD (default today)")
    p = sub.add_parser("dates", help="application dates by operator type")
    p.add_argument("operator_type", nargs="*", help="all (default), large, medium, sme, micro, small, trader, ...")
    p = sub.add_parser("country", help="country risk level")
    p.add_argument("country", nargs="+", help="ISO alpha-2, alpha-3 or English name")
    sub.add_parser("sources", help="legal acts, versions, hashes, licence")
    p = sub.add_parser("refresh", help="rebuild the snapshot from CELLAR (network)")
    p.add_argument("--out", required=True, help="directory to write the snapshot to, e.g. data")
    p.add_argument("--dry-run", action="store_true", help="fetch and check, write nothing")
    for name in ("scope", "codes", "dates", "country", "sources"):
        sub.choices[name].add_argument("--json", action="store_true", help="print the full answer as JSON")
    args = parser.parse_args(argv)
    if args.data_dir:
        os.environ[lookup.DATA_ENV] = args.data_dir
        lookup.reset_cache()

    if args.command in (None, "serve"):
        if sys.stdin.isatty():
            sys.stderr.write("eudr-scope-mcp: MCP server on stdio, waiting for JSON-RPC messages "
                             "(see --help for the command line)\n")
        return protocol.serve()
    if args.command == "refresh":
        from . import refresh
        return refresh.run(args.out, dry_run=args.dry_run, log=lambda m: sys.stderr.write(m + "\n"))

    try:
        if args.command == "scope":
            r = lookup.eudr_scope(" ".join(args.cn_code), args.date)
        elif args.command == "codes":
            r = lookup.commodity_codes(" ".join(args.commodity), args.date)
        elif args.command == "dates":
            r = lookup.application_dates(" ".join(args.operator_type) or "all")
        elif args.command == "country":
            r = lookup.country_risk(" ".join(args.country))
        else:
            r = lookup.sources()
    except (lookup.InputError, lookup.DataError) as e:
        sys.stderr.write(f"eudr-scope-mcp: {e}\n")
        return 2
    _print(json.dumps(r, ensure_ascii=False, indent=1) if args.json else render(args.command, r))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
