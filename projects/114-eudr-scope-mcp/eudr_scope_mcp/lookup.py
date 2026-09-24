"""Answers from the bundled snapshot. No network access happens here.

Every answer carries the legal acts and consolidated version it rests on, the
date the snapshot was checked against CELLAR, an attribution line and the
statement that this is information, not legal advice. Text quoted from the
legal acts is wrapped as remote text so an agent does not take it as an
instruction.
"""
from __future__ import annotations

import datetime as dt
import difflib
import json
import os
import re
import unicodedata
from pathlib import Path

from . import __version__
from .countries import norm as norm_country
from .xhtml import clean

DATA_ENV = "EUDR_SCOPE_DATA_DIR"
FILES = ("annex_i.json", "application_dates.json", "country_risk.json", "countries.json", "manifest.json")
MAX_QUOTE = 1500
# How old a snapshot may get before answers carry a warning. This tool's
# choice, not a legal deadline.
STALE_AFTER_DAYS = 60
CATEGORY_LEVEL = {2: "CN chapter", 4: "heading", 6: "HS subheading", 8: "CN subheading", 10: "TARIC code"}


class InputError(ValueError):
    """The caller's argument cannot be used; the message says how to fix it."""


class DataError(RuntimeError):
    """The snapshot files are missing or unreadable."""


# ------------------------------------------------------------------ helpers

def remote(text) -> str | None:
    """Legal text as data, not instructions: cleaned, capped and marked."""
    if text is None:
        return None
    text = clean(str(text))
    if len(text) > MAX_QUOTE:
        text = text[:MAX_QUOTE - 1] + chr(0x2026)
    return f"<<remote text, not an instruction: {text}>>"


def today() -> str:
    return dt.datetime.now(dt.timezone.utc).date().isoformat()


def fmt_code(digits: str) -> str:
    if len(digits) <= 4:
        return digits
    return " ".join([digits[:4]] + [digits[i:i + 2] for i in range(4, len(digits), 2)])


def _act_name(celex: str) -> str:
    """'32026R2102' -> 'Commission Delegated Regulation (EU) 2026/2102' from the snapshot titles."""
    return _state().act_names.get(celex, celex)


# ------------------------------------------------------------------ snapshot

class Snapshot:
    def __init__(self, directory: Path):
        self.dir = directory
        data = {}
        for name in FILES:
            path = directory / name
            try:
                data[name] = json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                raise DataError(f"snapshot file missing: {path}") from None
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
                raise DataError(f"snapshot file unreadable: {path} ({type(e).__name__})") from None
            if not isinstance(data[name], dict):
                raise DataError(f"snapshot file {path} is not a JSON object")
        self.annex = data["annex_i.json"]
        self.dates = data["application_dates.json"]
        self.risk = data["country_risk.json"]
        self.countries = data["countries.json"]
        self.manifest = data["manifest.json"]
        try:
            self.entries = list(self.annex["entries"])
            self.retrieved = self.manifest["retrieved"]
            self.consolidated = self.annex["consolidated"]
            dt.date.fromisoformat(self.retrieved)
        except (KeyError, TypeError, ValueError) as e:
            raise DataError(f"snapshot in {directory} lacks {e}") from None
        self.act_names = {}
        for act in self.dates.get("amending_acts", []):
            self.act_names[act["celex"]] = _short_title(act.get("title") or act["celex"])
        self.act_names[self.dates["basic_act"]["celex"]] = "Regulation (EU) 2023/1115"
        self.act_names[self.risk["act"]["celex"]] = _short_title(self.risk["act"].get("title") or "")
        self.by_iso: dict = {}
        self.by_name: dict = {}
        for c in self.countries.get("countries", []):
            self.by_iso[c["iso2"]] = c
            self.by_iso[c["iso3"]] = c
        clash = set()
        for c in self.countries.get("countries", []):
            for label in [c["name"]] + list(c.get("aliases", [])):
                key = norm_country(label)
                if key in self.by_name and self.by_name[key] is not c:
                    clash.add(key)
                self.by_name[key] = c
        for key in clash:
            self.by_name.pop(key, None)
        self.listed = {}
        for level in ("low", "high"):
            for item in self.risk.get(level, []):
                self.listed[item["iso3"]] = (level, item["annex_name"])
                if item["iso3"] in self.by_iso:  # the Annex's own spelling, e.g. "Solomon Island"
                    self.by_name[norm_country(item["annex_name"])] = self.by_iso[item["iso3"]]


