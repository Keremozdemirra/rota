# Data sources

Snapshot retrieved 2026-09-24 by `eudr-scope-mcp refresh` (version 0.1.0).
Regenerate with `python -m eudr_scope_mcp refresh --out data`.

## Legal acts

| CELEX | Act | Used for | Status |
| --- | --- | --- | --- |
| 02023R1115-20251226 | Consolidated text of Regulation (EU) 2023/1115 (02023R1115 — EN — 26.12.2025 — 002.001) | Annex I, Articles 1, 2, 37, 38 | verified |
| 32023R1115 | Regulation (EU) 2023/1115, original text (OJ of 2023-06-09) | Article 38 history | read |
| 32024R3234 | Regulation (EU) 2024/3234 of the European Parliament and of the Council of 19 December 2024 amending Regulation (EU) 2023/1115 as regards provisions relating to the date of application (in force 2024-12-26) | in the consolidated text; Article 38 history | read |
| 32025R2650 | Regulation (EU) 2025/2650 of the European Parliament and of the Council of 19 December 2025 amending Regulation (EU) 2023/1115 as regards certain obligations of operators and traders (in force 2025-12-26) | in the consolidated text; Article 38 history | read |
| 32026R2102 | Commission Delegated Regulation (EU) 2026/2102 of 13 July 2026 amending Regulation (EU) 2023/1115 of the European Parliament and of the Council as regards the list of relevant commodities and relevant products (in force 2026-09-18) | applied to Annex I (not yet consolidated) | read |
| 32025R1093 | Commission Implementing Regulation (EU) 2025/1093 of 22 May 2025 laying down rules for the application of Regulation (EU) 2023/1115 of the European Parliament and of the Council as regards a list of countries that present a low or high risk of producing relevant commodities for which the relevant products do not comply with Article 3, point (a) (in force 2025-05-26) | country classification | verified |

Every date in `application_dates.json` is read from the article text and checked against CELLAR's
`resource_legal_date_entry-into-force` metadata for the act.

## Raw files

| Role | CELEX | URL | SHA-256 | Bytes |
| --- | --- | --- | --- | --- |
| consolidated text | 02023R1115-20251226 | https://publications.europa.eu/resource/cellar/e9980b30-01b5-11f1-825d-01aa75ed71a1.0001.03/DOC_1 | `a00f759dfaf6daeff3b831e14571bd89828360e29cd9c7e6e1b6d3d1af0ddbe6` | 267071 |
| original act (Article 38 history) | 32023R1115 | https://publications.europa.eu/resource/cellar/d80446fe-0660-11ee-b12e-01aa75ed71a1.0006.03/DOC_1 | `fc30a30a1b6701800ad8abeb63e1d606769a4128bc97ddb2e481ee4bf6057259` | 387997 |
| amending act | 32024R3234 | https://publications.europa.eu/resource/cellar/ea03e94f-c0d0-11ef-91ed-01aa75ed71a1.0006.03/DOC_1 | `16fbf4deed26a264fd89daac18c657f01fe9ead90be23de777ba486885732a63` | 25934 |
| amending act | 32025R2650 | https://publications.europa.eu/resource/cellar/ce5c480c-dfa4-11f0-8439-01aa75ed71a1.0006.03/DOC_1 | `f9a2440227c4231d359e2816d9fc17bf59643dd1f3c7fa6ff31320180037ae27` | 182765 |
| amending act | 32026R2102 | https://publications.europa.eu/resource/cellar/42f36e5a-b230-11f1-b9e5-01aa75ed71a1.0006.03/DOC_1 | `f54c919c98c0f437efe0b4f5510c0a59c17a215a3bafe0e0af3e0a92a0167f4e` | 130940 |
| country list | 32025R1093 | https://publications.europa.eu/resource/cellar/c46f6f04-376f-11f0-8a44-01aa75ed71a1.0006.03/DOC_1 | `fcde4a646865e52000956d4b43eb3a58a2bee0e0d3540f180720231782c2e5af` | 16576 |

Country names are matched to ISO 3166-1 codes through the EU authority table http://publications.europa.eu/resource/authority/country
(version 20260617-0), queried at https://publications.europa.eu/webapi/rdf/sparql.

## Row counts

- annex i entries total: 139
- annex i entries in force on retrieval: 71
- annex i entries later: 18
- annex i entries removed: 50
- table notes: 5
- low risk countries: 140
- high risk countries: 4
- authority table countries: 251

## Corrigenda and proposals

