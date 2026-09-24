"""Command line: `ghg-factors-mcp` alone serves MCP on stdio; subcommands answer in the terminal.

  ghg-factors-mcp search "diesel average biofuel blend" --unit litres
  ghg-factors-mcp get desnz-2026:1_101_1011_8_1
  ghg-factors-mcp convert 1000 litres desnz-2026:1_101_1011_8_1
  ghg-factors-mcp grid Poland --year 2025
  ghg-factors-mcp sources
  ghg-factors-mcp refresh            (the only command that uses the network)

Exit codes: 0 answered, 1 not found or refused, 2 usage error, unreadable
snapshot, or a source that could not be refreshed.
"""
from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

from . import VERSION
from . import factors as F
from . import protocol
from . import provenance as P


def _print(text: str = "") -> None:
    print(text)


def _value(v) -> str:
    return "blank (not published)" if v is None else F._plain(Decimal(repr(v)))


def _attribution(result: dict) -> None:
    for line in result.get("attribution") or []:
        _print(line)


def render_search(r: dict) -> None:
    q = r["query"]
    filters = ", ".join(f"{k} {q[k]}" for k in ("scope", "unit") if q.get(k))
    _print(f"DESNZ {q['year']} (UK): {r['returned']} of {r['matches']} matches for {q['text']!r}"
           + (f" ({filters})" if filters else ""))
    for x in r["results"]:
        _print("")
        _print(f"{x['factor_id']}  {x['scope']}  {x['name']}")
        line = f"    {_value(x['value'])} {x['unit'] if x['value'] is not None else ''}".rstrip()
        gases = x.get("gases") or {}
        if gases:
            line += "   " + ", ".join(f"{g} {_value(v['value'])}" for g, v in gases.items())
        _print(line)
        for n in x.get("notes", []):
            _print(f"    note: {n}")
    _print("")
    _print(r["note"])
    _attribution(r)


def render_factor(r: dict) -> None:
    if "answers" in r or r.get("source") in ("Ember", "Umweltbundesamt"):
        render_grid(r)
        return
    if not r.get("found"):
        _print(r.get("reason", "not found"))
        return
    _print(f"{r['factor_id']}  {r['scope']}  {r['name']}")
    _print(f"value: {_value(r['value'])} {r['unit'] if r['value'] is not None else ''}".rstrip())
    for g, v in (r.get("gases") or {}).items():
        _print(f"  {g}: {_value(v['value'])} {v['unit']}  ({v['factor_id']})")
    if r.get("total"):
        _print(f"  total: {_value(r['total']['value'])} {r['total']['unit']}  ({r['total']['factor_id']})")
    for o in r.get("same_id_other_years", []):
        change = f", {o['change_to_this_year_pct']:+.2f}% to {r['year']}" if "change_to_this_year_pct" in o else ""
        _print(f"  {o['factor_id']}: {_value(o['value'])} {o['unit']}{change}")
    for n in r.get("notes", []):
        _print(f"note: {n}")
    _attribution(r)


def render_convert(r: dict) -> None:
    _print(f"{r['result']['value_text']} {r['result']['unit']}")
    _print(f"  {r['arithmetic']}")
    for g, v in (r.get("gases") or {}).items():
        _print(f"  {g}: {v['arithmetic']}")
    if r.get("gases_note"):
        _print(f"  {r['gases_note']}")
    _print(f"factor: {r['factor']['factor_id']}  {r['factor'].get('name') or r['factor'].get('area')}")
    _print(r["derived"])
    for n in r.get("notes", []):
        _print(f"note: {n}")
    _attribution(r)


def render_grid(r: dict) -> None:
    for a in r.get("answers", [r]):
        if not a.get("found"):
            _print(a.get("reason", "not found"))
            for n in a.get("nearest_years_with_value", []):
                _print(f"  nearest with a value: {n['year']}: {n['value']} ({n['factor_id']})")
            if a.get("did_you_mean"):
                _print("  did you mean: " + ", ".join(a["did_you_mean"]))
            _print("")
            continue
        _print(f"{a['factor_id']}  {a['area']} {a['year']}: {a['value_text']} {a['unit']}"
               f" (= {_value(a['kg_per_kwh'])} kg per kWh)  ({a['source']})")
        _print(f"basis: {a['basis']}")
        _print(a["scope2"])
        if a.get("see_also"):
            s = a["see_also"]
            _print(f"see also: {s['factor_id']} = {_value(s['value'])} {s['unit']}. {s['note']}")
        if a.get("other_areas_matching"):
            _print("other areas matching: " + ", ".join(a["other_areas_matching"]))
        for n in a.get("notes", []):
            _print(f"note: {n}")
        _attribution(a)
        _print("")
    if r.get("note"):
        _print(r["note"])


def render_sources(r: dict) -> None:
    for s in r["sources"]:
        _print(f"{s['id']}: {s['name']}")
        _print(f"  licence: {s['licence']}  {s.get('licence_url') or s.get('terms_url')}")
        _print(f"  retrieved {s['retrieved']}, {s['rows']} rows, raw file sha256 {s['raw_sha256']}")
        _print(f"  {s['raw_url']}")
        _print(f"  cite: {s['attribution']}")
    _print("")
    _print("Not included, on licence grounds:")
    for x in r["excluded"]:
        _print(f"  {x['source']}: {x['reason']} ({x['evidence_url']}, checked {x['checked']})")
    _print("")
    _print(r["scope2"]["location_based"])
    _print(f"snapshot: {r['data_dir']}")


