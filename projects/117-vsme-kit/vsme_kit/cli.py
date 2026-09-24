"""vsme-kit command line: look up the standard, check a filled template, serve MCP, refresh the snapshot."""
from __future__ import annotations

import argparse
import json
import sys

from . import VERSION, standard, template
from .xlsx import WorkbookError

STATUS_ORDER = ("inconsistent", "missing", "filled", "omitted", "not applicable", "not located")
EXIT_OK, EXIT_FINDINGS, EXIT_CANNOT = 0, 1, 2


def _table(headers, rows) -> str:
    widths = [max(len(str(x)) for x in col) for col in zip(headers, *rows)] if rows else [len(h) for h in headers]
    line = lambda r: "  ".join(str(x).ljust(w) for x, w in zip(r, widths)).rstrip()
    return "\n".join([line(headers), line(["-" * w for w in widths])] + [line(r) for r in rows])


def _md_escape(text) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _md_table(headers, rows) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(_md_escape(x) for x in r) + " |" for r in rows]
    return "\n".join(out)


# ---------------------------------------------------------------- lookups

def render_disclosures(res: dict, fmt: str) -> str:
    rows = [(d["code"], d["title"], ", ".join(d["paragraphs"])) + (("yes" if d.get("in_value_chain_cap") else "no",)
                                                                  if "in_value_chain_cap" in d else ())
            for d in res["disclosures"]]
    headers = ["code", "disclosure", "paragraphs"] + (["value chain cap"] if res["edition"] == "2026" else [])
    rules = "\n".join(f"{p['n']}. {p['text']}" for p in res["module_rules"])
    if fmt == "markdown":
        return "\n\n".join([f"**{res['standard']}** ({res['oj']}), {res['module']} module(s)", _md_table(headers, rows),
                            "> " + rules.replace("\n", "\n> "), f"_{res['status']}_", f"_{res['not_advice']}_",
                            f"_{res['attribution']}_"])
    return "\n\n".join([f"{res['standard']} ({res['oj']}), {res['module']} module(s)", _table(headers, rows),
                        "Structure of the standard (verbatim):\n" + rules, res["status"], res["not_advice"],
                        res["attribution"]])


def render_disclosure(res: dict, fmt: str) -> str:
    q = "> " if fmt == "markdown" else ""
    parts = [f"{'### ' if fmt == 'markdown' else ''}{res['code']} – {res['title']}  ({res['standard']}, {res['oj']})"]
    for p in res["paragraphs"]:
        parts.append(q + f"{p['n']}. " + p["text"].replace("\n", "\n" + q))
    for p in res["related_paragraphs"]:
        parts.append(f"Related, under \"{p['heading']}\":\n" + q + f"{p['n']}. " + p["text"].replace("\n", "\n" + q))
    if res.get("value_chain_cap") is not None:
        cap = res["value_chain_cap"]
        if cap:
            lines = [f"- {r['reference']}: {r['datapoint']} (10 or fewer employees: {'yes' if r['cap_10_or_fewer_employees'] else 'no'}; "
                     f"more than 10: {'yes' if r['cap_more_than_10_employees'] else 'no'})" for r in cap]
            parts.append("In the value chain cap (Annex II):\n" + "\n".join(lines))
        else:
            parts.append("Not in the value chain cap (Annex II).")
    if isinstance(res["guidance"], list):
        parts.append("Guidance (Annex II of the Recommendation):\n" + "\n".join(
            q + f"{p['n']}. " + p["text"].replace("\n", "\n" + q) for p in res["guidance"]))
    else:
        parts.append(res["guidance"])
    o = res["other_edition"]
    parts.append(f"In the other edition ({o['act']}): {res['code']} – {o['title']}, paragraphs {', '.join(o['paragraphs'])}.")
    parts += [res["status"], res["not_advice"], res["attribution"]]
    return "\n\n".join(parts)


# ---------------------------------------------------------------- template check

def _detail(d: dict) -> str:
    if d.get("reason"):
        return d["reason"]
    bits = []
    if d["findings"]:
        bits.append(f"{len(d['findings'])} inconsistency(ies)")
    if d["missing"]:
        bits.append("missing: " + "; ".join(d["missing"]))
    if d["omitted"]:
        bits.append("omitted as classified or sensitive: " + "; ".join(d["omitted"]))
    if d["not_located"]:
        bits.append("not located: " + "; ".join(d["not_located"]))
    return " | ".join(bits)


