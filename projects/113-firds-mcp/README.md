# firds-mcp

<!-- mcp-name: io.github.Keremozdemirra/firds-mcp -->

**Who issued an ISIN, what is the issuer's LEI, who is the ultimate parent, and where does the instrument trade.** One MCP tool call or one command, answered from ESMA's Financial Instruments Reference Data System (FIRDS) and GLEIF's LEI data.

## Why it exists

The answer sits in two public registers that do not link to each other. FIRDS holds the reference data that EU/EEA trading venues and systematic internalisers report for each instrument: its name, CFI code, an LEI, and every venue (by MIC) with admission and termination dates. GLEIF knows who that LEI is and which entity consolidates it, or why no parent is reported. Getting from an ISIN to a group by hand means a search on ESMA's register website, copying the LEI into GLEIF's search, and following parent links while interpreting reporting-exception codes.

`firds-mcp` does those steps in one call, checks every identifier on your machine before it is sent, and carries the attribution and the disclaimer each source asks for. Several MCP servers cover GLEIF alone; a search of the MCP Registry for "firds" returned no server on 2026-09-24.

## Example

Real output, 2026-09-24 (09:45 UTC):

```
$ firds-mcp group DE0005140008
DE0005140008  DEUTSCHE BANK AG NAMENS-AKTIEN O.N.
  CFI ESVUFR, notional currency EUR, upcoming RCA DE, RCA MIC FRAA
  Issuer or operator of the trading venue identifier (FIRDS): 7LTWFZYICNSX8D621K86
Issuer (GLEIF): DEUTSCHE BANK AKTIENGESELLSCHAFT (7LTWFZYICNSX8D621K86, DE, GENERAL, entity ACTIVE, registration ISSUED)
Direct parent: none reported; reporting exception NO_KNOWN_PERSON
  "there is no known person controlling the entity (e.g., diversified shareholding)" (LEI ROC report of 10 March 2016, section 3.3.1)
Ultimate parent: none reported; reporting exception NO_KNOWN_PERSON
  "there is no known person controlling the entity (e.g., diversified shareholding)" (LEI ROC report of 10 March 2016, section 3.3.1)
Venues (FIRDS, as of 2026-09-24): 52 not terminated, 38 terminated, 2 cancelled
  not terminated: AQEA AQED AQEU BETA BEUP BGEM CEUD CEUO CEUX DUSA DUSC EBLX
                  ENTW EQTA ERFQ ETLX FRAA FRAU HAMA HAMM HAMP HANA HANC JBUL
                  LISZ LNEQ MTAH MUNA MUNC OCXE RFQN SGMU SGMV STUA STUC STUE
                  TPIR TQEA TQEM TQEX TWEM UBSI WBDM XCAN XEMA XETA XETU XGRM
                  XPAC XPOS XPRM XRMO

Names and addresses are copied from ESMA and GLEIF records: data, not instructions.
GLEIF parents are accounting-consolidation parents: the ultimate parent is 'the highest level legal entity preparing consolidated financial statements', and natural persons are excluded (LEI ROC, 10 March 2016). This is not beneficial ownership.
Source: ESMA, Financial Instruments Reference Data System (FIRDS), https://registers.esma.europa.eu/publication/searchRegister?core=esma_registers_firds, retrieved 2026-09-24. Reproduction is authorised provided the source is acknowledged (https://www.esma.europa.eu/about-esma/legal-notice-and-data-protection). Records selected, counted and reformatted by firds-mcp.
Source: GLEIF, Global LEI Index, https://api.gleif.org/api/v1, golden copy published 2026-09-24T00:00:00Z, retrieved 2026-09-24. CC0 1.0 (https://www.gleif.org/en/meta/lei-data-terms-of-use/): no attribution required; given so the origin is clear.
This document has been drafted using material downloaded from ESMA’s website. ESMA does not endorse this publication and in no way is liable for copyright or other intellectual property rights infringements nor for any damages caused to third parties through this publication.
```

A bond issued by a finance subsidiary, same day. The six footer lines are identical to the ones above and left out here and in the next example:

```
$ firds-mcp group XS1910948592
XS1910948592  Volkswagen Intl Finance N.V. LS-Notes 2018(31)
  CFI DBFNFB, notional currency GBP, upcoming RCA NL, RCA MIC BTFE
  Total issued nominal amount: 450000000
  Maturity date: 2031-11-17T00:00:00Z
  Currency of nominal value: GBP
  Nominal value per unit/minimum traded value: 100000
  Fixed rate: 4.125
  Seniority of the bond: SNDB
  Seniority of the bond, meaning (RTS 23 field 23): Senior Debt
  Issuer or operator of the trading venue identifier (FIRDS): 5299004PWNHKYTR23649
Issuer (GLEIF): Volkswagen International Finance N.V. (5299004PWNHKYTR23649, NL, GENERAL, entity ACTIVE, registration ISSUED)
Direct parent: VOLKSWAGEN AKTIENGESELLSCHAFT (529900NNUPAGGOMPXZ31, DE, GENERAL, entity ACTIVE, registration ISSUED)
  IS_DIRECTLY_CONSOLIDATED_BY, ACTIVE, FULLY_CORROBORATED
Ultimate parent: VOLKSWAGEN AKTIENGESELLSCHAFT (529900NNUPAGGOMPXZ31, DE, GENERAL, entity ACTIVE, registration ISSUED)
  IS_ULTIMATELY_CONSOLIDATED_BY, ACTIVE, FULLY_CORROBORATED
Venues (FIRDS, as of 2026-09-24): 16 not terminated, 10 terminated, 0 cancelled
  not terminated: AURO BTFE DUSB DUSD FRAB FRAV HAMQ MANL MUNB MUND SSOB STUB
                  STUD TPIO TWEM XLUX
```

An exchange-traded fund. A fund reports no accounting parent, so the answer follows GLEIF's fund links instead: the umbrella fund, the fund manager, and the manager's ultimate parent.

```
$ firds-mcp group IE00B4L5Y983
IE00B4L5Y983  iShsIII-Core MSCI World U.ETF Registered Shs USD (Acc) o.N.
  CFI CEOGES, notional currency USD, upcoming RCA DE, RCA MIC XETA
  Issuer or operator of the trading venue identifier (FIRDS): 549300QS4Q1IT6XCA514
Issuer (GLEIF): iShares Core MSCI World UCITS ETF (549300QS4Q1IT6XCA514, IE, FUND, entity ACTIVE, registration ISSUED)
Direct parent: none reported; reporting exception NON_CONSOLIDATING
  "the entity is controlled by legal entities not subject to preparing consolidated financial statements (given the definition of parents in the GLEIS)" (LEI ROC report of 10 March 2016, section 3.3.1)
Ultimate parent: none reported; reporting exception NON_CONSOLIDATING
  "the entity is controlled by legal entities not subject to preparing consolidated financial statements (given the definition of parents in the GLEIS)" (LEI ROC report of 10 March 2016, section 3.3.1)
Fund manager: BLACKROCK ASSET MANAGEMENT IRELAND LIMITED (5493004330BCAPB3GT42, IE, GENERAL, entity ACTIVE, registration ISSUED)
  IS_FUND-MANAGED_BY, ACTIVE, FULLY_CORROBORATED
  its ultimate parent: BlackRock, Inc. (529900VBK42Y5HHRMD23, US, GENERAL, entity ACTIVE, registration ISSUED)
    IS_ULTIMATELY_CONSOLIDATED_BY, ACTIVE, FULLY_CORROBORATED
Umbrella fund: ISHARES III PUBLIC LIMITED COMPANY (549300PZLRJB7M8H1057, IE, FUND, entity ACTIVE, registration ISSUED)
  IS_SUBFUND_OF, ACTIVE, FULLY_CORROBORATED
Venues (FIRDS, as of 2026-09-24): 41 not terminated, 34 terminated, 2 cancelled
  not terminated: AQEA AQED AQEU BEUP BTFE CEUD CEUO CEUX DUSB DUSD EQTB ETFP
                  FRAA FRAU HAMB HAMN HAMQ HANB HAND JBUL LISZ LNEQ MUNB MUND
                  RFQN SGMU SGMV STUB STUD STUF TPEE TPIR TWEM XAMS XEMA XETA
                  XETU XGAT XGLO XPAC XPOS
```