- 32023R1115R(01) (2024-10-01) corrects 32023R1115: no English version, so the English text is unaffected
- 32023R1115R(02) (2025-02-28) corrects 32023R1115: no English version, so the English text is unaffected
- 32023R1115R(03) (2025-03-28) corrects 32023R1115: no English version, so the English text is unaffected
- 32023R1115R(04) (2025-12-22) corrects 32023R1115: no English version, so the English text is unaffected
- 32025R2650R(01) (2026-02-12) corrects 32025R2650: no English version, so the English text is unaffected
- 32025R2650R(02) (2026-05-18) corrects 32025R2650: no English version, so the English text is unaffected
- 32023R1115R(05) (2026-07-02) corrects 32023R1115: no English version, so the English text is unaffected
- 52024PC0452 (2024-10-02): adopted as 32024R3234: Proposal for a REGULATION OF THE EUROPEAN PARLIAMENT AND OF THE COUNCIL amending Regulation (EU) 2023/1115 as regards provisions relating to the date of application
- 52025PC0652 (2025-10-21): adopted as 32025R2650: Proposal for a REGULATION OF THE EUROPEAN PARLIAMENT AND OF THE COUNCIL amending Regulation (EU) 2023/1115 as regards certain obligations of operators and traders
- 52026PC0661 (2026-09-10): pending (no adopting act in CELLAR), not law and not applied: Proposal for a COUNCIL REGULATION amending Regulations (EU) No 1380/2013, (EU) No 1308/2013, (EU) 2023/1115 and (EU) 2024/1348 of the European Parliament and of the Council, and Council Regulation (EU) 2023/2720 as regards adaptation of certain requirements and reduction of administrative burden in the Union outermost regions

## Choices made by this tool

- Annex I is the consolidated text plus the amending acts listed as applied above, applied by
  `eudr_scope_mcp/annex.py`. The result is derived; it is not an official consolidated version.
- Names written 'Name (qualifier)' in the Annex are matched with the qualifier moved to the front: Iran (Islamic Republic of) = IRN, Micronesia (Federated States of) = FSM, Netherlands (Kingdom of the) = NLD.
- 'Solomon Island' is read as SLB (the Annex spells the name that way; no other country matches).
- Entries of the authority table recorded as part of another country (skos:broader) are reported
  as not determined when the Annex does not name them.

## Licence and attribution

EUR-Lex legal notice, https://eur-lex.europa.eu/content/legal-notice/legal-notice.html. From this sandbox
eur-lex.europa.eu answered HTTP 202 with an empty body and web.archive.org reset the connection on
2026-09-24, so the sentences below are quoted from the archived copy of 2026-09-22
(https://web.archive.org/web/20260922160312/https://eur-lex.europa.eu/content/legal-notice/legal-notice.html)
as given in this project's build notes, not re-read by this tool:

- 'Unless otherwise specified, you can re-use the legal documents published in EUR-Lex for commercial or
  non-commercial purposes.'
- Creative Commons Attribution 4.0 covers 'the editorial content of this website, the summaries of EU
  legislation and the consolidated texts'.

Commission Decision 2011/833/EU on the reuse of Commission documents (http://data.europa.eu/eli/dec/2011/833/oj),
read from CELLAR on 2026-09-24: Article 4, 'All documents shall be available for reuse: (a) for commercial or
non-commercial purposes under the conditions laid down in Article 6'; Article 6(2) conditions may include
'(a) the obligation for the reuser to acknowledge the source of the documents; (b) the obligation not to
distort the original meaning or message of the documents'.

| Data | Basis |
| --- | --- |
| Consolidated text 02023R1115-20251226 (Annex I base, Articles 1, 2, 37, 38) | CC BY 4.0 (EUR-Lex legal notice, consolidated texts); changes indicated: Annex I is derived |
| Regulations (EU) 2023/1115, 2024/3234, 2025/2650 as published in the OJ (European Parliament and Council) | EUR-Lex legal notice, re-use of legal documents published in EUR-Lex |
| Commission acts as published in the OJ (32026R2102, 32025R1093) | EUR-Lex legal notice, plus Decision 2011/833/EU Articles 4 and 6(2) |
| CELLAR metadata (SPARQL) and the 'Countries and territories' authority table | Commission reuse notice, Decision 2011/833/EU, per https://data.europa.eu/data/datasets/sparql-cellar-of-the-publications-office and https://data.europa.eu/data/datasets/country |

Attribution lines carried by the answers:

- scope and commodity answers: Source: consolidated text of Regulation (EU) 2023/1115 (CC BY 4.0) and the amending acts as published in the Official Journal, from EUR-Lex/CELLAR, Publications Office of the European Union, retrieved 2026-09-24; (c) European Union. Changes: Annex I derived by eudr-scope-mcp, amending acts applied to the consolidated text.
- date answers: Source: consolidated text of Regulation (EU) 2023/1115 (CC BY 4.0) and the amending acts as published in the Official Journal, from EUR-Lex/CELLAR, Publications Office of the European Union, retrieved 2026-09-24; (c) European Union. Dates read from the article texts by eudr-scope-mcp.
- country answers: Source: Commission Implementing Regulation (EU) 2025/1093 as published in the Official Journal, from EUR-Lex/CELLAR, Publications Office of the European Union, retrieved 2026-09-24; (c) European Union; reuse under the EUR-Lex legal notice and Commission Decision 2011/833/EU. ISO codes from the EU 'Countries and territories' authority table (version 20260617-0), matched by eudr-scope-mcp.

Only the texts published in the Official Journal of the European Union are authentic. The consolidated
text says of itself: 'This text is meant purely as a documentation tool and has no legal effect.'
