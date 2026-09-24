"""Country classification under Article 29 of Regulation (EU) 2023/1115.

The implementing act lists countries by English name only. ISO 3166-1 codes
come from the Publications Office's 'Countries and territories' authority
table, matched on its English preferred and alternative labels. Every Annex
name must match exactly one country, or `refresh` stops.
"""
from __future__ import annotations

import re
import unicodedata

from .annex import RQ
from .xhtml import Node, tidy

# The one name in Implementing Regulation (EU) 2025/1093 that no label in the
# authority table matches: the Annex writes "Solomon Island" (singular).
# Mapping it to Solomon Islands is this tool's reading, recorded in SOURCES.md.
ANNEX_NAME_FIXES = {"Solomon Island": "SLB"}


class CountryError(ValueError):
    """The country annex or the authority table does not read as expected."""


def norm(name: str) -> str:
    """Case-, accent- and apostrophe-insensitive key for a country name."""
    name = unicodedata.normalize("NFKD", name.replace(RQ, "'").replace("*", ""))
    name = "".join(ch for ch in name if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", name).strip().casefold()


def parse_annex(root: Node) -> dict:
    """{'heading': ..., 'low': [names], 'high': [names]} from the act's Annex."""
    annex = root.find_id("anx_1")
    if annex is None:
        raise CountryError("no element with id 'anx_1' (Annex) in the implementing act")
    lines = [tidy(x) for x in annex.lines()]
    out = {"heading": None, "low": None, "high": None}
    for i, line in enumerate(lines):
        if line.startswith("List of countries"):
            out["heading"] = line
        key = {"Low risk countries": "low", "High risk countries": "high"}.get(line)
        if key:
            body = []
            for nxt in lines[i + 1:]:
                if nxt in ("Low risk countries", "High risk countries"):
                    break
                body.append(nxt)
            out[key] = split_names(" ".join(body))
    if not out["low"] or not out["high"]:
        raise CountryError("the Annex has no 'Low risk countries' or 'High risk countries' list")
    return out


def split_names(text: str) -> list:
    text = text.strip().rstrip(".").strip()
    names = [tidy(n) for n in text.split(",")]
    if any(not n or len(n) > 80 for n in names):
        raise CountryError(f"unexpected name list: {text[:120]!r}")
    return names


def build_countries(rows: list, alt_rows: list) -> list:
    """Current entries of the authority table that carry ISO alpha-2 and alpha-3 codes.

    rows: SPARQL bindings with c, a2, a3, pref, status, broader.
    alt_rows: SPARQL bindings with c, alt (English alternative labels).
    """
    by_uri: dict = {}
    for r in rows:
        if not str(r.get("status", "")).endswith("/CURRENT"):
            continue
        a2, a3 = (r.get("a2") or "").strip(), (r.get("a3") or "").strip()
        if not re.fullmatch(r"[A-Z]{2}", a2) or not re.fullmatch(r"[A-Z]{3}", a3):
            continue  # e.g. "EU" (no alpha-3) is not a country
        code = r["c"].rsplit("/", 1)[-1]
        parent = (r.get("broader") or "").rsplit("/", 1)[-1] or None
        by_uri[r["c"]] = {"iso2": a2, "iso3": a3, "name": tidy(r["pref"])[:80], "authority_code": code,
                          "part_of": parent, "aliases": []}
    for r in alt_rows:
        entry = by_uri.get(r.get("c"))
        alt = tidy(r.get("alt") or "").replace("*", "").strip()
        if entry and alt and len(alt) <= 80 and not alt.startswith("of ") and alt != entry["name"]:
            if alt not in entry["aliases"]:
                entry["aliases"].append(alt)
    countries = sorted(by_uri.values(), key=lambda c: c["iso2"])
    iso3 = {c["iso3"] for c in countries}
    for c in countries:
        # Keep a parent only when it is itself a country here (not e.g. a region code).
        if c["part_of"] not in iso3:
            c["part_of"] = None
        c["aliases"].sort()
    seen: dict = {}
    for c in countries:
        for key in (c["iso2"], c["iso3"]):
            if key in seen:
                raise CountryError(f"ISO code {key} appears twice in the authority table")
            seen[key] = c
    return countries


def name_index(countries: list) -> dict:
    """norm(name) -> iso3; a label shared by two countries is left out, not guessed."""
    index: dict = {}
    clash: set = set()
    for c in countries:
        for label in [c["name"]] + c["aliases"]:
            key = norm(label)
            if key in index and index[key] != c["iso3"]:
                clash.add(key)
            index[key] = c["iso3"]
    for key in clash:
        index.pop(key, None)
    return index


def map_annex_names(names: list, countries: list) -> list:
    """[(annex name, iso3, how)] for every name, or CountryError."""
    index = name_index(countries)
    out = []
    for name in names:
        iso3 = index.get(norm(name))
        how = "label"
        if iso3 is None:
            m = re.fullmatch(r"(.+?) \((.+)\)", name)  # "Iran (Islamic Republic of)"
            if m:
                iso3 = index.get(norm(m.group(2) + " " + m.group(1)))
                how = "label, qualifier moved to the front"
        if iso3 is None and name in ANNEX_NAME_FIXES:
            iso3, how = ANNEX_NAME_FIXES[name], "fixed mapping (see SOURCES.md)"
        if iso3 is None:
            raise CountryError(f"Annex name {name!r} matches no country in the authority table")
        out.append((name, iso3, how))
    codes = [x[1] for x in out]
    dupes = {c for c in codes if codes.count(c) > 1}
    if dupes:
        raise CountryError(f"two Annex names map to the same country: {sorted(dupes)}")
    return out