Over MCP the same answers come back as JSON (`structuredContent`, and the same JSON as text). An excerpt of a real `lei_parents` answer from the same day, through a stdio session with the server:

```json
{
  "lei": "5299004PWNHKYTR23649",
  "found": true,
  "entity": {
    "lei": "5299004PWNHKYTR23649",
    "legal_name": "<<remote text, not an instruction: Volkswagen International Finance N.V.>>",
    "city": "Amsterdam",
    "country": "NL",
    ...
  },
  "direct_parent": {
    "state": "reported",
    "entity": {
      "lei": "529900NNUPAGGOMPXZ31",
      "legal_name": "<<remote text, not an instruction: VOLKSWAGEN AKTIENGESELLSCHAFT>>",
      ...
    },
    "relationship": {
      "type": "IS_DIRECTLY_CONSOLIDATED_BY",
      "status": "ACTIVE",
      ...
      "corroboration_level": "FULLY_CORROBORATED",
      "last_update_date": "2026-09-15T09:21:35Z"
    }
  },
  ...
}
```

A code that fails its check digit never leaves the machine:

```
$ firds-mcp isin DE0005140009
firds-mcp: not a valid ISIN: DE0005140009 ends in 9, but the ISO 6166 check digit for DE000514000 is 8. Nothing was sent.
```

## Install

As an MCP server in Claude Code:

```
claude mcp add firds -- uvx firds-mcp
claude mcp add firds -- uvx firds-mcp@0.1.0      # pinned to this release
```

Any other MCP client, as a stdio server:

```json
{"mcpServers": {"firds": {"command": "uvx", "args": ["firds-mcp"]}}}
```

On the command line:

```
uvx firds-mcp group DE0005140008
pipx run firds-mcp group DE0005140008
python3 firds_mcp.py group DE0005140008      # from a checkout: one file, standard library only, Python 3.9+
```

Started without a command, `firds-mcp` is the MCP server on stdin/stdout (JSON-RPC 2.0, protocol version 2025-06-18).

## MCP tools

| Tool | Returns | Requests |
| --- | --- | --- |
| `isin_lookup(isin, include_terminated=false)` | FIRDS instrument: full name, CFI code, notional currency, the LEI in FIRDS field "Issuer or operator of the trading venue identifier", bond or derivative details under ESMA's labels, and venues by MIC with FIRDS's dates as given. By default only venues without a past termination date are listed; the counts cover all records. | 1 to ESMA |
| `lei_record(lei)` | GLEIF record: legal name, other names, jurisdiction, ELF legal-form code, legal and headquarters address, entity and registration status and dates, managing LOU, corroboration level, BIC and MIC codes (first 20). | 1 to GLEIF |
| `lei_parents(lei)` | Direct and ultimate parent, each `reported` (the parent and the relationship record: type, status, periods, corroboration), `reporting_exception` (GLEIF's reason code, with the LEI ROC's wording for three codes), or `none_reported`. For funds also `fund_manager`, `umbrella_fund`, `master_fund` when GLEIF links them. | typically 3 to 7 to GLEIF |
| `lei_children(lei, limit=20, relation="direct")` | Entities reporting this LEI as their direct or ultimate parent, with GLEIF's total; at most `limit` (1 to 500). | 1 to GLEIF per 200 |
| `isin_to_group(isin)` | The chain: FIRDS summary and the MICs of venues without a past termination date, the issuer's GLEIF record, direct and ultimate parents, and for funds the fund manager, its ultimate parent and the umbrella fund. If GLEIF fails, the FIRDS part is still returned with `gleif_error`. | 1 to ESMA, typically 3 to 9 to GLEIF |
| `sources()` | Endpoints, licences and terms with quotes, attribution lines, ESMA's disclaimer, GLEIF's rate limit, what is sent. | none |

