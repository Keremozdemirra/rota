"""Rebuild the bundled snapshot from the three sources, standard library only.

  DESNZ   GOV.UK Content API -> the "flat file" attachment (XLSX) -> CSV per year
  Ember   yearly global CSV (about 16 MB) -> the "Total generation" rows only
  UBA     one web page -> the German power-mix CO2 factors (numbers only)

Each source is refreshed on its own. A source that cannot be downloaded or
parsed keeps its previous snapshot and is reported; nothing half-written is
left behind, because every file is written to a temporary name and renamed.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import html
import http.client
import io
import json
import math
import os
import re
import tempfile
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal
from pathlib import Path
from typing import Callable

from . import VERSION
from . import provenance as P
from .xlsx import Workbook, XlsxError

MANIFEST = "manifest.json"
EMBER_FILE = "ember_yearly_intensity.csv"
UBA_FILE = "uba_strommix.json"
DESNZ_COLUMNS = ["id", "scope", "level_1", "level_2", "level_3", "level_4", "column_text", "uom", "ghg_unit", "value"]
EMBER_COLUMNS = ["area", "iso3", "area_type", "year", "intensity_gco2e_per_kwh", "emissions_mtco2e", "generation_twh"]
_DESNZ_HEADER = ["ID", "Scope", "Level 1", "Level 2", "Level 3", "Level 4", "Column Text", "UOM", "GHG/Unit"]
_EMBER_REQUIRED = {"Area": "area", "ISO 3 code": "iso3", "Area type": "area_type", "Year": "year",
                   "Emissions intensity (gCO2e/kWh)": "intensity_gco2e_per_kwh",
                   "Emissions (MtCO2e)": "emissions_mtco2e", "Generation (TWh)": "generation_twh"}
_SAFE_ID = re.compile(r"^[0-9A-Za-z][0-9A-Za-z_.-]{0,63}$")
_NUMBER = re.compile(r"^-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?$")
# Size limits: the real files are 0.5 MB (DESNZ), 16 MB (Ember), 0.3 MB (UBA).
LIMITS = {"api": 2 * 2**20, "desnz": 32 * 2**20, "ember": 128 * 2**20, "uba": 8 * 2**20}


class RefreshError(Exception):
    """A source could not be refreshed; the message says why, in one line."""


def plain(d: Decimal) -> str:
    """A decimal without exponent or trailing zeros: 3E-5 -> '0.00003', 3943.0 -> '3943'."""
    s = format(d, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s


Fetch = Callable[[str, int], "tuple[bytes, dict]"]


def fetch(url: str, max_bytes: int, timeout: float = 90.0) -> tuple[bytes, dict]:
    """GET one https URL. Returns (body, lower-cased headers) or raises RefreshError."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise RefreshError(f"refusing to fetch {url!r}: only https URLs are fetched")
    req = urllib.request.Request(url, headers={"User-Agent": P.USER_AGENT.format(version=VERSION),
                                               "Accept-Encoding": "identity"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            final = urllib.parse.urlsplit(r.geturl() or url)
            if final.scheme != "https":  # urllib follows redirects; a downgrade to http is not followed through
                raise RefreshError(f"{parts.hostname} redirected to a non-https URL, refused")
            body = r.read(max_bytes + 1)
            headers = {k.lower(): v for k, v in r.headers.items()}
    except urllib.error.HTTPError as e:
        if e.code == 429:
            retry = e.headers.get("Retry-After") if e.headers else None
            raise RefreshError(f"HTTP 429 rate limited by {parts.hostname}"
                               + (f", retry after {retry} s" if retry else "")) from None
        raise RefreshError(f"HTTP {e.code} from {url}") from None
    except urllib.error.URLError as e:
        raise RefreshError(f"cannot reach {parts.hostname}: {e.reason}") from None
    except http.client.HTTPException as e:  # IncompleteRead, BadStatusLine, RemoteDisconnected
        raise RefreshError(f"broken HTTP response from {parts.hostname}: {type(e).__name__}") from None
    except (TimeoutError, OSError) as e:
        raise RefreshError(f"network error from {parts.hostname}: {type(e).__name__}: {e}") from None
    if len(body) > max_bytes:
        raise RefreshError(f"response from {parts.hostname} is larger than {max_bytes} bytes, refused")
    if not body.strip():
        raise RefreshError(f"empty response from {url}")
    return body, headers


MAX_LABEL = 200  # the longest label in the 2025 and 2026 files is 55 characters


def _label_text(value: str, what: str) -> str:
    """A table cell as it will reach an agent: no control characters, single spaces, bounded length.

    The cells are labels from a government table, but they end up in a model's
    context, so anything that does not look like a label is refused here.
    """
    text = "".join(ch for ch in value if unicodedata.category(ch) not in ("Cc", "Cf"))
    text = " ".join(text.split())
    if len(text) > MAX_LABEL:
        raise RefreshError(f"{what}: a {len(text)}-character cell where a label is expected, refused")
    return text


def _text(body: bytes, what: str) -> str:
    try:
        return body.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise RefreshError(f"{what} is not UTF-8 text") from None


# --------------------------------------------------------------------- DESNZ

def desnz_attachment(api_body: bytes, year: int) -> dict:
    """The flat-file attachment listed by the GOV.UK Content API for one year."""
    try:
        doc = json.loads(_text(api_body, "GOV.UK Content API response"))
    except json.JSONDecodeError:
        raise RefreshError("GOV.UK Content API response is not JSON") from None
    details = doc.get("details") if isinstance(doc, dict) else None
    attachments = details.get("attachments") if isinstance(details, dict) else None
    if not isinstance(attachments, list):
        raise RefreshError("GOV.UK Content API response has no attachment list")
    flat = [a for a in attachments if isinstance(a, dict) and "flat file" in str(a.get("title", "")).lower()
            and str(a.get("url", "")).lower().endswith(".xlsx")]
    if len(flat) != 1:
        raise RefreshError(f"expected one flat-file XLSX attachment for {year}, found {len(flat)}")
    url = str(flat[0]["url"])
    parts = urllib.parse.urlsplit(url)
    # The URL comes from a response body; only GOV.UK's asset host is fetched.
    if parts.scheme != "https" or parts.hostname != P.DESNZ_ASSET_HOST:
        raise RefreshError(f"flat-file URL {url!r} is not on {P.DESNZ_ASSET_HOST}, refused")
    return {"url": url, "title": str(flat[0].get("title", "")),
            "public_updated_at": str(doc.get("public_updated_at") or "")}


def _excel_date(value: str | None) -> str | None:
    if value and re.fullmatch(r"\d{5}(?:\.\d+)?", value):
        return (dt.date(1899, 12, 30) + dt.timedelta(days=int(float(value)))).isoformat()
    return value


def _label(rows: list, label: str) -> str | None:
    for row in rows:
        for i, cell in enumerate(row):
            if cell and cell.strip().rstrip(":").strip().lower() == label:
                return next((v.strip() for v in row[i + 1:] if v and v.strip()), None)
    return None


def parse_desnz(data: bytes, year: int) -> tuple[list[dict], dict]:
    """Rows of the DESNZ flat file, as published, plus the front-page metadata."""
    try:
        wb = Workbook(data)
        sheets = {name: wb.rows(name) for name in wb.sheet_names}
    except XlsxError as e:
        raise RefreshError(f"DESNZ {year} flat file: {e}") from None
    found = None
    for name, rows in sheets.items():
        for i, row in enumerate(rows):
            cells = [(c or "").strip() for c in row]
            if cells[:1] == ["ID"] and "UOM" in cells and "GHG/Unit" in cells:
                found = (name, i, cells)
                break
        if found:
            break
    if not found:
        raise RefreshError(f"DESNZ {year} flat file: no header row starting with 'ID' found")
    sheet, start, header = found
    missing = [h for h in _DESNZ_HEADER if h not in header]
    factor_cols = [i for i, h in enumerate(header) if h.startswith("GHG Conversion Factor")]
    if missing or len(factor_cols) != 1:
        raise RefreshError(f"DESNZ {year} flat file: header changed (missing {missing or 'the factor column'})")
    stated = re.search(r"(\d{4})", header[factor_cols[0]])
    if not stated or int(stated.group(1)) != year:
        raise RefreshError(f"DESNZ flat file header says {header[factor_cols[0]]!r}, expected year {year}")
    cols = [header.index(h) for h in _DESNZ_HEADER] + factor_cols
    out, seen, odd = [], set(), 0
    for row in sheets[sheet][start + 1:]:
        cells = [_label_text((row[i] if i < len(row) else None) or "", f"DESNZ {year} flat file") for i in cols]
        if not cells[0]:
            continue  # blank lines and the closing END marker
        if not _SAFE_ID.match(cells[0]):
            raise RefreshError(f"DESNZ {year} flat file: unexpected factor ID {cells[0][:40]!r}")
        if cells[0] in seen:
            raise RefreshError(f"DESNZ {year} flat file: factor ID {cells[0]} appears twice")
        seen.add(cells[0])
        value = cells[-1]
        if value:
            try:
                number = float(value)
            except ValueError:
                number = math.nan
            if math.isfinite(number):
                # repr is the shortest text that reads back to the same double; plain() drops the exponent.
                value = plain(Decimal(repr(number)))
            else:
                value, odd = "", odd + 1
        out.append(dict(zip(DESNZ_COLUMNS, cells[:-1] + [value])))
    if not out:
        raise RefreshError(f"DESNZ {year} flat file: no factor rows")
    front = next((rows for name, rows in sheets.items() if name.strip().lower() == "front page"), [])
    meta = {"year": year, "sheet": sheet, "version": _label(front, "version"), "status": _label(front, "status"),
            "updated": _excel_date(_label(front, "updated")), "rows": len(out),
            "rows_with_value": sum(1 for r in out if r["value"]), "non_numeric_values_dropped": odd}
    return out, meta


# --------------------------------------------------------------------- Ember

def parse_ember(data: bytes) -> tuple[list[dict], dict]:
    """The overall emissions intensity per area and year: Ember's "Total generation" rows."""
    text = _text(data, "Ember CSV")
    reader = csv.DictReader(io.StringIO(text, newline=""))
    fields = reader.fieldnames or []
    missing = [c for c in list(_EMBER_REQUIRED) + ["Electricity source"] if c not in fields]
    if missing:
        raise RefreshError(f"Ember CSV lacks columns {missing}; the download format may have changed")
    out, raw = [], 0
    try:
        for r in reader:
            raw += 1
            if (r.get("Electricity source") or "").strip() != "Total generation":
                continue
            row = {dst: _label_text(r.get(src) or "", "Ember CSV") for src, dst in _EMBER_REQUIRED.items()}
            if not row["area"] or not re.fullmatch(r"\d{4}", row["year"]):
                raise RefreshError(f"Ember CSV row {raw}: area or year missing")
            for k in ("intensity_gco2e_per_kwh", "emissions_mtco2e", "generation_twh"):
                if row[k] and not _NUMBER.match(row[k]):
                    raise RefreshError(f"Ember CSV row {raw}: {k} is not a number: {row[k][:20]!r}")
            out.append(row)
    except csv.Error as e:
        raise RefreshError(f"Ember CSV is malformed near row {raw}: {e}") from None
    if not out:
        raise RefreshError("Ember CSV has no 'Total generation' rows")
    years = sorted({int(r["year"]) for r in out if r["intensity_gco2e_per_kwh"]})
    meta = {"raw_rows": raw, "rows": len(out), "areas": len({r["area"] for r in out}),
            "rows_without_intensity": sum(1 for r in out if not r["intensity_gco2e_per_kwh"]),
            "years": f"{years[0]}-{years[-1]}" if years else ""}
    return out, meta


# ------------------------------------------------------------------------ UBA

def parse_uba(data: bytes) -> tuple[list[dict], dict]:
    """The yearly CO2 factors of the German power mix stated on the UBA page.

    Only the numbers are kept: the page text is CC BY-NC-ND. The parser looks
    for the sentence that holds "Gramm CO2" together with "Kilowattstunde"
    and pairs each year in it, and in the sentence after it, with the next
    number that follows.
    """
    page = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", _text(data, "UBA page"))
    text = html.unescape(re.sub(r"(?s)<[^>]+>", " ", page))
    text = re.sub(r"\s+", " ", text.replace("\u2082", "2"))
    text = re.sub(r"\bCO 2\b", "CO2", text)
    hit = re.search(r"Gramm CO2", text)
    if not hit:
        raise RefreshError("UBA page: no 'Gramm CO2' figure found; the page may have changed")
    before = text.rfind(". ", 0, hit.start())
    start = before + 2 if before >= 0 else 0
    first_end = text.find(". ", hit.end())
    second_end = text.find(". ", first_end + 2) if first_end >= 0 else -1
    window = text[start: second_end if second_end >= 0 else len(text)]
    if "Kilowattstunde" not in window:
        raise RefreshError("UBA page: the CO2 figure is not stated per Kilowattstunde; the page may have changed")
    pairs, year = [], None
    # Whole numbers only: "26,3" (a German decimal) must not read as 26.
    for token in re.findall(r"(?<!\d)(?<!\d[,.])\d{2,4}(?!\d)(?![,.]\d)", window):
        n = int(token)
        if 1990 <= n <= 2100 and len(token) == 4:
            year = n
        elif year is not None:
            pairs.append({"year": year, "g_co2_per_kwh": n})
            year = None
    years = [p["year"] for p in pairs]
    if not pairs or len(set(years)) != len(years) or not all(100 <= p["g_co2_per_kwh"] <= 1500 for p in pairs):
        raise RefreshError(f"UBA page: could not read year/value pairs reliably (got {pairs})")
    pairs.sort(key=lambda p: p["year"])
    return pairs, {"rows": len(pairs), "years": f"{pairs[0]['year']}-{pairs[-1]['year']}"}


# ------------------------------------------------------------------- writing

def _atomic_write(path: Path, data: bytes) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix="." + path.name + ".")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.chmod(tmp, 0o644)  # mkstemp creates 0600; the snapshot is meant to be shared and committed
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _csv_bytes(columns: list[str], rows: list[dict]) -> bytes:
    buf = io.StringIO(newline="")
    w = csv.DictWriter(buf, fieldnames=columns, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue().encode("utf-8")


def _raw_facts(body: bytes, url: str, today: str) -> dict:
    return {"raw_url": url, "raw_sha256": hashlib.sha256(body).hexdigest(), "raw_bytes": len(body), "retrieved": today}


def refresh_desnz(out: Path, year: int, get: Fetch, today: str) -> dict:
    api = P.DESNZ_API.format(year=year)
    body, _ = get(api, LIMITS["api"])
    att = desnz_attachment(body, year)
    raw, _ = get(att["url"], LIMITS["desnz"])
    rows, meta = parse_desnz(raw, year)
    name = f"desnz_{year}.csv"
    _atomic_write(out / name, _csv_bytes(DESNZ_COLUMNS, rows))
    return {"file": name, **meta, **_raw_facts(raw, att["url"], today), "page": P.DESNZ_PAGE.format(year=year),
            "content_api": api, "attachment_title": att["title"], "public_updated_at": att["public_updated_at"]}


def refresh_ember(out: Path, get: Fetch, today: str) -> dict:
    raw, headers = get(P.EMBER_CSV, LIMITS["ember"])
    rows, meta = parse_ember(raw)
    _atomic_write(out / EMBER_FILE, _csv_bytes(EMBER_COLUMNS, rows))
    return {"file": EMBER_FILE, **meta, **_raw_facts(raw, P.EMBER_CSV, today),
            "last_modified": headers.get("last-modified", ""), "page": P.EMBER["page"]}


def refresh_uba(out: Path, get: Fetch, today: str) -> dict:
    raw, _ = get(P.UBA_PAGE, LIMITS["uba"])
    rows, meta = parse_uba(raw)
    doc = {"country": "DEU", "area": "Germany", "unit": "g CO2/kWh", "values": rows}
    _atomic_write(out / UBA_FILE, (json.dumps(doc, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))
    # The page is rendered HTML and changes for reasons unrelated to the
    # figures, so its hash identifies this retrieval only.
    return {"file": UBA_FILE, **meta, **_raw_facts(raw, P.UBA_PAGE, today)}


def read_manifest(out: Path) -> dict:
    try:
        doc = json.loads((out / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"schema": 1, "sources": {}}
    if not isinstance(doc, dict) or not isinstance(doc.get("sources"), dict):
        return {"schema": 1, "sources": {}}
    return doc


def refresh(out: Path, only: set[str] | None = None, years: tuple[int, ...] = P.DESNZ_YEARS,
            get: Fetch | None = None, today: str | None = None) -> dict:
    """Refresh the snapshot in `out`. Returns {"ok": {...}, "failed": {...}}."""
    get = get or fetch
    out.mkdir(parents=True, exist_ok=True)
    today = today or dt.datetime.now(dt.timezone.utc).date().isoformat()
    manifest = read_manifest(out)
    jobs: list[tuple[str, Callable[[], dict]]] = []
    for y in years:
        jobs.append((f"desnz-{y}", lambda y=y: refresh_desnz(out, y, get, today)))
    jobs.append(("ember", lambda: refresh_ember(out, get, today)))
    jobs.append(("uba", lambda: refresh_uba(out, get, today)))
    ok, failed = {}, {}
    for key, job in jobs:
        group = key.split("-")[0]
        if only and key not in only and group not in only:
            continue
        try:
            manifest["sources"][key] = ok[key] = job()
        except RefreshError as e:
            failed[key] = str(e)
        except Exception as e:  # one source's surprise must not stop the others or leave a traceback
            failed[key] = f"unexpected {type(e).__name__}: {e}"
    manifest["schema"] = 1
    manifest["generated_by"] = f"ghg-factors-mcp {VERSION} refresh"
    manifest["sources"] = dict(sorted(manifest["sources"].items()))
    _atomic_write(out / MANIFEST, (json.dumps(manifest, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))
    _atomic_write(out / "SOURCES.md", sources_markdown(manifest).encode("utf-8"))
    return {"ok": ok, "failed": failed, "out": str(out)}


def sources_markdown(manifest: dict) -> str:
    src = manifest.get("sources", {})
    lines = ["# Sources of the bundled snapshot", "",
             "Generated by `ghg-factors-mcp refresh` from `manifest.json`; do not edit by hand.",
             "Values are copied from the sources unchanged; only rows and columns are selected. DESNZ numbers",
             "are written as the shortest plain decimal that reads back to the same double stored in the XLSX",
             "(e.g. `3.0000000000000001E-5` becomes `0.00003`).", ""]
    for key in sorted((k for k in src if k.startswith("desnz-")), reverse=True):
        m = src[key]
        lines += [f"## DESNZ {m.get('year')}: {P.DESNZ['title']}", "",
                  f"- Publication page: {m.get('page')}",
                  f"- File: {m.get('attachment_title')}",
                  f"- Raw file URL: {m.get('raw_url')}",
                  f"- Version (front page): {m.get('version')}, status {m.get('status')}, updated {m.get('updated')};"
                  f" GOV.UK public_updated_at {m.get('public_updated_at')}",
                  f"- Licence: {P.DESNZ['licence']}, {P.DESNZ['licence_url']}",
                  f"- Terms (GOV.UK footer): \"{P.DESNZ['terms_quote']}\"",
                  f"- Attribution: {P.DESNZ['attribution_statement']}",
                  f"- Retrieved: {m.get('retrieved')}; SHA-256 of the raw XLSX: `{m.get('raw_sha256')}`"
                  f" ({m.get('raw_bytes')} bytes)",
                  f"- Snapshot: `{m.get('file')}`, {m.get('rows')} rows, {m.get('rows_with_value')} with a value"
                  " (the others are published blank)", ""]
    if "ember" in src:
        m = src["ember"]
        lines += [f"## Ember: {P.EMBER['title']}", "",
                  f"- Page: {P.EMBER['page']}", f"- Raw file URL: {m.get('raw_url')}",
                  f"- Last-Modified header: {m.get('last_modified')}",
                  f"- Licence: {P.EMBER['licence']}, {P.EMBER['licence_url']}; terms {P.EMBER['terms_url']}",
                  f"- Terms: \"{P.EMBER['terms_quote']}\"",
                  f"- Retrieved: {m.get('retrieved')}; SHA-256 of the raw CSV: `{m.get('raw_sha256')}`"
                  f" ({m.get('raw_bytes')} bytes)",
                  f"- Snapshot: `{m.get('file')}`, {m.get('rows')} rows (the 'Total generation' rows of"
                  f" {m.get('raw_rows')}), {m.get('areas')} areas, years with a value {m.get('years')};"
                  " columns kept: area, ISO 3 code, area type, year, emissions intensity, emissions, generation", ""]
    if "uba" in src:
        m = src["uba"]
        lines += [f"## Umweltbundesamt: {P.UBA['title']}", "",
                  f"- Page: {m.get('raw_url')}",
                  f"- Terms: {P.UBA['terms_url']} (section C): \"{P.UBA['terms_quote']}\"",
                  "- Kept: the yearly figures only (g CO2 per kWh). Page texts and graphics are CC BY-NC-ND 4.0"
                  " and are not copied.",
                  f"- Retrieved: {m.get('retrieved')}; SHA-256 of the page as retrieved: `{m.get('raw_sha256')}`"
                  f" ({m.get('raw_bytes')} bytes; the page is re-rendered often, so the hash identifies"
                  " this retrieval only)",
                  f"- Snapshot: `{m.get('file')}`, {m.get('rows')} values, years {m.get('years')}", ""]
    lines += ["## Not included, on licence grounds", ""]
    for x in P.EXCLUDED:
        lines.append(f"- {x['source']}: {x['reason']} {x['evidence_url']} (checked {x['checked']}): \"{x['quote']}\"")
    return "\n".join(lines) + "\n"
