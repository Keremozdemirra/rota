# eu-ets-mcp

**EU Emissions Trading System installations from the Union Registry: verified emissions, free allocation and surrendered units, by installation, LEI, country or sector, as an MCP server and a command line.**

<!-- mcp-name: io.github.Keremozdemirra/eu-ets-mcp -->

The European Commission publishes the Union Registry's installation data as daily extracts: one
CSV with every installation, aircraft operator and shipping company (23,322 rows on 2026-09-24),
and one with their yearly values (606,372 rows, a full 2005-2030 grid for each). Answering "what
did the installations of the company with this LEI emit from 2013 to 2025" means joining the two,
matching LEIs that the registry writes as `5299-00FGOWZKLBZ81V-67`, adding up three free-allocation
columns, and knowing that 2025 surrenders are not due until 30 September 2026. `eu-ets-mcp` does
that on a local copy and answers with a table, the snapshot date and the attribution line.

## Example

Real output, 2026-09-24, registry snapshot of the same day.

```
$ eu-ets top --country DE --activity steel --limit 5
Top 5 of 42 installations by verified emissions in 2025; registry DE; activity 5, 24. All 42 together: 24,221,164 t CO2e (derived).
  5: Installations for the production of pig iron or steel (primary or secondary fusion) including continuous casting
  24: Production of pig iron or steel

#  country  id  name                              act  city            verified t CO2e  free allocation  surrendered  code
-  -------  --  --------------------------------  ---  --------------  ---------------  ---------------  -----------  ----
1  DE       69  Integriertes Hüttenwerk Duisburg   24  Duisburg              6,705,307       14,680,872    6,705,319
2  DE       53  Glocke Duisburg                    24  Duisburg              3,901,188        6,285,941    1,668,203
3  DE       52  Roheisenerzeugung Dillingen        24  Dillingen/Saar        3,646,506        6,267,829    3,646,506
4  DE       43  Glocke Salzgitter                  24  Salzgitter            3,497,812        6,038,034    3,497,812
5  DE       60  Einheitliche Anlage Bremen         24  Bremen                2,170,849        4,340,247    2,170,849

Note: total_verified_emissions sums every matching installation with verified emissions above 0 (derived).
Note: No compliance codes for 2025: the listing offers them for [2021, 2022, 2023, 2024].
Note: Surrenders for 2025 are due by 30 September 2026 (Directive 2003/87/EC Art. 12(3)); this snapshot of 2026-09-24 may not hold them all yet.
Source: European Commission, EU ETS Union Registry, CC BY 4.0, retrieved 2026-09-24 (registry snapshot 2026-09-24). Changes: selected columns; free_allocation and totals derived by eu-ets-mcp.
```

An LEI that the registry carries. GLEIF lists 529900FGOWZKLBZ81V67 as voestalpine Stahl GmbH, Linz
(registration status LAPSED on 2026-09-24):

