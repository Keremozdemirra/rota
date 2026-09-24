"""Where each figure comes from, and under which terms.

Three dated sources feed the labels on every answer:
- the API's own subsector definitions (`dataLeads`: the organisations behind each
  model), bundled as a snapshot in data/subsectors.json and rebuilt by `refresh`;
- Climate TRACE's terms page, which names the external datasets it reproduces
  and excludes them from its CC BY 4.0 licence;
- the licence pages of those external datasets.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

from .safety import clean

SNAPSHOT_PATH = Path(__file__).resolve().with_name("data") / "subsectors.json"
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

TERMS_URL = "https://climatetrace.org/terms"
DATA_PAGE_URL = "https://climatetrace.org/data"
CHECKED = "2026-09-24"
LICENCE_NAME = "CC BY 4.0"
LICENCE_URL = "https://creativecommons.org/licenses/by/4.0/"
CITATION_URL = "https://github.com/climatetracecoalition/methodology-documents/tree/main/2025/README"
API_DOCS_URL = "https://api.climatetrace.org/v7/docs/openapi.json"
API_VERSION_TESTED = "7.2.0"

# Quotes from https://climatetrace.org/terms and https://climatetrace.org/data, checked 2026-09-24.
LICENCE_QUOTE = ("The emissions data and associated metadata has been made available via Climate TRACE under the "
                 "Creative Commons Attribution 4.0 International License (CC BY 4.0), with the exception of external "
                 "datasets listed below.")
MODEL_QUOTE = ("[S]uch emissions data has been: Modeled using data from third-party sources that are either publicly "
               "available or available through licensing agreements, or Collected from publicly available sources.")
EVOLVING_QUOTE = ("The models used to generate emissions data are continually evolving and are expected to be updated "
                  "over time.")
USER_QUOTE = ("It is the sole responsibility of the user to review the terms and conditions for all the above sources "
              "prior to using the data.")
OWNERSHIP_QUOTE = ("Facility ownership information has been made available from a variety of sources, including primary "
                   "sources such as company websites, secondary sources such as industry news articles, and aggregators "
                   "such as PermID, OpenCorporates, and Wikipedia.")
BETA_QUOTE = ("As a beta release, we cannot guarantee availability of the Climate TRACE API; please keep volume low and "
              "use it with caution in production settings.")

CAVEAT = ("Climate TRACE figures are modelled estimates, not measured or company-reported values; Climate TRACE says "
          "its models \"are continually evolving and are expected to be updated over time\". A difference from a "
          "company's reported figure reflects different methods, scope and boundaries. It does not show that either "
          "figure is wrong.")


def attribution(retrieved: str) -> str:
    return "Source: Climate TRACE (climatetrace.org), CC BY 4.0, retrieved %s" % retrieved


# The five greenhouse-gas codes the API supports "throughout" (GET /v7/definitions/gases).
# Horizons: "100 year and 20 year time frame using IPCC Sixth Assessment Report (AR6)
# Global Warming Potentials" (OpenAPI 7.2.0, field `gas`, checked 2026-09-24).
# confidence_key: the matching field of the API's per-year `confidence` record.
GASES = {
    "co2e_100yr": {"unit": "t CO2e", "gwp_horizon": "100-year GWP (IPCC AR6)", "includes_co2": True,
                   "confidence_key": "total_co2e_100yrgwp"},
    "co2e_20yr": {"unit": "t CO2e", "gwp_horizon": "20-year GWP (IPCC AR6)", "includes_co2": True,
                  "confidence_key": "total_co2e_20yrgwp"},
    "co2": {"unit": "t CO2", "gwp_horizon": "none (tonnes of CO2)", "includes_co2": True,
            "confidence_key": "co2_emissions"},
    "ch4": {"unit": "t CH4", "gwp_horizon": "none (tonnes of CH4)", "includes_co2": False,
            "confidence_key": "ch4_emissions"},
    "n2o": {"unit": "t N2O", "gwp_horizon": "none (tonnes of N2O)", "includes_co2": False,
            "confidence_key": "n2o_emissions"},
}
GAS_SOURCE = ("Climate TRACE API OpenAPI %s, field `gas`: CO2e \"available (100 year and 20 year time frame using IPCC "
              "Sixth Assessment Report (AR6) Global Warming Potentials)\"; quantities in metric tonnes. %s, checked %s."
              % (API_VERSION_TESTED, API_DOCS_URL, CHECKED))

_NOT_CHECKED = "not checked by this tool; review the provider's terms before reuse"

# External datasets named on https://climatetrace.org/terms ("External Datasets"),
# checked 2026-09-24, with the licence each provider states where this tool read it.
EXTERNAL = {
    "EDGAR": {
        "name": "EDGAR, Emissions Database for Global Atmospheric Research (European Commission, JRC)",
        "url": "https://edgar.jrc.ec.europa.eu/",
        "licence": "CC BY 4.0 for EU-owned material, except the IEA-EDGAR CO2 component: CC BY-NC-ND 4.0",
        "licence_source": "https://edgar.jrc.ec.europa.eu/dataset_ghg2026",
        "licence_checked": CHECKED,
        "licence_quote": ("IEA-EDGAR CO2 (v5) data are based on data from IEA (2025) Greenhouse Gas Emissions from "
                          "Energy, www.iea.org/data-and-statistics, as modified by the Joint Research Centre, licensed "
                          "under CC BY-NC-ND 4.0."),
    },
    "FAOSTAT": {
        "name": "FAOSTAT (Food and Agriculture Organization of the United Nations)",
        "url": "https://www.fao.org/faostat/en/#home",
        "licence": "CC BY 4.0, complemented by FAO's database terms of use",
        "licence_source": "https://www.fao.org/contact-us/terms/db-terms-of-use/en/",
        "licence_checked": CHECKED,
        "licence_quote": ("Unless specified otherwise in their metadata or webpage, all datasets disseminated through "
                          "FAO corporate statistical databases ... are licensed under the Creative Commons "
                          "Attribution-4.0 International licence (CC BY 4.0)"),
    },
    "E-PRTR": {
        "name": "European Pollutant Release and Transfer Register (European Environment Agency)",
        "url": ("https://www.eea.europa.eu/data-and-maps/data/member-states-reporting-art-7-under-the-european-"
                "pollutant-release-and-transfer-register-e-prtr-regulation-23/european-pollutant-release-and-"
                "transfer-register-e-prtr-data-base"),
        "licence": None,
    },
    "US EPA FLIGHT": {
        "name": "US EPA FLIGHT dataset (Greenhouse Gas Reporting Program facility data)",
        "url": "https://ghgdata.epa.gov/ghgp/main.do?site_preference=normal",
        "licence": None,
    },
    "US EPA LMOP": {
        "name": "US EPA Landfill Methane Outreach Program (LMOP)",
        "url": "https://www.epa.gov/lmop",
        "licence": None,
    },
    "Canada GHGRP": {
        "name": "Canada Greenhouse Gas Reporting Program, Facility GHG Data",
        "url": "https://open.canada.ca/data/en/dataset/a8ba14b7-7f23-462a-bdbb-83b0ef629823",
        "licence": "Open Government Licence - Canada",
        "licence_source": "https://open.canada.ca/data/en/dataset/a8ba14b7-7f23-462a-bdbb-83b0ef629823",
        "licence_checked": CHECKED,
    },
    "Israel PRTR": {
        "name": "Israel Pollutant Release and Transfer Register",
        "url": "https://www.gov.il/en/departments/topics/prtr/govil-landing-page",
        "licence": None,
    },
}

_COUNTRY = "country-level emissions estimates"
_SOME = "source-level emissions estimates for some sources"
# Subsector (API slug) -> external datasets, as the terms page words it. The
# slug for each wording is this tool's reading of the page (checked 2026-09-24).
TERMS_SUBSECTORS = {
    "other-energy-use": [("EDGAR", _COUNTRY, "Other energy use")],
    "railways": [("EDGAR", _COUNTRY, "Railways")],
    "other-transport": [("EDGAR", _COUNTRY, "Other transportation")],
    "other-onsite-fuel-usage": [("EDGAR", _COUNTRY, "Other onsite fuel usage"),
                                ("FAOSTAT", _COUNTRY, "Other onsite fuel usage")],
    "other-solid-fuels": [("EDGAR", _COUNTRY, "Other Solid fuels")],
    "other-fossil-fuel-operations": [("EDGAR", _COUNTRY, "Other fossil fuel operations")],
    "other-manufacturing": [("EDGAR", _COUNTRY, "Other manufacturing"),
                            ("E-PRTR", _SOME, "some sources in \"Other manufacturing\" sector"),
                            ("US EPA FLIGHT", _SOME, "some sources in \"Other manufacturing\" sector"),
                            ("Israel PRTR", _SOME, "some sources in \"Other manufacturing\" sector")],
    "solid-waste-disposal": [("EDGAR", _COUNTRY, "Solid waste disposal"),
                             ("US EPA FLIGHT", _SOME, "some sources in \"Solid Waste Disposal\" sector"),
                             ("US EPA LMOP", _SOME, "some sources in \"Solid Waste Disposal\" sector (some landfills only)"),
                             ("Canada GHGRP", _SOME, "some sources in \"Solid Waste Disposal\" sector"),
                             ("E-PRTR", _SOME, "some sources in \"Solid Waste Disposal\" sector")],
    "biological-treatment-of-solid-waste-and-biogenic": [("EDGAR", _COUNTRY, "Biological treatment of solid waste")],
    "incineration-and-open-burning-of-waste": [("EDGAR", _COUNTRY, "Incineration and open burning of waste")],
    "fluorinated-gases": [("EDGAR", _COUNTRY, "Fluorinated gases")],
    "rice-cultivation": [("FAOSTAT", _COUNTRY, "Rice cultivation (in some geographies)")],
    "other-agricultural-soil-emissions": [("FAOSTAT", _COUNTRY, "Other Agricultural Soil Emissions")],
    "enteric-fermentation-other": [("FAOSTAT", _COUNTRY, "Enteric Fermentation – Other")],
    "manure-management-other": [("FAOSTAT", _COUNTRY, "Manure Management – Other")],
}


def external_dataset(key: str) -> dict:
    info = EXTERNAL[key]
    out = {"dataset": key, "name": info["name"], "url": info["url"],
           "licence": info["licence"] or _NOT_CHECKED}
    if info.get("licence_source"):
        out["licence_source"] = info["licence_source"]
        out["licence_checked"] = info["licence_checked"]
    return out


class Snapshot:
    """The API's sector and subsector definitions as bundled, or empty if the file is unusable."""

    def __init__(self, data=None, error=None):
        data = data if isinstance(data, dict) else {}
        self.error = error
        self.retrieved = data.get("retrieved") if isinstance(data.get("retrieved"), str) else None
        self.api_version = data.get("api_version") if isinstance(data.get("api_version"), str) else None
        self.sectors = [s for s in data.get("sectors") or [] if isinstance(s, str) and SLUG.match(s)]
        self.subsectors = {}
        for rec in data.get("subsectors") or []:
            if isinstance(rec, dict) and isinstance(rec.get("name"), str) and SLUG.match(rec["name"]):
                self.subsectors[rec["name"]] = rec

    @classmethod
    def load(cls, path=None) -> "Snapshot":
        path = Path(path) if path else SNAPSHOT_PATH
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            return cls(None, error="bundled definitions snapshot unreadable (%s)" % type(e).__name__)
        if not isinstance(data, dict):
            return cls(None, error="bundled definitions snapshot is not a JSON object")
        return cls(data)

    def sector_of(self, subsector: str):
        rec = self.subsectors.get(subsector) or {}
        s = rec.get("sector")
        return s if isinstance(s, str) and SLUG.match(s) else None

    def data_leads(self, subsector: str):
        """[{name, url}] as the API lists them, or None when the subsector is not in the snapshot."""
        rec = self.subsectors.get(subsector)
        if rec is None:
            return None
        leads = []
        for lead in rec.get("dataLeads") or []:
            if isinstance(lead, dict) and lead.get("name"):
                url = clean(lead.get("url"), 200)
                leads.append({"name": clean(lead.get("name"), 80), "url": url if url.startswith(("https://", "http://")) else None})
        return leads


