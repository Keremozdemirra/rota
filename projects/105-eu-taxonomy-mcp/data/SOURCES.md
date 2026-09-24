# Sources of the data in this directory

<!-- written by eu-taxonomy-mcp refresh -->

Two data files, each rebuilt by a `refresh` command. The terms for each are quoted with the date read.

## taxonomy.json: EU Taxonomy Navigator

<!-- begin taxonomy.json -->
| | |
|---|---|
| Source | EU Taxonomy Navigator, European Commission (DG FISMA): https://ec.europa.eu/sustainable-finance-taxonomy/ |
| Backend | https://webgate.ec.europa.eu/sft/api/v1/en: the undocumented JSON API behind the Navigator web app. No API documentation, terms of use or service level were found (checked 2026-09-24); it may change or stop without notice. |
| Licence | CC BY 4.0, per the European Commission legal notice that the Navigator's footer links to: https://commission.europa.eu/legal-notice_en |
| Retrieved | 2026-09-24T18:31:44Z |
| Requests | 3 (bulk; at least 1 s apart), 2,612,100 bytes, 14.5 s |
| Client | `User-Agent: eu-taxonomy-mcp/0.1.0 (+https://github.com/Keremozdemirra/eu-taxonomy-mcp)` |

Licence terms, quoted from https://commission.europa.eu/legal-notice_en (read 2026-09-24): "Unless otherwise indicated (e.g. in individual copyright notices), content owned by the EU on this website is licensed under the Creative Commons Attribution 4.0 International (CC BY 4.0) licence. This means that reuse is allowed, provided appropriate credit is given and changes are indicated."

