"""Command line: the same six tools, as tables for people or JSON for scripts.

With no subcommand and stdin not a terminal (an MCP client starting it, which
is what `uvx climate-trace-mcp` in an MCP config does), it runs the MCP server.

Exit codes: 0 answered; 1 input rejected or asset not found; 2 could not
check (network, timeout, rate limit, API error, malformed answer).
"""
from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from . import provenance as prov
from .client import ApiError, Client, NotFound
from .countries import CountryError
from .tools import Service, ToolError

EPILOG = """examples:
  climate-trace-mcp search --country DE --subsector iron-and-steel --year 2024
  climate-trace-mcp search --country Poland --sector power --name belchatow
  climate-trace-mcp asset 1566771 --years 2022-2024
  climate-trace-mcp owners 1566771
  climate-trace-mcp country Poland --sector power --years 2020-2024
  climate-trace-mcp sectors
  climate-trace-mcp sources

MCP: claude mcp add climate-trace -- uvx climate-trace-mcp
Figures are Climate TRACE modelled estimates. Source: Climate TRACE (climatetrace.org), CC BY 4.0."""


def _t(v) -> str:
    """Tonnes for display, rounded to whole tonnes."""
    if v is None:
        return "n/a"
    return "{:,}".format(int(round(v)))


def _measure(m) -> str:
    if not m:
        return ""
    v = m["value"]
    num = "{:,}".format(int(round(v))) if abs(v) >= 1000 else ("%g" % round(v, 4))
    return (num + " " + (m.get("unit") or "")).strip()


def _table(rows, aligns) -> list:
    widths = [max(len(str(r[i])) for r in rows) for i in range(len(rows[0]))]
    out = []
    for r in rows:
        cells = [str(c).rjust(w) if a == ">" else str(c).ljust(w) for c, w, a in zip(r, widths, aligns)]
        out.append("  ".join(cells).rstrip())
    return out


def _footer(res) -> list:
    lines = []
    for n in res.get("notes") or []:
        lines.append("Note: " + n)
    if res.get("licence_note"):
        lines.append("Licence: " + res["licence_note"])
    lines.append("Values rounded to whole tonnes for display. " + prov.CAVEAT)
    lines.append(res["attribution"])
    return lines


def _head(res) -> str:
    return "Emissions: %s, %s, %s. Modelled estimates." % (res["unit"], res["gas"], res["gwp_horizon"])


def render_search(res) -> str:
    q = res["query"]
    what = ", ".join(x for x in (q.get("subsector") or q.get("sector"),
                                 "%s (%s)" % (q["country_name"], q["country"]) if q.get("country") else None,
                                 "name ~ %r" % q["name"] if q.get("name") else None) if x)
    lines = ["Climate TRACE assets, %d%s" % (res["year"], (": " + what) if what else ""), _head(res), ""]
    if res["assets"]:
        rows = [("asset_id", "emissions " + res["unit"], "country", "type", "name")]
        for a in res["assets"]:
            rows.append((a["asset_id"], _t(a["emissions"]["value"]), a["country"] or "", a["asset_type"] or "",
                         a["name"] or ""))
        lines += _table(rows, "<><<<") + [""]
    lines.append("%d asset(s)." % res["count"])
    for key, d in res["source_datasets"].items():
        lines.append("Source dataset, %s: %s" % (key, d["label"]))
    return "\n".join(lines + _footer(res))


def render_asset(res) -> str:
    where = ", ".join(x for x in (
        "%s (%s)" % (res["country_name"], res["country"]) if res["country"] else None,
        "%s / %s" % (res["sector"], res["subsector"]),
        res["asset_type"], res["source_type"],
        "%.5f, %.5f" % (res["location"]["latitude"], res["location"]["longitude"]) if res["location"] else None) if x)
    lines = ["%s (asset %d)" % (res["name"], res["asset_id"]), where, _head(res)]
    if res["owners"]:
        lines.append("Owners (as the API lists them): " + "; ".join(
            "%s (Climate TRACE owner id %s)" % (o["name"], o["climate_trace_owner_id"]) for o in res["owners"]))
    lines.append("")
    if res["emissions"]:
        rows = [("year", "emissions " + res["unit"], "confidence", "emissions factor", "activity", "subsector rank")]
        for e in res["emissions"]:
            rows.append((e["year"], _t(e["value"]), e["confidence"] or "", _measure(e["emissions_factor"]),
                         _measure(e["activity"]), e["subsector_rank_global"] or ""))
        lines += _table(rows, "<><<<>") + [""]
    lines.append("Source dataset: " + res["source_dataset"]["label"])
    return "\n".join(lines + _footer(res))


