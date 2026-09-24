# eiopa-rfr

<!-- mcp-name: io.github.Keremozdemirra/eiopa-rfr -->

**EIOPA's Solvency II risk-free interest rate term structures, read as published, from the command line or as an MCP server.**

Every month EIOPA publishes the risk-free interest rate (RFR) term structures
that insurers and reinsurers use to value technical provisions under Solvency II:
a zip file of Excel workbooks with a spot curve per currency for maturities of 1
to 150 years, without and with the volatility adjustment (VA), and the parameters
behind each curve. To answer "what was the EUR 10-year rate at end-August, with
and without VA, and how much did it move since July?" you find the right zip on
EIOPA's page (its links carry random ids), open two workbooks and read the right
cells.

`eiopa-rfr` does that. It finds the releases on EIOPA's pages, downloads a release
once into a local cache, and returns the values as they appear in the workbook,
together with the cell they came from, the source file and the attribution line
EIOPA's legal notice asks for.

## Example

Real output, 2026-09-24. The newest release is August 2026, which EIOPA's page
shows as published on 2026-09-03.

```
$ eiopa-rfr rate EUR 10
EUR (Euro) 10-year spot rate, reference date 2026-08-31
  without VA  3.268 %    0.03268    RFR_spot_no_VA!C20
  with VA     3.408 %    0.03408    RFR_spot_with_VA!C20
Curve EUR_31_08_2026_SWP_LLP_20_EXT_40_UFR_3.30
  parameter    no VA       with VA
  Coupon_freq  1           1
  LLP          20 y        20 y
  Convergence  40 y        40 y
  UFR          3.3 %       3.3 %
  alpha        0.074103    0.087579
  CRA          10 bp       10 bp
  VA           -           14 bp
Date: 'latest' resolved to reference date 2026-08-31: newest release on EIOPA's pages (list fetched 2026-09-24T09:43:22Z)
Source: EIOPA - European Insurance and Occupational Pensions Authority, https://eiopa.europa.eu/, risk-free interest rate term structures, EIOPA_RFR_20260831.zip, retrieved 2026-09-24
```

```
$ eiopa-rfr compare EUR 10 2026-07 2026-08
EUR (Euro) 10-year spot rate: 2026-07-31 -> 2026-08-31
  without VA  3.159 % -> 3.268 %   change +10.9 bp
      alpha: 0.066628 -> 0.074103
  with VA     3.289 % -> 3.408 %   change +11.9 bp
      alpha: 0.082524 -> 0.087579
      va_bp: 13 -> 14
Change derived by eiopa-rfr: rate at the second date minus rate at the first.
Dates: '2026-07' resolved to reference date 2026-07-31: EIOPA dates each monthly release at the last calendar day of the month; '2026-08' resolved to reference date 2026-08-31: EIOPA dates each monthly release at the last calendar day of the month
Source: EIOPA - European Insurance and Occupational Pensions Authority, https://eiopa.europa.eu/, risk-free interest rate term structures, EIOPA_RFR_20260731.zip, retrieved 2026-09-24
Source: EIOPA - European Insurance and Occupational Pensions Authority, https://eiopa.europa.eu/, risk-free interest rate term structures, EIOPA_RFR_20260831.zip, retrieved 2026-09-24
This output has been drafted using material downloaded from EIOPA website. EIOPA does not endorse this publication and in no way is liable for copyright or other intellectual property rights infringements nor for any damages caused to third-parties through this publication.
```

```
$ eiopa-rfr rate USD 30 --date 2026-08
US (United States) 30-year spot rate, reference date 2026-08-31
  without VA  4.583 %    0.04583    RFR_spot_no_VA!AQ40
  with VA     4.913 %    0.04913    RFR_spot_with_VA!AQ40
Curve US_31_08_2026_OIS_LLP_30_EXT_40_UFR_3.30
  parameter    no VA       with VA
  Coupon_freq  1           1
  LLP          30 y        30 y
  Convergence  40 y        40 y
  UFR          3.3 %       3.3 %
  alpha        0.106018    0.116203
  CRA          0 bp        0 bp
  VA           -           33 bp
Date: '2026-08' resolved to reference date 2026-08-31: EIOPA dates each monthly release at the last calendar day of the month
Source: EIOPA - European Insurance and Occupational Pensions Authority, https://eiopa.europa.eu/, risk-free interest rate term structures, EIOPA_RFR_20260831.zip, retrieved 2026-09-24
```