```
$ eu-ets lei 529900FGOWZKLBZ81V67 --from 2019
LEI 529900FGOWZKLBZ81V67: 6 installation(s); GLEIF record https://search.gleif.org/#/record/529900FGOWZKLBZ81V67

country   id  name                                         act  city  first  last  verified 2025
-------  ---  -------------------------------------------  ---  ----  -----  ----  -------------
AT        14  Voestalpine Kokerei Linz                      22  Linz   2005  2012
AT        15  Voestalpine Kraftwerk Linz                    20  Linz   2005  2012
AT        16  Voestalpine Stahl Linz                        24  Linz   2005            8,866,634
AT        17  voestalpine Stahl GmbH - Kalkwerk Steyrling   30  Linz   2005              321,951
AT       208  Voestalpine L6 Erweiterung                    24  Linz   2005  2012
AT       231  Voestalpine Stahl Linz sonstige Anlagen       20  Linz   2005  2012

Yearly totals over these installations (derived):

year  verified t CO2e  free allocation  surrendered  installations with values
----  ---------------  ---------------  -----------  -------------------------
2019        9,116,590        6,428,414    9,116,590                          2
2020        8,841,514        6,291,168    8,841,514                          2
2021        9,717,141        7,116,880    9,717,141                          2
2022        9,210,578        7,121,163    9,210,578                          2
2023        8,982,440        7,121,163    8,982,440                          2
2024        8,902,722        7,117,671    8,902,722                          2
2025        9,188,585        7,115,398    9,188,585                          2
2026                         6,383,014                                       2
2027                         6,230,123                                       2
2028                         5,924,482                                       2
2029                         5,160,586                                       2
2030                         3,571,837                                       2

Note: The LEI is the one the current account holder registered in the Union Registry; the registry does not validate it, and earlier years may have been operated by another company.
Note: yearly_totals are sums over these installations (derived).
Note: The registry file writes 0 both for a reported zero and for nothing verified or allocated (the Commission's annual XLSX shows the latter as n/a). Years with no value at all are left out.
Note: Surrenders for 2025 are due by 30 September 2026 (Directive 2003/87/EC Art. 12(3)); this snapshot of 2026-09-24 may not hold them all yet.
Note: Verified emissions and surrenders after 2025 are not reported yet and shown as null; allocation for those years is the registry's current figure.
Source: European Commission, EU ETS Union Registry, CC BY 4.0, retrieved 2026-09-24 (registry snapshot 2026-09-24). Changes: selected columns; free_allocation and totals derived by eu-ets-mcp.
```

And one it does not. GLEIF lists 549300QGIICV4ZFTKX83 as ThyssenKrupp Steel Europe AG, Duisburg,
but no installation in the registry gives it as the account holder's LEI; the Duisburg integrated
steelworks, DE-69 above, has no LEI at all:

```
$ eu-ets lei 549300QGIICV4ZFTKX83
549300QGIICV4ZFTKX83: No installation in this snapshot lists this LEI. Only 5,234 of 23,322 installations carry an account-holder LEI, so this is not proof that the company holds none; search by installation name or city instead.

Source: European Commission, EU ETS Union Registry, CC BY 4.0, retrieved 2026-09-24 (registry snapshot 2026-09-24). Changes: selected columns.
```

```
$ eu-ets history DE-69 --from 2019
DE-69  Integriertes Hüttenwerk Duisburg
24 Production of pig iron or steel; city Duisburg; permit 14220-0035; LEI -; emissions 2005-

year  verified t CO2e  free allocation  surrendered  excluded  compliance
----  ---------------  ---------------  -----------  --------  ----------
2019        7,810,779       15,174,658    7,874,354
2020        6,835,470       14,861,357    6,835,471
2021        7,835,584       14,757,609    7,830,046            A
2022        7,935,590       14,749,000    7,935,269            A
2023        7,758,278       14,748,891    7,757,397            A
2024        7,271,749       14,755,828    7,271,737            A
2025        6,705,307       14,680,872    6,705,319
2026                        11,451,945
2027                        11,158,741
2028                        10,572,367
2029                         9,106,528
2030                         6,057,628
```

(Notes and source line as above.)

## Install

As an MCP server in Claude Code:

```bash
claude mcp add --transport stdio eu-ets -- uvx eu-ets-mcp
```

Any MCP client can start it the same way: the command is `uvx eu-ets-mcp` (or `pipx run eu-ets-mcp`),
stdio transport, no arguments, no keys.

The command line, without installing:

```bash
uvx --from eu-ets-mcp eu-ets top --country DE --activity steel
pipx run --spec eu-ets-mcp eu-ets lei 529900FGOWZKLBZ81V67
```

Standard library only, Python 3.9 or later. The package carries a dated snapshot of the registry
(3.3 MB compressed); on first use it is loaded into a SQLite cache (18.7 MB, about 4 seconds here).
To replace it with today's registry files:

```bash
uvx --from eu-ets-mcp eu-ets refresh
```

On 2026-09-24 a refresh from here downloaded 11,693,610 bytes in six files and took 23 to 30 seconds.
If it fails, the existing cache stays as it was.

## Tools (MCP)

