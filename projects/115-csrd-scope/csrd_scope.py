#!/usr/bin/env python3
"""csrd-scope: is an undertaking in scope of the EU Corporate Sustainability Reporting
Directive, and from which financial year?

A rules engine over Directive 2013/34/EU (Arts. 1, 2, 3, 19a, 29a, 40, 40a, 48i) as
amended by Directive (EU) 2026/470, and the application dates in Art. 5(2) of Directive
(EU) 2022/2464 as amended by Directives (EU) 2025/794 and (EU) 2026/470. Every step
names the provision it applies; where national law or legal judgement decides, the
answer is "depends" and the question for counsel is returned instead.

Offline: `check`, `thresholds`, `timeline` and `sources` read only the bundled snapshot
in data/. `refresh` and `verify-sources` contact CELLAR (see csrd_scope_cellar.py).
Standard library only. Not legal advice.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import math
import re
import sys
from pathlib import Path

VERSION = "0.1.0"
HERE = Path(__file__).resolve().parent
# The wheel installs data/ as the package csrd_scope_data next to this module.
DATA_DIRS = (HERE / "data", HERE / "csrd_scope_data")

# Thresholds. Primary sources, checked 2026-09-24 against the texts in data/legal_basis.json:
# Art. 19a(1) and 29a(1) Directive 2013/34/EU as amended by Directive (EU) 2026/470
# (consolidated 02013L0034-20260318); Art. 5(2) Directive (EU) 2022/2464 (consolidated
# 02022L2464-20260318).
NET_TURNOVER_EUR = 450_000_000
EMPLOYEES = 1_000
# Art. 5(2) first subparagraph point (a) Directive (EU) 2022/2464: financial years 2024-2026.
WAVE1_EMPLOYEES = 500
# Art. 40a(1) second, fourth and fifth subparagraphs Directive 2013/34/EU (as amended by 2026/470).
SUBSIDIARY_OR_BRANCH_EUR = 200_000_000
THIRD_COUNTRY_EU_TURNOVER_EUR = 450_000_000
# Art. 3(4) and 3(7): balance sheet total, net turnover, employees. Adjusted by Delegated
# Directive (EU) 2023/2775 for financial years beginning on or after 1 January 2024
# (Member States may allow them from 1 January 2023); before: 02013L0034-20230105.
LARGE_FROM_2024 = (25_000_000, 50_000_000, 250)
LARGE_BEFORE_2024 = (20_000_000, 40_000_000, 250)
# Financial years are named by the calendar year in which they start ("FY2027" starts in 2027).
FIRST_WAVE1_FY, LAST_WAVE1_FY = 2024, 2026           # Art. 5(2) first subpara (a), as amended by 2026/470
FIRST_NEW_FY = 2027                                   # Art. 5(2) first subpara (b), as amended by 2025/794
FIRST_40A_FY = 2028                                   # Art. 5(2) second subparagraph
DEROGATION_FYS = (2025, 2026)                         # Art. 5(2) fifth subparagraph, added by 2026/470

# Tool limits (this tool's choices, not legal thresholds).
MAX_YEARS, MIN_YEAR, MAX_YEAR = 30, 2000, 2050
MAX_AMOUNT, MAX_EMPLOYEES, MAX_ENTITIES, MAX_NAME = 1e15, 10_000_000, 200, 200

YES, NO, DEPENDS, NA = "yes", "no", "depends", "not applicable"

ATTRIBUTION = ("Source: EUR-Lex / CELLAR (Publications Office of the European Union), © European Union, "
               "reused under CC BY 4.0 (https://commission.europa.eu/legal-notice_en); legal texts {celex}; "
               "retrieved {checked}. Derived: csrd-scope's encoding of the provisions cited, not the text itself.")
NOT_COVERED = (
    "Not legal advice. The answer is at EU-directive level; the obligation applies through the national law of "
    "the Member State concerned. Not covered: the content of the reports (European Sustainability Reporting "
    "Standards, Commission Delegated Regulation (EU) 2023/2772 and later delegated acts under Art. 29b), assurance "
    "(Art. 34 Directive 2013/34/EU, Directive 2006/43/EC), due diligence (Directive (EU) 2024/1760, CSDDD), and "
    "EU Taxonomy disclosures (Art. 8 Regulation (EU) 2020/852, Delegated Regulation (EU) 2021/2178).")

QUESTIONS = {
    "national-law": (
        "Which national provisions transpose Directive (EU) 2026/470 (deadline 19 March 2027) and Directive (EU) "
        "2025/794 (deadline 31 December 2025) for this undertaking, and from which financial year do they apply?",
        ["OMNI-5-1", "STC-3"]),
    "two-dates": (
        "Does national law require the thresholds to be exceeded (or no longer exceeded) on two consecutive balance "
        "sheet dates before the obligation starts (or ends)? Art. 3(10) sets that rule only for the size categories "
        "of Art. 3(1)-(7); the Commission's Notice says timing follows the national measures.",
        ["AD-3-10", "NOTICE-FAQ1", "NOTICE-FAQ2"]),
    "employees": (
        "Is the average number of employees computed as national law requires (full-time equivalents or headcount, "
        "part-time and temporary staff)? Union law does not regulate the calculation.",
        ["NOTICE-FAQ3", "OMNI-rec-7"]),
    "derogation": (
        "Has the Member State used the option to exempt undertakings or issuers that do not exceed EUR 450 000 000 "
        "net turnover or 1 000 employees from reporting for the financial years starting in 2025 and 2026?",
        ["CSRD-5-2-derogation", "OMNI-rec-31"]),
    "art40": (
        "Art. 40 treats a public-interest entity as a large undertaking regardless of its figures, while Art. 5(2)(a) "
        "of Directive (EU) 2022/2464 refers to large undertakings 'within the meaning of Article 3(4)'. Which reading "
        "does national law follow for this undertaking?",
        ["AD-40", "CSRD-5-2-a", "AD-3-4"]),
    "fy2023-thresholds": (
        "Which size thresholds apply to the financial year starting in 2023 when Art. 3(10) compares two years: those "
        "before Delegated Directive (EU) 2023/2775, or the adjusted ones (Member States may allow them from financial "
        "years beginning on or after 1 January 2023)?",
        ["DD-2-1", "ADOLD-3-4", "AD-3-4"]),
    "crd-excluded": (
        "Is this credit institution one of those listed in points (2) to (23) of Article 2(5) of Directive "
        "2013/36/EU, and has the Member State used the option not to apply the sustainability reporting rules to it?",
        ["AD-1-3-2"]),
    "subsidiary-exemption": (
        "Are the conditions of the subsidiary exemption met: inclusion in the parent's consolidated management report "
        "(or, for a third-country parent, consolidated reporting under ESRS or equivalent standards), and the "
        "disclosures and publication listed in the second subparagraph of Art. 19a(9) or Art. 29a(8)?",
        ["AD-19a-9", "AD-29a-8"]),
    "subsidiary-exemption-listed": (
        "Before Directive (EU) 2026/470 the subsidiary exemption did not apply to large undertakings whose securities "
        "are admitted to trading on an EU regulated market; the amended text removes that exception through national "
        "law (deadline 19 March 2027). Does national law allow the exemption for the financial years starting in 2025 "
        "and 2026?",
        ["AD2024-19a-10", "AD-19a-10", "AD2024-29a-9", "AD-29a-9"]),
    "fhu": (
        "Is the parent a financial holding undertaking (Art. 2(15)) whose subsidiaries' business models and operations "
        "are independent of one another, so that it may choose not to report consolidated sustainability information "
        "(Art. 29a(7a), inserted by Directive (EU) 2026/470)?",
        ["AD-2-15", "AD-29a-7a"]),
    "fhu-40a": (
        "Is the third-country undertaking a financial holding undertaking whose subsidiaries' business models and "
        "operations are independent of one another, so that its EU subsidiaries and branches may decide not to publish "
        "the Art. 40a report?",
        ["AD-2-15", "AD-40a-1-7"]),
    "bank-parent-form": (
        "Art. 1(3) extends Art. 29a to credit institutions and insurance undertakings of any legal form only where the "
        "undertaking itself exceeds EUR 450 000 000 net turnover and 1 000 employees. Is this parent, whose legal form "
        "is not in Annex I or II, subject to Art. 29a when only its group exceeds them?",
        ["AD-1-3", "AD-29a-1"]),
    "issuer": (
        "Which law of the home Member State applies to the issuer, and does the issuer report under third-country "
        "standards found equivalent under Art. 23(4) of Directive 2004/109/EC?",
        ["TD-2-1-d", "TD-4-5", "NOTICE-fn18"]),
    "debt-only": (
        "Are the only securities admitted to trading on an EU regulated market debt securities with a denomination per "
        "unit of at least EUR 100 000? Such issuers are exempt from Art. 4 of Directive 2004/109/EC.",
        ["TD-8-1-b"]),
    "fund": (
        "Art. 1(4) excludes AIFs and UCITS from Arts. 19a, 29a and 29d. Does the issuer route of Art. 4(5) of Directive "
        "2004/109/EC ('when drawn up by undertakings referred to in those provisions') reach this listed fund?",
        ["AD-1-4", "SFDR-2-12", "TD-4-5"]),
    "40a-two-years": (
        "For the report on a given financial year, which are 'the last two consecutive financial years': that year and "
        "the one before, or the two years before it? The result differs on the figures given.",
        ["AD-40a-1-5"]),
    "40a-branch": (
        "Does 'a subsidiary undertaking as referred to in the first subparagraph' mean any EU subsidiary, or only one "
        "above EUR 200 000 000 net turnover? The branch obligation turns on it here; the Commission described the "
        "pre-2026 rule as applying 'in the absence of such subsidiary'.",
        ["AD-40a-1-4", "NOTICE-40a"]),
    "40a-publisher": (
        "Which EU subsidiary or branch in each Member State publishes the Art. 40a report (Member States may let one "
        "provide a link to another's report)?",
        ["AD-40a-1-1", "NOTICE-FAQ43"]),
    "eu-subsidiaries-own-scope": (
        "Is any EU subsidiary itself above the Art. 19a(1) or Art. 29a(1) thresholds? An Art. 40a report does not "
        "exempt it; until 6 January 2030 one EU subsidiary may report for all of them (Art. 48i). Assess each one "
        "separately with eu_undertaking=true.",
        ["NOTICE-FAQ48", "AD-48i-1"]),
    "designated-pie": (
        "Has the Member State designated undertakings of this kind as public-interest entities (Art. 2(1)(d))? If so, "
        "the result for the financial years starting in 2024 to 2026 changes.",
        ["AD-2-1"]),
    "set-off": (
        "Were the consolidated figures for the large-group test calculated with the set-off and eliminations of "
        "Art. 24(3) and (7)? Without them, Art. 3(8) raises the balance sheet total and net turnover limits by 20 %.",
        ["AD-3-8"]),
}


class InputError(ValueError):
    """The input does not meet the schema; .errors lists every problem found."""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


# ------------------------------------------------------------------ data

class Data:
    def __init__(self, directory: Path | None = None):
        d = directory or next((p for p in DATA_DIRS if (p / "legal_basis.json").exists()), None)
        if d is None:
            raise FileNotFoundError("bundled data/legal_basis.json not found; reinstall csrd-scope or run `csrd-scope refresh`")

        def load(name):
            return json.loads((d / name).read_text(encoding="utf-8"))
        self.dir = d
        self.legal = load("legal_basis.json")
        self.nim = load("national_measures.json")
        self.ms = load("member_states.json")
        self.forms = load("legal_forms.json")
        self.quotes = self.legal["quotes"]
        self.by_alpha2 = {m["alpha2"]: m for m in self.ms["member_states"]}
        for m in self.ms["member_states"]:
            if m.get("isg") and m["isg"] != m["alpha2"]:
                self.by_alpha2[m["isg"]] = m  # "EL" for Greece, as EU texts write it

    def version(self) -> dict:
        lb = self.legal
        cons = lb["consolidated_versions"]

        def later(base):
            pinned = lb["pinned"][base]
            return [v for v in cons.get(base, []) if v["celex"] > pinned]
        return {
            "directive_2013_34_eu": {"celex": "32013L0034", "consolidated_version": lb["pinned"]["32013L0034"],
                                     "consolidated_version_date": _cons_date(lb["pinned"]["32013L0034"]),
                                     "later_versions_listed": later("32013L0034"),
                                     "note": "02013L0034-20270130 differs from the version used only in its list of amending acts (see data/SOURCES.md)."},
            "directive_2022_2464_eu": {"celex": "32022L2464", "consolidated_version": lb["pinned"]["32022L2464"],
                                       "consolidated_version_date": _cons_date(lb["pinned"]["32022L2464"])},
            "amending_acts_applied": [
                {"act": "Directive (EU) 2026/470", "celex": "32026L0470", "oj": "OJ L, 2026/470, 26.2.2026",
                 "in_force": "2026-03-18", "transposition_deadline": "2027-03-19"},
                {"act": "Directive (EU) 2025/794", "celex": "32025L0794", "oj": "OJ L, 2025/794, 16.4.2025",
                 "in_force": "2025-04-17", "transposition_deadline": "2025-12-31"},
                {"act": "Commission Delegated Directive (EU) 2023/2775", "celex": "32023L2775",
                 "oj": "OJ L, 2023/2775, 21.12.2023", "applies_from": "financial years beginning on or after 2024-01-01",
                 "transposition_deadline": "2024-12-24"},
            ],
            "other_sources": ["02004L0109-20240109 (Directive 2004/109/EC)", "02019R2088-20260702 (Regulation (EU) 2019/2088)",
                              "52024XC06792 (Commission Notice C/2024/6792, interpretative, not binding)"],
            "checked": lb["checked"],
            "source": lb["endpoint"],
            "consolidated_text_status": self.quotes["consolidated-disclaimer"]["text"],
        }

    def attribution(self) -> str:
        return ATTRIBUTION.format(celex="32013L0034 (consolidated 02013L0034-20260318), 32022L2464 (consolidated "
                                  "02022L2464-20260318), 32026L0470, 32025L0794, 32023L2775, 32004L0109, 32019R2088, "
                                  "52024XC06792", checked=self.legal["checked"])

    def provisions(self, ids) -> dict:
        return {i: {"cite": self.quotes[i]["cite"], "celex": self.quotes[i]["celex"], "text": self.quotes[i]["text"]}
                for i in sorted(set(ids)) if i in self.quotes}

    def national(self, alpha2: str) -> dict:
        m = self.by_alpha2[alpha2]
        out = {"member_state": m["alpha2"], "name": m["name"], "as_of": self.nim["checked"], "directives": []}
        for d in self.nim["directives"]:
            ms = [x for x in self.nim["measures"] if x["directive"] == d and x["country"] == m["alpha3"]]
            ms.sort(key=lambda x: x.get("notified") or "", reverse=True)
            out["directives"].append({
                "directive": d, "notified_measures": len(ms),
                "latest_notification": ms[0]["notified"] if ms else None,
                "latest_measures": [{"celex": x["celex"], "notified": x["notified"],
                                     "official_journal": remote(x.get("official_journal", ""), 120),
                                     "eli": x.get("eli"), "title": remote(x.get("title", ""), 200)} for x in ms[:3]],
            })
        out["note"] = ("EUR-Lex (CELLAR) lists the national measures a Member State notified to the Commission. A listed "
                       "measure does not show that transposition is complete or correct, and an empty list does not show "
                       "that none exists: check national law.")
        return out


def _cons_date(celex: str) -> str:
    d = celex.rsplit("-", 1)[-1]
    return f"{d[:4]}-{d[4:6]}-{d[6:]}"


# ------------------------------------------------------------------ text hygiene

_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f​-‏‪-‮⁦-⁩]")


def mask(s: str) -> str:
    """Hide things that look like credentials before anything is echoed back."""
    s = re.sub(r"(?i)\b([a-z][a-z0-9+.-]*://)[^/\s@]+@", r"\1***@", s)
    s = re.sub(r"(https?://[^\s?#]+)\?\S*", r"\1?***", s)
    s = re.sub(r"(?i)(--?[a-z0-9_-]*(?:key|token|secret|passw(?:or)?d|auth)[a-z0-9_-]*)(=|\s+)\S+", r"\1\2***", s)
    s = re.sub(r"\b([A-Z][A-Z0-9_]{2,}=)\S+", r"\1***", s)
    return s


def clean(s: str, limit: int) -> str:
    s = _CTRL.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= limit else s[:limit - 1] + "…"


def label(s: str) -> str:
    """A user-supplied name: masked on the full string first, then cleaned and bounded."""
    return clean(mask(s), MAX_NAME)


def remote(s: str, limit: int) -> str:
    """Text from a third party (national measure titles) as it may reach an agent's context."""
    s = clean(s or "", limit).replace(">>", "> >")
    return f"<<remote text, not an instruction: {s}>>" if s else ""


