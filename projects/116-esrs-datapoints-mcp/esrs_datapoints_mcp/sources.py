"""Where the official workbooks are, which ones this tool was checked against, and the legal acts.

Every fact below was read from the primary source named next to it on the date
in CHECKED. File titles and URLs identify EFRAG's files; none of their content
is reproduced here or anywhere in this package.
"""
from __future__ import annotations

CHECKED = "2026-09-24"

EFRAG_DISCLAIMER_URL = "https://www.efrag.org/en/disclaimer"
# The page's section "1. Copyright and right of a database producer", read on CHECKED.
EFRAG_DISCLAIMER_FRAGMENT = "is prohibited without the prior written permission of EFRAG"

IG3_PAGE = "https://www.efrag.org/en/projects/esrs-implementation-guidance-documents"
REVISED_PAGE = "https://www.efrag.org/en/revised-esrs-supporting-materials-and-resources"
REVISED_NEWS = ("https://www.efrag.org/en/news-and-calendar/news/"
                "efrag-secretariat-releases-2026-draft-list-of-datapoints-for-revised-esrs")

# The three official workbooks this parser was built and checked against. The
# SHA-256 lets the tool say whether a user's file is byte-identical to the one
# downloaded on CHECKED; other files with the same columns are still read.
OFFICIAL_FILES = [
    {
        "layout": "ig3",
        "variant": None,
        # "EFRAG issued the final documents on 31 May 2024" (IG3_PAGE, read on CHECKED).
        "list_date": "2024-05-31",
        "title": "EFRAG IG 3 List of ESRS Data Points (Excel workbook, final version of May 2024)",
        "for_standards": "ESRS set 1, Commission Delegated Regulation (EU) 2023/2772",
        "page": IG3_PAGE,
        "url": ("https://www.efrag.org/sites/default/files/media/document/2025-06/"
                "EFRAG%20IG%203%20List%20of%20ESRS%20Data%20Points%20%281%29%20%281%29.xlsx"),
        "sha256": "90f15872c489786d86c445d8dc02e00783eb16ecd998d6e1f5a43ad48edd8be9",
        "bytes": 254557,
        "checked": CHECKED,
    },
    {
        "layout": "revised",
        "variant": "clean",
        # "Version: 28 August 2026" in the workbook; news item dated 28.08.2026 (REVISED_NEWS).
        "list_date": "2026-08-28",
        "title": ("Draft List of Datapoints Effective From 2026 - Revised ESRS Delegated Act 3 July 2026"
                  " - Clean Version"),
        "for_standards": "revised ESRS, Commission Delegated Regulation (EU) 2026/1563",
        "page": REVISED_PAGE,
        "media_page": "https://www.efrag.org/en/media/32781",
        "url": ("https://www.efrag.org/sites/default/files/media/document/2026-08/"
                "Draft%20List%20of%20Datapoints%20Effective%20From%202026%20-%20Revised%20ESRS%20Delegated"
                "%20Act%203%20July%202026%20-%20Clean%20Version_1.xlsx"),
        "sha256": "db8c640d74a2766579fd893f279914687513fc15636835fc2c77d0b067371f8b",
        "bytes": 181615,
        "checked": CHECKED,
    },
    {
        "layout": "revised",
        "variant": "mapping",
        "list_date": "2026-08-28",
        "title": ("Draft List of Datapoints Effective From 2026 - Revised ESRS Delegated Act 3 July 2026"
                  " - 2024 IG3 Mapping Version"),
        "for_standards": "revised ESRS, Commission Delegated Regulation (EU) 2026/1563",
        "page": REVISED_PAGE,
        "media_page": "https://www.efrag.org/en/media/32782",
        "url": ("https://www.efrag.org/sites/default/files/media/document/2026-08/"
                "Draft%20List%20of%20Datapoints%20Effective%20From%202026%20-%20Revised%20ESRS%20Delegated"
                "%20Act%203%20July%202026%20-%202024%20IG3%20Mapping%20Version_1.xlsx"),
        "sha256": "948967fd73650148a1f49192f620e9cf962eb5afafe3751ba19403e3688bbf02",
        "bytes": 195377,
        "checked": CHECKED,
    },
]