| Tool | Returns |
| --- | --- |
| `search_installations(query, country, activity, limit)` | Installations whose name, city, permit id or id contain all the words (accents and case ignored), with activity, city, permit id, LEI and latest verified emissions (t CO2e), largest first. `limit` 1-100, default 20. |
| `installation_history(installation_id, country, from_year, to_year)` | One installation, year by year: verified emissions, free allocation and its three components, surrendered units, excluded flag, compliance code. Accepts `69` with `country`, or `DE-69`; an id used in several registries returns the candidates. |
| `company_by_lei(lei, from_year, to_year, detail)` | Installations whose account holder registered the LEI, and yearly totals over them (derived). `detail=true` adds each installation's years. |
| `top_emitters(country, year, activity, limit)` | Installations ranked by verified emissions in a year (default: the latest reported, 2025 in this snapshot), with free allocation, surrendered units, compliance code, the count of matching installations and their total (derived). |
| `dataset_info()` | Snapshot date, source files with URL, SHA-256 and row counts, countries, activity codes, years, units with their legal definitions, the columns kept, licence, attribution. |

`country` is a registry code (`DE`, `FR`, `GB`, `XI` for Northern Ireland) or a country name.
`activity` is the registry's activity code (`24`), several codes (`22,23,24,25`), or words matched
against the registry's activity labels (`steel` finds codes 5 and 24, the 2005-2012 and the current
code for pig iron and steel). The matched codes are part of every answer.

Every answer carries `snapshot_date` and a `source` line to cite; answers with figures carry their
units, and notes where they apply (surrender deadlines, maritime phase-in, zeros that may mean
"nothing entered").

## Commands

| Command | What it does |
| --- | --- |
| `eu-ets search WORDS [--country C] [--activity A] [--limit N]` | `search_installations` |
| `eu-ets history ID [--country C] [--from Y] [--to Y]` | `installation_history` |
| `eu-ets lei LEI [--from Y] [--to Y] [--detail]` | `company_by_lei` |
| `eu-ets top [--country C] [--year Y] [--activity A] [--limit N]` | `top_emitters` |
| `eu-ets info` | `dataset_info` |
| `eu-ets refresh [--write-snapshot DIR] [--no-compliance] [--keep-raw]` | Download the registry files and rebuild the cache. |
| `eu-ets serve` | The MCP server, same as `eu-ets-mcp`. |

`--json` on the query commands prints the MCP answer. Exit codes: 0 found, 1 nothing found (or an
ambiguous id), 2 bad arguments, no data, or a failed refresh. `--cache-dir DIR` or
`EU_ETS_CACHE_DIR` moves the cache (default `~/.cache/eu-ets-mcp`, `%LOCALAPPDATA%\eu-ets-mcp` on
Windows, `~/Library/Caches/eu-ets-mcp` on macOS). `EU_ETS_SNAPSHOT_DIR` points to another snapshot
directory, such as one written by `eu-ets refresh --write-snapshot`.

## Data source, licence and attribution

| | |
| --- | --- |
| Publisher | European Commission, EU ETS Union Registry, https://union-registry-data.ec.europa.eu/ |
| Files | `operators_daily.csv.gz`, `operators_yearly_activity_daily.csv.gz` (daily), `compliance_YYYY_code_en.xlsx` (2021-2024 on 2026-09-24) |
| How they are found | The JSON list at https://union-registry-data.ec.europa.eu/api/data-download, which the registry website loads to show its download page. **It is undocumented and may change or disappear without notice.** File URLs are always taken from it; the tool fetches only from that host, the registry's blob storage (`dlsclimabi.blob.core.windows.net`) and `*.europa.eu`, over https. |
| Licence | CC BY 4.0. The registry website's footer links to the Commission's legal notice, https://commission.europa.eu/legal-notice_en, which says: "Unless otherwise indicated (e.g. in individual copyright notices), content owned by the EU on this website is licensed under the Creative Commons Attribution 4.0 International (CC BY 4.0) licence. This means that reuse is allowed, provided appropriate credit is given and changes are indicated." (checked 2026-09-24) |
| Attribution | Every answer ends with `Source: European Commission, EU ETS Union Registry, CC BY 4.0, retrieved <date> (registry snapshot <date>). Changes: ...`; it says "derived" when the tool computed a number. Keep it when you reuse the numbers. |
| Bundled snapshot | `data/`, retrieved 2026-09-24 09:40 UTC; [data/SOURCES.md](data/SOURCES.md) lists the file URLs, SHA-256 of the raw files, row counts and the changes made. `eu-ets refresh --write-snapshot data/` rebuilds it; the same input gives byte-identical files. |