Every answer carries a `sources` list with one attribution line per source it used; answers with FIRDS data also carry ESMA's `disclaimer`. Invalid input is an error result (`isError: true`) saying what is wrong, and nothing is sent. A code that is valid but unknown to the source is an answer with `found: false`.

## Command line

| Command | What it does |
| --- | --- |
| `firds-mcp group ISIN` | `isin_to_group` |
| `firds-mcp isin ISIN [--all-venues]` | `isin_lookup`; `--all-venues` also lists terminated and cancelled venue records with their dates |
| `firds-mcp lei LEI` | `lei_record` |
| `firds-mcp parents LEI` | `lei_parents` |
| `firds-mcp children LEI [--limit N] [--ultimate]` | `lei_children` |
| `firds-mcp sources` | `sources`, as JSON |

Each takes `--json` to print the JSON the MCP tool returns. Exit codes: 0 answered, 1 not found (FIRDS has no current record, or GLEIF has no such LEI), 2 invalid input, or a source could not answer (including a `group` answer whose GLEIF part is missing).

## What the fields mean

FIRDS fields are passed on as FIRDS gives them, dates included (ISO 8601, UTC). The labels are the ones ESMA's register website uses ([register configuration](https://registers.esma.europa.eu/publication/registerConfig/xml), checked 2026-09-24); the field numbers are those of RTS 23, Commission Delegated Regulation (EU) 2017/585, Annex, Table 3 (OJ L 87, 31.3.2017, p. 368; the text as published, later amendments not checked).

| Key | ESMA label | RTS 23 |
| --- | --- | --- |
| `full_name` | Instrument full name | 2 |
| `cfi_code` | Instrument classification | 3 |
| `commodity_or_emission_allowance_derivative` | Commodities or emission allowance derivative indicator | 4 |
| `issuer_or_venue_operator_lei` | Issuer or operator of the trading venue identifier | 5 |
| `mic` | Trading venue | 6 |
| `short_name` | Financial instrument short name | 7 |
| `issuer_requested_admission` | Request for admission to trading by issuer | 8 |
| `issuer_approval` | Date of approval of the admission to trading | 9 |
| `admission_request` | Date of request for admission to trading | 10 |
| `admission_or_first_trade` | Date of admission to trading or date of first trade | 11 |
| `termination` | Termination date | 12 |
| `notional_currency` | Notional currency 1 | 13 |
| `details` | bond and derivative fields, keyed by ESMA's labels | 14 to 48 |
| `publication_from`, `publication_to` | Publication from date, Publication to date | register field |
| `upcoming_rca`, `rca_mic`, `status` | Upcoming RCA, RCA MIC, Status | register field |

Three things worth knowing:

- **Field 5 is not always an issuer.** RTS 23 defines it as "LEI of issuer or trading venue operator". For the Eurex futures contract DE000C1D9NG7, FIRDS gives 529900UT4DG0LG5R9O07, which GLEIF names EUREX Frankfurt Aktiengesellschaft (both checked 2026-09-24).
- **Venues include systematic internalisers, by segment.** Field 6 is the "Segment MIC for the trading venue or systematic internaliser, where available, otherwise operating MIC". That is why Xetra appears as XETA and XETU, which the [ISO 10383 MIC list](https://www.iso20022.org/market-identifier-codes) gives as segments of the operating MIC XETR ("XETRA - REGULIERTER MARKT" and its off-book segment; checked 2026-09-24).
- **Venue names differ.** Each venue reports its own full name for the instrument. `full_name` is the one most venue records use, with runs of spaces collapsed.

`state` is this tool's own derivation, not a FIRDS field: `cancelled` when the FIRDS status is Cancelled; `terminated` when FIRDS gives a termination date on or before the moment of the query, or the status Terminated without a date; `unknown` when a termination date cannot be read; otherwise `not_terminated`. Bonds often carry their maturity as a future termination date, and one record for DE0005140008 carries 9999-12-31; both count as not terminated. Only records FIRDS marks as the latest for their venue are used (`latest_received_flag:1`, the register website's own default).

