"""From an ESRS datapoint workbook to an index: one record per datapoint row.

EFRAG's lists change their columns between releases (IG 3 in 2024, the 2026 draft
for the revised ESRS) and will change again, so columns are found by their header
text, never by position. In each sheet the header row is the row near the top that
has both an ID and a Name column; when several rows qualify, the one with the most
recognised columns wins. Sheets without such a row (an index, a disclaimer,
statistics) are skipped and reported.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import os
import re
from pathlib import Path

from . import sources
from .text import ID_RE, clean
from .xlsx import XlsxError, read_workbook

PARSER_VERSION = 1
HEADER_SCAN_ROWS = 40

# The columns the tools filter or report on. A file without some of them is still
# read; index_status says which ones it lacks.
CORE_FIELDS = ("standard", "dr", "paragraph", "name", "data_type", "conditional",
               "voluntary", "eu_legislation", "phase_in")
STANDARDS = ("ESRS 2", "E1", "E2", "E3", "E4", "E5", "S1", "S2", "S3", "S4", "G1")

# Disclosure requirement families of ESRS 2 (general disclosures and the minimum or
# general disclosure requirements for policies, actions, targets and metrics).
_ESRS2_FAMILIES = ("BP", "GOV", "SBM", "IRO", "MDR", "GDR")

# The EU laws named in ESRS 2 Appendix B (2023/2772) and Appendix A (2026/1563):
# SFDR, Pillar 3, Benchmark Regulation and EU Climate Law references; checked in
# the text of Delegated Regulation (EU) 2026/1563 on 2026-09-24.
_EU_LAWS = {
    "sfdr": "SFDR",
    "pillar 3": "Pillar 3", "pillar3": "Pillar 3", "p3": "Pillar 3",
    "benchmark": "Benchmark Regulation", "bench": "Benchmark Regulation", "bmr": "Benchmark Regulation",
    "benchmark regulation": "Benchmark Regulation",
    "cl": "EU Climate Law", "climate law": "EU Climate Law", "eu climate law": "EU Climate Law",
}

_MONTHS = {m: i for i, m in enumerate(
    ("january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"), 1)}
_VERSION_WORDS = re.compile(r"\bversion\b\s*:?\s*(\d{1,2})\s+([a-z]+)\s+(\d{4})\b", re.I)
_VERSION_ISO = re.compile(r"\bversion\b\s*:?\s*(\d{4})-(\d{2})-(\d{2})\b", re.I)


class NotADatapointList(XlsxError):
    """The file is a workbook, but no sheet holds a datapoint table."""


class MissingFile(XlsxError):
    """No file at the given path."""

    def __init__(self, path):
        self.path = str(path)
        super().__init__(missing_file_message(path))


def missing_file_message(path) -> str:
    pages = "; ".join(p["page"] for p in sources.download_pages())
    return (f"No file at {path}. Download the workbook from EFRAG ({pages}), then point "
            "ESRS_DATAPOINTS_XLSX at it or run: esrs-datapoints-mcp index PATH")


# ------------------------------------------------------------------ headers

def normalize_header(text) -> str:
    s = clean(text, 400).casefold()
    s = re.sub(r"[\[\]()\"'*:?‘’“”]", " ", s)
    return " ".join(s.split())


def phase_key(h: str) -> str:
    """A stable name for a phase-in column, from words in its header."""
    if "disclosed in case of phase" in h or "disclosed when phas" in h:
        # Datapoints to report when an undertaking uses a phase-in, not
        # datapoints that are themselves phased in.
        return "disclose_when_using_phase_in"
    if re.search(r"\b750\b", h):
        return "under_750_employees"
    if "wave-one" in h or "wave one" in h or "wave 1" in h:
        return "wave_one_below_threshold" if "not exceeding" in h else "wave_one_above_threshold"
    if "other undertakings" in h:
        return "other_undertakings"
    if "all undertakings" in h:
        return "all_undertakings"
    return "phase_in"


def classify(h: str):
    """(field, sub-key) for a normalised header, or None. The first rule that fits wins."""
    if not h:
        return None
    if "mapping" in h and ("ig 3" in h or "ig3" in h or re.search(r"\bid\b", h)):
        return ("ig3_mapping", None)
    m = re.match(r"^(?:19|20)\d\d esrs(?: (dr|paragraph|related ar|related guidance|ar))?$", h)
    if m:
        return ({None: "ig3_standard", "dr": "ig3_dr", "paragraph": "ig3_paragraph"}
                .get(m.group(1), "ig3_related"), None)
    if h in ("id", "datapoint id", "data point id", "dp id", "identifier", "datapoint identifier"):
        return ("id", None)
    if h in ("esrs", "revised esrs", "standard", "esrs standard", "topical standard", "topical esrs"):
        return ("standard", None)
    if h in ("dr", "disclosure requirement", "disclosure requirement dr", "dr code",
             "disclosure requirement code"):
        return ("dr", None)
    if h in ("paragraph", "paragraphs", "para", "paragraph reference", "esrs paragraph", "paragraph ref"):
        return ("paragraph", None)
    if h in ("related ar", "related ars", "related guidance", "application requirement",
             "application requirements", "related application requirement",
             "related application requirements", "ar"):
        return ("related", None)
    if h in ("name", "datapoint name", "data point name", "datapoint", "data point", "dp name", "label"):
        return ("name", None)
    if h.startswith("disaggregation"):
        return ("disaggregations", None)
    if h in ("data type", "datatype", "type", "data types"):
        return ("data_type", None)
    if "defined in a different paragraph" in h or h.startswith("conditionality defined"):
        return ("condition_ref", None)
    if "conditional" in h or "alternative" in h:
        return ("conditional", None)
    if h in ("may v", "may", "voluntary", "may voluntary", "voluntary v", "v") or h.startswith("may v"):
        return ("voluntary", None)
    if "sfdr" in h or "pillar 3" in h or "eu legislation" in h or "appendix b" in h:
        return ("eu_legislation", None)
    if "phase" in h or "appendix c" in h:
        return ("phase_in", phase_key(h))
    return None


def find_header(rows: dict):
    """(row number, {column: (field, sub-key)}, {column: normalised header}) or None."""
    best = None
    for rn in sorted(rows)[:HEADER_SCAN_ROWS]:
        cols, texts, taken = {}, {}, set()
        for c in sorted(rows[rn]):
            h = normalize_header(rows[rn][c])
            k = classify(h)
            if not k:
                continue
            field, sub = k
            if field == "phase_in":
                base, n = sub, 2
                while ("phase_in", sub) in taken:
                    sub, n = f"{base}_{n}", n + 1
            elif any(f == field for f, _ in taken):
                continue  # the first column with a given meaning wins
            taken.add((field, sub))
            cols[c] = (field, sub)
            texts[c] = h
        fields = {f for f, _ in cols.values()}
        if "id" in fields and "name" in fields and (best is None or len(fields) > best[0]):
            best = (len(fields), rn, cols, texts)
    return None if best is None else best[1:]


# ------------------------------------------------------------------ values

def standard_code(value):
    """'ESRS E1', 'E1', 'esrs-e1' -> 'E1'; 'ESRS 2', '2', 'ESRS 2 MDR' -> 'ESRS 2'; else None."""
    s = clean(value, 80).upper()
    s = re.sub(r"[\s\-_.]+", " ", s.replace("ESRS", " ")).strip()
    m = re.match(r"^([ESG])\s?(\d)(?!\d)", s)
    if m and f"{m.group(1)}{m.group(2)}" in STANDARDS:
        return f"{m.group(1)}{m.group(2)}"
    if re.match(r"^2(?!\d)", s):
        return "ESRS 2"
    return None


def standard_from_code(code):
    """The standard an ID or DR code belongs to, from its prefix: E1-6 -> E1, BP-1 -> ESRS 2."""
    s = clean(code, 120)
    s = re.sub(r"^ESRS\d{2}_", "", s, flags=re.I)
    m = re.match(r"^([ESG][1-5])(?=[-.])", s, re.I)
    if m and m.group(1).upper() in STANDARDS:
        return m.group(1).upper()
    fam = re.match(r"^([A-Za-z]{2,3})-", s)
    if fam and fam.group(1).upper() in _ESRS2_FAMILIES:
        return "ESRS 2"
    return None


def normalize_dr(value) -> str:
    s = clean(value, 120)
    return re.sub(r"\s*([-.])\s*", r"\1", s)


def parse_voluntary(value):
    s = clean(value, 50).casefold()
    if not s:
        return False
    if s in ("v", "[v]", "yes", "y", "x", "true", "may", "voluntary"):
        return True
    return None


def parse_conditional(value):
    s = clean(value, 200).casefold()
    if not s:
        return None
    kinds = []
    if "condition" in s:
        kinds.append("conditional")
    if "alternative" in s:
        kinds.append("alternative")
    return ", ".join(kinds) if kinds else "other"


def parse_eu_legislation(value):
    """(['SFDR', 'Pillar 3', ...], leftover text or None)."""
    s = clean(value, 300)
    found, other = [], []
    for tok in re.split(r"[+/,;&]|\band\b", s, flags=re.I):
        t = " ".join(tok.casefold().split())
        if not t:
            continue
        law = _EU_LAWS.get(t)
        if law and law not in found:
            found.append(law)
        elif not law:
            other.append(tok.strip())
    return found, (", ".join(other) or None)


def subject_to_phase_in(dp: dict):
    """True when a phase-in column says something for this datapoint; None when the file has no such column."""
    detail = dp.get("phase_in")
    if detail is None:
        return None
    return any(not k.startswith("disclose_when") for k in detail)


def list_date(sheets, table_sheets: set):
    """A 'Version: 28 August 2026' line in a sheet that is not a datapoint table, as an ISO date."""
    for sheet in sheets:
        if sheet.name in table_sheets:
            continue
        for rn in sorted(sheet.rows)[:80]:
            for text in sheet.rows[rn].values():
                m = _VERSION_WORDS.search(text)
                if m and m.group(2).casefold() in _MONTHS:
                    try:
                        return dt.date(int(m.group(3)), _MONTHS[m.group(2).casefold()], int(m.group(1))).isoformat()
                    except ValueError:
                        continue
                m = _VERSION_ISO.search(text)
                if m:
                    try:
                        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
                    except ValueError:
                        continue
    return None


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ------------------------------------------------------------------ workbook

def _datapoints_from_sheet(sheet, header, stats: dict, seen_ids: dict) -> list:
    header_row, cols, _texts = header
    by_field = {}
    for c, (field, sub) in cols.items():
        by_field.setdefault(field, []).append((c, sub))
    id_col = by_field["id"][0][0]
    sheet_std = standard_code(sheet.name)
    out = []
    note = None

    for rn in sorted(sheet.rows):
        if rn <= header_row:
            continue
        cells = sheet.rows[rn]

        def get(field, cells=cells):
            hits = by_field.get(field)
            return clean(cells.get(hits[0][0])) if hits else ""

        raw_id = clean(cells.get(id_col), 400)
        others = [c for c, v in cells.items() if c != id_col and c in cols and clean(v)]
        if not raw_id:
            if others:
                stats["rows_without_id"] += 1
            continue
        if raw_id.casefold() in ("id", "datapoint id", "data point id"):
            continue  # a header repeated inside the table
        if not ID_RE.match(raw_id):
            compact = re.sub(r"\s+", "", raw_id)
            if len(raw_id) <= 40 and ID_RE.match(compact):
                raw_id = compact
            elif not others:
                # A sentence alone in the ID column heads the rows below it, as in a
                # block of datapoints that apply only in a stated case.
                note = clean(raw_id, 600)
                continue
            else:
                stats["invalid_ids"] += 1
                continue
        dp_id = raw_id
        if dp_id in seen_ids:
            seen_ids[dp_id] += 1
            stats["duplicate_ids"].append(dp_id)
            dp_id = f"{dp_id}#{seen_ids[raw_id]}"
        else:
            seen_ids[dp_id] = 1
        dp = {"id": dp_id, "sheet": clean(sheet.name, 120), "row": rn}
        dr = normalize_dr(get("dr"))
        std = (sheet_std or standard_code(get("standard")) or standard_from_code(dr)
               or standard_from_code(raw_id))
        if std:
            dp["standard"] = std
        if dr:
            dp["dr"] = dr
        for field in ("paragraph", "related", "name", "data_type", "disaggregations", "condition_ref"):
            v = get(field)
            if v:
                dp[field] = v
        if "voluntary" in by_field:
            raw = get("voluntary")
            dp["voluntary"] = parse_voluntary(raw)
            if dp["voluntary"] is None:
                dp["voluntary_raw"] = raw
        if "conditional" in by_field:
            raw = get("conditional")
            kind = parse_conditional(raw)
            if kind:
                dp["conditional"] = kind
                if kind == "other":
                    dp["conditional_raw"] = raw
        if "eu_legislation" in by_field:
            laws, other = parse_eu_legislation(get("eu_legislation"))
            if laws:
                dp["eu_legislation"] = laws
            if other:
                dp["eu_legislation_other"] = other
        if "phase_in" in by_field:
            detail = {}
            for c, sub in by_field["phase_in"]:
                v = clean(cells.get(c), 600)
                if v:
                    detail[sub] = v
            dp["phase_in"] = detail
        if "ig3_mapping" in by_field:
            ids = [t for t in re.split(r"[\s,;]+", get("ig3_mapping")) if t and ID_RE.match(t)]
            if ids:
                dp["ig3_mapping"] = ids
        ref = {}
        for field, key in (("ig3_standard", "standard"), ("ig3_dr", "dr"), ("ig3_paragraph", "paragraph"),
                           ("ig3_related", "related")):
            v = get(field)
            if v:
                ref[key] = normalize_dr(v) if key == "dr" else v
        if ref:
            dp["ig3_reference"] = ref
        if note:
            dp["section_note"] = note
        out.append(dp)
    return out


def _layout(texts: set, fields: set, ids: list, sheet_names: list) -> str:
    if "revised esrs" in texts or fields & {"disaggregations", "condition_ref", "ig3_mapping"}:
        return "revised"
    if "voluntary" in fields or any(n.strip().upper().endswith(" MDR") for n in sheet_names):
        return "ig3"
    prefixed = sum(1 for i in ids if re.match(r"^ESRS\d{2}_", i))
    if ids and prefixed * 2 > len(ids):
        return "revised"
    return "list"


def describe(layout: str, variant, date, official) -> tuple:
    """(base key, title) for an index."""
    if layout == "ig3":
        key = "ig3" + (f"-{date}" if date else "")
        title = "ESRS datapoint list in the IG 3 layout"
    elif layout == "revised":
        key = "revised" + (f"-{date}" if date else "") + f"-{variant}"
        title = f"ESRS datapoint list in the revised-ESRS layout, {variant} variant"
    else:
        key = "list" + (f"-{date}" if date else "")
        title = "Datapoint list in an unrecognised layout, read by its column names"
    if official:
        title = official["title"]
    elif date:
        title += f", version {date}"
    if not official:
        title += f" (not byte-identical to an official file checked on {sources.CHECKED})"
    return key, title


def parse_workbook(path) -> dict:
    """Parse one workbook into an index dict. Raises XlsxError (or a subclass) with a helpful message."""
    p = Path(os.path.expanduser(str(path)))
    if not p.exists():
        raise MissingFile(p)
    if p.is_dir():
        raise XlsxError(f"{p} is a directory, not a workbook")
    sheets = read_workbook(p)
    digest = sha256_file(p)
    stats = {"rows_without_id": 0, "invalid_ids": 0, "duplicate_ids": []}
    datapoints, sheet_info, skipped = [], [], []
    fields, texts, table_sheets, seen_ids, phase_cols = set(), set(), set(), {}, set()
    for sheet in sheets:
        if sheet.hidden:
            skipped.append({"sheet": clean(sheet.name, 120), "reason": "hidden sheet"})
            continue
        header = find_header(sheet.rows)
        if not header:
            skipped.append({"sheet": clean(sheet.name, 120), "reason": "no header row with an ID and a Name column"})
            continue
        table_sheets.add(sheet.name)
        rows = _datapoints_from_sheet(sheet, header, stats, seen_ids)
        fields.update(f for f, _ in header[1].values())
        phase_cols.update(sub for f, sub in header[1].values() if f == "phase_in")
        texts.update(header[2].values())
        sheet_info.append({"sheet": clean(sheet.name, 120), "standard": standard_code(sheet.name),
                           "header_row": header[0], "datapoints": len(rows)})
        datapoints.extend(rows)
    if not table_sheets:
        raise NotADatapointList(
            f"{p} is a workbook, but none of its sheets has a header row with both an 'ID' and a 'Name' "
            "column. It does not look like an ESRS datapoint list; the supported files are listed by "
            "esrs-datapoints-mcp sources")
    layout = _layout(texts, fields, [d["id"] for d in datapoints], [s.name for s in sheets])
    variant = ("mapping" if "ig3_mapping" in fields else "clean") if layout == "revised" else None
    official = sources.official_file(digest)
    date = official["list_date"] if official else list_date(sheets, table_sheets)
    key, title = describe(layout, variant, date, official)
    st = p.stat()
    return {
        "format": 1,
        "parser": PARSER_VERSION,
        "key": key,
        "title": title,
        "layout": layout,
        "variant": variant,
        "list_date": date,
        "official": ({k: official[k] for k in ("title", "url", "page", "sha256", "checked")} if official else None),
        "file": {"name": p.name, "path": str(p.resolve()), "sha256": digest, "bytes": st.st_size,
                 "mtime": st.st_mtime},
        "parsed_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "columns_found": sorted(f for f in fields if f in CORE_FIELDS or f in ("related", "disaggregations",
                                                                                "condition_ref", "ig3_mapping")),
        "columns_missing": [f for f in CORE_FIELDS if f not in fields],
        "phase_in_columns": sorted(phase_cols),
        "sheets": sheet_info,
        "skipped_sheets": skipped,
        "rows_without_id": stats["rows_without_id"],
        "invalid_ids": stats["invalid_ids"],
        "duplicate_ids": sorted(set(stats["duplicate_ids"])),
        "notice": ("Parsed from your own copy of an EFRAG workbook. The datapoint content is EFRAG's; "
                   "keep it on this machine."),
        "datapoints": datapoints,
    }