### Units and definitions

| Field | Meaning | Source, checked 2026-09-24 |
| --- | --- | --- |
| `verified_emissions` | t CO2e, tonnes of carbon dioxide equivalent | Directive 2003/87/EC Art. 3(j); reports verified by 31 March of the following year, Art. 15 |
| `free_allocation` | Allowances; one allowance is one tonne of CO2e. Derived: the sum of `ALLOCATION` (Art. 10a(1)), `ALLOCATION_RES` (new entrants reserve, Art. 10a(7)) and `ALLOCATION_TRA` (Art. 10c), also returned separately by `installation_history` | Art. 3(a); the split is described in the "Read Me" sheet, note 3, of the Commission's `verified_emissions_2025_en.xlsx` |
| `surrendered` | Units surrendered, all unit types (`SURR_ALL`, which equals the sum of the eight `SURR_*` columns in all 606,372 rows of the 2026-09-24 file). Surrender equal to verified emissions is due by 30 September of the following year | Art. 12(3) |
| `compliance_code` | `A` surrendered ≥ verified emissions; `B` surrendered < verified emissions; `C` verified emissions not entered; `-` no compliance obligation; `EXCLUDED SINCE 2021` | Legend of `compliance_2024_code_en.xlsx`, citing Regulation (EU) 2019/1122, Annex XIII |
| Shipping companies | Surrender 40% of 2024 and 70% of 2025 verified emissions, 100% from 2026; their verified emissions are reported before that phase-in | Art. 3gb; note 7 of the `verified_emissions_2025_en.xlsx` Read Me |
| Aircraft operators | Since 2020, `surrendered` also covers Swiss ETS emissions (`ch_verified_emissions`) | Legend of `compliance_2024_code_en.xlsx` ("cumulative surrenders in EU and Swiss ETS"); in the 2026-09-24 file, `SURR_ALL` equals verified plus Swiss emissions in 474 of the 587 aircraft-operator years with Swiss emissions in 2022-2024 |
| Activity codes | Returned as the registry's code and label: 1-9 the codes used in 2005-2012, 10 aircraft operators, 20-47 the Annex I activities as listed since 2013, 50 shipping companies, 99 activities opted in under Art. 24, 70 "Regulated Entity" (the Directive uses that term for Chapter IVa, the system for buildings, road transport and additional sectors, Art. 3(ae); these accounts have no yearly values in this snapshot) | Labels from the registry file; alignment of 1-9 with the current labels from the "activity codes" sheet of `verified_emissions_2025_en.xlsx` |

The Directive is cited from its consolidated text of 1 March 2024 (CELEX 02003L0087-20240301), the
version the Commission's Union Registry page links to; the consolidated text is a documentation tool
without legal effect, and the binding texts are those published in the Official Journal.

### How the numbers were checked

On 2026-09-24 the daily extract was compared value by value with the Commission's annual
`verified_emissions_2025_en.xlsx` (extracted 1 April 2026). Verified emissions matched for 11,982 of
11,983 installations with a number in both for 2013, 12,347 of 12,382 for 2024 and 9,528 of 9,643
for 2025 (the XLSX is an extract of 1 April 2026, the daily file of 24 September 2026). For 2013,
the 5,935 installations the XLSX marks `n/a` all have 0 in the daily file, which is why a 0 is
reported with a note rather than as a fact. The daily `ALLOCATION_RES` and `ALLOCATION_TRA` columns
matched the XLSX's `ALLOCATION_RESERVE_YYYY` and `ALLOCATION_TRANSITIONAL_YYYY` for every installation
with a number in both, for 2013 and 2024.