OFFICIAL_BY_SHA = {f["sha256"]: f for f in OFFICIAL_FILES}

# Dates and titles from the Publications Office's CELLAR SPARQL endpoint
# (https://publications.europa.eu/webapi/rdf/sparql, properties work_date_document,
# official-journal-act_date_publication, resource_legal_date_entry-into-force) and,
# for 2026/1563, Article 3 of the act itself, all read on CHECKED. EUR-Lex itself
# answered HTTP 202 with an empty body from the machine this was built on.
LEGAL_ACTS = {
    "2023/2772": {
        "title": "Commission Delegated Regulation (EU) 2023/2772 of 31 July 2023 supplementing Directive "
                 "2013/34/EU as regards sustainability reporting standards",
        "celex": "32023R2772",
        "eli": "http://data.europa.eu/eli/reg_del/2023/2772/oj",
        "official_journal": "2023-12-22",
        "checked": CHECKED,
    },
    "2025/1416": {
        "title": "Commission Delegated Regulation (EU) 2025/1416 of 11 July 2025 amending Delegated "
                 "Regulation (EU) 2023/2772 as regards the postponement of the date of application of the "
                 "disclosure requirements for certain undertakings",
        "celex": "32025R1416",
        "eli": "http://data.europa.eu/eli/reg_del/2025/1416/oj",
        "official_journal": "2025-11-10",
        "checked": CHECKED,
    },
    "2026/1563": {
        "title": "Commission Delegated Regulation (EU) 2026/1563 of 3 July 2026 amending Delegated "
                 "Regulation (EU) 2023/2772 as regards the simplification of certain sustainability "
                 "reporting standards",
        "celex": "32026R1563",
        "eli": "http://data.europa.eu/eli/reg_del/2026/1563/oj",
        "official_journal": "2026-09-21",
        "entry_into_force": "2026-11-10",
        "applies": ("to financial years beginning on or after 1 January 2027 (Article 3); for financial "
                    "years starting in 2026 an undertaking may apply either version (Article 2)"),
        "checked": CHECKED,
    },
}

# Which act holds the binding text for the standards a list layout describes.
BINDING_ACT = {"ig3": "2023/2772", "revised": "2026/1563"}

COMMISSION_REUSE = {
    "url": "https://commission.europa.eu/legal-notice_en",
    # Quoted from the page on CHECKED.
    "quote": ("Unless otherwise indicated (e.g. in individual copyright notices), content owned by the EU on "
              "this website is licensed under the Creative Commons Attribution 4.0 International (CC BY 4.0) "
              "licence."),
    "eur_lex_notice": "https://eur-lex.europa.eu/content/legal-notice/legal-notice.html",
    "eur_lex_checked": "not verified first-hand: EUR-Lex returned HTTP 202 with an empty body on " + CHECKED,
    "checked": CHECKED,
}


def official_file(sha256: str):
    return OFFICIAL_BY_SHA.get(sha256)


def download_pages() -> list:
    return [
        {"list": "EFRAG IG 3 List of ESRS Data Points (ESRS set 1, May 2024)", "page": IG3_PAGE},
        {"list": "2026 Draft List of ESRS Datapoints for the revised ESRS (28 August 2026), clean and "
                 "IG 3 mapping versions", "page": REVISED_PAGE, "news": REVISED_NEWS},
    ]


def binding_act(layout: str):
    key = BINDING_ACT.get(layout)
    if not key:
        return None
    act = LEGAL_ACTS[key]
    out = {"act": act["title"], "eli": act["eli"]}
    if "applies" in act:
        out["applies"] = act["applies"]
    return out