def _short_title(title: str) -> str:
    m = re.match(r"^((?:Commission (?:Delegated |Implementing )?)?Regulation \(EU\) \d{4}/\d+)", title or "")
    return m.group(1) if m else (title or "")[:80]


_cache: dict = {}


def data_dir() -> Path:
    env = os.environ.get(DATA_ENV)
    if env:
        return Path(env)
    here = Path(__file__).resolve().parent
    packaged = here / "data"  # installed wheel: the data/ folder ships inside the package
    return packaged if (packaged / "manifest.json").exists() else here.parent / "data"


def _state() -> Snapshot:
    directory = data_dir()
    key = str(directory)
    if key not in _cache:
        _cache[key] = Snapshot(directory)
    return _cache[key]


def reset_cache() -> None:
    _cache.clear()


def attribution(retrieved: str, topic: str, derived: bool = False, table_version: str | None = None) -> str:
    """The attribution line for one kind of answer (also quoted in SOURCES.md)."""
    where = f"from EUR-Lex/CELLAR, Publications Office of the European Union, retrieved {retrieved}; (c) European Union"
    if topic == "country":
        return (f"Source: Commission Implementing Regulation (EU) 2025/1093 as published in the Official Journal, {where}; "
                "reuse under the EUR-Lex legal notice and Commission Decision 2011/833/EU. ISO codes from the EU "
                f"'Countries and territories' authority table (version {table_version}), matched by eudr-scope-mcp.")
    text = (f"Source: consolidated text of Regulation (EU) 2023/1115 (CC BY 4.0) and the amending acts as published "
            f"in the Official Journal, {where}.")
    if topic == "annex":
        text += (" Changes: Annex I derived by eudr-scope-mcp, amending acts applied to the consolidated text."
                 if derived else " Extracted by eudr-scope-mcp.")
    elif topic == "dates":
        text += " Dates read from the article texts by eudr-scope-mcp."
    return text


def _join(names: list) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def disclaimer(topic: str) -> str:
    """Information, not advice, and which acts are the legally binding ones."""
    s = _state()
    if topic == "country":
        return ("Information, not legal advice. The legally binding act is "
                f"{_act_name(s.risk['act']['celex'])}, as published in the Official Journal of the European Union.")
    amending = [_act_name(a["celex"]) for a in s.dates.get("amending_acts", [])]
    binding = "Regulation (EU) 2023/1115" + (" as amended by " + _join(amending) if amending else "")
    return ("Information, not legal advice. The consolidated text used here is a documentation tool with no legal "
            f"effect; the legally binding acts are {binding}, as published in the Official Journal of the European "
            "Union.")


def _common(topic: str) -> dict:
    """Provenance, attribution and disclaimer for one kind of answer."""
    s = _state()
    cons = s.consolidated
    applied = s.annex.get("amendments_applied", [])
    amending = [_act_name(a["celex"]) for a in s.dates.get("amending_acts", [])]
    if topic == "country":
        act = s.risk["act"]
        out = {"legal_acts": [_act_name(act["celex"]), "Regulation (EU) 2023/1115, Article 29"],
               "source_text": {"celex": act.get("source_text") or act["celex"], "entry_into_force": act.get("entry_into_force")},
               "checked": s.risk.get("retrieved", s.retrieved)}
    else:
        out = {"legal_acts": ["Regulation (EU) 2023/1115"] + amending,
               "consolidated_version": {"celex": cons["celex"], "date": cons["date"], "reference": cons["reference"]},
               "checked": s.retrieved}
        if topic == "annex":
            out["amendments_applied_by_this_tool"] = [
                {"celex": a["celex"], "act": _act_name(a["celex"]), "entry_into_force": a["entry_into_force"]}
                for a in applied]
    if topic == "sources":
        out["legal_acts"].append(_act_name(s.risk["act"]["celex"]))
    out["attribution"] = attribution(out["checked"], topic, derived=bool(applied),
                                     table_version=s.countries.get("version"))
    out["disclaimer"] = disclaimer(topic)
    age = (dt.date.fromisoformat(today()) - dt.date.fromisoformat(s.retrieved)).days
    if age > STALE_AFTER_DAYS:
        out["warning"] = (f"This snapshot was checked against CELLAR on {s.retrieved}, {age} days ago. Acts adopted "
                          "since are not reflected; run `eudr-scope-mcp refresh`.")
    return out


# ------------------------------------------------------------ CN codes

