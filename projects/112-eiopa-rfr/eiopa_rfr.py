#!/usr/bin/env python3
"""eiopa-rfr: EIOPA's Solvency II risk-free interest rate term structures, as published.

Every month EIOPA publishes a zip file with the risk-free interest rate (RFR)
term structures that insurers use to value technical provisions under
Solvency II. This module finds the releases on EIOPA's RFR page, downloads a
release once into a local cache, reads the spot curves and their parameters
from the release's Term_Structures workbook, and answers questions about
them, on the command line or as an MCP server on stdio.

Nothing is recomputed here. Rates are the numbers in EIOPA's workbook; the
extrapolation beyond the last liquid point is EIOPA's own (Smith-Wilson).
The only arithmetic this module does is unit conversion (decimal to percent)
and, in `compare`, the difference between two published values.

Standard library only. Python 3.9+.

  eiopa-rfr rate EUR 10 --date 2026-08       one maturity, with and without VA
  eiopa-rfr mcp                              MCP server on stdin/stdout
"""
from __future__ import annotations

import argparse
import calendar
import datetime as dt
import email.utils
import hashlib
import http.client
import io
import json
import os
import re
import socket
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import zlib
import xml.etree.ElementTree as ET
from decimal import ROUND_HALF_EVEN, Context, Decimal, DecimalException
from html.parser import HTMLParser
from pathlib import Path

__version__ = "0.1.0"

# --------------------------------------------------------------- sources
# All checked on 2026-09-24.
# The RFR page links each monthly zip through /document/download/<random id>;
# the ids cannot be derived, so links are always discovered, never built.
RFR_PAGE = "https://www.eiopa.europa.eu/tools-and-data/risk-free-interest-rate-term-structures_en"
# Releases before December 2022 are on this page, linked from the RFR page.
ARCHIVE_PAGE = ("https://www.eiopa.europa.eu/tools-and-data/risk-free-interest-rate-term-structures/"
                "risk-free-rate-previous-releases-and-preparatory-phase_en")
# The RFR page: "To get the latest monthly technical files in a structured way,
# please use the RSS feed". Used only when the page itself yields nothing.
RSS_FEED = "https://www.eiopa.europa.eu/feed/53/rss_en"
LEGAL_NOTICE = "https://www.eiopa.europa.eu/legal-notice_en"
EIOPA_HOST = "www.eiopa.europa.eu"
# The legal notice authorises reproduction "provided that the user acknowledges
# the Authority as the source" and gives this wording for it.
ACKNOWLEDGEMENT = "Source: EIOPA - European Insurance and Occupational Pensions Authority, https://eiopa.europa.eu/"
# The legal notice requires this twofold disclaimer when material is
# transformed (a derivative) and republished; `compare` output is derived.
DISCLAIMER = ("This output has been drafted using material downloaded from EIOPA website. EIOPA does not "
              "endorse this publication and in no way is liable for copyright or other intellectual property "
              "rights infringements nor for any damages caused to third-parties through this publication.")
NOT_COMPUTED = ("Values as published in EIOPA's workbook. Rates beyond the last liquid point are EIOPA's "
                "Smith-Wilson extrapolation; eiopa-rfr does not compute, interpolate or extrapolate curves.")

# ------------------------------------------------------ the tool's own choices
LISTING_MAX_AGE = 6 * 3600          # seconds a fetched release listing is reused
PAGE_TIMEOUT = 30                   # seconds per network operation, web pages
ZIP_TIMEOUT = 60                    # seconds per network operation, release zips
MAX_PAGE_BYTES = 8 * 1024 * 1024    # a listing page is about 0.3 MB
MAX_ZIP_BYTES = 64 * 1024 * 1024    # a release zip is 3 to 5 MB
MAX_PART_BYTES = 32 * 1024 * 1024   # largest workbook part read; the spot sheets are about 0.4 MB
RETRY_WAIT_CAP = 10                 # seconds; EIOPA's CDN sent "retry-after: 10.000" with its 429s
USER_AGENT = f"eiopa-rfr/{__version__} (+https://github.com/Keremozdemirra/eiopa-rfr)"
PARSER_VERSION = 1                  # bump when the parsed-release format changes

# ------------------------------------------------- workbook layout (EIOPA's)
# Sheet names and row labels as in every Term_Structures workbook checked
# (reference dates 2015-12-31, 2019-12-31, 2022-12-31, 2023-01-31,
# 2026-07-31, 2026-08-31), checked 2026-09-24. Both sheets hold plain values.
# The shocked-curve sheets and the VA sheet are Excel formulas whose stored
# results are #N/A or 0.01 in the 2026 files, so they are not read.
SHEETS = {"no_va": "RFR_spot_no_VA", "with_va": "RFR_spot_with_VA"}
# Output keys carry the unit. Units: EIOPA RFR Technical Documentation
# EIOPA-BoS-25-599 (December 2025): integer maturities 1 to 150 years (9.1.6),
# annual rates r with factor 1 + r (9.5.1), LLP in years (9.2.1), convergence
# period in years (9.4.1), UFR in percent (9.7.3, "4.2%"), alpha to six
# decimals with a floor of 0.05 (9.4.2), CRA in whole basis points (7.3.14), VA
# in whole basis points (13.1.5, 15.1.2); coupon frequency is Table 2 "SWP FREQ".
PARAMETERS = (("Coupon_freq", "coupon_freq"), ("LLP", "llp_years"), ("Convergence", "convergence_years"),
              ("UFR", "ufr_percent"), ("alpha", "alpha"), ("CRA", "cra_bp"), ("VA", "va_bp"))
UNITS = {
    "rate": "annually compounded zero-coupon spot rate, decimal, as published (0.03268 = 3.268 %)",
    "rate_percent": "the same rate in percent",
    "coupon_freq": "coupon frequency per year of the input instruments (0 on curves built from government "
                   "bond zero-coupon rates)",
    "llp_years": "last liquid point, years",
    "convergence_years": "convergence period, years from the last liquid point to the convergence point",
    "ufr_percent": "ultimate forward rate, percent",
    "alpha": "Smith-Wilson convergence speed parameter",
    "cra_bp": "credit risk adjustment, basis points",
    "va_bp": "volatility adjustment, basis points; empty on curves without VA, 'n/a' where EIOPA publishes none",
}
CURVE_ID = re.compile(r"(?P<code>[A-Z]{2,3})_(?P<day>\d{1,2})_(?P<month>\d{1,2})_(?P<year>\d{4})_(?P<instrument>[A-Z]+)"
                      r"_LLP_(?P<llp>\d+)_EXT_(?P<ext>\d+)_UFR_(?P<ufr>\d+(?:\.\d+)?)")
# Currency to curve column. Source: EIOPA-BoS-25-599 Table 2 (ISO 3166 and
# ISO 4217 per curve), checked 2026-09-24; the United Kingdom column is "GB"
# in releases up to at least 2023-01-31 and "UK" in 2026. The second group are
# curves in earlier releases (the hidden Parameters sheet of the August 2026
# workbook still maps them). BGN and HRK are not mapped: the BG and HR
# columns carry the euro curve in current releases; ask for BG or HR directly.
CURRENCY_COLUMNS = {
    "EUR": ("EUR",), "CZK": ("CZ",), "DKK": ("DK",), "HUF": ("HU",), "ISK": ("IS",), "NOK": ("NO",),
    "PLN": ("PL",), "RON": ("RO",), "SEK": ("SE",), "CHF": ("CH",), "GBP": ("UK", "GB"), "AUD": ("AU",),
    "CAD": ("CA",), "CNY": ("CN",), "COP": ("CO",), "HKD": ("HK",), "JPY": ("JP",), "TWD": ("TW",),
    "USD": ("US",),
    "RUB": ("RU",), "BRL": ("BR",), "CLP": ("CL",), "INR": ("IN",), "MYR": ("MY",), "MXN": ("MX",),
    "NZD": ("NZ",), "SGD": ("SG",), "ZAR": ("ZA",), "KRW": ("KR",), "THB": ("TH",), "TRY": ("TR",),
}
COLUMN_ALIASES = {"GB": ("UK",), "UK": ("GB",), "EU": ("EUR",)}

MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december")
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
NS_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
NS_PR = "{http://schemas.openxmlformats.org/package/2006/relationships}"
EXCEL = Context(prec=15, rounding=ROUND_HALF_EVEN)  # the 15 significant digits Excel displays
NUMBER = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")


class RfrError(Exception):
    """Anything the tool can explain to the person asking. exit_code is for the CLI."""
    exit_code = 2


class NotFound(RfrError):
    """The question cannot be answered from what EIOPA published (or was malformed)."""
    exit_code = 1


class FetchError(RfrError):
    """EIOPA could not be reached, refused, or answered with something unusable."""
    exit_code = 2

    def __init__(self, message: str, status: int | None = None, network: bool = False) -> None:
        super().__init__(message)
        self.status = status      # HTTP status, when there was one
        self.network = network    # no answer at all (DNS, refused, timeout)


class LayoutError(RfrError):
    """A file did not have the structure EIOPA's files have had since 2015."""
    exit_code = 2


# ------------------------------------------------------------------ helpers

def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


_sleep = time.sleep


