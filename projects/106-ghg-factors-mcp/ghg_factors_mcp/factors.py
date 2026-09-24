"""Queries over the bundled snapshot: search, lookup, conversion, grid intensity.

Every answer names the factor ID, the unit, the year and the source, and
carries the attribution line the source's licence asks for. Nothing is
estimated: a factor that is not in the snapshot is reported as not found, and
a conversion whose unit does not match the factor is refused, with the
factor IDs the source publishes for other units.
"""
from __future__ import annotations

import csv
import json
import os
import re
import unicodedata
from decimal import Decimal
from pathlib import Path

from . import provenance as P
from .refresh import DESNZ_COLUMNS, EMBER_COLUMNS, MANIFEST, plain as _plain

MAX_LIMIT = 50
_DECIMAL = re.compile(r"^-?\d+(?:\.\d+)?$")


class SnapshotError(RuntimeError):
    """The bundled data is missing or unreadable."""


class Refused(ValueError):
    """A request that would need a guess to answer, such as a unit mismatch."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.details = details or {}


# ------------------------------------------------------------- normalising

_DASHES = dict.fromkeys(map(ord, "\u2010\u2011\u2012\u2013\u2014\u2015\u2212"), "-")
_DASHES.update(dict.fromkeys(map(ord, "\u2018\u2019\u02bc\u00b4"), "'"))
# Words that say how to answer, not what to look up; everything else must match a label.
_STOP = set("""a an the of for in into on onto to from by at as with per and or vs versus is are be it its this
that these those what which how much many me my i we our you your please give show tell find get need want
look looking lookup value values number numbers figure figures latest current official applicable relevant
correct use using used about can could would should do does also only just all each every separately
separate broken down breakdown split factor factors conversion convert emission emissions ghg greenhouse
desnz defra beis co2e kgco2e kg_co2e co2 ch4 n2o scope""".split())
_GAS = re.compile(r"^kg CO2e of (\w+) per unit$")


def fold(text: str) -> str:
    """Case-, accent- and dash-insensitive form: 'Türkiye' and 'TURKIYE' fold alike."""
    text = unicodedata.normalize("NFKD", str(text).translate(_DASHES))
    return "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", fold(text))


# Spellings of the same unit. Never a conversion between different units.
_ALIASES = {
    "l": "litres", "litre": "litres", "liter": "litres", "liters": "litres", "litres": "litres",
    "t": "tonnes", "tonne": "tonnes", "tonnes": "tonnes", "metric ton": "tonnes", "metric tons": "tonnes",
    "kg": "kg", "kgs": "kg", "kilogram": "kg", "kilograms": "kg",
    "m3": "cubic metres", "m^3": "cubic metres", "cubic metre": "cubic metres", "cubic meter": "cubic metres",
    "cubic meters": "cubic metres", "cubic metres": "cubic metres",
    "km": "km", "kilometre": "km", "kilometres": "km", "kilometer": "km", "kilometers": "km",
    "mile": "miles", "miles": "miles",
    "tkm": "tonne.km", "tonne km": "tonne.km", "tonne-km": "tonne.km", "tonne.km": "tonne.km",
    "pkm": "passenger.km", "passenger km": "passenger.km", "passenger-km": "passenger.km",
    "passenger.km": "passenger.km",
    "wh": "wh", "kwh": "kwh", "kilowatt hour": "kwh", "kilowatt hours": "kwh", "kilowatt-hour": "kwh",
    "kilowatt-hours": "kwh", "mwh": "mwh", "megawatt hour": "mwh", "megawatt hours": "mwh", "gwh": "gwh",
    "gj": "gj", "gigajoule": "gj", "gigajoules": "gj",
    "room night": "room per night", "room-night": "room per night", "room nights": "room per night",
    "room per night": "room per night",
}
# Exact decimal steps within one kind of unit; anything else is refused.
_SCALE = {"wh": ("energy", Decimal("0.001")), "kwh": ("energy", Decimal(1)), "mwh": ("energy", Decimal(1000)),
          "gwh": ("energy", Decimal(1000000)), "kg": ("mass", Decimal(1)), "tonnes": ("mass", Decimal(1000)),
          "litres": ("volume", Decimal(1)), "cubic metres": ("volume", Decimal(1000)),
          "million litres": ("volume", Decimal(1000000))}


def unit_key(text: str) -> tuple[str, str]:
    """('kwh', 'net cv') for 'kWh (Net CV)': a unit and its qualifier, normalised."""
    t = re.sub(r"\s+", " ", fold(text)).strip()
    m = re.match(r"^(.*?)\s*\(([^)]*)\)$", t)
    base, qual = (m.group(1), m.group(2).strip()) if m else (t, "")
    base = base.strip()
    return _ALIASES.get(base, base), qual


def _number(text: str) -> float | None:
    return float(text) if text not in ("", None) else None


# --------------------------------------------------------------- snapshot

def data_dir() -> Path:
    env = os.environ.get("GHG_FACTORS_DATA")
    if env:
        return Path(env).expanduser()
    here = Path(__file__).resolve().parent
    for candidate in (here / "data", here.parent / "data"):  # installed wheel, then source checkout
        if (candidate / MANIFEST).is_file():
            return candidate
    return here.parent / "data"


class Snapshot:
    def __init__(self, directory: Path):
        self.dir = directory
        try:
            doc = json.loads((directory / MANIFEST).read_text(encoding="utf-8"))
            self.sources: dict = doc["sources"]
            if not isinstance(self.sources, dict):
                raise TypeError
        except (OSError, ValueError, KeyError, TypeError):
            raise SnapshotError(f"no readable snapshot in {directory}: run `ghg-factors-mcp refresh`") from None
        self.years = sorted((int(k.split("-")[1]) for k in self.sources if re.fullmatch(r"desnz-\d{4}", k)),
                            reverse=True)
        self.rows: dict[tuple[int, str], dict] = {}
        self.groups: dict[tuple[int, str], list[dict]] = {}
        self.index: list[tuple] = []
        self.vocabulary: dict[int, set[str]] = {}
        self.activity: dict[tuple, list[tuple[str, str]]] = {}
        try:
            for year in self.years:
                self._load_desnz(year)
            self._load_ember()
            self._load_uba()
        except (KeyError, TypeError, ValueError) as e:
            raise SnapshotError(f"snapshot in {directory} is inconsistent ({type(e).__name__}: {e}): "
                                "run `ghg-factors-mcp refresh`") from None

    def _csv(self, name: str, columns: list[str]) -> list[dict]:
        try:
            with open(self.dir / name, encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                missing = [c for c in columns if c not in (reader.fieldnames or [])]
        except (OSError, UnicodeDecodeError, csv.Error) as e:
            raise SnapshotError(f"snapshot file {name} is unreadable ({type(e).__name__}): run `refresh`") from None
        if missing:
            raise SnapshotError(f"snapshot file {name} lacks the columns {missing}: run `refresh`")
        return rows

    def _load_desnz(self, year: int) -> None:
        for order, row in enumerate(self._csv(self.sources[f"desnz-{year}"]["file"], DESNZ_COLUMNS)):
            # A value the arithmetic cannot read must stop here, not in the middle of an answer.
            if row["value"] and not _DECIMAL.match(row["value"]):
                raise ValueError(f"DESNZ {year} factor {row['id']} has the value {row['value'][:20]!r}")
            prefix = row["id"].rsplit("_", 1)[0]
            self.rows[(year, row["id"])] = row
            group = self.groups.setdefault((year, prefix), [])
            group.append(row)
            if len(group) == 1:
                name = set(words(" ".join([row["level_3"], row["level_4"], row["column_text"]])))
                context = set(words(" ".join([row["scope"], row["level_1"], row["level_2"], row["uom"]])))
                self.index.append((year, prefix, order, name, context, fold(row["level_3"]), row["scope"].casefold()))
                self.vocabulary.setdefault(year, set()).update(name, context)
            key = (year, row["scope"], row["level_1"], row["level_2"], row["level_3"], row["level_4"],
                   row["column_text"], row["ghg_unit"])
            self.activity.setdefault(key, []).append((row["uom"], row["id"]))

    def _load_ember(self) -> None:
        self.ember: dict[str, dict] = {}
        self.area_names: dict[str, str] = {}
        if "ember" not in self.sources:
            return
        for r in self._csv(self.sources["ember"]["file"], EMBER_COLUMNS):
            if r["intensity_gco2e_per_kwh"] and not _DECIMAL.match(r["intensity_gco2e_per_kwh"]):
                raise ValueError(f"Ember {r['area']} {r['year']} has the intensity "
                                 f"{r['intensity_gco2e_per_kwh'][:20]!r}")
            key = r["iso3"] or r["area"].replace(" ", "-")
            area = self.ember.setdefault(key, {"area": r["area"], "iso3": r["iso3"], "area_type": r["area_type"],
                                               "years": {}})
            area["years"][int(r["year"])] = r
            self.area_names[fold(r["area"])] = key
            if r["iso3"]:
                self.area_names[fold(r["iso3"])] = key

    def _load_uba(self) -> None:
        self.uba: dict[int, int] = {}
        if "uba" not in self.sources:
            return
        try:
            doc = json.loads((self.dir / self.sources["uba"]["file"]).read_text(encoding="utf-8"))
            self.uba = {int(v["year"]): int(v["g_co2_per_kwh"]) for v in doc["values"]}
        except (OSError, ValueError, KeyError, TypeError):
            raise SnapshotError("snapshot file for UBA is unreadable: run `refresh`") from None


_cache: dict[str, Snapshot] = {}


def snapshot() -> Snapshot:
    d = data_dir()
    key = str(d.resolve()) if d.exists() else str(d)
    if key not in _cache:
        _cache[key] = Snapshot(d)
    return _cache[key]


# ------------------------------------------------------------- attribution

def attribution(key: str) -> str:
    snap = snapshot()
    m = snap.sources.get(key, {})
    if key.startswith("desnz-"):
        return (f"Source: {P.DESNZ['publisher']}, {P.DESNZ['title']} {m.get('year')}, flat file version "
                f"{m.get('version')}, retrieved {m.get('retrieved')}. {P.DESNZ['attribution_statement']}")
    if key == "ember":
        return (f"Source: Ember, {P.EMBER['title']}, CC BY 4.0 ({P.EMBER['terms_url']}), retrieved "
                f"{m.get('retrieved')}; values unchanged, rows and columns selected.")
    return (f"Quelle/Source: Umweltbundesamt, {P.UBA['title']} ({P.UBA_PAGE}), retrieved {m.get('retrieved')}; "
            "figures reused under § 12a EGovG, unchanged.")


UK_NOTE = ("DESNZ factors are UK-specific. The 2026 publication page says: \"" + P.DESNZ["coverage_quote"]
           + "\". A row that names another country or an international journey is still part of this UK set.")


# ------------------------------------------------------------------- DESNZ

def _gas(row: dict) -> str | None:
    m = _GAS.match(row["ghg_unit"])
    return m.group(1) if m else None


def _output_unit(row: dict) -> str:
    return row["ghg_unit"][:-len(" per unit")] if row["ghg_unit"].endswith(" per unit") else row["ghg_unit"]


def _unit_text(row: dict) -> str:
    uom = row["uom"]
    return f"{_output_unit(row)} {uom}" if uom.lower().startswith("per ") else f"{_output_unit(row)} per {uom}"


def _row_notes(year: int, row: dict) -> list[str]:
    notes = []
    if not row["value"]:
        notes.append("DESNZ publishes this factor blank: no data available. Do not use it as zero.")
    if row["scope"] == "Scope 2" and "electricity" in row["level_1"].lower():
        notes.append(P.LOCATION_BASED)
    if row["level_3"] == "Electricity: UK" and year in P.UK_ELECTRICITY_DATA_YEAR:
        notes.append(f"The DESNZ {year} UK electricity factors are based on {P.UK_ELECTRICITY_DATA_YEAR[year]} data "
                     f"(DESNZ 2026 methodology paper, para 3.8: the 2025 set used 2023 data, the 2026 set 2025 data).")
    if row["scope"].lower() == "outside of scopes":
        notes.append("Listed by DESNZ as 'Outside of Scopes': CO2 reported separately from Scope 1, 2 and 3 totals.")
    if row["ghg_unit"].lower().startswith("kwh"):
        notes.append("This factor converts activity to energy (kWh) for SECR energy reporting; "
                     "it is not an emission factor.")
    return notes


def _view(year: int, row: dict, siblings: bool = True) -> dict:
    levels = [row[k] for k in ("level_1", "level_2", "level_3", "level_4", "column_text") if row[k]]
    out = {"factor_id": f"desnz-{year}:{row['id']}", "source": "DESNZ", "year": year, "region": "UK",
           "scope": row["scope"], "name": " > ".join(levels), "activity_unit": row["uom"],
           "value": _number(row["value"]), "unit": _unit_text(row)}
    gas = _gas(row)
    if gas:
        out["gas"] = gas
    if siblings:
        group = snapshot().groups[(year, row["id"].rsplit("_", 1)[0])]
        gases = {_gas(r): {"factor_id": f"desnz-{year}:{r['id']}", "value": _number(r["value"]), "unit": _unit_text(r)}
                 for r in group if r is not row and _gas(r)}
        if gases:
            out["gases" if not gas else "other_gases"] = gases
        total = next((r for r in group if r is not row and r["ghg_unit"] == "kg CO2e"), None)
        if total is not None:
            out["total"] = {"factor_id": f"desnz-{year}:{total['id']}", "value": _number(total["value"]),
                            "unit": _unit_text(total)}
    return out


def _main_row(group: list[dict]) -> dict:
    return next((r for r in group if r["ghg_unit"] == "kg CO2e"), group[0])


def _scope_filter(scope: str | None) -> str | None:
    if scope in (None, ""):
        return None
    s = fold(str(scope)).strip()
    if s in ("1", "2", "3"):
        return f"scope {s}"
    if re.fullmatch(r"scope\s*[123]", s):
        return "scope " + s[-1]
    if s in ("outside", "outside of scopes", "outside of scope", "outside scopes"):
        return "outside of scopes"
    raise Refused(f"unknown scope {scope!r}: use 1, 2, 3 or 'outside of scopes'")


def search_factors(text: str, scope: str | None = None, year: int | None = None, unit: str | None = None,
                   limit: int = 10) -> dict:
    snap = snapshot()
    if not isinstance(text, str) or not text.strip():
        raise Refused("text is empty: describe the activity, e.g. 'diesel average biofuel blend'")
    tokens = words(text)
    stated_years = [int(t) for t in tokens if re.fullmatch(r"(19|20)\d\d", t)]
    stated_scope = re.search(r"\bscope\s*([123])\b", fold(text))
    if year is None and stated_years:
        year = stated_years[0]
    if scope is None and stated_scope:
        scope = stated_scope.group(1)
    want_scope = _scope_filter(scope)
    tokens = [t for t in tokens if t not in _STOP and not re.fullmatch(r"(19|20)\d\d", t)
              and not (stated_scope and t == stated_scope.group(1))]
    if not tokens:
        raise Refused(f"no searchable words in {text!r}: name the fuel, activity or material")
    try:
        year = int(year) if year is not None else snap.years[0]
    except (TypeError, ValueError):
        raise Refused(f"year must be a number such as {snap.years[0]}") from None
    if year not in snap.years:
        raise Refused(f"DESNZ {year} is not in the snapshot; bundled sets: {', '.join(map(str, snap.years))}")
    # A word no DESNZ label of that year contains cannot match; saying which one it
    # was tells the caller why nothing came back, instead of silently dropping it.
    vocabulary = snap.vocabulary.get(year, set())
    unknown = [t for t in tokens if not any(w.startswith(t) for w in vocabulary)]
    want_unit = unit_key(unit) if unit else None
    try:
        limit = max(1, min(int(limit), MAX_LIMIT))
    except (TypeError, ValueError):
        raise Refused(f"limit must be a whole number from 1 to {MAX_LIMIT}") from None
    phrase = fold(" ".join(tokens))
    hits = []
    for y, prefix, order, name_words, context_words, level3, row_scope in snap.index:
        if unknown or y != year or (want_scope and row_scope != want_scope):
            continue
        all_words = name_words | context_words
        if not all(any(w.startswith(t) for w in all_words) for t in tokens):
            continue
        group = snap.groups[(y, prefix)]
        if want_unit:
            u = unit_key(group[0]["uom"])
            same = u[0] == want_unit[0] or (u[0] in _SCALE and want_unit[0] in _SCALE
                                            and _SCALE[u[0]][0] == _SCALE[want_unit[0]][0])
            if not same or (want_unit[1] and u[1] != want_unit[1]):
                continue
        in_name = sum(1 for t in tokens if any(w.startswith(t) for w in name_words))
        extra = sum(1 for w in name_words if not any(w.startswith(t) for t in tokens))
        hits.append((-in_name, 0 if fold(" ".join(words(level3))) == phrase else 1, extra, order, prefix))
    hits.sort()
    results = []
    for *_, prefix in hits[:limit]:
        group = snap.groups[(year, prefix)]
        view = _view(year, _main_row(group))
        notes = _row_notes(year, _main_row(group))
        if notes:
            view["notes"] = notes
        results.append(view)
    note = UK_NOTE + (" Rows published blank by DESNZ are included with value null." if results else "")
    if want_unit and any(unit_key(r["activity_unit"])[0] != want_unit[0] for r in results):
        note += (" The unit filter also matches factors published in another unit of the same kind "
                 "(e.g. kWh for MWh); convert scales between them exactly.")
    query = {"text": text, "scope": want_scope, "year": year, "unit": unit, "limit": limit, "words": tokens}
    if unknown:
        query["unknown_words"] = unknown
        hint = (" For a country's grid average use grid_intensity; the DESNZ UK grid factor is found with "
                "'electricity UK'." if {"grid", "intensity", "mix"} & set(unknown) else "")
        note = f"No DESNZ {year} label contains {', '.join(repr(u) for u in unknown)}.{hint} " + note
    return {"query": query, "matches": len(hits), "returned": len(results), "results": results, "note": note,
            "attribution": [attribution(f"desnz-{year}")]}


# ------------------------------------------------------------ factor IDs

_DESNZ_ID = re.compile(r"^desnz[-_ ]?(\d{4})[:/ ]\s*(\S+)$", re.I)
_GRID_ID = re.compile(r"^(ember|uba):([^:]+):(\d{4})$", re.I)


def _find(factor_id: str) -> tuple[str, dict]:
    """('desnz', {...}) or ('grid', {...}) for an ID; raises Refused when unknown."""
    snap = snapshot()
    fid = str(factor_id or "").strip()
    m = _GRID_ID.match(fid)
    if m:
        return "grid", {"source": m.group(1).lower(), "country": m.group(2), "year": int(m.group(3))}
    if re.match(r"^(ember|uba):", fid, re.I):
        raise Refused(f"grid IDs look like ember:DEU:2025 or uba:DEU:2025, got {fid!r}", {"factor_id": fid})
    m = _DESNZ_ID.match(fid)
    note = None
    if m:
        year, raw = int(m.group(1)), m.group(2)
    else:
        year, raw = (snap.years[0] if snap.years else 0), fid
        note = f"No set named in the ID: read as DESNZ {year}, the newest set in the snapshot."
    if year not in snap.years:
        raise Refused(f"DESNZ {year} is not in the snapshot; bundled sets: {', '.join(map(str, snap.years))}",
                      {"factor_id": fid})
    row = snap.rows.get((year, raw))
    if row is None:
        raise Refused(f"no DESNZ {year} factor with ID {raw!r}. Use search_factors to find one; IDs look like "
                      f"desnz-{year}:1_101_1011_8_1.", {"factor_id": fid})
    return "desnz", {"year": year, "row": row, "note": note}


def get_factor(factor_id: str) -> dict:
    try:
        kind, hit = _find(factor_id)
    except Refused as e:
        return {"found": False, "factor_id": str(factor_id), "reason": str(e)}
    if kind == "grid":
        return grid_intensity(hit["country"], hit["year"], hit["source"])
    snap, year, row = snapshot(), hit["year"], hit["row"]
    out = {"found": True, **_view(year, row)}
    if row["level_4"] or row["column_text"]:
        out["levels"] = {k: row[k] for k in ("level_1", "level_2", "level_3", "level_4", "column_text") if row[k]}
    notes = ([hit["note"]] if hit["note"] else []) + _row_notes(year, row) + [UK_NOTE]
    other = []
    for y in snap.years:
        r = snap.rows.get((y, row["id"])) if y != year else None
        if r is not None:
            item = {"factor_id": f"desnz-{y}:{r['id']}", "value": _number(r["value"]), "unit": _unit_text(r)}
            if r["value"] and row["value"] and Decimal(r["value"]) != 0:
                change = (Decimal(row["value"]) - Decimal(r["value"])) / Decimal(r["value"]) * 100
                item["change_to_this_year_pct"] = float(round(change, 2))
            if (r["level_2"], r["level_3"], r["column_text"]) != (row["level_2"], row["level_3"], row["column_text"]):
                levels = ("level_1", "level_2", "level_3", "level_4", "column_text")
                item["published_name"] = " > ".join(r[k] for k in levels if r[k])
            other.append(item)
    if other:
        out["same_id_other_years"] = other
        notes.append("same_id_other_years: DESNZ reuses factor IDs across years; change_to_this_year_pct is "
                     "derived by ghg-factors-mcp, not published by DESNZ.")
    out["notes"] = notes
    out["attribution"] = [attribution(f"desnz-{y}") for y in [year] + [int(o["factor_id"][6:10]) for o in other]]
    return out


# ------------------------------------------------------------------ convert

def _amount(amount) -> Decimal:
    if isinstance(amount, bool):
        raise Refused("amount must be a number, not true/false")
    if isinstance(amount, int):
        d = Decimal(amount)
    elif isinstance(amount, float):
        d = Decimal(repr(amount))
    elif isinstance(amount, str) and re.fullmatch(r"\s*-?\d+(\.\d+)?([eE][-+]?\d+)?\s*", amount):
        d = Decimal(amount.strip())
    else:
        raise Refused(f"amount must be a plain number such as 1250.5, got {str(amount)[:40]!r} "
                      "(no thousands separators or units)")
    if not d.is_finite():
        raise Refused("amount must be a finite number")
    return d


def _scale(given: str, expected: str) -> Decimal | None:
    g, e = unit_key(given), unit_key(expected)
    if g == e:
        return Decimal(1)
    if g[1] == e[1] and g[0] in _SCALE and e[0] in _SCALE and _SCALE[g[0]][0] == _SCALE[e[0]][0]:
        return _SCALE[g[0]][1] / _SCALE[e[0]][1]
    return None


def _alternatives(year: int, row: dict) -> list[dict]:
    key = (year, row["scope"], row["level_1"], row["level_2"], row["level_3"], row["level_4"], row["column_text"],
           row["ghg_unit"])
    snap = snapshot()
    return [{"factor_id": f"desnz-{year}:{fid}", "activity_unit": uom,
             "value": _number(snap.rows[(year, fid)]["value"])}
            for uom, fid in snap.activity.get(key, []) if fid != row["id"]]


def convert(amount, unit: str, factor_id: str) -> dict:
    qty = _amount(amount)
    if not isinstance(unit, str) or not unit.strip():
        raise Refused("unit is empty: give the unit of the amount, e.g. 'litres' or 'kWh'")
    kind, hit = _find(factor_id)
    if kind == "grid":
        return _convert_grid(qty, unit, hit)
    year, row = hit["year"], hit["row"]
    fid = f"desnz-{year}:{row['id']}"
    if not row["value"]:
        raise Refused(f"{fid} is published blank by DESNZ (no data available); there is nothing to multiply.",
                      {"factor_id": fid, "alternatives": _alternatives(year, row),
                       "attribution": [attribution(f"desnz-{year}")]})
    scale = _scale(unit, row["uom"])
    if scale is None:
        alts = _alternatives(year, row)
        listed = "; ".join(f"{a['activity_unit']}: {a['factor_id']}" for a in alts)
        basis = ""
        if unit_key(unit)[0] == unit_key(row["uom"])[0]:
            basis = f" If the amount is on the factor's basis, pass unit={row['uom']!r}."
        elsewhere = (f"DESNZ {year} publishes the same activity per {listed}." if alts
                     else "DESNZ publishes this activity in no other unit.")
        raise Refused(f"unit mismatch: {fid} is a factor per {row['uom']!r} and the amount is in {unit!r}. "
                      f"Not converted.{basis} {elsewhere}",
                      {"factor_id": fid, "factor_unit": row["uom"], "given_unit": unit, "alternatives": alts,
                       "attribution": [attribution(f"desnz-{year}")]})
    value = Decimal(row["value"])
    steps, base = [], qty
    if scale != 1:
        base = qty * scale
        steps.append(f"{_plain(qty)} {unit} = {_plain(base)} {row['uom']}")
    out_unit = _output_unit(row)
    result = base * value
    steps.append(f"{_plain(base)} {row['uom']} × {_plain(value)} {_unit_text(row)} = {_plain(result)} {out_unit}")
    out = {"factor_id": fid, "amount": float(qty), "unit": unit,
           "result": {"value": float(result), "value_text": _plain(result), "unit": out_unit},
           "arithmetic": "; ".join(steps), "factor": _view(year, row, siblings=False)}
    group = snapshot().groups[(year, row["id"].rsplit("_", 1)[0])]
    if row["ghg_unit"] == "kg CO2e":
        gases = {}
        for r in group:
            if _gas(r) and r["value"]:
                part = base * Decimal(r["value"])
                gases[_gas(r)] = {"factor_id": f"desnz-{year}:{r['id']}", "value": float(part),
                                  "arithmetic": f"{_plain(base)} × {_plain(Decimal(r['value']))} = {_plain(part)} "
                                                f"{_output_unit(r)}"}
        if gases:
            out["gases"] = gases
            total = sum(Decimal(r["value"]) for r in group if _gas(r) and r["value"]) * base
            if total != result:
                out["gases_note"] = (f"The gas parts add up to {_plain(total)}, the total factor gives "
                                     f"{_plain(result)}: DESNZ rounds each published figure separately.")
    out["derived"] = ("Computed by ghg-factors-mcp: amount × published factor. DESNZ publishes the factor, "
                      "not this result.")
    out["notes"] = _row_notes(year, row) + [UK_NOTE]
    out["attribution"] = [attribution(f"desnz-{year}")]
    return out


def _convert_grid(qty: Decimal, unit: str, hit: dict) -> dict:
    g = grid_intensity(hit["country"], hit["year"], hit["source"])
    if not g.get("found"):
        raise Refused(g.get("reason", "grid intensity not found"), {"grid": g})
    scale = _scale(unit, "kWh")
    if scale is None:
        raise Refused(f"unit mismatch: {g['factor_id']} is per kWh of electricity and the amount is in {unit!r}. "
                      "Not converted. Give the amount in Wh, kWh, MWh or GWh.",
                      {"factor_id": g["factor_id"], "factor_unit": "kWh", "given_unit": unit})
    value = Decimal(g["value_text"])
    gas = "CO2e" if g["source_id"] == "ember" else "CO2"
    steps, kwh = [], qty
    if scale != 1:
        kwh = qty * scale
        steps.append(f"{_plain(qty)} {unit} = {_plain(kwh)} kWh")
    grams = kwh * value
    kg = grams / 1000
    steps.append(f"{_plain(kwh)} kWh × {_plain(value)} {g['unit']} = {_plain(grams)} g {gas} = {_plain(kg)} kg {gas}")
    return {"factor_id": g["factor_id"], "amount": float(qty), "unit": unit,
            "result": {"value": float(kg), "value_text": _plain(kg), "unit": f"kg {gas}"},
            "arithmetic": "; ".join(steps),
            "factor": {k: g[k] for k in ("factor_id", "source", "area", "year", "value", "unit", "basis")},
            "derived": (f"Computed by ghg-factors-mcp: amount × published intensity, converted from g to kg. "
                        f"{g['source']} publishes the intensity, not this result (a change to the data)."),
            "notes": [g["scope2"]], "attribution": g["attribution"]}


# --------------------------------------------------------- grid intensity

_AREA_ALIASES = {  # this tool's own convenience mapping to Ember's area names
    "uk": "GBR", "great britain": "GBR", "britain": "GBR", "us": "USA", "usa": "USA",
    "united states of america": "USA", "turkey": "TUR", "czech republic": "CZE", "vietnam": "VNM",
    "philippines": "PHL", "laos": "LAO", "republic of korea": "KOR", "ivory coast": "CIV",
    "bosnia and herzegovina": "BIH", "democratic republic of the congo": "COD", "dr congo": "COD",
    "tanzania": "TZA", "taiwan": "TWN", "hong kong": "HKG", "macao": "MAC", "macau": "MAC", "brunei": "BRN",
    "cape verde": "CPV", "palestine": "PSE", "russian federation": "RUS", "european union": "EU",
}


def _area(country: str) -> tuple[str | None, list[str]]:
    snap = snapshot()
    q = re.sub(r"\s+", " ", fold(str(country or "")).replace("-", " ")).strip()
    key = snap.area_names.get(q) or snap.area_names.get(q.replace(" ", "-"))
    if key is None and q in _AREA_ALIASES and fold(_AREA_ALIASES[q]) in snap.area_names:
        key = snap.area_names[fold(_AREA_ALIASES[q])]
    qw = set(words(q))
    # After a match, only names that contain every word of the query are
    # worth mentioning ("Congo" -> "Congo (DRC)"); without one, prefixes help too.
    near = sorted({snap.ember[k]["area"] for n, k in snap.area_names.items()
                   if k != key and q and ((qw and qw <= set(words(n))) or (key is None and n.startswith(q)))})
    return key, near[:8]


def _ember_answer(key: str, year: int | None) -> dict:
    snap = snapshot()
    area = snap.ember[key]
    have = sorted(y for y, r in area["years"].items() if r["intensity_gco2e_per_kwh"])
    base = {"source": "Ember", "source_id": "ember", "area": area["area"], "iso3": area["iso3"] or None,
            "area_type": area["area_type"], "available_years": f"{have[0]}-{have[-1]}" if have else None}
    notes = []
    if year is None:
        if not have:
            return {"found": False, **base, "reason": f"Ember lists {area['area']} with no emissions intensity."}
        year = have[-1]
        notes.append(f"No year given: {year} is the latest year with a value.")
    r = area["years"].get(year)
    if r is None or not r["intensity_gco2e_per_kwh"]:
        before = [y for y in have if y < year]
        after = [y for y in have if y > year]
        nearest = [{"year": y, "factor_id": f"ember:{key}:{y}",
                    "value": float(area["years"][y]["intensity_gco2e_per_kwh"])}
                   for y in ([before[-1]] if before else []) + ([after[0]] if after else [])]
        reason = (f"Ember lists {area['area']} for {year} without an emissions intensity"
                  + (f" (generation {r['generation_twh']} TWh)." if r and r["generation_twh"] else ".")
                  if r is not None else f"Ember has no {year} row for {area['area']}.")
        return {"found": False, **base, "year": year, "reason": reason + " No other year is substituted.",
                "nearest_years_with_value": nearest, "scope2": P.LOCATION_BASED, "attribution": [attribution("ember")]}
    return {"found": True, "factor_id": f"ember:{key}:{year}", **base, "year": year,
            "value": float(r["intensity_gco2e_per_kwh"]), "value_text": r["intensity_gco2e_per_kwh"],
            "unit": "g CO2e/kWh", "kg_per_kwh": float(Decimal(r["intensity_gco2e_per_kwh"]) / 1000),
            "emissions_mtco2e": _number(r["emissions_mtco2e"]), "generation_twh": _number(r["generation_twh"]),
            "basis": ("Lifecycle emissions per kWh generated in the area: Ember's figures \"aim to include full "
                      "lifecycle emissions including upstream methane, supply chain and manufacturing emissions\" "
                      "(Ember methodology). Emissions from generation divided by generation (Ember's 'Total "
                      "generation' row); net imports are listed separately by Ember and not included."),
            "scope2": (P.LOCATION_BASED + " Ember's figure is lifecycle; the GHG Protocol counts only generation "
                       "emissions in Scope 2 and upstream emissions in Scope 3 category 3 (Scope 2 Guidance, p. 34), "
                       "so check which basis your reporting framework asks for."),
            "notes": notes + ["kg_per_kwh is derived by ghg-factors-mcp (g divided by 1000)."],
            "attribution": [attribution("ember")]}


def _uba_answer(year: int | None) -> dict:
    snap = snapshot()
    have = sorted(snap.uba)
    base = {"source": "Umweltbundesamt", "source_id": "uba", "area": "Germany", "iso3": "DEU",
            "available_years": f"{have[0]}-{have[-1]}" if have else None}
    notes = []
    if year is None and have:
        year = have[-1]
        notes.append(f"No year given: {year} is the latest year with a value.")
    if year not in snap.uba:
        return {"found": False, **base, "year": year,
                "reason": (f"The bundled UBA figures cover {base['available_years']} only. "
                           "No other year is substituted."),
                "nearest_years_with_value": [{"year": y, "factor_id": f"uba:DEU:{y}", "value": snap.uba[y]}
                                             for y in have[-1:]],
                "scope2": P.LOCATION_BASED, "attribution": [attribution("uba")]}
    v = snap.uba[year]
    return {"found": True, "factor_id": f"uba:DEU:{year}", **base, "year": year, "value": float(v),
            "value_text": str(v), "unit": "g CO2/kWh", "kg_per_kwh": v / 1000,
            "basis": ("Direct CO2 emissions of electricity generation per kWh of electricity consumed in Germany, "
                      "as stated by the Umweltbundesamt: CO2 only (no CH4, N2O or upstream emissions); emissions "
                      "behind Germany's net electricity imports are not counted."),
            "scope2": P.LOCATION_BASED,
            "notes": notes + ["kg_per_kwh is derived by ghg-factors-mcp (g divided by 1000)."],
            "attribution": [attribution("uba")]}


def grid_intensity(country: str, year: int | None = None, source: str = "ember") -> dict:
    snap = snapshot()
    src = fold(str(source or "ember")).strip()
    if src not in ("ember", "uba", "all"):
        raise Refused(f"unknown source {source!r}: use 'ember', 'uba' or 'all'")
    if year is not None:
        try:
            year = int(year)
        except (TypeError, ValueError):
            raise Refused(f"year must be a number such as 2025, got {year!r}") from None
    key, near = _area(country)
    if key is None:
        return {"found": False, "country": country,
                "reason": f"no country or region named {country!r} in the bundled data. Use a name or ISO 3166-1 "
                          "alpha-3 code as Ember lists it (e.g. Poland or POL).", "did_you_mean": near}
    answers = []
    if src in ("ember", "all"):
        answers.append(_ember_answer(key, year))
    if src in ("uba", "all"):
        if key == "DEU":
            answers.append(_uba_answer(year))
        elif src == "uba":
            return {"found": False, "country": country, "source": "Umweltbundesamt",
                    "reason": "UBA figures cover Germany only. Use source='ember' for other countries."}
    if key == "GBR" and snap.years:
        y = snap.years[0]
        uk = next((r for (yy, _), r in snap.rows.items() if yy == y and r["scope"] == "Scope 2"
                   and r["level_1"] == "UK electricity" and r["level_3"] == "Electricity: UK"
                   and r["ghg_unit"] == "kg CO2e"), None)
        if uk:
            for a in answers:
                a["see_also"] = {"factor_id": f"desnz-{y}:{uk['id']}", "value": _number(uk["value"]),
                                 "unit": _unit_text(uk), "note": "The DESNZ UK electricity factor, for UK reporting "
                                 "under the DESNZ set; see get_factor for its basis."}
    if near:
        for a in answers:
            a["other_areas_matching"] = near
    if len(answers) == 1:
        return answers[0]
    return {"found": any(a.get("found") for a in answers), "answers": answers,
            "note": "The sources measure different things (see basis); they are not interchangeable."}


# ------------------------------------------------------------------ sources

def sources() -> dict:
    snap = snapshot()
    items = []
    desnz = sorted((k for k in snap.sources if k.startswith("desnz-")), reverse=True)
    order = desnz + sorted(k for k in snap.sources if k not in desnz)
    for key in order:
        m = snap.sources[key]
        if key.startswith("desnz-"):
            meta = {"name": f"{P.DESNZ['title']} {m.get('year')}", "publisher": P.DESNZ["publisher"],
                    "licence": P.DESNZ["licence"], "licence_url": P.DESNZ["licence_url"],
                    "terms_quote": P.DESNZ["terms_quote"], "version": m.get("version"), "region": "UK",
                    "coverage": P.DESNZ["coverage_quote"], "use": P.DESNZ["use_quote"], "page": m.get("page"),
                    "methodology_2026": P.DESNZ_METHODOLOGY_2026}
        elif key == "ember":
            meta = {"name": f"Ember {P.EMBER['title']}", "publisher": "Ember", "licence": P.EMBER["licence"],
                    "licence_url": P.EMBER["licence_url"], "terms_url": P.EMBER["terms_url"],
                    "terms_quote": P.EMBER["terms_quote"], "page": P.EMBER["page"], "basis": P.EMBER["basis_quote"],
                    "last_modified": m.get("last_modified")}
        else:
            meta = {"name": P.UBA["title"], "publisher": P.UBA["publisher"], "licence": P.UBA["licence"],
                    "terms_url": P.UBA["terms_url"], "terms_quote": P.UBA["terms_quote"], "page": P.UBA_PAGE}
        items.append({"id": key, **meta, "retrieved": m.get("retrieved"), "raw_url": m.get("raw_url"),
                      "raw_sha256": m.get("raw_sha256"), "rows": m.get("rows"), "attribution": attribution(key)})
    return {"data_dir": str(snap.dir), "sources": items, "excluded": P.EXCLUDED,
            "scope2": {"location_based": P.LOCATION_BASED, "guidance": P.SCOPE2_GUIDANCE,
                       "quote_p8": P.LOCATION_BASED_QUOTE, "quote_p34": P.SCOPE2_BOUNDARY_QUOTE,
                       "checked": P.CHECKED}}