def normalize_cn(value) -> tuple:
    """-> (digits, notes). Accepts '1801 00 00', '18010000', '1801.00.00', 'CN 1801', 'ex 0201'."""
    notes = []
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise InputError("cn_code must be a string such as '1801 00 00'")
    if isinstance(value, int):
        if value < 0:
            raise InputError("cn_code must not be negative")
        text = str(value)
        if len(text) % 2:
            # JSON numbers lose the leading zero of chapters 01-09.
            text = "0" + text
            notes.append("A leading zero was restored: CN codes of chapters 01 to 09 start with 0; pass codes as strings.")
    else:
        if len(value) > 40:
            raise InputError("cn_code is too long; a CN code has at most 8 digits (10 for TARIC)")
        text = unicodedata.normalize("NFKC", value).strip()
    text = re.sub(r"^(?:(?:cn|hs|taric)(?:\s*code)?\s*:?\s*)", "", text, flags=re.I)
    if re.match(r"^ex\b", text, flags=re.I):
        text = re.sub(r"^ex\s*", "", text, flags=re.I)
        notes.append("The 'ex' prefix in the input was ignored; the answer says whether the code falls under an 'ex' entry.")
    digits = re.sub(r"[\s.\-_/]", "", text)
    if not digits:
        raise InputError("cn_code is empty")
    if not re.fullmatch(r"[0-9]+", digits):
        shown = re.sub(r"[^\x20-\x7e]", "?", str(value))[:30]
        raise InputError(f"cn_code may contain only digits, spaces, dots and hyphens; got {shown!r}")
    if len(digits) not in CATEGORY_LEVEL:
        raise InputError(f"cn_code has {len(digits)} digits; use 2 (chapter), 4 (heading), 6, 8 (CN subheading) "
                         "or 10 (TARIC)")
    if len(digits) == 10:
        notes.append("TARIC code: Annex I uses CN codes, so the first 8 digits were looked up.")
        digits = digits[:8]
    return digits, notes