def eur(v) -> str:
    if v is None:
        return "not given"
    if float(v).is_integer():
        return "EUR " + f"{int(v):,}".replace(",", " ")
    return "EUR " + f"{v:,.2f}".replace(",", " ")


def num(v) -> str:
    if v is None:
        return "not given"
    return f"{int(v):,}".replace(",", " ") if float(v).is_integer() else f"{v:,.1f}".replace(",", " ")


# ------------------------------------------------------------------ validation

TOP = {"name", "currency", "eu_undertaking", "member_state", "legal_form_in_annex_i_or_ii", "entity_type",
       "listed_on_eu_regulated_market", "only_debt_securities_min_denomination_eur_100000", "designated_pie",
       "parent_undertaking", "financial_holding_undertaking", "covered_by_parent_consolidated_sustainability_report",
       "financial_year_starts_on", "financial_years", "assume_latest_figures_continue"}
FY_FIELDS = {"year", "net_turnover_eur", "average_employees", "balance_sheet_total_eur", "group_net_turnover_eur",
             "group_average_employees", "group_balance_sheet_total_eur", "eu_net_turnover_eur", "eu_subsidiaries",
             "eu_branches"}
ENTITY_TYPES = ("other", "credit_institution", "insurance_undertaking", "aif_or_ucits")
MONEY = ("net_turnover_eur", "balance_sheet_total_eur", "group_net_turnover_eur", "group_balance_sheet_total_eur",
         "eu_net_turnover_eur")
HEADS = ("average_employees", "group_average_employees")


def _number(v, where: str, cap: float, errors: list):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        errors.append(f"{where}: must be a number (got {type(v).__name__}); write amounts as plain numbers in EUR, e.g. 480000000")
        return None
    if isinstance(v, float) and not math.isfinite(v):
        errors.append(f"{where}: must be a finite number")
        return None
    if v < 0 or v > cap:
        errors.append(f"{where}: must be between 0 and {cap:g}")
        return None
    return v


def _bool(x: dict, key: str, errors: list, default=None, nullable=False):
    if key not in x:
        return default
    v = x[key]
    if v is None and nullable:
        return None
    if not isinstance(v, bool):
        errors.append(f"{key}: must be true or false{' or null' if nullable else ''}")
        return default
    return v


