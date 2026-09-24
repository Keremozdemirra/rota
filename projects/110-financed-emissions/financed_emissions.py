#!/usr/bin/env python3
"""financed-emissions: financed emissions (Scope 3 category 15) by the PCAF Part A
methods, with the arithmetic shown for every position.

Method source, checked 2026-09-24:
  PCAF (2025). The Global GHG Accounting and Reporting Standard Part A:
  Financed Emissions. Third Edition (December 2025), file revision of
  15 January 2026.
  https://carbonaccountingfinancials.com/files/standard-launch-2025/PCAF-PartA-2025-V3-15012026.pdf
The edition does not number its equations, so every formula here is cited by
subchapter and page of that PDF (printed page numbers equal PDF page numbers).
The standard's text is not reproduced; the rules are restated in our words.

The user supplies amounts, denominators, emissions and data quality scores in a
CSV file. Nothing is fetched and no emission factor is bundled: the PCAF
emission factor database is available to PCAF signatories only.

Standard library only, Python 3.9+.

  financed-emissions portfolio.csv [--explain] [--markdown | --json] [--strict]
  financed-emissions --methods
  financed-emissions mcp            (MCP server on stdio)
"""
from __future__ import annotations

import argparse
import codecs
import csv
import io
import json
import os
import re
import sys
from decimal import Context, Decimal, ROUND_HALF_EVEN, ROUND_HALF_UP

__version__ = "0.1.0"

SOURCE = {
    "publisher": "Partnership for Carbon Accounting Financials (PCAF)",
    "title": "The Global GHG Accounting and Reporting Standard for the Financial Industry, Part A: Financed Emissions",
    "edition": "Third Edition",
    "date": "December 2025",
    "file_revision": "15 January 2026 (PCAF-PartA-2025-V3-15012026.pdf)",
    "url": "https://carbonaccountingfinancials.com/files/standard-launch-2025/PCAF-PartA-2025-V3-15012026.pdf",
    "landing_page": "https://carbonaccountingfinancials.com/en/standard",
    "sha256": "7c2b6b9725df9723e2837a42faf96cb5af8d821a7936b401d6ca58fbcc394a2c",
    "checked": "2026-09-24",
    "cite_as": "PCAF (2025). The Global GHG Accounting and Reporting Standard Part A: Financed Emissions. Third Edition.",
    "citations": "subchapter and page of the PDF above; the edition does not number its equations",
}
SHORT_SOURCE = "PCAF Part A, Third Edition (December 2025)"

# ----------------------------------------------------------------- method catalogue
# Order and names follow Table 5-1 (p. 37-38) and the reporting template in Table 10.2-2 (p. 199).
PCAF_CLASSES = [
    ("listed_equity_corporate_bonds", "Listed equity and corporate bonds", "5.1"),
    ("business_loans_unlisted_equity", "Business loans and unlisted equity", "5.2"),
    ("project_finance", "Project finance", "5.3"),
    ("commercial_real_estate", "Commercial real estate", "5.4"),
    ("mortgages", "Mortgages", "5.5"),
    ("motor_vehicle_loans", "Motor vehicle loans", "5.6"),
    ("use_of_proceeds", "Use of proceeds structures", "5.7"),
    ("securitization", "Securitization and structured products", "5.8"),
    ("sovereign_debt", "Sovereign debt", "5.9"),
    ("sub_sovereign_debt", "Sub-sovereign debt", "5.10"),
]
PCAF_CLASS_NAME = {k: n for k, n, _ in PCAF_CLASSES}
PCAF_CLASS_SECTION = {k: s for k, _, s in PCAF_CLASSES}

BASES = {
    "evic": {
        "name": "EVIC (enterprise value including cash)",
        "formula": "outstanding amount / EVIC",
    },
    "total_equity_plus_debt": {
        "name": "total equity + total debt",
        "formula": "outstanding amount / (total equity + total debt)",
    },
    "total_assets": {
        "name": "total assets (balance-sheet total, fallback when equity or debt cannot be obtained)",
        "formula": "outstanding amount / total assets",
    },
    "project_value_at_origination": {
        "name": "total project value at origination (project without a separate balance sheet)",
        "formula": "outstanding amount / total project value at origination",
    },
    "property_value_at_origination": {
        "name": "property value at origination",
        "formula": "outstanding amount / property value at origination",
    },
    "latest_property_value": {
        "name": "latest available property value, held constant in later years",
        "formula": "outstanding amount / latest available property value",
    },
    "vehicle_value_at_origination": {
        "name": "total value of the vehicle or fleet at origination",
        "formula": "outstanding amount / total value at origination",
    },
    "deal_outstanding": {
        "name": "deal outstanding amount (nominal, all tranches)",
        "formula": "investment outstanding (nominal) / deal outstanding (nominal)",
    },
    "ppp_adjusted_gdp": {
        "name": "PPP-adjusted GDP (international $)",
        "formula": "exposure (USD) / PPP-adjusted GDP (international $)",
    },
}

_SCOPE3_CORPORATE = ("scope 1 and 2: shall; scope 3: shall for every sector in reports published from 2025, "
                     "disclosed separately, with an explanation when it cannot be reported")

INSTRUMENTS = {
    "listed_equity": {
        "label": "Listed equity", "pcaf": "listed_equity_corporate_bonds", "instrument": "equity",
        "outstanding": "market value of the holding (share price x shares held)", "outstanding_cite": "5.1, p. 41",
        "bases": {"evic": "5.1, p. 42"}, "default": "evic", "fe_cite": "5.1, p. 44",
        "negative_equity": None,
        "scopes": _SCOPE3_CORPORATE, "scopes_cite": "5.1, pp. 40-41", "scope3_shall": True,
        "removals": "5.1, p. 49", "undrawn": False, "cap": None, "dq_decimal": False,
    },
    "corporate_bond": {
        "label": "Corporate bond", "pcaf": "listed_equity_corporate_bonds", "instrument": "debt",
        "outstanding": "book value of the debt owed", "outstanding_cite": "5.1, p. 41",
        "bases": {"evic": "5.1, p. 42", "total_equity_plus_debt": "5.1, p. 42",
                  "total_assets": "5.1, p. 42, footnote 44"},
        "default": "evic", "fe_cite": "5.1, p. 44",
        "negative_equity": "5.1, p. 42, footnote 42",
        "scopes": _SCOPE3_CORPORATE, "scopes_cite": "5.1, pp. 40-41", "scope3_shall": True,
        "removals": "5.1, p. 49", "undrawn": False, "cap": None, "dq_decimal": False,
    },
    "business_loan": {
        "label": "Business loan", "pcaf": "business_loans_unlisted_equity", "instrument": "debt",
        "outstanding": "disbursed amount minus repayments", "outstanding_cite": "5.2, p. 56",
        "bases": {"total_equity_plus_debt": "5.2, p. 57", "evic": "5.2, p. 57",
                  "total_assets": "5.2, p. 57, footnote 77"},
        "default": "total_equity_plus_debt", "fe_cite": "5.2, p. 58",
        "negative_equity": "5.2, p. 57, footnote 75",
        "scopes": _SCOPE3_CORPORATE, "scopes_cite": "5.2, p. 56", "scope3_shall": True,
        "removals": "5.2, p. 63", "undrawn": True, "cap": None, "dq_decimal": False,
    },
    "unlisted_equity": {
        "label": "Unlisted equity", "pcaf": "business_loans_unlisted_equity", "instrument": "equity",
        "outstanding": "share of the company held x its total equity", "outstanding_cite": "5.2, pp. 56-57",
        "bases": {"total_equity_plus_debt": "5.2, p. 57", "total_assets": "5.2, p. 57, footnote 77"},
        "default": "total_equity_plus_debt", "fe_cite": "5.2, p. 58",
        "negative_equity": "5.2, p. 57, footnote 75",
        "scopes": _SCOPE3_CORPORATE, "scopes_cite": "5.2, p. 56", "scope3_shall": True,
        "removals": "5.2, p. 63", "undrawn": False, "cap": None, "dq_decimal": False,
    },
    "project_finance": {
        "label": "Project finance", "pcaf": "project_finance", "instrument": None,
        "outstanding": "debt: disbursed minus repayments, without accrued interest; equity: share held x total project equity",
        "outstanding_cite": "5.3, p. 68",
        "bases": {"total_equity_plus_debt": "5.3, p. 67", "total_assets": "5.3, p. 68, footnote 109",
                  "project_value_at_origination": "5.3, p. 69"},
        "default": "total_equity_plus_debt", "fe_cite": "5.3, p. 70",
        "negative_equity": "5.3, p. 68, footnote 107",
        "scopes": "scope 1 and 2: shall; scope 3: should, where relevant", "scopes_cite": "5.3, p. 67",
        "scope3_shall": False,
        "removals": "5.3, p. 72", "undrawn": True, "cap": None, "dq_decimal": False,
    },
    "commercial_real_estate": {
        "label": "Commercial real estate", "pcaf": "commercial_real_estate", "instrument": None,
        "outstanding": "value of the loan or investment on the balance sheet", "outstanding_cite": "5.4, p. 78",
        "bases": {"property_value_at_origination": "5.4, p. 78", "latest_property_value": "5.4, p. 78"},
        "default": "property_value_at_origination", "fe_cite": "5.4, p. 79",
        "negative_equity": None,
        "scopes": ("scope 1 and 2 of the building's energy use, occupants and shared facilities included: shall; "
                   "construction or renovation emissions: optional"),
        "scopes_cite": "5.4, pp. 77-78", "scope3_shall": False,
        "removals": None, "undrawn": True, "cap": None, "dq_decimal": False,
    },
    "mortgage": {
        "label": "Mortgage", "pcaf": "mortgages", "instrument": "debt",
        "outstanding": "outstanding loan at the time of accounting", "outstanding_cite": "5.5, p. 84",
        "bases": {"property_value_at_origination": "5.5, p. 84", "latest_property_value": "5.5, p. 84"},
        "default": "property_value_at_origination", "fe_cite": "5.5, p. 84",
        "negative_equity": None,
        "scopes": "scope 1 and 2 of the property's energy use: shall; construction: not required",
        "scopes_cite": "5.5, p. 83", "scope3_shall": False,
        "removals": None, "undrawn": True, "cap": None, "dq_decimal": False,
    },
    "motor_vehicle_loan": {
        "label": "Motor vehicle loan", "pcaf": "motor_vehicle_loans", "instrument": "debt",
        "outstanding": "debt owed by the borrower", "outstanding_cite": "5.6, p. 91",
        "bases": {"vehicle_value_at_origination": "5.6, p. 91"},
        "default": "vehicle_value_at_origination", "fe_cite": "5.6, p. 92",
        "negative_equity": None,
        "scopes": ("scope 1 (fuel) and scope 2 (electricity of electric and hybrid vehicles): shall; "
                   "scope 3 production emissions: optional, new vehicles only, as a lump sum in the first financing year"),
        "scopes_cite": "5.6, p. 91", "scope3_shall": False,
        "removals": None, "undrawn": True, "cap": None, "dq_decimal": False,
    },
    "use_of_proceeds": {
        "label": "Use of proceeds structure", "pcaf": "use_of_proceeds", "instrument": None,
        "outstanding": "investor's outstanding debt or equity in the structure", "outstanding_cite": "5.7, p. 100",
        "bases": {"total_equity_plus_debt": "5.7, p. 100", "total_assets": "5.7, p. 100, footnote 166"},
        "default": "total_equity_plus_debt", "fe_cite": "5.7, pp. 101-102",
        "negative_equity": "5.7, p. 100, footnote 164",
        "scopes": "as required by the asset class of each underlying asset",
        "scopes_cite": "5.7, pp. 99-100", "scope3_shall": False,
        "removals": None, "undrawn": True, "cap": None, "dq_decimal": True,
    },
    "securitization": {
        "label": "Securitization or structured product", "pcaf": "securitization", "instrument": None,
        "outstanding": "current outstanding amount (nominal) of the investment", "outstanding_cite": "5.8, pp. 122-124",
        "bases": {"deal_outstanding": "5.8, p. 123 and Table 5.8-3, p. 124"},
        "default": "deal_outstanding", "fe_cite": "5.8, Table 5.8-3, pp. 124-125",
        "negative_equity": None,
        "scopes": ("scope 1 and 2 of the hard assets behind the collateral: shall; scope 3 of business-loan and "
                   "corporate-bond collateral: shall, disclosed separately"),
        "scopes_cite": "5.8, p. 119", "scope3_shall": False,
        "removals": None, "undrawn": False, "cap": None, "dq_decimal": True,
        "above_1": ("collateral attribution factors are capped at 1 (5.8, p. 122) inside the pool emissions you "
                    "supply; for the investment factor the standard gives no rule: used as computed and flagged"),
    },
    "sovereign_debt": {
        "label": "Sovereign debt", "pcaf": "sovereign_debt", "instrument": "debt",
        "outstanding": "disbursed debt minus repayments, in USD", "outstanding_cite": "5.9, p. 144",
        "bases": {"ppp_adjusted_gdp": "5.9, p. 144"},
        "default": "ppp_adjusted_gdp", "fe_cite": "5.9, p. 144",
        "negative_equity": None,
        "scopes": ("scope 1 (territorial production emissions): shall, both excluding and including LULUCF; "
                   "scope 2 (imported electricity, heat, steam, cooling) and scope 3 (non-energy imports): should"),
        "scopes_cite": "5.9, pp. 140-141", "scope3_shall": False,
        "removals": None, "undrawn": True, "cap": None, "dq_decimal": False,
    },
    "sub_sovereign_debt": {
        "label": "Sub-sovereign debt", "pcaf": "sub_sovereign_debt", "instrument": "debt",
        "outstanding": "disbursed debt minus repayments, in USD", "outstanding_cite": "5.10, p. 154",
        "bases": {"ppp_adjusted_gdp": "5.10, p. 154"},
        "default": "ppp_adjusted_gdp", "fe_cite": "5.10, p. 155",
        "negative_equity": None,
        "scopes": ("scope 1 excluding LULUCF: shall; including LULUCF: should, where available; "
                   "scope 2 and 3: should"),
        "scopes_cite": "5.10, pp. 153-154", "scope3_shall": False,
        "removals": None, "undrawn": True, "cap": "5.10, p. 154", "dq_decimal": False,
    },
}
SOVEREIGN = ("sovereign_debt", "sub_sovereign_debt")