```
$ eiopa-rfr params EUR --date 2026-08-31
EUR (Euro) curve parameters, reference date 2026-08-31, EUR_31_08_2026_SWP_LLP_20_EXT_40_UFR_3.30
  parameter    no VA       with VA
  Coupon_freq  1           1
  LLP          20 y        20 y
  Convergence  40 y        40 y
  UFR          3.3 %       3.3 %
  alpha        0.074103    0.087579
  CRA          10 bp       10 bp
  VA           -           14 bp
Date: reference date 2026-08-31 as requested
Source: EIOPA - European Insurance and Occupational Pensions Authority, https://eiopa.europa.eu/, risk-free interest rate term structures, EIOPA_RFR_20260831.zip, retrieved 2026-09-24
```

The same question through the MCP server, `get_rate` with
`{"currency": "EUR", "maturity_years": 10}`: an excerpt of the real
`structuredContent`, 2026-09-24.

```json
{
 "maturity_years": 10,
 "reference_date": "2026-08-31",
 "date": {"requested": "latest", "reference_date": "2026-08-31",
          "note": "'latest' resolved to reference date 2026-08-31: newest release on EIOPA's pages (list fetched 2026-09-24T09:44:15Z)"},
 "curve": {"code": "EUR", "name": "Euro", "curve_id": "EUR_31_08_2026_SWP_LLP_20_EXT_40_UFR_3.30", "instrument": "SWP"},
 "no_va": {"rate": 0.03268, "rate_percent": 3.268, "cell": "RFR_spot_no_VA!C20", "beyond_last_liquid_point": false},
 "with_va": {"rate": 0.03408, "rate_percent": 3.408, "cell": "RFR_spot_with_VA!C20", "beyond_last_liquid_point": false,
             "parameters": {"coupon_freq": 1, "llp_years": 20, "convergence_years": 40, "ufr_percent": 3.3,
                            "alpha": 0.087579, "cra_bp": 10, "va_bp": 14}},
 "source": {"file": "EIOPA_RFR_20260831.zip", "workbook": "EIOPA_RFR_20260831_Term_Structures.xlsx",
            "url": "https://www.eiopa.europa.eu/document/download/d491908e-9c02-427a-90ec-9dbd7b881ffe_en?filename=EIOPA_RFR_20260831.zip",
            "retrieved": "2026-09-24", "page_date": "2026-09-03",
            "sha256": "af7bd7a5228fca507f9995287adb6584caee2e681236321582f823faa81f8569"},
 "attribution": "Source: EIOPA - European Insurance and Occupational Pensions Authority, https://eiopa.europa.eu/, risk-free interest rate term structures, EIOPA_RFR_20260831.zip, retrieved 2026-09-24"
}
```

## Install

Python 3.9 or later, standard library only, no dependencies.

**MCP server** (Claude Code):

```bash
claude mcp add eiopa-rfr -- uvx eiopa-rfr mcp
```

Other MCP clients: command `uvx`, arguments `eiopa-rfr mcp`, transport stdio.

**Command line:**

```bash
uvx eiopa-rfr rate EUR 10
pipx run eiopa-rfr releases
pip install eiopa-rfr          # then: eiopa-rfr ...
python3 eiopa_rfr.py rate EUR 10   # from a checkout: the module is one file
```

`uvx` and `pipx run` keep a cached copy of the package; they do not fetch a newer
eiopa-rfr every time they start.

## Tools and commands

The MCP tools and the commands call the same functions.