def validate(inputs, data: Data) -> dict:
    errors: list[str] = []
    if not isinstance(inputs, dict):
        raise InputError(["input must be a JSON object"])
    unknown = sorted(set(inputs) - TOP)
    if unknown:
        errors.append(f"unknown field(s): {', '.join(clean(str(k), 60) for k in unknown)}")
    cur = inputs.get("currency")
    if cur != "EUR":
        errors.append("currency: must be \"EUR\". State every amount in euro; convert other currencies yourself at the "
                      "rate your accounting framework or national law prescribes. csrd-scope never converts.")
    x: dict = {"name": None}
    if "name" in inputs:
        if not isinstance(inputs["name"], str):
            errors.append("name: must be a string")
        else:
            x["name"] = label(inputs["name"])
    eu = inputs.get("eu_undertaking")
    if not isinstance(eu, bool):
        errors.append("eu_undertaking: required, true if the undertaking is governed by the law of an EU Member State")
        eu = True
    x["eu"] = eu
    ms = inputs.get("member_state")
    x["member_state"] = None
    if ms is not None:
        if not isinstance(ms, str) or ms.strip().upper() not in data.by_alpha2:
            errors.append("member_state: must be the two-letter code of an EU Member State (e.g. DE, FR, EL or GR)")
        else:
            x["member_state"] = data.by_alpha2[ms.strip().upper()]["alpha2"]
    et = inputs.get("entity_type", "other")
    if et not in ENTITY_TYPES:
        errors.append(f"entity_type: one of {', '.join(ENTITY_TYPES)}")
        et = "other"
    x["entity_type"] = et
    x["legal_form"] = None
    if "legal_form_in_annex_i_or_ii" in inputs:
        x["legal_form"] = _bool(inputs, "legal_form_in_annex_i_or_ii", errors, nullable=True)
    elif eu and et == "other":
        errors.append("legal_form_in_annex_i_or_ii: required for EU undertakings (true, false, or null if unknown); "
                      "Annex I lists limited-liability forms such as AG, GmbH, SA, SARL, BV, NV")
    x["listed"] = _bool(inputs, "listed_on_eu_regulated_market", errors, default=False)
    x["debt_only"] = _bool(inputs, "only_debt_securities_min_denomination_eur_100000", errors, default=None, nullable=True)
    x["designated"] = _bool(inputs, "designated_pie", errors, default=None, nullable=True)
    x["designated_given"] = "designated_pie" in inputs and inputs["designated_pie"] is not None
    x["parent"] = _bool(inputs, "parent_undertaking", errors, default=False)
    x["fhu"] = _bool(inputs, "financial_holding_undertaking", errors, default=False)
    x["covered"] = _bool(inputs, "covered_by_parent_consolidated_sustainability_report", errors, default=False)
    x["project"] = _bool(inputs, "assume_latest_figures_continue", errors, default=True)
    start = inputs.get("financial_year_starts_on", "01-01")
    x["fy_start"] = "01-01"
    if not isinstance(start, str) or not re.fullmatch(r"(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])", start):
        errors.append("financial_year_starts_on: MM-DD, e.g. 01-01 or 07-01")
    else:
        try:
            _dt.date(2001, int(start[:2]), int(start[3:]))
            x["fy_start"] = start
        except ValueError:
            errors.append("financial_year_starts_on: not a date that exists every year (29 February is not accepted)")
    fys = inputs.get("financial_years")
    x["years"] = {}
    if not isinstance(fys, list) or not fys:
        errors.append("financial_years: required, a list of 1 to 30 objects, one per financial year")
        fys = []
    if len(fys) > MAX_YEARS:
        errors.append(f"financial_years: at most {MAX_YEARS} entries")
        fys = fys[:MAX_YEARS]
    for i, fy in enumerate(fys):
        where = f"financial_years[{i}]"
        if not isinstance(fy, dict):
            errors.append(f"{where}: must be an object")
            continue
        bad = sorted(set(fy) - FY_FIELDS)
        if bad:
            errors.append(f"{where}: unknown field(s): {', '.join(clean(str(k), 60) for k in bad)}")
        y = fy.get("year")
        if isinstance(y, bool) or not isinstance(y, int) or not MIN_YEAR <= y <= MAX_YEAR:
            errors.append(f"{where}.year: an integer from {MIN_YEAR} to {MAX_YEAR} (the calendar year in which the financial year starts)")
            continue
        if y in x["years"]:
            errors.append(f"{where}.year: {y} appears twice")
            continue
        rec = {}
        for k in MONEY:
            if k in fy and fy[k] is not None:
                rec[k] = _number(fy[k], f"{where}.{k}", MAX_AMOUNT, errors)
        for k in HEADS:
            if k in fy and fy[k] is not None:
                rec[k] = _number(fy[k], f"{where}.{k}", MAX_EMPLOYEES, errors)
        for k in ("eu_subsidiaries", "eu_branches"):
            if k not in fy or fy[k] is None:
                continue
            lst = fy[k]
            if not isinstance(lst, list) or len(lst) > MAX_ENTITIES:
                errors.append(f"{where}.{k}: a list of at most {MAX_ENTITIES} objects {{name, net_turnover_eur}}")
                continue
            out = []
            for j, ent in enumerate(lst):
                if not isinstance(ent, dict) or set(ent) - {"name", "net_turnover_eur"} or "net_turnover_eur" not in ent:
                    errors.append(f"{where}.{k}[{j}]: an object with net_turnover_eur and an optional name")
                    continue
                nm = ent.get("name", f"{k[3:-1]} {j + 1}")
                if not isinstance(nm, str):
                    errors.append(f"{where}.{k}[{j}].name: must be a string")
                    continue
                v = _number(ent["net_turnover_eur"], f"{where}.{k}[{j}].net_turnover_eur", MAX_AMOUNT, errors)
                out.append({"name": label(nm), "net_turnover_eur": v})
            rec[k] = out
        if eu and any(k in rec for k in ("eu_net_turnover_eur", "eu_subsidiaries", "eu_branches")):
            errors.append(f"{where}: eu_net_turnover_eur, eu_subsidiaries and eu_branches are for third-country undertakings (eu_undertaking=false)")
        if not x["parent"] and any(k.startswith("group_") for k in rec):
            errors.append(f"{where}: group figures given but parent_undertaking is not true")
        x["years"][y] = rec
    if errors:
        raise InputError(errors)
    return x


# ------------------------------------------------------------------ three-valued logic

def AND(*xs):
    if any(v is False for v in xs):
        return False
    return True if all(v is True for v in xs) else None


def OR(*xs):
    if any(v is True for v in xs):
        return True
    return False if all(v is False for v in xs) else None


def gt(v, limit):
    return None if v is None else v > limit


def two_of_three(a, b, c):
    t = sum(v is True for v in (a, b, c))
    f = sum(v is False for v in (a, b, c))
    return True if t >= 2 else False if f >= 2 else None


def status(v) -> str:
    return YES if v is True else NO if v is False else DEPENDS


# ------------------------------------------------------------------ the rules

