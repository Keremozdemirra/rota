"""Command line: `cbam-mcp` alone serves MCP on stdio; subcommands answer in the terminal.

    cbam-mcp scope 7208 51 20
    cbam-mcp value 7601 10 00 India
    cbam-mcp compare 7601 10 00 India Türkiye "United States"
    cbam-mcp describe 2716 00 00 [--year 2025]
    cbam-mcp sources
    cbam-mcp refresh [--check-oj] [--data-dir DIR]

Add --json for the same structure the MCP tools return. Exit codes: 0 answered,
2 the question or the data could not be read (refresh: see refresh.py).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import textwrap
from pathlib import Path

from . import __version__, lookup, mcp_stdio, refresh
from .codes import InputError

_CODE_TOKEN = re.compile(r"^(?:ex|cn)?[0-9.\-]+$", re.IGNORECASE)


def split_code(tokens: list[str]) -> tuple[str, list[str]]:
    """Leading numeric tokens are the CN code ("7601 10 00"), the rest are countries."""
    code, rest = [], list(tokens)
    while rest and (_CODE_TOKEN.match(rest[0]) or (not code and rest[0].lower() == "ex")):
        code.append(rest.pop(0))
    if not code:
        raise InputError("start with a CN code, e.g. 7601 10 00")
    return " ".join(code), rest


def _wrap(label: str, text: str, width: int = 100) -> str:
    pad = " " * 20
    body = textwrap.fill(str(text), width=width, initial_indent=pad, subsequent_indent=pad)
    return f"  {label:<18}" + body[20:]


def _num(v) -> str:
    return "-" if v is None else f"{v:.3f}"


def _legal_lines(r: dict) -> list[str]:
    lines = [_wrap("Legally binding", "no. Binding text: " + r["legally_binding_source"])]
    status = r.get("legal_status_of_data")
    if isinstance(status, dict):
        lines.append(_wrap("Commission says", f"\"{status['quote']}\""))
    lines.append(_wrap("Data", r["data_version"]))
    if r.get("checked_against_official_journal"):
        lines.append(_wrap("Checked", r["checked_against_official_journal"]))
    for w in r.get("warnings") or []:
        lines.append(_wrap("Warning", w))
    lines.append("  " + r["attribution"])
    return lines


def render_scope(r: dict) -> str:
    out = [f"{r['cn_code']}: {r['status'].replace('_', ' ')}"]
    if r.get("annex_i_line"):
        line = r["annex_i_line"]
        text = f"{line['cn_code']} – {line['text']}"
        if line.get("except"):
            text += " (except " + "; ".join(line["except"]) + ")"
        out.append(_wrap("Annex I line", text))
        out.append(_wrap("Goods category", r.get("goods_category")))
        out.append(_wrap("Greenhouse gases", r.get("greenhouse_gases")))
    elif r.get("annex_i_lines_below"):
        out.append(_wrap("Annex I lines", "; ".join(f"{x['cn_code']} – {x['text']} ({x['goods_category']})"
                                                   for x in r["annex_i_lines_below"])))
    out.append(_wrap("Why", r["explanation"]))
    if r.get("annex_ii"):
        out.append(_wrap("Annex II", f"{r['annex_ii']['status']} in Annex II. Article 7(1): \"{r['annex_ii']['meaning']}\""))
    cn = r.get("cn") or {}
    if cn.get("found"):
        out.append(_wrap("CN 2026", f"{cn['cn_code']} {cn['label']}" + (f". {cn['self_explanatory_text']}"
                                                                       if cn.get("self_explanatory_text") else "")))
    dm = r.get("de_minimis")
    if dm:
        if dm["applies_to_these_goods"]:
            out.append(_wrap("De minimis", f"Annex VII, point 1: \"{dm['annex_vii_point_1']}\" {dm['note']}"))
        else:
            out.append(_wrap("De minimis", f"Article 2a(4): \"{dm['article_2a_4']}\""))
    sub = r.get("subcodes")
    if sub:
        c = sub["counts"]
        out.append(_wrap("Sub-codes", f"{sub['cn_version']}: {c['in_scope']} in scope, {c['partially_in_scope']} "
                                      f"partially, {c['not_in_scope']} not in scope"
                                      + (" (lists truncated)" if sub["truncated"] else "")))
        for key, tag in (("in_scope", "in"), ("partially_in_scope", "part"), ("not_in_scope", "not")):
            for item in sub.get(key, []):
                extra = f" [excluded by {item['excluded_by']}]" if item.get("excluded_by") else ""
                extra += f" [{item['ex_code']}]" if item.get("ex_code") else ""
                out.append(f"    {tag:<5} {item['cn_code']:<11} {item['description'][:70]}{extra}")
    out += _legal_lines(r)
    return "\n".join(out)


def _value_block(item: dict) -> list[str]:
    head = f"  table line {item['table_line']} {item['description']} ({item['goods_category']})"
    out = [head]
    if not item.get("found"):
        out.append("    no values")
        return out
    ap = item["as_published"]
    out.append(f"    total     {_num(item['total']):>7}   as published: {ap['total']}")
    out.append(f"    direct    {_num(item['direct']):>7}   as published: {ap['direct']}")
    out.append(f"    indirect  {_num(item['indirect']):>7}   as published: {ap['indirect']}")
    routes = ", ".join(f"({p['code']}) {p['meaning']}" for p in item.get("production_route") or []) or "none indicated"
    out.append(f"    route     {routes}")
    out.append(f"    from      table '{item['values_from_table']}'")
    if item.get("fallback"):
        fb = item["fallback"]
        out.append(textwrap.fill(f"because {fb['reason']}. {fb['rule']['citation']}: \"{fb['rule']['quote']}\"",
                                 width=100, initial_indent="    ", subsequent_indent="    "))
    a4 = item.get("annex_iv_highest_default")
    if a4:
        out.append(f"    Annex IV  {_num(a4['value']):>7}   (precursor whose country of production cannot be identified)")
    return out


def render_value(r: dict) -> str:
    out = [f"{r['cn_code']} from {r['country']}: {r.get('status', '').replace('_', ' ')}, unit {r['unit']}"]
    if r.get("explanation"):
        out.append(_wrap("Why", r["explanation"]))
    for item in r["lines"]:
        out += _value_block(item)
    for n in r.get("notes") or []:
        if isinstance(n, str):
            out.append(_wrap("Note", n))
    out += _legal_lines(r)
    return "\n".join(out)


def render_compare(r: dict) -> str:
    out = [f"{r['cn_code']}: default values in {r['unit']}"]
    for line in r["lines"]:
        out.append(f"  table line {line['table_line']} {line['description']} ({line['goods_category']})")
        out.append(f"    {'country':<34} {'total':>7} {'direct':>7} {'indirect':>8}  route  values from")
        for c in line["by_country"]:
            if "status" in c:
                out.append(f"    {c['country'][:34]:<34} {c['status'].replace('_', ' ')}")
                continue
            ap = c.get("as_published") or {}
            route = "/".join(p["code"] for p in c.get("production_route") or []) or "-"
            out.append(f"    {c['country'][:34]:<34} {_num(c.get('total')):>7} {_num(c.get('direct')):>7} "
                       f"{(ap.get('indirect') or '-'):>8}  {route:<5}  {c.get('values_from_table')}")
        o = line["other_countries_and_territories"]
        out.append(f"    {'Other countries and territories':<34} {_num(o.get('total')):>7} {_num(o.get('direct')):>7}")
        a4 = line.get("annex_iv_highest_default")
        if a4:
            out.append(f"    {'Annex IV (origin unknown)':<34} {_num(a4['value']):>7}")
    for p in r.get("countries_not_recognised") or []:
        out.append(_wrap("Not recognised", p))
    for n in r.get("notes") or []:
        if isinstance(n, str):
            out.append(_wrap("Note", n))
    out += _legal_lines(r)
    return "\n".join(out)


def render_describe(r: dict) -> str:
    if not r["found"]:
        out = [f"{r['cn_code']} (CN {r['year']}): not found", _wrap("Why", r["explanation"])]
    else:
        out = [f"{r['cn_code']} (CN {r['year']}): {r['label']}"]
        if r.get("self_explanatory_text"):
            out.append(_wrap("Self-explanatory", r["self_explanatory_text"]))
        out.append(_wrap("Hierarchy", " > ".join(f"{h['cn_code'] or ''} {h['label']}".strip() for h in r["hierarchy"])))
        for sub in r.get("sub_codes") or []:
            out.append(f"    {sub['cn_code'] or '':<11} {sub['label'][:80]}")
        other = [k for k in r if k.startswith("in_cn_")]
        for k in other:
            v = r[k]
            out.append(_wrap(k.replace("in_cn_", "CN "), v if isinstance(v, str) else f"label: {v['label']}"))
    out.append(_wrap("Legally binding", "no. Binding text: " + r["legally_binding_source"]))
    out.append(_wrap("Data", r["data_version"]))
    for w in r.get("warnings") or []:
        out.append(_wrap("Warning", w))
    out.append("  " + r["attribution"])
    return "\n".join(out)


def render_sources(r: dict) -> str:
    out = []
    for d in r["datasets"]:
        out.append(d["name"])
        out.append(_wrap("URL", d["url"]))
        out.append(_wrap("Version", d.get("version") or d.get("subset") or ""))
        out.append(_wrap("Retrieved", d["retrieved"]))
        if d.get("sha256"):
            out.append(_wrap("SHA-256", d["sha256"]))
        out.append(_wrap("Rows", ", ".join(f"{k} {v}" for k, v in d["rows"].items())))
        out.append(_wrap("Binding text", d["legally_binding_source"]))
        out.append(_wrap("Licence", f"{d['licence']['name']} ({d['licence']['terms']})"))
        if d.get("official_journal_check"):
            c = d["official_journal_check"]
            out.append(_wrap("OJ check", f"{c['checked']}: {c['rows_identical']}/{c['rows_compared']} lines, "
                                         f"{c['annex_iv_identical']}/{c['annex_iv_compared']} Annex IV lines identical "
                                         f"to {c['celex']}"))
        out.append("")
    later = r.get("later_acts")
    if later:
        for base, acts in later["acts"].items():
            out.append(_wrap(f"Acts on {base}", "; ".join(f"{a['celex']} {a['relation']} {a['date']}" for a in acts)
                             + f" (checked {later['checked']})"))
    out.append(f"Data directory: {r['data_directory']}")
    return "\n".join(out)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cbam-mcp", description="EU CBAM scope, default values and CN descriptions. "
                                "Without a command: MCP server on stdio.")
    p.add_argument("--version", action="version", version=f"cbam-mcp {__version__}")
    sub = p.add_subparsers(dest="command")
    sub.add_parser("serve", help="MCP server on stdio (the default)")
    s = sub.add_parser("scope", help="is a CN code in CBAM scope?")
    s.add_argument("code", nargs="+")
    s.add_argument("--limit", type=int, default=50)
    v = sub.add_parser("value", help="default value for a CN code and a country of origin")
    v.add_argument("words", nargs="+", help="CN code, then the country")
    c = sub.add_parser("compare", help="default values for a CN code across countries")
    c.add_argument("words", nargs="+", help="CN code, then countries (quote names with spaces)")
    d = sub.add_parser("describe", help="CN 2026 or 2025 description")
    d.add_argument("code", nargs="+")
    d.add_argument("--year", type=int, default=2026, choices=(2025, 2026))
    sub.add_parser("sources", help="sources, versions, licences")
    r = sub.add_parser("refresh", help="rebuild the data files from the sources")
    r.add_argument("--data-dir", type=Path, default=None, help="where to write (default: the package's data directory)")
    r.add_argument("--check-oj", action="store_true", help="also compare every value with the Official Journal text (downloads 16 MB)")
    r.add_argument("--only", choices=("annex", "values", "cn"), action="append")
    r.add_argument("--excel-url", default=refresh.EXCEL_URL)
    for sp in (s, v, c, d, sub.choices["sources"]):
        sp.add_argument("--json", action="store_true", help="print the JSON the MCP tool returns")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.command in (None, "serve"):
        if args.command is None and sys.stdin.isatty():
            print("cbam-mcp: MCP server on stdio, waiting for JSON-RPC. For the command line: cbam-mcp --help",
                  file=sys.stderr)
        return mcp_stdio.serve()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    if args.command == "refresh":
        target = args.data_dir or lookup.data_dir()
        try:
            return refresh.run(target, only=args.only, check_oj=args.check_oj, excel_url=args.excel_url)
        except OSError as e:
            print(f"cbam-mcp refresh: {e}", file=sys.stderr)
            return 2
    try:
        if args.command == "scope":
            result, render = lookup.cbam_scope(" ".join(args.code), args.limit), render_scope
        elif args.command == "value":
            code, rest = split_code(args.words)
            if not rest:
                raise InputError("add the country after the code, e.g. 7601 10 00 India")
            result, render = lookup.default_value(code, " ".join(rest)), render_value
        elif args.command == "compare":
            code, rest = split_code(args.words)
            countries = [x.strip() for w in rest for x in w.split(",") if x.strip()]
            if not countries:
                raise InputError("add countries after the code, e.g. 7601 10 00 India Türkiye")
            result, render = lookup.compare_origins(code, countries), render_compare
        elif args.command == "describe":
            result, render = lookup.cn_describe(" ".join(args.code), args.year), render_describe
        else:
            result, render = lookup.sources(), render_sources
    except InputError as e:
        print(f"cbam-mcp: {e}", file=sys.stderr)
        return 2
    except lookup.DataError as e:
        print(f"cbam-mcp: data unavailable: {e}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=1) if args.json else render(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