| MCP tool | Command | Returns |
| --- | --- | --- |
| `list_releases(refresh)` | `eiopa-rfr releases [--refresh]` | Every monthly release on EIOPA's pages: reference date, EIOPA's file name, the date the page shows, size, whether it is cached. |
| `get_rate(currency, maturity_years, date, variant)` | `eiopa-rfr rate EUR 10 [--date D] [--variant V]` | One maturity: rate as decimal and percent, the workbook cell, whether the maturity is beyond the last liquid point, the parameters. Default variant `both`. |
| `get_curve(currency, date, variant)` | `eiopa-rfr curve EUR [--date D] [--variant V]` | Maturities 1 to 150 with the parameters. Default variant `no_va`. |
| `get_parameters(currency, date)` | `eiopa-rfr params EUR [--date D]` | The parameters without and with VA; `all` lists every curve in the release. |
| `compare(currency, maturity_years, date_a, date_b, variant)` | `eiopa-rfr compare EUR 10 2026-07 2026-08` | Both values, the change in decimal and basis points (b minus a), the parameters that differ. Default variant `both`. |
| | `eiopa-rfr import FILE.zip` | Adds a release zip you downloaded yourself to the cache. |
| | `eiopa-rfr cache` | Where the cache is and which releases it holds. |
| | `eiopa-rfr mcp` | Runs the MCP server on stdin/stdout (JSON-RPC 2.0, protocol 2025-06-18). |

- **currency**: an ISO 4217 code (EUR, USD, GBP, CHF, JPY, SEK, ...) or the
  country code of one of EIOPA's columns (DE, FR, IT, UK, LI, ...), whose curve
  with VA can differ from the currency curve. The United Kingdom column is `GB`
  in releases up to 2023 and `UK` in 2026; either code, and GBP, finds it.
  BGN and HRK are not mapped because the Bulgarian and Croatian columns carry
  the euro curve in current releases; ask for `BG` or `HR`.
- **date**: `latest` (default), `YYYY-MM`, `YYYY-MM-DD` or `YYYYMMDD`. EIOPA dates
  each release at the last calendar day of the month, so any day of a month
  resolves to that month's release. Every answer states the reference date used.
- **maturity**: whole years from 1 to 150. Nothing is interpolated.
- **variant**: `no_va`, `with_va` or `both`.
- `--json` prints the result as JSON (the MCP `structuredContent`); `--offline`
  uses the cache only.

Exit codes: `0` answered; `1` the question cannot be answered from what EIOPA
published (currency not in the release, month not published, maturity out of
range, date not understood); `2` EIOPA could not be reached, refused the request,
or a file could not be read, and command-line usage errors.

## What the numbers are

