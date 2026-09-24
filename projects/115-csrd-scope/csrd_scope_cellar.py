#!/usr/bin/env python3
"""The legal sources behind csrd-scope, fetched from CELLAR (the repository behind EUR-Lex).

Two jobs:

  refresh   rebuild data/*.json and data/SOURCES.md from CELLAR: act metadata and
            consolidated versions (SPARQL), the verbatim provisions the rules encode
            (quoted from pinned XHTML documents), the EU-27 list, the legal forms in
            Annexes I and II, and the national measures Member States notified.
  verify    compare live CELLAR metadata with the bundled snapshot, to learn whether a
            newer consolidated version or a new amending act exists (the rules would
            then need a human review). Exit 0 unchanged, 1 changed, 2 could not check.

Only the fixed queries and fixed CELEX identifiers in this file are sent. Nothing a
user types reaches the network. Standard library only.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import html
import http.client
import json
import re
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

VERSION = "0.1.0"
SPARQL_ENDPOINT = "https://publications.europa.eu/webapi/rdf/sparql"
CELEX_RESOURCE = "https://publications.europa.eu/resource/celex/"
USER_AGENT = f"csrd-scope/{VERSION} (+https://github.com/Keremozdemirra/csrd-scope)"
TIMEOUT = 60
MAX_BYTES = 8_000_000  # the largest document used (consolidated 2013/34/EU) is ~0.8 MB

# CELEX grammar used before anything is put in a URL (sector digit, year, type, number,
# optional consolidation date). Every identifier below is a constant, but the check keeps
# a future edit from sending something else.
CELEX_RE = re.compile(r"^[0-9]{5}[A-Z]{1,2}[0-9]{4,5}(?:-[0-9]{8})?$")

# The versions the rules in csrd_scope.py were written against. `verify` reports when
# CELLAR lists a newer consolidated version or a new amending act.
PINNED = {
    "32013L0034": "02013L0034-20260318",
    "32022L2464": "02022L2464-20260318",
    "32004L0109": "02004L0109-20240109",
    "32019R2088": "02019R2088-20260702",
}
BASE_ACTS = ("32013L0034", "32022L2464")
ACTS = ("32013L0034", "32022L2464", "32025L0794", "32026L0470", "32023L2775",
        "32004L0109", "32019R2088", "52024XC06792")
NIM_DIRECTIVES = ("32022L2464", "32025L0794", "32026L0470")

# Documents quoted. The two older consolidated versions hold the wording that applied
# before Delegated Directive (EU) 2023/2775 and before Directive (EU) 2026/470.
DOCUMENTS = (
    "02013L0034-20260318", "02022L2464-20260318", "32026L0470", "32025L0794",
    "32023L2775", "02013L0034-20230105", "02013L0034-20240528", "02004L0109-20240109",
    "52024XC06792", "02019R2088-20260702", "02022L2464-20250417",
)

# (id, document, citation, first words, last words). The quote is the text from the
# first words through the last words, after normalisation (see normalise()).
QUOTES = (
    ("consolidated-disclaimer", "02013L0034-20260318", "Consolidated text header (EUR-Lex)",
     "This text is meant purely as a documentation tool and has no legal effect.", None),
    ("AD-1-1", "02013L0034-20260318", "Art. 1(1) Directive 2013/34/EU",
     "The coordination measures prescribed by this Directive shall apply to the laws",
     "which have a legal form comparable to those listed in Annex I."),
    ("AD-1-3", "02013L0034-20260318", "Art. 1(3) first subparagraph Directive 2013/34/EU",
     "The coordination measures prescribed by Articles 19a, 29a, 29d, 30 and 33",
     "credit institutions as defined in point (1) of Article 4(1) of Regulation (EU) No 575/2013"),
    ("AD-1-3-2", "02013L0034-20260318", "Art. 1(3) second subparagraph Directive 2013/34/EU",
     "Member States may choose not to apply the coordination measures referred to in the first subparagraph of this paragraph",
     "points (2) to (23) of Article 2(5) of Directive 2013/36/EU"),
    ("AD-1-4", "02013L0034-20260318", "Art. 1(4) Directive 2013/34/EU",
     "The coordination measures prescribed by Articles 19a, 29a and 29d shall not apply to the European Financial Stability Facility",
     "points (b) and (f) of point (12) of Article 2 of Regulation (EU) 2019/2088"),
    ("AD-2-1", "02013L0034-20260318", "Art. 2(1) Directive 2013/34/EU",
     "‘public-interest entities’ means undertakings within the scope of Article 1 which are:",
     "or the number of their employees;"),
    ("AD-2-5", "02013L0034-20260318", "Art. 2(5) Directive 2013/34/EU",
     "‘net turnover’ means the amounts derived from the sale of products",
     "on the basis of which the financial statements of the undertaking are prepared;"),
    ("AD-2-15", "02013L0034-20260318", "Art. 2(15) Directive 2013/34/EU",
     "‘financial holding undertakings’ means",
     "without prejudice to their rights as shareholders;"),
    ("AD-3-4", "02013L0034-20260318", "Art. 3(4) Directive 2013/34/EU",
     "Large undertakings shall be undertakings which on their balance sheet dates exceed at least two of the three following criteria:",
     "average number of employees during the financial year: 250."),
    ("AD-3-7", "02013L0034-20260318", "Art. 3(7) Directive 2013/34/EU",
     "Large groups shall be groups consisting of parent and subsidiary undertakings",
     "average number of employees during the financial year: 250."),
    ("AD-3-8", "02013L0034-20260318", "Art. 3(8) Directive 2013/34/EU",
     "Member States shall permit the set-off referred to in Article 24(3)",
     "shall be increased by 20 %."),
    ("AD-3-10", "02013L0034-20260318", "Art. 3(10) Directive 2013/34/EU",
     "Where, on its balance sheet date, an undertaking or a group exceeds or ceases to exceed",
     "only if it occurs in two consecutive financial years."),
    ("AD-3-13", "02013L0034-20260318", "Art. 3(13) Directive 2013/34/EU",
     "In order to adjust for the effects of inflation, the Commission shall at least every five years",
     "the second, fourth and fifth subparagraphs of Article 40a(1)."),
    ("AD-19a-1", "02013L0034-20260318", "Art. 19a(1) first subparagraph Directive 2013/34/EU",
     "Undertakings which, on their balance sheet dates, exceed a net turnover of EUR 450 000 000 and an average number of 1 000 employees during the financial year shall include in their management report",
     "affect the undertaking’s development, performance and position."),
    ("AD-19a-3-protected", "02013L0034-20260318", "Art. 19a(3) second subparagraph point (b) Directive 2013/34/EU",
     "‘protected undertaking’ means an undertaking which:",
     "is in the value chain of a reporting undertaking;"),
    ("AD-19a-9", "02013L0034-20260318", "Art. 19a(9) first subparagraph Directive 2013/34/EU",
     "Provided that the conditions set out in the second subparagraph of this paragraph are met, an undertaking which is a subsidiary undertaking shall be exempted",
     "drawn up in accordance with Articles 29 and 29a."),
    ("AD-19a-10", "02013L0034-20260318", "Art. 19a(10) Directive 2013/34/EU",
     "The exemption laid down in paragraph 9 shall also apply to public-interest entities subject to the requirements of this Article.", None),
    ("AD-29a-1", "02013L0034-20260318", "Art. 29a(1) first subparagraph Directive 2013/34/EU",
     "Parent undertakings of a group which, on its balance sheet date, exceeds, on a consolidated basis, a net turnover of EUR 450 000 000",
     "affect the group’s development, performance and position."),
    ("AD-29a-7a", "02013L0034-20260318", "Art. 29a(7a) Directive 2013/34/EU",
     "By way of derogation from paragraph 1, Member States shall ensure that parent undertakings that are financial holding undertakings",
     "the information referred to in paragraph 1."),
    ("AD-29a-8", "02013L0034-20260318", "Art. 29a(8) first subparagraph Directive 2013/34/EU",
     "Provided that the conditions set out in the second subparagraph of this paragraph are met, a parent undertaking which is a subsidiary undertaking shall be exempted",
     "drawn up in accordance with Article 29 and this Article."),
    ("AD-29a-9", "02013L0034-20260318", "Art. 29a(9) Directive 2013/34/EU",
     "The exemption laid down in paragraph 8 shall also apply to public-interest entities subject to the requirements of this Article.", None),
    ("AD-30-1", "02013L0034-20260318", "Art. 30(1) Directive 2013/34/EU",
     "Member States shall ensure that undertakings publish within a reasonable period of time, which shall not exceed 12 months after the balance sheet date", None),
    ("AD-40", "02013L0034-20260318", "Art. 40 Directive 2013/34/EU",
     "A public-interest entity shall be treated as a large undertaking",
     "average number of employees during the financial year."),
    ("AD-40a-1-1", "02013L0034-20260318", "Art. 40a(1) first subparagraph Directive 2013/34/EU",
     "A Member State shall require that a subsidiary undertaking established in its territory whose ultimate parent undertaking is governed by the law of a third country",
     "at the group level of that ultimate third-country parent undertaking."),
    ("AD-40a-1-2", "02013L0034-20260318", "Art. 40a(1) second subparagraph Directive 2013/34/EU",
     "The first subparagraph shall only apply to subsidiary undertakings which, on their balance sheet dates, exceed a net turnover of EUR 200 000 000 in the preceding financial year.", None),
    ("AD-40a-1-3", "02013L0034-20260318", "Art. 40a(1) third subparagraph Directive 2013/34/EU",
     "A Member State shall require that a branch located in its territory",
     "or, if not applicable, the individual level, of the third-country undertaking."),
    ("AD-40a-1-4", "02013L0034-20260318", "Art. 40a(1) fourth subparagraph Directive 2013/34/EU",
     "The rule referred to in the third subparagraph shall only apply to a branch",
     "exceeding EUR 200 000 000 in the preceding financial year."),
    ("AD-40a-1-5", "02013L0034-20260318", "Art. 40a(1) fifth subparagraph Directive 2013/34/EU",
     "The first and third subparagraphs shall only apply to the subsidiary undertakings or branches referred to in those subparagraphs",
     "for each of the last two consecutive financial years."),
    ("AD-40a-1-7", "02013L0034-20260318", "Art. 40a(1) seventh subparagraph Directive 2013/34/EU",
     "By way of derogation from the first and third subparagraphs, where the third-country undertaking is a financial holding undertaking",
     "referred to in the first and third subparagraphs."),
    ("AD-40d-1", "02013L0034-20260318", "Art. 40d(1) Directive 2013/34/EU",
     "The subsidiary undertakings and branches referred to in Article 40a(1) of this Directive shall publish their sustainability report",
     "within 12 months of the balance sheet date of the financial year for which the report is drawn up"),
    ("AD-48i-1", "02013L0034-20260318", "Art. 48i(1) first subparagraph Directive 2013/34/EU",
     "Until 6 January 2030, Member States shall permit a Union subsidiary undertaking which is subject to Article 19a or 29a",
     "that are subject to Article 19a or 29a."),
    ("CSRD-5-2-a", "02022L2464-20260318", "Art. 5(2) first subparagraph point (a) Directive (EU) 2022/2464",
     "Member States shall apply the measures necessary to comply with Article 1, with the exception of point (14):",
     "on a consolidated basis, the average number of 500 employees during the financial year;"),
    ("CSRD-5-2-b", "02022L2464-20260318", "Art. 5(2) first subparagraph point (b) Directive (EU) 2022/2464",
     "for financial years starting on or after 1 January 2027: (i) to undertakings which, on their balance sheet dates, exceed",
     "on a consolidated basis, a net turnover of EUR 450 000 000 and an average number of 1 000 employees during the financial year."),
    ("CSRD-5-2-sub2", "02022L2464-20260318", "Art. 5(2) second subparagraph Directive (EU) 2022/2464",
     "Member States shall apply the measures necessary to comply with point (14) of Article 1 for financial years starting on or after 1 January 2028.", None),
    ("CSRD-5-2-sub3-a", "02022L2464-20260318", "Art. 5(2) third subparagraph point (a) Directive (EU) 2022/2464",
     "Member States shall apply the measures necessary to comply with Article 2:",
     "on a consolidated basis, the average number of 500 employees during the financial year;"),
    ("CSRD-5-2-sub3-b", "02022L2464-20260318", "Art. 5(2) third subparagraph point (b) Directive (EU) 2022/2464",
     "(i) to issuers as defined in point (d) of Article 2(1) of Directive 2004/109/EC which are undertakings which, on their balance sheet dates, exceed",
     "on a consolidated basis, a net turnover of EUR 450 000 000 and an average number of 1 000 employees during the financial year."),
    ("CSRD2025-5-2-b", "02022L2464-20250417",
     "Art. 5(2) first subparagraph point (b) Directive (EU) 2022/2464 as amended by Directive (EU) 2025/794 (before Directive (EU) 2026/470)",
     "for financial years starting on or after 1 January 2027: (i) to large undertakings within the meaning of Article 3(4) of Directive 2013/34/EU",
     "other than those referred to in point (a)(ii) of this subparagraph;"),
    ("CSRD2025-5-2-sub3-b", "02022L2464-20250417",
     "Art. 5(2) third subparagraph point (b) Directive (EU) 2022/2464 as amended by Directive (EU) 2025/794 (before Directive (EU) 2026/470)",
     "(i) to issuers as defined in point (d) of Article 2(1) of Directive 2004/109/EC which are large undertakings within the meaning of Article 3(4) of Directive 2013/34/EU other than those",
     "other than those referred to in point (a) (ii) of this subparagraph;"),
    ("CSRD-5-2-derogation", "02022L2464-20260318", "Art. 5(2) fifth subparagraph Directive (EU) 2022/2464",
     "By way of derogation from point (a) of the first subparagraph and point (a) of the third subparagraph, Member States may exempt",
     "for the financial years starting between 1 January 2025 and 31 December 2026."),
    ("OMNI-title", "32026L0470", "Directive (EU) 2026/470, title",
     "DIRECTIVE (EU) 2026/470 OF THE EUROPEAN PARLIAMENT AND OF THE COUNCIL of 24 February 2026",
     "certain corporate sustainability due diligence requirements"),
    ("OMNI-oj", "32026L0470", "Directive (EU) 2026/470, Official Journal reference",
     "L series 2026/470 26.2.2026", None),
    ("OMNI-rec-7", "32026L0470", "Recital (7) Directive (EU) 2026/470",
     "the obligation to prepare and publish sustainability reporting at individual level should be limited to undertakings with a net turnover exceeding EUR 450 000 000",
     "as defined in the national measures transposing Directive 2013/34/EU."),
    ("OMNI-rec-31", "32026L0470", "Recital (31) Directive (EU) 2026/470",
     "Nevertheless, with a view to reducing burden as swiftly as possible, Member States should be able to exempt such undertakings",
     "between 1 January 2025 and 31 December 2026."),
    ("OMNI-5-1", "32026L0470", "Art. 5(1) Directive (EU) 2026/470",
     "Member States shall bring into force the laws, regulations and administrative provisions necessary to comply with Articles 1, 2 and 3 by 19 March 2027.",
     "necessary to comply with Article 4 by 26 July 2028."),
    ("OMNI-6", "32026L0470", "Art. 6 Directive (EU) 2026/470",
     "This Directive shall enter into force on the twentieth day following that of its publication in the Official Journal of the European Union.", None),
    ("STC-oj", "32025L0794", "Directive (EU) 2025/794, Official Journal reference",
     "L series 2025/794 16.4.2025", None),
    ("STC-1", "32025L0794", "Art. 1 Directive (EU) 2025/794",
     "Article 5(2) of Directive (EU) 2022/2464 is amended as follows:",
     "‘for financial years starting on or after 1 January 2028:’."),
    ("STC-3", "32025L0794", "Art. 3(1) Directive (EU) 2025/794",
     "Member States shall bring into force the laws, regulations and administrative provisions necessary to comply with this Directive by 31 December 2025.", None),
    ("STC-4", "32025L0794", "Art. 4 Directive (EU) 2025/794",
     "This Directive shall enter into force on the day following that of its publication in the Official Journal of the European Union.", None),
    ("DD-2-1", "32023L2775", "Art. 2(1) second and third subparagraphs Delegated Directive (EU) 2023/2775",
     "They shall apply those provisions for financial years beginning on or after 1 January 2024.",
     "for financial year beginning on or after 1 January 2023."),
    ("ADOLD-3-4", "02013L0034-20230105", "Art. 3(4) Directive 2013/34/EU before Delegated Directive (EU) 2023/2775",
     "Large undertakings shall be undertakings which on their balance sheet dates exceed at least two of the three following criteria:",
     "average number of employees during the financial year: 250."),
    ("AD2024-19a-10", "02013L0034-20240528", "Art. 19a(10) Directive 2013/34/EU before Directive (EU) 2026/470",
     "The exemption laid down in paragraph 9 shall also apply to public-interest entities subject to the requirements of this Article, with the exception of large undertakings",
     "defined in point (a) of point (1) of Article 2 of this Directive."),
    ("AD2024-29a-9", "02013L0034-20240528", "Art. 29a(9) Directive 2013/34/EU before Directive (EU) 2026/470",
     "The exemption laid down in paragraph 8 shall also apply to public-interest entities subject to the requirements of this Article, with the exception of large undertakings",
     "defined in point (a) of point (1) of Article 2 of this Directive."),
    ("TD-2-1-d", "02004L0109-20240109", "Art. 2(1)(d) Directive 2004/109/EC",
     "‘issuer’ means a natural person, or a legal entity governed by private or public law, including a State, whose securities are admitted to trading on a regulated market.", None),
    ("TD-4-5", "02004L0109-20240109", "Art. 4(5) Directive 2004/109/EC",
     "The management report shall be drawn up in accordance with Articles 19, 19a and 20, and Article 29d(1) of Directive 2013/34/EU",
     "when drawn up by undertakings referred to in those provisions."),
    ("TD-4-1", "02004L0109-20240109", "Art. 4(1) Directive 2004/109/EC",
     "The issuer shall make public its annual financial report at the latest four months after the end of each financial year", None),
    ("TD-8-1-b", "02004L0109-20240109", "Art. 8(1)(b) Directive 2004/109/EC",
     "an issuer exclusively of debt securities admitted to trading on a regulated market, the denomination per unit of which is at least EUR 100 000",
     "equivalent to at least EUR 100 000."),
    ("NOTICE-status", "52024XC06792", "Commission Notice C/2024/6792, introduction",
     "The replies to the FAQs contained in this Notice clarify the provisions already contained in the applicable legislation.",
     "nor introduce any additional requirements."),
    ("NOTICE-FAQ1", "52024XC06792", "Commission Notice C/2024/6792, FAQ 1",
     "The rules to determine the size of an undertaking for sustainability reporting purposes rely on the existing rules",
     "set out in the national measures transposing the preexisting Accounting Directive."),
    ("NOTICE-FAQ2", "52024XC06792", "Commission Notice C/2024/6792, FAQ 2",
     "The rules to determine the size category of an undertaking for sustainability reporting purposes, when that undertaking is evolving",
     "set out in the national measures transposing the preexisting Accounting Directive."),
    ("NOTICE-FAQ3", "52024XC06792", "Commission Notice C/2024/6792, FAQ 3",
     "Union legislation does not regulate the calculation of the average number of employees",
     "as guidance regarding the measurement of staff headcount, as a proxy of an average number of employees"),
    ("NOTICE-40a", "52024XC06792", "Commission Notice C/2024/6792, Section II (Article 40a, pre-2026 thresholds)",
     "Based on Article 40a of the Accounting Directive, where a third-country undertaking that generates a net turnover of more than EUR 150 million",
     "at the group level of the third-country parent undertaking."),
    ("NOTICE-FAQ43", "52024XC06792", "Commission Notice C/2024/6792, FAQ 43",
     "To avoid double reporting by the subsidiaries and branches of the same third-country undertaking, Member States may allow",
     "published by another Union subsidiary or branch of the third-country undertaking."),
    ("NOTICE-FAQ48", "52024XC06792", "Commission Notice C/2024/6792, FAQ 48",
     "Therefore, a Union subsidiary publishing a sustainability report at the group level of its third-country parent company",
     "from complying with the reporting obligations of Articles 19a and/or 29a."),
    ("NOTICE-fn18", "52024XC06792", "Commission Notice C/2024/6792, footnote 18",
     "Relevant reporting requirements for undertakings governed by the law of a third country:",
     "and Article 40a Accounting Directive."),
    ("SFDR-2-12", "02019R2088-20260702", "Art. 2(12) Regulation (EU) 2019/2088",
     "‘financial product’ means:", "a PEPP;"),
)

# Annexes I and II name Member States in these forms; everything else must match the
# EU-27 list exactly. The consolidated text still lists the United Kingdom.
ANNEX_ALIASES = {"Czech Republic": "Czechia"}

Q_ACTS = """PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT DISTINCT ?celex ?work ?inforce ?date ?endvalid ?title WHERE {
  VALUES ?celex { %s }
  ?work cdm:resource_legal_id_celex ?celex .
  OPTIONAL { ?work cdm:resource_legal_in-force ?inforce }
  OPTIONAL { ?work cdm:work_date_document ?date }
  OPTIONAL { ?work cdm:resource_legal_date_end-of-validity ?endvalid }
  OPTIONAL { ?expr cdm:expression_belongs_to_work ?work ;
                   cdm:expression_uses_language <http://publications.europa.eu/resource/authority/language/ENG> ;
                   cdm:expression_title ?title }
}"""

Q_CONSOLIDATED = """PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT DISTINCT ?base ?celex ?date WHERE {
  VALUES ?base { "32013L0034"^^xsd:string "32022L2464"^^xsd:string "32004L0109"^^xsd:string "32019R2088"^^xsd:string }
  ?b cdm:resource_legal_id_celex ?base .
  ?cons cdm:act_consolidated_consolidates_resource_legal ?b ;
        cdm:resource_legal_id_celex ?celex .
  OPTIONAL { ?cons cdm:act_consolidated_date ?date }
  FILTER(STRSTARTS(?celex, CONCAT("0", SUBSTR(?base, 2))))
}"""

Q_AMENDING = """PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT DISTINCT ?base ?celex ?date ?title WHERE {
  VALUES ?base { "32013L0034"^^xsd:string "32022L2464"^^xsd:string }
  ?b cdm:resource_legal_id_celex ?base .
  ?act cdm:resource_legal_amends_resource_legal ?b ;
       cdm:resource_legal_id_celex ?celex ;
       cdm:work_date_document ?date .
  FILTER(?date >= "2023-01-01"^^xsd:date)
  OPTIONAL { ?expr cdm:expression_belongs_to_work ?act ;
                   cdm:expression_uses_language <http://publications.europa.eu/resource/authority/language/ENG> ;
                   cdm:expression_title ?title }
}"""

# Aggregates (MAX, SAMPLE) returned inconsistent dates on this endpoint on 2026-09-24,
# so rows come back raw and are grouped here.
Q_NIM = """PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT DISTINCT ?dir ?c ?country ?notif ?ojn ?ojno ?e ?t WHERE {
  VALUES ?dir { "32022L2464"^^xsd:string "32025L0794"^^xsd:string "32026L0470"^^xsd:string }
  ?d cdm:resource_legal_id_celex ?dir .
  ?m cdm:measure_national_implementing_implements_resource_legal ?d ;
     cdm:measure_national_implementing_implemented_by_country ?country ;
     cdm:resource_legal_id_celex ?c .
  FILTER(STRSTARTS(?c, CONCAT("7", SUBSTR(?dir, 2))))
  OPTIONAL { ?m cdm:measure_national_implementing_date_notification ?notif }
  OPTIONAL { ?m cdm:measure_national_implementing_name_official_journal ?ojn }
  OPTIONAL { ?m cdm:measure_national_implementing_number_official_journal ?ojno }
  OPTIONAL { ?m cdm:eli ?e }
  OPTIONAL { ?m cdm:work_title ?t }
}"""

Q_EU_COUNTRIES = """PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX lemon: <http://lemon-model.net/lemon#>
SELECT DISTINCT ?c ?label ?n WHERE {
  ?c lemon:context <http://publications.europa.eu/resource/authority/use-context/EU_COU> ;
     skos:inScheme <http://publications.europa.eu/resource/authority/country> ;
     skos:prefLabel ?label .
  FILTER(lang(?label) = "en")
  OPTIONAL { ?c skos:notation ?n }
}"""

# Consolidated texts can lag behind the acts that amend or correct them. Every act relied
# on is checked for amendments, corrigenda and consolidations dated 2024 or later.
Q_AFTER = """PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT DISTINCT ?base ?rel ?celex ?date WHERE {
  VALUES ?base { %s }
  ?b cdm:resource_legal_id_celex ?base .
  { ?x cdm:resource_legal_amends_resource_legal ?b . BIND("amends" AS ?rel) }
  UNION { ?x cdm:resource_legal_corrects_resource_legal ?b . BIND("corrects" AS ?rel) }
  UNION { ?x cdm:act_consolidated_consolidates_resource_legal ?b . BIND("consolidates" AS ?rel) }
  ?x cdm:resource_legal_id_celex ?celex .
  OPTIONAL { ?x cdm:work_date_document ?d1 }
  OPTIONAL { ?x cdm:act_consolidated_date ?d2 }
  BIND(COALESCE(?d2, ?d1) AS ?date)
  FILTER(?date >= "2024-01-01"^^xsd:date)
}"""

Q_LANGS = """PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT DISTINCT ?celex ?lang WHERE {
  VALUES ?celex { %s }
  ?w cdm:resource_legal_id_celex ?celex .
  ?e cdm:expression_belongs_to_work ?w ; cdm:expression_uses_language ?l .
  BIND(REPLACE(STR(?l), "^.*/", "") AS ?lang)
}"""
CORRIGENDUM_RE = re.compile(r"^[0-9]{5}[A-Z]{1,2}[0-9]{4,5}R\([0-9]{2}\)$")

QUERIES = {"acts": None, "consolidated": Q_CONSOLIDATED, "amending": Q_AMENDING,
           "national_measures": Q_NIM, "eu_countries": Q_EU_COUNTRIES}


class SourceError(Exception):
    """CELLAR could not be reached or answered with something unusable."""


def acts_query() -> str:
    for c in ACTS:
        _check_celex(c)
    return Q_ACTS % " ".join(f'"{c}"^^xsd:string' for c in ACTS)


def after_query() -> str:
    return Q_AFTER % " ".join(f'"{_check_celex(c)}"^^xsd:string' for c in ACTS)


def related_since_2024(run=None) -> list[dict]:
    """Amendments, corrigenda (with the languages they correct) and consolidations since 2024."""
    run = run or sparql
    rows = []
    for r in run(after_query()):
        base, rel, celex = r.get("base"), r.get("rel"), r.get("celex", "")
        if base not in ACTS or rel not in ("amends", "corrects", "consolidates"):
            continue
        # A consolidation row also comes back for every act that a consolidated text of
        # another act includes; keep only the act's own consolidated versions.
        if rel == "consolidates" and not celex.startswith("0" + base[1:]):
            continue
        rows.append({"base": base, "rel": rel, "celex": celex, "date": r.get("date")})
    corr = sorted({x["celex"] for x in rows if x["rel"] == "corrects" and CORRIGENDUM_RE.match(x["celex"])})
    langs: dict = {}
    if corr:
        values = " ".join(f'"{c}"^^xsd:string' for c in corr)
        for r in run(Q_LANGS % values):
            if r.get("celex") in corr and re.fullmatch(r"[A-Z]{3}", r.get("lang", "")):
                langs.setdefault(r["celex"], set()).add(r["lang"])
    for x in rows:
        if x["rel"] == "corrects":
            x["languages"] = sorted(langs.get(x["celex"], set()))
    dedup = {(x["base"], x["rel"], x["celex"]): x for x in rows}
    return sorted(dedup.values(), key=lambda x: (x["base"], x["rel"], x["date"] or "", x["celex"]))


def _check_celex(celex: str) -> str:
    if not isinstance(celex, str) or not CELEX_RE.match(celex):
        raise SourceError(f"refusing to request a malformed CELEX identifier: {celex!r}")
    return celex


# ------------------------------------------------------------------ network

def _short(url: str) -> str:
    # Error messages name the endpoint, not the whole query string.
    return url.split("?", 1)[0] + ("?query=..." if "?" in url else "")


def _read(url: str, accept: str, extra_headers: dict | None = None) -> tuple[bytes, str]:
    shown = _short(url)
    headers = {"Accept": accept, "User-Agent": USER_AGENT}
    headers.update(extra_headers or {})
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read(MAX_BYTES + 1)
            final = resp.geturl() if hasattr(resp, "geturl") else url
    except urllib.error.HTTPError as e:
        if e.code == 429:
            retry = (e.headers or {}).get("Retry-After") if e.headers is not None else None
            raise SourceError(f"CELLAR rate limit (HTTP 429){'; retry after ' + str(retry) if retry else ''}: {shown}") from None
        raise SourceError(f"CELLAR answered HTTP {e.code} for {shown}") from None
    except urllib.error.URLError as e:
        raise SourceError(f"CELLAR unreachable ({e.reason}): {shown}") from None
    except (socket.timeout, TimeoutError):
        raise SourceError(f"CELLAR timed out after {TIMEOUT}s: {shown}") from None
    except http.client.HTTPException as e:
        raise SourceError(f"CELLAR connection broke ({type(e).__name__}): {shown}") from None
    except OSError as e:
        raise SourceError(f"CELLAR connection failed ({e}): {shown}") from None
    if len(body) > MAX_BYTES:
        raise SourceError(f"CELLAR response larger than {MAX_BYTES} bytes: {shown}")
    if not body:
        raise SourceError(f"CELLAR answered with an empty body: {shown}")
    return body, final


def sparql(query: str) -> list[dict]:
    """Run one fixed query; return bindings as {variable: value} dicts."""
    url = SPARQL_ENDPOINT + "?" + urllib.parse.urlencode({"query": query})
    body, _ = _read(url, "application/sparql-results+json")
    try:
        data = json.loads(body.decode("utf-8"))
    except UnicodeDecodeError:
        raise SourceError("CELLAR SPARQL answer is not UTF-8") from None
    except json.JSONDecodeError:
        raise SourceError("CELLAR SPARQL answer is not JSON") from None
    if not isinstance(data, dict) or not isinstance(data.get("results"), dict) \
            or not isinstance(data["results"].get("bindings"), list):
        raise SourceError("CELLAR SPARQL answer has no results.bindings list")
    rows = []
    for b in data["results"]["bindings"]:
        if not isinstance(b, dict):
            raise SourceError("CELLAR SPARQL answer has a malformed binding")
        row = {}
        for k, v in b.items():
            if not isinstance(v, dict) or not isinstance(v.get("value"), str):
                raise SourceError("CELLAR SPARQL answer has a malformed value")
            row[k] = v["value"]
            if v.get("datatype"):
                row[k + "@type"] = v["datatype"]
        rows.append(row)
    return rows


def fetch_document(celex: str) -> dict:
    """The English XHTML of one act or consolidated version, by content negotiation."""
    url = CELEX_RESOURCE + _check_celex(celex)
    body, final = _read(url, "application/xhtml+xml, text/html;q=0.9", {"Accept-Language": "eng"})
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        raise SourceError(f"document {celex} is not UTF-8") from None
    return {"celex": celex, "url": url, "resolved_url": final, "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(), "text": text}


# ------------------------------------------------------------------ text

class _TextParser(HTMLParser):
    """Visible text of an XHTML page; every tag boundary becomes a space."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head"):
            self.skip += 1
        self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head") and self.skip:
            self.skip -= 1
        self.parts.append(" ")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def normalise(markup: str) -> str:
    """One line of text: consolidation markers (►M8, ▼B, ◄) removed, whitespace collapsed,
    no space before punctuation or inside brackets, so quotes can be matched literally."""
    p = _TextParser()
    try:
        p.feed(markup)
        p.close()
    except Exception as e:  # html.parser raises little, but a broken document must not crash refresh
        raise SourceError(f"could not parse document markup: {type(e).__name__}") from None
    t = html.unescape("".join(p.parts))
    t = re.sub(r"[►▼][A-Z][0-9]*|◄", " ", t)
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"\s+([.,;:)’])", r"\1", t)
    t = re.sub(r"([(‘])\s+", r"\1", t)
    return t.strip()