def _checkout_data_dir() -> Path | None:
    root = Path(__file__).resolve().parent.parent
    if (root / "pyproject.toml").is_file() and (root / "data").is_dir():
        return root / "data"
    return None


def cmd_refresh(args) -> int:
    from . import refresh as R  # the only import that leads to the network
    out = Path(args.out) if args.out else _checkout_data_dir()
    if out is None:
        print("refresh: pass --out DIR (the installed package's own data is not rewritten); "
              "then set GHG_FACTORS_DATA=DIR so the server reads it", file=sys.stderr)
        return 2
    only = {s.strip().lower() for s in args.only.split(",") if s.strip()} if args.only else None
    valid = {"desnz", "ember", "uba"} | {f"desnz-{y}" for y in args.years}
    if only and not only <= valid:
        print(f"refresh: --only takes {', '.join(sorted(valid))}", file=sys.stderr)
        return 2
    report = R.refresh(out, only=only, years=tuple(args.years))
    for key, m in report["ok"].items():
        print(f"{key}: ok, {m['rows']} rows, raw sha256 {m['raw_sha256'][:16]}..., retrieved {m['retrieved']}")
    for key, why in report["failed"].items():
        print(f"{key}: FAILED, previous snapshot kept: {why}")
    print(f"snapshot: {report['out']}")
    return 2 if report["failed"] else 0


def _years(text: str) -> list[int]:
    try:
        years = [int(y) for y in text.split(",") if y.strip()]
    except ValueError:
        raise argparse.ArgumentTypeError("years look like 2026,2025") from None
    if not years or any(y < 2000 or y > 2100 for y in years):
        raise argparse.ArgumentTypeError("years look like 2026,2025")
    return years


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ghg-factors-mcp", description=(
        "GHG conversion factors with provenance: DESNZ (UK), Ember and UBA grid intensities. "
        "Without a command it runs the MCP server on stdio."))
    p.add_argument("--version", action="version", version=f"ghg-factors-mcp {VERSION}")
    sub = p.add_subparsers(dest="command")
    sub.add_parser("serve", help="run the MCP server on stdio (the default)")
    s = sub.add_parser("search", help="search DESNZ factors by activity words")
    s.add_argument("text")
    s.add_argument("--scope")
    s.add_argument("--year", type=int)
    s.add_argument("--unit")
    s.add_argument("--limit", type=int, default=10)
    g = sub.add_parser("get", help="one factor by ID")
    g.add_argument("factor_id")
    c = sub.add_parser("convert", help="amount x factor, with the arithmetic")
    c.add_argument("amount")
    c.add_argument("unit")
    c.add_argument("factor_id")
    gr = sub.add_parser("grid", help="grid carbon intensity by country and year")
    gr.add_argument("country")
    gr.add_argument("--year", type=int)
    gr.add_argument("--source", default="ember", choices=["ember", "uba", "all"])
    sub.add_parser("sources", help="sources, licences, retrieval dates, excluded sources")
    r = sub.add_parser("refresh", help="download and rebuild the snapshot (network)")
    r.add_argument("--out", help="directory to write (default: data/ of a source checkout)")
    r.add_argument("--only", help="comma-separated: desnz, desnz-2026, ember, uba")
    r.add_argument("--desnz-years", dest="years", type=_years, default=list(P.DESNZ_YEARS),
                   help="DESNZ sets to fetch, e.g. 2026,2025")
    for sp in (s, g, c, gr, sub.choices["sources"]):
        sp.add_argument("--json", action="store_true", help="print the structured result")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command in (None, "serve"):
        if getattr(sys.stdin, "isatty", lambda: False)():
            print("ghg-factors-mcp: MCP server on stdio, waiting for JSON-RPC messages "
                  "(see --help for the command line)", file=sys.stderr)
        return protocol.serve()
    if args.command == "refresh":
        return cmd_refresh(args)
    try:
        sys.stdout.reconfigure(errors="replace")  # a console code page without "×" must not crash an answer
    except (AttributeError, ValueError):
        pass
    try:
        if args.command == "search":
            result, render = F.search_factors(args.text, args.scope, args.year, args.unit, args.limit), render_search
        elif args.command == "get":
            result, render = F.get_factor(args.factor_id), render_factor
        elif args.command == "convert":
            result, render = F.convert(args.amount, args.unit, args.factor_id), render_convert
        elif args.command == "grid":
            result, render = F.grid_intensity(args.country, args.year, args.source), render_grid
        else:
            result, render = F.sources(), render_sources
    except F.Refused as e:
        if getattr(args, "json", False):
            print(json.dumps({"refused": True, "reason": str(e), **e.details}, ensure_ascii=False, indent=1))
        else:
            print(f"refused: {e}")
        return 1
    except F.SnapshotError as e:
        print(f"ghg-factors-mcp: {e}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
    else:
        render(result)
    found = result.get("found", True) and (args.command != "search" or result["results"])
    return 0 if found else 1


if __name__ == "__main__":
    raise SystemExit(main())