class Assessor:
    def __init__(self, x: dict, data: Data):
        self.x, self.d = x, data
        self.years = x["years"]
        self.last = max(self.years)
        self.first = min(self.years)
        self.questions: dict = {}
        self.facts: list[str] = []
        self.cites: set = set()
        self._large: dict = {}

    # -- figures
    def get(self, year: int, key: str):
        if year in self.years:
            return self.years[year].get(key)
        if self.x["project"] and year > self.last:
            return self.years[self.last].get(key)
        return None

    def has(self, year: int, key: str) -> bool:
        return year in self.years and key in self.years[year] or (self.x["project"] and year > self.last and key in self.years[self.last])

    def figures_source(self, year: int) -> str:
        if year in self.years:
            return "supplied"
        if self.x["project"] and year > self.last:
            return f"projected from FY{self.last} (assume_latest_figures_continue)"
        return "not supplied"

    def starts_on(self, year: int) -> str:
        return f"{year}-{self.x['fy_start']}"

    def ask(self, qid: str):
        if qid not in self.questions:
            text, cites = QUESTIONS[qid]
            self.questions[qid] = {"id": qid, "question": text, "cites": cites}
            self.cites.update(cites)

    def need(self, fact: str):
        if fact not in self.facts:
            self.facts.append(fact)

    # -- criteria
    def new_test(self, year: int, group: bool):
        """Art. 19a(1)/29a(1): both thresholds exceeded on the balance sheet date of the year."""
        pre = "group_" if group else ""
        return AND(gt(self.get(year, pre + "net_turnover_eur"), NET_TURNOVER_EUR),
                   gt(self.get(year, pre + "average_employees"), EMPLOYEES))

    def with_prior_year(self, year: int, test, what: str):
        """Literal reading: the year's own balance sheet date. If national law adds a two-date rule, the
        answer changes only where the two years differ; that case returns None and asks counsel."""
        cur, prev = test(year), test(year - 1)
        if cur is None:
            return None
        if prev is None:
            self.ask("two-dates")
            self.need(f"FY{year - 1} figures ({what}): they show whether a two-balance-sheet-date rule in national "
                      f"law would change the answer for FY{year}")
            return cur
        if prev == cur:
            return cur
        self.ask("two-dates")
        return None

    def large_raw(self, year: int, group: bool):
        pre = "group_" if group else ""
        bst, to, emp = (self.get(year, pre + k) for k in ("balance_sheet_total_eur", "net_turnover_eur", "average_employees"))

        def test(lim):
            return two_of_three(gt(bst, lim[0]), gt(to, lim[1]), gt(emp, lim[2]))
        if year >= 2024:
            return test(LARGE_FROM_2024)
        if year == 2023:
            old, new = test(LARGE_BEFORE_2024), test(LARGE_FROM_2024)
            if old == new:
                return old
            self.ask("fy2023-thresholds")
            return None
        return test(LARGE_BEFORE_2024)

    def large_status(self, year: int, group: bool, depth: int = 0):
        """Art. 3(10): a change of size category counts only if it occurs in two consecutive financial years."""
        key = (year, group)
        if key in self._large:
            return self._large[key]
        cur = self.large_raw(year, group)
        prev = self.large_raw(year - 1, group) if depth < 10 else None
        if cur is None:
            res = None
        elif prev is None:
            what = "consolidated balance sheet total, net turnover and employees" if group else "balance sheet total, net turnover and employees"
            self.need(f"FY{year - 1} {what}: Art. 3(10) compares two consecutive financial years to decide the size category for FY{year}")
            res = None
        elif prev == cur:
            res = cur
        else:
            res = self.large_status(year - 1, group, depth + 1)
        self._large[key] = res
        return res

    def pie(self):
        x = self.x
        listed = x["listed"] and x["eu"]
        fin = x["entity_type"] in ("credit_institution", "insurance_undertaking")
        designated = x["designated"] if x["designated_given"] else False
        return OR(listed, fin, designated)

    def coverage(self):
        """Art. 1(1) with Annexes I and II; Art. 1(3) for credit institutions and insurance undertakings."""
        if self.x["entity_type"] in ("credit_institution", "insurance_undertaking"):
            return True
        return self.x["legal_form"]

    # -- routes
    def route_19a(self, y: int) -> dict:
        x = self.x
        r = {"route": "individual sustainability reporting (Art. 19a Directive 2013/34/EU)"}
        if x["entity_type"] == "aif_or_ucits":
            self.cites.update(["AD-1-4", "SFDR-2-12"])
            return {**r, "status": NO, "because": "AIFs and UCITS are excluded from Arts. 19a, 29a and 29d (Art. 1(4)).",
                    "cites": ["AD-1-4", "SFDR-2-12"]}
        emp, to = self.get(y, "average_employees"), self.get(y, "net_turnover_eur")
        if y <= LAST_WAVE1_FY:
            cites = ["CSRD-5-2-a", "AD-2-1", "AD-3-4", "AD-3-10"]
            pie = self.pie()
            if pie is False or self.coverage() is False:
                why = "not a public-interest entity (Art. 2(1))" if pie is False else "legal form not in Annex I or II (Art. 1(1))"
                return {**r, "status": NO, "because": "Not in the set reporting for financial years starting in 2024-2026 "
                        f"(Art. 5(2) first subparagraph point (a)(i) Directive (EU) 2022/2464): {why}.", "cites": cites}
            large = self.large_status(y, False)
            e500 = self.with_prior_year(y, lambda z: gt(self.get(z, "average_employees"), WAVE1_EMPLOYEES), "average employees")
            if pie is True and large is False and e500 is True:
                self.ask("art40")
                cites.append("AD-40")
                large = None
            w1 = AND(self.coverage(), pie, large, e500)
            detail = (f"public-interest entity: {status(pie)}; large undertaking (Art. 3(4), two-year rule of Art. 3(10)): "
                      f"{status(large)}; average employees {num(emp)} > {WAVE1_EMPLOYEES}: {status(e500)}")
            if w1 is False:
                return {**r, "status": NO, "because": "Not in the set reporting for financial years starting in 2024-2026 "
                        f"(Art. 5(2) first subparagraph point (a)(i) Directive (EU) 2022/2464): {detail}.", "cites": cites}
            if w1 is None:
                return {**r, "status": DEPENDS, "because": f"Cannot decide the 2024-2026 test: {detail}.", "cites": cites}
            if y == FIRST_WAVE1_FY:
                res = {**r, "status": YES, "because": f"Reports for FY2024 under Art. 5(2) first subparagraph point (a)(i): {detail}.", "cites": cites}
            else:
                new = self.new_test(y, False)
                cites = cites + ["CSRD-5-2-derogation"]
                if new is True:
                    res = {**r, "status": YES, "because": f"Reports under point (a)(i) ({detail}); the Member State option for "
                           f"2025-2026 does not reach it because it exceeds {eur(NET_TURNOVER_EUR)} and {num(EMPLOYEES)} employees.", "cites": cites}
                else:
                    self.ask("derogation")
                    res = {**r, "status": DEPENDS, "because": f"In the 2024-2026 set ({detail}), but the Member State may exempt it for "
                           f"FY{y} because it does not exceed both {eur(NET_TURNOVER_EUR)} and {num(EMPLOYEES)} employees "
                           f"(net turnover {eur(to)}, {num(emp)} employees): check national law.", "cites": cites}
            return self.exemption(res, y, individual=True)
        cites = ["AD-19a-1", "CSRD-5-2-b"]
        if x["entity_type"] in ("credit_institution", "insurance_undertaking"):
            cites.append("AD-1-3")
        t = self.with_prior_year(y, lambda z: self.new_test(z, False), "net turnover and average employees")
        v = AND(self.coverage(), t)
        numbers = f"net turnover {eur(to)} (threshold {eur(NET_TURNOVER_EUR)}), average employees {num(emp)} (threshold {num(EMPLOYEES)})"
        if v is True:
            res = {**r, "status": YES, "because": f"{numbers}: both exceeded (Art. 19a(1); applies from financial years starting "
                   "on or after 1 January 2027, Art. 5(2) first subparagraph point (b)(i)).", "cites": cites}
        elif v is False:
            why = "legal form not in Annex I or II (Art. 1(1))" if self.coverage() is False else f"{numbers}: not both exceeded"
            res = {**r, "status": NO, "because": f"{why}.", "cites": cites + (["AD-1-1"] if self.coverage() is False else [])}
        else:
            why = []
            if self.coverage() is None:
                why.append("legal form not stated (Art. 1(1), Annexes I and II)")
            if t is None:
                why.append(f"{numbers}: missing figures, or the result differs between FY{y - 1} and FY{y}")
            res = {**r, "status": DEPENDS, "because": "; ".join(why) + ".", "cites": cites}
        return self.exemption(res, y, individual=True)

    def route_29a(self, y: int) -> dict:
        x = self.x
        r = {"route": "consolidated sustainability reporting (Art. 29a Directive 2013/34/EU)"}
        if x["entity_type"] == "aif_or_ucits":
            return {**r, "status": NO, "because": "AIFs and UCITS are excluded from Arts. 19a, 29a and 29d (Art. 1(4)).",
                    "cites": ["AD-1-4"]}
        gemp, gto = self.get(y, "group_average_employees"), self.get(y, "group_net_turnover_eur")
        if y <= LAST_WAVE1_FY:
            cites = ["CSRD-5-2-a", "AD-2-1", "AD-3-7", "AD-3-10"]
            pie = self.pie()
            if pie is False or self.coverage() is False:
                why = "not a public-interest entity (Art. 2(1))" if pie is False else "legal form not in Annex I or II (Art. 1(1))"
                return {**r, "status": NO, "because": "Not in the set reporting for financial years starting in 2024-2026 "
                        f"(Art. 5(2) first subparagraph point (a)(ii)): {why}.", "cites": cites}
            large = self.large_status(y, True)
            e500 = self.with_prior_year(y, lambda z: gt(self.get(z, "group_average_employees"), WAVE1_EMPLOYEES),
                                        "consolidated average employees")
            w1 = AND(self.coverage(), pie, large, e500)
            detail = (f"public-interest entity: {status(pie)}; parent of a large group (Art. 3(7), two-year rule of Art. 3(10)): "
                      f"{status(large)}; consolidated average employees {num(gemp)} > {WAVE1_EMPLOYEES}: {status(e500)}")
            if large is not None:
                self.ask("set-off")
            if w1 is False:
                return {**r, "status": NO, "because": "Not in the set reporting for financial years starting in 2024-2026 "
                        f"(Art. 5(2) first subparagraph point (a)(ii)): {detail}.", "cites": cites}
            if w1 is None:
                return {**r, "status": DEPENDS, "because": f"Cannot decide the 2024-2026 test: {detail}.", "cites": cites}
            if y == FIRST_WAVE1_FY:
                res = {**r, "status": YES, "because": f"Reports for FY2024 under point (a)(ii): {detail}.", "cites": cites}
            else:
                cites = cites + ["CSRD-5-2-derogation"]
                if self.new_test(y, True) is True:
                    res = {**r, "status": YES, "because": f"Reports under point (a)(ii) ({detail}); above both thresholds on a "
                           "consolidated basis, so the 2025-2026 Member State option does not reach it.", "cites": cites}
                else:
                    self.ask("derogation")
                    res = {**r, "status": DEPENDS, "because": f"In the 2024-2026 set ({detail}), but the Member State may exempt it "
                           f"for FY{y} (consolidated net turnover {eur(gto)}, {num(gemp)} employees): check national law.", "cites": cites}
            return self.fhu(self.exemption(res, y, individual=False), y)
        cites = ["AD-29a-1", "CSRD-5-2-b"]
        t = self.with_prior_year(y, lambda z: self.new_test(z, True), "consolidated net turnover and average employees")
        cov = self.coverage()
        if x["entity_type"] in ("credit_institution", "insurance_undertaking") and x["legal_form"] is not True:
            # Art. 1(3) reaches these regardless of legal form only if the undertaking itself exceeds the thresholds.
            ind = self.new_test(y, False)
            cites.append("AD-1-3")
            if ind is True:
                cov = True
            elif t is True:
                self.ask("bank-parent-form")
                cov = None
            else:
                cov = ind
        v = AND(cov, t)
        numbers = (f"consolidated net turnover {eur(gto)} (threshold {eur(NET_TURNOVER_EUR)}), consolidated average employees "
                   f"{num(gemp)} (threshold {num(EMPLOYEES)})")
        if v is True:
            res = {**r, "status": YES, "because": f"{numbers}: both exceeded (Art. 29a(1); from financial years starting on or "
                   "after 1 January 2027, Art. 5(2) first subparagraph point (b)(ii)).", "cites": cites}
        elif v is False:
            why = "legal form not in Annex I or II (Art. 1(1))" if cov is False and t is not False else f"{numbers}: not both exceeded"
            res = {**r, "status": NO, "because": f"{why}.", "cites": cites}
        else:
            res = {**r, "status": DEPENDS, "because": f"{numbers}: cannot decide (missing figures or legal form, the two years "
                   "differ, or a question for counsel).", "cites": cites}
        return self.fhu(self.exemption(res, y, individual=False), y)

    def route_issuer(self, y: int) -> dict:
        """Art. 4(5) Directive 2004/109/EC with Art. 5(2) third subparagraph Directive (EU) 2022/2464."""
        x = self.x
        r = {"route": "issuer with securities on an EU regulated market (Art. 4(5) Directive 2004/109/EC)"}
        if x["debt_only"] is True:
            return {**r, "status": NO, "because": "Only debt securities with a denomination of at least EUR 100 000: Art. 4 "
                    "Directive 2004/109/EC does not apply (Art. 8(1)(b)).", "cites": ["TD-8-1-b"]}
        if x["debt_only"] is None:
            self.ask("debt-only")
        if x["entity_type"] == "aif_or_ucits":
            self.ask("fund")
            return {**r, "status": DEPENDS, "because": "Listed AIF or UCITS: see the question for counsel.", "cites": ["AD-1-4", "TD-4-5"]}
        self.ask("issuer")
        emp, to = self.get(y, "average_employees"), self.get(y, "net_turnover_eur")
        if y <= LAST_WAVE1_FY:
            cites = ["CSRD-5-2-sub3-a", "TD-2-1-d", "AD-3-4", "AD-3-10"]
            ind = AND(self.large_status(y, False),
                      self.with_prior_year(y, lambda z: gt(self.get(z, "average_employees"), WAVE1_EMPLOYEES), "average employees"))
            grp = AND(x["parent"], self.large_status(y, True),
                      self.with_prior_year(y, lambda z: gt(self.get(z, "group_average_employees"), WAVE1_EMPLOYEES),
                                           "consolidated average employees")) if x["parent"] else False
            w1 = OR(ind, grp)
            if w1 is False:
                return {**r, "status": NO, "because": "Not a large undertaking with more than 500 employees, nor the parent of a "
                        "large group with more than 500 employees (Art. 5(2) third subparagraph point (a)).", "cites": cites}
            if w1 is None:
                return {**r, "status": DEPENDS, "because": "Cannot decide the 2024-2026 issuer test (missing figures or a question for counsel).",
                        "cites": cites}
            if y == FIRST_WAVE1_FY:
                return {**r, "status": YES, "because": "Issuer that is a large undertaking (or parent of a large group) with more "
                        "than 500 employees: reports for FY2024 (Art. 5(2) third subparagraph point (a)).", "cites": cites}
            above = OR(self.new_test(y, False), AND(x["parent"], self.new_test(y, True)))
            if above is True:
                return {**r, "status": YES, "because": "In the 2024-2026 issuer set and above both thresholds, so the 2025-2026 "
                        "Member State option does not reach it.", "cites": cites + ["CSRD-5-2-derogation"]}
            self.ask("derogation")
            return {**r, "status": DEPENDS, "because": f"In the 2024-2026 issuer set, but the Member State may exempt it for FY{y}: "
                    "check national law.", "cites": cites + ["CSRD-5-2-derogation"]}
        cites = ["CSRD-5-2-sub3-b", "TD-4-5", "AD-19a-1", "AD-29a-1"]
        t_ind = self.with_prior_year(y, lambda z: self.new_test(z, False), "net turnover and average employees")
        t_grp = self.with_prior_year(y, lambda z: self.new_test(z, True), "consolidated figures") if x["parent"] else False
        v = OR(t_ind, t_grp)
        numbers = f"net turnover {eur(to)}, {num(emp)} employees" + (
            f"; consolidated {eur(self.get(y, 'group_net_turnover_eur'))}, {num(self.get(y, 'group_average_employees'))} employees"
            if x["parent"] else "")
        return {**r, "status": status(v), "because": f"Issuer test from FY2027 (Art. 5(2) third subparagraph point (b)): {numbers}; "
                f"thresholds {eur(NET_TURNOVER_EUR)} and {num(EMPLOYEES)} employees, both to be exceeded.", "cites": cites}

    def route_40a(self, y: int) -> dict:
        x = self.x
        r = {"route": "third-country undertaking reported through its EU subsidiary or branch (Art. 40a Directive 2013/34/EU)"}
        if y < FIRST_40A_FY:
            return {**r, "status": NA, "because": "Art. 40a applies from financial years starting on or after 1 January 2028 "
                    "(Art. 5(2) second subparagraph Directive (EU) 2022/2464).", "cites": ["CSRD-5-2-sub2"]}
        cites = ["AD-40a-1-1", "AD-40a-1-2", "AD-40a-1-3", "AD-40a-1-4", "AD-40a-1-5", "CSRD-5-2-sub2"]

        def eu_turnover(z):
            return gt(self.get(z, "eu_net_turnover_eur"), THIRD_COUNTRY_EU_TURNOVER_EUR)
        a = AND(eu_turnover(y - 1), eu_turnover(y))        # the report year and the one before
        b = AND(eu_turnover(y - 2), eu_turnover(y - 1))    # the two years before the report year
        if a is not None and b is not None and a != b:
            self.ask("40a-two-years")
            cond = None
        elif a is None or b is None:
            cond = a if b is None and a is False else b if a is None and b is False else None
            if cond is None:
                self.need(f"eu_net_turnover_eur for FY{y - 2}, FY{y - 1} and FY{y} (Art. 40a(1) fifth subparagraph)")
        else:
            cond = a
        prev = y - 1
        subs = self.get(prev, "eu_subsidiaries")
        branches = self.get(prev, "eu_branches")
        qual_subs = [s["name"] for s in (subs or []) if s["net_turnover_eur"] > SUBSIDIARY_OR_BRANCH_EUR]
        qual_br = [b["name"] for b in (branches or []) if b["net_turnover_eur"] > SUBSIDIARY_OR_BRANCH_EUR]
        if qual_subs:
            vehicle = True                      # a subsidiary above EUR 200m carries it (second subparagraph)
        elif subs is None:
            self.need(f"eu_subsidiaries with their net turnover for FY{prev} (Art. 40a(1) second subparagraph); "
                      "an empty list means none")
            vehicle = None
        elif branches is None:
            self.need(f"eu_branches with their net turnover for FY{prev} (Art. 40a(1) fourth subparagraph); "
                      "an empty list means none")
            vehicle = None
        elif qual_br and not subs:
            vehicle = True                      # no EU subsidiary at all, branch above EUR 200m
        elif qual_br:
            self.ask("40a-branch")              # small EU subsidiaries exist, branch above EUR 200m
            vehicle = None
        else:
            vehicle = False
        v = AND(cond, vehicle)
        who = (f"EU subsidiaries above {eur(SUBSIDIARY_OR_BRANCH_EUR)} in FY{prev}: {', '.join(qual_subs) or 'none'}; "
               f"EU branches above it: {', '.join(qual_br) or 'none'}")
        eu_fig = ", ".join(f"FY{z} {eur(self.get(z, 'eu_net_turnover_eur'))}" for z in (y - 2, y - 1, y))
        res = {**r, "status": status(v), "because": f"EU net turnover of the third-country undertaking ({eu_fig}) must exceed "
               f"{eur(THIRD_COUNTRY_EU_TURNOVER_EUR)} in each of the last two consecutive financial years; {who}.", "cites": cites}
        if v is True:
            res["reporting_entities"] = qual_subs or qual_br
            self.ask("40a-publisher")
            if x["fhu"]:
                self.ask("fhu-40a")
                res.update(status=DEPENDS, because=res["because"] + " The financial-holding option may apply (Art. 40a(1), last subparagraph).")
                res["cites"] = cites + ["AD-40a-1-7"]
        if subs:
            self.ask("eu-subsidiaries-own-scope")
        return res

    # -- exemptions and options
    def exemption(self, res: dict, y: int, individual: bool) -> dict:
        if not self.x["covered"] or res["status"] == NO:
            return res
        cite = "AD-19a-9" if individual else "AD-29a-8"
        listed_large_pie = self.x["listed"] and self.x["eu"]
        if y == FIRST_WAVE1_FY and listed_large_pie:
            old = "AD2024-19a-10" if individual else "AD2024-29a-9"
            self.cites.add(old)
            res["because"] += (" The subsidiary exemption was not available for FY2024 to a large undertaking whose securities "
                               "are admitted to trading on an EU regulated market (wording before Directive (EU) 2026/470).")
            res["cites"] = res["cites"] + [old]
            return res
        self.ask("subsidiary-exemption")
        if y in DEROGATION_FYS and listed_large_pie:
            self.ask("subsidiary-exemption-listed")
        res["cites"] = res["cites"] + [cite]
        res["because"] += " Covered by a parent's consolidated sustainability report: exempt if the conditions of the subsidiary exemption are met."
        res["status"] = DEPENDS
        return res

    def fhu(self, res: dict, y: int) -> dict:
        if not self.x["fhu"] or res["status"] == NO or y < min(DEROGATION_FYS):
            return res
        self.ask("fhu")
        res["because"] += " Financial holding undertaking: Art. 29a(7a) lets it choose not to report consolidated information if its conditions are met."
        res["cites"] = res["cites"] + ["AD-29a-7a"]
        res["status"] = DEPENDS
        return res

    # -- assembly
    def run(self) -> dict:
        x = self.x
        end = max(FIRST_40A_FY, self.last)
        window = list(range(FIRST_WAVE1_FY, end + 1))
        by_fy = []
        for y in window:
            routes = []
            if x["eu"]:
                routes.append(self.route_19a(y))
                if x["parent"]:
                    routes.append(self.route_29a(y))
            if x["listed"] and (not x["eu"] or x["entity_type"] == "aif_or_ucits" or
                                (x["legal_form"] is not True and x["entity_type"] == "other")):
                routes.append(self.route_issuer(y))
            if not x["eu"]:
                routes.append(self.route_40a(y))
            for rt in routes:
                self.cites.update(rt.get("cites", []))
            sts = [rt["status"] for rt in routes]
            overall = YES if YES in sts else DEPENDS if DEPENDS in sts else NO
            by_fy.append({"financial_year": f"FY{y}", "year": y, "starts_on": self.starts_on(y),
                          "figures": self.figures_source(y), "in_scope": overall, "routes": routes})

        # A designation as public-interest entity (Art. 2(1)(d)) can only matter for 2024-2026.
        if x["eu"] and not x["designated_given"] and self.pie() is False:
            probe = Assessor({**x, "designated": True, "designated_given": True}, self.d)
            if any(probe.route_19a(y)["status"] != next(r for r in f["routes"] if r["route"].startswith("individual"))["status"]
                   for y, f in zip(window, by_fy) if y <= LAST_WAVE1_FY):
                self.ask("designated-pie")

        firsts = [f for f in by_fy if f["in_scope"] == YES]
        pending = [f for f in by_fy if f["in_scope"] == DEPENDS]
        first = firsts[0] if firsts else None
        earliest_dep = pending[0] if pending else None
        if first and earliest_dep and earliest_dep["year"] < first["year"]:
            frfy = None
        else:
            frfy = first
        overall = YES if firsts else DEPENDS if pending else NO

        if x["eu"]:
            self.ask("national-law")
        if x["eu"] or x["listed"]:
            self.ask("employees")
        if x["entity_type"] == "credit_institution":
            self.ask("crd-excluded")
        notes = []
        if x["entity_type"] in ("credit_institution", "insurance_undertaking"):
            self.cites.add("AD-2-5")
            notes.append("Net turnover of insurance undertakings and credit institutions is defined by reference to Directives "
                         "91/674/EEC and 86/635/EEC (Art. 2(5)); give the figure computed that way.")
        if x["eu"] and x["legal_form"] is None and x["entity_type"] == "other":
            forms = ""
            if x["member_state"]:
                f = self.d.forms
                forms = (f" For {self.d.by_alpha2[x['member_state']]['name']}: Annex I: {f['annex_i'][x['member_state']]}; "
                         f"Annex II (only where all members with unlimited liability are Annex I-type undertakings): "
                         f"{f['annex_ii'][x['member_state']]}.")
            self.need("legal_form_in_annex_i_or_ii: is the undertaking of a type listed in Annex I or Annex II (Art. 1(1))?" + forms)
            self.cites.add("AD-1-1")
        if not x["eu"]:
            notes.append("A third-country undertaking has no obligation of its own under Arts. 19a and 29a; it is reached "
                         "through Art. 4(5) of Directive 2004/109/EC if it is an issuer, and through its EU subsidiaries or "
                         "branches under Art. 40a.")
            self.cites.add("NOTICE-fn18")
        if x["project"] and self.last < end:
            span = f"FY{end}" if self.last + 1 == end else f"FY{self.last + 1} to FY{end}"
            notes.append(f"Figures for {span} repeat the FY{self.last} figures (assume_latest_figures_continue=true); "
                         "other figures can give another answer.")

        summary = self.summary(by_fy, overall, frfy, earliest_dep)
        out = {
            "tool": f"csrd-scope {VERSION}",
            "undertaking": x["name"],
            "question": "Is this undertaking in scope of the CSRD sustainability reporting requirements, and from which financial year?",
            "in_scope": overall,
            "summary": summary,
            "first_reporting_financial_year": (
                {"financial_year": frfy["financial_year"], "starts_on": frfy["starts_on"],
                 "report_published": "with the management report, within 12 months after the balance sheet date (Art. 30(1)); "
                                     "issuers: annual financial report within four months (Art. 4(1) Directive 2004/109/EC)"}
                if frfy else None),
            "earliest_possible_financial_year": earliest_dep["financial_year"] if (earliest_dep and not frfy) else None,
            "by_financial_year": [{k: v for k, v in f.items() if k != "year"} for f in by_fy],
            "rules_applied": self.chain(by_fy),
            "questions_for_counsel": list(self.questions.values()),
            "facts_needed": self.facts,
            "notes": notes,
            "national_law": self.d.national(x["member_state"]) if x["member_state"] else
            {"note": "No member_state given: check the national law that transposes the Directives where the undertaking "
                     "(or, for Art. 40a, its EU subsidiary or branch) is established."},
            "legal_basis_version": self.d.version(),
            "provisions": None,
            "what_this_is_not": NOT_COVERED,
            "attribution": self.d.attribution(),
        }
        self.cites.update(["AD-30-1"])
        out["provisions"] = self.d.provisions(self.cites)
        return out

    def summary(self, by_fy, overall, frfy, dep) -> str:
        parts = []
        run = []
        for f in by_fy:
            if run and run[-1][0] == f["in_scope"]:
                run[-1][2] = f["financial_year"]
            else:
                run.append([f["in_scope"], f["financial_year"], f["financial_year"]])
        for st, a, b in run:
            span = a if a == b else f"{a}-{b}"
            parts.append(f"{span}: {st}")
        head = {YES: "In scope", NO: "Not in scope on the figures given", DEPENDS: "Depends"}[overall]
        first = f"; first reporting financial year {frfy['financial_year']} (starts {frfy['starts_on']})" if frfy else ""
        tail = f"; earliest possible {dep['financial_year']}, subject to the questions and facts listed" if (dep and not frfy) else ""
        return f"{head}{first}{tail}. By financial year: " + ", ".join(parts) + "."

    def chain(self, by_fy) -> list[dict]:
        x = self.x
        steps = []

        def step(rule, result, cites):
            steps.append({"step": len(steps) + 1, "rule": rule, "result": result, "cites": cites})
            self.cites.update(cites)
        if x["eu"]:
            step("Governed by the law of an EU Member State: Directive 2013/34/EU applies to the types of undertaking in "
                 "Annexes I and II, and Art. 1(3) adds credit institutions and insurance undertakings of any legal form.",
                 {True: "legal form covered", False: "legal form not covered", None: "legal form not stated"}[self.coverage()],
                 ["AD-1-1", "AD-1-3"])
            step("Public-interest entity (Art. 2(1)): securities on an EU regulated market, credit institution, insurance "
                 "undertaking, or designated by the Member State. Matters only for financial years starting in 2024-2026.",
                 status(self.pie()), ["AD-2-1"])
        else:
            step("Governed by the law of a third country: no obligation of its own under Arts. 19a/29a; reached as an issuer "
                 "(Art. 4(5) Directive 2004/109/EC) and through EU subsidiaries or branches (Art. 40a).",
                 "issuer" if x["listed"] else "not an issuer", ["NOTICE-fn18", "TD-2-1-d"])
        if x["entity_type"] == "aif_or_ucits":
            step("Art. 1(4): Arts. 19a, 29a and 29d do not apply to AIFs and UCITS.", "excluded", ["AD-1-4", "SFDR-2-12"])
        seen = {}
        for f in by_fy:
            for rt in f["routes"]:
                seen.setdefault(rt["route"], []).append(f"{f['financial_year']}: {rt['status']} - {rt['because']}")
        for route, lines in seen.items():
            cites = sorted({c for f in by_fy for rt in f["routes"] if rt["route"] == route for c in rt.get("cites", [])})
            step(route, lines, cites)
        return steps