def describe(snapshot: Snapshot, subsector, gas: str, level: str) -> dict:
    """Provenance of a figure for one subsector.

    level "source": one asset record; only datasets the terms name for source-level
    records apply. level "country": a country total, to which the terms' country-level
    datasets apply as well.
    """
    sub = subsector if isinstance(subsector, str) and SLUG.match(subsector) else None
    leads = snapshot.data_leads(sub) if sub else None
    ext = []
    for key, scope, wording in TERMS_SUBSECTORS.get(sub or "", []):
        if level == "source" and scope == _COUNTRY:
            continue
        d = external_dataset(key)
        d["scope"] = scope
        d["terms_page_wording"] = wording
        ext.append(d)
    lead_names = [lead["name"] for lead in leads or []]
    edgar_in_terms = any(d["dataset"] == "EDGAR" for d in ext)
    edgar_lead = any(n.strip().upper() == "EDGAR" for n in lead_names)

    if sub is None:
        label = "Climate TRACE (the record names no valid subsector)"
    elif leads is None:
        label = "Climate TRACE, subsector %s (not in the bundled definitions snapshot of %s)" % (sub, snapshot.retrieved or "unknown date")
    elif lead_names:
        label = "Climate TRACE, subsector %s (data leads named by the API: %s)" % (sub, ", ".join(lead_names))
    else:
        label = "Climate TRACE, subsector %s (the API names no data lead)" % sub
    if ext:
        parts = []
        country_level = [d["dataset"] for d in ext if d["scope"] == _COUNTRY]
        some = [d["dataset"] for d in ext if d["scope"] == _SOME]
        if country_level:
            parts.append("country-level estimates reproduced from " + " and ".join(country_level))
        if some:
            parts.append("some source-level records from " + ", ".join(some) + " (the API does not say which records)")
        label += "; per climatetrace.org/terms: " + "; ".join(parts)

    out = {"subsector": sub, "sector": snapshot.sector_of(sub) if sub else None, "label": label,
           "data_leads": leads, "data_leads_as_of": snapshot.retrieved if leads is not None else None,
           "external_datasets": ext}
    if ext:
        out["licence"] = ("Climate TRACE's CC BY 4.0 excludes the external datasets listed here; their own terms "
                          "apply to the parts that come from them (%s)" % TERMS_URL)
    else:
        out["licence"] = LICENCE_NAME
    gas_info = GASES.get(gas, {})
    if (edgar_in_terms or edgar_lead) and gas_info.get("includes_co2"):
        who = "Climate TRACE's terms name EDGAR" if edgar_in_terms else "The API names EDGAR as a data lead"
        out["non_commercial_terms_may_apply"] = True
        out["licence_note"] = (
            "%s for this subsector. EDGAR licenses its CO2 data (IEA-EDGAR CO2) under CC BY-NC-ND 4.0 "
            "(non-commercial, no derivatives); its other EU-owned data are CC BY 4.0 (%s, checked %s). If this "
            "figure includes CO2 taken from EDGAR, non-commercial terms may apply to that part: check before "
            "commercial use." % (who, EXTERNAL["EDGAR"]["licence_source"], CHECKED))
    else:
        out["non_commercial_terms_may_apply"] = False
    return out