def extract(text: str, start: str, end: str | None) -> str | None:
    i = text.find(start)
    if i < 0:
        return None
    if end is None:
        return start
    j = text.find(end, i + len(start) - len(end) if end in start else i)
    if j < 0 or j - i > 4000:
        return None
    return text[i:j + len(end)]


def parse_annexes(text: str, eu_names: dict) -> dict:
    """Legal forms per Member State from Annexes I and II (Art. 1(1)), keyed by ISO alpha-2."""
    out = {"annex_i": {}, "annex_ii": {}, "not_eu_member_states": []}
    a1 = text.find("ANNEX I TYPES OF UNDERTAKING REFERRED TO IN POINT (A) OF ARTICLE 1(1)")
    a2 = text.find("ANNEX II TYPES OF UNDERTAKING REFERRED TO IN POINT (b) OF ARTICLE 1(1)")
    a3 = text.find("ANNEX III", a2 + 1) if a2 >= 0 else -1
    if min(a1, a2, a3) < 0:
        raise SourceError("Annexes I and II not found in the consolidated text")
    labels = sorted(list(eu_names) + list(ANNEX_ALIASES) + ["United Kingdom"], key=len, reverse=True)
    # Entries start with a dash and a Member State name; a dash inside an entry (Malta's
    # Annex II entry has one) is not followed by a name.
    head = re.compile(r"— (?:In )?(?:the )?(" + "|".join(re.escape(x) for x in labels) + r")\b:?\s*")
    for key, chunk in (("annex_i", text[a1:a2]), ("annex_ii", text[a2:a3])):
        found = list(head.finditer(chunk))
        if not found:
            raise SourceError(f"no Member State entries found in {key}")
        for n, m in enumerate(found):
            stop = found[n + 1].start() if n + 1 < len(found) else len(chunk)
            forms = chunk[m.end():stop].strip().rstrip(" ;.")
            name = m.group(1)
            if name == "United Kingdom":
                out["not_eu_member_states"].append(f"{key}: United Kingdom")
                continue
            out[key][eu_names[ANNEX_ALIASES.get(name, name)]] = forms
    for key in ("annex_i", "annex_ii"):
        if len(out[key]) != len(eu_names):
            raise SourceError(f"{key} lists {len(out[key])} EU Member States, expected {len(eu_names)}")
    return out


