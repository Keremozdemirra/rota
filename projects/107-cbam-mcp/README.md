# cbam-mcp

<!-- mcp-name: io.github.Keremozdemirra/cbam-mcp -->

**EU CBAM scope, default values and CN descriptions for a CN code, from dated copies of the official sources, as an MCP server and a command line. Every answer names the legally binding act, the data version, and says the data is not legally binding.**

Importers, customs brokers and sustainability teams ask three questions about the EU Carbon Border
Adjustment Mechanism (CBAM): is this CN code in scope, in which goods category, for which greenhouse
gases; what default value applies to it from a given country of origin; what exactly does the code
describe. The answers sit in three places: the consolidated CBAM Regulation on EUR-Lex, an Excel of
default values on the Commission's site with 122 tables (121 countries and "Other countries and
territories"), and the Combined Nomenclature in the
Publications Office's linked-data store. `cbam-mcp` bundles dated copies of the three, answers from
them offline, and puts the legal status next to every number.

## Example

Real output of `cbam-mcp` 0.1.0 on 2026-09-24, from the bundled data retrieved the same day.

```
$ cbam-mcp compare 7601 10 00 India Türkiye
7601 10 00: default values in tCO2e per tonne of good
  table line 7601 Unwrought aluminium (Aluminium)
    country                              total  direct indirect  route  values from
    India                                1.870   1.870      N/A  K      India
    Türkiye                              1.700   1.700      N/A  K      Türkiye
    Other countries and territories      2.203   2.203
    Annex IV (origin unknown)            3.198
  Note              Values as listed in the table. For the calculation of the number of CBAM
                    certificates, the introductory part of Annex I (as replaced by Implementing
                    Regulation (EU) 2026/1740) says the 'total emissions' value is selected and
                    increased; this tool does not apply or state that increase.
  Legally binding   no. Binding text: Annex I to Commission Implementing Regulation (EU) 2025/2621,
                    as replaced by Annex I to Commission Implementing Regulation (EU) 2026/1740 (OJ
                    L, 2026/1740, 31.7.2026)
  Commission says   "An Excel file is made available for information purposes only, while the
                    legally binding values are set out in Commission Implementing Regulation (EU)
                    2025/2621."
  Data              Commission Excel 'Default values definitive period', version 2 of 2026-08-06
                    (Default values based on Annex I and II to Implementing Regulation (EU)
                    2026/1740 adopted on 20 July 2026), file 'DV correcting act_final
                    update_06.08.xlsx', retrieved 2026-09-24
  Checked           On 2026-09-24 cbam-mcp compared this file with
                    http://publications.europa.eu/resource/celex/32026R1740: 12540 of 12540 country
                    lines and 283 of 283 Annex IV lines identical.
  Warning           7601 10 00 is not a CN 2026 code; the table line shown is the one whose code it
                    starts with
  Source: European Commission, DG TAXUD, default values Excel version 2, CC BY 4.0, retrieved 2026-09-24; decimal commas converted to numbers (derived)
```

The warning is a finding, not noise: CN 2025 and CN 2026 split 7601 10 into 7601 10 10 (slabs) and
7601 10 90; the default-value table gives one line for all of heading 7601.

An "ex" line of Annex I is never reported as fully in scope:

```
$ cbam-mcp scope 2507 00 80
2507 00 80: partially in scope
  Annex I line      ex 2507 00 80 – Other kaolinic clays except non-calcined kaolinic clays
  Goods category    Cement
  Greenhouse gases  Carbon dioxide
  Why               Annex I lists this as 'ex 2507 00 80 – Other kaolinic clays except non-calcined
                    kaolinic clays'. 'ex' means only the goods that description covers are in scope,
                    not every good under 2507 00 80.
  Annex II          not listed in Annex II. Article 7(1): "Embedded emissions in goods shall be
                    calculated pursuant to the methods set out in Annex IV. For goods listed in
                    Annex II only direct emissions shall be calculated and taken into account."
  CN 2026           2507 00 80 Other kaolinic clays. Kaolinic clays (other than kaolin)
  De minimis        Annex VII, point 1: "The single mass-based threshold referred to in Article 2a
                    shall be set at 50 tonnes of net mass." The threshold counts the net mass of all
                    CBAM goods an importer imports in a calendar year, not per CN code; this tool
                    cannot tell whether an importer is under it.
  Legally binding   no. Binding text: Annex I to Regulation (EU) 2023/956 as published in the
                    Official Journal (OJ L 130, 16.5.2023, p. 52) and amended by Regulation (EU)
                    2025/2083 (OJ L, 2025/2083, 17.10.2025)
  Data              consolidated text 02023R0956-20251020 of Regulation (EU) 2023/956 (02023R0956 —
                    EN — 20.10.2025 — 001.001), retrieved 2026-09-24 from CELLAR
  Source: EUR-Lex/CELLAR, consolidated text 02023R0956-20251020 of Regulation (EU) 2023/956, © European Union, retrieved 2026-09-24; table derived by cbam-mcp
```