def openapi_version(text: str):
    """info.version of the OpenAPI document, which the API serves as YAML."""
    try:
        data = json.loads(text)
        v = data.get("info", {}).get("version") if isinstance(data, dict) else None
        return clean(v, 40) if isinstance(v, str) else None
    except ValueError:
        pass
    m = re.search(r"(?m)^info:[ \t]*\n(?:[ \t]+.*\n)*?[ \t]+version:[ \t]*['\"]?([0-9][0-9A-Za-z.+-]{0,30})", text)
    return m.group(1) if m else None


def refresh(client, out_path=None, pause: float = 0.3, log=None) -> dict:
    """Rebuild data/subsectors.json from the API's definitions endpoints.

    One request per subsector, spaced by `pause` seconds (tool's choice) because
    the API asks users to keep volume low.
    """
    out_path = Path(out_path) if out_path else SNAPSHOT_PATH
    sectors, retrieved = client.get("/definitions/sectors")
    names, _ = client.get("/definitions/subsectors")
    for label, values in (("sectors", sectors), ("subsectors", names)):
        if not isinstance(values, list) or not values or not all(isinstance(v, str) and SLUG.match(v) for v in values):
            raise ValueError("the API's %s list is not a list of names; nothing written" % label)
    records = []
    for name in sorted(set(names)):
        rec, _ = client.get("/definitions/subsectors/" + name)
        if not isinstance(rec, dict) or rec.get("name") != name:
            raise ValueError("unexpected definition for subsector %s; nothing written" % name)
        records.append(rec)
        if log:
            log(name)
        time.sleep(pause)
    spec, _ = client.get_text("/docs/openapi.json")
    data = {
        "about": ("Snapshot of the Climate TRACE API definitions (sectors, subsectors and their data leads), "
                  "Climate TRACE, CC BY 4.0. Rebuilt by: climate-trace-mcp refresh"),
        "source": client.base + "/definitions/subsectors",
        "api_version": openapi_version(spec),
        "retrieved": retrieved,
        "sectors": sectors,
        "subsectors": records,
    }
    text = json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    tmp = out_path.with_name(out_path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(str(tmp), str(out_path))
    return {"path": str(out_path), "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "sectors": len(sectors), "subsectors": len(records), "retrieved": retrieved,
            "api_version": data["api_version"]}