# ------------------------------------------------------------------ snapshot

def _today() -> str:
    return _dt.date.today().isoformat()


def build_snapshot(today: str | None = None, run=sparql, fetch=fetch_document) -> dict:
    """Everything data/ holds, rebuilt from CELLAR. Raises SourceError on any failure."""
    today = today or _today()
    acts = {}
    for r in run(acts_query()):
        c = r.get("celex")
        if c not in ACTS:
            continue
        a = acts.setdefault(c, {"cellar_work": r.get("work")})
        if "inforce" in r:
            a["in_force"] = r["inforce"] in ("1", "true")
        for k_in, k_out in (("date", "date_document"), ("endvalid", "end_of_validity"), ("title", "title")):
            if r.get(k_in):
                a[k_out] = r[k_in]
    missing = [c for c in ACTS if c not in acts]
    if missing:
        raise SourceError(f"CELLAR does not list {', '.join(missing)}")

    consolidated: dict = {}
    for r in run(Q_CONSOLIDATED):
        if r.get("base") in PINNED and r.get("celex", "").startswith("0"):
            consolidated.setdefault(r["base"], []).append({"celex": r["celex"], "date": r.get("date")})
    for base in consolidated:
        consolidated[base].sort(key=lambda v: v["celex"], reverse=True)
    for base, pinned in PINNED.items():
        if pinned not in [v["celex"] for v in consolidated.get(base, [])]:
            raise SourceError(f"pinned consolidated version {pinned} is not listed by CELLAR")

    amending: dict = {}
    for r in run(Q_AMENDING):
        if r.get("base") in BASE_ACTS and r.get("celex"):
            lst = amending.setdefault(r["base"], [])
            if r["celex"] not in [a["celex"] for a in lst]:
                lst.append({"celex": r["celex"], "date": r.get("date"), "title": r.get("title", "")})
    for base in amending:
        amending[base].sort(key=lambda a: (a["date"] or "", a["celex"]), reverse=True)

    countries: dict = {}
    for r in run(Q_EU_COUNTRIES):
        code = r.get("c", "").rsplit("/", 1)[-1]
        if not re.fullmatch(r"[A-Z]{3}", code):
            continue
        rec = countries.setdefault(code, {"alpha3": code, "name": r.get("label")})
        typ = (r.get("n@type") or "").rsplit("#", 1)[-1]
        if typ == "ISO_3166_1_ALPHA_2":
            rec["alpha2"] = r.get("n")
        elif typ == "ISG_COU":
            rec["isg"] = r.get("n")
    member_states = sorted((c for c in countries.values() if c.get("alpha2")), key=lambda c: c["alpha2"])
    if len(member_states) != 27:
        raise SourceError(f"expected 27 EU Member States in the EU_COU list, got {len(member_states)}")

    measures = []
    for r in run(Q_NIM):
        if r.get("dir") not in NIM_DIRECTIVES:
            continue
        measures.append({
            "directive": r["dir"],
            "country": r.get("country", "").rsplit("/", 1)[-1],
            "celex": r.get("c"),
            "notified": r.get("notif"),
            "official_journal": " ".join(x for x in (r.get("ojn", "").strip(), r.get("ojno", "").strip()) if x),
            "eli": r.get("e"),
            # Titles are national text: bounded here, and wrapped again on output.
            "title": re.sub(r"\s+", " ", r.get("t", ""))[:300],
        })
    measures.sort(key=lambda m: (m["directive"], m["country"], m["notified"] or "", m["celex"] or ""))

    documents, quotes, texts = {}, {}, {}
    for celex in DOCUMENTS:
        doc = fetch(celex)
        texts[celex] = normalise(doc["text"])
        documents[celex] = {k: doc[k] for k in ("url", "resolved_url", "bytes", "sha256")}
        documents[celex]["retrieved"] = today
    for qid, celex, cite, start, end in QUOTES:
        q = extract(texts[celex], start, end)
        if q is None:
            raise SourceError(f"quote {qid} not found in {celex}: the text may have changed; review the rules")
        quotes[qid] = {"celex": celex, "cite": cite, "text": q}
    eu_names = {m["name"]: m["alpha2"] for m in member_states}
    annexes = parse_annexes(texts[PINNED["32013L0034"]], eu_names)

    related = related_since_2024(run)

    legal_basis = {
        "schema": 1, "checked": today, "endpoint": SPARQL_ENDPOINT, "pinned": dict(PINNED),
        "acts": acts, "consolidated_versions": consolidated, "amending_acts_since_2023": amending,
        "related_since_2024": related,
        "documents": documents, "quotes": quotes,
    }
    return {
        "legal_basis.json": legal_basis,
        "national_measures.json": {"schema": 1, "checked": today, "endpoint": SPARQL_ENDPOINT,
                                   "directives": list(NIM_DIRECTIVES), "measures": measures},
        "member_states.json": {"schema": 1, "checked": today, "endpoint": SPARQL_ENDPOINT,
                               "source": "Publications Office, EU Vocabularies, country authority table, use-context EU_COU",
                               "member_states": member_states},
        "legal_forms.json": {"schema": 1, "checked": today, "source_celex": PINNED["32013L0034"],
                             "source": "Annexes I and II to Directive 2013/34/EU (consolidated text)", **annexes},
    }