```
$ cbam-mcp describe 7308 20 10
7308 20 10 (CN 2026): Tubular wind turbine steel towers and tower-sections
  Self-explanatory  Tubular wind turbine steel towers and tower-sections
  Hierarchy         XV SECTION XV - BASE METALS AND ARTICLES OF BASE METAL > 73 CHAPTER 73 -
                    ARTICLES OF IRON OR STEEL > 7308 Structures (excluding prefabricated buildings
                    of heading 9406) and parts of structures (for example, bridges and bridge-
                    sections, lock-gates, towers, lattice masts, roofs, roofing frameworks, doors
                    and windows and their frames and thresholds for doors, shutters, balustrades,
                    pillars and columns), of iron or steel; plates, rods, angles, shapes, sections,
                    tubes and the like, prepared for use in structures, of iron or steel > 7308 20
                    Towers and lattice masts
  CN 2025           no such code
  Legally binding   no. Binding text: Annex I to Council Regulation (EEC) No 2658/87 as amended by
                    Commission Implementing Regulation (EU) 2025/1926 (Combined Nomenclature 2026),
                    as published in the Official Journal
  Data              CN 2026 (EU Vocabularies, http://data.europa.eu/xsp/cn2026/cn2026), bundled
                    subset, retrieved 2026-09-24
  Source: Publications Office of the European Union, EU Vocabularies, Combined Nomenclature 2026, European Commission reuse notice, retrieved 2026-09-24
```

## Install

Standard library only, Python 3.9 or newer, no dependencies. The data ships inside the package, so
answering needs no network.

As an MCP server in Claude Code:

```
claude mcp add cbam-mcp -- uvx cbam-mcp
```

In any other MCP client, the server is the command `uvx cbam-mcp` (or `pipx run cbam-mcp`) over stdio:

```json
{"mcpServers": {"cbam-mcp": {"command": "uvx", "args": ["cbam-mcp"]}}}
```

On the command line:

```
uvx cbam-mcp scope 7208 51 20
pipx run cbam-mcp value 7601 10 00 India
```

The PyPI package is published by this repository's release workflow; until the first release, install
from a checkout with `pip install .`, or run `python3 -m cbam_mcp` in it.

## Tools and commands

| MCP tool | Command line | Answers |
| --- | --- | --- |
| `cbam_scope(cn_code, limit?)` | `cbam-mcp scope CODE` | `in_scope`, `partially_in_scope` or `not_in_scope`, with the Annex I line that decides it (goods category, greenhouse gases, exceptions, `ex` flag), whether Annex II limits the goods to direct emissions, the de minimis texts where they apply, and the CN 2026 description. For a code shorter than 8 digits, the CN 2026 sub-codes in and out of scope. |
| `default_value(cn_code, country)` | `cbam-mcp value CODE COUNTRY` | Direct, indirect and total default values in tCO2e per tonne of good as listed, production route and its meaning, the "Other countries and territories" values where Annex I says to use them, and the Annex IV value. |
| `compare_origins(cn_code, countries)` | `cbam-mcp compare CODE COUNTRY...` | The same for up to 30 countries side by side. |
| `cn_describe(cn_code, year?)` | `cbam-mcp describe CODE [--year 2025]` | CN 2026 or CN 2025 label, self-explanatory text, hierarchy, sub-codes, and whether the other year differs. |
| `sources()` | `cbam-mcp sources` | URL, version, retrieval date, SHA-256, row counts, licence and legal status of every dataset, the Official Journal check, later acts found. |
| | `cbam-mcp refresh [--check-oj]` | Rebuilds the data from the sources (below). |

CN codes are read as `7208 51 20`, `72085120`, `7208.51.20`, with or without `ex`, at 2, 4, 6, 8 or 10
(TARIC) digits. Countries are read as the table names (`Türkiye`), common names (`Turkey`) or ISO
3166-1 alpha-2 codes (`TR`); the ISO codes are this tool's input convenience, the tables name
countries only. `--json` prints the structure the MCP tool returns. Exit codes: 0 answered, 2 the
question or the data could not be read.

Every answer carries `legally_binding` (always `false`), `legally_binding_source` (the act that is
binding), `data_version` and an attribution line.

## What the answers rest on

Each rule the answers state, where it was read, and when.

