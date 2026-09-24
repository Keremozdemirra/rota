# financed-emissions

<!-- mcp-name: io.github.Keremozdemirra/financed-emissions -->

**Financed emissions (Scope 3 category 15) by the PCAF Part A methods, with the arithmetic shown for every position.**

A bank or investor gives it a portfolio CSV: asset class, outstanding amount, the denominator the method needs,
the counterparty's emissions and a PCAF data quality score. It returns financed emissions per position and per
PCAF asset class, the outstanding-weighted data quality score, and the positions it could not compute, each with
the reason. Every computed position carries the formula used and the page of the standard it comes from.

It implements the ten asset classes of **PCAF Part A, Third Edition (December 2025)**, the current edition on
2026-09-24. Python 3.9+, standard library only, usable as a command or as an MCP server. It is not affiliated
with or endorsed by PCAF.

## Why it exists

The attribution arithmetic is short: outstanding amount over a denominator, times emissions. The rules around it
are many and spread over 200 pages: negative total equity counts as zero (5.2, p. 57), a vehicle of unknown value
is attributed at 100% (5.6, p. 91), a sub-sovereign factor is capped at 1 (5.10, p. 154), sovereign exposure in
USD is divided by PPP-adjusted GDP in international dollars (5.9, p. 144), scope 3 and removals are reported
separately (6.1, pp. 162, 165), and data quality is weighted by outstanding amount with scope 3 weighted apart
(6.1, p. 167). This tool applies them in the open, one line per step, each with its page, so a reviewer can
follow a figure back to its inputs and to the standard.

## Example

[`examples/portfolio.csv`](examples/portfolio.csv) holds 17 invented positions covering every asset class. All
counterparties are fictional and labelled as such; the `fx_rate` on the two USD rows is an illustrative value,
not a market rate. Two rows are there to fail (a mortgage without a property value, a swap) and one to be
flagged (a mortgage above 100% loan-to-value).

```bash
uvx financed-emissions examples/portfolio.csv --currency EUR
```

Real output, 2026-09-24 (excerpt: the per-asset-class summary and everything after it; the full run first
lists the 15 positions):