def sources_markdown(snap: dict) -> str:
    lb = snap["legal_basis.json"]
    nm = snap["national_measures.json"]
    ms = snap["member_states.json"]
    lf = snap["legal_forms.json"]
    lines = [
        "# Sources", "",
        f"Everything in `data/` was rebuilt from CELLAR, the Publications Office repository behind EUR-Lex, on {lb['checked']}",
        "by `csrd-scope refresh` (standard library only). `csrd-scope verify-sources` compares the live",
        "CELLAR metadata with this snapshot.", "",
        "## Licence and attribution", "",
        "- EUR-Lex legal notice, https://eur-lex.europa.eu/content/legal-notice/legal-notice.html, read on 2026-09-24",
        "  from the archived copy of 2026-09-22 (https://web.archive.org/web/20260922160312/https://eur-lex.europa.eu/content/legal-notice/legal-notice.html;",
        "  the live page answered HTTP 202 with an empty body from the build environment). For the acts as published in",
        "  the Official Journal (32026L0470, 32025L0794, 32023L2775 and the others listed below): \"The Commission's",
        "  document reuse policy is based on Decision 2011/833/EU. Unless otherwise specified, you can re-use the legal",
        "  documents published in EUR-Lex for commercial or non-commercial purposes.\"",
        "- The same notice, for the consolidated texts (02013L0034-20260318, 02022L2464-20260318): \"The copyright for the",
        "  editorial content of this website, the summaries of EU legislation and the consolidated texts, which is owned",
        "  by the EU, is licensed under the Creative Commons Attribution 4.0 International licence. This means that you can",
        "  re-use the content provided you acknowledge the source and indicate any changes you have made.\"",
        "- Commission Decision 2011/833/EU, Article 4: \"All documents shall be available for reuse: (a) for commercial or",
        "  non-commercial purposes under the conditions laid down in Article 6\". Article 6(2): those conditions \"may",
        "  include the following: (a) the obligation for the reuser to acknowledge the source of the documents; (b) the",
        "  obligation not to distort the original meaning or message of the documents; (c) the non-liability of the",
        "  Commission for any consequence stemming from the reuse.\" Every answer names the source and says that its rules",
        "  are csrd-scope's encoding of the provisions, not the text.",
        "- The Publications Office copyright page refers EUR-Lex content to the EUR-Lex notice and says, for the conditions",
        "  of reuse of CELLAR content, \"please contact us at op-copyright@publications.europa.eu\".",
        "- Attribution used in every answer: `Source: EUR-Lex / CELLAR (Publications Office of the European Union),",
        "  © European Union. Reuse: EUR-Lex legal notice [...]: Official Journal texts may be re-used for commercial or",
        "  non-commercial purposes (Commission Decision 2011/833/EU, Arts 4 and 6); consolidated texts are licensed CC BY 4.0.",
        "  [...] Derived: csrd-scope's encoding of the provisions cited, not the text itself.`",
        "- What is bundled: identifiers, dates, titles, short verbatim quotations of the provisions the rules",
        "  encode, the legal-form lists of Annexes I and II, and national-measure metadata. No personal data.", "",
        "## Endpoints", "",
        f"- SPARQL: {lb['endpoint']} (queries in `csrd_scope_cellar.py`: `Q_ACTS`, `Q_CONSOLIDATED`, `Q_AMENDING`, `Q_AFTER`, `Q_LANGS`, `Q_NIM`, `Q_EU_COUNTRIES`)",
        f"- Documents: {CELEX_RESOURCE}<CELEX> with `Accept: application/xhtml+xml` and `Accept-Language: eng`", "",
        "## Acts", "", "| CELEX | Date | In force | Title |", "| --- | --- | --- | --- |",
    ]
    for c in ACTS:
        a = lb["acts"][c]
        title = (a.get("title") or "").replace("|", "/")
        lines.append(f"| {c} | {a.get('date_document', '')} | {'yes' if a.get('in_force') else 'no' if 'in_force' in a else ''} | {title[:160]} |")
    lines += ["", "## Consolidated versions listed by CELLAR", ""]
    for base, versions in lb["consolidated_versions"].items():
        pinned = lb["pinned"].get(base)
        vs = ", ".join(f"{v['celex']}{' (used)' if v['celex'] == pinned else ''}" for v in versions)
        lines.append(f"- {base}: {vs}")
    lines += ["", "## Acts amending 32013L0034 or 32022L2464 dated 2023-01-01 or later", ""]
    for base, acts in lb["amending_acts_since_2023"].items():
        for a in acts:
            lines.append(f"- {base} <- {a['celex']} ({a['date']}): {a['title'][:150]}")
    lines += ["", "## Amendments, corrigenda and consolidations since 2024 (every act relied on)", "",
              "A consolidated text can lag behind acts that amend or correct it, so each act relied on is checked.",
              "Corrigenda that do not correct the English version (ENG) do not change the text this tool quotes.", "",
              "| Act | Relation | CELEX | Date | Languages corrected |", "| --- | --- | --- | --- | --- |"]
    for x in lb.get("related_since_2024", []):
        lines.append(f"| {x['base']} | {x['rel']} | {x['celex']} | {x['date']} | {' '.join(x.get('languages', [])) if x['rel'] == 'corrects' else ''} |")
    lines += ["", "## Verification notes (2026-09-24, by hand, recorded here because they are not re-derived by refresh)", "",
              "- 02013L0034-20270130 is dated in the future. A text comparison with 02013L0034-20260318 found no difference",
              "  except the list of amending acts, which adds Directive (EU) 2025/2 (32025L0002). Its Article 2 replaces",
              "  Art. 19a(6) of Directive 2013/34/EU from 30 January 2027; Directive (EU) 2026/470 had already deleted that",
              "  paragraph. The rules use 02013L0034-20260318.",
              "- 02019R2088-20260702 (after amending Regulation (EU) 2024/3005): Art. 2(12) is identical to the original text 32019R2088.",
              "- Directive (EU) 2026/470 was published in OJ L 2026/470 on 26.2.2026 and enters into force on the twentieth day",
              "  following publication (Art. 6), i.e. 18 March 2026, the date of the consolidated versions used.",
              "- The Commission Notice C/2024/6792 predates Directive (EU) 2026/470; it is cited only for points the",
              "  amendment did not change (size timing, employee averaging, Article 40a mechanics) and it is not binding.",
              "- No amending act dated after 2026-03-18 is listed for 32013L0034 or 32022L2464, and no corrigendum since 2024",
              "  corrects the English version of any act relied on (table above). `verify-sources` repeats this check.", ""]
    lines += ["", "## Documents quoted", "", "| CELEX | Bytes | SHA-256 | Retrieved |", "| --- | --- | --- | --- |"]
    for c, d in lb["documents"].items():
        lines.append(f"| {c} | {d['bytes']} | `{d['sha256']}` | {d['retrieved']} |")
    lines += ["", f"{len(lb['quotes'])} quotations are stored in `legal_basis.json` under `quotes`.", "",
              "## National measures", "",
              f"`national_measures.json`: {len(nm['measures'])} national measures notified for "
              f"{', '.join(nm['directives'])} ({len({m['country'] for m in nm['measures']})} Member States with at least one).",
              "A notified measure does not show that transposition is complete or correct; a missing one does not",
              "show that no national measure exists.", "",
              "## Member States and legal forms", "",
              f"`member_states.json`: {len(ms['member_states'])} Member States ({ms['source']}).",
              f"`legal_forms.json`: Annex I and Annex II entries for {len(lf['annex_i'])} Member States from {lf['source_celex']};"
              f" skipped because not an EU Member State: {', '.join(lf['not_eu_member_states']) or 'none'}.", ""]
    return "\n".join(lines)