Values come from the sheets `RFR_spot_no_VA` and `RFR_spot_with_VA` of the
release's `*_Term_Structures.xlsx` workbook. Rows are found by their labels,
not by position. Units, checked 2026-09-24 against EIOPA's
[RFR Technical Documentation EIOPA-BoS-25-599](https://www.eiopa.europa.eu/document/download/f7fca58f-4d24-4441-ac60-de562bf26d77_en?filename=EIOPA-BoS-25-599%20-%20RFR%20Technical%20Documentation.pdf)
(December 2025, "TD" below):

| Output key | EIOPA label | Unit | Source |
| --- | --- | --- | --- |
| `rate` | rows 1 to 150 | annual zero-coupon spot rate, decimal (0.03268 = 3.268 %), integer maturities 1 to 150 years | workbook Main_Menu "(annual zero-coupon spot rates)"; TD 9.5.1, 9.1.6 |
| `rate_percent` | | the same rate times 100 | |
| `coupon_freq` | Coupon_freq | coupon payments per year of the input instruments; 0 on curves built from government bond zero-coupon rates | TD Table 2 "SWP FREQ" |
| `llp_years` | LLP | last liquid point, years | TD 9.2.1 |
| `convergence_years` | Convergence | years from the last liquid point to the convergence point | TD 9.4.1 |
| `ufr_percent` | UFR | ultimate forward rate, percent | TD 9.7.3 ("4.2%") |
| `alpha` | alpha | Smith-Wilson convergence speed, six decimals, lower bound 0.05 | TD 9.4.2 |
| `cra_bp` | CRA | credit risk adjustment, whole basis points | TD 7.3.14 |
| `va_bp` | VA | volatility adjustment, whole basis points; empty without VA; the text `n/a` where EIOPA publishes none (Colombia and Taiwan in August 2026) | TD 13.1.5, 15.1.2 |

**Precision.** The workbook XML stores numbers with 17 digits
(`0.032680000000000001`). eiopa-rfr shows them with at most 15 significant
digits, which is what Excel displays. For every rate in the six releases checked
(reference dates 2015-12-31, 2019-12-31, 2022-12-31, 2023-01-31, 2026-07-31,
2026-08-31) that is exactly the stored value; all have at most five decimals. In
the parameter rows it removes binary noise: the August 2026 file stores the Czech
VA as `2.9999999999999996` and the euro alpha as `0.074103000000000016`; eiopa-rfr
reports 3 and 0.074103, as Excel shows them.

**Arithmetic.** The only arithmetic is `rate_percent` (times 100) and, in
`compare`, the change (b minus a, and times 10,000 for basis points), done in
exact decimal arithmetic. The change is labelled as derived and carries the
disclaimer EIOPA's legal notice requires for transformed material. Rates beyond
the last liquid point are EIOPA's Smith-Wilson extrapolation, as published.

**Curve identifiers** such as `EUR_31_08_2026_SWP_LLP_20_EXT_40_UFR_3.30` are
EIOPA's. `instrument` is the code inside them, passed on as written (SWP, OIS,
GOV, GVT, PEE).

### Not read

- The shocked curves (`Spot_NO_VA_shock_UP` and the three others) and the `VA`
  sheet: they are Excel formulas over the spot sheets. In the 2026 files their
  stored results are `#N/A` or 0.01 (Excel recalculates on opening), so reading
  them would mean computing them.
- The `Shocks` sheet (shock factors of the interest rate risk submodule) and the
  hidden `Parameters` sheet (a country-to-currency table that still lists BG with
  BGN and HR with HRK).
- The other three workbooks in each zip: `PD_CoD` (fundamental spreads,
  probabilities of default, cost of downgrade), `Qb_SW` (Smith-Wilson calibration
  vectors) and `VA_portfolios` (representative portfolios).
- Files that are not monthly releases: the 2020 extraordinary calculations,
  dual-run and parallel-calculation files, financial-stability (FSR) shifted
  curves, documentation.

## Data source, licence, attribution

- **Releases**: EIOPA's RFR page,
  https://www.eiopa.europa.eu/tools-and-data/risk-free-interest-rate-term-structures_en
  (releases from 2022-12-31), and the previous-releases page it links to
  (2015-12-31 to 2022-11-30). Download links carry random ids, so they are always
  read from the pages, never built. If the RFR page yields no release, the RSS
  feed the page offers "to get the latest monthly technical files in a structured
  way" is read instead: https://www.eiopa.europa.eu/feed/53/rss_en. On 2026-09-24
  the pages listed 129 monthly releases, 2015-12-31 to 2026-08-31, with no month
  missing. The page gives the remaining 2026 publication dates as 5 October,
  5 November and 3 December.
- **Terms**: EIOPA legal notice, https://www.eiopa.europa.eu/legal-notice_en
  (checked 2026-09-24): "Reproduction of information and documents from the
  Authority's website is authorised without prior permission, provided that the
  user acknowledges the Authority as the source: "Source: EIOPA - European
  Insurance and Occupational Pensions Authority, https://eiopa.europa.eu/ "."
  Every result carries an `attribution` line in that wording, with the file and
  the date it was retrieved. Quote it with the values.