ASSET_CLASS_ALIASES = {
    "listed_equities": "listed_equity", "equity_listed": "listed_equity",
    "corporate_bonds": "corporate_bond",
    "business_loans": "business_loan",
    "unlisted_equities": "unlisted_equity", "private_equity_direct": "unlisted_equity",
    "project_finance_loan": "project_finance", "project_finance_equity": "project_finance",
    "cre": "commercial_real_estate",
    "mortgages": "mortgage", "residential_mortgage": "mortgage", "residential_mortgages": "mortgage",
    "motor_vehicle_loans": "motor_vehicle_loan", "vehicle_loan": "motor_vehicle_loan", "auto_loan": "motor_vehicle_loan",
    "use_of_proceeds_structure": "use_of_proceeds", "use_of_proceeds_structures": "use_of_proceeds", "uop": "use_of_proceeds",
    "securitisation": "securitization", "securitizations": "securitization", "securitisations": "securitization",
    "structured_product": "securitization", "structured_products": "securitization",
    "sovereign": "sovereign_debt", "sovereign_bond": "sovereign_debt",
    "sub_sovereign": "sub_sovereign_debt", "subsovereign_debt": "sub_sovereign_debt",
}
BASIS_ALIASES = {"evic_": "evic", "enterprise_value_including_cash": "evic",
                 "total_equity_and_debt": "total_equity_plus_debt", "equity_plus_debt": "total_equity_plus_debt",
                 "property_value": "property_value_at_origination",
                 "value_at_origination": "vehicle_value_at_origination",
                 "deal_coa": "deal_outstanding", "ppp_gdp": "ppp_adjusted_gdp"}

# Instruments the standard leaves out of Part A, with its reason, so the "cannot be computed" list says why.
OUT_OF_SCOPE = {
    "derivative": "derivatives (futures, options, swaps) are not covered by Part A (chapter 5, p. 37; 5.1, p. 40)",
    "short_position": "short positions are not covered by Part A (5.1, p. 40)",
    "consumer_loan": "general consumer finance without a known use of proceeds is out of scope of Part A (chapter 5, step 3a, p. 35)",
    "home_equity_loan": "home equity loans and lines of credit are not required under the mortgage method, which gives no formula for them (5.5, p. 83)",
    "guarantee": "guarantees have no attribution until they are called and turned into a loan (5.3, p. 68)",
    "held_for_trading": "assets held for short durations or designated as held for sale are not in scope (chapter 5, p. 37; 5.1, p. 40)",
}
OUT_OF_SCOPE_ALIASES = {
    "derivatives": "derivative", "swap": "derivative", "future": "derivative", "option": "derivative",
    "futures": "derivative", "options": "derivative", "swaps": "derivative",
    "short": "short_position",
    "credit_card": "consumer_loan", "personal_loan": "consumer_loan", "consumer_loans": "consumer_loan",
    "heloc": "home_equity_loan", "hel": "home_equity_loan", "home_equity_line_of_credit": "home_equity_loan",
    "guarantees": "guarantee", "letter_of_credit_unfunded": "guarantee",
    "held_for_sale": "held_for_trading", "trading_asset": "held_for_trading", "trading_book": "held_for_trading",
}

DQ_RULE = {
    "rule": "sum(outstanding amount x data quality score) / sum(outstanding amount), per asset class or sector; "
            "scope 3 scores weighted separately from scope 1 and 2",
    "cite": "6.1, p. 167 and Box 6.1-6, pp. 167-168",
    "scale": "1 = highest quality, 5 = lowest; score tables per asset class in chapter 5 and Annex 10.1",
}

REQUIRED_COLUMNS = ["position_id", "asset_class", "outstanding", "denominator", "scope1_tco2e", "scope2_tco2e", "dq_score"]
OPTIONAL_COLUMNS = ["counterparty", "sector", "currency", "fx_rate", "denominator_basis", "total_equity", "total_debt",
                    "instrument", "scope3_tco2e", "dq_score_scope3", "scope1_incl_lulucf_tco2e", "removals_tco2e",
                    "undrawn_commitment", "allocation_pct"]
NUMERIC_COLUMNS = ["outstanding", "denominator", "total_equity", "total_debt", "fx_rate", "scope1_tco2e",
                   "scope2_tco2e", "scope3_tco2e", "scope1_incl_lulucf_tco2e", "removals_tco2e",
                   "undrawn_commitment", "dq_score", "dq_score_scope3"]

# Tool's choice, not a PCAF rule: no real position or economy reaches 10^24 in any currency unit or
# tCO2e, and the bound keeps Decimal formatting exact.
MAX_ABS = Decimal("1e24")
# Tool's choice: a portfolio file above this size is refused rather than read into memory.
MAX_FILE_BYTES = 50 * 1024 * 1024

_CTX = Context(prec=34, rounding=ROUND_HALF_EVEN)
ZERO = Decimal(0)
ONE = Decimal(1)
MILLION = Decimal(1_000_000)


class InputError(Exception):
    """The file cannot be read as a portfolio at all; the CLI exits 2."""


class AttributionError(ValueError):
    """A position cannot be attributed; .reasons lists every reason found."""

    def __init__(self, reasons):
        self.reasons = list(reasons)
        super().__init__("; ".join(self.reasons))


# ----------------------------------------------------------------- numbers
_PLAIN = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d{1,3})?")
_SEP = "[ \u00a0\u202f']"  # spaces and apostrophes group thousands in several locales; never decimals
_GROUP_POINT = re.compile(r"[+-]?\d{1,3}(?:" + _SEP + r"\d{3})+(?:\.\d+)?")
_US_MULTI = re.compile(r"[+-]?\d{1,3}(?:,\d{3}){2,}(?:\.\d+)?")
_US_DEC = re.compile(r"[+-]?\d{1,3}(?:,\d{3})+\.\d+")
_EU_PLAIN = re.compile(r"[+-]?\d+(?:,\d+)?")
_EU_GROUP = re.compile(r"[+-]?\d{1,3}(?:[." + _SEP[1:-1] + r"]\d{3})+(?:,\d+)?")