| Rule used in answers | Source | Checked |
| --- | --- | --- |
| The goods, CN codes, "ex" lines, exceptions and greenhouse gases of Annex I; the goods of Annex II ("only direct emissions", Article 7(1)) | Regulation (EU) 2023/956 as amended by Regulation (EU) 2025/2083, consolidated text 02023R0956-20251020 (parsed at each refresh) | 2026-09-24 |
| De minimis: Article 2a(1); "The single mass-based threshold referred to in Article 2a shall be set at 50 tonnes of net mass." (Annex VII, point 1); "This Article shall not apply to imports of electricity or hydrogen." (Article 2a(4)) | same consolidated text (parsed at each refresh) | 2026-09-24 |
| Goods originating in Iceland, Liechtenstein, Norway, Switzerland, Büsingen, Heligoland, Livigno, Ceuta and Melilla are outside the Regulation (Article 2(4), Annex III point 1); it applies to goods "originating in a third country" (Article 2(1)) | same consolidated text (parsed at each refresh) | 2026-09-24 |
| A country not listed, a missing line or a field showing "–": use the table "Other countries and territories" | Annex I (introductory part) to Implementing Regulation (EU) 2025/2621 as replaced by Implementing Regulation (EU) 2026/1740 | 2026-09-24 |
| Production routes (A) to (L), and "If no production route is indicated for a CN code, the CBAM benchmark (BM) is independent of the production route." | same | 2026-09-24 |
| "The default values for direct emissions and indirect emissions in Annex I have only been provided for information." | Recital 10 of Implementing Regulation (EU) 2026/1740 | 2026-09-24 |
| Annex IV is for "a precursor" whose "country of production cannot be identified" | Article 1(5) of Implementing Regulation (EU) 2025/2621 | 2026-09-24 |
| Default values for electricity are in Annex III, emission factors for indirect emissions in Annex II; the regulation says their data "is subject to a Creative Commons Non-Commercial Share-Alike 4.0 CC BY NC SA licence" | Article 1(3) and (4), Annexes II and III of Implementing Regulation (EU) 2025/2621 | 2026-09-24 |
| "An Excel file is made available for information purposes only, while the legally binding values are set out in Commission Implementing Regulation (EU) 2025/2621." | https://taxation-customs.ec.europa.eu/carbon-border-adjustment-mechanism/cbam-legislation-and-guidance_en | 2026-09-24 |
| CN 2026 is set by Commission Implementing Regulation (EU) 2025/1926, CN 2025 by (EU) 2024/2522 | CELLAR metadata; data.europa.eu datasets combined-nomenclature-2026 and -2025 | 2026-09-24 |
| 27 EU Member States (their origins get no default value) | https://european-union.europa.eu/principles-countries-history/eu-countries_en | 2026-09-24 |