- The notice adds that material transformed and republished must carry a
  twofold disclaimer ("This document has been drafted using material downloaded
  from EIOPA website"; "EIOPA does not endorse this publication and in no way is
  liable for copyright or other intellectual property rights infringements nor for
  any damages caused to third-parties through this publication"), which `compare`
  output includes, and that "where the original material is incorporated in
  documents that are sold (regardless of the medium), the publisher must inform
  buyers that it may be obtained free of charge through EIOPA website."
- EIOPA's separate "License Agreement - Risk Free Interest Rate Coding" covers
  its RFR source-code package, which eiopa-rfr neither downloads nor uses.
- The RFR page says EIOPA may "amend and/or republish, from time to time, its
  technical information after it has been published". When a fresh release list
  shows a new link for a month already in the cache, eiopa-rfr downloads that
  month again on its next use, and says so if the file differs.

eiopa-rfr itself is MIT-licensed. The tests use trimmed copies of real EIOPA
files; `tests/fixtures/SOURCES.md` gives their URLs, SHA-256 sums and how they
were cut.

## What it reads and what it sends

- **Sends**: HTTPS GET requests to `www.eiopa.europa.eu` only: the RFR page and
  the previous-releases page (the list is reused for 6 hours unless you refresh
  it), the RSS feed only when the RFR page lists nothing, and the zip files those
  pages link to. Redirects are followed only on that host. Nothing you type is
  sent: currency, date and maturity are only used to look things up locally. The
  user agent is `eiopa-rfr/<version> (+https://github.com/Keremozdemirra/eiopa-rfr)`.
- **Writes**: its cache directory, holding the release zips as downloaded, the
  parsed curves as JSON and the release list: `~/.cache/eiopa-rfr` on Linux
  (`$XDG_CACHE_HOME` respected), `~/Library/Caches/eiopa-rfr` on macOS,
  `%LOCALAPPDATA%\eiopa-rfr\Cache` on Windows, or wherever `EIOPA_RFR_CACHE`
  points. A zip that does not parse is not written.
- **Reads**: the cache, and a file you pass to `import`. No configuration files
  and no credentials; EIOPA's files need none.
- `EIOPA_RFR_OFFLINE=1` or `--offline`: nothing is fetched; `latest` then means
  the newest cached release, and the answer says so.
- Text from EIOPA's pages and files that reaches the output (file names, column
  names, curve identifiers) is reduced to letters, digits and plain punctuation
  and cut to a fixed length.

Choices of this tool, not EIOPA's: the 6-hour reuse of the release list; one
retry after HTTP 429 or 503, waiting what `Retry-After` asks up to 10 seconds
(EIOPA's CDN answered a burst of downloads with 429 and `retry-after: 10.000` on
2026-09-24, and kept refusing for several minutes); no download over 64 MB and no
workbook part over 32 MB (a release is 3 to 5 MB); timeouts of 30 seconds for
pages and 60 seconds for zips per network operation.

## Tests

```bash
python3 -m unittest discover -s tests -t .
```

120 tests, offline, on trimmed copies of real EIOPA files: page parsing with
random-id links and the files that are not releases (dual runs, parallel
calculations, FSR curves, the 2020 extraordinary updates), the older workbook
layout, network down, DNS failure, timeouts, 404, 429 with `Retry-After`,
truncated and corrupted zips, a web page served instead of a zip, a renamed sheet,
a renamed row label, moved rows, missing curve identifiers, entity declarations,
oversized parts, unknown currencies, unpublished months, offline mode, a
republished release, and an MCP session over stdin/stdout with a real server
process.

## What this is not

- **Not the legal act.** Article 77e(2) and (3) of Directive 2009/138/EC
  (consolidated text of 2024-01-09, checked 2026-09-24) let the Commission adopt
  EIOPA's technical information in implementing acts; where it has, undertakings
  shall use the information adopted there. eiopa-rfr reads EIOPA's monthly files,
  not those implementing regulations.
- **Not a curve engine.** No interpolation between maturities, no Smith-Wilson,
  no re-extrapolation, no shocked curves, no matching adjustment.
- **Not advice.** The values are information published by EIOPA. What an
  undertaking reports, and with which curve, remains its own responsibility.
- **Not EIOPA.** eiopa-rfr is not affiliated with or endorsed by EIOPA.