def write_snapshot(out_dir: Path, snap: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, obj in snap.items():
        (out_dir / name).write_text(json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=False) + "\n", encoding="utf-8")
    (out_dir / "SOURCES.md").write_text(sources_markdown(snap), encoding="utf-8")


# ------------------------------------------------------------------ verify

def verify(snapshot: dict, run=sparql, nim_snapshot: dict | None = None) -> dict:
    """Live metadata against the snapshot. Returns {status: unchanged|changed, findings: [...]}."""
    findings = []

    def rows(query, what):
        got = run(query)
        if not got:
            raise SourceError(f"CELLAR returned no rows for {what}; the snapshot has some, so nothing can be concluded")
        return got
    live_cons: dict = {}
    for r in rows(Q_CONSOLIDATED, "the consolidated versions"):
        if r.get("base") in PINNED and r.get("celex", "").startswith("0"):
            live_cons.setdefault(r["base"], set()).add((r["celex"], r.get("date")))
    known = {b: {v["celex"] for v in vs} for b, vs in snapshot["consolidated_versions"].items()}
    for base, versions in live_cons.items():
        for celex, date in sorted(versions):
            if celex not in known.get(base, set()):
                findings.append({"kind": "new consolidated version", "act": base, "celex": celex, "date": date})
        if PINNED.get(base) and PINNED[base] not in {c for c, _ in versions}:
            findings.append({"kind": "pinned version no longer listed", "act": base, "celex": PINNED[base]})
    for base in PINNED:
        if base not in live_cons:
            findings.append({"kind": "no consolidated versions returned", "act": base})
    known_rel = {(x["base"], x["rel"], x["celex"]) for x in snapshot.get("related_since_2024", [])}
    related = related_since_2024(run)
    if not related and known_rel:
        raise SourceError("CELLAR returned no amendments, corrigenda or consolidations; the snapshot has some")
    for x in related:
        if (x["base"], x["rel"], x["celex"]) in known_rel:
            continue
        if x["rel"] == "corrects":
            kind = "new corrigendum to the English text" if "ENG" in x.get("languages", []) \
                else "new corrigendum (other language versions only)"
        elif x["rel"] == "amends":
            kind = "new amending act"
        else:
            kind = "new consolidated version"
        findings.append({"kind": kind, **x})
    for r in rows(acts_query(), "the acts"):
        c = r.get("celex")
        if c in snapshot["acts"] and "inforce" in r:
            live = r["inforce"] in ("1", "true")
            if snapshot["acts"][c].get("in_force") is not None and live != snapshot["acts"][c]["in_force"]:
                findings.append({"kind": "in-force flag changed", "act": c, "in_force": live})
    if nim_snapshot is not None:
        known_m = {m["celex"] for m in nim_snapshot.get("measures", [])}
        new = sorted({r["c"] for r in rows(Q_NIM, "the national measures")
                      if r.get("dir") in NIM_DIRECTIVES and r.get("c") and r["c"] not in known_m})
        if new:
            findings.append({"kind": "new national measures notified", "count": len(new), "celex": new[:20]})
    dedup, seen = [], set()
    for f in findings:
        key = json.dumps(f, sort_keys=True)
        if key not in seen:
            seen.add(key)
            dedup.append(f)
    return {"status": "changed" if dedup else "unchanged", "findings": dedup}


def main(argv: list[str] | None = None) -> int:
    """Stand-alone entry: `python3 csrd_scope_cellar.py refresh|verify` (the CLI wraps these)."""
    argv = sys.argv[1:] if argv is None else argv
    here = Path(__file__).resolve().parent / "data"
    if argv[:1] == ["refresh"]:
        try:
            snap = build_snapshot()
        except SourceError as e:
            print(f"refresh failed, nothing written: {e}", file=sys.stderr)
            return 2
        write_snapshot(here, snap)
        print(f"wrote {', '.join(snap)} and SOURCES.md to {here}")
        return 0
    if argv[:1] == ["verify"]:
        snap = json.loads((here / "legal_basis.json").read_text(encoding="utf-8"))
        try:
            res = verify(snap)
        except SourceError as e:
            print(f"could not check: {e}", file=sys.stderr)
            return 2
        print(json.dumps(res, indent=1))
        return 1 if res["status"] == "changed" else 0
    print("usage: csrd_scope_cellar.py refresh|verify", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