GLEIF's parents are accounting-consolidation parents. The LEI ROC defines the ultimate parent as "the highest level legal entity preparing consolidated financial statements" and excludes natural persons ([LEI ROC, 10 March 2016](https://www.leiroc.org/publications/gls/lou_20161003-1.pdf)). Instead of a parent, GLEIF can hold a reporting exception with one of these reason codes: NO_LEI, NATURAL_PERSONS, NON_CONSOLIDATING, NO_KNOWN_PERSON, NON_PUBLIC, and five codes deprecated since 1 March 2022 ([GLEIF, Reporting Exceptions format 2.1](https://www.gleif.org/en/lei-data/access-and-use-lei-data/level-2-data-reporting-exceptions-2-1-format), checked 2026-09-24). For NATURAL_PERSONS, NON_CONSOLIDATING and NO_KNOWN_PERSON the answer quotes the ROC report's reasons a(i) to a(iii) in section 3.3.1; matching the code names to those three reasons is this tool's reading of the names.

## Data sources, licences, attribution

### ESMA FIRDS

- **Endpoint:** `https://registers.esma.europa.eu/solr/esma_registers_firds/select`, the Solr backend behind ESMA's [FIRDS register search](https://registers.esma.europa.eu/publication/searchRegister?core=esma_registers_firds). **It is undocumented**: ESMA does not publish it as an API, and it may change or disappear without notice. When it does, the tools say so (`kind: schema` or `http`), and the GLEIF tools keep working.
- **The documented route** is the set of daily full and delta files (FULINS, DLTINS), listed by `https://registers.esma.europa.eu/solr/esma_registers_firds_files/select` and downloaded from firds.esma.europa.eu, as described in ESMA's [instructions ESMA65-8-5014 rev.3](https://www.esma.europa.eu/sites/default/files/library/esma65-8-5014_firds_-_instructions_for_download_of_full_and_delta_reference_files.pdf) (9 February 2022). ESMA's instructions describe building a local database of all instruments from them (section 4.2); that is far more than one lookup needs, so `firds-mcp` does not use them. For the same reason it ships no snapshot: the lookup is live, one request per ISIN.
- **Terms:** ESMA's [legal notice](https://www.esma.europa.eu/about-esma/legal-notice-and-data-protection) (checked 2026-09-24): "Reproduction of all information on this site (ESMA Library) is authorised except as otherwise stated, provided the source is acknowledged". It also requires, when the material is transformed and republished, "the following disclaimer: ‘This document has been drafted using material downloaded from ESMA’s website’ [...] ESMA does not endorse this publication and in no way is liable for copyright or other intellectual property rights infringements nor for any damages caused to third parties through this publication’". Every answer with FIRDS data carries that wording and a source line.
- **FIRDS disclaimer** (shown on the register, checked 2026-09-24): "ESMA is not able to provide any representation or warranty that the available content is complete, accurate or up to date."

### GLEIF