## Personal data

The operators file names natural persons: `ACCOUNT_IDENTIFIER_IN_REG` holds account labels such as
a private person's name, and `ACCOUNT_HOLDER_NAME` is the operator, who may be a natural person
(Directive 2003/87/EC Art. 3(f), 3(g)); the 2026-09-24 file has both. So only these columns are
read, and everything else is discarded while parsing:

| Column | Why it is kept |
| --- | --- |
| `REGISTRY_CODE`, `REGISTRY_NAME` | The country, needed to identify an installation (ids repeat across registries) |
| `INSTALLATION_IDENTIFIER`, `PERMIT_IDENTIFIER` | Identify the installation |
| `INSTALLATION_NAME` | Names the site; see the exception below |
| `ACTIVITY_TYPE_CODE`, `ACTIVITY_TYPE` | The sector |
| `CITY` | Tells same-named installations apart; street address and postcode are not kept |
| `ACCOUNT_HOLDER_LEI` | Identifies the company without naming anyone |
| `YEAR_OF_FIRST_EMISSIONS`, `YEAR_OF_LAST_EMISSIONS`, `PERMIT_REVOCATION_DATE`, `SNAPSHOT_DATE` | Dates |
| Yearly file: `VERIFIED_EMISSIONS`, `CH_VERIFIED_EMISSIONS`, `ALLOCATION`, `ALLOCATION_RES`, `ALLOCATION_TRA`, `EXCLUDED`, `SURR_ALL` | The figures |

Never read: the account holder's name, address, postcode, city, country and registration number,
the account label, account identifiers, the installation's street address and postcode, the EPER
id. No account holder name is stored, so the tool has no name search for companies; use the LEI or
the installation name.

One exception, this tool's own choice and not a rule of the source: for aircraft operators (10),
shipping companies (50) and ETS2 regulated entities (70) the installation name is the operator,
which the Directive allows to be a natural person (Art. 3(o), 3(w), 3(ae)). Such a name is kept
only if it is a code or contains a company's legal form (or, for 10 and 50, a shipping or aviation
word); otherwise it is shown as `[name withheld]`, without its city. In the 2026-09-24 snapshot
that is 83 of 6,552 such names, among them sole traders listed as regulated entities, 19
placeholders such as `-`, and shipping companies whose registry name has no legal form. The test
fixtures carry placeholders (Mustermann) in every personal field, and the tests check that none of
them reaches the cache, the snapshot or any output.

## What it reads and what it sends

- **Reads:** the bundled snapshot and its cache directory. Nothing else on your machine.
- **Sends:** nothing while answering. All queries run on the local SQLite cache; the MCP server makes
  no network request. Only `eu-ets refresh` goes online: one GET for the listing, then one GET per
  listed file it uses (two CSV extracts, the compliance files), with a `User-Agent` naming this
  tool. Nothing you type is sent anywhere.
- **Writes:** the cache directory only.

## Limits

- The LEI is the one the **current** account holder registered. The registry does not validate it:
  76 of the 5,234 LEI entries fail the ISO 17442 check digits. Earlier years of an installation may
  belong to another operator.
- Compliance codes exist only for the years whose file the listing offers (2021-2024 on 2026-09-24).
- The latest year's surrenders are incomplete until 30 September of the following year.
- Figures are the registry's; the tool adds only sums. It does not correct for scope changes
  between trading periods (the Commission's note: "As of 2013 data is not directly comparable to
  data of 2012 and before given the extended scope of the EU ETS in phase III").

## Licence

MIT for the code. The data is the European Commission's, under CC BY 4.0 (see above).

## What this is not

It is not the Union Registry and not an official publication: it is a copy of public registry
extracts with some columns left out and some sums added, as of the snapshot date it states. It is
information from a public register, not legal advice; the binding acts are Directive 2003/87/EC and
Regulation (EU) 2019/1122. It says nothing about who operated an installation in past years, and it
does not judge any operator: a compliance code or a ranking is the registry's record, not a finding.