Attribution line carried by every answer:

    Source: European Commission, EU Taxonomy Navigator (https://ec.europa.eu/sustainable-finance-taxonomy/), CC BY 4.0, retrieved 2026-09-24

Raw responses:

| Request | Bytes | SHA-256 of the body |
|---|---:|---|
| GET /sectors | 745 | `fc7b3c9d8df9ad071dfd03da78910c8a5ae7809c77ba482d93b5be1db7bcab8a` |
| GET /activities | 212,004 | `90baa0d0cbe9fffb98b7f1ff899756fa651e2fa5b80bfe5351d48830c75d1c2e` |
| GET /activities/matches/all | 2,399,351 | `017da8b7fc72cada3a27c9c272e9c7c7f9eee77a62f958a88f285cf6cb13a800` |

| File | Bytes | SHA-256 |
|---|---:|---|
| taxonomy.json | 2,239,085 | `f813701e7f42eddaa17c28549395b2e8cbeb44ebeaa5367e4b2a03b454a2ec9d` |

| Rows | Count |
|---|---:|
| sectors | 16 |
| activities | 151 |
| criteria sets (one activity, one objective with substantial-contribution criteria) | 242 |
| DNSH entries | 1210 |
| environmental objectives | 6 |
| activities without NACE codes | 8 |
| activities without criteria | 0 |

What the snapshot changes:

- Keeps only these fields: activities id, name, sector, description, naceCodes; criteria sets id, objective, activityContributionType, contributionDescription, activityDescription, criteria, dnshCriterias; sectors and objectives as served. Nothing else from the backend is stored.
- Nests each activity's criteria sets under the activity and refers to objectives by id.
- Strips surrounding whitespace from NACE codes (the source serves codes such as ' F42.22'). Other code forms ('A2', 'M71.1.2', 'Q84') are stored as served and read against NACE Rev. 2 only when answering.
- Sorts sectors and activities by id, criteria sets and DNSH entries by objective order, and writes keys in sorted order, so the same data gives the same bytes.
- Changes no text: names, descriptions and criteria are the HTML strings as served.

Rebuild: `python3 eu_taxonomy_mcp.py refresh` in a source checkout (rewrites data/), or `eu-taxonomy-mcp refresh --out DIR` anywhere else, then `--snapshot DIR/taxonomy.json`. A result with no criteria sets, or with fewer than half the activities or criteria sets of the previous snapshot, is refused.
<!-- end taxonomy.json -->

## nace.json: NACE Rev. 2 and NACE Rev. 2.1

<!-- begin nace.json -->
| | |
|---|---|
| NACE Rev. 2 | Annex I to Regulation (EC) No 1893/2006, CELEX 32006R1893, http://data.europa.eu/eli/reg/2006/1893/oj (English text from Cellar, https://publications.europa.eu/resource/celex/32006R1893) |
| NACE Rev. 2.1 | Annex to Commission Delegated Regulation (EU) 2023/137, CELEX 32023R0137, http://data.europa.eu/eli/reg_del/2023/137/oj (English text from Cellar, https://publications.europa.eu/resource/celex/32023R0137) |
| Terms | Official Journal text, re-used under Commission Decision 2011/833/EU; see "Texts of EU law" below. Not labelled CC BY. |
| Retrieved | 2026-09-24T18:31:25Z |
| Requests | 2 (at least 1 s apart), 1,760,621 bytes, 4.4 s |

Raw responses:

| Request | Bytes | SHA-256 of the body |
|---|---:|---|
| GET CELEX 32006R1893 | 1,024,249 | `3c24afdb65e7c453026031296bb8e2cb1bf8c4a57d4e794f11e06d6dc094f83e` |
| GET CELEX 32023R0137 | 736,372 | `94da84c3995261681e8505b6ffd60f1b2fdbbc9961e6986703dffe4d597b5e34` |

| File | Bytes | SHA-256 |
|---|---:|---|
| nace.json | 124,254 | `642a19add78c8149049337480a42baadbc8962597a95f1f63482e8d6d91a8fbb` |

| Revision | Sections | Divisions | Groups | Classes |
|---|---:|---:|---:|---:|
| NACE Rev. 2 | 21 | 88 | 272 | 615 |
| NACE Rev. 2.1 | 22 | 87 | 287 | 651 |

What the file changes: nothing in the titles. It keeps the section letters and titles, which section each division belongs to, and the title of every division, group and class, as the annex tables give them; the ISIC Rev. 4 column of Regulation (EC) No 1893/2006 is left out.

Rebuild: `python3 eu_taxonomy_mcp.py refresh --nace` (two requests to Cellar).
<!-- end nace.json -->

## Texts of EU law

The tool quotes titles and passages of EU acts (in `sources()` and the notes) and the NACE titles (`nace.json`) from the Official Journal, and one passage from a EUR-Lex consolidated text. Every answer that carries them says so in `attribution_eu_law` or `attribution_consolidated_text`.

EUR-Lex legal notice, https://eur-lex.europa.eu/content/legal-notice/legal-notice.html, read 2026-09-24:

> The Commission’s document reuse policy is based on Decision 2011/833/EU. Unless otherwise specified, you can re-use the legal documents published in EUR-Lex for commercial or non-commercial purposes.

> The copyright for the editorial content of this website, the summaries of EU legislation and the consolidated texts, which is owned by the EU, is licensed under the Creative Commons Attribution 4.0 International licence. This means that you can re-use the content provided you acknowledge the source and indicate any changes you have made.

> Only European Union documents published in the Official Journal of the European Union are deemed authentic.

Commission Decision 2011/833/EU (OJ L 330, 14.12.2011, p. 39, CELEX 32011D0833), read in Cellar on 2026-09-24:

> Article 4: All documents shall be available for reuse: (a) for commercial or non-commercial purposes under the conditions laid down in Article 6;

> Article 6(2): Those conditions, which shall not unnecessarily restrict possibilities for reuse, may include the following: (a) the obligation for the reuser to acknowledge the source of the documents; (b) the obligation not to distort the original meaning or message of the documents; (c) the non-liability of the Commission for any consequence stemming from the reuse.

So: Official Journal texts are re-used under Decision 2011/833/EU, with the source acknowledged and the meaning not distorted; they are not labelled CC BY 4.0. The passage taken from the consolidated text of Delegated Regulation (EU) 2021/2139 (CELEX 02021R2139-20260101) is CC BY 4.0. The Navigator's own content is CC BY 4.0 under the Commission legal notice quoted above.

Acts read (English text from Cellar; titles, dates and ELI from the Publications Office SPARQL endpoint), 2026-09-24:

| Act | CELEX | ELI |
|---|---|---|
| Regulation (EU) 2020/852 | 32020R0852 | http://data.europa.eu/eli/reg/2020/852/oj |
| Commission Delegated Regulation (EU) 2021/2139 | 32021R2139 | http://data.europa.eu/eli/reg_del/2021/2139/oj |
| Commission Delegated Regulation (EU) 2021/2178 | 32021R2178 | http://data.europa.eu/eli/reg_del/2021/2178/oj |
| Commission Delegated Regulation (EU) 2022/1214 | 32022R1214 | http://data.europa.eu/eli/reg_del/2022/1214/oj |
| Commission Delegated Regulation (EU) 2023/2485 | 32023R2485 | http://data.europa.eu/eli/reg_del/2023/2485/oj |
| Commission Delegated Regulation (EU) 2023/2486 | 32023R2486 | http://data.europa.eu/eli/reg_del/2023/2486/oj |
| Commission Delegated Regulation (EU) 2024/3215 | 32024R3215 | http://data.europa.eu/eli/reg_del/2024/3215/oj |
| Commission Delegated Regulation (EU) 2026/73 | 32026R0073 | http://data.europa.eu/eli/reg_del/2026/73/oj |
| Regulation (EC) No 1893/2006 (NACE Rev. 2) | 32006R1893 | http://data.europa.eu/eli/reg/2006/1893/oj |
| Commission Delegated Regulation (EU) 2023/137 (NACE Rev. 2.1) | 32023R0137 | http://data.europa.eu/eli/reg_del/2023/137/oj |