def month_end(year: int, month: int) -> dt.date:
    return dt.date(year, month, calendar.monthrange(year, month)[1])


def month_label(d: dt.date) -> str:
    return f"{MONTHS[d.month - 1].capitalize()} {d.year}"


_INVISIBLE = dict.fromkeys(map(ord, "​‌‍⁠﻿"), None)


def clean_text(value, limit: int = 80) -> str:
    """Third-party text reduced to letters, digits and plain punctuation.

    File names, titles and column names come from EIOPA's pages and files and
    end up in an agent's context; nothing else of theirs is passed on.
    """
    s = unicodedata.normalize("NFC", str(value)).translate(_INVISIBLE)
    s = "".join(ch if (ch.isalnum() or ch in " .,'()&/_-") else " " for ch in s)
    return " ".join(s.split())[:limit]


def excel_decimal(text) -> Decimal | None:
    """A workbook number as Excel shows it: at most 15 significant digits.

    Excel stores 17 digits (0.032680000000000001, 3.2999999999999998). Rounding
    to 15 gives back the same double for every rate in the releases checked,
    and removes binary noise from parameters (-2.9999999999999996 is -3 bp).
    """
    if text is None:
        return None
    s = str(text).strip()
    if not NUMBER.fullmatch(s):
        return None
    try:
        d = EXCEL.plus(Decimal(s))
    except DecimalException:  # overflow on absurd exponents, which no workbook cell holds
        return None
    if not d.is_finite():
        return None
    return Decimal(0) if d.is_zero() else d.normalize()


def as_number(d: Decimal | None):
    if d is None:
        return None
    return int(d) if d == d.to_integral_value() else float(d)


def plain(d: Decimal) -> str:
    return format(d, "f")


