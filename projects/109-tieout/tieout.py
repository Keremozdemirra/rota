#!/usr/bin/env python3
"""tieout: find the source cell behind every number in a report or deck.

Consultants and auditors call it tying out: every figure in a deliverable is
checked against the workbook it came from. tieout does the mechanical part. It
reads a .docx, .pptx, .md or .txt file, extracts every number (with its number
format, scale, currency, sign and qualifier) and looks for cells in .xlsx and
.csv sources that the number could have come from, allowing for rounding,
percentages and scale. Every number it cannot tie is listed; every number it
skips on purpose (years, dates, page numbers ...) is listed with the reason
under --explain.

Standard library only. Nothing is sent anywhere unless --check-links is given,
and then only the http(s) URLs and DOIs written in the deliverable.

    tieout deck.pptx model.xlsx
    tieout report.docx model.xlsx data.csv --markdown
    tieout deck.pptx model.xlsx --json --strict
    tieout deck.pptx                    # list the numbers only
    tieout mcp                          # MCP server on stdio (tieout_mcp.py)
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import http.client
import io
import ipaddress
import json
import os
import posixpath
import re
import socket
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
import zlib
from bisect import bisect_left, bisect_right
from concurrent.futures import ThreadPoolExecutor
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal, InvalidOperation, localcontext

__version__ = "0.1.0"

# ---------------------------------------------------------------- constants
# The tool's own choices, not standards. The README lists them.
MAX_SAME_VALUE_CELLS = 5            # more cells than this holding the matching value: "ambiguous"
NEAREST_WITHIN = Decimal("0.10")    # untied number: show the closest source value within +/-10 %
YEAR_MIN, YEAR_MAX = 1900, 2100     # a bare four-digit integer in this range is read as a year
MAX_FILE_BYTES = 200 * 1024 * 1024  # larger inputs, and larger decompressed zip parts, are refused
LINK_TIMEOUT = 10.0                 # seconds per request under --check-links
CONTEXT_CHARS = 45                  # characters of context on each side of a number
MAX_CANDIDATES_SHOWN = 10

# Excel keeps 15 significant digits ("Number precision: 15 digits",
# https://support.microsoft.com/en-us/office/excel-specifications-and-limits-1672b34d-7043-467e-8e27-269d656771c3,
# checked 2026-09-24). Source values are read at that precision before rounding,
# so binary noise such as 0.61339999999999995 is taken as 0.6134.
EXCEL_DIGITS = 15

# Built-in number formats that display dates or times: ids 14-22 and 45-47 in
# all languages, 27-36 and 50-58 East Asian dates (Open XML SDK, NumberingFormat
# class, https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.spreadsheet.numberingformat,
# checked 2026-09-24). Cells formatted this way hold serial dates, not figures.
BUILTIN_DATE_FORMATS = set(range(14, 23)) | set(range(27, 37)) | set(range(45, 48)) | set(range(50, 59))

# Crossref's DOI pattern ("matches 74.4M" of 74.9M DOIs,
# https://www.crossref.org/blog/dois-and-matching-regular-expressions/, checked 2026-09-24).
# Only strings matching it are sent to doi.org.
DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")

USER_AGENT = "tieout/%s (link check; +https://github.com/Keremozdemirra/tieout)" % __version__

PDF_HELP = ("PDF is not supported: tieout uses the Python standard library only, which cannot "
            "extract PDF text. Convert first, for example `pdftotext -layout report.pdf report.txt` "
            "(poppler-utils; form feeds become page numbers), or export the original as .docx or .pptx.")

DELIVERABLE_FORMATS = {".docx": "docx", ".docm": "docx", ".dotx": "docx",
                       ".pptx": "pptx", ".pptm": "pptx", ".potx": "pptx",
                       ".md": "md", ".markdown": "md", ".txt": "txt", ".text": "txt"}
SOURCE_FORMATS = {".xlsx": "xlsx", ".xlsm": "xlsx", ".xltx": "xlsx", ".xltm": "xlsx",
                  ".csv": "csv", ".tsv": "csv"}
LEGACY_HELP = {".doc": "save it as .docx", ".ppt": "save it as .pptx", ".xls": "save it as .xlsx",
               ".xlsb": "save it as .xlsx", ".odt": "save it as .docx", ".odp": "save it as .pptx",
               ".ods": "save it as .xlsx", ".rtf": "save it as .docx", ".pages": "export it as .docx",
               ".key": "export it as .pptx", ".numbers": "export it as .xlsx"}

STATUS_ORDER = ("untied", "ambiguous", "tied", "extracted", "excluded")

R_YEAR = "year"
R_DATE = "date"
R_TIME = "time"
R_PAGE = "page or slide number"
R_FOOTNOTE = "footnote marker"
R_EXPONENT = "unit exponent (m², m³)"
R_LIST = "list or section numbering"
R_PHONE = "phone number"
R_LABEL = "label or reference (Scope 3, Figure 2, ISO 14001)"
R_CODE = "part of a word or code (CO2, Q3, FY25, 5G)"
R_ORDINAL = "ordinal (1st, 2nd)"
R_LINK = "part of a link, e-mail address or DOI"
R_CODEBLOCK = "code (Markdown code span or block)"
R_COMMENT = "HTML comment"
R_MALFORMED = "not a well-formed number"
R_UNITLABEL = "unit label ('000)"
R_SECRET = "inside a credential or query string (hidden)"


class InputError(Exception):
    """A file could not be read. The message says why, for a person."""


# ------------------------------------------------------------------ masking
_URL_CRED = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^/\s@]+@")
_URL_QUERY = re.compile(r"(?i)\b((?:https?|ftp)://[^\s?#]+)\?[^\s#]*")
_SECRET_FLAG = re.compile(r"(?i)(--(?:api[-_]?key|token|secret|password|passwd|access[-_]?key|auth)[=\s]+)\S+")
_SECRET_PAIR = re.compile(r"(?i)\b((?:api[-_]?key|token|secret|password|passwd|access[-_]?key)\s*[=:]\s*)\S+")
_SECRET_ENV = re.compile(r"\b([A-Z][A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD)[A-Z0-9_]*=)\S+")


_HIDE = "\ue000"  # stands in for a hidden character until runs of it are printed as ***


def _hide_groups(rx, text: str, group: int) -> str:
    return rx.sub(lambda m: m.group(0)[:m.start(group) - m.start()] + _HIDE * (m.end(group) - m.start(group))
                  + m.group(0)[m.end(group) - m.start():], text)


_URL_CRED_G = re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://([^/\s@]+)@")
_URL_QUERY_G = re.compile(r"(?i)\b(?:https?|ftp)://[^\s?#]+\?([^\s#]+)")
_SECRET_FLAG_G = re.compile(r"(?i)--(?:api[-_]?key|token|secret|password|passwd|access[-_]?key|auth)[=\s]+(\S+)")
_SECRET_PAIR_G = re.compile(r"(?i)\b(?:api[-_]?key|token|secret|password|passwd|access[-_]?key)\s*[=:]\s*(\S+)")
_SECRET_ENV_G = re.compile(r"\b[A-Z][A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD)[A-Z0-9_]*=(\S+)")


def hide_secrets(text: str) -> str:
    """Same length as `text`, secrets replaced by a placeholder, so positions still line up. Runs on the
    whole segment before anything is cut, so a cut can never split a secret from what marks it."""
    for rx in (_URL_CRED_G, _URL_QUERY_G, _SECRET_FLAG_G, _SECRET_PAIR_G, _SECRET_ENV_G):
        text = _hide_groups(rx, text, 1)
    return text


def shown(text: str) -> str:
    return re.sub(_HIDE + "+", "***", text)


def mask(text: str) -> str:
    """Hide URL credentials, query strings and key=value secrets before anything is printed."""
    if not text:
        return text
    text = _URL_CRED.sub(r"\1***@", text)
    text = _URL_QUERY.sub(r"\1?***", text)
    text = _SECRET_FLAG.sub(r"\1***", text)
    text = _SECRET_PAIR.sub(r"\1***", text)
    return _SECRET_ENV.sub(r"\1***", text)


# ------------------------------------------------------------ number helpers
def excel15(d: Decimal) -> Decimal:
    """Round to 15 significant digits, the precision Excel stores and shows."""
    if not d.is_finite() or d.is_zero():
        return Decimal(0) if d.is_zero() else d
    with localcontext() as c:
        c.prec = EXCEL_DIGITS
        c.rounding = ROUND_HALF_EVEN
        return (+d).normalize()


def fmt(d: Decimal | None) -> str:
    """A Decimal as a person writes it: 4,213,500,000 and 0.6134, never 4.2135E+9."""
    if d is None:
        return ""
    if d.is_zero():
        return "0"
    d = d.normalize()
    with localcontext() as c:
        c.prec = 60
        return format(d, ",f")


def fmt_short(d: Decimal) -> str:
    """At most six significant digits after the decimal point, for tables: 0.0875794, not 0.087579371225027."""
    d = d.normalize()
    if _decimals(d) and len(d.as_tuple().digits) > 6:
        q = _pow10(d.adjusted() - 5)
        d = d.quantize(q if q < 1 else Decimal(1))
    return fmt(d)


def fmt_places(d: Decimal, places: int) -> str:
    """A Decimal with exactly `places` decimals, grouped: 14.0, 4,213.5."""
    with localcontext() as c:
        c.prec = 60
        return format(d.quantize(_pow10(-places)) if places > 0 else d.to_integral_value(), ",f")


def _decimals(d: Decimal) -> int:
    exp = d.normalize().as_tuple().exponent
    return -exp if isinstance(exp, int) and exp < 0 else 0


def _pow10(n: int) -> Decimal:
    return Decimal(1).scaleb(n)


_SUP = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")
_SUB = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")


def _short(text: str, width: int) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= width else text[: max(1, width - 1)].rstrip() + "…"


# ---------------------------------------------------------------- xml, zip
def _local(tag) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _attr(el, name, default=None):
    """An attribute by local name, namespaced or not."""
    if el is None:
        return default
    for k, v in el.attrib.items():
        if _local(k) == name:
            return v
    return default


def _rattr(el, name):
    """A namespaced attribute (r:id, r:embed, r:dm), never the plain one of the same name."""
    if el is None:
        return None
    for k, v in el.attrib.items():
        if k.startswith("{") and _local(k) == name:
            return v
    return None


def _kids(el, name):
    return [c for c in el if _local(c.tag) == name] if el is not None else []


def _kid(el, name):
    if el is None:
        return None
    for c in el:
        if _local(c.tag) == name:
            return c
    return None


def _find_stop(el, names):
    """Descendants with a local name in `names`, not descending into a match."""
    for c in el:
        if _local(c.tag) in names:
            yield c
        else:
            yield from _find_stop(c, names)


def _text_of(el) -> str:
    return "".join(t.text or "" for t in el.iter() if _local(t.tag) == "t") if el is not None else ""


def _no_dtd(data: bytes, name: str) -> None:
    head = data
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        head = data.decode("utf-16", errors="replace").encode("utf-8")
    # OOXML parts never carry a DTD; refusing one rules out entity-expansion tricks.
    if b"<!DOCTYPE" in head or b"<!ENTITY" in head:
        raise InputError(f"{name} contains a document type declaration; Office files never need one, so it is not read")


def parse_xml(data: bytes, name: str):
    _no_dtd(data, name)
    try:
        return ET.fromstring(data)
    except ET.ParseError as e:
        raise InputError(f"{name}: malformed XML ({e})") from None


def _check_file(path: str) -> int:
    if not os.path.exists(path):
        raise InputError(f"{path}: file not found")
    if os.path.isdir(path):
        raise InputError(f"{path}: is a directory, not a file")
    try:
        size = os.path.getsize(path)
    except OSError as e:
        raise InputError(f"{path}: cannot be read ({e.strerror or e})") from None
    if size == 0:
        raise InputError(f"{path}: file is empty")
    if size > MAX_FILE_BYTES:
        raise InputError(f"{path}: larger than {MAX_FILE_BYTES // (1024 * 1024)} MB; not read")
    return size


def _read_file(path: str) -> bytes:
    _check_file(path)
    try:
        with open(path, "rb") as f:
            return f.read(MAX_FILE_BYTES + 1)
    except OSError as e:
        raise InputError(f"{path}: cannot be read ({e.strerror or e})") from None


class Rel:
    __slots__ = ("type", "target", "external")

    def __init__(self, type_, target, external):
        self.type, self.target, self.external = type_, target, external


class Package:
    """An Office Open XML zip, read with size limits and without a DTD."""

    def __init__(self, path: str, what: str):
        self.path, self.name, self.what = path, os.path.basename(path), what
        _check_file(path)
        try:
            with open(path, "rb") as f:
                head = f.read(8)
        except OSError as e:
            raise InputError(f"{path}: cannot be read ({e.strerror or e})") from None
        if head.startswith(b"%PDF"):
            raise InputError(f"{self.name}: this is a PDF. {PDF_HELP}")
        if head.startswith(b"\xd0\xcf\x11\xe0"):
            raise InputError(f"{self.name}: this is a legacy binary Office file or a password-protected one; "
                             f"save an unprotected copy as {what}")
        try:
            self.zip = zipfile.ZipFile(path)
            self.names = set(self.zip.namelist())
        except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, EOFError, ValueError) as e:
            raise InputError(f"{self.name}: not a valid {what} file (not a readable zip archive: {e})") from None
        self._rels = {}

    def has(self, part: str) -> bool:
        return part in self.names

    def read(self, part: str) -> bytes:
        try:
            info = self.zip.getinfo(part)
        except KeyError:
            raise InputError(f"{self.name}: part {part} is missing") from None
        if info.file_size > MAX_FILE_BYTES:
            raise InputError(f"{self.name}: part {part} unpacks to more than {MAX_FILE_BYTES // (1024 * 1024)} MB; not read")
        try:
            with self.zip.open(info) as f:
                data = f.read(MAX_FILE_BYTES + 1)
        except (zipfile.BadZipFile, zlib.error, EOFError, OSError, RuntimeError, NotImplementedError, ValueError) as e:
            raise InputError(f"{self.name}: part {part} is damaged ({type(e).__name__}: {e})") from None
        if len(data) > MAX_FILE_BYTES:
            raise InputError(f"{self.name}: part {part} unpacks to more than {MAX_FILE_BYTES // (1024 * 1024)} MB; not read")
        return data

    def xml(self, part: str):
        return parse_xml(self.read(part), f"{self.name}:{part}")

    def rels(self, part: str) -> dict:
        if part in self._rels:
            return self._rels[part]
        d, b = posixpath.split(part)
        rp = posixpath.join(d, "_rels", b + ".rels")
        out = {}
        if rp in self.names:
            for r in self.xml(rp):
                if _local(r.tag) != "Relationship":
                    continue
                target = r.get("Target") or ""
                external = (r.get("TargetMode") or "").lower() == "external"
                if not external:
                    t = urllib.parse.unquote(target)
                    target = t.lstrip("/") if t.startswith("/") else posixpath.normpath(posixpath.join(d, t))
                out[r.get("Id")] = Rel(r.get("Type") or "", target, external)
        self._rels[part] = out
        return out

    def main_part(self, suffix: str = "/officeDocument") -> str | None:
        for rel in self.rels("").values():
            if rel.type.endswith(suffix) and not rel.external:
                return rel.target
        return None


# ------------------------------------------------------------------ segments
class Segment:
    """A piece of deliverable text in one place: a paragraph, a table cell, a note, a chart value."""
    __slots__ = ("text", "where", "loc", "spans", "labels", "table", "raw", "lines")

    def __init__(self, text, where, loc=None, spans=None, labels=None, table=False, raw=None, lines=False):
        self.text = text
        self.where = where
        self.loc = loc or {}
        self.spans = spans or []        # (start, end, reason): text the reader already knows is not a figure
        self.labels = labels or []      # (kind, text): row label, column header, caption, chart title
        self.table = table
        self.raw = raw                  # "value" or "date" for a chart cache value
        self.lines = lines              # a line of a .md/.txt file


class _Para:
    """Accumulates paragraph text with spans and links."""

    def __init__(self):
        self.parts, self.n, self.spans, self.links, self.fields = [], 0, [], [], []

    def add(self, s: str) -> None:
        if s:
            self.parts.append(s)
            self.n += len(s)

    def text(self) -> str:
        return "".join(self.parts)


# ------------------------------------------------------------ number reading
_SEP_CHARS = ",.'\u2019\u00a0\u202f\u2009"
_SPACE_SEPS = "'\u2019\u00a0\u202f\u2009"
# A letter, for "the word ends here" checks. Python's \w also matches superscript and
# fraction digits (¹, ², ½), which may follow a unit ("€4.2bn¹"), so they are carved out.
_LET = r"[^\W\d_\u00b2\u00b3\u00b9\u00bc-\u00be\u2070-\u209f]"
NUM_RE = re.compile(r"(?<![0-9])[0-9]+(?:[,.'\u2019\u00a0\u202f\u2009][0-9]+)*")
_MINUS = "-\u2212\u2013"
_SP = " \u00a0\u202f\u2009"


def read_token(tok: str, locale: str):
    """Read a run of digits and separators.

    Returns (mantissa, decimals, evidence, note) or None if the token is not a
    well-formed number. `evidence` is "en" (1,234.5), "de" (1.234,5) or None
    when the form fits both. Only a lone separator followed by exactly three
    digits is ambiguous ("1,234"); the document's locale decides that one.
    """
    parts = re.split(r"[^0-9]", tok)
    seps = [c for c in tok if c in _SEP_CHARS]
    if not seps:
        return Decimal(tok), 0, None, None
    first, last = parts[0], parts[-1]
    if len(seps) == 1:
        c = seps[0]
        if c in _SPACE_SEPS:
            if 1 <= len(first) <= 3 and len(last) == 3:
                return Decimal(first + last), 0, None, None
            return None
        if len(last) == 3 and 1 <= len(first) <= 3 and first != "0":
            if c == ("," if locale == "de" else "."):
                return Decimal(first + "." + last), 3, None, f"'{tok}' read as a decimal ({locale} number format)"
            return Decimal(first + last), 0, None, f"'{tok}' read as thousands ({locale} number format)"
        return Decimal(first + "." + last), len(last), ("en" if c == "." else "de"), None
    if len(set(seps)) == 1:
        c = seps[0]
        if 1 <= len(first) <= 3 and all(len(p) == 3 for p in parts[1:]):
            return Decimal("".join(parts)), 0, ("en" if c == "," else "de" if c == "." else None), None
        return None
    dec, thou = seps[-1], set(seps[:-1])
    if len(thou) != 1 or dec not in ".," or dec in thou:
        return None
    if not (1 <= len(first) <= 3 and all(len(p) == 3 for p in parts[1:-1])):
        return None
    return Decimal("".join(parts[:-1]) + "." + last), len(last), ("en" if dec == "." else "de"), None


_MONTHS = (r"(?:jan(?:uary|uar)?|jän(?:ner)?|feb(?:ruary|ruar)?|mar(?:ch)?|märz|maerz|apr(?:il)?|may|mai|"
           r"jun[ei]?|jul[iy]?|aug(?:ust)?|sep(?:t(?:ember)?)?|o[ck]t(?:ober)?|nov(?:ember)?|de[cz](?:ember)?)"
           r"\.?(?!" + _LET + r")")
_DAY = r"(?:0?[1-9]|[12][0-9]|3[01])"
_LINK_RE = re.compile(r"(?i)\b(?:https?|ftp)://[^\s<>\"'«»]+|\bwww\.[^\s<>\"'«»]+|[\w.+-]+@[\w-]+(?:\.[\w-]+)+"
                      r"|\b(?:doi:\s*)?10\.\d{4,9}/[^\s\"<>]+")
_DATE_RES = [
    re.compile(r"(?<![\d.,])\d{4}-\d{1,2}-\d{1,2}(?!\d)"),
    re.compile(r"(?<![\d.,])\d{4}/\d{1,2}/\d{1,2}(?!\d)"),
    re.compile(r"(?<![\d.,/])\d{1,2}[./-]\d{1,2}[./-](?:\d{4}|\d{2})(?![\d])(?![.,]\d)"),
    re.compile(r"(?i)(?<![\w.,])" + _DAY + r"(?:st|nd|rd|th|\.)?(?:\s*[-–]\s*" + _DAY + r"(?:st|nd|rd|th|\.)?)?[ \u00a0]+"
               + _MONTHS + r"(?:,?[ \u00a0]+\d{4}(?!\d))?"),
    re.compile(r"(?i)(?<![\w])" + _MONTHS + r"[ \u00a0]+" + _DAY + r"(?:st|nd|rd|th)?(?:\s*[-–]\s*" + _DAY
               + r")?(?:,?[ \u00a0]+\d{4})?(?![\d.,]*\d)"),
    re.compile(r"(?i)(?<![\w])" + _MONTHS + r"[-/ '’]\d{2}(?![\d%])"),
    re.compile(r"(?<![\d.,])(?:0?[1-9]|1[0-2])/\d{4}(?!\d)"),
]
_TIME_RES = [
    re.compile(r"(?<![\d.,:])(?:[01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d)?(?!\d)"),
    re.compile(r"(?i)(?<![\d.,])(?:[01]?\d|2[0-3])[.:][0-5]\d\s?(?:h|uhr|am|pm|a\.m\.|p\.m\.)(?!" + _LET + r")"),
    re.compile(r"(?i)(?<![\d.,])(?:1[0-2]|0?[1-9])\s?(?:am|pm|a\.m\.|p\.m\.)(?!" + _LET + r")"),
    re.compile(r"(?i)(?<![\d.,])(?:[01]?\d|2[0-3])\s?uhr(?!" + _LET + r")"),
]
_PHONE_RES = [
    re.compile(r"(?<![\w+])(?:\+|00)[1-9][0-9]{0,2}(?:[ \u00a0./-]?\(?[0-9]{1,5}\)?){2,6}(?![0-9])"),
    re.compile(r"(?i)(?<![\w])(?:tel|phone|fax|mobile|mob|telefon|mobil)\.?:?[ \u00a0]*(\+?[0-9(][0-9 \u00a0()./-]{5,}[0-9])"),
    re.compile(r"(?<![\w])[TFM]:[ \u00a0]*(\+?[0-9(][0-9 \u00a0()./-]{5,}[0-9])"),
    re.compile(r"(?<![\w.,])\(?0[1-9][0-9]{1,4}\)?[ /-][0-9]{3,}(?:[ -][0-9]{2,})*(?![0-9])"),
]
_PAGE_RE = re.compile(r"(?i)(?<![\w])(?:pages?|pp?\.|seiten?|s\.|slides?|folien?)[ \u00a0]*"
                      r"\d{1,4}(?:[ \u00a0]*(?:[-–—]|to|bis|and|und|&|,|of|von|/)[ \u00a0]*\d{1,4})*(?![\d.,]*\d)")
_LABEL_WORDS = (r"(?:scope|tier|phase|stage|step|level|wave|round|option|scenario|section|chapter|article|art\.|"
                r"paragraph|para\.|clause|figure|fig\.|table|tab\.|exhibit|chart|appendix|annex|schedule|note|"
                r"footnote|item|no\.|nr\.|number|version|ver\.|release|iso|sdg|ifrs|ias|gri|question|priority|"
                r"pillar|principle|goal|kapitel|abschnitt|artikel|absatz|abs\.|ziffer|nummer|abbildung|abb\.|"
                r"tabelle|anhang|anlage|anmerkung|fußnote|szenario|stufe|schritt|welle|runde|säule|§|(?<!#)#(?=\d))")
_LNUM = r"\d+(?:[.,]\d+)*"
_LABEL_RE = re.compile(r"(?i)(?<![\w])" + _LABEL_WORDS + r"[ \u00a0]*" + _LNUM
                       + r"(?:(?:[ \u00a0]*,[ \u00a0]*" + _LNUM + r")*[ \u00a0]*,?[ \u00a0]*(?:and|und|or|oder|&)[ \u00a0]*" + _LNUM
                       + r"|[ \u00a0]*(?:[-–—/]|to|bis)[ \u00a0]*" + _LNUM + r")*(?![\d])")
_FOOTNOTE_RE = re.compile(r"\[\^?\d{1,3}\]|\[\d{1,3}(?:\s*[,–-]\s*\d{1,3})+\]")
_SUPER_RE = re.compile(r"[⁰¹²³⁴⁵⁶⁷⁸⁹]+")
_PAGE_LINE_RE = re.compile(r"(?i)^\s*(?:[-–—|]\s*)?(?:(?:page|seite|p\.|s\.|slide|folie)\s*)?\d{1,4}"
                           r"(?:\s*(?:/|of|von)\s*\d{1,4})?\s*(?:[-–—|]\s*)?$")
_LINE_PREFIX_RE = re.compile(r"[ \t]*(?:(?:#{1,6}|>|[-*+•▪◦‣–])[ \t]+)*")
_LIST_NUM_RE = re.compile(r"(?:\(?[0-9]{1,3}[.)]|[0-9]{1,2}(?:\.[0-9]{1,2}){1,3}\.?)(?=[ \t\u00a0]+\S)")

_SPAN_PRIORITY = {R_LINK: 0, R_CODEBLOCK: 0, R_COMMENT: 0, R_DATE: 1, R_TIME: 2, R_PHONE: 3, R_FOOTNOTE: 4,
                  R_PAGE: 5, R_LABEL: 6}


def _phone_ok(s: str) -> bool:
    digits = sum(ch.isdigit() for ch in s)
    return 8 <= digits <= 15 and not re.search(r"\.\d(?!\d)", s) and "%" not in s


def find_spans(text: str) -> list:
    """Stretches of text whose digits are not figures: links, dates, times, phone numbers,
    footnote markers, page references and labels. (start, end, reason)."""
    spans = [(m.start(), m.end(), R_LINK) for m in _LINK_RE.finditer(text)]
    for rx in _DATE_RES:
        spans += [(m.start(), m.end(), R_DATE) for m in rx.finditer(text)]
    for rx in _TIME_RES:
        spans += [(m.start(), m.end(), R_TIME) for m in rx.finditer(text)]
    for i, rx in enumerate(_PHONE_RES):
        for m in rx.finditer(text):
            s, e = (m.start(1), m.end(1)) if rx.groups else (m.start(), m.end())
            if i in (1, 2) or _phone_ok(text[s:e]):
                if sum(ch.isdigit() for ch in text[s:e]) >= 6:
                    spans.append((s, e, R_PHONE))
    spans += [(m.start(), m.end(), R_FOOTNOTE) for m in _FOOTNOTE_RE.finditer(text)]
    spans += [(m.start(), m.end(), R_PAGE) for m in _PAGE_RE.finditer(text)]
    spans += [(m.start(), m.end(), R_LABEL) for m in _LABEL_RE.finditer(text)]
    return spans


# currency, scale and unit words around a number
_CODES = ("EUR|USD|GBP|CHF|JPY|CNY|RMB|AUD|CAD|SEK|NOK|DKK|PLN|CZK|HUF|INR|BRL|ZAR|SGD|HKD|NZD|MXN|KRW|TRY|"
          "AED|SAR|ILS|RUB")
_PREFIX_CUR_RE = re.compile(r"(?:(?:US|AU|A|C|CA|NZ|HK|S|R|Mex)?\$|€|£|¥|₹|₩|₽|₺|₪|(?<![A-Za-z])(?:" + _CODES
                            + r")|(?<![A-Za-z])S?Fr\.)[ \u00a0\u202f\u2009]?$")
_CUR_AFTER_RE = re.compile(r"(?:€|\$|£|¥|₹|₩|₽|₺|₪)|(?:" + _CODES + r")(?!" + _LET + r")")
_CUR_WORD_RE = re.compile(r"(?i)(?:euros?|dollars?|pounds?(?:\s+sterling)?|francs?|franken)(?!" + _LET + r")")
_COMBO_RE = re.compile(r"(?P<s>[TkKmM])(?P<c>EUR|USD|CHF|GBP|€|\$)(?!" + _LET + r")")
_SCALE_WORD_RE = re.compile(r"(?i)(?:thousands?|millions?|billions?|trillions?|tausend|tsd\.|tsd|millionen|million|"
                            r"mio\.|mio|milliarden|milliarde|mrd\.|mrd|billionen|bio\.|bn|mn|tn|trn|mm)(?!" + _LET + r")")
_SCALE_LETTER_RE = re.compile(r"[kKmMbBT](?!" + _LET + r")")
SCALE_EXP = {"thousand": 3, "thousands": 3, "tausend": 3, "tsd": 3, "tsd.": 3, "k": 3,
             "million": 6, "millions": 6, "millionen": 6, "mio": 6, "mio.": 6, "mn": 6, "mm": 6, "m": 6,
             "billion": 9, "billions": 9, "milliarde": 9, "milliarden": 9, "mrd": 9, "mrd.": 9, "bn": 9, "b": 9,
             "trillion": 12, "trillions": 12, "billionen": 12, "bio.": 12, "tn": 12, "trn": 12, "t": 12}
_NL = r"(?!" + _LET + r")"   # the word ends here: no letter follows
_UNIT_RE = re.compile(
    r"(?i)(?P<pp>percentage[\s-]points?" + _NL + r"|prozentpunkte?" + _NL + r"|%-?punkte?" + _NL
    + r"|pp(?!" + _LET + r"|\.)|ppt" + _NL + r"|p\.p\.|pts" + _NL + r")"
    + r"|(?P<pct>%|per\s?cent" + _NL + r"|percent" + _NL + r"|pct" + _NL + r"|pc" + _NL + r"|prozent" + _NL
    + r"|v\.\s?h\.)"
    + r"|(?P<pm>‰|per\s?mille" + _NL + r"|promille" + _NL + r")"
    + r"|(?P<bp>basis[\s-]points?" + _NL + r"|basispunkte?" + _NL + r"|bps" + _NL + r"|bp" + _NL + r"|‱)"
    + r"|(?P<x>[x×](?![^\W_]))")
_UNIT_NAMES = {"pct": "%", "pp": "pp", "pm": "‰", "bp": "bp", "x": "x"}
_QUAL_RE = re.compile(r"""(?ix)(?:
   (?<![\w])(?P<approximate>approximately|approx\.?|around|about|roughly|some|circa|ca\.|c\.|nearly|almost
        |close\s+to|rund|etwa|ungefähr|zirka|knapp)
 | (?<![\w])(?P<lower>more\s+than|over|above|at\s+least|exceeding|in\s+excess\s+of|greater\s+than|upwards\s+of
        |mehr\s+als|über|mindestens)
 | (?<![\w])(?P<upper>less\s+than|fewer\s+than|under|below|up\s+to|at\s+most|no\s+more\s+than|weniger\s+als
        |unter|bis\s+zu|höchstens|maximal)
 | (?P<approx_sym>~|≈|±|\+/-)
 | (?P<lower_sym>>=|≥|>)
 | (?P<upper_sym><=|≤|<)
)[ \u00a0]*$""")

_LABEL_SCALE_RES = [
    (9, re.compile(r"(?i)(?:\bbillions?\b|\bmilliarden?\b|\bmrd\b\.?|\bbn\b|(?:€|\$|£)\s?(?:bn|b)\b"
                   r"|\b(?:EUR|USD|GBP|CHF)\s?(?:bn|b)\b|\(\s*bn\s*\))")),
    (6, re.compile(r"(?i)(?:\bmillions?\b|\bmillionen\b|\bmio\b\.?|\bmn\b|\bM(?:EUR|USD|CHF|GBP)\b|[mM]€"
                   r"|(?:€|\$|£)\s?(?:m|mn|mm)\b|\b(?:EUR|USD|GBP|CHF)\s?(?:m|mn|mm)\b|\(\s*m\s*\))")),
    (3, re.compile(r"(?i)(?:\bthousands?\b|\btausend\b|\btsd\b\.?|\bT(?:EUR|USD|CHF|GBP)\b|\bT€|[kK]€"
                   r"|(?:€|\$|£)\s?k\b|\b(?:EUR|USD|GBP|CHF)\s?k\b|\(\s*'?000s?\s*\)|\bin\s+'?000s?\b)")),
]
_LABEL_PCT_RE = re.compile(r"(?i)(?:\(\s*%|\bin\s*%|%\s*$|^\s*%|\bpercent\b|\bprozent\b|\bper\s?cent\b)")


def label_scale(label: str):
    """(exponent, matched text) for a unit statement in a label such as 'Revenue (€m)', or None."""
    best = None
    for exp, rx in _LABEL_SCALE_RES:
        m = rx.search(label or "")
        if m and (best is None or m.start() < best[2]):
            best = (exp, m.group(), m.start())
    return (best[0], best[1]) if best else None


class Num:
    """One number as written in the deliverable, and what became of it."""

    def __init__(self, seg: Segment, s: int, e: int, tok: str):
        self.seg, self.tok, self.tok_start, self.tok_end = seg, tok, s, e
        self.start, self.end = s, e
        self.mantissa = None
        self.decimals = 0
        self.evidence = None
        self.scale_exp = 0
        self.scale_word = None
        self.scale_from = None
        self.soft_scale = False
        self.unit = None
        self.unit_word = None
        self.unit_from = None
        self.currency = None
        self.negative = False
        self.sign = None
        self.qualifier = None
        self.range_role = None
        self.notes = []
        self.status = None
        self.reason = None
        self.candidates = []
        self.candidate_count = 0
        self.nearest = None
        self.context = ""
        self.written = tok
        self.marker = False
        self.secret = False

    @property
    def scale(self) -> Decimal:
        return _pow10(self.scale_exp)


def _suffix(n: Num, text: str, de_doc: bool) -> None:
    j = n.tok_end
    has_cur = bool(n.currency)

    def sp(k):
        return k + 1 if k < len(text) and text[k] in _SP else k

    k = sp(j)
    m = _COMBO_RE.match(text, k)
    if m:
        n.scale_exp = 3 if m.group("s") in "TkK" else 6
        n.scale_word, n.scale_from, n.currency = m.group(), "written", m.group("c")
        n.end = m.end()
        return
    exp, end = None, None
    m = _SCALE_WORD_RE.match(text, k)
    if m:
        word = m.group()
        low = word.lower()
        if low == "mm" and not has_cur:
            m = None
        else:
            exp = SCALE_EXP[low]
            if word.startswith("Billion") and low in ("billion", "billions") and de_doc:
                exp = 12  # German "Billion" is 10^12
            end = m.end()
            n.scale_word = word
    if exp is None and (k == j or has_cur):
        m = _SCALE_LETTER_RE.match(text, k)
        if m:
            letter = m.group()
            after = text[m.end():m.end() + 1]
            unit_like = letter in "mM" and after in ("²", "³", "/") and not has_cur
            if not unit_like and not (letter == "T" and not has_cur):
                exp, end, n.scale_word = SCALE_EXP[letter.lower()], m.end(), letter
    if exp is not None:
        n.scale_exp, n.scale_from, n.end = exp, "written", end
        k = sp(end)
        m = _CUR_AFTER_RE.match(text, k) or _CUR_WORD_RE.match(text, k)
        if m and not n.currency:
            n.currency, n.end = m.group(), m.end()
        return
    m = _CUR_AFTER_RE.match(text, k) or _CUR_WORD_RE.match(text, k)
    if m and not n.currency:
        n.currency, n.end = m.group(), m.end()
        return
    m = _UNIT_RE.match(text, k)
    if m:
        kind = m.lastgroup
        if kind == "x" and re.match(r"\s*[0-9]", text[m.end():]):
            return
        n.unit, n.unit_word, n.unit_from, n.end = _UNIT_NAMES[kind], m.group(), "written", m.end()


def _prefix(n: Num, text: str) -> None:
    end = n.tok_start
    if end >= 1 and text[end - 1] in _MINUS:
        end -= 1
    m = _PREFIX_CUR_RE.search(text, max(0, end - 8), end)
    if m and m.end() == end:
        n.currency = m.group().strip()
        n.start = m.start()


def _ranges(nums: list, text: str) -> None:
    rid = 0
    for a, b in zip(nums, nums[1:]):
        if a.mantissa is None or b.mantissa is None or a.range_role == "to":
            continue
        between = text[a.end:b.start]
        if not re.fullmatch(r"[ \u00a0]*[–—][ \u00a0]*|-|[ \u00a0]+-[ \u00a0]+|[ \u00a0]+(?:to|bis)[ \u00a0]+", between):
            continue
        rid += 1
        a.range_role, b.range_role = "from", "to"
        if a.unit is None and b.unit:
            a.unit, a.unit_word, a.unit_from = b.unit, b.unit_word, "range"
        if b.unit is None and a.unit:
            b.unit, b.unit_word, b.unit_from = a.unit, a.unit_word, "range"
        if a.scale_exp == 0 and b.scale_exp:
            a.scale_exp, a.scale_word, a.scale_from = b.scale_exp, b.scale_word, "range"
        if b.scale_exp == 0 and a.scale_exp:
            b.scale_exp, b.scale_word, b.scale_from = a.scale_exp, a.scale_word, "range"
        if a.currency and not b.currency:
            b.currency = a.currency
        if b.currency and not a.currency:
            a.currency = b.currency


def _sign(n: Num, text: str) -> None:
    if n.range_role != "to":
        for pos in (n.tok_start - 1, n.start - 1):
            if pos < 0 or pos >= len(text) or text[pos] not in _MINUS + "+":
                continue
            before = text[pos - 1] if pos > 0 else " "
            if before.isalnum() or before in ")%]":
                break
            if text[pos] != "+":
                n.negative, n.sign = True, "minus sign"
            n.start = min(n.start, pos)
            break
    ps, pe = n.start - 1, n.end
    if ps >= 0 and pe < len(text) and text[ps] == "(" and text[pe] == ")" and not n.negative:
        n.negative, n.sign = True, "parentheses"
        n.start, n.end = ps, pe + 1


def _qualifier(n: Num, text: str) -> None:
    m = _QUAL_RE.search(text, max(0, n.start - 30), n.start)
    if not m:
        return
    kind = m.lastgroup
    kind = {"approx_sym": "approximate", "lower_sym": "lower", "upper_sym": "upper"}.get(kind, kind)
    n.qualifier = (kind, re.sub(r"\s+", " ", m.group().strip()))


def _list_starts(text: str) -> set:
    starts = set()
    for ls in [0] + [i + 1 for i, c in enumerate(text) if c == "\n"]:
        p = _LINE_PREFIX_RE.match(text, ls).end()
        if _LIST_NUM_RE.match(text, p):
            starts.add(p + 1 if text[p] == "(" else p)
    return starts


def _glued(n: Num, text: str):
    i = n.tok_start - 1
    if n.tok == "000":
        before = text[i] if i >= 0 else ""
        after = text[n.tok_end:n.tok_end + 1]
        if before in "'’" or (before == "(" and after == ")") or after == "s":
            return R_UNITLABEL
    if i >= 0 and not (n.currency and n.start < n.tok_start):
        c = text[i]
        if c.isalpha() or c == "_":
            return R_CODE
        if c == "-" and i >= 1 and text[i - 1].isalpha():
            return R_CODE
        if c in "'’" and len(n.tok) == 2 and n.tok.isdigit():
            return R_YEAR
    j = n.tok_end
    if n.end == n.tok_end and j < len(text) and text[j].isalpha():
        rest = text[j:j + 16]
        if n.decimals == 0 and re.match(r"(?:st|nd|rd|th)(?!" + _LET + r")", rest):
            return R_ORDINAL
        if len(n.tok) == 4 and n.tok.isdigit() and YEAR_MIN <= int(n.tok) <= YEAR_MAX \
                and re.match(r"[EeFfAaBbPp](?!" + _LET + r")", rest):
            return R_YEAR
        letters = re.match(r"[^\W\d_]+", rest).group()
        after = j + len(letters)
        if after < len(text) and text[after].isdigit():
            return R_CODE
        if len(letters) == 1 and letters.isupper() and n.decimals == 0 and len(n.tok) <= 2:
            return R_CODE
        n.unit_word = n.unit_word or letters
    return None


def _is_year_token(n: Num) -> bool:
    return (len(n.tok) == 4 and n.tok.isdigit() and YEAR_MIN <= int(n.tok) <= YEAR_MAX)


def _exclusion(n: Num, text: str, spans: list, list_starts: set, page_line: bool, prev, min_digits: int):
    hit = None
    for s, e, reason in spans:
        if s < n.tok_end and n.tok_start < e:
            if hit is None or _SPAN_PRIORITY.get(reason, 9) < _SPAN_PRIORITY.get(hit, 9):
                hit = reason
    if hit:
        return hit
    if n.mantissa is None:
        return R_MALFORMED
    g = _glued(n, text)
    if g:
        return g
    plain = not (n.scale_word or n.unit or n.currency)
    if _is_year_token(n) and plain and n.sign != "minus sign":
        return R_YEAR
    if prev is not None and _is_year_token(prev) and len(n.tok) == 2 and n.tok.isdigit() and plain \
            and text[prev.tok_end:n.tok_start] in ("/", "-", "–", "—"):
        return R_YEAR
    if n.tok_start in list_starts and plain and n.sign != "minus sign":
        return R_LIST
    if page_line:
        return R_PAGE
    digits = sum(ch.isdigit() for ch in n.tok)
    if digits < min_digits:
        return f"fewer than {min_digits} digits (--min-digits)"
    return None


def _label_units(n: Num, seg: Segment) -> None:
    if n.scale_word or n.unit or not seg.labels:
        return
    for kind, label in seg.labels:
        if not label:
            continue
        sc = label_scale(label)
        pct = _LABEL_PCT_RE.search(label)
        if sc and not pct:
            n.scale_exp, n.scale_word = sc[0], sc[1]
            n.scale_from, n.soft_scale = f"{kind} '{_short(label, 40)}'", True
            return
        if pct and not sc:
            n.unit, n.unit_word, n.unit_from = "%", "%", f"{kind} '{_short(label, 40)}'"
            return
        if sc and pct:
            return


def _context(text: str, s: int, e: int) -> str:
    """`text` must already have its secrets hidden (hide_secrets); the cut happens afterwards."""
    a, b = max(0, s - CONTEXT_CHARS), min(len(text), e + CONTEXT_CHARS)
    if a > 0:
        sp = text.find(" ", a, s)
        a = sp + 1 if sp != -1 else a
    if b < len(text):
        sp = text.rfind(" ", e, b)
        b = sp if sp != -1 else b
    squash = lambda x: re.sub(r"\s+", " ", x)
    left, mid, right = squash(text[a:s]), squash(text[s:e]), squash(text[e:b])
    return shown(("…" if a > 0 else "") + left.lstrip() + "«" + mid + "»" + right.rstrip()
                 + ("…" if b < len(text) else ""))


def _table_context(seg: Segment, ctx: str) -> str:
    row = next((t for k, t in seg.labels if k == "row label" and t), None)
    col = next((t for k, t in seg.labels if k in ("column header", "series") and t), None)
    head = " · ".join(_short(mask(x), 30) for x in (row, col) if x)
    return f"{head}: {ctx}" if head else ctx


def _raw_number(seg: Segment, min_digits: int) -> Num:
    n = Num(seg, 0, len(seg.text), seg.text.strip())
    try:
        v = Decimal(seg.text.strip())
        if not v.is_finite():
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        n.status, n.reason = "excluded", R_MALFORMED
        return n
    v = excel15(v)
    n.negative, n.sign = (v < 0), ("minus sign" if v < 0 else None)
    n.mantissa = abs(v)
    n.decimals = _decimals(n.mantissa)
    n.written = ("-" if n.negative else "") + fmt(n.mantissa)
    n.notes.append("value cached in the chart XML")
    if seg.raw == "date":
        n.status, n.reason = "excluded", R_DATE
    elif sum(ch.isdigit() for ch in fmt(n.mantissa)) < min_digits:
        n.status, n.reason = "excluded", f"fewer than {min_digits} digits (--min-digits)"
    else:
        _label_units(n, seg)
    n.context = _table_context(seg, "«" + n.written + "»")
    return n


def _split_tokens(m) -> list:
    tok, s = m.group(), m.start()
    if read_token(tok, "en") is not None or not any(c in tok for c in "\u00a0\u202f\u2009"):
        return [(s, m.end(), tok)]
    out, pos = [], s
    for piece in re.split(r"([\u00a0\u202f\u2009])", tok):
        if piece and piece not in "\u00a0\u202f\u2009":
            out.append((pos, pos + len(piece), piece))
        pos += len(piece)
    return out


def scan_segment(seg: Segment, locale: str, min_digits: int = 1) -> list:
    """Every number in one segment, read and either kept or excluded with a reason."""
    if seg.raw:
        return [_raw_number(seg, min_digits)]
    text = seg.text
    spans = find_spans(text) + list(seg.spans)
    out = []
    for m in _SUPER_RE.finditer(text):
        n = Num(seg, m.start(), m.end(), m.group())
        before = text[m.start() - 1] if m.start() else ""
        n.status = "excluded"
        n.reason = R_EXPONENT if before.isalpha() and set(m.group()) <= set("²³") else R_FOOTNOTE
        n.marker = True
        out.append(n)
    nums = []
    for m in NUM_RE.finditer(text):
        for s, e, tok in _split_tokens(m):
            n = Num(seg, s, e, tok)
            r = read_token(tok, locale)
            if r is not None:
                n.mantissa, n.decimals, n.evidence, note = r
                if note:
                    n.notes.append(note)
                elif n.evidence and n.evidence != locale:
                    n.notes.append(f"written in {n.evidence} number format, unlike the rest of the document")
            nums.append(n)
    for n in nums:
        _prefix(n, text)
        _suffix(n, text, locale == "de")
    _ranges(nums, text)
    for n in nums:
        _sign(n, text)
        _qualifier(n, text)
    starts = _list_starts(text)
    page_line = bool(seg.lines and _PAGE_LINE_RE.match(text))
    prev = None
    for n in nums:
        n.reason = _exclusion(n, text, spans, starts, page_line, prev, min_digits)
        if n.reason:
            n.status = "excluded"
        else:
            _label_units(n, seg)
        prev = n
    out.extend(nums)
    out.sort(key=lambda x: x.start)
    hidden = hide_secrets(text)
    for n in out:
        if _HIDE in hidden[n.tok_start:n.tok_end]:
            n.secret, n.status, n.reason = True, "excluded", R_SECRET
        n.written = shown(hidden[n.start:n.end])
        ctx = _context(hidden, n.start, n.end)
        n.context = _table_context(seg, ctx) if seg.table else ctx
    return out


# ---------------------------------------------------------- locale detection
_DE_WORDS = re.compile(r"(?i)\b(?:der|die|das|und|ist|mit|für|nicht|eine?|den|dem|des|wird|wurde|auf|im|zum|zur|"
                       r"sich|auch|nach|bei|gegenüber|sowie)\b")
_EN_WORDS = re.compile(r"(?i)\b(?:the|and|is|with|for|not|of|to|was|were|by|on|this|that|from|at|which|compared)\b")
_DE_SCALE = re.compile(r"(?<=\d)[ \u00a0]?(?:Mio\.|Mrd\.|Tsd\.|Millionen|Milliarden|TEUR)")
_EN_SCALE = re.compile(r"(?<=\d)[ \u00a0]?(?:bn|mn|million|billion)(?!" + _LET + r")")


def detect_locale(segments) -> tuple:
    """'en' or 'de' for a document, with the evidence counted."""
    en = de = 0
    words_en = words_de = 0
    for seg in segments:
        if seg.raw:
            continue
        text = seg.text
        spans = find_spans(text) + list(seg.spans)
        for m in NUM_RE.finditer(text):
            if any(s < m.end() and m.start() < e for s, e, _ in spans):
                continue
            r = read_token(m.group(), "en")
            if r and r[2] == "en":
                en += 1
            elif r and r[2] == "de":
                de += 1
        de += len(_DE_SCALE.findall(text))
        en += len(_EN_SCALE.findall(text))
        words_de += len(_DE_WORDS.findall(text))
        words_en += len(_EN_WORDS.findall(text))
    if de != en:
        loc, basis = ("de" if de > en else "en"), "number format"
    elif words_de != words_en:
        loc, basis = ("de" if words_de > words_en else "en"), "language (number format undecided)"
    else:
        loc, basis = "en", "default (no evidence)"
    return loc, {"en_numbers": en, "de_numbers": de, "basis": basis}


# ----------------------------------------------------------------- readers
def _deliverable_format(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        raise InputError(f"{os.path.basename(path)}: {PDF_HELP}")
    if ext in LEGACY_HELP:
        raise InputError(f"{os.path.basename(path)}: {ext} is not supported; {LEGACY_HELP[ext]}")
    if ext in SOURCE_FORMATS:
        raise InputError(f"{os.path.basename(path)}: {ext} is a source format; the deliverable must be "
                         ".docx, .pptx, .md or .txt")
    if ext not in DELIVERABLE_FORMATS:
        raise InputError(f"{os.path.basename(path)}: unsupported file type '{ext or '(none)'}'; "
                         "use .docx, .pptx, .md or .txt")
    return DELIVERABLE_FORMATS[ext]


class Deliverable:
    def __init__(self, path, fmt_):
        self.path, self.name, self.format = path, os.path.basename(path), fmt_
        self.segments, self.links, self.warnings = [], [], []
        self.counts = {}


def read_deliverable(path: str) -> Deliverable:
    kind = _deliverable_format(path)
    if kind == "docx":
        return _Docx(path).read()
    if kind == "pptx":
        return _Pptx(path).read()
    return _read_text(path, kind)


# DrawingML text (slides, notes, SmartArt, charts in Word)
def _dml_para(p, rels, st: _Para) -> None:
    for ch in p:
        ln = _local(ch.tag)
        if ln == "r":
            rpr = _kid(ch, "rPr")
            try:
                base = int(_attr(rpr, "baseline") or 0) if rpr is not None else 0
            except ValueError:
                base = 0
            t = "".join(x.text or "" for x in _kids(ch, "t"))
            if base > 0:
                t = t.translate(_SUP)
            elif base < 0:
                t = t.translate(_SUB)
            link = _kid(rpr, "hlinkClick") if rpr is not None else None
            rid = _rattr(link, "id") if link is not None else None
            if rid and rid in rels and rels[rid].external:
                st.links.append(rels[rid].target)
            st.add(t)
        elif ln == "br":
            st.add("\n")
        elif ln == "fld":
            typ = (_attr(ch, "type") or "").lower()
            t = "".join(x.text or "" for x in _kids(ch, "t"))
            s = st.n
            st.add(t)
            if typ == "slidenum":
                st.spans.append((s, st.n, R_PAGE))
            elif typ.startswith("datetime"):
                st.spans.append((s, st.n, R_DATE))


def read_chart(pkg: Package, part: str, where: str, loc: dict, extra_labels=()) -> list:
    """Numbers in a chart part: title and axis titles as text, cached series values as values."""
    root = pkg.xml(part)
    segs = []
    chart = next((e for e in root.iter() if _local(e.tag) == "chart"), None)
    title_el = _kid(chart, "title") if chart is not None else None
    title = _short(_text_of(title_el) or "".join(v.text or "" for v in title_el.iter() if _local(v.tag) == "v")
                   if title_el is not None else "", 80)
    cloc = dict(loc, chart=where)
    if title:
        segs.append(Segment(title, f"{where} title", dict(cloc, part="title")))
    for ax in root.iter():
        if _local(ax.tag) in ("valAx", "catAx", "dateAx", "serAx"):
            t = _short(_text_of(_kid(ax, "title")), 80)
            if t:
                segs.append(Segment(t, f"{where} axis title", dict(cloc, part="axis title")))
    for dl in root.iter():
        if _local(dl.tag) == "rich":
            parent_is_title = False
            t = _text_of(dl)
            if t and t != title and not parent_is_title and not any(t == s.text for s in segs):
                segs.append(Segment(t, f"{where} label", dict(cloc, part="label")))
    for ser in root.iter():
        if _local(ser.tag) != "ser":
            continue
        tx = _kid(ser, "tx")
        name = _short("".join(v.text or "" for v in tx.iter() if _local(v.tag) == "v") if tx is not None else "", 40)
        cats = {}
        cat = _kid(ser, "cat")
        if cat is not None:
            for pt in cat.iter():
                if _local(pt.tag) == "pt" and pt.get("idx", "").isdigit():
                    v = _kid(pt, "v")
                    if v is not None and v.text is not None:
                        cats.setdefault(int(pt.get("idx")), v.text)
        for vtag in ("val", "yVal", "xVal", "bubbleSize"):
            ve = _kid(ser, vtag)
            if ve is None:
                continue
            cache = next((e for e in ve.iter() if _local(e.tag) in ("numCache", "numLit")), None)
            if cache is None:
                continue
            fc = _kid(cache, "formatCode")
            is_date = _is_date_format(fc.text if fc is not None else "")
            for pt in _kids(cache, "pt"):
                v = _kid(pt, "v")
                if v is None or v.text is None:
                    continue
                idx = int(pt.get("idx")) if (pt.get("idx") or "").isdigit() else 0
                cat_label = _short(cats.get(idx, f"point {idx + 1}"), 30)
                labels = [("series", name), ("chart title", title)] + list(extra_labels) + [("category", cat_label)]
                seg = Segment(v.text, f"{where} ({name or 'series'}, {cat_label})",
                              dict(cloc, series=name, point=cat_label), labels=labels,
                              raw="date" if is_date else "value")
                segs.append(seg)
    return segs


class _Docx:
    def __init__(self, path):
        self.pkg = Package(path, ".docx")
        self.doc = Deliverable(path, "docx")
        self.fn_numbers, self.en_numbers = {}, {}
        self.para_no = self.table_no = self.box_no = self.chart_no = 0
        self.last_para = ""
        self.note_number = None
        self.pending = []

    def read(self) -> Deliverable:
        main = self.pkg.main_part()
        if not main or not self.pkg.has(main):
            if self.pkg.has("word/document.xml"):
                main = "word/document.xml"
            else:
                raise InputError(f"{self.pkg.name}: not a Word document (word/document.xml is missing)")
        self.main = main
        self.rels = self.pkg.rels(main)
        root = self.pkg.xml(main)
        body = _kid(root, "body")
        if body is None:
            raise InputError(f"{self.pkg.name}: not a Word document (no document body)")
        self._blocks(body, "", self.rels)
        counts = {"paragraphs": self.para_no, "tables": self.table_no}
        for kind, attr, label in (("footnotes", "fn_numbers", "footnote"), ("endnotes", "en_numbers", "endnote")):
            part = next((r.target for r in self.rels.values() if r.type.endswith("/" + kind) and not r.external), None)
            if part and self.pkg.has(part):
                counts[kind] = self._notes(part, getattr(self, attr), label)
        for kind in ("header", "footer"):
            parts = sorted(r.target for r in self.rels.values() if r.type.endswith("/" + kind) and not r.external)
            for i, part in enumerate(parts, 1):
                if self.pkg.has(part):
                    root = self.pkg.xml(part)
                    self._blocks(root, f"{kind} {i}" if len(parts) > 1 else kind, self.pkg.rels(part), fixed=True)
        if self.chart_no:
            counts["charts"] = self.chart_no
        self.doc.counts = counts
        return self.doc

    def _blocks(self, container, prefix, rels, fixed=False):
        for ch in container:
            ln = _local(ch.tag)
            if ln == "p":
                st = _Para()
                self._inline(ch, st, rels)
                text = st.text()
                if text.strip():
                    if fixed:
                        where = prefix
                    else:
                        self.para_no += 1
                        where = f"{prefix}, paragraph" if prefix else f"paragraph {self.para_no}"
                    loc = {"paragraph": self.para_no} if not fixed and not prefix else {"part": prefix}
                    self.doc.segments.append(Segment(text, where, loc, st.spans))
                    self.last_para = text
                self.doc.links.extend((u, text) for u in st.links)
                self._flush(prefix or f"paragraph {self.para_no}")
            elif ln == "tbl":
                self._table(ch, prefix, rels)
            elif ln in ("sdt", "customXml", "ins", "moveTo"):
                inner = _kid(ch, "sdtContent") if ln == "sdt" else ch
                if inner is not None:
                    self._blocks(inner, prefix, rels, fixed)
            elif ln == "AlternateContent":
                choice = _kid(ch, "Choice")
                if choice is not None:
                    self._blocks(choice, prefix, rels, fixed)

    def _flush(self, near):
        while self.pending:
            kind, el, rels = self.pending.pop(0)
            if kind == "box":
                self.box_no += 1
                self._blocks(el, f"text box {self.box_no} (near {near})", rels, fixed=True)
            elif kind == "chart":
                self.chart_no += 1
                try:
                    self.doc.segments.extend(read_chart(self.pkg, el, f"chart {self.chart_no}", {"near": near},
                                                        [("caption", self.last_para)] if self.last_para else []))
                except InputError as e:
                    self.doc.warnings.append(f"chart {self.chart_no} not read: {e}")
            elif kind == "smartart":
                try:
                    root = self.pkg.xml(el)
                    for p in root.iter():
                        if _local(p.tag) == "p" and p.tag.startswith("{http://schemas.openxmlformats.org/drawingml"):
                            st = _Para()
                            _dml_para(p, {}, st)
                            if st.text().strip():
                                self.doc.segments.append(Segment(st.text(), f"SmartArt (near {near})", {"near": near}, st.spans))
                except InputError as e:
                    self.doc.warnings.append(f"SmartArt not read: {e}")

    def _table(self, tbl, prefix, rels, nested=""):
        if not nested:
            self.table_no += 1
            name = f"{prefix}, table {self.table_no}" if prefix else f"table {self.table_no}"
        else:
            name = nested
        caption = self.last_para
        header = {}
        rows = [r for r in _find_stop(tbl, {"tr"})]
        inner_no = 0
        for ri, tr in enumerate(rows, 1):
            ci = 0
            row_label = None
            for tc in _find_stop(tr, {"tc"}):
                ci += 1
                tcpr = _kid(tc, "tcPr")
                span = 1
                gs = _kid(tcpr, "gridSpan") if tcpr is not None else None
                if gs is not None and (_attr(gs, "val") or "").isdigit():
                    span = max(1, int(_attr(gs, "val")))
                vm = _kid(tcpr, "vMerge") if tcpr is not None else None
                st = _Para()
                nested_tables = []
                if vm is None or (_attr(vm, "val") or "") == "restart":
                    first = True
                    for block in tc:
                        bl = _local(block.tag)
                        if bl == "p":
                            if not first:
                                st.add("\n")
                            self._inline(block, st, rels)
                            first = False
                        elif bl == "tbl":
                            nested_tables.append(block)
                        elif bl == "sdt":
                            inner = _kid(block, "sdtContent")
                            for p in (_kids(inner, "p") if inner is not None else []):
                                if not first:
                                    st.add("\n")
                                self._inline(p, st, rels)
                                first = False
                text = st.text()
                if ri == 1:
                    header[ci] = text
                if ci == 1:
                    row_label = text
                if text.strip():
                    labels = []
                    if ci > 1 and row_label:
                        labels.append(("row label", row_label))
                    if ri > 1 and header.get(ci):
                        labels.append(("column header", header[ci]))
                    if caption:
                        labels.append(("caption", caption))
                    self.doc.segments.append(Segment(text, f"{name}, row {ri}, col {ci}",
                                                     {"table": name, "row": ri, "col": ci}, st.spans, labels, table=True))
                self.doc.links.extend((u, text) for u in st.links)
                for nt in nested_tables:
                    inner_no += 1
                    self._table(nt, prefix, rels, nested=f"{name}.{inner_no}")
                ci += span - 1
            self._flush(name)

    def _inline(self, el, st: _Para, rels):
        for ch in el:
            ln = _local(ch.tag)
            if ln == "r":
                self._run(ch, st, rels)
            elif ln == "hyperlink":
                rid = _rattr(ch, "id")
                if rid and rid in rels and rels[rid].external:
                    st.links.append(rels[rid].target)
                self._inline(ch, st, rels)
            elif ln == "fldSimple":
                s = st.n
                self._inline(ch, st, rels)
                self._field(_attr(ch, "instr") or "", s, st)
            elif ln in ("ins", "moveTo", "smartTag", "customXml", "bdo", "dir", "sdtContent"):
                self._inline(ch, st, rels)
            elif ln == "sdt":
                inner = _kid(ch, "sdtContent")
                if inner is not None:
                    self._inline(inner, st, rels)
            elif ln == "AlternateContent":
                choice = _kid(ch, "Choice")
                if choice is not None:
                    self._inline(choice, st, rels)
            elif ln in ("oMath", "oMathPara"):
                st.add(_text_of(ch))

    def _run(self, r, st: _Para, rels):
        rpr = _kid(r, "rPr")
        va = _attr(_kid(rpr, "vertAlign"), "val") if rpr is not None else None
        for ch in r:
            ln = _local(ch.tag)
            if ln == "t":
                t = ch.text or ""
                if va == "superscript":
                    t = t.translate(_SUP)
                elif va == "subscript":
                    t = t.translate(_SUB)
                st.add(t)
            elif ln == "tab":
                st.add("\t")
            elif ln in ("br", "cr"):
                st.add("\n")
            elif ln == "noBreakHyphen":
                st.add("-")
            elif ln in ("footnoteReference", "endnoteReference"):
                numbers = self.fn_numbers if ln.startswith("foot") else self.en_numbers
                nid = _attr(ch, "id")
                if nid not in numbers:
                    numbers[nid] = len(numbers) + 1
                st.add(str(numbers[nid]).translate(_SUP))
            elif ln in ("footnoteRef", "endnoteRef"):
                if self.note_number is not None:
                    st.add(str(self.note_number).translate(_SUP))
            elif ln == "fldChar":
                typ = _attr(ch, "fldCharType")
                if typ == "begin":
                    st.fields.append({"instr": "", "start": None})
                elif typ == "separate" and st.fields:
                    st.fields[-1]["start"] = st.n
                elif typ == "end" and st.fields:
                    f = st.fields.pop()
                    if f["start"] is not None:
                        self._field(f["instr"], f["start"], st)
            elif ln == "instrText":
                if st.fields:
                    st.fields[-1]["instr"] += ch.text or ""
            elif ln in ("drawing", "pict", "AlternateContent"):
                self._drawing(ch, rels)

    def _drawing(self, el, rels):
        if _local(el.tag) == "AlternateContent":
            el = _kid(el, "Choice")
            if el is None:
                return
        for found in _find_stop(el, {"txbxContent", "chart", "relIds", "Fallback"}):
            ln = _local(found.tag)
            if ln == "txbxContent":
                self.pending.append(("box", found, rels))
            elif ln == "chart":
                rid = _rattr(found, "id")
                if rid in rels and not rels[rid].external and self.pkg.has(rels[rid].target):
                    self.pending.append(("chart", rels[rid].target, rels))
            elif ln == "relIds":
                rid = _rattr(found, "dm")
                if rid in rels and not rels[rid].external and self.pkg.has(rels[rid].target):
                    self.pending.append(("smartart", rels[rid].target, rels))

    def _field(self, instr: str, s: int, st: _Para):
        code = instr.strip().split()[0].upper() if instr.strip() else ""
        reason = {"PAGE": R_PAGE, "NUMPAGES": R_PAGE, "SECTIONPAGES": R_PAGE, "PAGEREF": R_PAGE, "SECTION": R_PAGE,
                  "DATE": R_DATE, "TIME": R_DATE, "CREATEDATE": R_DATE, "SAVEDATE": R_DATE, "PRINTDATE": R_DATE,
                  "EDITTIME": R_TIME, "NOTEREF": R_FOOTNOTE, "SEQ": R_LABEL}.get(code)
        if reason and st.n > s:
            st.spans.append((s, st.n, reason))

    def _notes(self, part, numbers, label) -> int:
        root = self.pkg.xml(part)
        rels = self.pkg.rels(part)
        count = 0
        for note in root:
            if _local(note.tag) not in ("footnote", "endnote"):
                continue
            nid = _attr(note, "id")
            if (_attr(note, "type") or "normal") != "normal":
                continue
            n = numbers.get(nid)
            self.note_number = n
            st = _Para()
            first = True
            for p in _find_stop(note, {"p"}):
                if not first:
                    st.add("\n")
                self._inline(p, st, rels)
                first = False
            self.note_number = None
            text = st.text()
            where = f"{label} {n}" if n else f"{label} (id {nid}, not referenced)"
            if text.strip():
                count += 1
                self.doc.segments.append(Segment(text, where, {label: n or nid}, st.spans))
            self.doc.links.extend((u, text) for u in st.links)
            self._flush(where)
        return count


class _Pptx:
    def __init__(self, path):
        self.pkg = Package(path, ".pptx")
        self.doc = Deliverable(path, "pptx")
        self.charts = 0

    def read(self) -> Deliverable:
        main = self.pkg.main_part()
        if not main or not self.pkg.has(main):
            if self.pkg.has("ppt/presentation.xml"):
                main = "ppt/presentation.xml"
            else:
                raise InputError(f"{self.pkg.name}: not a PowerPoint file (ppt/presentation.xml is missing)")
        root = self.pkg.xml(main)
        rels = self.pkg.rels(main)
        ids = [e for e in root.iter() if _local(e.tag) == "sldId"]
        hidden = 0
        for n, sid in enumerate(ids, 1):
            rid = _rattr(sid, "id")
            rel = rels.get(rid)
            if rel is None or rel.external or not self.pkg.has(rel.target):
                self.doc.warnings.append(f"slide {n}: slide part missing; skipped")
                continue
            slide = self.pkg.xml(rel.target)
            srels = self.pkg.rels(rel.target)
            where = f"slide {n}"
            if slide.get("show") == "0":
                where += " (hidden)"
                hidden += 1
            tree = next((e for e in slide.iter() if _local(e.tag) == "spTree"), None)
            title = self._title(tree)
            if tree is not None:
                self._shapes(tree, where, srels, title, {"slide": n}, [0])
            for r in srels.values():
                if r.type.endswith("/notesSlide") and not r.external and self.pkg.has(r.target):
                    notes = self.pkg.xml(r.target)
                    ntree = next((e for e in notes.iter() if _local(e.tag) == "spTree"), None)
                    if ntree is not None:
                        self._shapes(ntree, f"slide {n} notes", self.pkg.rels(r.target), None,
                                     {"slide": n, "notes": True}, [0], notes=True)
        self.doc.counts = {"slides": len(ids)}
        if hidden:
            self.doc.counts["hidden slides"] = hidden
        if self.charts:
            self.doc.counts["charts"] = self.charts
        return self.doc

    @staticmethod
    def _ph(sp):
        for e in sp.iter():
            if _local(e.tag) == "ph":
                return e.get("type") or "body"
        return None

    def _title(self, tree):
        if tree is None:
            return None
        for sp in tree.iter():
            if _local(sp.tag) == "sp" and self._ph(sp) in ("title", "ctrTitle"):
                return _short(_text_of(sp), 80) or None
        return None

    def _shapes(self, tree, where, rels, title, loc, tables, notes=False):
        for sh in tree:
            ln = _local(sh.tag)
            if ln == "sp":
                ph = self._ph(sh)
                if notes and ph == "sldImg":
                    continue
                body = _kid(sh, "txBody")
                if body is None:
                    continue
                whole = {"sldNum": R_PAGE, "dt": R_DATE}.get(ph)
                for p in _kids(body, "p"):
                    st = _Para()
                    _dml_para(p, rels, st)
                    text = st.text()
                    if whole and text:
                        st.spans = [(0, len(text), whole)]
                    if text.strip():
                        self.doc.segments.append(Segment(text, where, dict(loc), st.spans))
                    self.doc.links.extend((u, text) for u in st.links)
            elif ln == "grpSp":
                self._shapes(sh, where, rels, title, loc, tables, notes)
            elif ln == "graphicFrame":
                for g in sh.iter():
                    gl = _local(g.tag)
                    if gl == "tbl":
                        tables[0] += 1
                        self._table(g, f"{where}, table {tables[0]}", rels, title, dict(loc, table=tables[0]))
                    elif gl == "chart":
                        rid = _rattr(g, "id")
                        rel = rels.get(rid)
                        if rel and not rel.external and self.pkg.has(rel.target):
                            self.charts += 1
                            try:
                                self.doc.segments.extend(read_chart(self.pkg, rel.target, f"{where}, chart", dict(loc),
                                                                    [("slide title", title)] if title else []))
                            except InputError as e:
                                self.doc.warnings.append(f"{where}: chart not read: {e}")
                    elif gl == "relIds":
                        rel = rels.get(_rattr(g, "dm"))
                        if rel and not rel.external and self.pkg.has(rel.target):
                            try:
                                data = self.pkg.xml(rel.target)
                                for p in data.iter():
                                    if _local(p.tag) == "p" and p.tag.startswith("{http://schemas.openxmlformats.org/drawingml"):
                                        st = _Para()
                                        _dml_para(p, {}, st)
                                        if st.text().strip():
                                            self.doc.segments.append(Segment(st.text(), f"{where}, SmartArt", dict(loc), st.spans))
                            except InputError as e:
                                self.doc.warnings.append(f"{where}: SmartArt not read: {e}")
            elif ln == "AlternateContent":
                choice = _kid(sh, "Choice")
                if choice is not None:
                    self._shapes(choice, where, rels, title, loc, tables, notes)

    def _table(self, tbl, where, rels, title, loc):
        header = {}
        for ri, tr in enumerate(_kids(tbl, "tr"), 1):
            row_label = None
            for ci, tc in enumerate(_kids(tr, "tc"), 1):
                if tc.get("hMerge") in ("1", "true") or tc.get("vMerge") in ("1", "true"):
                    continue
                st = _Para()
                body = _kid(tc, "txBody")
                for k, p in enumerate(_kids(body, "p") if body is not None else []):
                    if k:
                        st.add("\n")
                    _dml_para(p, rels, st)
                text = st.text()
                if ri == 1:
                    header[ci] = text
                if ci == 1:
                    row_label = text
                if text.strip():
                    labels = []
                    if ci > 1 and row_label:
                        labels.append(("row label", row_label))
                    if ri > 1 and header.get(ci):
                        labels.append(("column header", header[ci]))
                    if title:
                        labels.append(("slide title", title))
                    self.doc.segments.append(Segment(text, f"{where}, row {ri}, col {ci}", dict(loc, row=ri, col=ci),
                                                     st.spans, labels, table=True))
                self.doc.links.extend((u, text) for u in st.links)


_MD_SEP_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)*\|?\s*$")
_MD_FENCE_RE = re.compile(r"^\s*(```+|~~~+)")
_MD_CODE_RE = re.compile(r"(`+)(.+?)\1")
_MD_LINKTARGET_RE = re.compile(r"\]\(([^)\s]*)(?:\s+\"[^\"]*\")?\)")
_MD_COMMENT_RE = re.compile(r"<!--.*?-->")


def _decode(data: bytes, name: str) -> tuple:
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        try:
            return data.decode("utf-16"), "read as UTF-16"
        except UnicodeDecodeError:
            raise InputError(f"{name}: not valid UTF-16 text") from None
    try:
        return data.decode("utf-8-sig"), None
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace"), "not valid UTF-8; read as Windows-1252"


def _md_cells(line: str) -> list:
    """(start, end) of each cell in a Markdown table row, honouring escaped pipes."""
    cells, start, i = [], 0, 0
    s = line
    lead = len(s) - len(s.lstrip())
    if s[lead:lead + 1] == "|":
        start = lead + 1
    i = start
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            i += 2
            continue
        if s[i] == "|":
            cells.append((start, i))
            start = i + 1
        i += 1
    if s[start:].strip():
        cells.append((start, len(s)))
    return cells


def _read_text(path: str, kind: str) -> Deliverable:
    data = _read_file(path)
    if data.startswith(b"%PDF"):
        raise InputError(f"{os.path.basename(path)}: this is a PDF. {PDF_HELP}")
    if b"\x00" in data[:4096] and data[:2] not in (b"\xff\xfe", b"\xfe\xff"):
        raise InputError(f"{os.path.basename(path)}: looks like a binary file, not text")
    text, note = _decode(data, os.path.basename(path))
    doc = Deliverable(path, kind)
    if note:
        doc.warnings.append(note)
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    paged = "\f" in text
    page = 1
    in_code = False
    tables = {}
    if kind == "md":
        i = 0
        tno = 0
        while i < len(lines) - 1:
            if "|" in lines[i] and _MD_SEP_RE.match(lines[i + 1]) and not _MD_SEP_RE.match(lines[i]):
                tno += 1
                head = [lines[i][a:b].strip() for a, b in _md_cells(lines[i])]
                tables[i] = (tno, 1, head)
                j = i + 2
                r = 2
                while j < len(lines) and "|" in lines[j] and lines[j].strip():
                    tables[j] = (tno, r, head)
                    j += 1
                    r += 1
                tables[i + 1] = None
                i = j
            else:
                i += 1
    prev_nonempty = ""
    for no, line in enumerate(lines, 1):
        if "\f" in line:
            page += line.count("\f")
            line = line.replace("\f", "")
        where = f"line {no}" + (f" (page {page})" if paged else "")
        loc = {"line": no}
        if paged:
            loc["page"] = page
        spans = []
        if kind == "md":
            fence = _MD_FENCE_RE.match(line)
            if fence or in_code:
                if fence:
                    in_code = not in_code
                if line.strip():
                    doc.segments.append(Segment(line, where, loc, [(0, len(line), R_CODEBLOCK)], lines=True))
                continue
            spans += [(m.start(), m.end(), R_CODEBLOCK) for m in _MD_CODE_RE.finditer(line)]
            spans += [(m.start(1), m.end(1), R_LINK) for m in _MD_LINKTARGET_RE.finditer(line)]
            spans += [(m.start(), m.end(), R_COMMENT) for m in _MD_COMMENT_RE.finditer(line)]
            for m in _MD_LINKTARGET_RE.finditer(line):
                if m.group(1).lower().startswith(("http://", "https://")):
                    doc.links.append((m.group(1), line))
            if no - 1 in tables:
                info = tables[no - 1]
                if info is None:
                    continue
                tno, r, head = info
                cells = _md_cells(line)
                row_label = line[cells[0][0]:cells[0][1]].strip() if cells else ""
                for ci, (a, b) in enumerate(cells, 1):
                    cell = line[a:b]
                    if not cell.strip():
                        continue
                    cspans = [(s - a, e - a, why) for s, e, why in spans if s < b and a < e]
                    labels = []
                    if ci > 1 and row_label:
                        labels.append(("row label", row_label))
                    if r > 1 and ci <= len(head) and head[ci - 1]:
                        labels.append(("column header", head[ci - 1]))
                    if prev_nonempty:
                        labels.append(("caption", prev_nonempty))
                    doc.segments.append(Segment(cell, f"{where}, table {tno}, row {r}, col {ci}",
                                                dict(loc, table=tno, row=r, col=ci), cspans, labels, table=True))
                continue
        if line.strip():
            doc.segments.append(Segment(line, where, loc, spans, lines=True))
            prev_nonempty = line.strip()
    doc.counts = {"lines": len(lines)}
    if paged:
        doc.counts["pages"] = page
    return doc


# ------------------------------------------------------------------ sources
class Cell:
    """A numeric source cell."""
    __slots__ = ("file", "sheet", "ref", "cell", "row", "col", "raw", "value", "unit_exp", "unit_from", "label",
                 "from_text", "hidden", "order")

    def __init__(self, file, sheet, cell, row, col, raw, label="", from_text=False, hidden=False):
        self.file, self.sheet, self.cell, self.row, self.col = file, sheet, cell, row, col
        self.raw = raw
        self.value = raw
        self.unit_exp, self.unit_from = 0, None
        self.label = label
        self.from_text, self.hidden = from_text, hidden
        self.ref = f"{_sheet_ref(sheet)}!{cell}" if sheet is not None else f"row {row}, col {col}"
        self.order = 0

    def with_unit(self, exp: int, why: str) -> "Cell":
        c = Cell(self.file, self.sheet, self.cell, self.row, self.col, self.raw, self.label, self.from_text, self.hidden)
        c.unit_exp, c.unit_from = exp, why
        c.value = excel15(self.raw * _pow10(exp)) if exp else self.raw
        c.ref, c.order = self.ref, self.order
        return c


def _sheet_ref(name: str) -> str:
    return name if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", name or "") else "'" + (name or "").replace("'", "''") + "'"


def _col_letter(n: int) -> str:
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _col_number(letters: str) -> int:
    n = 0
    for ch in letters.upper():
        n = n * 26 + ord(ch) - 64
    return n


def _is_date_format(code: str) -> bool:
    if not code:
        return False
    c = re.sub(r'"[^"]*"|\\.|\[[^\]]*\]|_.|\*.', "", code)
    return bool(re.search(r"[dmyhsDMYHS]", c)) and c.strip().lower() != "general"


_SIMPLE_NUM_RE = re.compile(r"[-+\u2212]?[0-9][0-9.,'\u2019\u00a0\u202f\u2009]*[-]?")


def parse_cell_number(text: str, locale: str):
    """A text cell that is one number and nothing else ('1.234,5', '(3.2)', '61.3%', '€4.2bn'), as a
    Decimal in plain units, or None. Percentages become fractions, as Excel stores them."""
    s = (text or "").strip()
    if not s or len(s) > 40 or not any(ch.isdigit() for ch in s):
        return None
    if _SIMPLE_NUM_RE.fullmatch(s):
        neg = s[0] in "-\u2212" or (s.endswith("-") and len(s) > 1)
        core = s.strip("-+\u2212")
        r = read_token(core, locale)
        if r is None:
            return None
        return -r[0] if neg else r[0]
    seg = Segment(s, "")
    nums = [n for n in scan_segment(seg, locale) if not n.marker]
    if len(nums) != 1:
        return None
    n = nums[0]
    if n.mantissa is None or n.start > 0 or n.end < len(s) or n.reason in (R_MALFORMED, R_LINK, R_DATE, R_TIME, R_PHONE):
        return None
    v = n.mantissa * n.scale
    div = {"%": 100, "pp": 100, "‰": 1000, "bp": 10000}.get(n.unit)
    if div:
        v = v / div
    return -v if n.negative else v


class _Source:
    def __init__(self, path):
        self.path, self.name = path, os.path.basename(path)
        self.cells, self.warnings = [], []
        self.meta = {"path": path, "name": self.name}


def _unit_for(row_label: str, col_label: str):
    for kind, label in (("row label", row_label), ("column header", col_label)):
        sc = label_scale(label or "")
        if sc:
            return sc[0], f"{kind} '{_short(label, 40)}'"
    return None


def _finish_cells(src: _Source, raw_cells: list, source_units: list) -> None:
    for c, row_label, col_label in raw_cells:
        c.label = " | ".join(_short(mask(x), 40) for x in (row_label, col_label) if x)
        u = _unit_for(row_label, col_label)
        if u:
            src.cells.append(c.with_unit(u[0], u[1]))
            continue
        src.cells.append(c)
        for exp in source_units:
            src.cells.append(c.with_unit(exp, f"--source-unit {_UNIT_WORD[exp]}"))


_UNIT_WORD = {3: "thousand", 6: "million", 9: "billion"}


def read_xlsx(path: str, source_units: list) -> _Source:
    pkg = Package(path, ".xlsx")
    src = _Source(path)
    main = pkg.main_part()
    if not main or not pkg.has(main):
        if pkg.has("xl/workbook.xml"):
            main = "xl/workbook.xml"
        else:
            raise InputError(f"{pkg.name}: not an Excel workbook (xl/workbook.xml is missing)")
    wb = pkg.xml(main)
    rels = pkg.rels(main)
    shared = []
    ss = next((r.target for r in rels.values() if r.type.endswith("/sharedStrings") and not r.external), None)
    if ss and pkg.has(ss):
        for si in pkg.xml(ss):
            if _local(si.tag) == "si":
                shared.append("".join(t.text or "" for t in si.iter() if _local(t.tag) == "t"
                                      and not _in_phonetic(si, t)))
    date_styles = set()
    styles = next((r.target for r in rels.values() if r.type.endswith("/styles") and not r.external), None)
    if styles and pkg.has(styles):
        st = pkg.xml(styles)
        custom = {}
        for nf in st.iter():
            if _local(nf.tag) == "numFmt":
                custom[nf.get("numFmtId")] = nf.get("formatCode") or ""
        xfs = next((e for e in st if _local(e.tag) == "cellXfs"), None)
        for i, xf in enumerate(_kids(xfs, "xf") if xfs is not None else []):
            fid = xf.get("numFmtId") or "0"
            if (fid.isdigit() and int(fid) in BUILTIN_DATE_FORMATS) or _is_date_format(custom.get(fid, "")):
                date_styles.add(str(i))
    sheets = [e for e in wb.iter() if _local(e.tag) == "sheet"]
    stats = {"sheets": 0, "numeric cells": 0, "formula cells without a saved value": 0, "date cells skipped": 0,
             "error cells": 0, "numbers stored as text": 0}
    raw_cells = []
    order = 0
    for sh in sheets:
        name = sh.get("name") or "?"
        rel = rels.get(_rattr(sh, "id"))
        if rel is None or rel.external or not rel.type.endswith("/worksheet") or not pkg.has(rel.target):
            continue
        hidden = (sh.get("state") or "visible") != "visible"
        stats["sheets"] += 1
        data = pkg.read(rel.target)
        _no_dtd(data, f"{pkg.name}:{rel.target}")
        header, row_no, col_no = {}, 0, 0
        row_cells = []
        try:
            for ev, el in ET.iterparse(io.BytesIO(data), events=("start", "end")):
                ln = _local(el.tag)
                if ev == "start":
                    if ln == "row":
                        r = el.get("r")
                        row_no = int(r) if r and r.isdigit() else row_no + 1
                        col_no = 0
                        row_cells = []
                    continue
                if ln == "c":
                    ref = el.get("r")
                    m = re.fullmatch(r"([A-Za-z]{1,3})([0-9]+)", ref or "")
                    if m:
                        col_no, rno = _col_number(m.group(1)), int(m.group(2))
                    else:
                        col_no, rno = col_no + 1, row_no
                    t = el.get("t") or "n"
                    v = _kid(el, "v")
                    f = _kid(el, "f")
                    vt = v.text if v is not None else None
                    kind, val = None, None
                    if t == "s":
                        if vt is not None and vt.strip().isdigit() and int(vt) < len(shared):
                            kind, val = "text", shared[int(vt)]
                    elif t == "inlineStr":
                        kind, val = "text", _text_of(_kid(el, "is"))
                    elif t == "str":
                        kind, val = "text", vt or ""
                    elif t == "e":
                        stats["error cells"] += 1
                    elif t in ("n",):
                        if vt is None or not vt.strip():
                            if f is not None:
                                stats["formula cells without a saved value"] += 1
                        elif (el.get("s") or "0") in date_styles:
                            stats["date cells skipped"] += 1
                        else:
                            try:
                                kind, val = "num", excel15(Decimal(vt.strip()))
                            except InvalidOperation:
                                stats["error cells"] += 1
                    if kind == "text" and val is not None:
                        num = parse_cell_number(val, "en")
                        if num is not None:
                            stats["numbers stored as text"] += 1
                            kind, val = "num_text", excel15(num)
                    if kind:
                        row_cells.append((col_no, rno, kind, val))
                    el.clear()
                elif ln == "row":
                    _xlsx_row(row_cells, header, name, src, raw_cells, hidden)
                    for k, (c_, r_, kd, vl) in enumerate(row_cells):
                        pass
                    el.clear()
                    row_cells = []
        except ET.ParseError as e:
            raise InputError(f"{pkg.name}: sheet '{name}' is malformed XML ({e})") from None
        if row_cells:
            _xlsx_row(row_cells, header, name, src, raw_cells, hidden)
    for c, _, _ in raw_cells:
        order += 1
        c.order = order
    stats["numeric cells"] = len(raw_cells)
    _finish_cells(src, raw_cells, source_units)
    if stats["formula cells without a saved value"]:
        src.warnings.append(f"{pkg.name}: {stats['formula cells without a saved value']} formula cells have no saved "
                            "value (the file was written by a program that does not calculate, such as openpyxl); "
                            "open and save it in Excel or LibreOffice so the values are stored")
    src.meta.update(format="xlsx", **{k: v for k, v in stats.items() if v or k in ("sheets", "numeric cells")})
    return src


def _in_phonetic(si, t) -> bool:
    for rph in si.iter():
        if _local(rph.tag) == "rPh" and any(x is t for x in rph.iter()):
            return True
    return False


def _xlsx_row(row_cells, header, sheet, src, raw_cells, hidden):
    nums = [c for c in row_cells if c[2] in ("num", "num_text")]
    texts = [c for c in row_cells if c[2] == "text" and c[3].strip()]
    year_row = len(nums) >= 2 and all(c[3] == c[3].to_integral_value() and YEAR_MIN <= c[3] <= YEAR_MAX for c in nums)
    for col, rno, kind, val in ([] if year_row else nums):
        left = " · ".join(_short(t[3], 30) for t in texts if t[0] < col)
        cell = Cell(src.name, sheet, f"{_col_letter(col)}{rno}", rno, col, val, from_text=(kind == "num_text"),
                    hidden=hidden)
        raw_cells.append((cell, left, header.get(col, "")))
    for col, rno, kind, val in texts:
        header.setdefault(col, val.strip())
    if year_row:
        for col, rno, kind, val in nums:
            header.setdefault(col, str(int(val)))


def read_csv(path: str, source_units: list) -> _Source:
    data = _read_file(path)
    name = os.path.basename(path)
    if b"\x00" in data[:4096] and data[:2] not in (b"\xff\xfe", b"\xfe\xff"):
        raise InputError(f"{name}: looks like a binary file, not CSV text")
    text, note = _decode(data, name)
    src = _Source(path)
    if note:
        src.warnings.append(f"{name}: {note}")
    if path.lower().endswith(".tsv"):
        delim = "\t"
    else:
        sample = text[:65536]
        try:
            delim = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
        except csv.Error:
            counts = {d: sample.count(d) for d in (";", ",", "\t", "|")}
            delim = max(counts, key=counts.get) if any(counts.values()) else ","
    old = csv.field_size_limit()
    try:
        csv.field_size_limit(min(sys.maxsize, MAX_FILE_BYTES))
        rows = list(csv.reader(io.StringIO(text), delimiter=delim))
    except csv.Error as e:
        raise InputError(f"{name}: not readable as CSV ({e})") from None
    finally:
        csv.field_size_limit(old)
    en = de = 0
    for row in rows[:2000]:
        for v in row:
            v = v.strip().strip("-+\u2212()%€$£ ")
            if _SIMPLE_NUM_RE.fullmatch(v or "x"):
                r = read_token(v.rstrip("-"), "en")
                if r and r[2] == "en":
                    en += 1
                elif r and r[2] == "de":
                    de += 1
    locale = "de" if de > en else "en" if en > de else ("de" if delim == ";" else "en")
    header = {}
    raw_cells = []
    numeric = 0
    for rno, row in enumerate(rows, 1):
        cells = []
        for col, v in enumerate(row, 1):
            num = parse_cell_number(v, locale)
            if num is not None:
                cells.append((col, rno, "num", excel15(num)))
            elif v.strip():
                cells.append((col, rno, "text", v))
        nums = [c for c in cells if c[2] == "num"]
        texts = [c for c in cells if c[2] == "text"]
        year_row = bool(nums) and all(c[3] == c[3].to_integral_value() and YEAR_MIN <= c[3] <= YEAR_MAX for c in nums)
        if rno == 1 and texts and (not nums or year_row):
            for col, _, kind, val in cells:
                header[col] = val.strip() if kind == "text" else fmt(val).replace(",", "")
            continue
        for col, _, kind, val in nums:
            left = " · ".join(_short(t[3], 30) for t in texts if t[0] < col)
            c = Cell(name, None, f"{_col_letter(col)}{rno}", rno, col, val)
            raw_cells.append((c, left, header.get(col, "")))
            numeric += 1
    for i, (c, _, _) in enumerate(raw_cells, 1):
        c.order = i
    _finish_cells(src, raw_cells, source_units)
    src.meta.update(format="csv", delimiter=delim, number_format=locale, rows=len(rows), **{"numeric cells": numeric})
    return src


def read_source(path: str, source_units: list) -> _Source:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        raise InputError(f"{os.path.basename(path)}: {PDF_HELP}")
    if ext in LEGACY_HELP:
        raise InputError(f"{os.path.basename(path)}: {ext} is not supported; {LEGACY_HELP[ext]}")
    if ext not in SOURCE_FORMATS:
        raise InputError(f"{os.path.basename(path)}: unsupported source type '{ext or '(none)'}'; use .xlsx or .csv")
    return read_xlsx(path, source_units) if SOURCE_FORMATS[ext] == "xlsx" else read_csv(path, source_units)


# ----------------------------------------------------------------- matching
class Index:
    """Source cells sorted by absolute value, for range lookups."""

    def __init__(self, cells: list):
        pairs = sorted(((float(abs(c.value)), i) for i, c in enumerate(cells)), key=lambda p: p[0])
        self.keys = [k for k, _ in pairs]
        self.cells = [cells[i] for _, i in pairs]

    def between(self, lo: float, hi: float) -> list:
        return self.cells[bisect_left(self.keys, lo):bisect_right(self.keys, hi)]

    def near(self, x: float) -> list:
        i = bisect_left(self.keys, x)
        return self.cells[max(0, i - 2):i + 2]

    def __len__(self):
        return len(self.cells)


def _variants(n: Num) -> list:
    """(multiplier p, name, scale exponent) readings of a written number: t = |v| * p / 10^exp."""
    ps = [(Decimal(1), None)]
    if n.unit in ("%", "pp"):
        ps = [(Decimal(100), "percentage"), (Decimal(1), None)]
    elif n.unit == "‰":
        ps = [(Decimal(1000), "per mille"), (Decimal(1), None)]
    elif n.unit == "bp":
        ps = [(Decimal(10000), "basis points"), (Decimal(1), None)]
    scales = [n.scale_exp, 0] if (n.soft_scale and n.scale_exp) else [n.scale_exp]
    return [(p, name, s) for s in scales for p, name in ps]


def _quantum(n: Num) -> Decimal:
    if n.qualifier and n.decimals == 0:
        digits = str(int(n.mantissa)) if n.mantissa == n.mantissa.to_integral_value() else ""
        z = len(digits) - len(digits.rstrip("0")) if digits and digits != "0" else 0
        if z:
            return _pow10(z)
    return _pow10(-n.decimals)


def _rounds(t: Decimal, q: Decimal, target: Decimal):
    up = (t / q).to_integral_value(rounding=ROUND_HALF_UP) * q
    even = (t / q).to_integral_value(rounding=ROUND_HALF_EVEN) * q
    if up == target:
        return "half up"
    if even == target:
        return "half even"
    return None


def _describe(c: Cell, p: Decimal, s_exp: int, t: Decimal, rounded: Decimal, exact: bool) -> str:
    parts = [fmt(c.raw)]
    if c.unit_exp:
        parts.append(f"× {fmt(_pow10(c.unit_exp))} ({c.unit_from})")
    if p != 1:
        parts.append(f"× {fmt(p)}")
    if s_exp:
        parts.append(f"÷ {fmt(_pow10(s_exp))}")
    expr = " ".join(parts)
    if len(parts) > 1:
        expr += f" = {fmt(t)}"
    return expr if exact else f"{expr}, rounds to {fmt_places(rounded, max(0, -rounded.as_tuple().exponent))}"


def match_number(n: Num, index: Index) -> None:
    with localcontext() as ctx:
        ctx.prec = 60
        m = n.mantissa
        q = _quantum(n)
        found = {}
        for p, pname, s_exp in _variants(n):
            f = p / _pow10(s_exp)
            lo, hi = (m - q / 2) / f, (m + q / 2) / f
            for c in index.between(float(lo) * (1 - 1e-9) - 1e-300, float(hi) * (1 + 1e-9) + 1e-300):
                t = abs(c.value) * f
                mode = _rounds(t, q, m)
                if not mode:
                    continue
                if n.qualifier and n.qualifier[0] == "lower" and t < m:
                    continue
                if n.qualifier and n.qualifier[0] == "upper" and t > m:
                    continue
                key = (c.file, c.sheet, c.cell, c.unit_exp)
                if key in found:
                    continue
                exact = t == m
                how = ("percentage" if pname else "scaled" if (s_exp or c.unit_exp) else "exact" if exact else "rounded")
                rounded = (t / q).to_integral_value(rounding=ROUND_HALF_UP) * q if mode == "half up" else \
                    (t / q).to_integral_value(rounding=ROUND_HALF_EVEN) * q
                found[key] = {"cell": c, "t": t.normalize(), "how": how, "exact": exact,
                              "detail": _describe(c, p, s_exp, t, rounded, exact)
                              + ("" if mode == "half up" else " (half-even rounding)")}
        cands = list(found.values())
        same = [x for x in cands if (x["cell"].value < 0) == n.negative or x["cell"].value == 0]
        if same:
            cands = same
        else:
            for x in cands:
                x["sign_differs"] = True
                x["detail"] += "; sign differs (" + ("written negative" if n.negative else "source negative") + ")"
        # a cell reached through two unit readings is one cell
        seen, uniq = set(), []
        for x in cands:
            k = (x["cell"].file, x["cell"].sheet, x["cell"].cell)
            if k not in seen:
                seen.add(k)
                uniq.append(x)
        cands = sorted(uniq, key=lambda x: (not x["exact"], x["cell"].order))
        values = {x["t"] for x in cands}
        n.candidate_count = len(cands)
        if not cands:
            n.status = "untied"
            n.nearest = _nearest(n, index)
        elif len(values) == 1 and len(cands) <= MAX_SAME_VALUE_CELLS:
            n.status = "tied"
        else:
            n.status = "ambiguous"
            n.notes.append(f"{len(values)} different source values match" if len(values) > 1
                           else f"{len(cands)} cells hold the value (more than {MAX_SAME_VALUE_CELLS})")
        n.candidates = cands


def _nearest(n: Num, index: Index):
    if not n.mantissa or not len(index):
        return None
    best = None
    m, q = n.mantissa, _quantum(n)
    for p, pname, s_exp in _variants(n):
        f = p / _pow10(s_exp)
        for c in index.near(float(m / f)):
            t = abs(c.value) * f
            rel = abs(t - m) / m
            if rel <= NEAREST_WITHIN and (best is None or rel < best[0]):
                best = (rel, c, t, p, s_exp)
    if best is None:
        return None
    rel, c, t, p, s_exp = best
    rounded = (t / q).to_integral_value(rounding=ROUND_HALF_UP) * q
    return {"cell": c, "t": t.normalize(), "difference": float(round((t - m) / m * 100, 2)),
            "detail": _describe(c, p, s_exp, t, rounded, False)}


# -------------------------------------------------------------- link checks
class _SafeRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        problem = url_problem(newurl)
        if problem:
            raise urllib.error.URLError(f"redirected to a URL that is not requested ({problem})")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def url_problem(url: str):
    """Why a URL is not requested, or None. Only public http(s) URLs without credentials go out."""
    if len(url) > 2048:
        return "longer than 2,048 characters"
    if any(ord(ch) <= 32 or ord(ch) == 127 for ch in url):
        return "contains spaces or control characters"
    try:
        p = urllib.parse.urlsplit(url)
        port = p.port
    except ValueError:
        return "not a valid URL"
    if p.scheme.lower() not in ("http", "https"):
        return "not an http(s) URL"
    if "@" in p.netloc:
        return "carries credentials"
    host = (p.hostname or "").rstrip(".").lower()
    if not host:
        return "no host name"
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None:
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            return "private or local address"
    else:
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".lan", ".home.arpa", ".corp")) \
                or "." not in host:
            return "local host name"
        try:
            host.encode("idna")
        except UnicodeError:
            return "invalid host name"
    if port is not None and not 0 < port < 65536:
        return "invalid port"
    return None


def collect_links(doc: Deliverable) -> list:
    """URLs and DOIs written in the deliverable, in document order, each once."""
    out, seen = [], set()

    def add(kind, value, where):
        key = (kind, value.lower() if kind == "doi" else value)
        if key not in seen:
            seen.add(key)
            out.append({"kind": kind, "target": value, "where": where})

    def add_url(url, where):
        m = re.match(r"(?i)https?://(?:dx\.)?doi\.org/(10\..+)", url)
        if m and DOI_RE.fullmatch(urllib.parse.unquote(m.group(1))):
            add("doi", urllib.parse.unquote(m.group(1)), where)
        elif re.match(r"(?i)https?://", url):
            add("url", url, where)

    hyperlinks = {}
    for url, text in doc.links:
        hyperlinks.setdefault(text, []).append(url)
    for seg in doc.segments:
        if seg.raw:
            continue
        found = []
        for m in re.finditer(r"(?i)\b(?:https?://(?:dx\.)?doi\.org/|doi:\s*)?(10\.\d{4,9}/[^\s\"<>]+)", seg.text):
            doi = m.group(1).rstrip(".,;:)]}'\"»")
            if DOI_RE.fullmatch(doi):
                found.append((m.start(), "doi", doi))
        for m in re.finditer(r"(?i)\b(?:https?://|www\.)[^\s<>\"'«»]+", seg.text):
            url = _trim_url(m.group())
            if not re.match(r"(?i)https?://(?:dx\.)?doi\.org/10\.", url):
                found.append((m.start(), "url", "https://" + url if url.lower().startswith("www.") else url))
        for _, kind, value in sorted(found):
            add(kind, value, seg.where)
        for url in hyperlinks.pop(seg.text, []):
            add_url(url, seg.where)
    for urls in hyperlinks.values():
        for url in urls:
            add_url(url, "hyperlink")
    return out


def _trim_url(url: str) -> str:
    url = url.rstrip(".,;:!?'\"»")
    while url.endswith(")") and url.count(")") > url.count("("):
        url = url[:-1]
    while url.endswith("]") and url.count("]") > url.count("["):
        url = url[:-1]
    return url.rstrip(".,;:!?'\"»")


def _request(opener, url: str, method: str, timeout: float):
    req = urllib.request.Request(url, method=method, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    try:
        with opener.open(req, timeout=timeout) as r:
            body = r.read(65536) if method == "GET" else b""
            return getattr(r, "status", None) or r.getcode(), r.geturl(), body, None
    except urllib.error.HTTPError as e:
        try:
            body = e.read(65536) or b""
        except Exception:  # an error body that cannot be read changes nothing
            body = b""
        return e.code, url, body, None
    except urllib.error.URLError as e:
        return None, url, b"", _reason(e.reason)
    except (socket.timeout, TimeoutError):
        return None, url, b"", "timed out"
    except (ssl.SSLError, http.client.HTTPException, ConnectionError, OSError, ValueError, UnicodeError) as e:
        return None, url, b"", _reason(e)


def _reason(e) -> str:
    if isinstance(e, (socket.timeout, TimeoutError)):
        return "timed out"
    if isinstance(e, socket.gaierror):
        return "host name not found"
    if isinstance(e, str):
        return e
    text = str(e) or type(e).__name__
    return _short(f"{type(e).__name__}: {text}" if not isinstance(e, OSError) or not getattr(e, "strerror", None)
                  else e.strerror, 120)


def check_link(link: dict, timeout: float = LINK_TIMEOUT, opener=None) -> dict:
    opener = opener or urllib.request.build_opener(_SafeRedirects())
    shown = ("doi:" + link["target"]) if link["kind"] == "doi" else link["target"]
    out = {"kind": link["kind"], "target": mask(shown), "where": link["where"],
           "status": "could not check", "http_status": None, "detail": ""}
    if link["kind"] == "doi":
        doi = link["target"]
        if not DOI_RE.fullmatch(doi):
            out.update(status="not checked", detail="does not match the DOI pattern")
            return out
        url = "https://doi.org/api/handles/" + urllib.parse.quote(doi, safe="/:;()._-")
        code, _, body, err = _request(opener, url, "GET", timeout)
        out["http_status"] = code
        try:
            rc = json.loads(body.decode("utf-8")).get("responseCode") if body else None
        except (ValueError, UnicodeDecodeError, AttributeError):
            rc = None
        if code == 200 and rc in (1, 200):
            out.update(status="resolves", detail="DOI registered at doi.org")
        elif code == 404 or rc == 100:
            out.update(status="does not resolve", detail="DOI not registered at doi.org")
        else:
            out["detail"] = err or f"doi.org answered HTTP {code}"
        return out
    url = link["target"]
    problem = url_problem(url)
    if problem:
        out.update(status="not checked", detail=f"not requested: {problem}")
        return out
    code, final, _, err = _request(opener, url, "HEAD", timeout)
    if code is None or code >= 400:
        code, final, _, err2 = _request(opener, url, "GET", timeout)
        err = err2 if code is None else None
    out["http_status"] = code
    if code is not None and code < 400:
        host0, host1 = urllib.parse.urlsplit(url).hostname, urllib.parse.urlsplit(final or url).hostname
        out.update(status="resolves", detail=f"HTTP {code}" + (f", redirected to {host1}" if host1 and host1 != host0 else ""))
    elif code in (404, 410):
        out.update(status="does not resolve", detail=f"HTTP {code}")
    elif code is not None:
        out["detail"] = f"HTTP {code}" + {401: " (login required)", 403: " (refused automated request)",
                                          429: " (rate limited)"}.get(code, "")
    elif err == "host name not found":
        out.update(status="does not resolve", detail=err)
    else:
        out["detail"] = err or "no answer"
    return out


def check_links(links: list, timeout: float = LINK_TIMEOUT, opener=None) -> list:
    if not links:
        return []
    with ThreadPoolExecutor(max_workers=4) as ex:
        return list(ex.map(lambda l: check_link(l, timeout, opener), links))


# ------------------------------------------------------------------- report
def _num_dict(n: Num, many_sources: bool) -> dict:
    d = {"id": 0, "written": n.written, "where": n.seg.where, "location": n.seg.loc, "context": n.context,
         "status": n.status}
    if n.status == "excluded":
        d["reason"] = n.reason
    if n.mantissa is not None and not n.marker and not n.secret:
        value = n.mantissa * n.scale * (-1 if n.negative else 1)
        d["read_as"] = {
            "value": fmt(value).replace(",", ""),
            "mantissa": fmt_places(n.mantissa, n.decimals).replace(",", ""),
            "decimals": n.decimals,
            "scale": fmt(n.scale).replace(",", "") if n.scale_exp else "1",
            "scale_word": n.scale_word, "scale_from": n.scale_from if n.scale_exp else None,
            "unit": n.unit, "unit_from": n.unit_from,
            "currency": n.currency, "negative": n.negative, "sign": n.sign,
            "qualifier": ({"kind": n.qualifier[0], "word": n.qualifier[1]} if n.qualifier else None),
            "range": n.range_role, "notes": n.notes,
        }
        if n.status not in ("excluded", "extracted"):
            d["rule"] = _rule(n)
    if n.candidates:
        d["candidates"] = [_cand_dict(x, many_sources) for x in n.candidates[:MAX_CANDIDATES_SHOWN]]
        d["candidate_count"] = n.candidate_count
    if n.nearest:
        nd = _cell_dict(n.nearest["cell"], many_sources)
        nd.update(detail=n.nearest["detail"], difference_percent=n.nearest["difference"])
        d["nearest"] = nd
    return d


def _cell_dict(c: Cell, many: bool) -> dict:
    d = {"source": c.file, "ref": (f"{c.file} › " if many else "") + (c.ref if c.sheet is not None else
                                                                        f"row {c.row}, col {c.col}"),
         "sheet": c.sheet, "cell": c.cell, "row": c.row, "col": c.col, "value": fmt(c.raw).replace(",", ""),
         "label": c.label}
    if c.unit_exp:
        d["unit"] = {"scale": fmt(_pow10(c.unit_exp)).replace(",", ""), "from": c.unit_from}
    if c.from_text:
        d["stored_as_text"] = True
    if c.hidden:
        d["hidden_sheet"] = True
    return d


def _cand_dict(x: dict, many: bool) -> dict:
    d = _cell_dict(x["cell"], many)
    d.update(how=x["how"], exact=x["exact"], detail=x["detail"])
    if x.get("sign_differs"):
        d["sign_differs"] = True
    return d


def _rule(n: Num) -> str:
    q = _quantum(n)
    variants = _variants(n)
    exprs = []
    for p, _, s_exp in variants:
        e = "|v|"
        if p != 1:
            e += f" × {fmt(p)}"
        if s_exp:
            e += f" ÷ {fmt(_pow10(s_exp))}"
        exprs.append(e)
    step = f"{_decimals(q)} decimal{'s' if _decimals(q) != 1 else ''}" if q < 1 else \
        ("whole number" if q == 1 else f"nearest {fmt(q)} (written '{n.qualifier[1]}')")
    bound = ""
    if n.qualifier and n.qualifier[0] in ("lower", "upper"):
        bound = f", and {'≥' if n.qualifier[0] == 'lower' else '≤'} {fmt(n.mantissa)}"
    shown = fmt_places(n.mantissa, _decimals(q) if q < 1 else 0)
    return f"{' or '.join(exprs)} rounds to {shown} at {step}{bound}"


def _empty_summary() -> dict:
    return {"numbers": 0, "tied": 0, "untied": 0, "ambiguous": 0, "excluded": 0, "extracted": 0, "excluded_by_reason": {}}


def build_report(deliverable: str, sources=(), locale: str = "auto", min_digits: int = 1, source_units=(),
                 links: bool = False, timeout: float = LINK_TIMEOUT, opener=None, extract_only: bool = False) -> dict:
    """The whole tie-out as one JSON-ready dict. Every output format renders this."""
    report = {"tool": "tieout", "version": __version__,
              "checked_at": _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat(),
              "deliverable": {"path": deliverable, "name": os.path.basename(deliverable)},
              "sources": [], "number_format": None, "summary": _empty_summary(), "numbers": [],
              "links": None, "errors": [], "warnings": []}
    try:
        doc = read_deliverable(deliverable)
    except InputError as e:
        report["errors"].append({"file": deliverable, "error": mask(str(e))})
        return report
    report["deliverable"].update(format=doc.format, **doc.counts)
    report["warnings"] += [mask(w) for w in doc.warnings]
    if locale in ("en", "de"):
        loc, evidence = locale, {"basis": "set with --locale"}
    else:
        loc, evidence = detect_locale(doc.segments)
    report["number_format"] = dict(locale=loc, **evidence)
    nums = []
    for seg in doc.segments:
        nums.extend(scan_segment(seg, loc, min_digits))
    cells = []
    units = sorted({{"thousand": 3, "million": 6, "billion": 9}[u] for u in source_units})
    if not extract_only:
        for path in sources:
            try:
                src = read_source(path, units)
            except InputError as e:
                report["errors"].append({"file": path, "error": mask(str(e))})
                continue
            report["sources"].append(src.meta)
            report["warnings"] += [mask(w) for w in src.warnings]
            cells.extend(src.cells)
    index = Index(cells)
    readable_sources = len(report["sources"])
    for n in nums:
        if n.status == "excluded":
            continue
        if readable_sources:
            match_number(n, index)
        else:
            n.status = "extracted"
    many = readable_sources > 1
    out = []
    for i, n in enumerate(nums, 1):
        d = _num_dict(n, many)
        d["id"] = i
        out.append(d)
    report["numbers"] = out
    s = _empty_summary()
    s["numbers"] = len(out)
    for d in out:
        s[d["status"]] += 1
        if d["status"] == "excluded":
            s["excluded_by_reason"][d["reason"]] = s["excluded_by_reason"].get(d["reason"], 0) + 1
    report["summary"] = s
    if links:
        found = collect_links(doc)
        report["links"] = check_links(found, timeout, opener)
    return report


def exit_code(report: dict, strict: bool) -> int:
    """0 clean; 1 untied numbers or broken links; 2 a file could not be read (or, under --strict,
    nothing to tie against or a link that could not be checked)."""
    if report["errors"]:
        return 2
    if not strict:
        return 0
    if report["summary"]["untied"]:
        return 1
    links = report.get("links") or []
    if any(l["status"] == "does not resolve" for l in links):
        return 1
    if not report["sources"]:
        return 2
    if any(l["status"] == "could not check" for l in links):
        return 2
    return 0


# ------------------------------------------------------------------ output
def _source_text(d: dict) -> str:
    st = d["status"]
    if st == "excluded":
        return d.get("reason", "")
    if st == "extracted":
        return "not tied (no source)"
    if st == "untied":
        nr = d.get("nearest")
        if nr:
            return f"nearest {nr['ref']} = {fmt_short(Decimal(nr['value']))} ({nr['difference_percent']:+.1f}%)"
        return "no source value within ±10%"
    cands = d.get("candidates") or []
    if st == "tied":
        c = cands[0]
        more = f", {d['candidate_count'] - 1} more cell{'s' if d['candidate_count'] > 2 else ''}" \
            if d["candidate_count"] > 1 else ""
        sign = ", sign differs" if c.get("sign_differs") else ""
        return f"{c['ref']} = {fmt_short(Decimal(c['value']))} ({c['how']}{sign}){more}"
    vals = []
    for c in cands[:3]:
        vals.append(f"{c['ref']} = {fmt_short(Decimal(c['value']))}")
    return f"{d['candidate_count']} cells: " + "; ".join(vals) + ("; …" if d["candidate_count"] > 3 else "")


def _header_lines(report: dict) -> list:
    dl = report["deliverable"]
    names = ", ".join(s["name"] for s in report["sources"]) or "no source"
    lines = [f"tieout {report['version']} · {dl['name']} against {names} · {report['checked_at'][:10]}"]
    nf = report.get("number_format")
    if nf:
        if nf["basis"] == "set with --locale":
            lines.append(f"number format: {nf['locale']} (set with --locale)")
        else:
            lines.append(f"number format: {nf['locale']} ({nf['basis']}: {nf['en_numbers']} numbers written the en way, "
                         f"{nf['de_numbers']} the de way)")
    return lines


def _summary_line(report: dict) -> str:
    s = report["summary"]
    parts = [f"{s[k]} {k}" for k in ("tied", "untied", "ambiguous", "extracted") if s[k]]
    line = f"{s['numbers']} numbers: " + (", ".join(parts) if parts else "none checked")
    if s["excluded"]:
        by = ", ".join(f"{v} {k}" for k, v in sorted(s["excluded_by_reason"].items(), key=lambda kv: (-kv[1], kv[0])))
        line += f", {s['excluded']} excluded ({by})"
    return line + "."


def render_text(report: dict, explain: bool = False) -> str:
    out = _header_lines(report)
    for e in report["errors"]:
        out.append(f"could not read: {e['error']}")
    rows = [d for d in report["numbers"] if explain or d["status"] != "excluded"]
    if rows:
        widths = (3, 9, 14, 30, 64)
        head = ("#", "status", "number", "where", "source")
        out.append("")
        out.append("  ".join(h.ljust(w) for h, w in zip(head, widths)) + "  context")
        for d in rows:
            cols = (str(d["id"]), d["status"], _short(d["written"], widths[2]), _short(d["where"], widths[3]),
                    _short(_source_text(d), widths[4]))
            out.append("  ".join(c.ljust(w) for c, w in zip(cols, widths)) + "  " + _short(d["context"], 90))
            if explain:
                out.extend("      " + line for line in _explain_lines(d))
    out.append("")
    if report["deliverable"].get("format"):
        out.append(_summary_line(report))
        if not explain and report["summary"]["excluded"]:
            out.append("--explain shows how each number was read and every excluded number with its reason.")
    for w in report["warnings"]:
        out.append(f"note: {w}")
    if report.get("links") is not None:
        out.append("")
        out.append("links (--check-links; HEAD, then GET; DOIs through the doi.org handle API):" if report["links"]
                   else "links (--check-links): none found")
        for l in report["links"]:
            out.append(f"  {l['status'].ljust(16)}  {_short(l['detail'], 34).ljust(34)}  {_short(l['target'], 70)}"
                       f"  [{l['where']}]")
    return "\n".join(out) + "\n"


def _explain_lines(d: dict) -> list:
    out = []
    ra = d.get("read_as") if d["status"] != "excluded" else None
    if ra:
        bits = [f"read as {ra['mantissa']}"]
        if ra["scale"] != "1":
            bits.append(f"× {fmt(Decimal(ra['scale']))} ({ra['scale_word']!r}, {ra['scale_from']})")
        if ra["unit"]:
            bits.append(f"unit {ra['unit']} ({ra['unit_from']})")
        bits.append(f"{ra['decimals']} decimal{'s' if ra['decimals'] != 1 else ''}")
        if ra["currency"]:
            bits.append(f"currency {ra['currency']}")
        if ra["negative"]:
            bits.append(f"negative ({ra['sign']})")
        if ra["qualifier"]:
            bits.append(f"{ra['qualifier']['kind']} ('{ra['qualifier']['word']}')")
        if ra["range"]:
            bits.append(f"range {ra['range']}")
        out.append(", ".join(bits))
        out.extend(f"note: {x}" for x in ra["notes"])
    if d.get("rule"):
        out.append(f"tie rule: {d['rule']}")
    for c in d.get("candidates", []):
        out.append(f"{c['ref']} [{c['label']}]: {c['detail']} ({c['how']})" if c["label"] else
                   f"{c['ref']}: {c['detail']} ({c['how']})")
    if d.get("candidate_count", 0) > len(d.get("candidates", [])):
        out.append(f"… {d['candidate_count'] - len(d['candidates'])} more")
    if d.get("nearest"):
        nr = d["nearest"]
        out.append(f"nearest {nr['ref']}" + (f" [{nr['label']}]" if nr["label"] else "") + f": {nr['detail']}")
    return out


def _md(s: str) -> str:
    return (s or "").replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ").replace("*", "\\*")


def render_markdown(report: dict, explain: bool = False) -> str:
    dl = report["deliverable"]
    names = ", ".join(s["name"] for s in report["sources"]) or "no source"
    out = [f"## Tie-out: {_md(dl['name'])} against {_md(names)}", "",
           f"tieout {report['version']}, {report['checked_at'][:10]}. " + " · ".join(_header_lines(report)[1:]), ""]
    for e in report["errors"]:
        out.append(f"- could not read: {_md(e['error'])}")
    rows = [d for d in report["numbers"] if explain or d["status"] != "excluded"]
    if rows:
        out += ["| # | Status | Number | Where | Source | Context |", "|---|---|---|---|---|---|"]
        for d in rows:
            ctx = _md(d["context"]).replace("«", "**").replace("»", "**")
            src = _md(_source_text(d))
            if explain:
                src += "<br>" + "<br>".join(_md(x) for x in _explain_lines(d))
            out.append(f"| {d['id']} | {d['status']} | {_md(d['written'])} | {_md(d['where'])} | {src} | {ctx} |")
        out.append("")
    if dl.get("format"):
        out.append(f"**Summary:** {_md(_summary_line(report))}")
    for w in report["warnings"]:
        out.append(f"\n> Note: {_md(w)}")
    if report.get("links") is not None:
        out += ["", "| Link | Status | Where |", "|---|---|---|"]
        for l in report["links"]:
            out.append(f"| {_md(l['target'])} | {_md(l['status'] + (' (' + l['detail'] + ')' if l['detail'] else ''))} "
                       f"| {_md(l['where'])} |")
    return "\n".join(out) + "\n"


def render_json(report: dict) -> str:
    return json.dumps(report, ensure_ascii=False, indent=1) + "\n"


# --------------------------------------------------------------------- CLI
def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["mcp"]:
        import tieout_mcp
        return tieout_mcp.main()
    ap = argparse.ArgumentParser(
        prog="tieout",
        description="Tie every number in a report or deck back to the source cells it came from.",
        epilog="Exit codes: 0 all read (with --strict: every number tied); 1 --strict and a number did not tie or a "
               "link does not resolve; 2 a file could not be read (with --strict also: no source, or a link could not "
               "be checked). PDF is not supported: convert with `pdftotext -layout report.pdf report.txt`.")
    ap.add_argument("deliverable", help="the report or deck: .docx, .pptx, .md or .txt")
    ap.add_argument("sources", nargs="*", help="source workbooks: .xlsx or .csv (none: list the numbers only)")
    fmt_group = ap.add_mutually_exclusive_group()
    fmt_group.add_argument("--json", action="store_true", help="machine-readable output")
    fmt_group.add_argument("--markdown", action="store_true", help="a Markdown table")
    ap.add_argument("--explain", action="store_true",
                    help="show how each number was read, every candidate, and every excluded number with its reason")
    ap.add_argument("--strict", action="store_true", help="exit 1 if any number does not tie (see exit codes)")
    ap.add_argument("--min-digits", type=int, default=1, metavar="N",
                    help="ignore numbers written with fewer than N digits (default 1: check every number)")
    ap.add_argument("--locale", choices=("auto", "en", "de"), default="auto",
                    help="number format of the deliverable: en = 1,234.5, de = 1.234,5 (default: detect)")
    ap.add_argument("--source-unit", action="append", default=[], choices=("thousand", "million", "billion"),
                    help="also read unlabelled source numbers as thousands/millions/billions (repeatable)")
    ap.add_argument("--check-links", action="store_true",
                    help="request every URL and DOI in the deliverable (network; off by default)")
    ap.add_argument("--timeout", type=float, default=LINK_TIMEOUT, metavar="SECONDS",
                    help=f"per-request timeout for --check-links (default {LINK_TIMEOUT:g})")
    ap.add_argument("--version", action="version", version=f"tieout {__version__}")
    args = ap.parse_args(argv)
    if args.min_digits < 1:
        ap.error("--min-digits must be 1 or more")
    if not 0 < args.timeout <= 120:
        ap.error("--timeout must be between 0 and 120 seconds")
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    report = build_report(args.deliverable, args.sources, args.locale, args.min_digits, args.source_unit,
                          links=args.check_links, timeout=args.timeout)
    if args.json:
        sys.stdout.write(render_json(report))
    elif args.markdown:
        sys.stdout.write(render_markdown(report, args.explain))
    else:
        sys.stdout.write(render_text(report, args.explain))
    for e in report["errors"]:
        print(f"tieout: {e['error']}", file=sys.stderr)
    return exit_code(report, args.strict)


if __name__ == "__main__":
    raise SystemExit(main())