```
By PCAF asset class
asset class                                              positions  outstanding (EUR)  S1+2 tCO2e   S3 tCO2e  S1+2 tCO2e per M EUR  DQ S1+2  DQ S3
--------------------------------------------  --------------------  -----------------  ----------  ---------  --------------------  -------  -----
Listed equity and corporate bonds (5.1)                          2         20,000,000   19,150.00   5,050.00                957.50     1.40   3.40
Business loans and unlisted equity (5.2)                         3         23,000,000    9,815.00  19,600.00                426.74     3.09   4.63
Project finance (5.3)                                            2         51,000,000      273.00          -                  5.35     2.00    n/a
Commercial real estate (5.4)                                     1         18,000,000      618.00          -                 34.33     2.00    n/a
Mortgages (5.5)                                2 (+1 not computed)            555,000        6.56          -                 11.81     3.43    n/a
Motor vehicle loans (5.6)                                        1            400,000      310.00          -                775.00     4.00    n/a
Use of proceeds structures (5.7)                                 1         40,000,000    5,000.00   1,125.00                125.00     2.60   3.80
Securitization and structured products (5.8)                     1         20,000,000      221.33          -                 11.07     3.60    n/a
Sovereign debt (5.9)                                             1         27,600,000   12,947.37          -                469.11     1.00    n/a
Sub-sovereign debt (5.10)                                        1          9,200,000    2,470.59          -                268.54     2.00    n/a
Total                                         15 (+1 not computed)        209,755,000   50,811.84  25,775.00                242.24     2.20   3.78

Coverage: 99.9% of the outstanding amount of in-scope rows in this file was computed.
Weighted scores: sum(outstanding amount x data quality score) / sum(outstanding amount), per asset class or sector; scope 3 scores weighted separately from scope 1 and 2 (6.1, p. 167 and Box 6.1-6, pp. 167-168). Scope 3 is reported separately from scope 1+2 (6.1, p. 162).

By sector
sector          positions  outstanding (EUR)  S1+2 tCO2e   S3 tCO2e  DQ S1+2
--------------  ---------  -----------------  ----------  ---------  -------
Cement                  1          8,000,000   13,000.00   2,800.00     2.00
Food                    1          5,000,000    4,100.00  19,000.00     4.00
Forestry                1          6,000,000       48.00          -     2.00
Health care             1          3,000,000      115.00     600.00     2.00
Households              3         20,555,000      227.89          -     3.60
Infrastructure          1         40,000,000    5,000.00   1,125.00     2.60
Power                   1         45,000,000      225.00          -     2.00
Real estate             1         18,000,000      618.00          -     2.00
Sovereign               1         27,600,000   12,947.37          -     1.00
Sub-sovereign           1          9,200,000    2,470.59          -     2.00
Transport               2         15,400,000    5,910.00          -     3.03
Utilities               1         12,000,000    6,150.00   2,250.00     1.00

Reported separately
Emission removals, financed: 12,600.00 tCO2e (1 position), reported separately and not netted (6.1, p. 165).
Sovereign scope 1 including LULUCF, financed: 12,157.89 tCO2e (1 position; 5.9, p. 141; 5.10, p. 154).
Undrawn loan commitments: 5,000,000 EUR (1 position), 25.00 tCO2e scope 1+2, no scope 3 given; unweighted and reported separately from financed emissions (6.2, pp. 172-174).
Sovereign rows without scope 2 contribute scope 1 only to scope 1+2.

Not computed (2)
  line 11  MG-02 (mortgage, Mortgage 0002 (fictional borrower)): denominator (property value at origination) is blank
  line 18  DER-01 (derivative, Interest rate swap with Calder Bank (fictional)): derivatives (futures, options, swaps) are not covered by Part A (chapter 5, p. 37; 5.1, p. 40)

Flags (1)
  line 12  MG-03: attribution factor 1.05 is above 1; PCAF Part A (Third Edition) gives no cap for mortgage, so it was used as computed; check the denominator

Warnings (3)
  line 4  BL-01: scope 3 not supplied; PCAF requires it for every sector in reports published from 2025 and asks for an explanation when it cannot be reported (5.2, p. 56)
  line 16  SOV-01: scope 2 not supplied; PCAF says it should be reported for this issuer type (5.9, pp. 140-141); scope 1+2 shows scope 1 only
  line 17  SUB-01: scope 2 not supplied; PCAF says it should be reported for this issuer type (5.10, pp. 153-154); scope 1+2 shows scope 1 only

Method: PCAF (2025). The Global GHG Accounting and Reporting Standard Part A: Financed Emissions. Third Edition. https://carbonaccountingfinancials.com/files/standard-launch-2025/PCAF-PartA-2025-V3-15012026.pdf (checked 2026-09-24); cited by subchapter and page. Amounts, emissions and scores are the user's input; this tool fetched nothing.
```

With `--explain`, each position shows its arithmetic. Three of the fifteen, real output from the same run:

```
BL-02  Vireo Foods BV (fictional)  business_loan -> Business loans and unlisted equity (PCAF 5.2)
  attribution factor = outstanding amount / (total equity + total debt) [5.2, p. 57]
                     = 5,000,000 / (0 + 25,000,000) = 0.2
  financed scope 1 = 5,000,000 / 25,000,000 x 18,000 = 3,600.00 tCO2e [5.2, p. 58]
  financed scope 2 = 5,000,000 / 25,000,000 x 2,500 = 500.00 tCO2e [5.2, p. 58]
  financed scope 3 = 5,000,000 / 25,000,000 x 95,000 = 19,000.00 tCO2e (reported separately) [5.2, p. 58]
  financed scope 1+2 = 4,100.00 tCO2e [6.1, p. 162]
  data quality score = 4 (scope 1 and 2), 5 (scope 3)
  note: total equity -2,000,000 is negative; PCAF sets it to 0, so emissions are attributed to debt only (5.2, p. 57, footnote 75)

MV-01  Porter Vans Ltd fleet (fictional)  motor_vehicle_loan -> Motor vehicle loans (PCAF 5.6)
  attribution factor = 1 (value at origination unknown: PCAF says to assume 100% attribution) [5.6, p. 91]
  financed scope 1 = 1 x 310 = 310.00 tCO2e [5.6, p. 92]
  financed scope 2 = 1 x 0 = 0.00 tCO2e [5.6, p. 92]
  financed scope 1+2 = 310.00 tCO2e [6.1, p. 162]
  data quality score = 4 (scope 1 and 2)
  note: vehicle value at origination unknown: attribution assumed at 100% as PCAF advises (5.6, p. 91)

SOV-01  Republic of Examplia (fictional)  sovereign_debt -> Sovereign debt (PCAF 5.9)
  attribution factor = exposure (USD) / PPP-adjusted GDP (international $) [5.9, p. 144]
                     = 30,000,000 / 950,000,000,000 = 0.0000315789
  financed scope 1 = 30,000,000 / 950,000,000,000 x 410,000,000 = 12,947.37 tCO2e [5.9, p. 144]
  financed scope 1 incl. LULUCF = 30,000,000 / 950,000,000,000 x 385,000,000 = 12,157.89 tCO2e (reported separately) [5.9, p. 144]
  financed scope 1+2 = 12,947.37 tCO2e [6.1, p. 162]
  outstanding in EUR = 30,000,000 USD x fx_rate 0.92 = 27,600,000.00 (rate supplied by the user)
  data quality score = 1 (scope 1 and 2)
```

The same run with `--strict` exits 1: two positions were not computed and one is flagged.

## Install

```bash
uvx financed-emissions portfolio.csv --currency EUR
pipx run financed-emissions portfolio.csv --currency EUR
```

As an MCP server, for example in Claude Code:

```bash
claude mcp add financed-emissions -- uvx financed-emissions mcp
```

## Commands

```bash
financed-emissions portfolio.csv                  # text report
financed-emissions portfolio.csv --explain        # plus every position's arithmetic
financed-emissions portfolio.csv --markdown       # Markdown tables
financed-emissions portfolio.csv --json           # everything, unrounded
financed-emissions --methods                      # the formulas, scope rules and citations implemented
financed-emissions mcp                            # MCP server on stdio
```

| Option | What it does |
| --- | --- |
| `--explain` | Each position's formula with its numbers substituted, and the page it comes from. |
| `--markdown` | Markdown tables, for a review document. |
| `--json` | Machine-readable; values unrounded, arithmetic included. |
| `--strict` | Exit 1 if any position cannot be computed or is flagged. |
| `--currency CUR` | Reporting currency (ISO 4217). Needed when the file mixes currencies. |
| `--decimal-comma` | Numbers use a comma as decimal separator (`1.234,5`). |
| `--encoding ENC` | File encoding, when detection is not enough. |
| `--methods` | List the methods implemented; add `--json` for data. |
| `-` as the file | Read the CSV from standard input. |

Exit codes: 0 when the report was produced; 1 with `--strict` when a position was not computed or was flagged;
2 when the file could not be read as a portfolio (missing or unreadable file, required column missing, several
currencies without `--currency`).

### MCP tools

| Tool | Returns |
| --- | --- |
| `compute_portfolio(csv_path, reporting_currency?, decimal_comma?, encoding?, explain?, max_positions?)` | For a CSV on the same machine: financed scope 1, 2, 1+2 and 3 in tCO2e per position, per asset class and in total; weighted data quality (scope 1+2 and scope 3); tCO2e per million of the reporting currency; coverage; positions not computed with reasons; flags and warnings. Lists up to `max_positions` positions (default 100); totals always cover the whole file. Files up to 50 MB. |
| `attribute(asset_class, outstanding, emissions, denominator?, denominator_basis?, total_equity?, total_debt?, instrument?, currency?)` | One position: attribution factor, financed emissions in tCO2e, the arithmetic, citations, rules applied and flags. |
| `methods()` | Every asset class with its denominators, formulas, scope requirements, caps and page citations, plus the data quality rule. |