def _check_date(on_date) -> str:
    s = _state()
    if on_date in (None, ""):
        return today()
    if not isinstance(on_date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", on_date):
        raise InputError("date must be YYYY-MM-DD")
    try:
        dt.date.fromisoformat(on_date)
    except ValueError:
        raise InputError(f"date {on_date!r} is not a calendar date") from None
    first = s.consolidated["date"]
    if on_date < first:
        raise InputError(f"this snapshot covers Annex I from {first} (the consolidated version it starts from); "
                         f"earlier versions are not included")
    if on_date > "2100-12-31":
        raise InputError("date is too far in the future")
    return on_date


def _live(e: dict, day: str) -> bool:
    return (e["valid_from"] is None or e["valid_from"] <= day) and (e["valid_to"] is None or e["valid_to"] >= day)


def _source_text(e: dict) -> str:
    src = e["source"]
    if src["celex"] == _state().consolidated["celex"]:
        return f"Regulation (EU) 2023/1115, Annex I (consolidated text {src['celex']})"
    return f"{_act_name(src['celex'])}, {src['provision']}"


def _view(e: dict, relation: str | None = None) -> dict:
    view = {
        "annex_entry": e["label"],
        "codes": [fmt_code(c["code"]) for c in e["codes"]],
        "ex": any(c["ex"] for c in e["codes"]),
        "commodity": e["commodity"],
        "description": remote(e["description"]),
        "notes": [remote(n) for n in e["notes"]],
        "valid_from": e["valid_from"],
        "valid_to": e["valid_to"],
        "source": _source_text(e),
    }
    if e.get("removed_by"):
        view["removed_by"] = f"{_act_name(e['removed_by']['celex'])}, {e['removed_by']['provision']}"
    if relation:
        view["relation"] = relation
    return view


def _table_notes(commodities, day: str) -> list:
    out = []
    for n in _state().annex.get("table_notes", []):
        if n["valid_from"] and n["valid_from"] > day:
            continue
        if n["attached_to"] is None or n["attached_to"] in commodities:
            out.append({"note": f"({n['number']})", "applies_to": n["attached_to"] or "all relevant products",
                        "text": remote(n["text"]), "source": f"{_act_name(n['source']['celex'])}, {n['source']['provision']}"})
    return out


def _partial(e: dict, inside: list) -> bool:
    """An 'ex' code, or an entry with its own exclusions, covers only part of the goods under the code."""
    return (all(c["ex"] for c in inside) or bool(e["notes"])
            or "with the exception of" in e["description"])


def _horizon(day: str) -> str:
    checked = _state().retrieved
    if day > checked:
        return f" (Checked on {checked}; acts adopted after that date are not reflected in an answer for {day}.)"
    return ""


def eudr_scope(cn_code, date: str | None = None) -> dict:
    digits, notes = normalize_cn(cn_code)
    day = _check_date(date)
    s = _state()
    containing, below, later, earlier = [], [], [], []
    for e in s.entries:
        codes = [c["code"] for c in e["codes"]]
        inside = [c for c in e["codes"] if digits.startswith(c["code"])]
        under = any(k.startswith(digits) and len(k) > len(digits) for k in codes)
        if not inside and not under:
            continue
        if _live(e, day):
            if inside:
                containing.append((e, inside))
            else:
                below.append(e)
        elif e["valid_from"] and e["valid_from"] > day:
            later.append(e)
        elif e["valid_to"] and e["valid_to"] < day:
            earlier.append(e)
    shown = fmt_code(digits)
    level = CATEGORY_LEVEL[len(digits)]
    commodities = sorted({e["commodity"] for e, _ in containing} | {e["commodity"] for e in below})
    if containing:
        full = [e for e, inside in containing if not _partial(e, inside)]
        e, inside = next(((x, i) for x, i in containing if x in full), containing[0])
        if full:
            status = "relevant_product"
            answer = (f"Yes: CN {shown} falls under Annex I entry '{e['label']}' ({e['commodity']}) on {day}; goods "
                      "under this code are relevant products within the meaning of Article 2, point (2), of Regulation "
                      "(EU) 2023/1115 (general exclusions such as samples are in table_notes).")
        else:
            status = "partly_ex"
            kind = "the 'ex' entry" if all(c["ex"] for c in inside) else "the entry"
            answer = (f"Depends: CN {shown} falls under {kind} '{e['label']}' ({e['commodity']}) on {day}, which covers "
                      "only part of the goods under this code. Question to settle: do the goods match the entry's "
                      "description and fall outside each exclusion quoted in its notes or text? Only then are they "
                      "relevant products.")
    elif below:
        status = "heading_with_listed_codes"
        labels = ", ".join(e["label"] for e in below[:12]) + (" ..." if len(below) > 12 else "")
        answer = (f"Depends on the sub-code: CN {shown} ({level}) is not listed as a whole on {day}; Annex I lists "
                  f"{len(below)} entr{'y' if len(below) == 1 else 'ies'} under it: {labels}. Look up the code of the goods.")
    else:
        status = "not_listed"
        answer = (f"No: CN {shown} is not listed in Annex I on {day}, so goods under this code are not relevant "
                  "products under Regulation (EU) 2023/1115. This tool does not check that the code exists in the "
                  "Combined Nomenclature.")
    if later:
        answer += " Later: " + "; ".join(f"'{e['label']}' applies from {e['valid_from']}" for e in later[:6]) + "."
    if earlier and not containing:
        answer += " Earlier: " + "; ".join(f"'{e['label']}' until {e['valid_to']}" for e in earlier[:6]) + "."
    answer += _horizon(day)
    table_status = status
    if s.annex.get("status") != "verified":
        status = "unverified"
        answer = ("unverified: " + "; ".join(s.annex.get("status_reasons", [])[:3])
                  + ". What the table last verified says (may be outdated): " + answer)
    notes.append("The answer depends on the CN classification of the goods, which this tool does not check.")
    result = {
        "input": str(cn_code)[:40], "cn_code": digits, "cn_code_display": shown, "level": level, "date": day,
        "status": status, "answer": answer, "table_status": table_status,
        "commodities": commodities,
        "matches": [_view(e, "the code falls under this entry") for e, _ in containing],
        "listed_under_this_code": [_view(e, "entry under this code") for e in below],
        "applies_later": [_view(e) for e in later],
        "removed_earlier": [_view(e) for e in earlier],
        "table_notes": _table_notes(commodities, day),
        "annex_i_introduction": [remote(p) for p in s.annex.get("intro", [])],
        "legal_basis": ("Article 1(1), Article 2, point (2), and Annex I of Regulation (EU) 2023/1115"
                        + ("; Annex I as amended by " + ", ".join(_act_name(a["celex"]) for a in s.annex["amendments_applied"])
                           if s.annex.get("amendments_applied") else "")),
        "notes": notes,
        "data_status": s.annex.get("status"),
    }
    if s.annex.get("status") != "verified":
        result["data_status_reasons"] = s.annex.get("status_reasons", [])
    result.update(_common("annex"))
    return result


# ------------------------------------------------------------ commodities

COMMODITY_ALIASES = {  # this tool's convenience spellings
    "cattle": "Cattle", "cocoa": "Cocoa", "coffee": "Coffee", "oil palm": "Oil palm", "palm oil": "Oil palm",
    "palm": "Oil palm", "rubber": "Rubber", "natural rubber": "Rubber", "soya": "Soya", "soy": "Soya",
    "soybean": "Soya", "soybeans": "Soya", "soya bean": "Soya", "soya beans": "Soya", "wood": "Wood",
    "timber": "Wood",
}


def commodity_codes(commodity, date: str | None = None) -> dict:
    if not isinstance(commodity, str) or not commodity.strip() or len(commodity) > 40:
        raise InputError("commodity must be one of: cattle, cocoa, coffee, oil palm, rubber, soya, wood")
    key = re.sub(r"[\s_\-]+", " ", commodity.strip().casefold())
    name = COMMODITY_ALIASES.get(key)
    if not name:
        raise InputError("commodity must be one of: cattle, cocoa, coffee, oil palm, rubber, soya, wood "
                         "(Article 2, point (1), of Regulation (EU) 2023/1115)")
    day = _check_date(date)
    s = _state()
    mine = [e for e in s.entries if e["commodity"] == name]
    live = [e for e in mine if _live(e, day)]
    later = [e for e in mine if e["valid_from"] and e["valid_from"] > day]
    removed = [e for e in mine if e["valid_to"] and e["valid_to"] < day]
    answer = (f"On {day}, Annex I lists {len(live)} entr{'y' if len(live) == 1 else 'ies'} under {name}"
              + (f"; {len(later)} more apply later" if later else "")
              + (f"; {len(removed)} earlier entr{'y was' if len(removed) == 1 else 'ies were'} replaced or removed"
                 if removed else "") + "." + _horizon(day))
    if s.annex.get("status") != "verified":
        answer = ("unverified: " + "; ".join(s.annex.get("status_reasons", [])[:3])
                  + ". What the table last verified says (may be outdated): " + answer)
    result = {
        "commodity": name, "date": day, "status": s.annex.get("status"),
        "answer": answer,
        "entries": [_view(e) for e in live],
        "applies_later": [_view(e) for e in later],
        "replaced_or_removed": [_view(e) for e in removed],
        "table_notes": _table_notes([name], day),
        "legal_basis": "Article 2, point (1), and Annex I of Regulation (EU) 2023/1115",
        "data_status": s.annex.get("status"),
    }
    result.update(_common("annex"))
    return result


# ------------------------------------------------------------ dates

OPERATOR_TYPES = {
    "all": "all", "large": "large", "large undertaking": "large", "large undertakings": "large",
    "large enterprise": "large", "medium": "medium", "medium sized": "medium", "medium undertaking": "medium",
    "medium sized undertaking": "medium", "sme": "sme", "smes": "sme", "micro": "micro_small",
    "small": "micro_small", "micro or small": "micro_small", "micro undertaking": "micro_small",
    "small undertaking": "micro_small", "micro or small undertaking": "micro_small", "micro and small": "micro_small",
    "natural person": "micro_small", "micro or small primary operator": "primary", "primary operator": "primary",
    "downstream operator": "downstream", "trader": "trader", "operator": "operator",
}


def application_dates(operator_type: str = "all") -> dict:
    if not isinstance(operator_type, str) or len(operator_type) > 60:
        raise InputError("operator_type must be a string")
    key = re.sub(r"[\s_\-]+", " ", operator_type.strip().casefold().replace("/", " or "))
    category = OPERATOR_TYPES.get(key or "all")
    if not category:
        raise InputError("operator_type must be one of: all, large, medium, sme, micro, small, micro or small, "
                         "natural person, micro or small primary operator, downstream operator, trader, operator")
    s = _state()
    d = s.dates
    a38, a37 = d["article_38"], d["article_37"]
    verified = d.get("status") == "verified"
    set_by = a38.get("set_by")
    set_by_text = f"{_act_name(set_by['celex'])}, {set_by['provision']}" if set_by else None

    def row(par: str, who: str, extra=None):
        date_ = a38["p2_date"] if par == "2" else a38["p3_date"]
        r = {"applies_from": date_ if verified else "unverified", "provision": f"Article 38({par})",
             "who": who, "text": remote(a38["paragraphs"][par]),
             "set_by": set_by_text, "status": "verified" if verified else "unverified"}
        if par == "3":
            r["conditions"] = [f"established as such by {a38['p3_established_by']}",
                               "natural person, or micro- or small undertaking within the meaning of Article 3(1) or "
                               "Article 3(2), first subparagraph, of Directive 2013/34/EU, irrespective of legal form"]
            if a38.get("p3_excludes_eutr_products"):
                r["conditions"].append("does not apply to products covered by the Annex to Regulation (EU) No 995/2010 "
                                       "(timber products under the EU Timber Regulation): for those, Article 38(2) applies")
        if extra:
            r["note"] = extra
        if not verified:
            r["reasons"] = d.get("status_reasons", [])
        return r

    general = "operators, downstream operators and traders not covered by Article 38(3)"
    micro = ("operators that are natural persons or micro- or small undertakings, established as such by "
             f"{a38['p3_established_by']}")
    fallback = "the same operators if a condition of Article 38(3) is not met"
    rows, definition = [], None
    defs = d.get("definitions", {})
    if category == "large":
        rows = [row("2", "large undertakings (not SMEs)", "Article 38(3) covers only natural persons and micro- or small undertakings.")]
    elif category == "medium":
        rows = [row("2", "medium-sized undertakings", "Article 38(3) covers only natural persons and micro- or small undertakings.")]
        definition = ("Article 2, point (30)", defs.get("30"))
    elif category == "sme":
        rows = [row("3", micro), row("2", "medium-sized undertakings, and micro or small ones outside Article 38(3)")]
        definition = ("Article 2, point (30)", defs.get("30"))
    elif category == "micro_small":
        rows = [row("3", micro), row("2", fallback)]
    elif category == "primary":
        rows = [row("3", micro), row("2", fallback)]
        definition = ("Article 2, point (15a)", defs.get("15a"))
    elif category in ("downstream", "trader"):
        label = "downstream operators" if category == "downstream" else "traders"
        rows = [row("2", label,
                    "Article 38(3) defers the date for 'operators, whether natural persons or micro- or small "
                    "undertakings'; Article 2 defines operator (point 15), downstream operator (point 15b) and trader "
                    "(point 17) separately. This tool does not decide whether Article 38(3) extends to "
                    f"{label}.")]
        definition = ("Article 2, point (15b)" if category == "downstream" else "Article 2, point (17)",
                      defs.get("15b" if category == "downstream" else "17"))
    elif category == "operator":
        rows = [row("2", general), row("3", micro)]
        definition = ("Article 2, point (15)", defs.get("15"))
    else:
        rows = [row("2", general), row("3", micro)]

    first = rows[0]
    if verified and category in ("large", "medium"):
        answer = f"From {first['applies_from']} ({first['provision']}) for {first['who']}."
    elif verified and category in ("downstream", "trader"):
        answer = (f"From {first['applies_from']} ({first['provision']}) for {first['who']} that are not natural persons "
                  f"or micro- or small undertakings. Depends for micro or small ones: {a38['p3_date']} if Article "
                  "38(3) extends to them. Question for counsel: does Article 38(3), worded for 'operators', cover "
                  f"{first['who']} that are natural persons or micro- or small undertakings?")
    elif verified:
        p3 = next(r for r in rows if r["provision"] == "Article 38(3)")
        p2 = next(r for r in rows if r["provision"] == "Article 38(2)")
        answer = (f"Depends on two facts for natural persons and micro- or small undertakings: were they established "
                  f"as such by {a38['p3_established_by']}, and are the products outside the Annex to Regulation (EU) "
                  f"No 995/2010? If both, from {p3['applies_from']} (Article 38(3)); otherwise from "
                  f"{p2['applies_from']} (Article 38(2))"
                  + (f", which also applies to {p2['who']}" if category in ("sme", "operator", "all") else "") + ".")
    else:
        answer = "unverified: " + "; ".join(d.get("status_reasons", [])[:3])
    if verified:
        answer += f" The obligations concerned are {a38['p2_articles']}."
    related = [
        {"date": a38["entry_into_force"], "provision": "Article 38(1) and Article 1(2)",
         "what": "entry into force; relevant products produced before this date are outside the Regulation, "
                 "except timber under Article 37(3)"},
        {"date": a37["p1_repeal_from"], "provision": "Article 37(1)",
         "what": "Regulation (EU) No 995/2010 (EU Timber Regulation) repealed"},
        {"date": a37["p2_until"], "provision": "Article 37(2)",
         "what": f"Regulation (EU) No 995/2010 still applies until this date to timber produced before "
                 f"{a37['p2_produced_before']} and placed on the market from {a37['p2_placed_from']}"},
    ]
    for group in d.get("annex_i_deferred", []):
        related.append({"date": group["applies_from"], "provision": "Annex I as amended",
                        "what": f"{len(group['entries'])} Annex I entries apply from this date: "
                                + ", ".join(group["entries"])})
    if not verified:
        for r in related:
            r["date"] = "unverified"
    result = {
        "operator_type": operator_type, "category": category, "answer": answer, "dates": rows,
        "obligations_concerned": a38["p2_articles"],
        "definition": {"provision": definition[0], "text": remote(definition[1])} if definition and definition[1] else None,
        "related_dates": related,
        "history": [{"act": _act_name(h["celex"]) if h["celex"] != d["basic_act"]["celex"] else "Regulation (EU) 2023/1115 (original text)",
                     "provision": h["provision"], "article_38_2": h["p2_date"], "article_38_3": h["p3_date"],
                     "established_by": h["p3_established_by"]} for h in d.get("history", [])],
        "pending_proposals": [{"celex": p["celex"], "date": p["date"], "title": remote(p["title"]),
                               "note": "a proposal, not law; not applied"} for p in d.get("pending_proposals", [])],
        "legal_basis": "Article 38 of Regulation (EU) 2023/1115" + (f", as replaced by {set_by_text}" if set_by_text else ""),
        "data_status": d.get("status"),
    }
    if d.get("warnings"):
        result["data_warnings"] = d["warnings"]
    result.update(_common("dates"))
    return result


# ------------------------------------------------------------ countries

def _readings(c: dict, s: "Snapshot", depth: int = 0) -> set:
    """Risk levels the Annex can be read to give an entry of the authority table.

    Listed: its level. A country not listed: standard (Article 1(2)). A
    territory (scheme 'Territories' or recorded under another country):
    standard, or the level of the country it is recorded under, or unknown when
    the table names none. This rule is the tool's reading, documented in README.
    """
    listed = s.listed.get(c["iso3"])
    if listed:
        return {listed[0]}
    if not c.get("territory") and not c.get("part_of"):
        return {"standard"}
    parent = s.by_iso.get(c.get("part_of") or "")
    if parent is None or depth > 5:
        return {"standard", "unknown"}
    return {"standard"} | _readings(parent, s, depth + 1)


def _resolve_country(text: str):
    s = _state()
    raw = text.strip()
    if re.fullmatch(r"[A-Za-z]{2,3}", raw) and raw.upper() in s.by_iso:
        return s.by_iso[raw.upper()]
    return s.by_name.get(norm_country(raw))


def country_risk(country) -> dict:
    if not isinstance(country, str) or not country.strip():
        raise InputError("country must be an ISO 3166-1 alpha-2 or alpha-3 code or an English country name")
    if len(country) > 100 or re.search(r"[\x00-\x1f\x7f]", country):
        raise InputError("country must be at most 100 printable characters")
    s = _state()
    act = s.risk["act"]
    act_name = _act_name(act["celex"])
    base = {"input": country.strip()[:100]}
    c = _resolve_country(country)
    common = _common("country")
    if c is None:
        keys = list(s.by_name)
        close = difflib.get_close_matches(norm_country(country), keys, n=3, cutoff=0.8)
        names = sorted({s.by_name[k]["name"] for k in close})
        base.update({"risk": None, "status": "unknown_country",
                     "answer": "No country or territory matches this input. Use an ISO 3166-1 alpha-2 or alpha-3 code "
                               "or an English name." + (f" Close matches: {', '.join(names)}." if names else ""),
                     "suggestions": names})
        base.update(common)
        return base
    info = {"name": c["name"], "iso2": c["iso2"], "iso3": c["iso3"]}
    base["country"] = info
    if s.risk.get("status") != "verified":
        base.update({"risk": "unverified", "status": "unverified",
                     "answer": "unverified: " + "; ".join(s.risk.get("status_reasons", [])[:3]),
                     "reasons": s.risk.get("status_reasons", [])})
        base.update(common)
        return base
    listed = s.listed.get(c["iso3"])
    art1 = s.risk.get("article_1", {})
    if listed:
        level, annex_name = listed
        base.update({"risk": level, "status": "listed",
                     "answer": f"{c['name']} is classified as {level} risk: listed as '{annex_name}' under "
                               f"'{'Low' if level == 'low' else 'High'} risk countries' in the Annex to {act_name}.",
                     "listed_in_annex_as": annex_name,
                     "basis": {"provision": f"Article 1(1) and Annex of {act_name}", "text": remote(art1.get("1"))}})
    else:
        readings = _readings(c, s)
        parent = s.by_iso.get(c.get("part_of") or "")
        if readings == {"standard"}:
            base.update({"risk": "standard", "status": "not_listed",
                         "answer": f"{c['name']} is not listed in the Annex to {act_name}, so it has the standard level "
                                   "of risk (Article 1(2))." + (f" It is recorded under {parent['name']}, which is not "
                                                                "listed either, so both readings give standard."
                                                                if parent else ""),
                         "basis": {"provision": f"Article 1(2) of {act_name}", "text": remote(art1.get("2"))}})
        else:
            under = (f"the EU authority table records it under {parent['name']} "
                     f"({'/'.join(sorted(readings - {'standard'}))} risk)" if parent
                     else "the EU authority table lists it as a territory without naming the country it belongs to")
            base.update({"risk": None, "status": "not_determined",
                         "answer": f"Depends: {c['name']} is not named in the Annex to {act_name}, and {under}. "
                                   "Article 1(2) gives standard risk to countries not listed. Question for counsel: "
                                   f"does the classification of the country {c['name']} belongs to cover it, or is it "
                                   "a country not listed?",
                         "readings": sorted(readings),
                         "part_of": {"name": parent["name"], "iso3": parent["iso3"]} if parent else None,
                         "basis": {"provision": f"Article 1(2) of {act_name}", "text": remote(art1.get("2"))}})
    base["act"] = {"celex": act["celex"], "name": act_name, "entry_into_force": act.get("entry_into_force"),
                   "amended": bool(act.get("related"))}
    base["legal_basis"] = f"Article 29 of Regulation (EU) 2023/1115; {act_name}"
    base.update(common)
    return base


# ------------------------------------------------------------ sources

def sources() -> dict:
    s = _state()
    d = s.dates
    acts = [{"celex": d["basic_act"]["celex"], "name": "Regulation (EU) 2023/1115", "title": remote(d["basic_act"]["title"]),
             "published": d["basic_act"]["published"], "eli": d["basic_act"]["eli"], "role": "basic act"}]
    for a in d.get("amending_acts", []):
        applied = any(x["celex"] == a["celex"] for x in s.annex.get("amendments_applied", []))
        acts.append({"celex": a["celex"], "name": _act_name(a["celex"]), "title": remote(a["title"]),
                     "published": a["published"], "entry_into_force": a["entry_into_force_text"],
                     "changes": a.get("touches", []),
                     "role": "amending act, applied to Annex I by this tool (not yet in a consolidated version)"
                     if applied else "amending act, included in the consolidated version"})
    r = s.risk["act"]
    acts.append({"celex": r["celex"], "name": _act_name(r["celex"]), "title": remote(r.get("title")),
                 "published": r.get("published"), "entry_into_force": r.get("entry_into_force"), "eli": r.get("eli"),
                 "role": "country classification (Article 29)", "amending_or_repealing_acts": r.get("related", [])})
    result = {
        "answer": (f"Snapshot checked against CELLAR on {s.retrieved}: consolidated text {s.consolidated['celex']}"
                   + "".join(f" plus {_act_name(a['celex'])}" for a in s.annex.get("amendments_applied", []))
                   + f"; country list {_act_name(r['celex'])}."),
        "acts": acts,
        "consolidated_version": s.consolidated | {"disclaimer": remote(s.consolidated.get("disclaimer"))},
        "corrigenda": [{"celex": c["celex"], "date": c["date"], "english": c.get("english")} for c in d.get("corrigenda", [])],
        "proposals": [{"celex": p["celex"], "date": p["date"], "adopted_as": p.get("adopted_as"),
                       "title": remote(p["title"])} for p in d.get("proposals", d.get("pending_proposals", []))],
        "documents": s.manifest.get("documents", []),
        "status": {"annex_i": s.annex.get("status"), "application_dates": d.get("status"),
                   "country_risk": s.risk.get("status")},
        "country_codes": {"table": s.countries.get("authority_table"), "version": s.countries.get("version")},
        "licence": {
            "consolidated_text": "CC BY 4.0 (EUR-Lex legal notice, consolidated texts); Annex I here is derived",
            "official_journal_acts": "EUR-Lex legal notice: 'Unless otherwise specified, you can re-use the legal "
                                     "documents published in EUR-Lex for commercial or non-commercial purposes.'",
            "commission_acts": "also Commission Decision 2011/833/EU, Articles 4 and 6(2) (acknowledge the source, "
                               "do not distort the meaning)",
            "cellar_metadata_and_country_table": "Commission reuse notice, Decision 2011/833/EU "
                                                 "(data.europa.eu dataset records)",
            "legal_notice": "https://eur-lex.europa.eu/content/legal-notice/legal-notice.html (see data/SOURCES.md "
                            "for where and when it was read)",
        },
        "tool": {"name": "eudr-scope-mcp", "version": __version__},
    }
    result.update(_common("sources"))
    return result