def assess(inputs, data: Data | None = None) -> dict:
    """csrd_scope(): validate strictly, then apply the rules. Raises InputError."""
    data = data or Data()
    return Assessor(validate(inputs, data), data).run()


# ------------------------------------------------------------------ reference tables

def thresholds(data: Data | None = None) -> dict:
    d = data or Data()
    items = [
        {"id": "undertaking", "applies_from": "financial years starting on or after 1 January 2027",
         "test": f"net turnover > {eur(NET_TURNOVER_EUR)} AND average number of employees during the financial year > {num(EMPLOYEES)}, "
                 "on the balance sheet date (both criteria)", "cites": ["AD-19a-1", "CSRD-5-2-b"]},
        {"id": "group", "applies_from": "financial years starting on or after 1 January 2027",
         "test": f"parent undertaking of a group whose consolidated net turnover > {eur(NET_TURNOVER_EUR)} AND consolidated average "
                 f"employees > {num(EMPLOYEES)}", "cites": ["AD-29a-1", "CSRD-5-2-b"]},
        {"id": "credit-institutions-and-insurers",
         "test": "any legal form, provided the undertaking itself exceeds the same two thresholds; Member States may exclude the "
                 "institutions in points (2) to (23) of Art. 2(5) of Directive 2013/36/EU", "cites": ["AD-1-3", "AD-1-3-2", "AD-2-5"]},
        {"id": "financial-years-2024-2026",
         "test": f"public-interest entity that is a large undertaking with more than {WAVE1_EMPLOYEES} average employees, or a "
                 f"public-interest entity that is the parent of a large group with more than {WAVE1_EMPLOYEES} (consolidated); "
                 "issuers under Directive 2004/109/EC on the same size tests", "cites": ["CSRD-5-2-a", "CSRD-5-2-sub3-a"]},
        {"id": "member-state-option-2025-2026",
         "test": f"Member States may exempt undertakings or issuers that do not exceed {eur(NET_TURNOVER_EUR)} net turnover or "
                 f"{num(EMPLOYEES)} employees for financial years starting in 2025 and 2026", "cites": ["CSRD-5-2-derogation"]},
        {"id": "large-undertaking",
         "test": f"exceeds at least two of: balance sheet total {eur(LARGE_FROM_2024[0])}, net turnover {eur(LARGE_FROM_2024[1])}, "
                 f"{LARGE_FROM_2024[2]} average employees (financial years beginning on or after 1 January 2024; before: "
                 f"{eur(LARGE_BEFORE_2024[0])}, {eur(LARGE_BEFORE_2024[1])}, {LARGE_BEFORE_2024[2]}); a change counts only if it "
                 "occurs in two consecutive financial years", "cites": ["AD-3-4", "AD-3-7", "AD-3-10", "DD-2-1", "ADOLD-3-4"]},
        {"id": "third-country", "applies_from": "financial years starting on or after 1 January 2028",
         "test": f"third-country undertaking with EU net turnover > {eur(THIRD_COUNTRY_EU_TURNOVER_EUR)} in each of the last two "
                 f"consecutive financial years, with an EU subsidiary whose net turnover > {eur(SUBSIDIARY_OR_BRANCH_EUR)} in the "
                 f"preceding financial year, or (without such a subsidiary) an EU branch above {eur(SUBSIDIARY_OR_BRANCH_EUR)}",
         "cites": ["AD-40a-1-2", "AD-40a-1-4", "AD-40a-1-5", "CSRD-5-2-sub2"]},
        {"id": "protected-undertaking-value-chain",
         "test": f"not a scope test: value-chain undertakings with at most {num(EMPLOYEES)} average employees in the preceding "
                 "financial year may decline requests beyond the voluntary standard", "cites": ["AD-19a-3-protected"]},
    ]
    exclusions = [{"what": "European Financial Stability Facility; AIFs and UCITS (Art. 2(12)(b) and (f) Regulation (EU) 2019/2088)",
                   "cites": ["AD-1-4", "SFDR-2-12"]},
                  {"what": "issuers of only debt securities with a denomination of at least EUR 100 000 (issuer route)",
                   "cites": ["TD-8-1-b"]}]
    ids = [c for i in items for c in i["cites"]] + [c for e in exclusions for c in e["cites"]] + ["AD-3-13", "NOTICE-FAQ3"]
    return {"as_of": d.legal["checked"], "thresholds": items, "exclusions": exclusions,
            "notes": ["Amounts are in euro; csrd-scope never converts currencies.",
                      "Employees: the average number during the financial year; Union law does not regulate the calculation "
                      "(Commission Notice C/2024/6792, FAQ 3).",
                      "The Commission reviews these thresholds for inflation at least every five years by delegated act (Art. 3(13))."],
            "provisions": d.provisions(ids), "legal_basis_version": d.version(), "attribution": d.attribution()}