Errors (a missing file, a blank denominator, a derivative) come back as tool results with `isError: true` and
the reason.

## Input

One row per position. Column names are case-insensitive; spaces and hyphens count as underscores. Comma,
semicolon or tab separated; UTF-8, UTF-8 with byte order mark, UTF-16 and Windows-1252 are recognised. Amounts
in one unit throughout the file (whole currency units for the intensity column to mean per million); emissions in
tCO2e.

| Column | Required | Meaning |
| --- | --- | --- |
| `position_id` | yes | Unique per row. |
| `asset_class` | yes | One of the twelve keys in the next table. |
| `outstanding` | yes | Outstanding amount as PCAF defines it for the class (`--methods` shows each definition). |
| `denominator` | column yes | The value the class divides by. Blank allowed for a motor vehicle loan (100% attribution) or when `total_equity` and `total_debt` are given. |
| `scope1_tco2e` | yes | Counterparty scope 1. For use of proceeds and securitizations: the financed emissions of the structure or collateral pool. |
| `scope2_tco2e` | column yes | Scope 2. Blank allowed for sovereign and sub-sovereign debt only; enter 0 when there is none. |
| `dq_score` | column yes | PCAF data quality score, 1 (best) to 5. Blank means not scored: left out of the weighted score, with a warning. |
| `counterparty`, `sector` | no | Shown in the output; `sector` adds a breakdown by sector (also usable for regional, city and local sub-sovereign levels). |
| `currency` | no | ISO code of the row's amounts; blank means the reporting currency. |
| `fx_rate` | no | Reporting-currency units per one unit of the row's currency, supplied by you. |
| `denominator_basis` | no | Which denominator (next table); blank means the class default. |
| `total_equity`, `total_debt` | no | Instead of `denominator` for the equity-plus-debt basis, so the negative-equity rule can apply. |
| `instrument` | no | `debt` or `equity`, for project finance and use of proceeds. |
| `scope3_tco2e`, `dq_score_scope3` | no | Scope 3 and its score, reported and weighted separately. |
| `scope1_incl_lulucf_tco2e` | no | Sovereign and sub-sovereign scope 1 including LULUCF, reported separately; may be negative. |
| `removals_tco2e` | no | Emission removals, for listed equity, bonds, business loans, unlisted equity and project finance; reported separately. |
| `undrawn_commitment` | no | Undrawn amount of a committed loan facility; reported separately (6.2). |
| `allocation_pct` | no | Use of proceeds: allocated share of the structure in percent (default 100). |

## Methods implemented

