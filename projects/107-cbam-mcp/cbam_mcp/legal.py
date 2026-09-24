"""Legal texts this tool quotes, each with its citation and the date it was checked.

Everything here was read in the Official Journal texts served by CELLAR
(http://publications.europa.eu/resource/celex/<CELEX>) on 2026-09-24. Rules that
the consolidated text of Regulation (EU) 2023/956 carries (de minimis threshold,
Annex II and III lists) are not repeated here: `refresh` parses them from that
text, so they always match the snapshot in use.

Deliberately absent: the mark-up percentages. They are in the introductory part
of Annex I as replaced by Implementing Regulation (EU) 2026/1740, but no
consolidated text of Implementing Regulation (EU) 2025/2621 that includes them
existed on 2026-09-24, and this tool only states such rules from consolidated
text. Answers point to where the increase is set instead.
"""

CHECKED = "2026-09-24"

CELLAR = "http://publications.europa.eu/resource/celex/"

ACTS = {
    "32023R0956": "Regulation (EU) 2023/956 of the European Parliament and of the Council of 10 May 2023 "
                  "establishing a carbon border adjustment mechanism (OJ L 130, 16.5.2023, p. 52)",
    "32025R2083": "Regulation (EU) 2025/2083 of the European Parliament and of the Council of 8 October 2025 "
                  "amending Regulation (EU) 2023/956 as regards simplifying and strengthening the carbon border "
                  "adjustment mechanism (OJ L, 2025/2083, 17.10.2025)",
    "32025R2621": "Commission Implementing Regulation (EU) 2025/2621 of 16 December 2025 laying down rules for the "
                  "application of Regulation (EU) 2023/956 as regards the establishment of default values "
                  "(OJ L, 2025/2621, 31.12.2025)",
    "32026R1740": "Commission Implementing Regulation (EU) 2026/1740 of 20 July 2026 correcting Implementing "
                  "Regulation (EU) 2025/2621 as regards Annexes I and IV thereto (OJ L, 2026/1740, 31.7.2026)",
    "32025R1926": "Commission Implementing Regulation (EU) 2025/1926 of 22 September 2025 amending Annex I to "
                  "Council Regulation (EEC) No 2658/87 on the tariff and statistical nomenclature and on the "
                  "Common Customs Tariff (the Combined Nomenclature 2026)",
    "32024R2522": "Commission Implementing Regulation (EU) 2024/2522 of 23 September 2024 amending Annex I to "
                  "Council Regulation (EEC) No 2658/87 on the tariff and statistical nomenclature and on the "
                  "Common Customs Tariff (the Combined Nomenclature 2025)",
}

# --------------------------------------------------------------- scope

SCOPE_BINDING_SOURCE = (
    "Annex I to Regulation (EU) 2023/956 as published in the Official Journal (OJ L 130, 16.5.2023, p. 52) "
    "and amended by Regulation (EU) 2025/2083 (OJ L, 2025/2083, 17.10.2025)"
)

# --------------------------------------------------------------- default values

VALUES_BINDING_SOURCE = (
    "Annex I to Commission Implementing Regulation (EU) 2025/2621, as replaced by Annex I to Commission "
    "Implementing Regulation (EU) 2026/1740 (OJ L, 2026/1740, 31.7.2026)"
)
ANNEX_IV_BINDING_SOURCE = (
    "Annex IV to Commission Implementing Regulation (EU) 2025/2621, as replaced by Annex II to Commission "
    "Implementing Regulation (EU) 2026/1740 (OJ L, 2026/1740, 31.7.2026)"
)

# The Commission's own words next to the download link.
EXCEL_NOTICE = {
    "quote": "An Excel file is made available for information purposes only, while the legally binding values "
             "are set out in Commission Implementing Regulation (EU) 2025/2621.",
    "source": "https://taxation-customs.ec.europa.eu/carbon-border-adjustment-mechanism/"
              "cbam-legislation-and-guidance_en",
    "checked": CHECKED,
}

# Introductory part of Annex I as replaced by Implementing Regulation (EU) 2026/1740.
RULE_NOT_LISTED = {
    "quote": "Where a country or territory is not explicitly listed, the default value for the respective good "
             "from the table “Other countries and territories” needs to be selected.",
    "citation": "Annex I (introductory part) to Implementing Regulation (EU) 2025/2621 as replaced by "
                "Implementing Regulation (EU) 2026/1740",
    "checked": CHECKED,
}
RULE_NO_VALUE = {
    "quote": "Where a country or territory is explicitly listed but no value is provided or the relevant field "
             "shows “–”, the default value for the respective good from the table “Other "
             "countries and territories” needs to be selected.",
    "citation": "Annex I (introductory part) to Implementing Regulation (EU) 2025/2621 as replaced by "
                "Implementing Regulation (EU) 2026/1740",
    "checked": CHECKED,
}

# Same annex: the letters in the column "Underlying production route determining
# CBAM BM". The Annex I copy writes "cementw" for (A), a typo; Annex IV of the
# same act writes "cement", which is used here.
PRODUCTION_ROUTES = {
    "A": "grey clinker / cement",
    "B": "white clinker / cement",
    "C": "Carbon Steel based on BF/BOF",
    "D": "Carbon Steel based on DRI/EAF",
    "E": "Carbon Steel based on Scrap/EAF",
    "F": "Low alloy Steel based on BF/BOF",
    "G": "Low alloy Steel based on DRI/EAF",
    "H": "Low alloy Steel based on scrap/EAF",
    "J": "High alloy Steel (based on EAF)",
    "K": "primary Aluminium",
    "L": "secondary Aluminium",
}
NO_ROUTE = {
    "quote": "If no production route is indicated for a CN code, the CBAM benchmark (BM) is independent of the "
             "production route.",
    "citation": "Annex I (introductory part) to Implementing Regulation (EU) 2025/2621 as replaced by "
                "Implementing Regulation (EU) 2026/1740",
    "checked": CHECKED,
}