def _cell_value(cell):
    """Parameter cell -> number, text such as 'n/a', or None for empty/error."""
    if not cell:
        return None
    kind, text = cell
    if kind == "e":
        return None
    d = excel_decimal(text)
    if d is not None:
        return as_number(d)
    t = clean_text(text, 20)
    return t or None


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=path.suffix)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _load_json(path: Path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def cache_dir() -> Path:
    """EIOPA_RFR_CACHE, else the platform's user cache directory."""
    env = os.environ.get("EIOPA_RFR_CACHE")
    if env:
        return Path(env).expanduser()
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        return (Path(base) if base else Path.home() / "AppData" / "Local") / "eiopa-rfr" / "Cache"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "eiopa-rfr"
    base = os.environ.get("XDG_CACHE_HOME")
    return (Path(base) if base else Path.home() / ".cache") / "eiopa-rfr"


def offline() -> bool:
    return os.environ.get("EIOPA_RFR_OFFLINE", "").strip().lower() in ("1", "true", "yes")


# ------------------------------------------------------------------ network

def checked_url(url: str, base: str | None = None) -> str:
    """The absolute URL if it is https on EIOPA's host, else FetchError.

    The only URLs ever requested are the fixed pages above and links found on
    them; nothing a user types is sent anywhere.
    """
    full = urllib.parse.urljoin(base, url) if base else url
    try:
        p = urllib.parse.urlsplit(full)
        port = p.port
    except ValueError:
        raise FetchError("refusing a malformed link") from None
    if (p.scheme != "https" or (p.hostname or "").lower() != EIOPA_HOST or p.username or p.password
            or port not in (None, 443)):
        raise FetchError(f"refusing to fetch a link outside https://{EIOPA_HOST}/")
    return urllib.parse.urlunsplit(("https", EIOPA_HOST, p.path, p.query, ""))


class _SameHostRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return super().redirect_request(req, fp, code, msg, headers, checked_url(newurl, req.full_url))


_OPENER = urllib.request.build_opener(_SameHostRedirect)


def _retry_wait(value) -> float:
    try:
        wait = float(str(value).strip())
    except (TypeError, ValueError):
        wait = 3.0
    return max(0.0, min(wait, RETRY_WAIT_CAP))


def _reason(reason) -> str:
    if isinstance(reason, (socket.timeout, TimeoutError)):
        return "timed out"
    text = str(getattr(reason, "strerror", None) or reason)
    return clean_text(text, 120) or type(reason).__name__


def http_get(url: str, what: str, *, timeout: float = PAGE_TIMEOUT, max_bytes: int = MAX_PAGE_BYTES) -> bytes:
    """GET from EIOPA's host, following redirects only on that host.

    One retry after a 429 or 503, waiting what Retry-After asks (at most
    RETRY_WAIT_CAP seconds): EIOPA's CDN answers bursts with 429.
    """
    url = checked_url(url)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in (1, 2):
        try:
            with _OPENER.open(request, timeout=timeout) as resp:
                declared = (resp.headers.get("Content-Length") or "").strip()
                if declared.isdigit() and int(declared) > max_bytes:
                    raise FetchError(f"{what} is larger than {max_bytes // 2 ** 20} MB; not downloaded")
                chunks, total = [], 0
                while True:
                    chunk = resp.read(1 << 16)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise FetchError(f"{what} is larger than {max_bytes // 2 ** 20} MB; not downloaded")
                    chunks.append(chunk)
                return b"".join(chunks)
        except urllib.error.HTTPError as e:
            retry_after = e.headers.get("Retry-After") if e.headers is not None else None
            try:
                e.close()
            except Exception:
                pass
            if e.code in (429, 503) and attempt == 1:
                _sleep(_retry_wait(retry_after))
                continue
            if e.code == 429:
                hint = f", Retry-After {clean_text(retry_after, 20)} s" if retry_after else ""
                raise FetchError(f"EIOPA's web server is refusing requests as too frequent (HTTP 429{hint}) "
                                 f"while fetching {what}; try again in a minute", status=429) from None
            if e.code == 404:
                raise FetchError(f"EIOPA answered HTTP 404 (not found) for {what}", status=404) from None
            raise FetchError(f"EIOPA answered HTTP {e.code} for {what}", status=e.code) from None
        except urllib.error.URLError as e:
            raise FetchError(f"could not reach {EIOPA_HOST} for {what}: {_reason(e.reason)}", network=True) from None
        except (socket.timeout, TimeoutError):
            raise FetchError(f"{EIOPA_HOST} did not answer within {timeout:g} s while sending {what}",
                             network=True) from None
        except (http.client.HTTPException, OSError) as e:
            raise FetchError(f"the connection to {EIOPA_HOST} broke while fetching {what} "
                             f"({type(e).__name__})", network=True) from None
    raise FetchError(f"no answer from {EIOPA_HOST} for {what}", network=True)  # not reached


# ----------------------------------------------------------- release pages

class _PageScan(HTMLParser):
    """Collects every link, with the section heading and file entry around it.

    EIOPA's pages list each file as a <div class="ecl-file"> block with a
    title, a date and a size; links outside such blocks are kept too, so the
    file-name rule still works if the block markup changes.
    """

    FIELDS = (("ecl-file__title", "title"), ("ecl-file__detail-meta-item", "page_date"), ("ecl-file__meta", "size"))

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.anchors: list[dict] = []
        self.section = ""
        self._heading: list[str] | None = None
        self._heading_tag = ""
        self._div_depth = 0
        self._block: dict | None = None
        self._block_depth = 0
        self._field: tuple[str, str] | None = None
        self._buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        classes = (a.get("class") or "").split()
        if tag == "div":
            self._div_depth += 1
            if "ecl-file" in classes and self._block is None:
                self._block = {"title": "", "page_date": "", "size": ""}
                self._block_depth = self._div_depth
        if tag in ("summary", "h2", "h3", "h4") and self._heading is None:
            self._heading, self._heading_tag = [], tag
        if self._block is not None and self._field is None:
            for cls, name in self.FIELDS:
                if cls in classes:
                    self._field, self._buf = (name, tag), []
                    break
        if tag == "a" and a.get("href"):
            self.anchors.append({"href": a["href"], "section": self.section, "block": self._block})

    def handle_endtag(self, tag):
        if self._field is not None and tag == self._field[1]:
            name = self._field[0]
            if self._block is not None and not self._block[name]:
                self._block[name] = " ".join("".join(self._buf).split())
            self._field = None
        if self._heading is not None and tag == self._heading_tag:
            self.section = " ".join("".join(self._heading).split())
            self._heading = None
        if tag == "div":
            if self._block is not None and self._div_depth == self._block_depth:
                self._block = None
            self._div_depth = max(0, self._div_depth - 1)

    def handle_data(self, data):
        if self._field is not None:
            self._buf.append(data)
        if self._heading is not None:
            self._heading.append(data)


_RFR_FILE = re.compile(r"eiopa_rfr_(\d{4})(\d{2})(\d{2})\.zip", re.I)
_MONTH_TITLE = re.compile(r"(" + "|".join(MONTHS) + r")\s+(\d{4})", re.I)
_MONTHLY_SECTION = re.compile(r"monthly technical information", re.I)
_PAGE_DATE = re.compile(r"(\d{1,2})\s+(" + "|".join(MONTHS) + r")\s+(\d{4})", re.I)
_SIZE = re.compile(r"\(\s*(\d+(?:\.\d+)?\s*[KMG]B)\s*-\s*ZIP\s*\)", re.I)


def _date_from_filename(name: str) -> dt.date | None:
    """EIOPA_RFR_YYYYMMDD.zip, dated at a month end (mid-month 2020 files are extraordinary)."""
    m = _RFR_FILE.fullmatch(name.strip())
    if not m:
        return None
    try:
        d = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None
    return d if d == month_end(d.year, d.month) else None


def _date_from_title(title: str) -> dt.date | None:
    """'November 2022' or 'November 2022.zip' -> 2022-11-30."""
    t = " ".join(clean_text(title, 60).split())
    if t.lower().endswith(".zip"):
        t = t[:-4].strip()
    m = _MONTH_TITLE.fullmatch(t)
    if not m:
        return None
    return month_end(int(m.group(2)), MONTHS.index(m.group(1).lower()) + 1)


def _page_date(text: str | None) -> str | None:
    m = _PAGE_DATE.fullmatch(clean_text(text or "", 40))
    if not m:
        return None
    try:
        return dt.date(int(m.group(3)), MONTHS.index(m.group(2).lower()) + 1, int(m.group(1))).isoformat()
    except ValueError:
        return None


def _link_filename(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    names = urllib.parse.parse_qs(parts.query).get("filename")
    name = names[0] if names else urllib.parse.unquote(parts.path.rsplit("/", 1)[-1])
    return name.translate(_INVISIBLE).strip()


def parse_listing_page(body: bytes, page_url: str, listed_on: str) -> tuple[list[dict], str | None]:
    """Monthly releases linked from one EIOPA page, and the previous-releases link.

    A link is a monthly release when its file name is EIOPA_RFR_<month end>.zip,
    or when it is a zip under a "Monthly technical information" heading titled
    "<Month> <YYYY>" (how releases before 2023 are named). Dual-run,
    parallel-calculation, extraordinary 2020 and financial-stability files match
    neither rule.
    """
    scan = _PageScan()
    try:
        scan.feed(body.decode("utf-8", errors="replace"))
        scan.close()
    except Exception:  # HTMLParser is lenient; anything it still raises means an unusable page
        return [], None
    releases, archive = [], None
    for a in scan.anchors:
        try:
            url = checked_url(a["href"].strip(), page_url)
        except FetchError:
            continue
        path = urllib.parse.urlsplit(url).path
        if "previous-releases" in path:
            archive = archive or url
            continue
        if not (path.startswith("/document/download/") or path.startswith("/system/files/")):
            continue
        name = _link_filename(url)
        block = a["block"] or {}
        ref = _date_from_filename(name)
        if ref is None:
            if not name.lower().endswith(".zip") or not _MONTHLY_SECTION.search(a["section"]):
                continue
            ref = _date_from_title(block.get("title") or "") or _date_from_title(name)
            if ref is None:
                continue
        size = _SIZE.search(block.get("size") or "")
        releases.append({"reference_date": ref.isoformat(), "file": clean_text(name, 80), "url": url,
                         "page_date": _page_date(block.get("page_date")),
                         "size": " ".join(size.group(1).split()) if size else None, "listed_on": listed_on})
    return releases, archive


def _reject_dtd(data: bytes, label: str) -> None:
    # Office files and RSS never need a DTD; refusing one rules out entity expansion.
    if re.search(rb"<!\s*(DOCTYPE|ENTITY)", data[:4096], re.I) or b"<!ENTITY" in data:
        raise LayoutError(f"{label} contains a DTD, which EIOPA's files do not; not read")


def parse_rss(body: bytes) -> list[dict]:
    _reject_dtd(body, "the RSS feed")
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return []
    releases = []
    for item in root.iter("item"):
        try:
            url = checked_url((item.findtext("link") or "").strip())
        except FetchError:
            continue
        name = _link_filename(url)
        ref = _date_from_filename(name)
        if ref is None:
            continue
        published = None
        try:
            published = email.utils.parsedate_to_datetime(item.findtext("pubDate") or "").date().isoformat()
        except (TypeError, ValueError, IndexError):
            pass
        releases.append({"reference_date": ref.isoformat(), "file": clean_text(name, 80), "url": url,
                         "page_date": published, "size": None, "listed_on": "rss"})
    return releases


def _merge(*groups: list[dict]) -> list[dict]:
    seen, out = set(), []
    for group in groups:
        for r in group:
            if r["reference_date"] not in seen:
                seen.add(r["reference_date"])
                out.append(r)
    return sorted(out, key=lambda r: r["reference_date"], reverse=True)


def fetch_listing() -> dict:
    """Read the RFR page and the previous-releases page (the RSS feed if the page yields nothing)."""
    warnings, sources = [], []
    main, archive_url = [], None
    try:
        main, archive_url = parse_listing_page(http_get(RFR_PAGE, "EIOPA's RFR page"), RFR_PAGE, "rfr page")
        if main:
            sources.append(RFR_PAGE)
        else:
            warnings.append("no monthly release found on EIOPA's RFR page; its layout may have changed")
    except FetchError as e:
        if e.network:
            raise  # the other pages are on the same host
        warnings.append(str(e))
    if not main:
        try:
            main = parse_rss(http_get(RSS_FEED, "EIOPA's RFR RSS feed"))
            if main:
                sources.append(RSS_FEED)
                warnings.append("release list taken from EIOPA's RSS feed instead of the RFR page")
        except RfrError as e:
            warnings.append(str(e))
    archive = []
    if main:
        url = archive_url or ARCHIVE_PAGE
        try:
            archive, _ = parse_listing_page(http_get(url, "EIOPA's previous-releases page"), url, "previous releases")
            if archive:
                sources.append(url)
        except FetchError as e:
            warnings.append(f"older releases not listed: {e}")
    releases = _merge(main, archive)
    if not releases:
        raise FetchError("no release could be read from EIOPA's pages" + (": " + "; ".join(warnings) if warnings
                                                                            else ""))
    return {"format": PARSER_VERSION, "fetched_at": _now().strftime("%Y-%m-%dT%H:%M:%SZ"), "sources": sources,
            "warnings": warnings, "releases": releases}


# ----------------------------------------------------------------- workbook

class _Workbook:
    """Just enough of an .xlsx reader for EIOPA's Term_Structures workbook."""

    def __init__(self, data: bytes, label: str) -> None:
        self.label = label
        try:
            self.zip = zipfile.ZipFile(io.BytesIO(data))
        except (zipfile.BadZipFile, ValueError, OSError):
            raise LayoutError(f"{label} is not a readable .xlsx workbook") from None
        self.sheets = self._sheets()
        self.strings = self._shared_strings()

    def part(self, path: str) -> bytes:
        try:
            info = self.zip.getinfo(path)
        except KeyError:
            raise LayoutError(f"{self.label} has no part {path}") from None
        if info.file_size > MAX_PART_BYTES:
            raise LayoutError(f"{self.label}: {path} is larger than {MAX_PART_BYTES // 2 ** 20} MB; not read")
        try:
            data = self.zip.read(info)
        except (zipfile.BadZipFile, zlib.error, EOFError, OSError, RuntimeError, NotImplementedError):
            raise LayoutError(f"{self.label}: {path} cannot be decompressed (corrupted file)") from None
        _reject_dtd(data, f"{self.label}: {path}")
        return data

    def xml(self, path: str) -> ET.Element:
        try:
            return ET.fromstring(self.part(path))
        except ET.ParseError:
            raise LayoutError(f"{self.label}: {path} is not well-formed XML") from None

    def _sheets(self) -> dict[str, str]:
        wb = self.xml("xl/workbook.xml")
        rels = self.xml("xl/_rels/workbook.xml.rels")
        targets = {r.get("Id"): r.get("Target") or "" for r in rels.iter(f"{NS_PR}Relationship")}
        out = {}
        for s in wb.iter(f"{NS}sheet"):
            target = targets.get(s.get(f"{NS_R}id"), "")
            if not target:
                continue
            path = target.lstrip("/") if target.startswith("/") else "xl/" + target
            out[s.get("name") or ""] = os.path.normpath(path).replace("\\", "/")
        return out

    def _shared_strings(self) -> list[str]:
        if "xl/sharedStrings.xml" not in self.zip.namelist():
            return []
        out = []
        for si in self.xml("xl/sharedStrings.xml").iter(f"{NS}si"):
            parts = []
            for child in si:  # plain <t>, or rich-text runs <r><t>; phonetic <rPh> runs are reading aids
                if child.tag == f"{NS}t":
                    parts.append(child.text or "")
                elif child.tag == f"{NS}r":
                    parts.extend(t.text or "" for t in child.iter(f"{NS}t"))
            out.append("".join(parts))
        return out

    def find_sheet(self, wanted: str) -> tuple[str, str]:
        if wanted in self.sheets:
            return wanted, self.sheets[wanted]
        key = re.sub(r"[^a-z0-9]", "", wanted.lower())
        for name, path in self.sheets.items():
            if re.sub(r"[^a-z0-9]", "", name.lower()) == key:
                return name, path
        present = ", ".join(clean_text(n, 40) for n in self.sheets) or "none"
        raise LayoutError(f"{self.label} has no sheet {wanted!r} (sheets: {present}); EIOPA's layout has "
                          "changed and this version of eiopa-rfr cannot read it")

    def cells(self, path: str) -> dict[tuple[int, int], tuple[str, str]]:
        grid = {}
        for c in self.xml(path).iter(f"{NS}c"):
            m = re.fullmatch(r"([A-Z]{1,3})(\d{1,7})", c.get("r") or "")
            if not m:
                continue
            kind = c.get("t") or "n"
            if kind == "inlineStr":
                grid[(int(m.group(2)), _col_number(m.group(1)))] = ("s", "".join(t.text or "" for t in c.iter(f"{NS}t")))
                continue
            v = c.find(f"{NS}v")
            if v is None or v.text is None:
                continue
            text = v.text
            if kind == "s":
                try:
                    text = self.strings[int(text)]
                except (ValueError, IndexError):
                    raise LayoutError(f"{self.label}: cell {m.group(0)} points to a missing shared string") from None
            kind = {"s": "s", "str": "s", "e": "e", "b": "b"}.get(kind, "n")
            grid[(int(m.group(2)), _col_number(m.group(1)))] = (kind, text)
        return grid


def _col_number(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n


def _col_letters(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _read_curve_sheet(wb: _Workbook, variant: str) -> dict:
    """Columns of one spot sheet: identifier, name, parameters, rates 1..N.

    Rows are located by their labels in column B, not by number.
    """
    name, path = wb.find_sheet(SHEETS[variant])
    cells = wb.cells(path)
    labels = {label for label, _ in PARAMETERS}
    label_col = next((c for (r, c), (k, v) in sorted(cells.items()) if k == "s" and v.strip() == "LLP"), None)
    if label_col is None:
        raise LayoutError(f"{wb.label}: sheet {name} has no 'LLP' label; EIOPA's layout has changed")
    rows: dict[str, int] = {}
    for (r, c), (k, v) in sorted(cells.items()):
        if c == label_col and k == "s" and v.strip() in labels:
            rows.setdefault(v.strip(), r)
    missing = [label for label, _ in PARAMETERS if label not in rows]
    if missing:
        raise LayoutError(f"{wb.label}: sheet {name} lacks the row label(s) {', '.join(missing)}; "
                          "EIOPA's layout has changed")
    last_label = max(rows.values())
    numbers = {r: excel_decimal(v) for (r, c), (k, v) in cells.items() if c == label_col and k == "n" and r > last_label}
    first = min(numbers) if numbers else 0
    count = 0
    while numbers.get(first + count) == count + 1:
        count += 1
    if count == 0:
        raise LayoutError(f"{wb.label}: sheet {name} does not list maturities 1, 2, 3, ... below the "
                          "parameter rows; EIOPA's layout has changed")
    expected = [(first + i, i + 1) for i in range(count)]
    id_row, ids = None, {}
    for r in range(min(rows.values()) - 1, 0, -1):
        ids = {c: v.strip() for (rr, c), (k, v) in cells.items()
               if rr == r and c > label_col and k == "s" and CURVE_ID.fullmatch(v.strip())}
        if ids:
            id_row = r
            break
    if id_row is None:
        raise LayoutError(f"{wb.label}: sheet {name} has no curve identifiers such as "
                          "EUR_31_08_2026_SWP_LLP_20_EXT_40_UFR_3.30 above its parameter rows")
    columns, seen = [], set()
    for c in sorted(ids):
        m = CURVE_ID.fullmatch(ids[c])
        code = m.group("code")
        if code in seen:
            continue
        seen.add(code)
        label_cell = cells.get((id_row - 1, c))
        display = clean_text(label_cell[1], 60) if label_cell and label_cell[0] == "s" else ""
        columns.append({
            "code": code, "name": display or code, "curve_id": clean_text(ids[c], 80), "col": _col_letters(c),
            "instrument": m.group("instrument"),
            "curve_date": f"{m.group('year')}-{int(m.group('month')):02d}-{int(m.group('day')):02d}",
            "params": {label: list(cells[(rows[label], c)]) if (rows[label], c) in cells else None
                       for label, _ in PARAMETERS},
            "rates": [list(cells[(r, c)]) if (r, c) in cells else None for r, _ in expected],
        })
    return {"sheet": name, "first_rate_row": first, "param_rows": rows, "columns": columns}


def _main_menu_date(wb: _Workbook) -> str | None:
    try:
        _, path = wb.find_sheet("Main_Menu")
        cell = wb.cells(path).get((1, 1))
    except LayoutError:
        return None
    text = (cell or ("", ""))[1].strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return dt.datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def parse_release(data: bytes, file_label: str, expect: dt.date | None = None) -> dict:
    """Parse a release zip (bytes) into the cached form. Raises before anything is stored."""
    if not data:
        raise FetchError(f"{file_label}: EIOPA returned an empty file")
    if data[:4] != b"PK\x03\x04":
        what = "a web page" if data.lstrip()[:1] == b"<" else "something"
        raise FetchError(f"{file_label}: EIOPA returned {what} instead of a zip file")
    try:
        outer = zipfile.ZipFile(io.BytesIO(data))
        names = outer.namelist()
    except (zipfile.BadZipFile, ValueError, OSError):
        raise LayoutError(f"{file_label} is not a readable zip file (corrupted or truncated download)") from None
    books = [n for n in names if re.search(r"_term_structures\.xlsx$", n.rsplit("/", 1)[-1], re.I)]
    if expect is not None:
        books.sort(key=lambda n: expect.strftime("%Y%m%d") not in n)
    if not books:
        listed = ", ".join(clean_text(n, 60) for n in names[:8]) or "nothing"
        raise LayoutError(f"{file_label} has no *_Term_Structures.xlsx workbook (it contains {listed})")
    book = books[0]
    info = outer.getinfo(book)
    if info.file_size > MAX_ZIP_BYTES:
        raise LayoutError(f"{file_label}: {clean_text(book)} unpacks to more than {MAX_ZIP_BYTES // 2 ** 20} MB")
    try:
        xlsx = outer.read(info)
    except (zipfile.BadZipFile, zlib.error, EOFError, OSError, RuntimeError, NotImplementedError):
        raise LayoutError(f"{file_label} is corrupted: {clean_text(book)} cannot be decompressed") from None
    wb = _Workbook(xlsx, clean_text(book.rsplit("/", 1)[-1], 80))
    curves = {variant: _read_curve_sheet(wb, variant) for variant in SHEETS}
    curve_dates = sorted({col["curve_date"] for v in curves.values() for col in v["columns"]})
    warnings = []
    if len(curve_dates) != 1:
        warnings.append(f"curve identifiers carry more than one date: {', '.join(curve_dates)}")
    reference = curve_dates[-1]
    if expect is not None and expect.isoformat() not in curve_dates:
        raise LayoutError(f"{file_label} is listed by EIOPA for {expect.isoformat()} but its curves are dated "
                          f"{', '.join(curve_dates)}; not used")
    if expect is not None:
        reference = expect.isoformat()
    book_date = re.search(r"(\d{8})_term_structures", book, re.I)
    if book_date and book_date.group(1) != reference.replace("-", ""):
        warnings.append(f"workbook name {clean_text(book)} does not match reference date {reference}")
    menu = _main_menu_date(wb)
    if menu and menu != reference:
        warnings.append(f"Main_Menu sheet shows {menu}, the curves are dated {reference}")
    return {"format": PARSER_VERSION, "reference_date": reference, "workbook": wb.label, "warnings": warnings,
            "curves": curves}


# -------------------------------------------------------------------- cache

def _release_paths(ref: dt.date) -> tuple[Path, Path]:
    base = cache_dir() / "releases"
    stem = f"rfr_{ref.strftime('%Y%m%d')}"
    return base / f"{stem}.zip", base / f"{stem}.json"


def _usable(rel: dict) -> bool:
    """The parsed form this version writes; anything else is re-read from the zip."""
    try:
        return (rel["format"] == PARSER_VERSION and isinstance(rel["reference_date"], str)
                and all(isinstance(rel["curves"][v]["columns"], list) and isinstance(rel["curves"][v]["sheet"], str)
                        and isinstance(rel["curves"][v]["first_rate_row"], int) for v in SHEETS))
    except (KeyError, TypeError):
        return False


def _cached(ref: dt.date) -> dict | None:
    zpath, jpath = _release_paths(ref)
    rel = _load_json(jpath)
    if not rel or not isinstance(rel.get("source"), dict):
        return None
    if rel.get("stale") and not offline():
        return None  # EIOPA's link changed since download: fetch it again
    if _usable(rel):
        return rel
    # written by another version of this tool, or damaged: re-read the stored zip, keep its provenance
    try:
        fresh = parse_release(zpath.read_bytes(), clean_text(rel["source"].get("file") or zpath.name), ref)
    except (OSError, RfrError):
        return None
    fresh.pop("workbook", None)
    fresh["source"] = rel["source"]
    try:
        _write_atomic(jpath, json.dumps(fresh, ensure_ascii=False).encode("utf-8"))
    except OSError:
        pass  # answering matters more than caching
    return fresh


def _cached_dates() -> list[str]:
    folder = cache_dir() / "releases"
    try:
        names = sorted(p.name for p in folder.glob("rfr_*.json"))
    except OSError:
        return []
    out = []
    for n in names:
        m = re.fullmatch(r"rfr_(\d{4})(\d{2})(\d{2})\.json", n)
        if m:
            out.append(f"{m.group(1)}-{m.group(2)}-{m.group(3)}")
    return sorted(out, reverse=True)


def store_release(data: bytes, source: dict, expect: dt.date | None) -> dict:
    """Parse, then store zip and parsed form. Nothing is written if parsing fails."""
    rel = parse_release(data, source.get("file") or "release zip", expect)
    ref = dt.date.fromisoformat(rel["reference_date"])
    zpath, jpath = _release_paths(ref)
    previous = _load_json(jpath) or {}
    digest = hashlib.sha256(data).hexdigest()
    old = (previous.get("source") or {}).get("sha256")
    if old and old != digest:
        rel["warnings"].append(f"EIOPA's file differs from the copy retrieved {previous['source'].get('retrieved')}"
                               " (EIOPA may republish technical information)")
    rel["source"] = dict(source, sha256=digest, bytes=len(data), workbook=rel.pop("workbook"))
    try:
        _write_atomic(zpath, data)
        _write_atomic(jpath, json.dumps(rel, ensure_ascii=False).encode("utf-8"))
    except OSError as e:
        rel["warnings"].append(f"not cached: cannot write {cache_dir()} ({e.strerror or type(e).__name__})")
    return rel


def _download(entry: dict) -> dict:
    ref = dt.date.fromisoformat(entry["reference_date"])
    source = {"file": entry["file"], "url": entry["url"], "retrieved": _now().date().isoformat(),
              "page_date": entry.get("page_date"), "origin": "download"}
    try:
        data = http_get(entry["url"], entry["file"], timeout=ZIP_TIMEOUT, max_bytes=MAX_ZIP_BYTES)
        return store_release(data, source, ref)
    except RfrError as e:
        if isinstance(e, LayoutError) or getattr(e, "status", None) == 404:
            # the list may point at a moved or replaced file: read EIOPA's pages again next time
            try:
                (cache_dir() / "listing.json").unlink()
            except OSError:
                pass
        raise


def import_release(path: str) -> dict:
    """Add a release zip downloaded by hand (e.g. behind a firewall) to the cache."""
    p = Path(path)
    try:
        data = p.read_bytes()
    except OSError as e:
        raise NotFound(f"cannot read {p}: {e.strerror or e}") from None
    source = {"file": clean_text(p.name, 80), "url": None, "retrieved": _now().date().isoformat(),
              "page_date": None, "origin": "import"}
    return store_release(data, source, None)


def _mark_republished(listing: dict) -> None:
    """A cached month whose EIOPA link changed is fetched again on next use."""
    for entry in listing["releases"]:
        _, jpath = _release_paths(dt.date.fromisoformat(entry["reference_date"]))
        rel = _load_json(jpath)
        if not rel or rel.get("stale"):
            continue
        old = (rel.get("source") or {}).get("url") or ""
        new = entry["url"]
        same_kind = old.split("/")[3:5] == new.split("/")[3:5] if old else False
        if old and same_kind and old != new:
            rel["stale"] = True
            _write_atomic(jpath, json.dumps(rel, ensure_ascii=False).encode("utf-8"))


def _listing_from_cache() -> dict:
    releases = []
    for iso in _cached_dates():
        rel = _load_json(_release_paths(dt.date.fromisoformat(iso))[1]) or {}
        src = rel.get("source") or {}
        releases.append({"reference_date": iso, "file": src.get("file"), "url": src.get("url"),
                         "page_date": src.get("page_date"), "size": None, "listed_on": "local cache"})
    return {"format": PARSER_VERSION, "fetched_at": None, "sources": [], "warnings": [], "releases": releases}


def get_listing(refresh: bool = False) -> dict:
    path = cache_dir() / "listing.json"
    cached = _load_json(path)
    if cached is not None and (cached.get("format") != PARSER_VERSION or not isinstance(cached.get("releases"), list)):
        cached = None
    if cached is not None:
        cached["releases"] = sorted((r for r in cached["releases"] if isinstance(r, dict)
                                     and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(r.get("reference_date")))
                                     and isinstance(r.get("file"), str) and isinstance(r.get("url"), (str, type(None)))),
                                    key=lambda r: r["reference_date"], reverse=True)
    if offline():
        listing = cached or _listing_from_cache()
        listing["warnings"] = list(listing.get("warnings") or []) + [
            "offline mode (EIOPA_RFR_OFFLINE): nothing was fetched; releases newer than the local cache may exist"]
        listing["from_cache"] = True
        return listing
    if cached and not refresh:
        try:
            fetched = dt.datetime.strptime(cached["fetched_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
            fresh_enough = 0 <= (_now() - fetched).total_seconds() < LISTING_MAX_AGE
        except (KeyError, TypeError, ValueError):
            fresh_enough = False
        if fresh_enough:
            cached["from_cache"] = True
            return cached
    try:
        listing = fetch_listing()
    except FetchError as e:
        fallback = cached or _listing_from_cache()
        if not fallback["releases"]:
            raise
        when = fallback.get("fetched_at")
        fallback["warnings"] = list(fallback.get("warnings") or []) + [
            f"{e}; using the release list {'fetched ' + when if when else 'of the local cache'}"]
        fallback["from_cache"] = True
        return fallback
    try:
        _mark_republished(listing)
        _write_atomic(path, json.dumps(listing, ensure_ascii=False, indent=1).encode("utf-8"))
    except OSError as e:
        listing["warnings"].append(f"release list not cached: cannot write {cache_dir()} "
                                   f"({e.strerror or type(e).__name__})")
    listing["from_cache"] = False
    return listing


# ---------------------------------------------------------------- resolving

def parse_date(value) -> dt.date | None:
    """'latest' -> None; 'YYYY-MM', 'YYYY-MM-DD' or 'YYYYMMDD' -> that month's end."""
    text = "latest" if value is None else str(value).strip().lower()
    if text in ("", "latest"):
        return None
    m = (re.fullmatch(r"(\d{4})-(\d{1,2})", text) or re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
         or re.fullmatch(r"(\d{4})(\d{2})(\d{2})", text))
    if not m:
        raise NotFound(f"date {clean_text(value, 30)!r} not understood; use 'latest', 'YYYY-MM' or 'YYYY-MM-DD'")
    year, month = int(m.group(1)), int(m.group(2))
    try:
        if m.lastindex == 3:
            dt.date(year, month, int(m.group(3)))
        return month_end(year, month)
    except ValueError:
        raise NotFound(f"{clean_text(value, 30)!r} is not a calendar date") from None


def _resolve(date_value) -> tuple[dict, dict]:
    """The release for a date argument, downloading it if needed, and how the date was read."""
    requested = "latest" if date_value in (None, "") else clean_text(date_value, 30)
    ref = parse_date(date_value)
    if ref is not None:
        rel = _cached(ref)
        if rel is not None:
            return rel, _date_info(requested, ref, None)
        if offline():
            raise FetchError(f"offline mode (EIOPA_RFR_OFFLINE): the release for reference date {ref.isoformat()} "
                             "is not in the local cache")
    if ref is None and offline():
        dates = _cached_dates()
        if not dates:
            raise FetchError("offline mode (EIOPA_RFR_OFFLINE) and no release in the local cache")
        ref = dt.date.fromisoformat(dates[0])
        rel = _cached(ref)
        if rel is None:
            raise FetchError(f"offline mode and the cached release {ref} cannot be read")
        return rel, _date_info(requested, ref, "newest release in the local cache (offline mode; EIOPA may have "
                                               "published newer ones)")
    listing = get_listing()
    releases = listing["releases"]
    if ref is None:
        if not releases:
            raise FetchError("EIOPA's pages list no release")
        entry = releases[0]
        ref = dt.date.fromisoformat(entry["reference_date"])
        how = (f"newest release on EIOPA's pages (list fetched {listing['fetched_at']})" if listing.get("fetched_at")
               else "newest release in the local cache")
    else:
        entry = next((r for r in releases if r["reference_date"] == ref.isoformat()), None)
        how = None
        if entry is None:
            span = (f"EIOPA's pages list releases from {releases[-1]['reference_date']} to "
                    f"{releases[0]['reference_date']}" if releases else "no release is listed")
            fetched = f" (list fetched {listing['fetched_at']})" if listing.get("fetched_at") else ""
            raise NotFound(f"no EIOPA release for reference date {ref.isoformat()} (requested {requested}); "
                           f"{span}{fetched}")
    rel = _cached(ref)
    if rel is None:
        if offline() or not entry.get("url"):
            raise FetchError(f"the release for {ref.isoformat()} is not in the local cache and cannot be "
                             "downloaded (offline mode)")
        rel = _download(entry)
    info = _date_info(requested, ref, how)
    info["listing_warnings"] = list(listing.get("warnings") or [])
    return rel, info


def _date_info(requested: str, ref: dt.date, how: str | None) -> dict:
    iso = ref.isoformat()
    if how:
        note = f"'{requested}' resolved to reference date {iso}: {how}"
    elif requested == iso:
        note = f"reference date {iso} as requested"
    else:
        note = (f"'{requested}' resolved to reference date {iso}: EIOPA dates each monthly release at the last "
                "calendar day of the month")
    return {"requested": requested, "reference_date": iso, "note": note}


def _variants(value) -> list[str]:
    v = str(value or "").strip().lower().replace("-", "_")
    if v == "both":
        return ["no_va", "with_va"]
    if v in SHEETS:
        return [v]
    raise NotFound(f"variant {clean_text(value, 20)!r} not understood; use 'no_va', 'with_va' or 'both'")


def _maturity(value) -> int:
    m = None
    if isinstance(value, bool):
        m = None
    elif isinstance(value, int):
        m = value
    elif isinstance(value, float) and value.is_integer():
        m = int(value)
    elif isinstance(value, str) and re.fullmatch(r"\s*\d{1,3}\s*", value):
        m = int(value)
    if m is None or m < 1:
        raise NotFound(f"maturity_years must be a whole number of years from 1 to 150, got "
                       f"{clean_text(value, 20)!r}; EIOPA publishes integer maturities and eiopa-rfr does not "
                       "interpolate")
    return m


def _currency_code(value) -> str:
    code = str(value or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{2,3}", code):
        raise NotFound(f"currency {clean_text(value, 20)!r} not understood; use an ISO 4217 code such as EUR "
                       "or USD, or an EIOPA country column such as DE or UK")
    return code


def _column_currency() -> dict[str, str]:
    return {col: cur for cur, cols in CURRENCY_COLUMNS.items() for col in cols}


def _available(columns: list[dict]) -> str:
    by_col = _column_currency()
    currencies = [by_col[c["code"]] for c in columns if c["code"] in by_col]
    countries = [c["code"] for c in columns if c["code"] not in by_col]
    return f"currencies {', '.join(currencies)}; country columns {', '.join(countries)}"


def _pick(rel: dict, variant: str, currency) -> dict:
    code = _currency_code(currency)
    columns = rel["curves"][variant]["columns"]
    by_code = {c["code"]: c for c in columns}
    for candidate in (code,) + COLUMN_ALIASES.get(code, ()) + CURRENCY_COLUMNS.get(code, ()):
        if candidate in by_code:
            return by_code[candidate]
    raise NotFound(f"{code} is not among the {len(columns)} curves of {rel['source'].get('file')} (reference "
                   f"date {rel['reference_date']}). Available: {_available(columns)}")


def _parameters(col: dict) -> dict:
    return {key: _cell_value(col["params"].get(label)) for label, key in PARAMETERS}


def _rate_value(col: dict, maturity: int) -> Decimal | None:
    rates = col["rates"]
    if maturity > len(rates):
        raise NotFound(f"maturity {maturity} years is beyond the {len(rates)} years EIOPA publishes")
    cell = rates[maturity - 1]
    return excel_decimal(cell[1]) if cell and cell[0] == "n" else None


def _rate(rel: dict, variant: str, col: dict, maturity: int) -> dict:
    value = _rate_value(col, maturity)
    sheet = rel["curves"][variant]
    out = {"rate": as_number(value), "rate_percent": as_number((value * 100).normalize()) if value is not None else None,
           "cell": f"{sheet['sheet']}!{col['col']}{sheet['first_rate_row'] + maturity - 1}"}
    if value is None:
        cell = col["rates"][maturity - 1]
        out["note"] = f"the cell holds {clean_text(cell[1], 20) if cell else 'nothing'}, not a number"
    return out


def attribution(rel: dict) -> str:
    src = rel.get("source") or {}
    when = (f"imported from a local copy {src.get('retrieved')}" if src.get("origin") == "import"
            else f"retrieved {src.get('retrieved')}")
    return f"{ACKNOWLEDGEMENT}, risk-free interest rate term structures, {src.get('file')}, {when}"


def _source(rel: dict) -> dict:
    src = rel.get("source") or {}
    return {k: src.get(k) for k in ("file", "workbook", "url", "retrieved", "page_date", "sha256", "origin")}


def _column_info(col: dict) -> dict:
    return {"code": col["code"], "name": col["name"], "curve_id": col["curve_id"], "instrument": col["instrument"]}


def _finish(out: dict, rel: dict, info: dict) -> dict:
    warnings = list(rel.get("warnings") or []) + list(info.pop("listing_warnings", []) or [])
    out["source"] = _source(rel)
    out["attribution"] = attribution(rel)
    if warnings:
        out["warnings"] = warnings
    return out


# -------------------------------------------------------------------- tools

def list_releases(refresh=False) -> dict:
    listing = get_listing(refresh=refresh is True or str(refresh).strip().lower() in ("true", "1", "yes"))
    cached = set(_cached_dates())
    releases = []
    for r in listing["releases"]:
        ref = dt.date.fromisoformat(r["reference_date"])
        releases.append({"reference_date": r["reference_date"], "label": month_label(ref), "file": r["file"],
                         "page_date": r.get("page_date"), "size": r.get("size"),
                         "cached": r["reference_date"] in cached, "url": r.get("url")})
    fetched = listing.get("fetched_at")
    out = {
        "count": len(releases),
        "latest": releases[0]["reference_date"] if releases else None,
        "earliest": releases[-1]["reference_date"] if releases else None,
        "releases": releases,
        "listing": {"fetched_at": fetched, "from_cache": bool(listing.get("from_cache")),
                    "sources": listing.get("sources") or []},
        "notes": ["reference_date is the last calendar day of the month the curves describe",
                  "page_date is the date EIOPA's page shows next to the file; for entries moved to the current "
                  "site it is the move date (2023-01-31), not the publication date",
                  "not listed: extraordinary 2020 calculations, dual-run and parallel-calculation files, "
                  "financial-stability (FSR) shifted curves, background material"],
        "attribution": (f"{ACKNOWLEDGEMENT}, risk-free interest rate term structures, release list, "
                        + (f"retrieved {fetched[:10]}" if fetched else "from the local cache")),
    }
    if listing.get("warnings"):
        out["warnings"] = listing["warnings"]
    return out


def get_curve(currency, date="latest", variant="no_va") -> dict:
    variants = _variants(variant or "no_va")
    rel, info = _resolve(date)
    out = {"reference_date": rel["reference_date"], "date": info}
    for v in variants:
        col = _pick(rel, v, currency)
        sheet = rel["curves"][v]
        out.setdefault("curve", _column_info(col))
        rates = []
        for i in range(len(col["rates"])):
            r = _rate(rel, v, col, i + 1)
            rates.append({"maturity_years": i + 1, "rate": r["rate"]})
        out[v] = {"sheet": sheet["sheet"], "column": col["col"], "parameters": _parameters(col), "rates": rates}
    out["units"] = {k: UNITS[k] for k in ("rate",) + tuple(key for _, key in PARAMETERS)}
    out["note"] = NOT_COMPUTED
    return _finish(out, rel, info)


def get_rate(currency, maturity_years, date="latest", variant="both") -> dict:
    variants = _variants(variant or "both")
    maturity = _maturity(maturity_years)
    rel, info = _resolve(date)
    out = {"maturity_years": maturity, "reference_date": rel["reference_date"], "date": info}
    for v in variants:
        col = _pick(rel, v, currency)
        out.setdefault("curve", _column_info(col))
        params = _parameters(col)
        block = _rate(rel, v, col, maturity)
        llp = params.get("llp_years")
        if isinstance(llp, (int, float)):
            block["beyond_last_liquid_point"] = maturity > llp
        block["parameters"] = params
        out[v] = block
    out["units"] = {k: UNITS[k] for k in ("rate", "rate_percent") + tuple(key for _, key in PARAMETERS)}
    out["note"] = NOT_COMPUTED
    return _finish(out, rel, info)


def get_parameters(currency, date="latest") -> dict:
    rel, info = _resolve(date)
    out = {"reference_date": rel["reference_date"], "date": info}
    if str(currency or "").strip().lower() == "all":
        rows = []
        with_va = {c["code"]: c for c in rel["curves"]["with_va"]["columns"]}
        for col in rel["curves"]["no_va"]["columns"]:
            row = _column_info(col)
            row["no_va"] = _parameters(col)
            if col["code"] in with_va:
                row["with_va"] = _parameters(with_va[col["code"]])
            rows.append(row)
        out["curves"] = rows
    else:
        for v in SHEETS:
            col = _pick(rel, v, currency)
            out.setdefault("curve", _column_info(col))
            out[v] = _parameters(col)
    out["units"] = {key: UNITS[key] for _, key in PARAMETERS}
    return _finish(out, rel, info)


def compare(currency, maturity_years, date_a, date_b, variant="both") -> dict:
    variants = _variants(variant or "both")
    maturity = _maturity(maturity_years)
    rel_a, info_a = _resolve(date_a)
    rel_b, info_b = _resolve(date_b)
    out = {"maturity_years": maturity, "a": info_a, "b": info_b}
    for v in variants:
        col_a, col_b = _pick(rel_a, v, currency), _pick(rel_b, v, currency)
        out.setdefault("curve", {"a": _column_info(col_a), "b": _column_info(col_b)})
        block = {"a": _rate(rel_a, v, col_a, maturity), "b": _rate(rel_b, v, col_b, maturity)}
        va, vb = _rate_value(col_a, maturity), _rate_value(col_b, maturity)
        if va is not None and vb is not None:
            diff = vb - va
            block["change"] = {"decimal": as_number(diff.normalize() if diff else Decimal(0)),
                               "bp": as_number((diff * 10000).normalize() if diff else Decimal(0))}
        else:
            block["change"] = None
        pa, pb = _parameters(col_a), _parameters(col_b)
        block["parameters_changed"] = {k: {"a": pa[k], "b": pb[k]} for k in pa if pa[k] != pb[k]}
        out[v] = block
    out["derived"] = ("change = rate at date b minus rate at date a, computed by eiopa-rfr from the two "
                      "published values with exact decimal arithmetic; bp = change x 10,000")
    out["disclaimer"] = DISCLAIMER
    out["note"] = NOT_COMPUTED
    warnings = list(rel_a.get("warnings") or []) + list(rel_b.get("warnings") or [])
    warnings += list(info_a.pop("listing_warnings", []) or []) + list(info_b.pop("listing_warnings", []) or [])
    out["sources"] = [_source(rel_a), _source(rel_b)]
    out["attribution"] = [attribution(rel_a), attribution(rel_b)]
    if warnings:
        out["warnings"] = list(dict.fromkeys(warnings))
    return out


# ---------------------------------------------------------------------- MCP

PROTOCOL = "2025-06-18"
_DATE_PROP = {"type": "string",
              "description": "'latest' (default), 'YYYY-MM' or 'YYYY-MM-DD'. EIOPA dates each release at the last "
                             "calendar day of the month; any day of a month resolves to that month's release, and the "
                             "answer says which reference date was used."}
_CURRENCY_PROP = {"type": "string",
                  "description": "ISO 4217 currency code (EUR, USD, GBP, CHF, JPY, SEK, ...) or an EIOPA country "
                                 "column code (DE, FR, IT, UK, LI, ...) for a country's own curve, which can differ "
                                 "from the currency curve when VA is applied."}
_MATURITY_PROP = {"type": "integer", "minimum": 1, "maximum": 150,
                  "description": "Whole years, 1 to 150. No interpolation."}
_PARAMS_TEXT = ("Parameters: coupon_freq, llp_years (last liquid point), convergence_years, ufr_percent (ultimate "
                "forward rate, percent), alpha (Smith-Wilson convergence speed), cra_bp (credit risk adjustment, "
                "basis points), va_bp (volatility adjustment, basis points; null without VA, 'n/a' where EIOPA "
                "publishes none).")
_CACHE_TEXT = (" The first use of a month downloads EIOPA's release zip (3 to 5 MB) once; later calls read the local "
               "cache.")
TOOLS = [
    {"name": "list_releases",
     "description": "List EIOPA's monthly Solvency II risk-free interest rate (RFR) term structure releases, found on "
                    "EIOPA's RFR page and its previous-releases page (reference dates from 2015-12-31). Returns "
                    "reference dates (month ends), EIOPA's file names, the date shown on the page, file size and "
                    "whether the release is already in the local cache. The list is reused for 6 hours unless "
                    "refresh is true. Extraordinary 2020 calculations, dual-run, parallel-calculation and "
                    "financial-stability files are not listed.",
     "inputSchema": {"type": "object", "properties": {
         "refresh": {"type": "boolean", "description": "Fetch EIOPA's pages again even if the list is recent."}}}},
    {"name": "get_curve",
     "description": "One published EIOPA risk-free spot curve: annually compounded zero-coupon spot rates for "
                    "maturities 1 to 150 years, exactly as in the release workbook (decimal: 0.03268 = 3.268 %), "
                    "without ('no_va') or with ('with_va') the volatility adjustment, plus the curve parameters, "
                    "the workbook sheet and column, the source file and the attribution line to quote. "
                    + _PARAMS_TEXT + " Rates beyond the last liquid point are EIOPA's Smith-Wilson extrapolation; "
                    "nothing is computed or interpolated here." + _CACHE_TEXT,
     "inputSchema": {"type": "object", "properties": {
         "currency": _CURRENCY_PROP, "date": _DATE_PROP,
         "variant": {"type": "string", "enum": ["no_va", "with_va", "both"],
                     "description": "Default no_va."}}, "required": ["currency"]}},
    {"name": "get_rate",
     "description": "The published EIOPA risk-free spot rate for one currency, one whole-year maturity and one "
                    "reference date, without and/or with volatility adjustment: decimal and percent, the workbook "
                    "cell it was read from, whether the maturity lies beyond the last liquid point, the curve "
                    "parameters, the source file and the attribution line to quote. " + _PARAMS_TEXT + _CACHE_TEXT,
     "inputSchema": {"type": "object", "properties": {
         "currency": _CURRENCY_PROP, "maturity_years": _MATURITY_PROP, "date": _DATE_PROP,
         "variant": {"type": "string", "enum": ["no_va", "with_va", "both"], "description": "Default both."}},
         "required": ["currency", "maturity_years"]}},
    {"name": "get_parameters",
     "description": "The curve parameters EIOPA publishes above each spot curve, for the curves without and with "
                    "volatility adjustment. " + _PARAMS_TEXT + " currency 'all' returns every curve in the "
                    "release with its code, name and identifier." + _CACHE_TEXT,
     "inputSchema": {"type": "object", "properties": {
         "currency": {"type": "string", "description": _CURRENCY_PROP["description"] + " Or 'all'."},
         "date": _DATE_PROP}, "required": ["currency"]}},
    {"name": "compare",
     "description": "The published spot rate for one currency and whole-year maturity at two reference dates: both "
                    "values with their workbook cells, the change (date_b minus date_a) in decimal and in basis "
                    "points, computed with exact decimal arithmetic and labelled as derived, and the parameters "
                    "that differ between the two releases. Includes both attribution lines and EIOPA's required "
                    "disclaimer for derived output." + _CACHE_TEXT,
     "inputSchema": {"type": "object", "properties": {
         "currency": _CURRENCY_PROP, "maturity_years": _MATURITY_PROP,
         "date_a": dict(_DATE_PROP, description="The earlier date, same formats as date."),
         "date_b": dict(_DATE_PROP, description="The later date, same formats as date."),
         "variant": {"type": "string", "enum": ["no_va", "with_va", "both"], "description": "Default both."}},
         "required": ["currency", "maturity_years", "date_a", "date_b"]}},
]
HANDLERS = {"list_releases": list_releases, "get_curve": get_curve, "get_rate": get_rate,
            "get_parameters": get_parameters, "compare": compare}
INSTRUCTIONS = ("Values are EIOPA's published Solvency II risk-free interest rate term structures. Quote the "
                "'attribution' line of each result with the values (EIOPA's legal notice requires the source to be "
                "acknowledged). Say which reference date was used; it is in 'date.note'.")


def _tool_result(payload: dict) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=1)}],
            "structuredContent": payload, "isError": False}


def _tool_error(message: str) -> dict:
    return {"content": [{"type": "text", "text": message}], "isError": True}


def call_tool(name: str, arguments) -> dict:
    tool = next(t for t in TOOLS if t["name"] == name)
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        return _tool_error("arguments must be a JSON object")
    schema = tool["inputSchema"]
    unknown = sorted(set(arguments) - set(schema["properties"]))
    missing = [k for k in schema.get("required", []) if k not in arguments]
    if unknown or missing:
        parts = ([f"unknown argument(s): {', '.join(clean_text(u, 30) for u in unknown)}"] if unknown else []) + \
                ([f"missing argument(s): {', '.join(missing)}"] if missing else [])
        return _tool_error("; ".join(parts))
    try:
        return _tool_result(HANDLERS[name](**arguments))
    except RfrError as e:
        return _tool_error(str(e))
    except Exception as e:  # the server must survive anything one call does
        return _tool_error(f"unexpected {type(e).__name__}: {clean_text(e, 200)}")


def handle(request) -> dict | None:
    """One JSON-RPC message in, one response (or None for a notification) out."""
    if not isinstance(request, dict) or request.get("jsonrpc") != "2.0" or not isinstance(request.get("method"), str):
        return {"jsonrpc": "2.0", "id": request.get("id") if isinstance(request, dict) else None,
                "error": {"code": -32600, "message": "invalid request"}}
    method, id_ = request["method"], request.get("id")
    params = request.get("params") if isinstance(request.get("params"), dict) else {}
    if "id" not in request:
        return None  # notifications (initialized, cancelled, ...) need no answer
    if method == "initialize":
        result = {"protocolVersion": PROTOCOL, "capabilities": {"tools": {}},
                  "serverInfo": {"name": "eiopa-rfr", "title": "EIOPA risk-free interest rates", "version": __version__},
                  "instructions": INSTRUCTIONS}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        name = params.get("name")
        if name not in HANDLERS:
            return {"jsonrpc": "2.0", "id": id_, "error": {"code": -32602, "message": f"unknown tool {clean_text(name, 40)!r}"}}
        result = call_tool(name, params.get("arguments"))
    else:
        return {"jsonrpc": "2.0", "id": id_, "error": {"code": -32601, "message": f"method not found: {clean_text(method, 60)}"}}
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def serve(stdin=None, stdout=None) -> int:
    """MCP over stdio: one JSON-RPC message per line, UTF-8, nothing else on stdout."""
    stdin = stdin or io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace")
    out = stdout or sys.stdout.buffer
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except ValueError:
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            response = handle(request)
        if response is not None:
            out.write((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))
            out.flush()
    return 0


# ---------------------------------------------------------------------- CLI

def _fmt(value, suffix: str = "") -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        d = excel_decimal(repr(value))
        return plain(d) + suffix if d is not None else str(value)
    if isinstance(value, int):
        return f"{value}{suffix}"
    return str(value)


def _params_table(blocks: dict[str, dict]) -> list[str]:
    names = {"no_va": "no VA", "with_va": "with VA"}
    units = {"llp_years": " y", "convergence_years": " y", "ufr_percent": " %", "cra_bp": " bp", "va_bp": " bp"}
    head = "  " + "parameter".ljust(13) + "".join(names[v].ljust(12) for v in blocks)
    lines = [head]
    for label, key in PARAMETERS:
        lines.append("  " + label.ljust(13) + "".join(_fmt(blocks[v].get(key), units.get(key, "")).ljust(12)
                                                     for v in blocks))
    return lines


def _render(command: str, r: dict) -> str:
    lines: list[str] = []
    names = {"no_va": "without VA", "with_va": "with VA"}
    if command == "releases":
        lines.append(f"{'reference':12}{'label':17}{'file':30}{'page date':12}{'size':10}cached")
        for x in r["releases"]:
            lines.append(f"{x['reference_date']:12}{x['label']:17}{(x['file'] or '-'):30}{(x['page_date'] or '-'):12}"
                         f"{(x['size'] or '-'):10}{'yes' if x['cached'] else ''}")
        lines.append(f"{r['count']} releases, {r['earliest']} to {r['latest']}; list "
                     + (f"fetched {r['listing']['fetched_at']}" if r["listing"]["fetched_at"] else "from the local cache"))
    elif command == "rate":
        c = r["curve"]
        lines.append(f"{c['code']} ({c['name']}) {r['maturity_years']}-year spot rate, reference date "
                     f"{r['reference_date']}")
        for v in SHEETS:
            if v in r:
                b = r[v]
                beyond = " (beyond the last liquid point: EIOPA extrapolation)" if b.get("beyond_last_liquid_point") else ""
                lines.append(f"  {names[v]:11} {_fmt(b['rate_percent'], ' %'):10} {_fmt(b['rate']):10} {b['cell']}{beyond}")
        lines.append(f"Curve {c['curve_id']}")
        lines += _params_table({v: r[v]["parameters"] for v in SHEETS if v in r})
    elif command == "curve":
        c = r["curve"]
        present = [v for v in SHEETS if v in r]
        lines.append(f"{c['code']} ({c['name']}) spot curve, reference date {r['reference_date']}, {c['curve_id']}")
        lines.append("  years  " + "".join(names[v].ljust(12) for v in present))
        for i in range(len(r[present[0]]["rates"])):
            lines.append(f"  {i + 1:5}  " + "".join(_fmt(r[v]["rates"][i]["rate"]).ljust(12) for v in present))
        lines += _params_table({v: r[v]["parameters"] for v in present})
    elif command == "params":
        if "curves" in r:
            lines.append(f"{'code':6}{'name':22}{'LLP':>5}{'conv':>6}{'UFR %':>7}{'alpha':>10}{'CRA bp':>8}{'VA bp':>7}")
            for x in r["curves"]:
                p, q = x["no_va"], x.get("with_va", {})
                lines.append(f"{x['code']:6}{x['name'][:21]:22}{_fmt(p['llp_years']):>5}{_fmt(p['convergence_years']):>6}"
                             f"{_fmt(p['ufr_percent']):>7}{_fmt(p['alpha']):>10}{_fmt(p['cra_bp']):>8}"
                             f"{_fmt(q.get('va_bp')):>7}")
            lines.append("alpha: curve without VA")
        else:
            c = r["curve"]
            lines.append(f"{c['code']} ({c['name']}) curve parameters, reference date {r['reference_date']}, "
                         f"{c['curve_id']}")
            lines += _params_table({v: r[v] for v in SHEETS})
    elif command == "compare":
        c = r["curve"]["b"]
        lines.append(f"{c['code']} ({c['name']}) {r['maturity_years']}-year spot rate: {r['a']['reference_date']} -> "
                     f"{r['b']['reference_date']}")
        for v in SHEETS:
            if v in r:
                b = r[v]
                ch = b["change"]
                change = (f"{'+' if ch['bp'] > 0 else ''}{_fmt(ch['bp'])} bp" if ch else "n/a")
                lines.append(f"  {names[v]:11} {_fmt(b['a']['rate_percent'], ' %')} -> {_fmt(b['b']['rate_percent'], ' %')}"
                             f"   change {change}")
                for k, pair in b["parameters_changed"].items():
                    lines.append(f"      {k}: {_fmt(pair['a'])} -> {_fmt(pair['b'])}")
        lines.append("Change derived by eiopa-rfr: rate at the second date minus rate at the first.")
    elif command == "import":
        lines.append(f"Imported {r['source']['file']}: reference date {r['reference_date']}, "
                     f"{len(r['curves']['no_va']['columns'])} curves, sha256 {r['source']['sha256']}")
    elif command == "cache":
        lines.append(f"Cache: {r['path']}")
        lines.append(f"Releases: {', '.join(r['releases']) or 'none'}")
        lines.append(f"Release list: {'fetched ' + r['listing_fetched_at'] if r['listing_fetched_at'] else 'not cached'}")
        return "\n".join(lines)
    date = r.get("date") or {}
    if date.get("note") and command != "compare":
        lines.append(f"Date: {date['note']}")
    elif command == "compare":
        lines.append(f"Dates: {r['a']['note']}; {r['b']['note']}")
    for w in r.get("warnings") or []:
        lines.append(f"Warning: {w}")
    attributions = r.get("attribution")
    for a in (attributions if isinstance(attributions, list) else [attributions] if attributions else []):
        lines.append(a)
    if command == "compare":
        lines.append(r["disclaimer"])
    return "\n".join(line.rstrip() for line in lines)


def cache_info() -> dict:
    listing = _load_json(cache_dir() / "listing.json") or {}
    return {"path": str(cache_dir()), "releases": _cached_dates(), "listing_fetched_at": listing.get("fetched_at")}


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="print the result as JSON")
    common.add_argument("--offline", action="store_true", help="use the local cache only; fetch nothing")
    dated = argparse.ArgumentParser(add_help=False)
    dated.add_argument("--date", default="latest", help="'latest' (default), YYYY-MM or YYYY-MM-DD")
    ap = argparse.ArgumentParser(prog="eiopa-rfr", description="EIOPA's Solvency II risk-free interest rate term "
                                 "structures, as published.")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = ap.add_subparsers(dest="command", metavar="command")
    p = sub.add_parser("releases", parents=[common], help="list the monthly releases on EIOPA's pages")
    p.add_argument("--refresh", action="store_true", help="fetch EIOPA's pages even if the list is recent")
    p = sub.add_parser("rate", parents=[common, dated], help="spot rate for one maturity")
    p.add_argument("currency")
    p.add_argument("maturity", help="whole years, 1 to 150")
    p.add_argument("--variant", default="both", choices=["no_va", "with_va", "both"])
    p = sub.add_parser("curve", parents=[common, dated], help="the whole spot curve, 1 to 150 years")
    p.add_argument("currency")
    p.add_argument("--variant", default="no_va", choices=["no_va", "with_va", "both"])
    p = sub.add_parser("params", parents=[common, dated], help="curve parameters (currency or 'all')")
    p.add_argument("currency")
    p = sub.add_parser("compare", parents=[common], help="one maturity at two reference dates")
    p.add_argument("currency")
    p.add_argument("maturity")
    p.add_argument("date_a")
    p.add_argument("date_b")
    p.add_argument("--variant", default="both", choices=["no_va", "with_va", "both"])
    p = sub.add_parser("import", parents=[common], help="add a release zip you downloaded yourself to the cache")
    p.add_argument("file")
    sub.add_parser("cache", parents=[common], help="where the cache is and what is in it")
    sub.add_parser("mcp", help="run as an MCP server on stdin/stdout")
    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    if args.command is None:
        ap.print_help()
        return 0
    if args.command == "mcp":
        return serve()
    if getattr(args, "offline", False):
        os.environ["EIOPA_RFR_OFFLINE"] = "1"
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    try:
        if args.command == "releases":
            result = list_releases(refresh=args.refresh)
        elif args.command == "rate":
            result = get_rate(args.currency, args.maturity, args.date, args.variant)
        elif args.command == "curve":
            result = get_curve(args.currency, args.date, args.variant)
        elif args.command == "params":
            result = get_parameters(args.currency, args.date)
        elif args.command == "compare":
            result = compare(args.currency, args.maturity, args.date_a, args.date_b, args.variant)
        elif args.command == "import":
            rel = import_release(args.file)
            result = {"reference_date": rel["reference_date"], "source": rel["source"], "curves": rel["curves"],
                      "warnings": rel["warnings"], "attribution": attribution(rel)}
            if args.json:
                result = {k: v for k, v in result.items() if k != "curves"}
                result["curves"] = len(rel["curves"]["no_va"]["columns"])
        else:
            result = cache_info()
    except RfrError as e:
        print(f"eiopa-rfr: {e}", file=sys.stderr)
        return e.exit_code
    except KeyboardInterrupt:
        return 130
    print(json.dumps(result, ensure_ascii=False, indent=1) if args.json else _render(args.command, result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