def timeline(data: Data | None = None) -> dict:
    d = data or Data()
    rows = [
        {"financial_years": "starting 1 January 2024 - 31 December 2026",
         "who": "public-interest entities that are large undertakings with > 500 employees; PIE parents of large groups with "
                "> 500 employees (consolidated); issuers of the same size", "cites": ["CSRD-5-2-a", "CSRD-5-2-sub3-a"]},
        {"financial_years": "starting 1 January 2025 - 31 December 2026",
         "who": "Member States may exempt those not exceeding EUR 450 000 000 net turnover or 1 000 employees",
         "cites": ["CSRD-5-2-derogation"]},
        {"financial_years": "starting on or after 1 January 2027",
         "who": "undertakings and parents of groups (consolidated) exceeding EUR 450 000 000 net turnover and 1 000 employees; "
                "issuers on the same tests", "cites": ["CSRD-5-2-b", "CSRD-5-2-sub3-b", "AD-19a-1", "AD-29a-1"]},
        {"financial_years": "starting on or after 1 January 2028",
         "who": "EU subsidiaries and branches of third-country undertakings (Art. 40a)", "cites": ["CSRD-5-2-sub2", "AD-40a-1-5"]},
    ]
    history = [
        {"act": "Directive (EU) 2022/2464 (CSRD), as adopted", "celex": "32022L2464",
         "set": "other large undertakings from FY2025; listed SMEs, small and non-complex institutions and captive insurers from FY2026"},
        {"act": "Directive (EU) 2025/794, in force 17 April 2025", "celex": "32025L0794",
         "set": "moved those dates to FY2027 and FY2028", "cites": ["STC-1", "STC-4"]},
        {"act": "Directive (EU) 2026/470, in force 18 March 2026", "celex": "32026L0470",
         "set": "replaced them with the EUR 450 000 000 / 1 000-employee tests, deleted the listed-SME set, limited the "
                "2024-2026 set to three financial years, added the 2025-2026 Member State option",
         "cites": ["OMNI-6", "OMNI-5-1"]},
    ]
    deadlines = [
        {"what": "transposition of Directive (EU) 2022/2464", "date": "2024-07-06"},
        {"what": "transposition of Delegated Directive (EU) 2023/2775", "date": "2024-12-24", "cites": ["DD-2-1"]},
        {"what": "transposition of Directive (EU) 2025/794", "date": "2025-12-31", "cites": ["STC-3"]},
        {"what": "transposition of Arts. 1-3 of Directive (EU) 2026/470", "date": "2027-03-19", "cites": ["OMNI-5-1"]},
        {"what": "publication of the management report", "date": "within 12 months after the balance sheet date", "cites": ["AD-30-1"]},
    ]
    ids = [c for r in rows + history + deadlines for c in r.get("cites", [])]
    return {"as_of": d.legal["checked"], "reporting": rows, "history": history, "deadlines": deadlines,
            "note": "Financial years are named by the calendar year in which they start. National law may apply different dates "
                    "where it has not (yet) transposed the amending Directives.",
            "provisions": d.provisions(ids), "legal_basis_version": d.version(), "attribution": d.attribution()}


