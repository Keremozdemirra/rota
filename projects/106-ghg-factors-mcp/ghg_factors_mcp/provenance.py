"""Where every number comes from, under which licence, and what it means.

Each fact here was checked against the primary source on the date in
CHECKED; quotes are copied verbatim so they can be searched for on the page.
The snapshot-specific facts (retrieval date, SHA-256, row counts, version)
live in data/manifest.json, written by `refresh`.
"""
from __future__ import annotations

CHECKED = "2026-09-24"
USER_AGENT = "ghg-factors-mcp/{version} (+https://github.com/Keremozdemirra/ghg-factors-mcp)"

# --------------------------------------------------------------------- DESNZ

DESNZ_YEARS = (2026, 2025)  # newest first; add a year here when DESNZ publishes it (next: June 2027)
DESNZ_PAGE = "https://www.gov.uk/government/publications/greenhouse-gas-reporting-conversion-factors-{year}"
DESNZ_API = "https://www.gov.uk/api/content/government/publications/greenhouse-gas-reporting-conversion-factors-{year}"
DESNZ_ASSET_HOST = "assets.publishing.service.gov.uk"
DESNZ = {
    "publisher": "Department for Energy Security and Net Zero (DESNZ)",
    "title": "UK Government GHG Conversion Factors for Company Reporting",
    "licence": "Open Government Licence v3.0",
    "licence_url": "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/",
    # Footer of the GOV.UK publication page, checked 2026-09-24.
    "terms_quote": "All content is available under the Open Government Licence v3.0, except where otherwise stated",
    # OGL v3 text, checked 2026-09-24: the statement to use when the provider names none.
    "attribution_statement": "Contains public sector information licensed under the Open Government Licence v3.0.",
    # GOV.UK publication page (2026), checked 2026-09-24; "; " joins two list items.
    "coverage_quote": ("They are suitable for use by: UK-based organisations of all sizes; International "
                       "organisations reporting on their UK operations"),
    "use_quote": "The factors may also be used for other purposes, but users do so at their own risk.",
}

# DESNZ 2026 methodology paper, paragraph 3.8 (page 27), checked 2026-09-24:
# "the 2025 publication used 2023 data, and the 2026 publication uses 2025 data."
DESNZ_METHODOLOGY_2026 = ("https://assets.publishing.service.gov.uk/media/6a2940543b15d05a7ce3202e/"
                          "2026-GHG-conversion-factors-methodology-report.pdf")
UK_ELECTRICITY_DATA_YEAR = {2026: 2025, 2025: 2023}

# --------------------------------------------------------------------- Ember

EMBER_CSV = "https://files.ember-energy.org/public-downloads/generation/outputs/release_generation_yearly_global.csv"
EMBER = {
    "publisher": "Ember",
    "title": "Yearly Electricity Data (global)",
    "page": "https://ember-energy.org/data/yearly-electricity-data/",
    "licence": "CC BY 4.0",
    "licence_url": "https://creativecommons.org/licenses/by/4.0/",
    "terms_url": "https://ember-energy.org/creative-commons/",
    # https://ember-energy.org/creative-commons/, checked 2026-09-24; " / " separates two text blocks.
    "terms_quote": ("Ember content is released under a Creative Commons Attribution Licence (CC-BY-4.0)"
                    " / This means you\u2019re free to share and adapt our work \u2013 as long as you credit us."),
    "methodology": "https://files.ember-energy.org/public-downloads/ember_electricity_data_methodology.pdf",
    # Ember methodology PDF, section on emissions, checked 2026-09-24.
    "basis_quote": ("These figures aim to include full lifecycle emissions including upstream methane, "
                    "supply chain and manufacturing emissions, and include all gases, converted into CO2 "
                    "equivalent over a 100-year timescale."),
}

# ------------------------------------------------------------------------ UBA

UBA_PAGE = "https://www.umweltbundesamt.de/themen/klima-energie/energieversorgung/strom-waermeversorgung-in-zahlen"
UBA = {
    "publisher": "Umweltbundesamt (German Environment Agency)",
    "title": "Strom- und Wärmeversorgung in Zahlen",
    "terms_url": "https://www.umweltbundesamt.de/datenschutz-haftung-urheberrecht",
    # Section C of the terms page, checked 2026-09-24. Texts and graphics are
    # CC BY-NC-ND 4.0 on the same page, which is why only numbers are kept.
    "terms_quote": ("Soweit nicht anders gekennzeichnet, ist die Nutzung von Daten im Sinne des § 12a EGovG "
                    "zulässig. Die bereitgestellten Daten und Metadaten dürfen für die kommerzielle und nicht "
                    "kommerzielle Nutzung insbesondere vervielfältigt, [...] werden. Bei der Nutzung ist "
                    "sicherzustellen, dass das Umweltbundesamt im Quellenvermerk enthalten ist."),
    "licence": "data use under § 12a EGovG, Umweltbundesamt named in the source note",
}

# ----------------------------------------------------------- GHG Protocol

# GHG Protocol Scope 2 Guidance (2015), https://ghgprotocol.org/scope-2-guidance, checked 2026-09-24.
SCOPE2_GUIDANCE = "https://ghgprotocol.org/scope-2-guidance"
LOCATION_BASED_QUOTE = ("A location-based method reflects the average emissions intensity of grids on which "
                        "energy consumption occurs (using mostly grid-average emission factor data).")  # p. 8
SCOPE2_BOUNDARY_QUOTE = ("Scope 2 includes indirect emissions from generation only; other upstream emissions "
                         "associated with the production and processing of upstream fuels, or transmission or "
                         "distribution of energy within a grid, are tracked in scope 3, category 3")  # p. 34

LOCATION_BASED = ("Location-based: a grid-average figure, usable for the location-based method of Scope 2 "
                  "(GHG Protocol Scope 2 Guidance, 2015, p. 8). It is not a market-based factor: it reflects no "
                  "supplier contract, tariff or energy attribute certificate.")

# -------------------------------------------------------------- left out

EXCLUDED = [
    {"source": "IPCC Emission Factor Database (EFDB)",
     "reason": "IPCC material may be copied for personal, non-commercial use only, without redistribution.",
     "evidence_url": "https://www.ipcc.ch/copyright/",
     "quote": ("You may freely download and copy the material contained on this website for your personal, "
               "non-commercial use, without any right to resell or redistribute it or to compile or create "
               "derivative works there from"),
     "checked": CHECKED},
    {"source": "PCAF emission factor database",
     "reason": "Access is a benefit for PCAF signatories and accredited partners, not an open licence.",
     "evidence_url": "https://carbonaccountingfinancials.com/join-pcaf",
     "quote": "The PCAF Database provides PCAF signatories and accredited partners with physical- and "
              "economic-activity-based emission factors",
     "checked": CHECKED},
    {"source": "IEA-EDGAR CO2 (EDGAR fossil CO2 from fuel combustion)",
     "reason": "Licensed CC BY-NC-ND 4.0: no commercial use, no derivatives.",
     "evidence_url": "https://edgar.jrc.ec.europa.eu/report_2026",
     "quote": "IEA-EDGAR CO 2 (v5) data are based on data from IEA (2025) Greenhouse Gas Emissions from Energy, "
              "www.iea.org/data-and-statistics , as modified by the Joint Research Centre, licensed under "
              "CC BY-NC-ND 4.0.",
     "checked": CHECKED},
]
