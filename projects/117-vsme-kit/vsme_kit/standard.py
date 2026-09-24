"""Lookups in the bundled text of the standard: which disclosures a module has, what one of them asks.

Two editions, both quoted from the Official Journal:
  "2026"  Annex I to Commission Delegated Regulation (EU) 2026/1560, in force since 24 September 2026;
  "2025"  Annex I to Commission Recommendation (EU) 2025/1710 (the VSME), with its Annex II guidance.
The default is the edition in force. EFRAG's Digital Template up to version 1.3.0
implements the 2025 edition, so questions about filling that template use "2025".
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
EDITIONS = ("2026", "2025")
DEFAULT = "2026"
CODE = re.compile(r"^([BC])(\d{1,2})$")
VALID = {f"B{i}" for i in range(1, 12)} | {f"C{i}" for i in range(1, 10)}
MODULES = ("basic", "comprehensive", "all")
NOT_ADVICE = "Information from the published text, not legal advice."


class LookupError_(ValueError):
    """A request this module cannot answer (unknown code, module or edition)."""


@lru_cache(maxsize=None)
def load(edition: str) -> dict:
    if edition not in EDITIONS:
        raise LookupError_(f"unknown edition {str(edition)[:12]!r}; use one of {', '.join(EDITIONS)}")
    path = DATA / f"standard-{edition}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise LookupError_(f"the bundled snapshot {path.name} cannot be read ({type(e).__name__}); "
                           "reinstall vsme-kit or run `vsme-kit refresh`") from None


def attribution(snap: dict) -> str:
    return (f"Source: {snap['act']}, {snap['oj']}, {snap['eli']}; © European Union; reused under the Commission's reuse "
            f"policy (Decision 2011/833/EU), CC BY 4.0; retrieved {snap['source']['retrieved']} from CELLAR. "
            f"Changes: {snap['changes']}")


def status() -> dict:
    """What each edition is and which one applies, read from the 2026 act itself."""
    new, old = load("2026"), load("2025")
    return {
        "2026": {"act": new["act"], "oj": new["oj"], "eli": new["eli"], "entry_into_force": new["entry_into_force"],
                 "value_chain_cap_applies": new["value_chain_cap_applies"],
                 "note": "Standard for voluntary use (Article 2); the value chain cap in Annex II applies from "
                         f"{new['value_chain_cap_applies']} (Article 4)."},
        "2025": {"act": old["act"], "oj": old["oj"], "eli": old["eli"],
                 "note": "Recital 5 of Delegated Regulation (EU) 2026/1560: \"" + new["recital_5"].split(". However")[0]
                         .removeprefix("(5) ").strip() + ".\" EFRAG's VSME Digital Template up to version 1.3.0 "
                         "implements this edition."},
    }


def normalise_code(code) -> str:
    m = CODE.match(str(code).strip().upper()) if isinstance(code, str) else None
    if not m or f"{m.group(1)}{int(m.group(2))}" not in VALID:
        raise LookupError_(f"unknown disclosure {str(code)[:12]!r}; the codes are B1 to B11 and C1 to C9")
    return f"{m.group(1)}{int(m.group(2))}"


def _order(code: str):
    return (code[0], int(code[1:]))


def _titles(snap: dict) -> dict:
    out = {}
    for p in snap["annex_i"]:
        if p["code"] and p["code"] not in out:
            out[p["code"]] = re.sub(r"^" + p["code"] + r"\s*[–-]\s*", "", p["heading"] or "").strip()
    return out


def disclosures(module: str = "all", edition: str = DEFAULT) -> dict:
    """The disclosures of a module, with their titles and paragraph numbers, and the module rules verbatim."""
    module = (module or "all").strip().lower()
    if module not in MODULES:
        raise LookupError_(f"unknown module {module[:20]!r}; use basic, comprehensive or all")
    snap = load(edition)
    titles = _titles(snap)
    paras = {}
    for p in snap["annex_i"]:
        if p["code"]:
            paras.setdefault(p["code"], []).append(p["n"])
    capped = {r["code"] for r in snap.get("value_chain_cap", [])}
    rows = []
    for code in sorted(titles, key=_order):
        mod = "basic" if code[0] == "B" else "comprehensive"
        if module != "all" and mod != module:
            continue
        row = {"code": code, "title": titles[code], "module": mod, "paragraphs": paras[code]}
        if edition == "2026":
            row["in_value_chain_cap"] = code in capped
        rows.append(row)
    structure = [{"n": p["n"], "text": p["text"]} for p in snap["annex_i"]
                 if (p["heading"] or "").lower().startswith("structure of this standard")]
    return {"edition": edition, "standard": f"{snap['act']}, {snap['standard']}", "oj": snap["oj"],
            "module": module, "disclosures": rows, "module_rules": structure,
            "status": status()[edition]["note"], "not_advice": NOT_ADVICE, "attribution": attribution(snap)}


def disclosure(code: str, edition: str = DEFAULT, guidance: bool = False) -> dict:
    """What one disclosure asks, verbatim, with paragraph numbers."""
    code = normalise_code(code)
    snap = load(edition)
    own = [{"n": p["n"], "text": p["text"]} for p in snap["annex_i"] if p["code"] == code]
    related = [{"n": p["n"], "heading": p["heading"], "text": p["text"]} for p in snap["annex_i"] if code in p["related"]]
    out = {"edition": edition, "standard": f"{snap['act']}, {snap['standard']}", "oj": snap["oj"], "code": code,
           "title": _titles(snap)[code], "module": "basic" if code[0] == "B" else "comprehensive",
           "paragraphs": own, "related_paragraphs": related}
    if edition == "2026":
        out["value_chain_cap"] = [r for r in snap["value_chain_cap"] if r["code"] == code]
        out["guidance"] = "Article 2(2): undertakings \"may also use the practical guidance provided by EFRAG\"; it is not bundled."
    elif guidance:
        out["guidance"] = [{"n": p["n"], "heading": p["heading"], "text": p["text"]}
                           for p in snap["annex_ii_guidance"] if p["code"] == code]
    else:
        n = sum(1 for p in snap["annex_ii_guidance"] if p["code"] == code)
        out["guidance"] = f"{n} paragraph(s) of Annex II guidance; ask with guidance=true to include them."
    other = "2025" if edition == "2026" else "2026"
    other_snap = load(other)
    out["other_edition"] = {"edition": other, "act": other_snap["act"], "title": _titles(other_snap)[code],
                            "paragraphs": [p["n"] for p in other_snap["annex_i"] if p["code"] == code]}
    out["status"] = status()[edition]["note"]
    out["not_advice"] = NOT_ADVICE
    out["attribution"] = attribution(snap)
    return out