def render_country(res) -> str:
    lines = ["Climate TRACE country totals: %s (%s)%s" % (
        res["country_name"], res["country"], (", sector " + res["sector"]) if res["sector"] else ", all sectors"),
        _head(res), ""]
    years = res["years"]
    key = "subsectors" if res["breakdown_by"] == "subsector" else "sectors"
    latest = {}
    for y in years:
        for b in y.get(key) or []:
            n = b.get("subsector") or b.get("sector")
            if n:
                latest[n] = b.get("value") or 0
    # Largest first, by the most recent year that has the row.
    names = sorted(latest, key=lambda n: -latest[n])
    rows = [[""] + [str(y["year"]) for y in years],
            ["total"] + [_t(y["total"]["value"]) if y.get("total") else "no data" for y in years],
            ["months with data"] + [str(y.get("months_with_data", 0)) for y in years]]
    flagged = {s for s, d in res["source_datasets"].items() if d["external_datasets"]}
    if key == "sectors":
        # A sector is marked when any of its subsectors comes from an external dataset.
        flagged_rows = {res["source_datasets"][s]["sector"] for s in flagged}
    else:
        flagged_rows = flagged
    for n in names:
        label = n + (" *" if n in flagged_rows else "")
        row = [label]
        for y in years:
            match = [b for b in y.get(key) or [] if (b.get("subsector") or b.get("sector")) == n]
            row.append(_t(match[0]["value"]) if match else "")
        rows.append(row)
    lines += _table(rows, "<" + ">" * len(years)) + [""]
    if flagged:
        lines.append("* includes data Climate TRACE reproduces from an external dataset (below).")
    for y in years:
        if y.get("note"):
            lines.append("%d: %s" % (y["year"], y["note"]))
    shown = set(names) if key == "subsectors" else flagged
    for s in sorted(shown & set(res["source_datasets"])):
        lines.append("Source dataset, %s: %s" % (s, res["source_datasets"][s]["label"]))
    return "\n".join(lines + _footer(res))


def render_owners(res) -> str:
    lines = ["Owners of %s (asset %d), as the Climate TRACE API lists them" % (res["asset_name"], res["asset_id"])]
    for o in res["owners"]:
        lei = o["lei"] or "none returned by the API"
        lines.append("  %s (Climate TRACE owner id %s; LEI: %s)" % (o["name"], o["climate_trace_owner_id"], lei))
    lines.append("Ownership shares: %s." % res["ownership_shares"])
    lines += ["Note: " + n for n in res["notes"]]
    lines.append("Ownership data: " + res["ownership_data_source"])
    lines.append(res["attribution"])
    return "\n".join(lines)


def render_sectors(res) -> str:
    lines = []
    for s in res["sectors"]:
        lines.append(s["sector"])
        rows = []
        for sub in s["subsectors"]:
            ext = ", ".join(e["dataset"] for e in sub["external_datasets_per_terms"])
            rows.append(("  " + sub["subsector"], "assets" if sub["asset_level_data"] else "country only",
                         ("data leads: " + ", ".join(sub["data_leads"])) if sub["data_leads"] else "no data lead named",
                         ("external (terms): " + ext) if ext else ""))
        if rows:
            lines += _table(rows, "<<<<")
    lines.append("")
    lines.append("Gases: " + "; ".join("%s = %s, %s" % (k, v["unit"], v["gwp_horizon"]) for k, v in res["gases"].items()))
    lines.append("Definitions snapshot of %s (API %s); live check: %s" % (
        res["snapshot_retrieved"], res["snapshot_api_version"], res["live_check"]["status"]))
    for k in ("new_in_api", "no_longer_in_api"):
        if res["live_check"].get(k):
            lines.append("  %s: %s" % (k.replace("_", " "), ", ".join(res["live_check"][k])))
    lines.append(res["attribution"])
    return "\n".join(lines)