Source: [PCAF Part A, Third Edition, December 2025](https://carbonaccountingfinancials.com/files/standard-launch-2025/PCAF-PartA-2025-V3-15012026.pdf),
file revision of 15 January 2026, 209 pages, SHA-256
`7c2b6b9725df9723e2837a42faf96cb5af8d821a7936b401d6ca58fbcc394a2c`, downloaded and checked 2026-09-24 from
[the standard's page](https://carbonaccountingfinancials.com/en/standard), which lists the second (2022) and first
(2019) editions as previous versions. The edition does not number its equations, so each formula is cited by
subchapter and page. In every class, financed emissions = attribution factor x emissions.

| `asset_class` | PCAF asset class | Attribution factor (`denominator_basis`, default first) | Cited |
| --- | --- | --- | --- |
| `listed_equity` | 5.1 Listed equity and corporate bonds | outstanding / EVIC (`evic`) | 5.1, pp. 42, 44 |
| `corporate_bond` | 5.1 | outstanding / EVIC (`evic`); / (total equity + debt) for private issuers (`total_equity_plus_debt`); / total assets as fallback (`total_assets`) | 5.1, pp. 42, 44, fn. 44 |
| `business_loan` | 5.2 Business loans and unlisted equity | outstanding / (total equity + debt); / EVIC for listed borrowers; / total assets | 5.2, pp. 57-58, fn. 77 |
| `unlisted_equity` | 5.2 | outstanding / (total equity + debt); / total assets | 5.2, pp. 57-58 |
| `project_finance` | 5.3 Project finance | outstanding / (total project equity + debt); / total assets; / project value at origination for a project without its own balance sheet (`project_value_at_origination`) | 5.3, pp. 67-70 |
| `commercial_real_estate` | 5.4 Commercial real estate | outstanding / property value at origination; / latest property value, then held constant (`latest_property_value`) | 5.4, pp. 78-79 |
| `mortgage` | 5.5 Mortgages | as commercial real estate | 5.5, p. 84 |
| `motor_vehicle_loan` | 5.6 Motor vehicle loans | outstanding / total value at origination; 100% when that value is unknown | 5.6, pp. 91-92 |
| `use_of_proceeds` | 5.7 Use of proceeds structures | investor outstanding / (total equity + debt of the structure), times the structure's financed emissions | 5.7, pp. 100-103 |
| `securitization` | 5.8 Securitization and structured products | investment outstanding / deal outstanding, both nominal (= investment x tranche attribution factor), times the collateral pool's financed emissions (`deal_outstanding`) | 5.8, p. 123; Table 5.8-3, pp. 124-125 |
| `sovereign_debt` | 5.9 Sovereign debt | exposure in USD / PPP-adjusted GDP in international $ (`ppp_adjusted_gdp`) | 5.9, p. 144 |
| `sub_sovereign_debt` | 5.10 Sub-sovereign debt | as sovereign debt, capped at 1 | 5.10, pp. 154-155 |

### Rules taken from the standard

| Rule | Where in PCAF Part A (3rd ed.) |
| --- | --- |
| Negative total equity counts as 0: emissions go to debt, and an equity stake in such an entity gets none. | 5.1 fn. 42; 5.2 fn. 75; 5.3 fn. 107; 5.7 fn. 164 |
| A motor vehicle of unknown value at origination is attributed at 100%; a repaid loan at 0. | 5.6, p. 91 |
| The sub-sovereign attribution factor is capped at 1. | 5.10, p. 154 |
| Collateral attribution factors in a securitization are capped at 1 (inside the pool emissions you supply). | 5.8, p. 122 |
| Scope 1 and 2 are required; scope 3 is required for listed equity, bonds, business loans and unlisted equity in reports published from 2025, and reported separately. | 5.1, pp. 40-41; 5.2, p. 56; 6.1, p. 162 |
| Sovereign scope 1 is reported excluding and including LULUCF; scope 2 and 3 should be reported. | 5.9, pp. 140-141 |
| Sovereign exposure is in USD, the denominator in international dollars. | 5.9, p. 144 |
| Weighted data quality = sum(outstanding x score) / sum(outstanding); scope 3 weighted separately. | 6.1, p. 167; Box 6.1-6, pp. 167-168 |
| Emission intensity in tCO2e per million of currency lent or invested. | 6.1, p. 166 |
| Removals are reported separately and never netted. | 6.1, p. 165 |
| Undrawn loan commitments are optional; when used, the unweighted figure is reported, separately. | 6.2, pp. 171-174 |
| Use of proceeds: the outstanding amount reported is the investor's outstanding times the allocation percentage. | 5.7, pp. 102-103 |
| Derivatives, short positions, general consumer loans, guarantees not yet called and assets held for trading are outside Part A. | ch. 5, pp. 35, 37; 5.1, p. 40; 5.3, p. 68 |

### Choices of this tool, not rules of the standard

- Where the standard sets no cap (every class except sub-sovereign debt), an attribution factor above 1 is used as
  computed and flagged, and `--strict` exits 1 on it. The flag asks you to check the denominator.
- Default denominators when `denominator_basis` is blank: EVIC for listed equity and corporate bonds; total
  equity + debt for business loans, unlisted equity, project finance and use of proceeds; the value at origination
  for real estate and vehicles.
- Data quality scores must be whole numbers 1 to 5, except for use of proceeds and securitizations, whose score is
  an outstanding-weighted average of the underlying assets (5.7, p. 103; 5.8, p. 127).
- A number such as `1,234` is refused as ambiguous rather than guessed; use `--decimal-comma` if commas are decimal
  separators. `1,234,567` and `1,234.5` are read as thousands-separated.
- Values of 10^24 or more, and files above 50 MB, are refused.
- Rows of instruments outside Part A are listed as not computed and left out of the coverage base.
- Text and Markdown round half-up for display (tCO2e to 2 decimals, scores to 2); totals are summed before
  rounding; JSON carries unrounded values.

## Data source, licence and attribution

- **Method.** PCAF Part A, Third Edition, linked above. PCAF publishes the standard as a free download; no licence
  statement appears in the PDF's text, and the website footer reads "© PCAF 2026" (checked 2026-09-24). This tool
  implements the published method and cites it by subchapter and page; it does not reproduce the standard's text.
  Three test fixtures reuse the numbers of worked examples printed in the standard (Tables 5.2-2 and 5.2-3,
  Box 6.1-6, Table 10.3-2) so the tool is checked against the standard's own results; the tests cite them.
- **Attribution.** Every report ends with the citation the standard asks for: "PCAF (2025). The Global GHG
  Accounting and Reporting Standard Part A: Financed Emissions. Third Edition." Financed emissions in the output
  are derived from your inputs by that method.
- **Emission factors: none bundled, none fetched.** PCAF's FAQ
  (https://carbonaccountingfinancials.com/en/contact#faqs, checked 2026-09-24): "Access to the PCAF Academy,
  PCAF’s web-based emission factor database and corresponding database methodologies is exclusively available to
  PCAF signatories and Accredited Partners." You supply emissions, estimated with your own factors or a source you
  are licensed to use.

## What it reads, what it sends

- **Reads:** the CSV file you name, or standard input. The MCP server reads the `csv_path` it is given, up to
  50 MB, and nothing else. No configuration files, no environment variables beyond `HOME` for a `~` in a path.
- **Sends:** nothing. There is no network code; a test runs the whole example with sockets disabled.
- **Writes:** only its output to standard output.

## Limits

- Emissions are inputs. The tool does not estimate emissions from activity data, revenue or floor area (options 2
  and 3 of the data quality tables); it attributes the figures you give.
- Use of proceeds structures and securitizations take the structure's or pool's financed emissions as input; the
  asset-level and loan-level attribution inside the structure (5.7, p. 101; Table 5.8-3) happens before this tool.
- One reporting date per file. PCAF asks for a fixed point in time aligned with the financial year (chapter 4,
  p. 28); the tool does not check dates.
- Not implemented: carbon credits, avoided emissions, fluctuation analysis, inflation adjustment, EVIC adjustment,
  projected lifetime emissions of new projects, weighted undrawn figures, and Parts B (facilitated emissions) and
  C (insurance-associated emissions).
- Double counting between sovereign, sub-sovereign and corporate positions is not removed. The standard asks for
  separate disclosure instead (5.9, pp. 147-148; 5.10, p. 158), which the per-class table provides.

## Development

```bash
python3 -m unittest discover -s tests -t .
```

Offline, standard library only. The tests include the worked examples printed in the standard and the example
portfolio end to end, over the command line and over the MCP protocol.

## Licence

MIT for the code. The PCAF Standard belongs to PCAF.

## What this is not

Not the PCAF Standard, not a PCAF product, and not endorsed by PCAF. Not assurance, not a disclosure, not advice.
A computed figure is the arithmetic of your inputs and the published method; whether the inputs are right, and
whether the method chosen fits each position (Figure 5-1 of the standard), is for the preparer and the auditor to
decide. A position that computes cleanly is not thereby verified.