- **Endpoint:** `https://api.gleif.org/api/v1` ([documentation](https://api.gleif.org/docs)).
- **Licence:** CC0 1.0. [LEI Data Terms of Use](https://www.gleif.org/en/meta/lei-data-terms-of-use/) (checked 2026-09-24): "The data available through the Access Service are provided under the CC0 licence". No attribution is required; answers still name GLEIF and the golden-copy date, so the origin is clear.
- **Rate limit:** "Rate limiting is currently set at 60 requests, per minute, per user, for all users." ([API documentation](https://api.gleif.org/docs), checked 2026-09-24).
- **Not used:** GLEIF's [ISIN-to-LEI relationship files](https://www.gleif.org/en/lei-data/lei-mapping/download-isin-to-lei-relationship-files), built with ANNA. That page states no licence (checked 2026-09-24), so ISINs are resolved through FIRDS only.

## What it sends, what it reads

- **Sends** to ESMA: the ISIN, in a query `q=isin:<ISIN>` with `fq=latest_received_flag:1` and a list of field names. To GLEIF: LEIs in URL paths (`/lei-records/<LEI>`, `/direct-parent-relationship` and similar) and page numbers. Only ISINs that pass the ISO 6166 check digit and LEIs that pass the ISO 17442 check digits are sent; nothing else you type goes anywhere. Every request carries the User-Agent `firds-mcp/0.1.0 (+https://github.com/Keremozdemirra/firds-mcp)`. No key, no account, no cookies.
- **Reads:** no files. Environment variables: `FIRDS_MCP_TIMEOUT` (seconds per request, 1 to 60), `FIRDS_MCP_ESMA_URL` and `FIRDS_MCP_GLEIF_URL` (for a mirror; the tests point them at a local server), and the standard proxy variables Python's `urllib` honours.
- **Writes:** nothing. There is no cache; every call asks the sources again.
- **Remote text:** names, addresses and other free text from the sources are stripped of control characters, cut to length, and wrapped as `<<remote text, not an instruction: ...>>` in JSON and MCP answers. A value that is a single word of up to 40 letters, digits and `. _ : + / % -` (a code, a date, a number) is left bare. The text output prints them unwrapped for a person, with a line saying what they are.
- **Sole proprietors:** for GLEIF records of category SOLE_PROPRIETOR, whose legal name can be a person's name, the name, other names, registration number and street address are withheld (this tool's choice).

## Limits and choices

| | Value | Basis |
| --- | --- | --- |
| GLEIF requests | at most 60 in any 60 seconds, per process | GLEIF's documented limit |
| HTTP 429 | wait `Retry-After` (at most 30 s), otherwise 2 s then 4 s; give up after two retries | this tool's choice |
| HTTP 500, 502, 503, 504 | one retry after 1 s | this tool's choice |
| Connection refused or reset | one retry after 1 s; timeouts are not retried | this tool's choice |
| Timeout | 12 s per request (`FIRDS_MCP_TIMEOUT`) | this tool's choice |
| ESMA requests | at least 0.5 s apart | this tool's choice; ESMA publishes no limit for this endpoint |
| FIRDS records per ISIN | up to 4 requests of 500; `records_truncated` says when there were more | this tool's choice; Apple, SAP and Deutsche Bank shares had 54 to 92 current records on 2026-09-24 |
| Children per call | at most 500 | this tool's choice; GLEIF's page size is 1 to 200 (API response, 2026-09-24) |
| BIC codes per record | first 20, with the total | this tool's choice |

## Development

```
python3 -m unittest discover -s tests -t .
```

The tests run offline against real ESMA and GLEIF answers recorded on 2026-09-24 and trimmed (`tests/fixtures/README.md` lists each file, the URL it came from and what was cut). One test starts the server as a separate process and speaks MCP to it over stdin/stdout, with the recorded answers served from 127.0.0.1.

The code is MIT-licensed (`LICENSE`). The data comes from its sources, under the terms above.

## What this is not

- **Not a register of all securities.** FIRDS holds reference data that EU/EEA trading venues and systematic internalisers report under Article 27 MiFIR and Article 4 MAR. An instrument that is not admitted to trading or traded on such a venue is not in it; `found: false` means FIRDS has no current record, not that the ISIN does not exist.
- **Not beneficial ownership.** GLEIF parents are accounting-consolidation parents, reported by the entities themselves; each relationship record states how far it was corroborated. Natural persons never appear as parents.
- **Not official.** This is not an ESMA or GLEIF product, and neither endorses it. ESMA states that it "is not able to provide any representation or warranty that the available content is complete, accurate or up to date"; the same goes for this tool's reformatting of it.
- **Not advice.** Reference data, stated as the sources give it. Not investment, legal or compliance advice, and no verdict on any issuer.
- **Not a MIC directory.** Venues are given as MIC codes, as FIRDS gives them; the tool does not resolve them to venue names.
- **Not real time.** FIRDS publishes daily; GLEIF answers from its golden copy, whose publication date every answer with GLEIF data states.