Not stated on purpose: the mark-up percentages. They are in the introductory part of Annex I as
replaced by Implementing Regulation (EU) 2026/1740, but on 2026-09-24 no consolidated text of
Implementing Regulation (EU) 2025/2621 including them existed (the Commission's page says one "will
be available soon"), and this tool only states such rules from consolidated text. Answers say that the
listed value is increased for the certificate calculation and where; they do not compute it.

Later acts, checked in CELLAR on 2026-09-24 (`data/later_acts.json`, repeated at every refresh): no
act amending or correcting Implementing Regulation (EU) 2025/2621 is dated after Implementing
Regulation (EU) 2026/1740 (20 July 2026), and none amending Regulation (EU) 2023/956 after the
consolidation date. CELLAR lists corrigenda to both acts (2023/956 R(01) to R(04), 2025/2621 R(01)),
none with an English version. The Commission's CBAM page listed Implementing Regulation (EU) 2026/1740
as its latest update ("UPDATE JULY 2026") and the same Excel file on that day.

Choices of this tool, not rules: the status names (`partially_in_scope` covers both an "ex" line and a
heading whose sub-codes differ); for a code shorter than 8 digits the status is derived from its CN
2026 sub-codes; a country name that is close to a table name (similarity 0.75 or more) is an error
with a suggestion, while an unknown name gets the "Other countries and territories" values with a
warning; refresh refuses an Annex I of fewer than 20 lines in 5 categories or a CN answer of fewer
than 500 concepts, as a sign of a truncated or changed source.

## Data, licences and attribution

The bundled files are in `cbam_mcp/data/`; `cbam_mcp/data/SOURCES.md` lists for each the URL,
licence, retrieval date, SHA-256 of the raw file and row counts.

| File | Source | Licence and terms |
| --- | --- | --- |
| `annex_i.json` | Consolidated text of Regulation (EU) 2023/956, CELEX 02023R0956-20251020, from CELLAR: `http://publications.europa.eu/resource/celex/02023R0956-20251020` (XHTML by content negotiation) | EU legal act. The Publications Office's copyright notice (https://op.europa.eu/en/web/about-us/legal-notices/publications-office-of-the-european-union-copyright) says: "If you need further information regarding copyright issues, including the conditions under which the content of the CELLAR, and of the EU Vocabularies may be re-used, please contact us at op-copyright@publications.europa.eu". Only codes, descriptions, gases and quoted sentences are kept. Attribution: © European Union, https://eur-lex.europa.eu |
| `default_values.json` | European Commission, DG TAXUD, "Default values definitive period (Excel format)", version 2 of 2026-08-06, https://taxation-customs.ec.europa.eu/document/download/1c05d211-80cb-4aaa-8ef0-e08005a95d7e_en | CC BY 4.0, https://commission.europa.eu/legal-notice_en: "content owned by the EU on this website is licensed under the Creative Commons Attribution 4.0 International (CC BY 4.0) licence. This means that reuse is allowed, provided appropriate credit is given and changes are indicated." Changes: decimal commas converted to numbers in answers. |
| `cn_2026.json`, `cn_2025.json` | Combined Nomenclature 2026 and 2025, EU Vocabularies, via the CELLAR SPARQL endpoint https://publications.europa.eu/webapi/rdf/sparql; chapters 25, 28, 31, 72, 73 and 76 in full, headings 2601 and 2716 with their chapters | European Commission reuse notice (Commission Decision 2011/833/EU, http://data.europa.eu/eli/dec/2011/833/oj), the licence data.europa.eu gives both distributions of the datasets combined-nomenclature-2026 and -2025. Attribution: Publications Office of the European Union. Changes: English labels only; leading dashes turned into an indent number. |

On 2026-09-24 every value of the Excel was compared with the Official Journal text of Implementing
Regulation (EU) 2026/1740 (XHTML from CELLAR): 12,540 of 12,540 country lines in 122 tables and 283 of
283 Annex IV lines were identical, and the four rules quoted above from that act were found in it.

EUR-Lex web pages answered HTTP 202 with an empty body to scripted requests from here on 2026-09-24;
the same texts are read from CELLAR instead.

## Refreshing the data

```
cbam-mcp refresh                      # all sources into cbam_mcp/data/ (in a checkout)
cbam-mcp refresh --check-oj           # also compare every value with the Official Journal text (16 MB)
cbam-mcp refresh --data-dir DIR       # elsewhere; then run with CBAM_MCP_DATA_DIR=DIR
```

Standard library only (urllib, zipfile, xml.etree). Each source is fetched, parsed and checked on its
own; one that fails keeps its previous file, and files are replaced atomically. The newest
consolidated text is looked up in CELLAR first, with 02023R0956-20251020 as the fallback. If the
Commission publishes a new Excel under another link, pass it with `--excel-url`; `SOURCES.md` records
which default-value downloads the Commission's page listed. Exit codes: 0 refreshed, 1 the Official
Journal check found a difference, 2 a source could not be refreshed.

## What it reads, what it sends

- **Answering** (MCP server and commands other than `refresh`): reads the JSON files in
  `cbam_mcp/data/`, or in `CBAM_MCP_DATA_DIR` if set. Sends nothing, writes nothing, reads no
  configuration or home-directory files. Your CN codes and countries stay on your machine.
- **`refresh`**: sends HTTPS requests to `publications.europa.eu` (CELLAR documents and SPARQL queries;
  the queries contain only fixed act numbers, CN chapter prefixes and identifiers returned by the
  previous query) and to `taxation-customs.ec.europa.eu` (the Excel and the CBAM page), with the
  User-Agent `cbam-mcp/0.1.0 (+https://github.com/Keremozdemirra/cbam-mcp)`. It writes only the data
  directory.

## What this is not

- **Not legal advice.** It is information from dated copies of public sources; read the Official
  Journal text before relying on it.
- **Not a CBAM declaration tool.** It does not prepare, check or submit CBAM declarations, does not
  talk to the CBAM Registry, and computes no certificates, prices or free allocation adjustments.
- **Not the legally binding values.** The Excel is published "for information purposes only"; the
  binding values are Annex I and IV to Implementing Regulation (EU) 2025/2621 as corrected by
  Implementing Regulation (EU) 2026/1740, as published in the Official Journal. The listed values are
  shown without the increase Annex I applies for the certificate calculation. Default values for
  electricity and emission factors for indirect emissions (Annexes II and III) are not included.
- **No duty rates.** Duty rates live in TARIC, for which the Commission's TARIC page
  (https://taxation-customs.ec.europa.eu/online-services/online-services-and-databases-customs/eu-customs-tariff-taric_en)
  lists no public API (read 2026-09-24): it links to the TARIC consultation application and says
  "TARIC raw data is also freely available in Excel format". This tool gives no tariff, TARIC
  measure or preference.

## Licence

MIT for the code. The bundled data keeps the licences listed above.