def sources(member_state: str | None = None, data: Data | None = None) -> dict:
    d = data or Data()
    lb = d.legal
    out = {"legal_basis_version": d.version(),
           "acts": {c: {k: a.get(k) for k in ("title", "date_document", "in_force")} for c, a in lb["acts"].items()},
           "consolidated_versions": lb["consolidated_versions"],
           "amendments_corrigenda_since_2024": lb.get("related_since_2024", []),
           "licence": {"terms": "https://commission.europa.eu/legal-notice_en",
                       "quote": "content owned by the EU on this website is licensed under the Creative Commons Attribution 4.0 "
                                "International (CC BY 4.0) licence. This means that reuse is allowed, provided appropriate credit "
                                "is given and changes are indicated."},
           "endpoint": lb["endpoint"], "attribution": d.attribution()}
    if member_state is not None:
        code = member_state.strip().upper() if isinstance(member_state, str) else ""
        if code not in d.by_alpha2:
            raise InputError(["member_state: must be the two-letter code of an EU Member State"])
        a2 = d.by_alpha2[code]["alpha2"]
        out["national_law"] = d.national(a2)
        out["legal_forms"] = {"annex_i": d.forms["annex_i"][a2], "annex_ii": d.forms["annex_ii"][a2],
                              "source": f"Annexes I and II, {d.forms['source_celex']}"}
    return out


# ------------------------------------------------------------------ text output

def render(res: dict) -> str:
    L = []
    if res.get("undertaking"):
        L.append(res["undertaking"])
    L.append(res["summary"])
    L.append("")
    L.append(f"{'Financial year':<16}{'Starts':<12}{'In scope':<10}Figures")
    for f in res["by_financial_year"]:
        L.append(f"{f['financial_year']:<16}{f['starts_on']:<12}{f['in_scope']:<10}{f['figures']}")
    L.append("")
    L.append("Rules applied:")
    for s in res["rules_applied"]:
        r = s["result"]
        L.append(f" {s['step']}. {s['rule']}  [{', '.join(s['cites'])}]")
        for line in (r if isinstance(r, list) else [r]):
            L.append(f"    - {line}")
    if res["questions_for_counsel"]:
        L.append("")
        L.append("Questions for counsel:")
        for q in res["questions_for_counsel"]:
            L.append(f" - {q['question']}  [{', '.join(q['cites'])}]")
    if res["facts_needed"]:
        L.append("")
        L.append("Facts that would decide what is open:")
        L.extend(f" - {f}" for f in res["facts_needed"])
    for n in res.get("notes", []):
        L.append(f"Note: {n}")
    nl = res.get("national_law", {})
    if nl.get("directives"):
        L.append("")
        L.append(f"National measures notified for {nl['name']} (EUR-Lex/CELLAR, as of {nl['as_of']}):")
        for dd in nl["directives"]:
            L.append(f" - {dd['directive']}: {dd['notified_measures']} measure(s), latest notified {dd['latest_notification'] or '-'}")
        L.append(f"   {nl['note']}")
    v = res["legal_basis_version"]
    L.append("")
    L.append(f"Legal basis: {v['directive_2013_34_eu']['consolidated_version']}, {v['directive_2022_2464_eu']['consolidated_version']}, "
             f"32026L0470, 32025L0794, 32023L2775; checked {v['checked']}. {v['consolidated_text_status']}")
    L.append(res["attribution"])
    L.append(res["what_this_is_not"])
    return "\n".join(L)


# ------------------------------------------------------------------ CLI

def _parse_fy(spec: str) -> dict:
    """--fy 2027,net_turnover_eur=480000000,average_employees=1200"""
    parts = [p.strip() for p in spec.split(",") if p.strip()]
    if not parts or not re.fullmatch(r"\d{4}", parts[0]):
        raise InputError([f"--fy: start with the year, e.g. 2027,net_turnover_eur=480000000 (got {clean(spec, 60)!r})"])
    out: dict = {"year": int(parts[0])}
    for p in parts[1:]:
        k, sep, v = p.partition("=")
        k = k.strip()
        if not sep or k not in FY_FIELDS - {"year", "eu_subsidiaries", "eu_branches"}:
            raise InputError([f"--fy: unknown or malformed item {clean(p, 60)!r}"])
        v = v.strip().replace("_", "")
        if not re.fullmatch(r"\d+(\.\d+)?", v):
            raise InputError([f"--fy: {k} must be a plain number in EUR or employees, e.g. 480000000 (got {clean(v, 30)!r})"])
        out[k] = float(v) if "." in v else int(v)
    return out