DIRECT_INDIRECT_FOR_INFORMATION = {
    "quote": "The default values for direct emissions and indirect emissions in Annex I have only been provided "
             "for information.",
    "citation": "Recital 10 of Implementing Regulation (EU) 2026/1740",
    "checked": CHECKED,
}

MARKUP_POINTER = (
    "Values as listed in the table. For the calculation of the number of CBAM certificates, the introductory "
    "part of Annex I (as replaced by Implementing Regulation (EU) 2026/1740) says the 'total emissions' value "
    "is selected and increased; this tool does not apply or state that increase."
)

ANNEX_IV_USE = {
    "quote": "By way of derogation from paragraph 2, where a country of production cannot be identified for a "
             "precursor, the default values laid down in Annex IV shall be used.",
    "citation": "Article 1(5) of Implementing Regulation (EU) 2025/2621",
    "checked": CHECKED,
}

ELECTRICITY = {
    "quote": "Where the embedded direct emissions in electricity imported into the customs territory of the "
             "Union are determined on the basis of default values in accordance with Article 7(3) of Regulation "
             "(EU) 2023/956, the default values laid down in Annex III to this Regulation shall be used.",
    "citation": "Article 1(4) of Implementing Regulation (EU) 2025/2621",
    "checked": CHECKED,
}
INDIRECT_FACTORS = {
    "quote": "Where the specific indirect embedded emissions are determined on the basis of default values in "
             "accordance with Article 7(4) of Regulation (EU) 2023/956, the default values laid down in Annex II "
             "to this Regulation shall be used.",
    "citation": "Article 1(3) of Implementing Regulation (EU) 2025/2621",
    "checked": CHECKED,
}
# Why Annexes II and III are not bundled: the regulation itself says whose data they are.
IEA_NOTICE = {
    "quote": "The data provided are based on data sourced from the International Energy Agency (IEA) and is "
             "subject to a Creative Commons Non-Commercial Share-Alike 4.0 CC BY NC SA licence",
    "citation": "Annexes II and III to Implementing Regulation (EU) 2025/2621",
    "checked": CHECKED,
}

# --------------------------------------------------------------- origin

# The 27 Member States, from https://european-union.europa.eu/principles-countries-history/eu-countries_en
# (27 country pages listed, checked 2026-09-24). Goods originating there are
# not imports from a third country, which is what Article 2(1) covers.
EU_MEMBER_STATES = {
    "Austria": "AT", "Belgium": "BE", "Bulgaria": "BG", "Croatia": "HR", "Cyprus": "CY", "Czechia": "CZ",
    "Denmark": "DK", "Estonia": "EE", "Finland": "FI", "France": "FR", "Germany": "DE", "Greece": "GR",
    "Hungary": "HU", "Ireland": "IE", "Italy": "IT", "Latvia": "LV", "Lithuania": "LT", "Luxembourg": "LU",
    "Malta": "MT", "Netherlands": "NL", "Poland": "PL", "Portugal": "PT", "Romania": "RO", "Slovakia": "SK",
    "Slovenia": "SI", "Spain": "ES", "Sweden": "SE",
}
EU_MEMBER_STATES_SOURCE = "https://european-union.europa.eu/principles-countries-history/eu-countries_en"

# ISO codes for the countries in point 1 of Annex III, which refresh parses by name.
ANNEX_III_ISO = {"Iceland": "IS", "Liechtenstein": "LI", "Norway": "NO", "Switzerland": "CH"}

# --------------------------------------------------------------- CN

CN_BINDING_SOURCE = {
    2026: "Annex I to Council Regulation (EEC) No 2658/87 as amended by Commission Implementing Regulation "
          "(EU) 2025/1926 (Combined Nomenclature 2026), as published in the Official Journal",
    2025: "Annex I to Council Regulation (EEC) No 2658/87 as amended by Commission Implementing Regulation "
          "(EU) 2024/2522 (Combined Nomenclature 2025), as published in the Official Journal",
}
CN_DATASET = {
    2026: "http://data.europa.eu/88u/dataset/combined-nomenclature-2026",
    2025: "http://data.europa.eu/88u/dataset/combined-nomenclature-2025",
}

# --------------------------------------------------------------- licences

LICENCES = {
    "commission": {
        "name": "CC BY 4.0",
        "terms": "https://commission.europa.eu/legal-notice_en",
        "quote": "Unless otherwise indicated (e.g. in individual copyright notices), content owned by the EU on "
                 "this website is licensed under the Creative Commons Attribution 4.0 International (CC BY 4.0) "
                 "licence. This means that reuse is allowed, provided appropriate credit is given and changes "
                 "are indicated.",
    },
    "cn": {
        "name": "European Commission reuse notice (Commission Decision 2011/833/EU)",
        "terms": "http://data.europa.eu/eli/dec/2011/833/oj",
        "quote": "Licence of both distributions of the datasets combined-nomenclature-2025 and "
                 "combined-nomenclature-2026 on data.europa.eu: 'European Commission reuse notice'.",
    },
    "eurlex": {
        "name": "EU legal acts from EUR-Lex/CELLAR; reuse conditions of CELLAR content on request",
        "terms": "https://op.europa.eu/en/web/about-us/legal-notices/publications-office-of-the-european-union-copyright",
        "quote": "If you need further information regarding copyright issues, including the conditions under "
                 "which the content of the CELLAR, and of the EU Vocabularies may be re-used, please contact us "
                 "at op-copyright@publications.europa.eu",
    },
}

NOT_LEGAL_ADVICE = "Information only, not legal advice; check the Official Journal text before relying on it."