def render_sources(res) -> str:
    lines = [
        "Provider: " + res["provider"],
        "API: %s (live version %s; tested %s)" % (res["api"], res["api_version_live"] or "unknown", res["api_version_tested"]),
        "API status (%s): \"%s\"" % (res["api_status"]["source"], res["api_status"]["quote"]),
        "Licence: %s, %s. Terms: %s" % (res["licence"]["name"], res["licence"]["url"], res["licence"]["terms"]),
        "  \"%s\"" % res["licence"]["quote"],
        "Attribution line: " + res["attribution"],
        "  " + res["attribution_note"],
        "Citation guidance: " + res["citation_guidance"],
        "Estimates: " + res["caveat"],
        "External datasets (%s, checked %s):" % (res["external_datasets"]["source"], res["external_datasets"]["checked"]),
    ]
    for d in res["external_datasets"]["datasets"]:
        lines.append("  %s: %s. Licence: %s%s. Subsectors: %s" % (
            d["dataset"], d["url"], d["licence"],
            (" (%s, checked %s)" % (d["licence_source"], d["licence_checked"])) if d.get("licence_source") else "",
            ", ".join(d["subsectors"])))
    lines.append("  EDGAR: \"%s\"" % res["external_datasets"]["edgar_co2_licence_quote"])
    lines.append("Gases: " + res["gases_source"])
    lines.append("What this is not:")
    lines += ["  - " + w for w in res["what_this_is_not"]]
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="climate-trace-mcp", formatter_class=argparse.RawDescriptionHelpFormatter,
                                description="Climate TRACE emission estimates for assets and countries, with owners "
                                            "and the source of every figure. MCP server and command line.",
                                epilog=EPILOG)
    p.add_argument("--version", action="version", version="climate-trace-mcp " + __version__)
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("search", help="assets ranked by emissions for one year")
    s.add_argument("--name")
    s.add_argument("--country")
    s.add_argument("--sector")
    s.add_argument("--subsector")
    s.add_argument("--year", type=int)
    s.add_argument("--limit", type=int, default=20)
    a = sub.add_parser("asset", help="one asset by id, by year")
    a.add_argument("asset_id")
    a.add_argument("--years")
    a.add_argument("--gas", default="co2e_100yr")
    c = sub.add_parser("country", help="country totals by year, optionally for one sector")
    c.add_argument("country")
    c.add_argument("--sector")
    c.add_argument("--years")
    c.add_argument("--gas", default="co2e_100yr")
    o = sub.add_parser("owners", help="owners of one asset")
    o.add_argument("asset_id")
    sub.add_parser("sectors", help="sectors, subsectors, data leads and external datasets")
    sub.add_parser("sources", help="licence, attribution, caveats and external datasets")
    sub.add_parser("serve", help="run the MCP server on stdio")
    r = sub.add_parser("refresh", help="rebuild the bundled definitions snapshot from the API")
    r.add_argument("--out", help="write here instead of the package's data/subsectors.json")
    for sp in (s, a, c, o, sub.choices["sectors"], sub.choices["sources"]):
        sp.add_argument("--json", action="store_true", help="print the JSON result")
    return p


def _stdio_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv=None) -> int:
    _stdio_utf8()
    parser = _parser()
    args = parser.parse_args(argv)
    if args.cmd in (None, "serve"):
        if args.cmd is None and sys.stdin.isatty():
            parser.print_help()
            return 0
        from .server import main as serve
        return serve()
    try:
        if args.cmd == "refresh":
            info = prov.refresh(Client(), args.out, log=lambda name: print("  " + name, file=sys.stderr))
            print(json.dumps(info, indent=1))
            print("Record the sha256, counts and date in climate_trace_mcp/data/SOURCES.md.", file=sys.stderr)
            return 0
        service = Service()
        if args.cmd == "search":
            res = service.search_assets(name=args.name, country=args.country, sector=args.sector,
                                        subsector=args.subsector, year=args.year, limit=args.limit)
            render = render_search
        elif args.cmd == "asset":
            res, render = service.asset(args.asset_id, years=args.years, gas=args.gas), render_asset
        elif args.cmd == "country":
            res = service.country_emissions(args.country, sector=args.sector, years=args.years, gas=args.gas)
            render = render_country
        elif args.cmd == "owners":
            res, render = service.owners(args.asset_id), render_owners
        elif args.cmd == "sectors":
            res, render = service.sectors(), render_sectors
        else:
            res, render = service.sources(), render_sources
    except (ToolError, CountryError) as e:
        print("error: %s" % (e.message if isinstance(e, ToolError) else e), file=sys.stderr)
        return 1 if not isinstance(e, ToolError) or e.kind in ("invalid_argument", "not_found") else 2
    except NotFound as e:
        print("error: %s" % e.message, file=sys.stderr)
        return 1
    except ApiError as e:
        print("error: %s" % e.message, file=sys.stderr)
        return 2
    except ValueError as e:  # a CLIMATE_TRACE_API_BASE the client refused, or a refresh that found bad data
        print("error: %s" % e, file=sys.stderr)
        return 2
    print(json.dumps(res, ensure_ascii=False, indent=1) if args.json else render(res))
    return 0