def _entity(spec: str) -> tuple[int, dict]:
    """--eu-subsidiary 2027:Name=250000000"""
    m = re.fullmatch(r"(\d{4}):(.{0,200})=(\d[\d_]*(?:\.\d+)?)", spec.strip())
    if not m:
        raise InputError([f"expected YEAR:NAME=NET_TURNOVER_EUR, e.g. 2027:Example GmbH=250000000 (got {clean(spec, 60)!r})"])
    v = m.group(3).replace("_", "")
    return int(m.group(1)), {"name": m.group(2), "net_turnover_eur": float(v) if "." in v else int(v)}


def _tri(v: str | None):
    return None if v in (None, "unknown") else v == "yes"


def build_inputs(a) -> dict:
    if a.input:
        try:
            raw = sys.stdin.read() if a.input == "-" else Path(a.input).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            raise InputError([f"--input: cannot read {clean(a.input, 100)!r} ({type(e).__name__})"]) from None
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise InputError([f"--input: not valid JSON ({e.msg} at line {e.lineno})"]) from None
    if a.eu is None:
        raise InputError(["say --eu or --non-eu (or give --input FILE)"])
    fys = {}
    for spec in a.fy or []:
        f = _parse_fy(spec)
        if f["year"] in fys:
            raise InputError([f"--fy: {f['year']} given twice"])
        fys[f["year"]] = f
    for key, specs in (("eu_subsidiaries", a.eu_subsidiary or []), ("eu_branches", a.eu_branch or [])):
        for spec in specs:
            y, ent = _entity(spec)
            fys.setdefault(y, {"year": y}).setdefault(key, []).append(ent)
    inp = {"currency": "EUR", "eu_undertaking": a.eu, "entity_type": a.entity_type,
           "listed_on_eu_regulated_market": a.listed, "parent_undertaking": a.parent,
           "financial_holding_undertaking": a.financial_holding,
           "covered_by_parent_consolidated_sustainability_report": a.covered_by_parent,
           "financial_year_starts_on": a.fy_start, "assume_latest_figures_continue": not a.no_projection,
           "financial_years": [fys[y] for y in sorted(fys)]}
    if a.name:
        inp["name"] = a.name
    if a.member_state:
        inp["member_state"] = a.member_state
    if a.eu:
        inp["legal_form_in_annex_i_or_ii"] = _tri(a.legal_form)
    if a.designated_pie:
        inp["designated_pie"] = _tri(a.designated_pie)
    if a.debt_only:
        inp["only_debt_securities_min_denomination_eur_100000"] = _tri(a.debt_only)
    return inp


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="csrd-scope", description="Is an undertaking in scope of the CSRD, and from which "
                                 "financial year? EU-directive level, with article citations. Not legal advice.")
    ap.add_argument("--version", action="version", version=f"csrd-scope {VERSION}")
    sub = ap.add_subparsers(dest="cmd")
    c = sub.add_parser("check", help="assess one undertaking")
    c.add_argument("--input", metavar="FILE", help="JSON input (see README); '-' reads stdin")
    g = c.add_mutually_exclusive_group()
    g.add_argument("--eu", dest="eu", action="store_const", const=True, help="governed by the law of an EU Member State")
    g.add_argument("--non-eu", dest="eu", action="store_const", const=False, help="governed by the law of a third country")
    c.add_argument("--name")
    c.add_argument("--member-state", metavar="CC")
    c.add_argument("--legal-form", choices=["yes", "no", "unknown"], default="unknown",
                   help="type listed in Annex I or II of Directive 2013/34/EU (EU undertakings)")
    c.add_argument("--entity-type", choices=ENTITY_TYPES, default="other")
    c.add_argument("--listed", action="store_true", help="securities admitted to trading on an EU regulated market")
    c.add_argument("--debt-only", choices=["yes", "no", "unknown"], help="only debt securities of EUR 100 000 or more per unit")
    c.add_argument("--designated-pie", choices=["yes", "no", "unknown"])
    c.add_argument("--parent", action="store_true", help="parent undertaking of a group (give group_* figures)")
    c.add_argument("--financial-holding", action="store_true")
    c.add_argument("--covered-by-parent", action="store_true", help="included in a parent's consolidated sustainability report")
    c.add_argument("--fy", action="append", metavar="YEAR,key=value,...",
                   help="figures for one financial year, e.g. 2027,net_turnover_eur=480000000,average_employees=1200")
    c.add_argument("--eu-subsidiary", action="append", metavar="YEAR:NAME=EUR")
    c.add_argument("--eu-branch", action="append", metavar="YEAR:NAME=EUR")
    c.add_argument("--fy-start", default="01-01", metavar="MM-DD")
    c.add_argument("--no-projection", action="store_true", help="do not repeat the latest figures for later years")
    c.add_argument("--json", action="store_true")
    for name, hlp in (("thresholds", "current thresholds with articles"), ("timeline", "who reports for which financial year")):
        p = sub.add_parser(name, help=hlp)
        p.add_argument("--json", action="store_true")
    s = sub.add_parser("sources", help="legal basis, versions, licence; national measures and legal forms for one Member State")
    s.add_argument("--member-state", metavar="CC")
    s.add_argument("--json", action="store_true")
    v = sub.add_parser("verify-sources", help="compare live CELLAR metadata with the bundled snapshot (exit 0 same, 1 changed, 2 could not check)")
    v.add_argument("--json", action="store_true")
    r = sub.add_parser("refresh", help="rebuild data/ from CELLAR")
    r.add_argument("--out", metavar="DIR", help="directory to write (default: data/ of a source checkout)")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 2
    try:
        if a.cmd == "check":
            res = assess(build_inputs(a))
            print(json.dumps(res, ensure_ascii=False, indent=1) if a.json else render(res))
            return 0
        if a.cmd in ("thresholds", "timeline", "sources"):
            res = thresholds() if a.cmd == "thresholds" else timeline() if a.cmd == "timeline" else sources(a.member_state)
            print(json.dumps(res, ensure_ascii=False, indent=1) if a.json else _render_table(a.cmd, res))
            return 0
        import csrd_scope_cellar as cellar
        if a.cmd == "verify-sources":
            data = Data()
            try:
                res = cellar.verify(data.legal, nim_snapshot=data.nim)
            except cellar.SourceError as e:
                print(f"could not check: {e}", file=sys.stderr)
                return 2
            if a.json:
                print(json.dumps(res, ensure_ascii=False, indent=1))
            else:
                print(f"snapshot checked {data.legal['checked']}: {res['status']}")
                for f in res["findings"]:
                    print(" - " + ", ".join(f"{k}: {clean(str(v), 200)}" for k, v in f.items()))
            return 1 if res["status"] == "changed" else 0
        if a.cmd == "refresh":
            out = Path(a.out) if a.out else HERE / "data"
            if not a.out and not ((HERE / "pyproject.toml").is_file() and (HERE / "data" / "legal_basis.json").is_file()):
                print("refresh: give --out DIR (this is an installed copy, not a source checkout)", file=sys.stderr)
                return 2
            try:
                snap = cellar.build_snapshot()
            except cellar.SourceError as e:
                print(f"refresh failed, nothing written: {e}", file=sys.stderr)
                return 2
            cellar.write_snapshot(out, snap)
            print(f"wrote {', '.join(snap)} and SOURCES.md to {out}")
            return 0
    except InputError as e:
        print("input error:\n" + "\n".join(f" - {m}" for m in e.errors), file=sys.stderr)
        return 2
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return 2
    return 2


def _render_table(cmd: str, res: dict) -> str:
    L = []
    if cmd == "thresholds":
        for t in res["thresholds"]:
            L.append(f"- {t['id']}{' (' + t['applies_from'] + ')' if t.get('applies_from') else ''}: {t['test']}  [{', '.join(t['cites'])}]")
        for e in res["exclusions"]:
            L.append(f"- excluded: {e['what']}  [{', '.join(e['cites'])}]")
        L += [f"Note: {n}" for n in res["notes"]]
    elif cmd == "timeline":
        for r in res["reporting"]:
            L.append(f"- FY {r['financial_years']}: {r['who']}  [{', '.join(r['cites'])}]")
        L.append("History:")
        L += [f" - {h['act']} ({h['celex']}): {h['set']}" for h in res["history"]]
        L.append("Deadlines:")
        L += [f" - {x['what']}: {x['date']}" for x in res["deadlines"]]
        L.append(res["note"])
    else:
        v = res["legal_basis_version"]
        L.append(f"Directive 2013/34/EU: {v['directive_2013_34_eu']['consolidated_version']}; Directive (EU) 2022/2464: "
                 f"{v['directive_2022_2464_eu']['consolidated_version']}; checked {v['checked']} at {res['endpoint']}")
        for a in v["amending_acts_applied"]:
            L.append(f" - {a['act']} ({a['celex']}), {a['oj']}")
        L.append(f"Licence: {res['licence']['terms']}")
        if "national_law" in res:
            nl = res["national_law"]
            L.append(f"{nl['name']}: " + "; ".join(f"{d['directive']} {d['notified_measures']} notified measure(s)" for d in nl["directives"]))
            L.append(nl["note"])
            L.append(f"Annex I: {res['legal_forms']['annex_i']}")
            L.append(f"Annex II: {res['legal_forms']['annex_ii']}")
    L.append(res["attribution"])
    return "\n".join(L)


if __name__ == "__main__":
    raise SystemExit(main())