def parse_decimal(text, decimal_comma: bool = False):
    """A finite Decimal, or None for a blank cell. Raises ValueError with the reason."""
    if text is None:
        return None
    s = str(text).strip()
    if not s:
        return None
    if decimal_comma:
        if _EU_PLAIN.fullmatch(s) or _EU_GROUP.fullmatch(s):
            s = re.sub("[." + _SEP[1:-1] + "]", "", s).replace(",", ".")
        elif "." in s:
            raise ValueError(f"{_short(s)!r} is not a number with a decimal comma (--decimal-comma is set)")
    else:
        if _GROUP_POINT.fullmatch(s):
            s = re.sub(_SEP, "", s)
        elif _US_MULTI.fullmatch(s) or _US_DEC.fullmatch(s):
            s = s.replace(",", "")
        elif "," in s:
            raise ValueError(f"{_short(s)!r} contains a comma: remove thousands separators, "
                             "or pass --decimal-comma if the comma is the decimal separator")
    if not _PLAIN.fullmatch(s):
        raise ValueError(f"{_short(s)!r} is not a number")
    value = Decimal(s)
    if abs(value) >= MAX_ABS:
        raise ValueError(f"{_short(s)!r} is implausibly large (limit 1e24, a safeguard of this tool)")
    return value


def _short(s, limit=40):
    s = str(s)
    return s if len(s) <= limit else s[:limit] + "..."


def clean_text(value, limit=120):
    """Cell text shown back to the user or an agent: no control characters, bounded length."""
    if value is None:
        return None
    s = re.sub(r"[\x00-\x1f\x7f-\x9f\u2028\u2029\u202a-\u202e\u2066-\u2069]", " ", str(value)).strip()
    s = re.sub(r"\s{2,}", " ", s)
    if len(s) > limit:
        s = s[:limit - 3] + "..."
    return s or None


def _div(a, b):
    return _CTX.divide(a, b)


def _mul(a, b):
    return _CTX.multiply(a, b)


def _add(a, b):
    return _CTX.add(a, b)


def _sum(values):
    total = ZERO
    for v in values:
        total = _add(total, v)
    return total


def fmt_amount(d) -> str:
    """An input amount as given, with thousands separators."""
    if d is None:
        return "n/a"
    s = format(d, ",f")
    return "0" if s in ("-0", "0") else s


def fmt_t(d, places=2) -> str:
    """tCO2e or other computed values, rounded half-up for display."""
    if d is None:
        return "n/a"
    if abs(d) >= Decimal("1e20"):
        return format(d, ".6e")
    q = d.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    if q == 0:
        q = abs(q)
    return format(q, f",.{places}f")


