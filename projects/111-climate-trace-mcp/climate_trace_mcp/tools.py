"""The six tools. Each returns one dict: the MCP structuredContent and the CLI's --json output.

Every number leaves here with its unit, gas, GWP horizon, year, the label
"modelled", the dataset it comes from and the attribution line. Inputs are
validated before anything is sent: a country becomes a code from the bundled
table, sectors and subsectors must be names the API itself lists, and a name
search is done locally because the API has none (it ignores a `name`
parameter, checked 2026-09-24).
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone

from . import countries
from . import provenance as prov
from .client import ApiError, BadPayload, Client
from .safety import clean, fold

# Year limits from the OpenAPI document 7.2.0 (checked 2026-09-24):
# /v7/sources "Annual data is available for 2021 through the current year";
# /v7/sources/:id "minimum: 2021-01-01"; /v7/sources/emissions for a country
# "data is available beginning 2015 through the current year".
MIN_YEAR_ASSETS = 2021
MIN_YEAR_COUNTRY = 2015
PAGE = 100  # the API's own default page size
NAME_SCAN_PAGES = 5  # tool's choice: a name search reads at most 500 ranked assets
MAX_COUNTRY_YEARS = 12  # tool's choice: one request per year, made one after another
ALL_NO_FOREST = "all_no_forest"  # the API's value for "all sectors except forestry-and-land-use"
_SLUG = prov.SLUG
_A3 = re.compile(r"^[A-Z]{3}$")
_LEI = re.compile(r"^[A-Z0-9]{18}[0-9]{2}$")


class ToolError(Exception):
    def __init__(self, message: str, kind: str = "invalid_argument"):
        super().__init__(message)
        self.message = message
        self.kind = kind

    def as_dict(self) -> dict:
        return {"kind": self.kind, "message": self.message}


def _utc_today() -> date:
    return datetime.now(timezone.utc).date()


# ------------------------------------------------------------------ arguments

def _int(value, name: str, lo: int, hi: int) -> int:
    if isinstance(value, bool):
        raise ToolError("%s must be an integer" % name)
    if isinstance(value, int):
        n = value
    elif isinstance(value, float) and value.is_integer():
        n = int(value)
    elif isinstance(value, str) and re.fullmatch(r"\s*\d{1,13}\s*", value):
        n = int(value)
    else:
        raise ToolError("%s must be an integer, got %s" % (name, clean(repr(value), 40)))
    if not lo <= n <= hi:
        raise ToolError("%s must be between %d and %d, got %d" % (name, lo, hi, n))
    return n


def _years(value, lo: int, hi: int, max_n: int, default: list) -> list:
    if value is None:
        return default
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        items = [_int(value, "years", lo, hi)]
    elif isinstance(value, (list, tuple)):
        items = [_int(v, "years", lo, hi) for v in value]
    elif isinstance(value, str):
        s = value.strip()
        m = re.fullmatch(r"(\d{4})\s*(?:-|–|to|\.\.)\s*(\d{4})", s)
        if m:
            a, b = _int(m.group(1), "years", lo, hi), _int(m.group(2), "years", lo, hi)
            if a > b:
                raise ToolError("years range %d-%d runs backwards" % (a, b))
            items = list(range(a, b + 1))
        elif re.fullmatch(r"\d{4}(?:\s*,\s*\d{4})*", s):
            items = [_int(x, "years", lo, hi) for x in re.split(r"\s*,\s*", s)]
        else:
            raise ToolError("years must be one year (2024), a range (2020-2024) or a list (2020,2022)")
    else:
        raise ToolError("years must be one year (2024), a range (2020-2024) or a list (2020,2022)")
    items = sorted(set(items))
    if not items:
        raise ToolError("years is empty")
    if len(items) > max_n:
        raise ToolError("at most %d years per call; asked for %d" % (max_n, len(items)))
    return items


def _gas(value) -> str:
    if not isinstance(value, str) or value.strip().lower() not in prov.GASES:
        raise ToolError("gas must be one of: " + ", ".join(prov.GASES))
    return value.strip().lower()


def _slug(value, name: str) -> str:
    if not isinstance(value, str):
        raise ToolError("%s must be a string" % name)
    s = value.strip().lower().replace("_", "-").replace(" ", "-")
    if not _SLUG.match(s) or len(s) > 80:
        raise ToolError("%s %r is not a valid name; see the sectors tool" % (name, clean(value, 60)))
    return s


def _lei_ok(value) -> bool:
    """ISO 17442: 20 characters, the last two check digits (ISO 7064 MOD 97-10).

    GLEIF's own LEI shown on gleif.org, 506700GE1G29325QX363, passes (checked 2026-09-24).
    """
    if not isinstance(value, str) or not _LEI.match(value):
        return False
    return int("".join(str(int(c, 36)) for c in value)) % 97 == 1


def _name_words(name) -> list:
    if not isinstance(name, str):
        raise ToolError("name must be a string")
    words = re.findall(r"[0-9a-z]+", fold(clean(name, 100)))
    if not words:
        raise ToolError("name needs at least one letter or digit")
    return words


_DE = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue"})


def _name_matches(asset_name, words: list) -> bool:
    if not isinstance(asset_name, str):
        return False
    # Both "Huttenwerke" and "Huettenwerke" should find "Hüttenwerke".
    for variant in (asset_name, asset_name.translate(_DE)):
        hay = " ".join(re.findall(r"[0-9a-z]+", fold(variant)))
        if all(w in hay for w in words):
            return True
    return False


# ---------------------------------------------------------------- the service

class Service:
    def __init__(self, client: Client | None = None, snapshot: prov.Snapshot | None = None, today=None):
        self.client = client or Client()
        self.snapshot = snapshot or prov.Snapshot.load()
        self._today = today or _utc_today

    # ------------------------------------------------------------- helpers
    def _live_names(self, path: str):
        try:
            data, _ = self.client.get(path)
        except ApiError:
            return None
        return {v for v in data if isinstance(v, str)} if isinstance(data, list) else None

    def _sector(self, value, allow_all_no_forest: bool = True) -> str:
        if isinstance(value, str) and value.strip().lower() == ALL_NO_FOREST and allow_all_no_forest:
            return ALL_NO_FOREST
        s = _slug(value, "sector")
        if s in self.snapshot.sectors:
            return s
        live = self._live_names("/definitions/sectors")
        if live and s in live:
            return s
        known = sorted(set(self.snapshot.sectors) | (live or set()))
        raise ToolError("unknown sector %r; valid sectors: %s%s" % (
            s, ", ".join(known) or "(list unavailable)", ", all_no_forest" if allow_all_no_forest else ""))

    def _subsector(self, value) -> str:
        s = _slug(value, "subsector")
        if s in self.snapshot.subsectors:
            return s
        live = self._live_names("/definitions/subsectors")
        if live and s in live:
            return s
        raise ToolError("unknown subsector %r; the sectors tool lists the valid ones" % s)

    def _common(self, retrieved: set, gas: str) -> dict:
        g = prov.GASES[gas]
        day = min(retrieved) if retrieved else self._today().isoformat()
        return {"gas": gas, "unit": g["unit"], "gwp_horizon": g["gwp_horizon"], "estimate_type": "modelled",
                "caveat": prov.CAVEAT, "attribution": prov.attribution(day)}

    @staticmethod
    def _figure(value, gas: str, year, dataset: dict) -> dict:
        g = prov.GASES[gas]
        out = {"value": value, "unit": g["unit"], "gas": gas, "gwp_horizon": g["gwp_horizon"], "year": year,
               "estimate_type": "modelled", "source_dataset": dataset["label"]}
        if dataset.get("non_commercial_terms_may_apply"):
            out["non_commercial_terms_may_apply"] = True
        if value is None:
            out["note"] = "no value: the API returned null, which it uses for data not yet available"
        return out

    @staticmethod
    def _number(rec: dict, key: str, missing: list, required: bool = False):
        if key not in rec:
            if required:
                missing.append(key)
            return None
        v = rec[key]
        if v is None:
            return None
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            missing.append(key + " (not a number)")
            return None
        return v

    def _measure(self, rec: dict, key: str, unit_key: str, missing: list):
        v = self._number(rec, key, missing)
        if v is None:
            return None
        unit = clean(rec.get(unit_key), 80)
        return {"value": v, "unit": unit or None}

    @staticmethod
    def _records(data, endpoint: str) -> list:
        if data is None:  # this API answers "no rows" with a bare null
            return []
        if not isinstance(data, list):
            raise BadPayload("expected a list from the API, got %s" % type(data).__name__, endpoint)
        return [r for r in data if isinstance(r, dict)]

    def _asset_row(self, rec: dict, gas: str, datasets: dict) -> dict:
        missing = []
        aid = rec.get("id")
        if not isinstance(aid, int) or isinstance(aid, bool):
            missing.append("id")
            aid = None
        for key in ("name", "subsector", "year", "emissionsQuantity"):
            if key not in rec:
                missing.append(key)
        sub = rec.get("subsector") if isinstance(rec.get("subsector"), str) and _SLUG.match(rec.get("subsector")) else None
        key = sub or "(unknown subsector)"
        if key not in datasets:
            datasets[key] = prov.describe(self.snapshot, sub, gas, "source")
        year = rec.get("year") if isinstance(rec.get("year"), int) else None
        value = self._number(rec, "emissionsQuantity", missing)
        country = rec.get("country") if isinstance(rec.get("country"), str) and _A3.match(rec.get("country")) else None
        row = {
            "asset_id": aid,
            "name": clean(rec.get("name"), 200) or None,
            "country": country,
            "sector": rec.get("sector") if isinstance(rec.get("sector"), str) and _SLUG.match(rec.get("sector")) else None,
            "subsector": sub,
            "asset_type": clean(rec.get("assetType"), 80) or None,
            "source_type": clean(rec.get("sourceType"), 40) or None,
            "emissions": self._figure(value, gas, year, datasets[key]),
            "emissions_factor": self._measure(rec, "emissionsFactor", "emissionsFactorUnits", missing),
            "activity": self._measure(rec, "activity", "activityUnits", missing),
            "capacity": self._measure(rec, "capacity", "capacityUnits", missing),
            "capacity_factor": self._number(rec, "capacityFactor", missing),
            "location": self._location(rec.get("centroid")),
        }
        if rec.get("gas") is not None and rec.get("gas") != gas:
            missing.append("gas (the API answered %s, not %s)" % (clean(rec.get("gas"), 20), gas))
        if missing:
            row["missing_fields"] = missing
        return row

    @staticmethod
    def _location(centroid):
        if not isinstance(centroid, dict):
            return None
        lat, lon = centroid.get("latitude"), centroid.get("longitude")
        if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (lat, lon)) \
                and -90 <= lat <= 90 and -180 <= lon <= 180:
            return {"latitude": lat, "longitude": lon}
        return None

    def _partial_note(self, year: int):
        if year >= self._today().year:
            return ("%d is the current calendar year: Climate TRACE releases monthly data with a delay, so %d "
                    "figures cover only the months released so far." % (year, year))
        return None

    @staticmethod
    def _terms(out: dict, described) -> None:
        """Licence fields shared by every numeric answer."""
        described = list(described)
        terms = prov.dataset_terms(described)
        if terms:
            out["licence"] = ("CC BY 4.0 (Climate TRACE, %s), except the parts taken from the external datasets in "
                              "external_dataset_terms, which keep their own terms" % prov.TERMS_URL)
            out["external_dataset_terms"] = terms
        else:
            out["licence"] = "CC BY 4.0 (Climate TRACE, %s)" % prov.TERMS_URL
        note = prov.licence_note(described)
        if note:
            out["licence_note"] = note

    def _owners_from(self, data: dict):
        raw = data.get("owners")
        entries = raw if isinstance(raw, list) else []
        seen, owners = set(), []
        for o in entries:
            if not isinstance(o, dict):
                continue
            oid = clean(o.get("id"), 64) or None
            name = clean(o.get("name"), 200) or None
            if (oid, name) in seen:
                continue
            seen.add((oid, name))
            lei, field = None, None
            for k, v in o.items():
                if isinstance(k, str) and k.lower() in ("lei", "leicode", "lei_code") and _lei_ok(v):
                    lei, field = v, k
                    break
            if lei is None and _lei_ok(o.get("id")):
                lei, field = o.get("id"), "id"
            owners.append({"name": name, "climate_trace_owner_id": oid, "lei": lei,
                           "lei_source": ("Climate TRACE API field %r" % field) if lei else None})
        return owners, len(entries), ("owners" in data)

    # ---------------------------------------------------------------- tools
    def search_assets(self, name=None, country=None, sector=None, subsector=None, year=None, limit=20) -> dict:
        today = self._today()
        y = _int(year, "year", MIN_YEAR_ASSETS, today.year) if year is not None else today.year - 1
        lim = _int(limit, "limit", 1, PAGE)
        gas = "co2e_100yr"
        params = {"year": y, "gas": gas}
        query = {"year": y, "limit": lim}
        if country is not None:
            a3, cname = countries.resolve(country)
            params["gadmId"] = a3
            query.update(country=a3, country_name=cname)
        sec = self._sector(sector) if sector is not None else None
        sub = self._subsector(subsector) if subsector is not None else None
        if sec and sub and sec != ALL_NO_FOREST:
            owner = self.snapshot.sector_of(sub)
            if owner and owner != sec:
                raise ToolError("subsector %s belongs to sector %s, not %s" % (sub, owner, sec))
        if sec:
            params["sectors"] = sec
            query["sector"] = sec
        if sub:
            params["subsectors"] = sub
            query["subsector"] = sub
        words = _name_words(name) if name is not None else None
        if words:
            query["name"] = clean(name, 100)

        retrieved, found, scanned, complete = set(), [], 0, False
        pages = NAME_SCAN_PAGES if words else 1
        for page in range(pages):
            p = dict(params, limit=PAGE if words else lim, offset=page * PAGE if words else None)
            data, day = self.client.get("/sources", p)
            retrieved.add(day)
            recs = self._records(data, "/sources")
            scanned += len(recs)
            found.extend(r for r in recs if not words or _name_matches(r.get("name"), words))
            if len(recs) < p["limit"]:
                complete = True
                break
            if len(found) >= lim:
                break
        found = found[:lim]

        datasets = {}
        rows = [self._asset_row(r, gas, datasets) for r in found]
        notes = []
        partial = self._partial_note(y)
        if partial:
            notes.append(partial)
        if words and not complete:
            notes.append("The API has no name search: this looked at the top %d assets for the other filters "
                         "(the tool's limit is %d) and more exist beyond them." % (scanned, NAME_SCAN_PAGES * PAGE))
        if not words and not complete:
            notes.append("These are the first %d; more may exist (raise limit, up to %d)." % (lim, PAGE))
        if not rows:
            if sub and self.snapshot.subsectors.get(sub, {}).get("asset") is False:
                notes.append("The API lists no asset-level data for %s (only country totals): use country_emissions." % sub)
            else:
                notes.append("No assets matched.")
        if not rows and not scanned:
            notes.append("The API returned no records for these filters (it answers \"no rows\" with null).")
        out = {"tool": "search_assets", "query": query, "year": y}
        out.update(self._common(retrieved, gas))
        out.update({"count": len(rows), "scanned": scanned, "complete": complete, "assets": rows,
                    "source_datasets": datasets})
        self._terms(out, datasets.values())
        out["notes"] = notes
        return out

    def asset(self, asset_id, years=None, gas="co2e_100yr") -> dict:
        aid = _int(asset_id, "asset_id", 1, 10 ** 12)
        today = self._today()
        ys = _years(years, MIN_YEAR_ASSETS, today.year, today.year - MIN_YEAR_ASSETS + 1,
                    list(range(MIN_YEAR_ASSETS, today.year)))
        g = _gas(gas)
        data, day = self.client.get("/sources/%d" % aid, {"start": min(ys), "end": max(ys),
                                                         "timeGranularity": "year", "gas": g})
        if data is None:
            raise ToolError("the API returned no record for asset %d" % aid, "not_found")
        if not isinstance(data, dict):
            raise BadPayload("expected an object for asset %d, got %s" % (aid, type(data).__name__), "/sources/%d" % aid)
        missing = [k for k in ("id", "name", "subsector", "emissions") if k not in data]
        sub = data.get("subsector") if isinstance(data.get("subsector"), str) and _SLUG.match(data.get("subsector")) else None
        dataset = prov.describe(self.snapshot, sub, g, "source")
        conf_key = prov.GASES[g]["confidence_key"]
        by_year = {}
        for e in data.get("emissions") or []:
            if isinstance(e, dict) and isinstance(e.get("year"), int) and e["year"] in ys:
                if e.get("gas") not in (None, g):
                    missing.append("emissions[%d].gas (the API answered %s)" % (e["year"], clean(e.get("gas"), 20)))
                    continue
                by_year[e["year"]] = e
        confidence = {c["year"]: c for c in data.get("confidence") or [] if isinstance(c, dict) and isinstance(c.get("year"), int)}
        ranks = {r["year"]: r.get("rank") for r in data.get("subsectorRanks") or []
                 if isinstance(r, dict) and isinstance(r.get("year"), int) and isinstance(r.get("rank"), int)}
        series = []
        for y in ys:
            e = by_year.get(y)
            if e is None:
                continue
            m = []
            entry = self._figure(self._number(e, "emissionsQuantity", m, required=True), g, y, dataset)
            entry.update({
                "confidence": clean(confidence.get(y, {}).get(conf_key), 20) or None,
                "emissions_factor": self._measure(e, "emissionsFactor", "emissionsFactorUnits", m),
                "activity": self._measure(e, "activity", "activityUnits", m),
                "capacity": self._measure(e, "capacity", "capacityUnits", m),
                "capacity_factor": self._number(e, "capacityFactor", m),
                "subsector_rank_global": ranks.get(y),
            })
            if m:
                entry["missing_fields"] = m
            series.append(entry)
        without = [y for y in ys if y not in by_year]
        owners, n_raw, _ = self._owners_from(data)
        notes = []
        if without:
            notes.append("No data for %s: the API returned no entry for %s (not a zero)." % (
                ", ".join(map(str, without)), "that year" if len(without) == 1 else "those years"))
        for y in ys:
            p = self._partial_note(y)
            if p and y in by_year:
                notes.append(p)
        if ranks:
            notes.append("subsector_rank_global is Climate TRACE's global rank of this asset within its subsector "
                         "(OpenAPI: \"for total CO2 emissions produced by the parent source/asset\").")
        country = data.get("country") if isinstance(data.get("country"), str) and _A3.match(data.get("country")) else None
        out = {"tool": "asset", "asset_id": aid, "name": clean(data.get("name"), 200) or None,
               "country": country, "country_name": countries.name_of(country) if country else None,
               "sector": data.get("sector") if isinstance(data.get("sector"), str) and _SLUG.match(data.get("sector")) else None,
               "subsector": sub, "asset_type": clean(data.get("assetType"), 80) or None,
               "source_type": clean(data.get("sourceType"), 40) or None,
               "location": self._location(data.get("centroid")), "years_requested": ys}
        out.update(self._common({day}, g))
        out.update({"emissions": series, "years_without_data": without, "owners": owners,
                    "owners_note": "Owners as listed by the API (%d entries, %d distinct); the owners tool has details." % (n_raw, len(owners)),
                    "source_dataset": dataset})
        self._terms(out, [dataset])
        out["notes"] = notes
        if missing:
            out["missing_fields"] = missing
        return out

    def country_emissions(self, country, sector=None, years=None, gas="co2e_100yr") -> dict:
        a3, cname = countries.resolve(country)
        today = self._today()
        ys = _years(years, MIN_YEAR_COUNTRY, today.year, MAX_COUNTRY_YEARS, [today.year - 1])
        g = _gas(gas)
        sec = self._sector(sector) if sector is not None else None
        by_subsector = sec is not None and sec != ALL_NO_FOREST
        retrieved, rows, datasets, seen_subs = set(), [], {}, {}
        for y in ys:
            params = {"year": y, "gas": g, "gadmId": a3}
            if sec:
                params["sectors"] = sec
            data, day = self.client.get("/sources/emissions", params)
            retrieved.add(day)
            rows.append(self._country_year(data, y, a3, sec, g, by_subsector, datasets, seen_subs))
        notes = []
        if sec is None:
            notes.append("All sectors, including forestry-and-land-use (which can be negative). climatetrace.org "
                         "shows totals without it by default: pass sector=\"all_no_forest\" to match.")
        for y in ys:
            p = self._partial_note(y)
            if p:
                notes.append(p)
        flagged = sorted(s for s, d in datasets.items() if d["external_datasets"])
        if flagged:
            notes.append("These subsectors include data Climate TRACE reproduces from external datasets: %s. "
                         "See source_datasets and external_dataset_terms." % ", ".join(flagged))
        if not by_subsector:
            # Keep the answer small: every subsector without an external dataset or
            # licence flag is Climate TRACE's own model (the sectors tool lists them).
            own = sorted(s for s, d in datasets.items()
                         if not d["external_datasets"] and not d["non_commercial_terms_may_apply"])
            datasets = {s: d for s, d in datasets.items() if s not in own}
            if own:
                notes.append("The other %d subsectors in these totals are Climate TRACE's own models; the sectors "
                             "tool lists their data leads." % len(own))
        out = {"tool": "country_emissions", "country": a3, "country_name": cname,
               "sector": sec, "years_requested": ys}
        out.update(self._common(retrieved, g))
        out.update({"breakdown_by": "subsector" if by_subsector else "sector", "years": rows,
                    "source_datasets": datasets,
                    "non_commercial_terms_may_apply": any(d["non_commercial_terms_may_apply"] for d in datasets.values())})
        self._terms(out, datasets.values())
        out["notes"] = notes
        return out

    def _country_year(self, data, y, a3, sec, g, by_subsector, datasets, seen_subs) -> dict:
        endpoint = "/sources/emissions"
        if data is None:
            return {"year": y, "total": None, "note": "no data: the API returned null"}
        if not isinstance(data, dict):
            raise BadPayload("expected an object for %s %d, got %s" % (a3, y, type(data).__name__), endpoint)
        missing = [k for k in ("location", "totals", "sectors", "subsectors") if k not in data]
        loc = data.get("location") if isinstance(data.get("location"), dict) else {}
        got = loc.get("country") or loc.get("gadmId")
        if got is not None and got != a3:
            raise ToolError("the API answered for %s instead of %s; not reporting it" % (clean(got, 12), a3),
                            "unexpected_response")

        def block(name):
            b = data.get(name) if isinstance(data.get(name), dict) else {}
            return ([s for s in b.get("summaries") or [] if isinstance(s, dict)],
                    [t for t in b.get("timeseries") or [] if isinstance(t, dict)])

        tot_sums, tot_ts = block("totals")
        sec_sums, _ = block("sectors")
        sub_sums, _ = block("subsectors")
        returned = {s.get("sector") for s in sec_sums if isinstance(s.get("sector"), str)}
        if sec == ALL_NO_FOREST:
            unexpected = returned & {"forestry-and-land-use"}
        elif sec:
            unexpected = returned - {sec}
        else:
            unexpected = set()
        # The API answers an unknown or ignored sector filter with the whole
        # country (seen 2026-09-24): a total that must not carry the sector's name.
        if unexpected:
            raise ToolError("the API returned sectors that were not requested (%s), so its total is not the %s "
                            "total; not reporting it" % (", ".join(sorted(clean(s, 40) for s in unexpected)), sec),
                            "unexpected_response")
        total = next((s for s in tot_sums if s.get("gas") == g), None)
        months = sorted({t.get("month") for t in tot_ts if t.get("year") == y and isinstance(t.get("month"), int)})
        if total is None or not months:
            got_value = total.get("emissionsQuantity") if total else None
            return {"year": y, "total": None,
                    "note": "no data for %d: the API returned %s with no monthly values; a true zero comes with "
                            "monthly values" % (y, "a total of %s" % got_value if got_value is not None else "no total")}
        subs = []
        for s in sub_sums:
            name = s.get("subsector")
            if isinstance(name, str) and _SLUG.match(name):
                if name not in datasets:
                    datasets[name] = prov.describe(self.snapshot, name, g, "country")
                subs.append(s)
        ext_subs = [s for s in subs if datasets[s["subsector"]]["external_datasets"]]
        if by_subsector:
            label = "Climate TRACE country total for %s, sector %s (subsectors listed)" % (a3, sec)
            if ext_subs:
                label += "; includes data reproduced from external datasets in: " + ", ".join(s["subsector"] for s in ext_subs)
        else:
            label = "Climate TRACE country total for %s across %d subsectors" % (a3, len(subs))
            if ext_subs:
                label += ", %d of which include data reproduced from external datasets (see source_datasets)" % len(ext_subs)
        nc = any(datasets[s["subsector"]].get("non_commercial_terms_may_apply") for s in subs)
        m = []
        entry = {"year": y,
                 "total": self._figure(self._number(total, "emissionsQuantity", m, required=True), g, y,
                                       {"label": label, "non_commercial_terms_may_apply": nc}),
                 "months_with_data": len(months)}
        if len(months) < 12:
            entry["partial_year"] = True
        if by_subsector:
            entry["subsectors"] = [{"subsector": s["subsector"],
                                    "value": self._number(s, "emissionsQuantity", m),
                                    "share_percent": self._number(s, "percentage", m),
                                    "source_dataset": datasets[s["subsector"]]["label"]} for s in subs]
        else:
            entry["sectors"] = [{"sector": clean(s.get("sector"), 40) or None,
                                 "value": self._number(s, "emissionsQuantity", m),
                                 "share_percent": self._number(s, "percentage", m)} for s in sec_sums]
            entry["external_dataset_subsectors"] = [
                {"subsector": s["subsector"], "value": self._number(s, "emissionsQuantity", m)} for s in ext_subs]
        if missing or m:
            entry["missing_fields"] = missing + m
        return entry

    def owners(self, asset_id) -> dict:
        aid = _int(asset_id, "asset_id", 1, 10 ** 12)
        today = self._today()
        # Same request as asset() with its defaults, so the two share one cached answer.
        data, day = self.client.get("/sources/%d" % aid, {"start": MIN_YEAR_ASSETS, "end": today.year - 1,
                                                         "timeGranularity": "year", "gas": "co2e_100yr"})
        if data is None:
            raise ToolError("the API returned no record for asset %d" % aid, "not_found")
        if not isinstance(data, dict):
            raise BadPayload("expected an object for asset %d, got %s" % (aid, type(data).__name__), "/sources/%d" % aid)
        owners, n_raw, present = self._owners_from(data)
        notes = []
        if not present:
            notes.append("The API answer has no owners field (missing field).")
        elif not owners:
            notes.append("The API lists no owners for this asset.")
        if owners and not any(o["lei"] for o in owners):
            notes.append("The API returned no LEI for these owners. climate_trace_owner_id is Climate TRACE's own "
                         "identifier; it is not an LEI (an LEI has 20 characters, ISO 17442).")
        if n_raw > len(owners):
            notes.append("The API listed %d owner entries for %d distinct owner%s." % (n_raw, len(owners), "" if len(owners) == 1 else "s"))
        return {"tool": "owners", "asset_id": aid, "asset_name": clean(data.get("name"), 200) or None,
                "country": data.get("country") if isinstance(data.get("country"), str) and _A3.match(data.get("country")) else None,
                "subsector": data.get("subsector") if isinstance(data.get("subsector"), str) and _SLUG.match(data.get("subsector")) else None,
                "owners": owners, "ownership_shares": "not provided by the API",
                "ownership_data_source": "Climate TRACE: \"%s\" (%s, checked %s)" % (prov.OWNERSHIP_QUOTE, prov.TERMS_URL, prov.CHECKED),
                "notes": notes, "licence": "CC BY 4.0 (Climate TRACE, %s)" % prov.TERMS_URL,
                "attribution": prov.attribution(day)}

    def sectors(self) -> dict:
        snap = self.snapshot
        grouped = {}
        for name in sorted(snap.subsectors):
            rec = snap.subsectors[name]
            sector = snap.sector_of(name) or "(unknown)"
            grouped.setdefault(sector, []).append({
                "subsector": name,
                "display": clean(rec.get("subsectorDisplay"), 80) or None,
                "asset_level_data": rec.get("asset") if isinstance(rec.get("asset"), bool) else None,
                "country_level_data": rec.get("country") if isinstance(rec.get("country"), bool) else None,
                "data_leads": [lead["name"] for lead in snap.data_leads(name) or []],
                "external_datasets_per_terms": [{"dataset": k, "scope": scope}
                                                for k, scope, _ in prov.TERMS_SUBSECTORS.get(name, [])],
            })
        live = {"status": "not_checked"}
        retrieved = set()
        try:
            live_sectors, day = self.client.get("/definitions/sectors")
            live_subs, _ = self.client.get("/definitions/subsectors")
            retrieved.add(day)
            if not isinstance(live_sectors, list) or not isinstance(live_subs, list):
                raise BadPayload("definitions are not lists", "/definitions")
            ls = {s for s in live_sectors if isinstance(s, str)}
            lu = {s for s in live_subs if isinstance(s, str)}
            added = sorted((ls - set(snap.sectors)) | (lu - set(snap.subsectors)))
            removed = sorted((set(snap.sectors) - ls) | (set(snap.subsectors) - lu))
            live = {"status": "matches snapshot" if not (added or removed) else "differs from snapshot",
                    "new_in_api": [clean(a, 80) for a in added], "no_longer_in_api": removed}
            if added:
                live["hint"] = "New names still work as filters; `climate-trace-mcp refresh` updates their labels."
        except ApiError as e:
            live = {"status": "could not check", "error": e.as_dict()}
        out = {"tool": "sectors",
               "sectors": [{"sector": s, "subsectors": grouped.get(s, [])} for s in sorted(grouped)],
               "special_sector_values": {ALL_NO_FOREST: "all sectors except forestry-and-land-use (country_emissions, search_assets)"},
               "gases": {k: {"unit": v["unit"], "gwp_horizon": v["gwp_horizon"]} for k, v in prov.GASES.items()},
               "snapshot_retrieved": snap.retrieved, "snapshot_api_version": snap.api_version,
               "live_check": live,
               "attribution": prov.attribution(min(retrieved) if retrieved else (snap.retrieved or self._today().isoformat()))}
        if snap.error:
            out["snapshot_error"] = snap.error
        return out

    def sources(self) -> dict:
        version, checked = None, None
        try:
            text, checked = self.client.get_text("/docs/openapi.json")
            version = prov.openapi_version(text)
            version_note = None if version else "the OpenAPI document has no readable info.version"
        except ApiError as e:
            version_note = "could not check the live API version (%s)" % e.kind
        return {
            "tool": "sources",
            "provider": "Climate TRACE (climatetrace.org), a coalition; WattTime Corporation serves as its secretariat",
            "api": self.client.base, "api_documentation": prov.API_DOCS_URL,
            "api_version_live": version, "api_version_checked": checked, "api_version_note": version_note,
            "api_version_tested": "%s (%s)" % (prov.API_VERSION_TESTED, prov.CHECKED),
            "api_status": {"quote": prov.BETA_QUOTE, "source": prov.DATA_PAGE_URL, "checked": prov.CHECKED},
            "licence": {"name": prov.LICENCE_NAME, "url": prov.LICENCE_URL, "terms": prov.TERMS_URL,
                        "quote": prov.LICENCE_QUOTE, "checked": prov.CHECKED},
            "attribution": prov.attribution(checked or self._today().isoformat()),
            "attribution_note": ("Quote this line with every figure. CC BY 4.0 also asks you to say when you changed "
                                 "the data: call a figure you computed from these (a sum, a share) \"derived\"."),
            "citation_guidance": prov.CITATION_URL,
            "estimate_type": "modelled",
            "caveat": prov.CAVEAT,
            "how_climate_trace_describes_its_data": {"quote": prov.MODEL_QUOTE, "also": prov.EVOLVING_QUOTE,
                                                     "source": prov.TERMS_URL, "checked": prov.CHECKED},
            "external_datasets": {
                "quote": prov.USER_QUOTE, "source": prov.TERMS_URL, "checked": prov.CHECKED,
                "datasets": [dict(prov.external_dataset(k),
                                  subsectors=sorted(s for s, v in prov.TERMS_SUBSECTORS.items() if any(d[0] == k for d in v)))
                             for k in prov.EXTERNAL],
                "edgar_co2_licence_quote": prov.EXTERNAL["EDGAR"]["licence_quote"],
            },
            "gases": {k: {"unit": v["unit"], "gwp_horizon": v["gwp_horizon"]} for k, v in prov.GASES.items()},
            "gases_source": prov.GAS_SOURCE,
            "data_leads_snapshot": {"retrieved": self.snapshot.retrieved, "api_version": self.snapshot.api_version,
                                    "subsectors": len(self.snapshot.subsectors)},
            "what_this_is_not": [
                "Not measured, verified or company-reported emissions: Climate TRACE publishes modelled estimates.",
                "Not a check of any company's reported figures. A difference between a Climate TRACE estimate and a "
                "reported figure is a difference in method, scope or boundary, not evidence that either is wrong.",
                "Not regulatory data (for example EU ETS verified emissions) and not legal advice on licences.",
                "Not affiliated with or endorsed by Climate TRACE.",
            ],
        }


TOOLS = [
    {"name": "search_assets",
     "description": (
         "Find emitting assets in Climate TRACE (facilities, or district-level aggregates where it has no facility "
         "data), ranked by emissions for one year, largest first. Filters: country (ISO 3166-1 alpha-3 such as DEU, "
         "alpha-2 such as DE, or an English name), sector and subsector (names from the sectors tool, e.g. "
         "manufacturing / iron-and-steel, power / electricity-generation), year (2021 to the current year; default "
         "the last complete calendar year; the current year is partial), name (words matched case- and "
         "accent-insensitively in asset names; the API has no name search, so this reads at most the top 500 assets "
         "for the other filters and says whether that covered everything). Returns up to `limit` assets (1-100, "
         "default 20), each with asset_id, name, country, subsector, asset type, emissions in tonnes of CO2e "
         "(co2e_100yr: 100-year GWP, IPCC AR6), emissions factor, activity and capacity with their units, "
         "coordinates, and the dataset it comes from. All figures are modelled estimates, not measured or reported "
         "values. Quote the attribution line with any figure."),
     "inputSchema": {"type": "object", "properties": {
         "name": {"type": "string", "description": "Words to find in asset names, e.g. \"Salzgitter\" or \"Belchatow\"."},
         "country": {"type": "string", "description": "ISO 3166-1 alpha-3 (DEU), alpha-2 (DE) or English name (Germany)."},
         "sector": {"type": "string", "description": "A sector from the sectors tool, e.g. manufacturing, power."},
         "subsector": {"type": "string", "description": "A subsector from the sectors tool, e.g. iron-and-steel."},
         "year": {"type": "integer", "minimum": MIN_YEAR_ASSETS, "description": "Default: the last complete calendar year."},
         "limit": {"type": "integer", "minimum": 1, "maximum": PAGE, "default": 20}},
         "additionalProperties": False}},
    {"name": "asset",
     "description": (
         "Emissions by year and details for one Climate TRACE asset, by asset_id from search_assets. years: one "
         "year (2024), a range (\"2021-2024\") or a list (\"2021,2024\"), 2021 to the current year; default 2021 to "
         "the last complete year. gas: co2e_100yr (default; t CO2e, 100-year GWP, IPCC AR6), co2e_20yr, or co2, "
         "ch4, n2o in tonnes of the gas. Returns per year: value and unit, Climate TRACE's confidence label, "
         "emissions factor, activity, capacity and the asset's global rank in its subsector; plus country, "
         "coordinates, owners as the API lists them, and the source dataset with its licence. Years without data "
         "are listed as such, never shown as zero. Modelled estimates."),
     "inputSchema": {"type": "object", "properties": {
         "asset_id": {"type": "integer", "minimum": 1, "description": "Climate TRACE asset (source) id, e.g. 1566771."},
         "years": {"type": "string", "description": "\"2024\", \"2021-2024\" or \"2021,2024\"."},
         "gas": {"type": "string", "enum": list(prov.GASES), "default": "co2e_100yr"}},
         "required": ["asset_id"], "additionalProperties": False}},
    {"name": "country_emissions",
     "description": (
         "Country totals from Climate TRACE, one per year, optionally for one sector. country: ISO 3166-1 alpha-3 "
         "(POL), alpha-2 (PL) or English name (Poland). sector: a sector from the sectors tool, or \"all_no_forest\" "
         "for every sector except forestry-and-land-use (the default view on climatetrace.org); omitted means all "
         "sectors including forestry-and-land-use. years: \"2020-2024\", \"2020,2024\" or one year, 2015 to the "
         "current year, at most 12 per call; default the last complete year. gas as in the asset tool. Returns per "
         "year: the total in tonnes with unit and GWP horizon, the months with data (the current year is partial), "
         "and a breakdown by subsector (when a sector is given) or by sector, each labelled with its source dataset. "
         "Says which subsectors Climate TRACE reproduces from external datasets such as EDGAR or FAOSTAT, and when "
         "non-commercial licence terms may apply. Modelled estimates."),
     "inputSchema": {"type": "object", "properties": {
         "country": {"type": "string", "description": "ISO 3166-1 alpha-3 (POL), alpha-2 (PL) or English name."},
         "sector": {"type": "string", "description": "e.g. power, manufacturing, or all_no_forest."},
         "years": {"type": "string", "description": "\"2024\", \"2020-2024\" or \"2020,2024\"."},
         "gas": {"type": "string", "enum": list(prov.GASES), "default": "co2e_100yr"}},
         "required": ["country"], "additionalProperties": False}},
    {"name": "owners",
     "description": (
         "Owners of one Climate TRACE asset as the API lists them: owner name and Climate TRACE owner id, duplicates "
         "removed. The API gives no ownership shares. An LEI is shown only when the API returns a valid one; for the "
         "assets checked on 2026-09-24 it returned none. Climate TRACE compiles ownership from company websites, "
         "news and aggregators (PermID, OpenCorporates, Wikipedia)."),
     "inputSchema": {"type": "object", "properties": {
         "asset_id": {"type": "integer", "minimum": 1, "description": "Climate TRACE asset (source) id."}},
         "required": ["asset_id"], "additionalProperties": False}},
    {"name": "sectors",
     "description": (
         "Climate TRACE sectors and subsectors: the valid values for the sector and subsector filters, whether each "
         "has asset-level data, the data-lead organisations the API names for each, and the external datasets "
         "(EDGAR, FAOSTAT, E-PRTR, US EPA...) Climate TRACE's terms name for it. From a dated snapshot of the API's "
         "definitions, compared with the live lists when the API is reachable. Also lists the gas codes."),
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "sources",
     "description": (
         "Where the numbers come from: Climate TRACE's licence (CC BY 4.0, with exceptions for external datasets), "
         "the attribution line to quote, the modelled-estimates caveat, each external dataset with its licence and "
         "the date it was checked, the GWP definitions, the live API version and what this tool is not."),
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
]


def handlers(service: Service) -> dict:
    return {"search_assets": service.search_assets, "asset": service.asset,
            "country_emissions": service.country_emissions, "owners": service.owners,
            "sectors": service.sectors, "sources": service.sources}
