"""The five questions this tool answers, over the bundled snapshots.

Every answer carries `legally_binding` (always false: these are copies),
`legally_binding_source` (the act that is binding), `data_version` and an
attribution line. Text taken from the sources is wrapped as remote text (see
remote.py); codes, numbers, dates and known vocabularies stay bare. Nothing
here uses the network.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from . import legal
from .codes import ISO_BY_TABLE_NAME, InputError, cn_candidates, format_cn, normalize_cn, resolve_country
from .parsers import parse_value
from .remote import CATEGORIES, CELEX, CODE, DATE, GASES, PUBLISHED, ROUTE, clean, known, remote

DATA_ENV = "CBAM_MCP_DATA_DIR"
PACKAGE_DATA = Path(__file__).resolve().parent / "data"
UNIT = "tCO2e per tonne of good"
ELECTRICITY = "27160000"
HYDROGEN = "28041000"
MAX_LIST = 500
BUNDLED_PREFIXES = ("25", "28", "31", "72", "73", "76", "2601", "2716")
URL = re.compile(r"^https?://[A-Za-z0-9.-]+(?:/[A-Za-z0-9._~%/?=&:+()-]*)?$")
VERSION = re.compile(r"^\d{1,3}$")


class DataError(RuntimeError):
    """A bundled data file is missing or unreadable."""


def data_dir() -> Path:
    env = os.environ.get(DATA_ENV)
    return Path(env) if env else PACKAGE_DATA


class Store:
    """Lazily loaded snapshots plus the indexes built on them."""

    def __init__(self, directory=None):
        self.dir = Path(directory) if directory else data_dir()
        self._docs: dict = {}
        self._cn_index: dict = {}

    def _load(self, name: str) -> dict:
        if name not in self._docs:
            path = self.dir / name
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                raise DataError(f"{path} is missing; run `cbam-mcp refresh`") from None
            except (OSError, UnicodeDecodeError, ValueError) as e:
                raise DataError(f"{path} cannot be read ({type(e).__name__}); run `cbam-mcp refresh`") from None
            if not isinstance(doc, dict) or not isinstance(doc.get("meta"), dict):
                raise DataError(f"{path} is not a cbam-mcp data file; run `cbam-mcp refresh`")
            self._docs[name] = doc
        return self._docs[name]

    @property
    def annex(self) -> dict:
        return self._load("annex_i.json")

    @property
    def values(self) -> dict:
        doc = self._load("default_values.json")
        if "_lines" not in doc:
            doc["_lines"] = {row[0]: row for row in doc["lines"]}
            doc["_order"] = [row[0] for row in doc["lines"]]
        return doc

    def cn(self, year: int) -> dict:
        doc = self._load(f"cn_{year}.json")
        if year not in self._cn_index:
            by_code, children = {}, {}
            for cid, c in doc["concepts"].items():
                if c[0].isdigit() and c[0] not in by_code:
                    by_code[c[0]] = cid
                children.setdefault(c[4], []).append(cid)
            self._cn_index[year] = (by_code, children)
        return doc

    def cn_lookup(self, year: int, digits: str):
        doc = self.cn(year)
        by_code = self._cn_index[year][0]
        for cand in cn_candidates(digits):
            if cand in by_code:
                return by_code[cand], doc["concepts"][by_code[cand]]
        return None, None

    def cn_children(self, year: int, cid: str) -> list:
        self.cn(year)
        return self._cn_index[year][1].get(cid, [])

    def cn_codes_under(self, year: int, digits: str) -> list[str]:
        self.cn(year)
        return sorted(code for code in self._cn_index[year][0] if len(code) == 8 and code.startswith(digits))

    @staticmethod
    def cn_bundled(digits: str) -> bool:
        return any(digits.startswith(p) or p.startswith(digits) for p in BUNDLED_PREFIXES)


_store: Store | None = None


def store() -> Store:
    global _store
    if _store is None or _store.dir != data_dir():
        _store = Store()
    return _store


# ------------------------------------------------------------------ shared

def _date(value) -> str:
    return known(value, DATE) or "unknown date"


def _scope_version(s: Store) -> str:
    m = s.annex["meta"]
    return (f"consolidated text {known(m['celex'], CELEX)} of Regulation (EU) 2023/956 (consolidation date "
            f"{_date(m.get('consolidation_date'))}), retrieved {_date(m['retrieved'])} from CELLAR")


def _scope_attribution(s: Store) -> str:
    m = s.annex["meta"]
    return (f"Source: EUR-Lex/CELLAR, consolidated text {known(m['celex'], CELEX)} of Regulation (EU) 2023/956, "
            f"© European Union, retrieved {_date(m['retrieved'])}; table derived by cbam-mcp")


def _values_version(s: Store) -> str:
    m = s.values["meta"]
    return (f"Commission Excel 'Default values definitive period', version {known(m.get('version'), VERSION)} of "
            f"{_date(m.get('version_date'))}, retrieved {_date(m['retrieved'])}")


def _values_attribution(s: Store) -> str:
    m = s.values["meta"]
    return (f"Source: European Commission, DG TAXUD, default values Excel version {known(m.get('version'), VERSION)}, "
            f"CC BY 4.0, retrieved {_date(m['retrieved'])}; decimal commas converted to numbers (derived)")


def _cn_version(s: Store, year: int) -> str:
    m = s.cn(year)["meta"]
    return f"CN {year} (EU Vocabularies, scheme cn{year}), bundled subset, retrieved {_date(m['retrieved'])}"


def _cn_attribution(s: Store, year: int) -> str:
    m = s.cn(year)["meta"]
    return (f"Source: Publications Office of the European Union, EU Vocabularies, Combined Nomenclature {year}, "
            f"European Commission reuse notice, retrieved {_date(m['retrieved'])}")


def _entry_display(e: dict) -> str:
    return ("ex " if e.get("ex") else "") + format_cn(e["code"])


def classify(entries: list, digits: str) -> dict:
    """Where one code stands against a list of Annex I (or II) lines, by CN prefix."""
    covering = [e for e in entries if digits.startswith(e["code"])]
    if covering:
        e = max(covering, key=lambda x: len(x["code"]))
        excs = [x for x in e.get("except", []) if not x.get("heading_only")]
        hit = next((x for x in excs if digits.startswith(x["code"])), None)
        if hit:
            return {"status": "not_in_scope", "basis": "excluded_by_exception", "entry": e, "exception": hit}
        under = [x for x in excs if x["code"].startswith(digits) and x["code"] != digits]
        if under:
            return {"status": "partially_in_scope", "basis": "exceptions_below", "entry": e, "below": under}
        if e.get("ex"):
            return {"status": "partially_in_scope", "basis": "ex_code", "entry": e}
        return {"status": "in_scope", "basis": "listed", "entry": e}
    below = [e for e in entries if e["code"].startswith(digits)]
    if below:
        return {"status": "partially_in_scope", "basis": "lines_below", "below": below}
    return {"status": "not_in_scope", "basis": "not_listed"}


def _line(e: dict) -> dict:
    out = {"cn_code": _entry_display(e), "text": remote(e["description"]), "ex": bool(e.get("ex")),
           "goods_category": known(e.get("category"), CATEGORIES),
           "greenhouse_gases": known(e.get("greenhouse_gases"), GASES)}
    if e.get("except"):
        out["except"] = [{"cn_code": format_cn(x["code"]), "text": remote(x["description"])} for x in e["except"]]
    if e.get("amended_by"):
        out["amended_by"] = [legal.ACTS.get(c) or known(c, CELEX) for c in e["amended_by"]]
    return out


def _cn_brief(s: Store, digits: str, year: int = 2026) -> dict:
    _, c = s.cn_lookup(year, digits[:8])
    if c is None:
        where = "in the bundled subset" if s.cn_bundled(digits) else "(outside the bundled chapters)"
        return {"version": f"CN {year}", "found": False, "note": f"not a CN {year} code {where}"}
    out = {"version": f"CN {year}", "found": True, "cn_code": format_cn(c[0]), "label": remote(c[1])}
    if c[3] and c[3] != c[1]:
        out["self_explanatory_text"] = remote(c[3])
    return out


def _explain(r: dict, digits: str) -> str:
    code = format_cn(digits)
    b = r["basis"]
    if b == "listed":
        e = r["entry"]
        extra = ", and none of its exceptions does" if e.get("except") else ""
        return f"The Annex I line {_entry_display(e)} covers {code}{extra}."
    if b == "ex_code":
        e = r["entry"]
        return (f"Annex I lists {format_cn(e['code'])} as an 'ex' line: only the goods its text describes "
                f"(annex_i_line.text) are in scope, not every good under {format_cn(e['code'])}.")
    if b == "excluded_by_exception":
        e, x = r["entry"], r["exception"]
        return f"The Annex I line {_entry_display(e)} covers {code}, but its exception {format_cn(x['code'])} excludes it."
    if b in ("exceptions_below", "lines_below", "cn_subcodes"):
        return f"Some codes under {code} are in scope and some are not; see subcodes."
    if b == "all_cn_subcodes_in_scope":
        return f"Every CN 2026 sub-code of {code} is covered by Annex I; see subcodes."
    if b == "no_cn_subcode_in_scope":
        return f"Annex I lines touch {code}, but none of its CN 2026 sub-codes is in scope; see subcodes."
    return f"No line of Annex I covers {code}."


def _warn_not_cn(s: Store, digits: str, warnings: list, consequence: str) -> None:
    if len(digits) >= 4 and s.cn_bundled(digits) and s.cn_lookup(2026, digits[:8])[1] is None:
        warnings.append(f"{format_cn(digits[:8])} is not a CN 2026 code; {consequence}")


# ------------------------------------------------------------------ cbam_scope

def cbam_scope(cn_code, limit: int = 50) -> dict:
    s = store()
    digits, warnings = normalize_cn(cn_code)
    if isinstance(limit, bool):
        raise InputError(f"limit must be a whole number from 1 to {MAX_LIST}")
    try:
        limit = max(1, min(int(limit if limit is not None else 50), MAX_LIST))
    except (TypeError, ValueError, OverflowError):
        raise InputError(f"limit must be a whole number from 1 to {MAX_LIST}") from None
    entries = s.annex["annex_i"]
    r = classify(entries, digits)
    out: dict = {"query": clean(cn_code, 60), "cn_code": format_cn(digits)}
    status, basis = r["status"], r["basis"]
    subcodes = None
    if len(digits) < 8:
        buckets: dict = {"in_scope": [], "partially_in_scope": [], "not_in_scope": []}
        for code in s.cn_codes_under(2026, digits):
            cr = classify(entries, code)
            _, c = s.cn_lookup(2026, code)
            item = {"cn_code": format_cn(code), "description": remote((c[3] or c[1]) if c else "")}
            if cr["status"] == "not_in_scope" and cr["basis"] == "excluded_by_exception":
                item["excluded_by"] = format_cn(cr["exception"]["code"])
            if cr["status"] == "partially_in_scope" and cr["basis"] == "ex_code":
                item["ex_line"] = _entry_display(cr["entry"])
            buckets[cr["status"]].append(item)
        total = sum(len(v) for v in buckets.values())
        if total:
            n_in, n_part = len(buckets["in_scope"]), len(buckets["partially_in_scope"])
            if n_in == total:
                status, basis = "in_scope", ("listed" if basis == "listed" else "all_cn_subcodes_in_scope")
            elif n_in == 0 and n_part == 0:
                status, basis = "not_in_scope", ("not_listed" if basis == "not_listed" else "no_cn_subcode_in_scope")
            elif status != "partially_in_scope":
                status, basis = "partially_in_scope", "cn_subcodes"
            subcodes = {"cn_version": "CN 2026", "counts": {k: len(v) for k, v in buckets.items()},
                        "limit_per_list": limit, "truncated": any(len(v) > limit for v in buckets.values())}
            subcodes.update({k: v[:limit] for k, v in buckets.items()})
    out["status"] = status
    out["basis"] = basis
    out["explanation"] = _explain({**r, "basis": basis}, digits)
    entry = r.get("entry")
    if entry is None and status == "in_scope" and len(r.get("below") or []) == 1:
        entry = r["below"][0]
    if entry:
        out["goods_category"] = known(entry.get("category"), CATEGORIES)
        out["greenhouse_gases"] = known(entry.get("greenhouse_gases"), GASES)
        out["annex_i_line"] = _line(entry)
    elif r.get("below"):
        out["annex_i_lines_below"] = [_line(e) for e in r["below"][:limit]]
    if subcodes:
        out["subcodes"] = subcodes
    if status != "not_in_scope":
        a2 = classify(s.annex["annex_ii"], digits)
        q = s.annex.get("quotes", {})
        out["annex_ii"] = {
            "status": {"in_scope": "listed", "partially_in_scope": "partly listed", "not_in_scope": "not listed"}[a2["status"]],
            "article_7_1": remote(q.get("article_7_1")),
            "citation": "Article 7(1) and Annex II of Regulation (EU) 2023/956 (consolidated text)",
        }
        dm = _de_minimis(s, entry)
        if dm:
            out["de_minimis"] = dm
    out["cn"] = _cn_brief(s, digits)
    _warn_not_cn(s, digits, warnings, "the answer only applies Annex I by prefix")
    if len(digits) == 10:
        warnings.append("10 digits is a TARIC code; Annex I is written in CN codes (8 digits and fewer)")
    out["warnings"] = warnings
    out.update(_scope_legal(s))
    return out


def _de_minimis(s: Store, entry: dict | None) -> dict | None:
    q = s.annex.get("quotes", {})
    if entry is None or not q.get("article_2a_1") or not q.get("annex_vii_1"):
        return None
    m = s.annex["meta"]
    src = (f"Article 2a and Annex VII of Regulation (EU) 2023/956, consolidated text {known(m['celex'], CELEX)}, "
           f"retrieved {_date(m['retrieved'])}")
    if entry["code"].startswith(ELECTRICITY[:4]) or entry["code"].startswith(HYDROGEN):
        return {"applies_to_these_goods": False, "article_2a_4": remote(q.get("article_2a_4")), "source": src}
    return {"applies_to_these_goods": True, "article_2a_1": remote(q["article_2a_1"]),
            "annex_vii_point_1": remote(q["annex_vii_1"]),
            "note": "The threshold counts the net mass of all CBAM goods an importer imports in a calendar year, "
                    "not per CN code; this tool cannot tell whether an importer is under it.",
            "source": src}


def _scope_legal(s: Store) -> dict:
    return {"legally_binding": False,
            "legally_binding_source": legal.SCOPE_BINDING_SOURCE,
            "legal_status_of_data": remote(s.annex["meta"].get("disclaimer")),
            "data_version": _scope_version(s),
            "attribution": _scope_attribution(s),
            "not_legal_advice": legal.NOT_LEGAL_ADVICE}


# ------------------------------------------------------------------ default values

def _routes(text: str) -> list:
    out = []
    for letter in [p.strip("() ") for p in (text or "").split("/") if p.strip("() ")]:
        out.append({"code": known(letter, ROUTE), "meaning": legal.PRODUCTION_ROUTES.get(letter, "not in the legend")})
    return out


def _row(s: Store, table: str, code: str):
    raw = s.values["tables"].get(table, {}).get(code)
    if raw is None:
        return None
    return (raw.split("|") + ["", "", "", ""])[:4]


def _known_names(s: Store) -> set:
    names = set(ISO_BY_TABLE_NAME) | set(legal.EU_MEMBER_STATES) | set(legal.ANNEX_III_NAMES)
    other = s.values["other_table"]
    if other.lower().startswith("other countries"):
        names.add(other)
    return names


def _country(s: Store, name: str) -> str:
    return known(name, _known_names(s))


def _origin_extra(s: Store) -> dict:
    extra = {name: {"iso": iso, "kind": "eu"} for name, iso in legal.EU_MEMBER_STATES.items()}
    point1 = s.annex.get("annex_iii_point_1") or {}
    for name in point1.get("countries", []):
        extra[name] = {"iso": legal.ANNEX_III_ISO.get(name), "kind": "annex_iii"}
    for name in point1.get("territories", []):
        extra[name] = {"iso": None, "kind": "annex_iii"}
    return extra


def _resolve(s: Store, country) -> dict:
    tables = list(s.values["tables"])
    extra = _origin_extra(s)
    name, suggestions = resolve_country(country, tables, extra)
    if name is None:
        if suggestions:
            raise InputError(f"country {clean(country, 100)!r} not recognised; did you mean: "
                             f"{', '.join(clean(x, 100) for x in suggestions)}?")
        return {"name": clean(country, 100), "label": clean(country, 100), "kind": "unlisted"}
    if name in s.values["tables"]:
        kind = "other" if name == s.values["other_table"] else "table"
        return {"name": name, "label": _country(s, name), "kind": kind, "iso": ISO_BY_TABLE_NAME.get(name)}
    return {"name": name, "label": _country(s, name), **extra[name]}


def _is_heading(s: Store, code: str) -> bool:
    row = _row(s, s.values["other_table"], code)
    return bool(row) and parse_value(row[2])[1] == "see_below"


def _match_lines(s: Store, digits: str) -> list[str]:
    order = s.values["_order"]
    below = [c for c in order if c.startswith(digits)]
    if below:
        # "see below" rows only point at their sub-lines; rows with values of their own stay.
        return [c for c in below if not _is_heading(s, c)] or below
    above = [c for c in order if digits.startswith(c)]
    return [max(above, key=len)] if above else []


def _values_for(s: Store, code: str, origin: dict) -> dict:
    line = s.values["_lines"][code]
    other = s.values["other_table"]
    shown = known(line[1], CODE)
    item = {"table_line": shown, "description": remote(line[2]), "goods_category": known(line[3], CATEGORIES)}
    fallback = None
    row = _row(s, origin["name"], code) if origin["kind"] in ("table", "other") else None
    if origin["kind"] == "unlisted":
        fallback = {"reason": f"{origin['label']!r} is not one of the countries in the tables", "rule": legal.RULE_NOT_LISTED}
    elif row is None:
        fallback = {"reason": f"the table for {origin['label']} has no line {shown}", "rule": legal.RULE_NO_VALUE}
    elif any(parse_value(x)[1] == "dash" for x in row[:3]):
        fallback = {"reason": f"the table for {origin['label']} shows '–' for {shown}", "rule": legal.RULE_NO_VALUE}
    if fallback:
        row = _row(s, other, code)
        item["values_from_table"] = _country(s, other)
        item["fallback"] = fallback
    else:
        item["values_from_table"] = origin["label"]
    if row is None:
        item["found"] = False
        return item
    item["found"] = True
    (direct, dk), (indirect, ik), (total, tk) = (parse_value(x) for x in row[:3])
    item.update({"total": total, "direct": direct, "indirect": indirect,
                 "as_published": {"direct": known(row[0], PUBLISHED), "indirect": known(row[1], PUBLISHED),
                                  "total": known(row[2], PUBLISHED)}})
    if ik == "not_applicable":
        item["indirect_note"] = "'N/A' in the table"
    if tk == "see_below":
        item["note"] = "the table gives values for the sub-lines of this heading, not for the heading itself"
    item["production_route"] = _routes(row[3])
    a4 = s.values["annex_iv"].get(code)
    if a4:
        v, r = (a4.split("|") + [""])[:2]
        item["annex_iv_highest_default"] = {"value": parse_value(v)[0], "as_published": known(v, PUBLISHED),
                                            "production_route": _routes(r), "use": legal.ANNEX_IV_USE}
    return item


def _values_legal(s: Store) -> dict:
    m = s.values["meta"]
    check = m.get("oj_check")
    out = {"legally_binding": False,
           "legally_binding_source": legal.VALUES_BINDING_SOURCE,
           "legal_status_of_data": legal.EXCEL_NOTICE,
           "data_version": _values_version(s),
           "data_version_note": remote(m.get("version_note")),
           "attribution": _values_attribution(s),
           "not_legal_advice": legal.NOT_LEGAL_ADVICE}
    if check:
        out["checked_against_official_journal"] = (
            f"On {_date(check.get('checked'))} cbam-mcp compared this file with the Official Journal text of "
            f"{known(check.get('celex'), CELEX)}: {int(check['rows_identical'])} of {int(check['rows_compared'])} "
            f"country lines and {int(check['annex_iv_identical'])} of {int(check['annex_iv_compared'])} Annex IV "
            f"lines identical.")
    return out


def _value_notes(lines_found: bool) -> list:
    if not lines_found:
        return []
    return [legal.MARKUP_POINTER, {"direct_and_indirect": legal.DIRECT_INDIRECT_FOR_INFORMATION},
            {"no_production_route": legal.NO_ROUTE}]


def _origin_answer(s: Store, origin: dict) -> dict | None:
    q = s.annex.get("quotes", {})
    if origin["kind"] == "eu":
        return {"status": "not_a_third_country",
                "explanation": f"{origin['label']} is an EU Member State ({legal.EU_MEMBER_STATES_SOURCE}, checked "
                               f"{legal.CHECKED}). Regulation (EU) 2023/956 covers goods originating in a third "
                               f"country; Article 2(1) is quoted in article_2_1.",
                "article_2_1": remote(q.get("article_2_1"))}
    if origin["kind"] == "annex_iii":
        return {"status": "origin_outside_cbam",
                "explanation": f"{origin['label']} is listed in point 1 of Annex III to Regulation (EU) 2023/956, "
                               f"whose goods the Regulation does not cover; Article 2(4) is quoted in article_2_4.",
                "article_2_4": remote(q.get("article_2_4"))}
    return None


def default_value(cn_code, country) -> dict:
    s = store()
    digits, warnings = normalize_cn(cn_code)
    origin = _resolve(s, country)
    scope = classify(s.annex["annex_i"], digits)
    out: dict = {"cn_code": format_cn(digits), "country": origin["label"], "unit": UNIT,
                 "scope_status": scope["status"]}
    blocked = _origin_answer(s, origin)
    if blocked:
        out.update(blocked)
        out["lines"] = []
    elif digits.startswith(ELECTRICITY[:4]):
        out["status"] = "not_in_this_data"
        out["explanation"] = ("Default values for electricity are in Annex III to Implementing Regulation (EU) "
                              "2025/2621, which the Commission Excel does not contain; this tool does not carry them.")
        out["rule"] = legal.ELECTRICITY
        out["licence_of_annex_iii"] = legal.IEA_NOTICE
        out["lines"] = []
    else:
        codes = _match_lines(s, digits)
        if not codes:
            out["status"] = "no_line"
            out["explanation"] = (f"The default-value tables have no line for {format_cn(digits)}"
                                  + (" (not in CBAM scope under Annex I)." if scope["status"] == "not_in_scope" else "."))
            out["lines"] = []
        else:
            out["status"] = "found"
            if origin["kind"] == "unlisted":
                warnings.append(f"{origin['label']!r} is not a country name in the tables; if it is a third country "
                                "that is not listed, the 'Other countries and territories' values apply as shown")
            out["lines"] = [_values_for(s, c, origin) for c in codes[:60]]
            if len(codes) > 60:
                warnings.append(f"{len(codes)} table lines match; the first 60 are shown. Ask for a longer code.")
            if len(codes) > 1 and len(digits) >= 8:
                warnings.append("several table lines (TARIC codes) match this CN code; the description decides which applies")
    out["notes"] = _value_notes(bool(out["lines"]))
    if out["lines"]:
        _warn_not_cn(s, digits, warnings, "the table line shown is the one whose code it starts with")
    if scope["status"] == "partially_in_scope" and scope["basis"] == "ex_code":
        warnings.append(f"Annex I lists {format_cn(scope['entry']['code'])} as an 'ex' line: only part of this code "
                        "is in scope (see cbam_scope)")
    out["warnings"] = warnings
    out.update(_values_legal(s))
    return out


def compare_origins(cn_code, countries) -> dict:
    s = store()
    digits, warnings = normalize_cn(cn_code)
    if isinstance(countries, str):
        countries = countries.split(",")
    if not isinstance(countries, list) or not countries:
        raise InputError("countries must be a list of country names or ISO codes, e.g. ['India', 'TR']")
    if len(countries) > 30:
        raise InputError("at most 30 countries per comparison")
    origins, problems = [], []
    for c in countries:
        try:
            origins.append(_resolve(s, c))
        except InputError as e:
            problems.append(str(e))
    out: dict = {"cn_code": format_cn(digits), "unit": UNIT, "scope_status": classify(s.annex["annex_i"], digits)["status"]}
    if digits.startswith(ELECTRICITY[:4]):
        out.update({"status": "not_in_this_data", "rule": legal.ELECTRICITY, "lines": []})
    else:
        codes = _match_lines(s, digits)[:30]
        other = {"name": s.values["other_table"], "label": _country(s, s.values["other_table"]), "kind": "other"}
        lines = []
        for code in codes:
            ref = _values_for(s, code, other)
            by_country = []
            for o in origins:
                blocked = _origin_answer(s, o)
                if blocked:
                    by_country.append({"country": o["label"], **blocked})
                    continue
                v = _values_for(s, code, o)
                row = {"country": o["label"]}
                row.update({k: v[k] for k in ("total", "direct", "indirect", "values_from_table", "fallback",
                                              "production_route", "as_published", "indirect_note") if v.get(k) is not None})
                by_country.append(row)
            lines.append({"table_line": ref["table_line"], "description": ref["description"],
                          "goods_category": ref["goods_category"], "by_country": by_country,
                          "other_countries_and_territories": {k: ref.get(k) for k in ("total", "direct", "indirect",
                                                                                      "production_route")},
                          "annex_iv_highest_default": ref.get("annex_iv_highest_default")})
        out["status"] = "found" if lines else "no_line"
        out["lines"] = lines
    out["countries_not_recognised"] = problems
    out["notes"] = _value_notes(bool(out["lines"]))
    if out["lines"]:
        _warn_not_cn(s, digits, warnings, "the table line shown is the one whose code it starts with")
    out["warnings"] = warnings
    out.update(_values_legal(s))
    return out


# ------------------------------------------------------------------ cn_describe

def _cn_code(value: str):
    return format_cn(value) if value.isdigit() else known(value or None, CODE)


def cn_describe(cn_code, year: int = 2026) -> dict:
    s = store()
    digits, warnings = normalize_cn(cn_code)
    if isinstance(year, bool) or year is None:
        raise InputError("year must be 2025 or 2026")
    try:
        year = int(year)
    except (TypeError, ValueError, OverflowError):
        raise InputError("year must be 2025 or 2026") from None
    if year not in (2025, 2026):
        raise InputError("year must be 2025 or 2026 (the bundled CN versions)")
    if len(digits) > 8:
        warnings.append("digits after the eighth are a TARIC subdivision; the CN describes the first 8")
        digits = digits[:8]
    out: dict = {"cn_code": format_cn(digits), "year": year}
    cid, c = s.cn_lookup(year, digits)
    if c is None:
        out["found"] = False
        if s.cn_bundled(digits):
            out["explanation"] = f"{format_cn(digits)} is not a code of CN {year}."
        else:
            out["explanation"] = ("Outside the bundled subset (chapters 25, 28, 31, 72, 73, 76 and headings 2601, "
                                  "2716), which covers the CBAM goods; this tool does not describe other codes.")
    else:
        concepts = s.cn(year)["concepts"]
        out.update({"found": True, "cn_code": format_cn(c[0]), "label": remote(c[1]), "indent": c[2]})
        if c[3]:
            out["self_explanatory_text"] = remote(c[3])
        chain, seen, parent = [], set(), c[4]
        while parent and parent not in seen:
            seen.add(parent)
            p = concepts.get(parent)
            if not p:
                break
            chain.append({"cn_code": _cn_code(p[0]), "label": remote(p[1]), "indent": p[2]})
            parent = p[4]
        out["hierarchy"] = list(reversed(chain))
        kids = [concepts[k] for k in sorted(s.cn_children(year, cid))]
        if kids:
            out["sub_codes"] = [{"cn_code": _cn_code(k[0]), "label": remote(k[1])} for k in kids[:100]]
        other_year = 2025 if year == 2026 else 2026
        _, o = s.cn_lookup(other_year, c[0])
        if o is None:
            out[f"in_cn_{other_year}"] = "no such code"
        elif o[1] != c[1]:
            out[f"in_cn_{other_year}"] = {"label": remote(o[1])}
        else:
            out[f"in_cn_{other_year}"] = "same label"
    out["warnings"] = warnings
    out.update({"legally_binding": False, "legally_binding_source": legal.CN_BINDING_SOURCE[year],
                "data_version": _cn_version(s, year), "attribution": _cn_attribution(s, year),
                "not_legal_advice": legal.NOT_LEGAL_ADVICE})
    return out


# ------------------------------------------------------------------ sources

def _acts(doc) -> dict | None:
    if not isinstance(doc, dict) or not isinstance(doc.get("acts"), dict):
        return None
    out = {"checked": _date(doc.get("checked")), "acts": {}}
    for base, rows in doc["acts"].items():
        out["acts"][known(base, CELEX)] = [
            {"celex": known(r.get("celex"), CELEX), "date": _date(r.get("date")),
             "relation": known(r.get("relation"), {"amends", "corrects"}),
             "english_version": bool(r.get("english_version", True))}
            for r in rows if isinstance(r, dict)]
    return out


def sources() -> dict:
    s = store()
    out = {"datasets": []}
    a = s.annex["meta"]
    out["datasets"].append({
        "name": "CBAM scope: Annexes I, II and III of Regulation (EU) 2023/956",
        "file": "annex_i.json", "url": known(a["url"], URL), "version": known(a["celex"], CELEX),
        "reference": remote(a.get("reference")), "retrieved": _date(a["retrieved"]), "sha256": a["sha256"],
        "rows": {"annex_i": a["annex_i_lines"], "annex_ii": a["annex_ii_lines"]},
        "legally_binding": False, "legal_status": remote(a.get("disclaimer")),
        "legally_binding_source": legal.SCOPE_BINDING_SOURCE, "licence": legal.LICENCES["eurlex"],
        "attribution": _scope_attribution(s)})
    v = s.values["meta"]
    check = v.get("oj_check")
    out["datasets"].append({
        "name": "CBAM default values, definitive period (Commission Excel)",
        "file": "default_values.json", "url": known(v["url"], URL), "page": known(v.get("page"), URL),
        "file_name": remote(v.get("filename")), "version": f"{known(v.get('version'), VERSION)} of {_date(v.get('version_date'))}",
        "version_note": remote(v.get("version_note")), "retrieved": _date(v["retrieved"]), "sha256": v["sha256"],
        "rows": {"tables": v["tables"], "country_lines": v["rows"], "cn_taric_lines": v["lines"], "annex_iv": v["annex_iv_rows"]},
        "legally_binding": False, "legal_status": legal.EXCEL_NOTICE, "disclaimer_in_file": remote(v.get("disclaimer")),
        "legally_binding_source": legal.VALUES_BINDING_SOURCE,
        "official_journal_check": check and {
            "checked": _date(check.get("checked")), "celex": known(check.get("celex"), CELEX),
            **{k: int(check[k]) for k in ("rows_compared", "rows_identical", "annex_iv_compared", "annex_iv_identical")},
            "quotes_found": {k: bool(x) for k, x in check.get("quotes_found", {}).items()}},
        "not_included": "Annexes II and III to Implementing Regulation (EU) 2025/2621 (indirect-emission factors, "
                        "electricity); the Excel does not contain them",
        "licence": legal.LICENCES["commission"], "attribution": _values_attribution(s)})
    for year in (2026, 2025):
        m = s.cn(year)["meta"]
        out["datasets"].append({
            "name": f"Combined Nomenclature {year} (subset)", "file": f"cn_{year}.json", "url": known(m["scheme"], URL),
            "endpoint": known(m["endpoint"], URL), "dataset": known(m["dataset"], URL), "subset": m["subset"],
            "retrieved": _date(m["retrieved"]), "sha256_of_responses": m["sha256_of_responses"],
            "rows": {"concepts": m["concepts"]}, "legally_binding": False,
            "legally_binding_source": legal.CN_BINDING_SOURCE[year], "licence": legal.LICENCES["cn"],
            "attribution": _cn_attribution(s, year)})
    try:
        out["later_acts"] = _acts(json.loads((s.dir / "later_acts.json").read_text(encoding="utf-8")))
    except (OSError, ValueError):
        out["later_acts"] = None
    out["data_directory"] = str(s.dir)
    out["not_legal_advice"] = legal.NOT_LEGAL_ADVICE
    return out