def fmt_ratio(d, digits=6) -> str:
    """A ratio to `digits` significant digits in plain notation."""
    if d is None:
        return "n/a"
    if d == 0:
        return "0"
    q = Decimal(1).scaleb(d.adjusted() - digits + 1)
    r = d.quantize(q, rounding=ROUND_HALF_UP)
    s = format(r, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def num(d):
    """Decimal to a JSON number (full precision of a double), None stays None."""
    if d is None:
        return None
    f = float(d)
    return 0.0 if f == 0 else f


# ----------------------------------------------------------------- reading the file
_BOMS = [
    (codecs.BOM_UTF32_LE, "utf-32"), (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF8, "utf-8-sig"), (codecs.BOM_UTF16_LE, "utf-16"), (codecs.BOM_UTF16_BE, "utf-16"),
]


def decode_bytes(data: bytes, encoding=None):
    """(text, encoding used, notes). Excel's usual CSV encodings are recognised without help."""
    notes = []
    if data[:4] == b"PK\x03\x04":
        raise InputError("this is a ZIP file (an .xlsx workbook?); save the sheet as CSV first")
    if encoding:
        try:
            codecs.lookup(encoding)
        except LookupError:
            raise InputError(f"unknown encoding {encoding!r}") from None
        try:
            return data.decode(encoding), encoding, notes
        except UnicodeDecodeError as e:
            raise InputError(f"the file is not valid {encoding} (byte {e.start})") from None
    for bom, enc in _BOMS:
        if data.startswith(bom):
            try:
                text = data.decode(enc)
            except UnicodeDecodeError as e:
                raise InputError(f"the file starts with a {enc} byte order mark but is not valid {enc} (byte {e.start})") from None
            return text.lstrip("\ufeff"), enc, notes
    if b"\x00" in data:
        # UTF-16 without a byte order mark: in ASCII-range text every other byte is zero.
        even, odd = data[0::2], data[1::2]
        if odd and odd.count(0) >= len(odd) * 0.3 and even.count(0) == 0:
            enc = "utf-16-le"
        elif even and even.count(0) >= len(even) * 0.3 and odd.count(0) == 0:
            enc = "utf-16-be"
        else:
            raise InputError("the file contains NUL bytes and is not UTF-16 text; is it a CSV file?")
        try:
            return data.decode(enc), enc, notes
        except UnicodeDecodeError as e:
            raise InputError(f"the file looks like {enc} but does not decode (byte {e.start})") from None
    try:
        return data.decode("utf-8"), "utf-8", notes
    except UnicodeDecodeError:
        pass
    try:
        text = data.decode("cp1252")
        enc = "cp1252"
    except UnicodeDecodeError:
        text = data.decode("latin-1")
        enc = "latin-1"
    notes.append(f"the file is not valid UTF-8 and was read as {enc}; pass --encoding if names look wrong")
    return text, enc, notes


def _count_outside_quotes(line, ch):
    n, quoted = 0, False
    for c in line:
        if c == '"':
            quoted = not quoted
        elif c == ch and not quoted:
            n += 1
    return n


def sniff_delimiter(text):
    """(delimiter, lines to skip). Honours Excel's 'sep=;' first line."""
    for line in text.splitlines():
        if not line.strip():
            continue
        stripped = line.strip()
        if stripped.lower().startswith("sep=") and len(stripped) == 5:
            return stripped[4], 1
        counts = {d: _count_outside_quotes(line, d) for d in (",", ";", "\t", "|")}
        best = max(counts, key=lambda d: counts[d])
        return (best if counts[best] else ","), 0
    return ",", 0


def normalise_key(value) -> str:
    s = str(value or "").strip().lstrip("\ufeff").strip().lower()
    return re.sub(r"[\s\-/]+", "_", s)


def read_rows(text):
    """(header, [(line, {column: cell})], notes, delimiter). Raises InputError."""
    delimiter, skip = sniff_delimiter(text)
    notes = []
    stream = io.StringIO(text, newline="")
    for _ in range(skip):
        stream.readline()
    reader = csv.reader(stream, delimiter=delimiter)
    header = None
    rows = []
    try:
        for cells in reader:
            line = reader.line_num + skip
            if not any(c.strip() for c in cells):
                continue
            if header is None:
                header = [normalise_key(c) for c in cells]
                dupes = sorted({h for h in header if h and header.count(h) > 1})
                if dupes:
                    raise InputError("duplicate column names: " + ", ".join(dupes))
                continue
            row = {}
            for i, cell in enumerate(cells):
                if i < len(header):
                    if header[i]:
                        row[header[i]] = cell
                elif cell.strip():
                    row.setdefault("__extra__", []).append(cell)
            rows.append((line, row))
    except csv.Error as e:
        raise InputError(f"CSV error on line {reader.line_num + skip}: {e}") from None
    if header is None:
        raise InputError("the file is empty")
    missing = [c for c in REQUIRED_COLUMNS if c not in header]
    if missing:
        raise InputError("missing required columns: " + ", ".join(missing)
                         + " (found: " + ", ".join(h for h in header if h) + ")")
    known = set(REQUIRED_COLUMNS) | set(OPTIONAL_COLUMNS)
    unknown = [h for h in header if h and h not in known]
    if unknown:
        notes.append("ignored columns: " + ", ".join(clean_text(u, 40) for u in unknown))
    return header, rows, notes, delimiter


# ----------------------------------------------------------------- attribution
def attribution(instrument, outstanding, denominator=None, basis=None, total_equity=None, total_debt=None,
                is_equity=None):
    """Attribution factor for one position by the PCAF method of its instrument.

    Returns a dict with the factor and its derivation; raises ValueError listing the
    reasons it cannot be computed. Amounts must share one currency and unit.
    """
    reasons = []
    spec = INSTRUMENTS.get(instrument)
    if spec is None:
        raise AttributionError([f"unknown asset class {instrument!r}"])
    basis = basis or ("total_equity_plus_debt" if (total_equity is not None or total_debt is not None)
                      and "total_equity_plus_debt" in spec["bases"] else spec["default"])
    if basis not in spec["bases"]:
        raise AttributionError([f"denominator basis {basis!r} is not used for {instrument}; allowed: "
                                + ", ".join(spec["bases"])])
    if is_equity is None:
        is_equity = spec["instrument"] == "equity"
    cite = spec["bases"][basis]
    notes, flags = [], []
    if outstanding is None:
        reasons.append("outstanding is blank")
    elif outstanding < 0:
        reasons.append(f"outstanding is negative ({fmt_amount(outstanding)}); short positions are not covered (5.1, p. 40)")

    equity_used = None
    denom_expr = None
    if total_equity is not None or total_debt is not None:
        if basis != "total_equity_plus_debt":
            reasons.append("total_equity and total_debt apply only to the total_equity_plus_debt basis")
        elif total_equity is None or total_debt is None:
            reasons.append("give both total_equity and total_debt, or only denominator")
        elif total_debt < 0:
            reasons.append(f"total_debt is negative ({fmt_amount(total_debt)})")
        else:
            equity_used = total_equity if total_equity > 0 else ZERO
            split = _add(equity_used, total_debt)
            if denominator is not None:
                raw = _add(total_equity, total_debt)
                if not (_close(denominator, split) or _close(denominator, raw)):
                    reasons.append(f"denominator {fmt_amount(denominator)} does not equal total_equity + total_debt "
                                   f"({fmt_amount(raw)})")
            denominator = split
            denom_expr = f"({fmt_amount(equity_used)} + {fmt_amount(total_debt)})"
            if total_equity < 0:
                notes.append(f"total equity {fmt_amount(total_equity)} is negative; PCAF sets it to 0, so emissions "
                             f"are attributed to debt only ({spec['negative_equity']})")

    assumed_full = False
    if denominator is None and not any("total_equity" in r for r in reasons):
        if instrument == "motor_vehicle_loan":
            assumed_full = True
        else:
            reasons.append(f"denominator ({BASES[basis]['name']}) is blank")
    elif denominator is not None and denominator <= 0:
        why = f"denominator ({BASES[basis]['name']}) is {fmt_amount(denominator)}; it must be greater than 0"
        if basis == "evic":
            why += "; EVIC adds market capitalisation and book debt without deducting cash, so it cannot be negative (5.1, p. 42)"
        elif basis == "total_equity_plus_debt" and equity_used is None:
            why += "; if total equity is negative, give total_equity and total_debt so the PCAF rule (set equity to 0) can apply"
        reasons.append(why)
    if reasons:
        raise AttributionError(reasons)

    lines = []
    formula = BASES[basis]["formula"]
    af_raw = None
    capped = False
    plain = True
    if assumed_full:
        plain = False
        if outstanding == 0:
            af = ZERO
            lines.append(f"attribution factor = 0 (loan repaid; the value at origination is not needed) [{cite}]")
        else:
            af = ONE
            lines.append("attribution factor = 1 (value at origination unknown: PCAF says to assume 100% attribution) "
                         "[5.6, p. 91]")
            notes.append("vehicle value at origination unknown: attribution assumed at 100% as PCAF advises (5.6, p. 91)")
        formula = "1 (100% attribution, value at origination unknown)"
    elif is_equity and total_equity is not None and total_equity < 0:
        plain = False
        af = ZERO
        af_raw = _div(outstanding, denominator)
        lines.append(f"attribution factor = 0 (equity stake in an entity whose total equity is negative: "
                     f"PCAF attributes no emissions to equity) [{spec['negative_equity']}]")
        formula = "0 (equity in an entity with negative total equity)"
    else:
        af_raw = _div(outstanding, denominator)
        af = af_raw
        lines.append(f"attribution factor = {formula} [{cite}]")
        lines.append(f"                   = {fmt_amount(outstanding)} / {denom_expr or fmt_amount(denominator)} "
                     f"= {fmt_ratio(af_raw)}")
        if af_raw > 1:
            if spec["cap"]:
                af = ONE
                capped = True
                plain = False
                lines.append(f"                   capped at 1 as PCAF requires for this asset class [{spec['cap']}]")
                flags.append(f"attribution factor {fmt_ratio(af_raw)} is above 1 and was capped at 1 as PCAF "
                             f"requires ({spec['cap']}); check that exposure and GDP are in the same unit")
            else:
                flags.append(f"attribution factor {fmt_ratio(af_raw)} is above 1; PCAF Part A (Third Edition) gives no "
                             f"cap for {spec['label'].lower()}, so it was used as computed; check the denominator")
    return {
        "instrument": instrument, "basis": basis, "denominator": denominator, "equity_used": equity_used,
        "attribution_factor": af, "attribution_factor_uncapped": af_raw, "capped": capped,
        "assumed_full": assumed_full, "plain_ratio": plain, "formula": formula, "cite": cite,
        "lines": lines, "notes": notes, "flags": flags,
    }


def _close(a, b):
    tolerance = max(abs(b) * Decimal("1e-9"), Decimal("0.005"))
    return abs(a - b) <= tolerance


def financed(att, outstanding, emissions):
    """(financed emissions, arithmetic text) for one emissions figure."""
    fe = _mul(att["attribution_factor"], emissions)
    if att["plain_ratio"]:
        expr = f"{fmt_amount(outstanding)} / {fmt_amount(att['denominator'])} x {fmt_amount(emissions)}"
    else:
        expr = f"{fmt_ratio(att['attribution_factor'])} x {fmt_amount(emissions)}"
    return fe, expr


def attribute(asset_class, outstanding, emissions, denominator=None, denominator_basis=None,
              total_equity=None, total_debt=None, instrument=None, currency=None):
    """One position, for the MCP tool and library use. Numbers may be Decimal, int, float or str."""
    key = _resolve_instrument(asset_class)
    if key in OUT_OF_SCOPE:
        raise ValueError(OUT_OF_SCOPE[key])
    if key not in INSTRUMENTS:
        raise ValueError(f"unknown asset class {asset_class!r}; one of: " + ", ".join(INSTRUMENTS))
    spec = INSTRUMENTS[key]
    values = {}
    for name, raw in (("outstanding", outstanding), ("emissions", emissions), ("denominator", denominator),
                      ("total_equity", total_equity), ("total_debt", total_debt)):
        values[name] = _to_decimal(raw, name)
    if values["emissions"] is None:
        raise ValueError("emissions is required (tCO2e)")
    if values["emissions"] < 0:
        raise ValueError("emissions must not be negative; report removals separately")
    basis = None
    if denominator_basis:
        basis = BASIS_ALIASES.get(normalise_key(denominator_basis), normalise_key(denominator_basis))
    is_equity = None
    if instrument:
        kind = normalise_key(instrument)
        if kind not in ("debt", "equity"):
            raise ValueError("instrument must be debt or equity")
        if spec["instrument"] and spec["instrument"] != kind:
            raise ValueError(f"{key} is a {spec['instrument']} instrument")
        is_equity = kind == "equity"
    notes = []
    if key in SOVEREIGN:
        if currency and normalise_key(currency) != "usd":
            raise ValueError(f"PCAF defines this exposure in USD over PPP-adjusted GDP in international dollars "
                             f"({spec['bases']['ppp_adjusted_gdp']}); the exposure given is in {clean_text(currency, 10)}")
        if not currency:
            notes.append(f"PCAF defines the exposure in USD and the denominator in international dollars "
                         f"({spec['bases']['ppp_adjusted_gdp']}); make sure the inputs follow that")
    att = attribution(key, values["outstanding"], values["denominator"], basis, values["total_equity"],
                      values["total_debt"], is_equity)
    fe, expr = financed(att, values["outstanding"], values["emissions"])
    lines = att["lines"] + [f"financed emissions = {expr} = {fmt_t(fe)} tCO2e [{spec['fe_cite']}]"]
    return {
        "asset_class": key,
        "pcaf_asset_class": PCAF_CLASS_NAME[spec["pcaf"]],
        "section": PCAF_CLASS_SECTION[spec["pcaf"]],
        "denominator_basis": att["basis"],
        "attribution_factor": num(att["attribution_factor"]),
        "attribution_factor_uncapped": num(att["attribution_factor_uncapped"]),
        "capped": att["capped"],
        "financed_emissions_tco2e": num(fe),
        "formula": att["formula"] + " ; financed emissions = attribution factor x emissions",
        "arithmetic": lines,
        "citations": sorted({att["cite"], spec["fe_cite"]}),
        "notes": att["notes"] + notes,
        "flags": att["flags"],
        "source": SHORT_SOURCE + ", " + SOURCE["url"],
    }


def _to_decimal(raw, name):
    if raw is None or isinstance(raw, bool):
        if isinstance(raw, bool):
            raise ValueError(f"{name} must be a number")
        return None
    if isinstance(raw, Decimal):
        if not raw.is_finite():
            raise ValueError(f"{name} must be a finite number")
        return raw
    if isinstance(raw, (int, float)):
        if isinstance(raw, float) and (raw != raw or raw in (float("inf"), float("-inf"))):
            raise ValueError(f"{name} must be a finite number")
        raw = repr(raw) if isinstance(raw, float) else str(raw)
    try:
        return parse_decimal(raw)
    except ValueError as e:
        raise ValueError(f"{name}: {e}") from None


def _resolve_instrument(value):
    key = normalise_key(value)
    key = ASSET_CLASS_ALIASES.get(key, key)
    return OUT_OF_SCOPE_ALIASES.get(key, key)


# ----------------------------------------------------------------- one CSV row
class _Env:
    def __init__(self, reporting_currency, decimal_comma):
        self.reporting_currency = reporting_currency
        self.decimal_comma = decimal_comma
        self.seen = {}


def evaluate_row(line, row, env):
    """('ok', position) or ('failed', failure). Warnings travel inside either."""
    reasons, warnings = [], []
    pid = clean_text(row.get("position_id"), 60)
    counterparty = clean_text(row.get("counterparty"))
    raw_class = clean_text(row.get("asset_class"), 60)
    sector = clean_text(row.get("sector"), 60)
    base = {"line": line, "position_id": pid, "counterparty": counterparty, "asset_class": raw_class, "sector": sector}

    if row.get("__extra__"):
        reasons.append("the row has more cells than the header has columns")
    if not pid:
        reasons.append("position_id is blank")
    elif pid in env.seen:
        reasons.append(f"position_id {pid!r} is already used on line {env.seen[pid]}")
    else:
        env.seen[pid] = line

    inst = _resolve_instrument(raw_class) if raw_class else None
    spec = None
    if not raw_class:
        reasons.append("asset_class is blank")
    elif inst in OUT_OF_SCOPE:
        return "failed", dict(base, reasons=reasons + [OUT_OF_SCOPE[inst]], out_of_scope=True)
    elif inst not in INSTRUMENTS:
        reasons.append(f"asset_class {raw_class!r} is not one this calculator knows; use one of: " + ", ".join(INSTRUMENTS))
    else:
        spec = INSTRUMENTS[inst]
        base["asset_class"] = inst
        base["pcaf_asset_class"] = spec["pcaf"]

    v, bad = {}, set()
    for col in NUMERIC_COLUMNS:
        try:
            v[col] = parse_decimal(row.get(col), env.decimal_comma)
        except ValueError as e:
            reasons.append(f"{col}: {e}")
            v[col] = None
            bad.add(col)
    allocation = None
    raw_alloc = (row.get("allocation_pct") or "").strip()
    if raw_alloc:
        try:
            allocation = parse_decimal(raw_alloc.rstrip("%").strip(), env.decimal_comma)
        except ValueError as e:
            reasons.append(f"allocation_pct: {e}")

    outstanding = v["outstanding"]
    if outstanding is None and "outstanding" not in bad:
        reasons.append("outstanding is blank")
    elif outstanding is not None and outstanding < 0:
        reasons.append(f"outstanding is negative ({fmt_amount(outstanding)}); short positions are not covered (5.1, p. 40)")

    # Currency: amounts in a row share its currency; only the reporting total needs a rate, and the user supplies it.
    currency = (row.get("currency") or "").strip().upper() or None
    if currency and not re.fullmatch(r"[A-Z]{3}", currency):
        reasons.append(f"currency {clean_text(currency, 12)!r} is not a three-letter ISO 4217 code")
        currency = None
    currency = currency or env.reporting_currency
    fx = v["fx_rate"]
    rate = None
    if fx is not None and fx <= 0:
        reasons.append("fx_rate must be greater than 0")
    elif fx is not None and fx != 1 and not (currency and env.reporting_currency):
        reasons.append("fx_rate is given but no currency is stated; add a currency column and name the reporting "
                       "currency with --currency")
    elif currency and env.reporting_currency and currency != env.reporting_currency:
        if fx is None:
            reasons.append(f"amounts are in {currency} and the report is in {env.reporting_currency}, but fx_rate is "
                           f"blank; this tool never converts currencies on its own")
        else:
            rate = fx
    else:
        if fx is not None and fx != 1:
            reasons.append(f"fx_rate is {fmt_amount(fx)} but the row is already in the reporting currency")
        else:
            rate = ONE
    base["currency"] = currency
    if outstanding is not None and outstanding >= 0 and rate is not None:
        base["outstanding_reporting"] = _mul(outstanding, rate)

    scope1, scope2, scope3 = v["scope1_tco2e"], v["scope2_tco2e"], v["scope3_tco2e"]
    for col in ("scope1_tco2e", "scope2_tco2e", "scope3_tco2e", "removals_tco2e", "undrawn_commitment",
                "total_debt"):
        if v[col] is not None and v[col] < 0:
            hint = "; report removals in removals_tco2e, never as negative emissions" if col.startswith("scope") else ""
            reasons.append(f"{col} is negative ({fmt_amount(v[col])}){hint}")
    if scope1 is None and "scope1_tco2e" not in bad:
        reasons.append("scope1_tco2e is blank; scope 1 is required for every asset class")

    dq = dq3 = None
    if spec is not None:
        if inst in SOVEREIGN:
            if currency is None:
                reasons.append(f"currency unknown: PCAF defines this exposure in USD over PPP-adjusted GDP in "
                               f"international dollars ({spec['bases']['ppp_adjusted_gdp']}); add a currency column "
                               f"or --currency")
            elif currency != "USD":
                reasons.append(f"the exposure is in {currency}: PCAF defines it in USD over PPP-adjusted GDP in "
                               f"international dollars ({spec['bases']['ppp_adjusted_gdp']}); give the exposure in "
                               f"USD with an fx_rate to the reporting currency")
            if scope2 is None:
                warnings.append("scope 2 not supplied; PCAF says it should be reported for this issuer type "
                                f"({spec['scopes_cite']}); scope 1+2 shows scope 1 only")
            if inst == "sovereign_debt" and v["scope1_incl_lulucf_tco2e"] is None:
                warnings.append("scope 1 including LULUCF not supplied; PCAF requires sovereign scope 1 both "
                                "excluding and including LULUCF (5.9, p. 141)")
        elif scope2 is None and "scope2_tco2e" not in bad:
            reasons.append(f"scope2_tco2e is blank; PCAF requires scope 1 and 2 for {spec['label'].lower()} "
                           f"({spec['scopes_cite']}); enter 0 if there is none")
        if spec["scope3_shall"] and scope3 is None:
            warnings.append("scope 3 not supplied; PCAF requires it for every sector in reports published from 2025 "
                            f"and asks for an explanation when it cannot be reported ({spec['scopes_cite']})")
        if v["scope1_incl_lulucf_tco2e"] is not None and inst not in SOVEREIGN:
            warnings.append("scope1_incl_lulucf_tco2e applies to sovereign and sub-sovereign debt only; ignored")
        if v["removals_tco2e"] is not None and not spec["removals"]:
            warnings.append("PCAF gives removal attribution only for listed equity, corporate bonds, business loans, "
                            "unlisted equity and project finance (chapter 5, p. 33); removals_tco2e ignored")
        if v["undrawn_commitment"] is not None and not spec["undrawn"]:
            warnings.append("undrawn_commitment applies to loans only (6.2, p. 173); ignored")
        if allocation is not None:
            if inst != "use_of_proceeds":
                warnings.append("allocation_pct applies to use_of_proceeds only; ignored")
            elif allocation < 0:
                reasons.append("allocation_pct must not be negative")
            elif allocation > 100:
                warnings.append("allocation_pct above 100: PCAF notes this can happen for equity funds "
                                "(5.7, p. 103, footnote 170)")
        dq = _check_dq(v["dq_score"], "dq_score", spec, reasons)
        if v["dq_score"] is None and "dq_score" not in bad:
            warnings.append("no data quality score; the position is left out of the weighted score "
                            "(6.1, p. 167: publish the weighted score or explain why not)")
        dq3 = _check_dq(v["dq_score_scope3"], "dq_score_scope3", spec, reasons)
        if scope3 is not None and v["dq_score_scope3"] is None and "dq_score_scope3" not in bad:
            warnings.append("scope 3 given without dq_score_scope3; PCAF weights scope 3 data quality separately "
                            "(6.1, p. 167), so this position is left out of that score")

    kind = normalise_key(row.get("instrument"))
    is_equity = None
    if kind:
        if kind not in ("debt", "equity"):
            reasons.append("instrument must be debt or equity")
        elif spec is not None and spec["instrument"] and spec["instrument"] != kind:
            reasons.append(f"instrument {kind!r} conflicts with {inst}, which is a {spec['instrument']} instrument")
        else:
            is_equity = kind == "equity"

    att = None
    basis = None
    if spec is not None:
        braw = normalise_key(row.get("denominator_basis"))
        if braw:
            basis = BASIS_ALIASES.get(braw, braw)
            if basis not in spec["bases"]:
                reasons.append(f"denominator_basis {clean_text(braw, 40)!r} is not used for {inst}; allowed: "
                               + ", ".join(spec["bases"]))
                basis = None
        if braw == "" or basis is not None:
            try:
                att = attribution(inst, outstanding if (outstanding is not None and outstanding >= 0) else ZERO,
                                  v["denominator"], basis, v["total_equity"], v["total_debt"], is_equity)
            except AttributionError as e:
                reasons.extend(r for r in e.reasons if not r.startswith("outstanding"))

    if reasons:
        return "failed", dict(base, reasons=_dedupe(reasons))

    alloc_frac = ONE
    if inst == "use_of_proceeds" and allocation is not None:
        alloc_frac = _div(allocation, Decimal(100))
    out_rep = _mul(base["outstanding_reporting"], alloc_frac)

    lines = list(att["lines"])
    results = {}
    labels = [("scope1", "scope 1", scope1), ("scope2", "scope 2", scope2), ("scope3", "scope 3", scope3)]
    if inst in SOVEREIGN:
        labels.append(("scope1_incl_lulucf", "scope 1 incl. LULUCF", v["scope1_incl_lulucf_tco2e"]))
    if spec["removals"]:
        labels.append(("removals", "removals", v["removals_tco2e"]))
    for key, label, e in labels:
        if e is None:
            results[key] = None
            continue
        fe, expr = financed(att, outstanding, e)
        results[key] = fe
        cite = spec["removals"] if key == "removals" else spec["fe_cite"]
        suffix = " (reported separately)" if key in ("scope3", "removals", "scope1_incl_lulucf") else ""
        lines.append(f"financed {label} = {expr} = {fmt_t(fe)} tCO2e{suffix} [{cite}]")
    results["scope1_2"] = _add(results["scope1"], results["scope2"] or ZERO)
    lines.append(f"financed scope 1+2 = {fmt_t(results['scope1_2'])} tCO2e [6.1, p. 162]")
    if inst == "use_of_proceeds":
        lines.append(f"outstanding reported = {fmt_amount(outstanding)} x allocation "
                     f"{fmt_amount(allocation if allocation is not None else Decimal(100))}% "
                     f"= {fmt_t(_mul(outstanding, alloc_frac))} [5.7, pp. 102-103]")
    undrawn = None
    if v["undrawn_commitment"] is not None and spec["undrawn"]:
        try:
            undrawn = _undrawn(inst, att, v, is_equity, rate, lines)
        except AttributionError as e:
            warnings.append("undrawn commitment not computed: " + str(e))
    if rate != ONE:
        lines.append(f"outstanding in {env.reporting_currency} = {fmt_amount(outstanding)} {currency} x fx_rate "
                     f"{fmt_amount(rate)} = {fmt_t(base['outstanding_reporting'])} (rate supplied by the user)")
    dq_text = f"data quality score = {fmt_amount(dq) if dq is not None else 'n/a'} (scope 1 and 2)"
    if scope3 is not None:
        dq_text += f", {fmt_amount(dq3) if dq3 is not None else 'n/a'} (scope 3)"
    lines.append(dq_text)

    position = dict(base)
    position.update({
        "pcaf_asset_class_name": PCAF_CLASS_NAME[spec["pcaf"]],
        "section": PCAF_CLASS_SECTION[spec["pcaf"]],
        "fx_rate": rate,
        "outstanding": outstanding,
        "outstanding_reporting": out_rep,
        "allocation_pct": allocation if inst == "use_of_proceeds" else None,
        "denominator_basis": att["basis"],
        "denominator": att["denominator"],
        "attribution_factor": att["attribution_factor"],
        "attribution_factor_uncapped": att["attribution_factor_uncapped"],
        "capped": att["capped"],
        "financed": results,
        "undrawn": undrawn,
        "dq_score": dq,
        "dq_score_scope3": dq3 if scope3 is not None else None,
        "formula": att["formula"],
        "arithmetic": lines,
        "citations": sorted({att["cite"], spec["fe_cite"]}),
        "notes": att["notes"],
        "flags": att["flags"],
        "warnings": warnings,
    })
    return "ok", position


def _undrawn(inst, att, v, is_equity, rate, lines):
    # 6.2 (p. 173): same denominator as the drawn part, so the drawn position's resolved denominator is reused.
    amount = v["undrawn_commitment"]
    denominator = None if att["assumed_full"] else att["denominator"]
    u = attribution(inst, amount, denominator, att["basis"], None, None, is_equity)
    out = {"amount": amount, "amount_reporting": _mul(amount, rate), "attribution_factor": u["attribution_factor"],
           "flags": u["flags"]}
    for key, e in (("scope1_2", _add(v["scope1_tco2e"], v["scope2_tco2e"] or ZERO)), ("scope3", v["scope3_tco2e"])):
        if e is None:
            out[key] = None
            continue
        fe, expr = financed(u, amount, e)
        out[key] = fe
        label = "scope 1+2" if key == "scope1_2" else "scope 3"
        lines.append(f"undrawn {label} = {expr} = {fmt_t(fe)} tCO2e (unweighted, reported separately) "
                     f"[6.2, pp. 172-173]")
    return out


def _check_dq(value, col, spec, reasons):
    if value is None:
        return None
    if not (1 <= value <= 5):
        reasons.append(f"{col} is {fmt_amount(value)}; PCAF scores run from 1 (highest quality) to 5 (lowest)")
        return None
    if not spec["dq_decimal"] and value != value.to_integral_value():
        reasons.append(f"{col} is {fmt_amount(value)}; for {spec['label'].lower()} PCAF scores are whole numbers 1 to 5 "
                       "(averages apply only to use of proceeds structures and securitizations, 5.7 p. 103, 5.8 p. 127)")
        return None
    return value


def _dedupe(items):
    seen, out = set(), []
    for i in items:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


# ----------------------------------------------------------------- the portfolio
def compute(data: bytes, source_name="(stdin)", reporting_currency=None, decimal_comma=False, encoding=None):
    """Read a portfolio CSV (bytes) and return the full result as a dict of Decimals and strings."""
    if not data or not data.strip():
        raise InputError("the file is empty")
    text, used_encoding, notes = decode_bytes(data, encoding)
    header, rows, more_notes, delimiter = read_rows(text)
    notes += more_notes
    if reporting_currency:
        reporting_currency = reporting_currency.strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", reporting_currency):
            raise InputError(f"--currency {clean_text(reporting_currency, 12)!r} is not a three-letter ISO 4217 code")
    elif "currency" in header:
        found = sorted({(r.get("currency") or "").strip().upper() for _, r in rows} - {""})
        if len(found) == 1:
            reporting_currency = found[0]
        elif len(found) > 1:
            raise InputError(f"the file has several currencies ({', '.join(clean_text(c, 12) for c in found)}); "
                             "name the reporting currency (--currency, or reporting_currency in the MCP tool) and give "
                             "fx_rate for the other rows")
    if not reporting_currency:
        notes.append("no currency stated: amounts are summed as one unnamed currency, and sovereign rows cannot be "
                     "computed (they need USD)")

    env = _Env(reporting_currency, decimal_comma)
    positions, failures = [], []
    for line, row in rows:
        status, item = evaluate_row(line, row, env)
        (positions if status == "ok" else failures).append(item)

    result = {
        "tool": "financed-emissions", "version": __version__,
        "method": dict(SOURCE),
        "input": {"file": source_name, "encoding": used_encoding, "delimiter": {"\t": "tab"}.get(delimiter, delimiter),
                  "rows": len(rows), "reporting_currency": reporting_currency, "decimal_comma": decimal_comma},
        "positions": positions,
        "not_computed": failures,
        "notes": notes,
    }
    result.update(summarise(positions, failures))
    return result


def compute_file(path, **kwargs):
    if path == "-":
        data = sys.stdin.buffer.read()
        return compute(data, source_name="(stdin)", **kwargs)
    if not os.path.exists(path):
        raise InputError(f"no such file: {path}")
    if not os.path.isfile(path):
        raise InputError(f"not a regular file: {path}")
    size = os.path.getsize(path)
    if size > MAX_FILE_BYTES:
        raise InputError(f"{path} is {size} bytes; the limit is {MAX_FILE_BYTES} (a safeguard of this tool)")
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as e:
        raise InputError(f"cannot read {path}: {e.strerror or e}") from None
    return compute(data, source_name=os.path.basename(path), **kwargs)


def _group():
    return {"positions": 0, "outstanding": ZERO, "scope1": ZERO, "scope2": ZERO, "scope1_2": ZERO,
            "scope3": ZERO, "scope3_positions": 0, "removals": ZERO, "removals_positions": 0,
            "scope1_incl_lulucf": ZERO, "lulucf_positions": 0,
            "dq_num": ZERO, "dq_den": ZERO, "dq3_num": ZERO, "dq3_den": ZERO,
            "undrawn_amount": ZERO, "undrawn_scope1_2": ZERO, "undrawn_scope3": ZERO, "undrawn_positions": 0,
            "undrawn_scope3_positions": 0,
            "not_computed": 0, "outstanding_not_computed": ZERO}


def _add_position(g, p):
    f = p["financed"]
    out = p["outstanding_reporting"]
    g["positions"] += 1
    g["outstanding"] = _add(g["outstanding"], out)
    for k in ("scope1", "scope1_2"):
        g[k] = _add(g[k], f[k])
    if f["scope2"] is not None:
        g["scope2"] = _add(g["scope2"], f["scope2"])
    if f["scope3"] is not None:
        g["scope3"] = _add(g["scope3"], f["scope3"])
        g["scope3_positions"] += 1
    if f.get("removals") is not None:
        g["removals"] = _add(g["removals"], f["removals"])
        g["removals_positions"] += 1
    if f.get("scope1_incl_lulucf") is not None:
        g["scope1_incl_lulucf"] = _add(g["scope1_incl_lulucf"], f["scope1_incl_lulucf"])
        g["lulucf_positions"] += 1
    if p["dq_score"] is not None:
        g["dq_num"] = _add(g["dq_num"], _mul(out, p["dq_score"]))
        g["dq_den"] = _add(g["dq_den"], out)
    if p["dq_score_scope3"] is not None:
        g["dq3_num"] = _add(g["dq3_num"], _mul(out, p["dq_score_scope3"]))
        g["dq3_den"] = _add(g["dq3_den"], out)
    u = p["undrawn"]
    if u:
        g["undrawn_positions"] += 1
        g["undrawn_amount"] = _add(g["undrawn_amount"], u["amount_reporting"])
        if u["scope1_2"] is not None:
            g["undrawn_scope1_2"] = _add(g["undrawn_scope1_2"], u["scope1_2"])
        if u["scope3"] is not None:
            g["undrawn_scope3"] = _add(g["undrawn_scope3"], u["scope3"])
            g["undrawn_scope3_positions"] += 1


def _finish(g):
    covered_base = _add(g["outstanding"], g["outstanding_not_computed"])
    g["dq_weighted"] = _div(g["dq_num"], g["dq_den"]) if g["dq_den"] > 0 else None
    g["dq_weighted_scope3"] = _div(g["dq3_num"], g["dq3_den"]) if g["dq3_den"] > 0 else None
    g["dq_share"] = _div(g["dq_den"], g["outstanding"]) if g["outstanding"] > 0 else None
    g["intensity_scope1_2"] = _div(g["scope1_2"], _div(g["outstanding"], MILLION)) if g["outstanding"] > 0 else None
    g["coverage"] = _div(g["outstanding"], covered_base) if covered_base > 0 else None
    return g


def summarise(positions, failures):
    by_class = {k: _group() for k, _, _ in PCAF_CLASSES}
    sectors = {}
    total = _group()
    has_sector = any(p.get("sector") for p in positions)
    for p in positions:
        _add_position(by_class[p["pcaf_asset_class"]], p)
        _add_position(total, p)
        if has_sector:
            _add_position(sectors.setdefault(p.get("sector") or "(no sector)", _group()), p)
    unplaced = 0
    for f in failures:
        out = f.get("outstanding_reporting")
        klass = f.get("pcaf_asset_class")
        if klass is None:
            unplaced += 1
            continue
        for g in (by_class[klass], total):
            g["not_computed"] += 1
            if out is not None:
                g["outstanding_not_computed"] = _add(g["outstanding_not_computed"], out)
    classes = []
    for key, name, section in PCAF_CLASSES:
        g = by_class[key]
        if g["positions"] or g["not_computed"]:
            classes.append(dict(_finish(g), key=key, name=name, section=section))
    flags, warnings = [], []
    for p in positions:
        for msg in p["flags"]:
            flags.append({"line": p["line"], "position_id": p["position_id"], "message": msg})
        if p["undrawn"]:
            for msg in p["undrawn"]["flags"]:
                flags.append({"line": p["line"], "position_id": p["position_id"], "message": "undrawn: " + msg})
    for item in positions:
        for msg in item.get("warnings") or []:
            warnings.append({"line": item["line"], "position_id": item["position_id"], "message": msg})
    return {
        "by_asset_class": classes,
        "by_sector": [dict(_finish(g), name=name) for name, g in sorted(sectors.items())] if has_sector else [],
        "totals": dict(_finish(total), not_computed_out_of_scope=unplaced),
        "flags": flags,
        "warnings": sorted(warnings, key=lambda w: w["line"]),
    }


# ----------------------------------------------------------------- JSON
def to_json(result, max_positions=None, explain=True):
    """The result with Decimals as JSON numbers. max_positions trims the position list."""
    def group(g, extra=()):
        out = {k: g[k] for k in extra}
        out.update({
            "positions": g["positions"], "not_computed": g["not_computed"],
            "outstanding_covered": num(g["outstanding"]),
            "outstanding_not_computed": num(g["outstanding_not_computed"]),
            "coverage_share": num(g["coverage"]),
            "financed_tco2e": {"scope1": num(g["scope1"]), "scope2": num(g["scope2"]),
                               "scope1_2": num(g["scope1_2"]), "scope3": num(g["scope3"])},
            "scope3_positions": g["scope3_positions"],
            "intensity_scope1_2_tco2e_per_million": num(g["intensity_scope1_2"]),
            "dq_weighted_scope1_2": num(g["dq_weighted"]),
            "dq_weighted_scope3": num(g["dq_weighted_scope3"]),
            "dq_share_of_outstanding_scored": num(g["dq_share"]),
        })
        if g["removals_positions"]:
            out["removals_tco2e"] = num(g["removals"])
        if g["lulucf_positions"]:
            out["scope1_incl_lulucf_tco2e"] = num(g["scope1_incl_lulucf"])
        if g["undrawn_positions"]:
            out["undrawn"] = {"positions": g["undrawn_positions"], "amount": num(g["undrawn_amount"]),
                              "financed_tco2e_scope1_2": num(g["undrawn_scope1_2"]),
                              "financed_tco2e_scope3": num(g["undrawn_scope3"]) if g["undrawn_scope3_positions"] else None}
        return out

    positions = []
    for p in result["positions"]:
        item = {
            "line": p["line"], "position_id": p["position_id"], "counterparty": p["counterparty"],
            "asset_class": p["asset_class"], "pcaf_asset_class": p["pcaf_asset_class_name"], "section": p["section"],
            "sector": p["sector"], "currency": p["currency"], "fx_rate": num(p["fx_rate"]),
            "outstanding": num(p["outstanding"]), "outstanding_reporting": num(p["outstanding_reporting"]),
            "denominator_basis": p["denominator_basis"], "denominator": num(p["denominator"]),
            "attribution_factor": num(p["attribution_factor"]),
            "attribution_factor_uncapped": num(p["attribution_factor_uncapped"]), "capped": p["capped"],
            "financed_tco2e": {k: num(val) for k, val in p["financed"].items()},
            "dq_score": num(p["dq_score"]), "dq_score_scope3": num(p["dq_score_scope3"]),
            "formula": p["formula"], "citations": p["citations"], "notes": p["notes"], "flags": p["flags"],
        }
        if p["allocation_pct"] is not None:
            item["allocation_pct"] = num(p["allocation_pct"])
        if p["undrawn"]:
            u = p["undrawn"]
            item["undrawn"] = {"amount": num(u["amount"]), "amount_reporting": num(u["amount_reporting"]),
                               "attribution_factor": num(u["attribution_factor"]),
                               "financed_tco2e_scope1_2": num(u["scope1_2"]), "financed_tco2e_scope3": num(u["scope3"])}
        if explain:
            item["arithmetic"] = p["arithmetic"]
        positions.append(item)
    totals = group(result["totals"])
    totals["not_computed_out_of_scope"] = result["totals"]["not_computed_out_of_scope"]
    doc = {
        "tool": result["tool"], "version": result["version"], "method": result["method"], "input": result["input"],
        "totals": totals,
        "by_asset_class": [group(g, ("name", "section")) for g in result["by_asset_class"]],
        "by_sector": [group(g, ("name",)) for g in result["by_sector"]],
        "not_computed": [{"line": f["line"], "position_id": f["position_id"], "counterparty": f["counterparty"],
                          "asset_class": f["asset_class"], "reasons": f["reasons"]} for f in result["not_computed"]],
        "flags": result["flags"], "warnings": result["warnings"], "notes": result["notes"],
        "data_quality_rule": DQ_RULE,
        "positions_total": len(positions),
    }
    if max_positions is not None and len(positions) > max_positions:
        doc["positions_truncated"] = True
        positions = positions[:max_positions]
    doc["positions"] = positions
    return doc


# ----------------------------------------------------------------- text and Markdown
def _table(headers, rows, align, markdown=False):
    if markdown:
        out = ["| " + " | ".join(headers) + " |",
               "| " + " | ".join("---:" if a == "r" else "---" for a in align) + " |"]
        for r in rows:
            out.append("| " + " | ".join(str(c).replace("|", "\\|") for c in r) + " |")
        return "\n".join(out)
    widths = [max(len(str(h)), *(len(str(r[i])) for r in rows)) if rows else len(str(h)) for i, h in enumerate(headers)]

    def fmt(r):
        return "  ".join(str(c).rjust(w) if a == "r" else str(c).ljust(w) for c, w, a in zip(r, widths, align)).rstrip()
    return "\n".join([fmt(headers), "  ".join("-" * w for w in widths), *(fmt(r) for r in rows)])


def _pct(d):
    return "n/a" if d is None else fmt_t(_mul(d, Decimal(100)), 1) + "%"


def render(result, markdown=False, explain=False):
    md = markdown
    cur = result["input"]["reporting_currency"]
    cur_label = cur or "currency not stated"
    h2 = (lambda t: f"## {t}") if md else (lambda t: t)
    out = []
    head = (f"financed-emissions {result['version']}: {SHORT_SOURCE}. File {result['input']['file']}, "
            f"{result['input']['rows']} rows, reporting currency {cur_label}.")
    out.append(("# Financed emissions\n\n" + head) if md else head)

    positions = result["positions"]
    if positions:
        rows = []
        for p in positions:
            f = p["financed"]
            rows.append([
                p["position_id"], _clip(p["counterparty"] or "", 34), p["asset_class"],
                f"{fmt_amount(p['outstanding'])} {p['currency'] or ''}".strip(),
                fmt_ratio(p["attribution_factor"]) + ("*" if p["flags"] else ""),
                fmt_t(f["scope1_2"]), fmt_t(f["scope3"]) if f["scope3"] is not None else "-",
                fmt_amount(p["dq_score"]) if p["dq_score"] is not None else "-",
                fmt_amount(p["dq_score_scope3"]) if p["dq_score_scope3"] is not None else "-",
            ])
        out.append("")
        out.append(h2(f"Positions ({len(positions)} computed)"))
        if md:
            out.append("")
        out.append(_table(["id", "counterparty", "asset class", "outstanding", "attribution", "S1+2 tCO2e",
                           "S3 tCO2e", "DQ", "DQ S3"], rows, "lllrrrrrr", md))
        if any(p["flags"] for p in positions):
            out.append("* flagged, see Flags below")

    if explain and positions:
        out.append("")
        out.append(h2("Arithmetic"))
        blocks = []
        for p in positions:
            title = (f"{p['position_id']}  {p['counterparty'] or ''}  {p['asset_class']} -> "
                     f"{p['pcaf_asset_class_name']} (PCAF {p['section']})")
            blocks.append("\n".join([title] + ["  " + line for line in p["arithmetic"]]
                                    + ["  note: " + n for n in p["notes"]]))
        body = "\n\n".join(blocks)
        out.append(f"\n```\n{body}\n```" if md else body)

    classes = result["by_asset_class"]
    if classes:
        rows = []
        for g in classes + [dict(result["totals"], name="Total", section="")]:
            rows.append([
                g["name"] + (f" ({g['section']})" if g.get("section") else ""),
                str(g["positions"]) + (f" (+{g['not_computed']} not computed)" if g["not_computed"] else ""),
                fmt_t(g["outstanding"], 0), fmt_t(g["scope1_2"]),
                fmt_t(g["scope3"]) if g["scope3_positions"] else "-",
                fmt_t(g["intensity_scope1_2"]) if g["intensity_scope1_2"] is not None else "n/a",
                fmt_t(g["dq_weighted"]) if g["dq_weighted"] is not None else "n/a",
                fmt_t(g["dq_weighted_scope3"]) if g["dq_weighted_scope3"] is not None else "n/a",
            ])
        out.append("")
        out.append(h2("By PCAF asset class"))
        if md:
            out.append("")
        out.append(_table(["asset class", "positions", f"outstanding ({cur_label})", "S1+2 tCO2e", "S3 tCO2e",
                           f"S1+2 tCO2e per M {cur or ''}".rstrip(), "DQ S1+2", "DQ S3"], rows, "lrrrrrrr", md))
        t = result["totals"]
        extra = [f"Coverage: {_pct(t['coverage'])} of the outstanding amount of in-scope rows in this file was computed."]
        if t["dq_share"] is not None and t["dq_share"] < 1:
            extra.append(f"The weighted scores cover {_pct(t['dq_share'])} of the computed outstanding amount "
                         f"(positions without a score are left out).")
        extra.append(f"Weighted scores: {DQ_RULE['rule']} ({DQ_RULE['cite']}). Scope 3 is reported separately "
                     f"from scope 1+2 (6.1, p. 162).")
        out.append("")
        out.extend(extra)

    sectors = result["by_sector"]
    if sectors:
        rows = [[g["name"], str(g["positions"]), fmt_t(g["outstanding"], 0), fmt_t(g["scope1_2"]),
                 fmt_t(g["scope3"]) if g["scope3_positions"] else "-",
                 fmt_t(g["dq_weighted"]) if g["dq_weighted"] is not None else "n/a"] for g in sectors]
        out.append("")
        out.append(h2("By sector"))
        if md:
            out.append("")
        out.append(_table(["sector", "positions", f"outstanding ({cur_label})", "S1+2 tCO2e", "S3 tCO2e", "DQ S1+2"],
                          rows, "lrrrrr", md))

    t = result["totals"]
    separate = []
    if t["removals_positions"]:
        separate.append(f"Emission removals, financed: {fmt_t(t['removals'])} tCO2e ({_n(t['removals_positions'])}), "
                        f"reported separately and not netted (6.1, p. 165).")
    if t["lulucf_positions"]:
        separate.append(f"Sovereign scope 1 including LULUCF, financed: {fmt_t(t['scope1_incl_lulucf'])} tCO2e "
                        f"({_n(t['lulucf_positions'])}; 5.9, p. 141; 5.10, p. 154).")
    if t["undrawn_positions"]:
        s3 = (f"{fmt_t(t['undrawn_scope3'])} tCO2e scope 3" if t["undrawn_scope3_positions"]
              else "no scope 3 given")
        separate.append(f"Undrawn loan commitments: {fmt_t(t['undrawn_amount'], 0)} {cur or ''} "
                        f"({_n(t['undrawn_positions'])}), {fmt_t(t['undrawn_scope1_2'])} tCO2e scope 1+2, {s3}; "
                        f"unweighted and reported separately from financed emissions (6.2, pp. 172-174).")
    if any(p["financed"]["scope2"] is None for p in positions):
        separate.append("Sovereign rows without scope 2 contribute scope 1 only to scope 1+2.")
    if separate:
        out.append("")
        out.append(h2("Reported separately"))
        if md:
            out.append("")
        out.extend(("- " + s) if md else s for s in separate)

    fails = result["not_computed"]
    out.append("")
    out.append(h2(f"Not computed ({len(fails)})"))
    if md:
        out.append("")
    if not fails:
        out.append("Every position was computed.")
    for f in fails:
        who = f["position_id"] or "(no id)"
        what = ", ".join(x for x in (f["asset_class"], f["counterparty"]) if x)
        text = f"line {f['line']}  {who}" + (f" ({what})" if what else "") + ": " + "; ".join(f["reasons"])
        out.append(("- " + text) if md else "  " + text)

    for title, items in (("Flags", result["flags"]), ("Warnings", result["warnings"])):
        if items:
            out.append("")
            out.append(h2(f"{title} ({len(items)})"))
            if md:
                out.append("")
            for w in items:
                text = f"line {w['line']}  {w['position_id']}: {w['message']}"
                out.append(("- " + text) if md else "  " + text)
    if result["notes"]:
        out.append("")
        out.append(h2("Notes"))
        if md:
            out.append("")
        out.extend(("- " + n) if md else "  " + n for n in result["notes"])
    out.append("")
    out.append(f"Method: {SOURCE['cite_as']} {SOURCE['url']} (checked {SOURCE['checked']}); cited by subchapter and "
               f"page. Amounts, emissions and scores are the user's input; this tool fetched nothing.")
    return "\n".join(out) + "\n"


def _n(count):
    return f"{count} position" + ("" if count == 1 else "s")


def _clip(s, n):
    return s if len(s) <= n else s[:n - 3] + "..."


# ----------------------------------------------------------------- methods
def methods_catalogue():
    """Every asset class this calculator implements, with formulas and citations."""
    classes = []
    for key, spec in INSTRUMENTS.items():
        classes.append({
            "asset_class": key,
            "label": spec["label"],
            "pcaf_asset_class": PCAF_CLASS_NAME[spec["pcaf"]],
            "section": PCAF_CLASS_SECTION[spec["pcaf"]],
            "outstanding_amount": spec["outstanding"] + f" ({spec['outstanding_cite']})",
            "denominators": [{"basis": b, "denominator": BASES[b]["name"], "attribution_factor": BASES[b]["formula"],
                              "cite": c, "default": b == spec["default"]} for b, c in spec["bases"].items()],
            "financed_emissions": "attribution factor x emissions of the counterparty (or of the structure's collateral "
                                  "or assets for use of proceeds and securitizations)",
            "financed_emissions_cite": spec["fe_cite"],
            "scopes": spec["scopes"], "scopes_cite": spec["scopes_cite"],
            "removals": ("attributed with the same factor, reported separately (" + spec["removals"] + ")")
            if spec["removals"] else None,
            "negative_total_equity": ("set to 0, so emissions go to debt only and none to equity ("
                                      + spec["negative_equity"] + ")") if spec["negative_equity"] else None,
            "attribution_factor_above_1": ("capped at 1 (" + spec["cap"] + ")") if spec["cap"] else
            spec.get("above_1", "no rule in the standard: used as computed and flagged by this tool"),
            "special": _special(key),
            "dq_scores": "decimal 1-5 allowed (weighted average of the underlying assets)" if spec["dq_decimal"]
            else "whole number 1-5",
        })
    return {
        "method": dict(SOURCE),
        "asset_classes": classes,
        "data_quality": DQ_RULE,
        "reporting": {
            "absolute": "scope 1+2 combined shall be disclosed; scope 1 and 2 separately should be where useful (6.1, p. 162)",
            "scope3": "disclosed separately from scope 1+2 where the method requires it (6.1, p. 162)",
            "intensity": "tCO2e per million of currency lent or invested (6.1, p. 166)",
            "removals": "reported separately, never netted; carbon credits not deducted (6.1, pp. 163, 165)",
            "undrawn": "optional, unweighted amount required when used, reported separately (6.2, pp. 171-174)",
            "coverage": "share of loans and investments covered shall be disclosed (6.1, p. 161)",
        },
        "out_of_scope": OUT_OF_SCOPE,
        "not_bundled": "No emission factors are bundled or fetched. The PCAF emission factor database is available "
                       "to PCAF signatories and Accredited Partners only; supply emissions or your own factors.",
    }


def _special(key):
    return {
        "motor_vehicle_loan": "value at origination unknown: attribution assumed at 100% (5.6, p. 91); repaid loan: 0",
        "use_of_proceeds": "emissions = financed emissions of the structure (sum over allocated assets of their "
                           "attribution factor x emissions, or the issuer's reported figure, 5.7 pp. 101-102); "
                           "outstanding reported = investor outstanding x allocation percentage (5.7 pp. 102-103)",
        "securitization": "attribution = investment attribution factor x tranche attribution factor = investment "
                          "outstanding / deal outstanding (5.8 p. 123, Table 5.8-3 p. 124); emissions = financed "
                          "emissions of the collateral pool, whose collateral factors PCAF caps at 1 (5.8 p. 122)",
        "sovereign_debt": "exposure in USD over PPP-adjusted GDP in international dollars (5.9 p. 144)",
        "sub_sovereign_debt": "PPP-adjusted GDP of the sub-sovereign = its nominal GDP x the country's PPP "
                              "adjustment factor (Annex 10.3, pp. 204-205)",
        "project_finance": "projects without a separate balance sheet may use the project value at origination, "
                           "held constant (5.3 p. 69)",
        "commercial_real_estate": "latest property value allowed when the value at origination cannot be obtained, "
                                  "then held constant (5.4 p. 78)",
        "mortgage": "latest property value allowed when the value at origination cannot be obtained, then held "
                    "constant (5.5 p. 84)",
    }.get(key)


def render_methods(markdown=False):
    cat = methods_catalogue()
    rows = []
    for c in cat["asset_classes"]:
        dens = "; ".join(f"{d['attribution_factor']} [{d['cite']}]" + (" (default)" if d["default"] and
                                                                          len(c["denominators"]) > 1 else "")
                         for d in c["denominators"])
        rows.append([c["asset_class"], f"{c['pcaf_asset_class']} ({c['section']})", dens,
                     f"{c['scopes']} [{c['scopes_cite']}]", c["attribution_factor_above_1"], c["special"] or ""])
    head = (f"Methods implemented: {SHORT_SOURCE}, {SOURCE['url']} (checked {SOURCE['checked']}). "
            f"Financed emissions = attribution factor x emissions in every class.")
    body = _table(["asset_class", "PCAF asset class", "attribution factor", "scopes", "factor above 1", "also"], rows,
                  "llllll", markdown)
    if not markdown:
        body = "\n\n".join(
            "\n".join([f"{r[0]}  ->  {r[1]}", f"  attribution: {r[2]}", f"  scopes: {r[3]}", f"  above 1: {r[4]}"]
                      + ([f"  also: {r[5]}"] if r[5] else []))
            for r in rows)
    tail = f"Data quality: {DQ_RULE['rule']} [{DQ_RULE['cite']}]."
    return f"{head}\n\n{body}\n\n{tail}\n{cat['not_bundled']}\n"


# ----------------------------------------------------------------- CLI
def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["mcp"]:
        if len(argv) > 1:
            print("usage: financed-emissions mcp   (takes no further arguments)", file=sys.stderr)
            return 2
        import financed_emissions_mcp
        return financed_emissions_mcp.main()
    parser = argparse.ArgumentParser(
        prog="financed-emissions",
        description="Financed emissions (Scope 3 category 15) by the PCAF Part A methods (Third Edition, "
                    "December 2025), with the arithmetic shown for every position. "
                    "`financed-emissions mcp` starts the MCP server on stdio.")
    parser.add_argument("portfolio", nargs="?", help="portfolio CSV file, or - for standard input")
    fmt = parser.add_mutually_exclusive_group()
    fmt.add_argument("--json", action="store_true", help="machine-readable output")
    fmt.add_argument("--markdown", action="store_true", help="Markdown tables")
    parser.add_argument("--explain", action="store_true", help="show each position's formula with its numbers")
    parser.add_argument("--strict", action="store_true",
                        help="exit 1 if any position cannot be computed or is flagged (attribution factor above 1)")
    parser.add_argument("--currency", metavar="CUR", help="reporting currency (ISO 4217), e.g. EUR")
    parser.add_argument("--decimal-comma", action="store_true", help="numbers use a comma as decimal separator")
    parser.add_argument("--encoding", help="file encoding, when detection is not enough (e.g. cp1252)")
    parser.add_argument("--methods", action="store_true", help="list the methods, formulas and citations")
    parser.add_argument("--version", action="version", version=f"financed-emissions {__version__}")
    args = parser.parse_args(argv)
    _safe_stdout()

    if args.methods:
        if args.json:
            print(json.dumps(methods_catalogue(), ensure_ascii=False, indent=1))
        else:
            sys.stdout.write(render_methods(markdown=args.markdown))
        return 0
    if not args.portfolio:
        parser.print_usage(sys.stderr)
        print("financed-emissions: error: give a portfolio CSV file (or --methods)", file=sys.stderr)
        return 2
    try:
        result = compute_file(args.portfolio, reporting_currency=args.currency, decimal_comma=args.decimal_comma,
                              encoding=args.encoding)
    except InputError as e:
        print(f"financed-emissions: {e}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(to_json(result, explain=True), ensure_ascii=False, indent=1))
    else:
        sys.stdout.write(render(result, markdown=args.markdown, explain=args.explain))
    if args.strict and (result["not_computed"] or result["flags"]):
        return 1
    return 0


def _safe_stdout():
    # A console that cannot print a counterparty's name should not stop the report.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass


if __name__ == "__main__":
    raise SystemExit(main())