def render_check(rep: dict, fmt: str) -> str:
    t = rep["template"]
    head = (f"VSME Digital Template check: {rep['file']}\n"
            f"Template version {t['version'] or 'unknown'}; it implements {t['implements']}.\n"
            f"Module option (B1, para 24(a)): {rep['option'] or 'not given'}")
    rows = [(d["code"], d["title"][:48], d["status"], _detail(d)) for d in rep["disclosures"]]
    counts = " · ".join(f"{rep['summary'][s]} {s}" for s in STATUS_ORDER if rep["summary"].get(s))
    findings = [f"- {x['disclosure']}: {x['message']}. {x['cite']}." for d in rep["disclosures"] for x in d["findings"]]
    tail = []
    if rep["template_own_validation"]:
        tail.append(f"The template's own validation status, as saved in the file: {rep['template_own_validation']}")
    tail += rep["notes"]
    tail.append("Paragraph numbers: Annex I (the standard) and Annex II (guidance) of Commission Recommendation (EU) "
                "2025/1710. This is a completeness and arithmetic check, not assurance and not advice.")
    if fmt == "markdown":
        out = [head.replace("\n", "  \n"), _md_table(["code", "disclosure", "status", "details"], rows), f"**{counts}**"]
        if findings:
            out.append("**Inconsistencies**\n\n" + "\n".join(findings))
        return "\n\n".join(out + ["_" + x + "_" for x in tail])
    out = [head, _table(["code", "disclosure", "status", "details"], rows), counts]
    if findings:
        out.append("Inconsistencies:\n" + "\n".join(findings))
    return "\n\n".join(out + tail)


# ---------------------------------------------------------------- main

def _parser():
    fmt = argparse.ArgumentParser(add_help=False)
    g = fmt.add_mutually_exclusive_group()
    g.add_argument("--json", action="store_true", help="machine-readable output")
    g.add_argument("--markdown", action="store_true", help="Markdown, to paste into an issue or a document")
    p = argparse.ArgumentParser(prog="vsme-kit", parents=[fmt],
                                description="The EU voluntary sustainability reporting standard for SMEs (VSME): "
                                            "the text, and a check of EFRAG's Digital Template.")
    p.add_argument("--version", action="version", version=f"vsme-kit {VERSION}")
    sub = p.add_subparsers(dest="command")
    d = sub.add_parser("disclosures", parents=[fmt], help="the disclosures of the basic or comprehensive module")
    d.add_argument("--module", default="all", choices=standard.MODULES)
    d.add_argument("--edition", default=standard.DEFAULT, choices=standard.EDITIONS)
    one = sub.add_parser("disclosure", parents=[fmt], help="what one disclosure (B1-B11, C1-C9) asks, verbatim")
    one.add_argument("code")
    one.add_argument("--edition", default=standard.DEFAULT, choices=standard.EDITIONS)
    one.add_argument("--guidance", action="store_true", help="include the Annex II guidance (2025 edition)")
    c = sub.add_parser("check", parents=[fmt], help="check a filled VSME Digital Template (xlsx)")
    c.add_argument("path")
    c.add_argument("--strict", action="store_true",
                   help="exit 1 when a disclosure is missing or inconsistent (2 when the file cannot be checked)")
    sub.add_parser("editions", parents=[fmt], help="which edition of the standard is which, with dates")
    sub.add_parser("mcp", help="run the MCP server on stdin/stdout")
    r = sub.add_parser("refresh", help="rebuild the bundled text from the Official Journal (network)")
    r.add_argument("--out", help="directory for the snapshot (default: the package's data directory)")
    return p


def _emit(obj, text_fn, args):
    if args.json:
        print(json.dumps(obj, ensure_ascii=False, indent=1))
    else:
        print(text_fn(obj, "markdown" if args.markdown else "text"))


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "disclosures":
            _emit(standard.disclosures(args.module, args.edition), render_disclosures, args)
        elif args.command == "disclosure":
            _emit(standard.disclosure(args.code, args.edition, args.guidance), render_disclosure, args)
        elif args.command == "editions":
            _emit(standard.status(), lambda s, f: "\n\n".join(
                f"{k}: {v['act']}, {v['oj']}, {v['eli']}\n{v['note']}" for k, v in s.items()), args)
        elif args.command == "check":
            report = template.check(args.path)
            _emit(report, render_check, args)
            return EXIT_FINDINGS if args.strict and template.serious(report) else EXIT_OK
        elif args.command == "mcp":
            from . import mcp
            return mcp.main()
        elif args.command == "refresh":
            from . import refresh
            for line in refresh.run(args.out):
                print(line)
        else:
            _parser().print_help()
            return EXIT_CANNOT
    except standard.LookupError_ as e:
        print(f"vsme-kit: {e}", file=sys.stderr)
        return EXIT_CANNOT
    except WorkbookError as e:
        print(f"vsme-kit: cannot check {args.path}: {e}", file=sys.stderr)
        return EXIT_CANNOT
    except Exception as e:  # refresh errors and anything unexpected: a message, never a traceback
        name = type(e).__name__
        print(f"vsme-kit: {name}: {e}", file=sys.stderr)
        return EXIT_CANNOT
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
