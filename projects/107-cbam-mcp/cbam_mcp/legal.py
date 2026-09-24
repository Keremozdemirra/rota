"""Legal texts this tool quotes, each with its citation and the date it was checked.

Everything here was read in the Official Journal texts served by CELLAR
(http://publications.europa.eu/resource/celex/<CELEX>) on 2026-09-24. Rules that
the consolidated text of Regulation (EU) 2023/956 carries (de minimis threshold,
Annex II and III lists) are not repeated here: `refresh` parses them from that
text, so they always match the snapshot in use.

The mark-up rule is not kept here either: `refresh` reads it from the consolidated
text of Implementing Regulation (EU) 2025/2621 (02025R2621-20260101 on 2026-09-24,
which includes Implementing Regulation (EU) 2026/1740 as M1) and answers quote it
with that text's version. This tool quotes the rule and never applies it.
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
                "Implementing Regulation (EU) 2026/1740; same words in the consolidated text 02025R2621-20260101",
    "checked": CHECKED,
}
RULE_NO_VALUE = {
    "quote": "Where a country or territory is explicitly listed but no value is provided or the relevant field "
             "shows “–”, the default value for the respective good from the table “Other "
             "countries and territories” needs to be selected.",
    "citation": "Annex I (introductory part) to Implementing Regulation (EU) 2025/2621 as replaced by "
                "Implementing Regulation (EU) 2026/1740; same words in the consolidated text 02025R2621-20260101",
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
                "Implementing Regulation (EU) 2026/1740; same words in the consolidated text 02025R2621-20260101",
    "checked": CHECKED,
}

HS_GROUP_ROUTE = {
    "quote": "If a production route is indicated for a group of CN codes at HS code level (i.e. with 4 or 6 digits) "
             "and the CBAM BM as defined in Implementing Regulation (EU) 2025/2620 for one or more of the CN codes at "
             "8-digit level in that group has no production route, the CBAM BM for the concerned CN code is "
             "independent of the production route.",
    "citation": "Annex I (introductory part) to Implementing Regulation (EU) 2025/2621 as replaced by "
                "Implementing Regulation (EU) 2026/1740; same words in the consolidated text 02025R2621-20260101",
    "checked": CHECKED,
}

DIRECT_INDIRECT_FOR_INFORMATION = {
    "quote": "The default values for direct emissions and indirect emissions in Annex I have only been provided "
             "for information.",
    "citation": "Recital 10 of Implementing Regulation (EU) 2026/1740",
    "checked": CHECKED,
}

MARKUP_NOTE = ("Values as listed, before the mark-up. The rule is quoted in markup_rule from the consolidated "
               "text named there; this tool quotes it and does not apply it.")
MARKUP_MISSING = ("Values as listed, before the mark-up that the introductory part of Annex I sets; the rule could "
                  "not be read from the consolidated text at the last refresh.")

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
# The names point 1 of Annex III listed in the consolidated text of 2025-10-20 (checked 2026-09-24);
# names outside this set, after a refresh, are shown as remote text.
ANNEX_III_NAMES = frozenset(ANNEX_III_ISO) | {"Büsingen", "Heligoland", "Livigno", "Ceuta", "Melilla"}

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

# Licence basis (standards point 16). EUR-Lex legal notice:
# https://eur-lex.europa.eu/content/legal-notice/legal-notice.html (archived copy:
# https://web.archive.org/web/20260922160312/https://eur-lex.europa.eu/content/legal-notice/legal-notice.html).
# It answers HTTP 202 with an empty body to curl from the build sandbox; it was read on
# 2026-09-24 through the WebFetch tool. Decision 2011/833/EU was read from CELLAR the same day.
_EURLEX = "https://eur-lex.europa.eu/content/legal-notice/legal-notice.html"
_EURLEX_READ = ("2026-09-24 through the WebFetch tool (curl from here got HTTP 202 with an empty body); archived "
                "copy https://web.archive.org/web/20260922160312/" + _EURLEX)
_DECISION = {
    "article_4": "All documents shall be available for reuse: (a) for commercial or non-commercial purposes under "
                 "the conditions laid down in Article 6; (b) without charge, subject to the provisions laid down in "
                 "Article 9; and (c) without the need to make an individual application, unless otherwise provided "
                 "in Article 7.",
    "article_6_2": "Those conditions, which shall not unnecessarily restrict possibilities for reuse, may include "
                   "the following: (a) the obligation for the reuser to acknowledge the source of the documents; "
                   "(b) the obligation not to distort the original meaning or message of the documents; (c) the "
                   "non-liability of the Commission for any consequence stemming from the reuse.",
}
LICENCES = {
    # Consolidated texts (02023R0956-..., 02025R2621-...): CC BY 4.0.
    "eurlex_consolidated": {
        "name": "CC BY 4.0 (EUR-Lex legal notice: consolidated texts)",
        "terms": _EURLEX, "read": _EURLEX_READ,
        "quote": "The copyright for the editorial content of this website, the summaries of EU legislation and the "
                 "consolidated texts, which is owned by the EU, is licensed under the Creative Commons Attribution "
                 "4.0 International licence.",
        "quote_2": "This means that you can re-use the content provided you acknowledge the source and indicate any "
                   "changes you have made.",
    },
    # Official Journal texts as published (e.g. 32026R1740): not CC BY; re-use as legal documents.
    "eurlex_oj": {
        "name": "EU legal documents re-usable for commercial or non-commercial purposes (EUR-Lex legal notice; "
                "Commission Decision 2011/833/EU, Articles 4 and 6(2))",
        "terms": _EURLEX, "read": _EURLEX_READ,
        "quote": "Unless otherwise specified, you can re-use the legal documents published in EUR-Lex for commercial "
                 "or non-commercial purposes.",
        "quote_2": "Decision 2011/833/EU, Article 4: " + _DECISION["article_4"],
    },
    # The Commission's Excel: a Commission document.
    "commission_excel": {
        "name": "Commission document, re-usable under Commission Decision 2011/833/EU, Articles 4 and 6(2)",
        "terms": "http://data.europa.eu/eli/dec/2011/833/oj", "read": "2026-09-24 from CELLAR, celex 32011D0833",
        "quote": "Article 4: " + _DECISION["article_4"],
        "quote_2": "Article 6(2): " + _DECISION["article_6_2"],
    },
    "cn": {
        "name": "European Commission reuse notice (COM_REUSE, Commission Decision 2011/833/EU)",
        "terms": "http://data.europa.eu/eli/dec/2011/833/oj",
        "read": "2026-09-24 from the data.europa.eu dataset metadata",
        "quote": "Licence of both distributions of the datasets combined-nomenclature-2025 and "
                 "combined-nomenclature-2026 on data.europa.eu: 'European Commission reuse notice'.",
    },
}

NOT_LEGAL_ADVICE = "Information only, not legal advice; check the Official Journal text before relying on it."
