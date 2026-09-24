# tieout

**Find the source cell behind every number in a report or deck, and list every number that has none.**

<!-- mcp-name: io.github.Keremozdemirra/tieout -->

Consultants and auditors call it *tying out*: before a deliverable goes out, every figure in
it is checked against the workbook it came from. `tieout` does the mechanical part. It
reads a `.docx`, `.pptx`, `.md` or `.txt` file, extracts every number, and finds the cells in
your `.xlsx` and `.csv` sources that each number could have come from, allowing for rounding
(`61%` ties to 0.6134), percentages, scale (`€4.2bn` ties to 4,213,500,000; `3.1x` to a
ratio) and number formats (`1,234.5` and `1.234,5`). Every number it cannot tie is listed,
with the nearest source value if there is one.

## Why

- On 7 October 2025 the Associated Press reported that "Deloitte Australia will partially
  refund the 440,000 Australian dollars ($290,000) paid by the Australian government for a
  report that was littered with apparent AI-generated errors, including a fabricated quote
  from a federal court judgment and references to nonexistent academic research papers"
  (Rod McGuirk, AP, [via Yahoo News](https://www.yahoo.com/news/articles/deloitte-partially-refund-australian-government-070855665.html),
  checked 2026-09-24). Those errors were references and a quote, not figures: `tieout`
  checks figures, and with `--check-links` whether cited URLs and DOIs exist.
- The check is sold today. UpSlide's help centre (updated 12 May 2026) says its AI
  Consistency Check "scans your PowerPoint presentations to automatically detect calculation
  errors, data contradictions, and inconsistencies across slides"
  ([source](https://support.upslide.net/hc/en-us/articles/24884682152604-AI-Consistency-Check));
  DataSnipper's Financial Statement Suite is "built for financial statements tick-and-tie
  work" ([source](https://www.datasnipper.com/product/financial-statement-suite)). Both checked 2026-09-24.
- `tieout` is free, open source, runs locally, and compares the deliverable with the source
  workbook rather than with itself.

## Example

The `examples/` folder has a small model (`model.xlsx`), a German CSV export
(`marktdaten.csv`), an English board deck (`deck.pptx`) and a German report (`bericht.docx`)
with deliberate errors. Real output, 2026-09-24 (rows cut; the full run lists 33 numbers
plus 22 excluded ones):

```
$ tieout examples/deck.pptx examples/model.xlsx examples/marktdaten.csv
tieout 0.1.0 · deck.pptx against model.xlsx, marktdaten.csv · 2026-09-24
number format: en (number format: 18 numbers written the en way, 0 the de way)

#    status     number          where                           source                                                            context
5    tied       €4.2bn          slide 2                         model.xlsx › 'P&L'!C2 = 4,213,500,000 (scaled), 1 more cell       Revenue reached «€4.2bn»¹ in 2025, up 8.8% on 2024
10   untied     €612m           slide 2                         nearest model.xlsx › 'P&L'!C3 = 598,300,000 (-2.2%)               EBITDA of «€612m» at a margin of 14.2%
14   untied     62%             slide 2                         nearest model.xlsx › KPIs!C3 = 0.6149 (-0.8%)                     «62%» of customers renewed their contracts
16   ambiguous  14%             slide 2                         3 cells: model.xlsx › 'P&L'!B4 = 0.139642; model.xlsx › 'P&L'!C…  Margin held at around «14%» for three years
20   tied       61.5%           slide 2 notes                   model.xlsx › KPIs!C3 = 0.6149 (percentage)                        Renewal was «61.5%» before rounding. Target: 1,500 employees by…
21   untied     1,500           slide 2 notes                   no source value within ±10%                                       Renewal was 61.5% before rounding. Target: «1,500» employees by 2027.
36   untied     1,080           slide 3, table 1, row 5, col 3  nearest model.xlsx › 'P&L'!C5 = 1,050,000,000 (-2.8%)             Net debt · 2025: «1,080»
43   tied       2,105.2         slide 4, chart (Revenue, DACH)  model.xlsx › Segments!B2 = 2,105.2 (scaled)                       Revenue: «2,105.2»

55 numbers: 28 tied, 4 untied, 1 ambiguous, 22 excluded (10 year, 6 page or slide number, 2 date, 2 footnote marker, 1 label or reference (Scope 3, Figure 2, ISO 14001), 1 unit label ('000)).
--explain shows how each number was read and every excluded number with its reason.
note: marktdaten.csv: not valid UTF-8; read as Windows-1252
```

What that shows: the wrong EBITDA (`€612m`; the model says 598.3m), a double-rounding error
(0.6149 is 61.5% at one decimal, which the speaker notes tie to, but 61% at none, not 62%),
a stale net-debt figure in a table (`1,080`; the model now says 1,050), a target that is not
in the model (`1,500`), and a margin written as "around 14%" that fits three years. The
table cells tie because the slide title says `(€m)`; the chart values tie from the values
PowerPoint caches in the chart XML.

The German report, with `--check-links` (real output, 2026-09-24, rows cut):

```
$ tieout examples/bericht.docx examples/model.xlsx examples/marktdaten.csv --check-links
number format: de (number format: 0 numbers written the en way, 19 the de way)
5    tied       4,2 Mrd. €      paragraph 4                     model.xlsx › 'P&L'!C2 = 4,213,500,000 (scaled), 1 more cell       Der Umsatz stieg 2025 auf «4,2 Mrd. €» und lag damit 8,8 % über dem Vorjahr. Das…
13   tied       1.310           paragraph 6                     model.xlsx › KPIs!C5 = 1,310 (exact)                              Ende 2025 beschäftigte Atlas «1.310» Mitarbeiter (Vollzeitäquivalente). Die…
19   untied     15,3 %          paragraph 8                     nearest marktdaten.csv › row 2, col 4 = 0.148 (-3.3%)             …%). Der Marktanteil in Deutschland beträgt «15,3 %».²
43 numbers: 20 tied, 1 untied, 22 excluded (8 year, 4 footnote marker, 3 date, 2 list or section numbering, 2 page or slide number, 2 part of a link, e-mail address or DOI, 1 label or reference (Scope 3, Figure 2, ISO 14001)).

links (--check-links; HEAD, then GET; DOIs through the doi.org handle API):
  resolves          HTTP 200                            https://www.destatis.de/EN/Home/_node.html  [paragraph 11]
  resolves          HTTP 200                            https://ec.europa.eu/eurostat/web/main/home  [paragraph 12]
  does not resolve  DOI not registered at doi.org       doi:10.5555/atlas.2025.017  [paragraph 13]
```

The DOI in the report's reference list is made up; doi.org does not know it.

## Install

Command line, from PyPI (standard library only, no dependencies):

```bash
uvx tieout@0.1.0 deck.pptx model.xlsx
pipx run --spec tieout==0.1.0 tieout deck.pptx model.xlsx
```

Or without installing: `python3 tieout.py deck.pptx model.xlsx` from a checkout.

MCP server (Claude Code, or any MCP client on stdio):

```bash
claude mcp add tieout -- uvx tieout@0.1.0 mcp
```

Claude Code plugin (a skill: "tie out this deck", "check the numbers against the model"):

```
/plugin marketplace add Keremozdemirra/tieout
/plugin install tieout@tieout
```

The skill runs `tieout.py` with the `python3` on your `PATH`.

## Usage

```
tieout DELIVERABLE [SOURCE ...] [options]
```

| Option | What it does |
| --- | --- |
| `--json` / `--markdown` | Machine-readable output / a Markdown table. |
| `--explain` | How each number was read, the tie rule, every candidate cell, and every excluded number with its reason. |
| `--strict` | Exit codes for CI: 0 every number tied; 1 a number did not tie (or a link does not resolve); 2 a file could not be read, no source was given, or a link could not be checked. |
| `--min-digits N` | Ignore numbers written with fewer than N digits (default 1: check every number). |
| `--locale en\|de` | Number format of the deliverable (`1,234.5` or `1.234,5`); detected per document by default. |
| `--source-unit thousand\|million\|billion` | Also read source numbers without a unit label in these units. Repeatable. |
| `--check-links` | Request every URL and DOI in the deliverable. Off by default; see below. |
| `--timeout SECONDS` | Per-request timeout for `--check-links` (default 10). |

A file that cannot be read exits 2 even without `--strict`. With no source, `tieout` lists
the numbers it found (the `extract_numbers` view).

MCP tools:

- `tie_out(deliverable_path, source_paths, locale?, min_digits?, source_units?, include_excluded?, limit?)`:
  summary counts and the numbers, untied first, with candidate cells (file, sheet!cell or CSV
  row/column, value, labels, how it tied and the arithmetic).
- `extract_numbers(path, locale?, min_digits?, limit?)`: every number, how it was read, and
  every exclusion with its reason.

## What it reads

| Deliverable | Read |
| --- | --- |
| `.docx` | Paragraphs, tables (with row and column labels), footnotes, endnotes, text boxes, headers, footers, SmartArt, and chart values cached in the chart XML. Tracked deletions and field codes are skipped; PAGE and DATE field results are excluded. |
| `.pptx` | Slides in presentation order, tables, speaker notes, grouped shapes, SmartArt, hidden slides (marked), and chart values cached in the chart XML (`c:numCache`, what the chart displays; the embedded workbook is not opened). Slide-number and date fields are excluded. |
| `.md`, `.txt` | Line by line. Markdown tables by cell; code and link targets excluded. Form feeds (as `pdftotext` writes them) become page numbers. |
| PDF | Not read: the standard library cannot extract PDF text. Convert first, e.g. `pdftotext -layout report.pdf report.txt` (poppler-utils), or use the original .docx/.pptx. |

| Source | Read |
| --- | --- |
| `.xlsx`, `.xlsm` | Every numeric cell, including the saved value of formula cells, shared and inline strings, numbers stored as text; row and column labels. Cells with a date format are skipped. A formula without a saved value (files written by openpyxl and similar) is counted and reported, since there is no value to tie to. |
| `.csv`, `.tsv` | Delimiter and number format detected per file (`;` with `1.234,5` is read as German); UTF-8, UTF-16 or Windows-1252. |

## How numbers are read and tied

A number with *d* decimals and scale *s* ties to a source value *v* if *v / s* rounds to it
at *d* decimals; a percentage also ties to *v × 100*. Details:

- **Number format.** `1,234.5` and `1.234,5` read themselves; only a lone separator with
  three digits (`1,234`) is ambiguous, and the document's detected format decides it.
- **Scale.** Suffixes and words: k, m, mn, bn, tn, thousand, million, billion, trillion,
  Tsd., Mio., Mrd., Millionen, Milliarden, Billionen (German, 10^12), TEUR, and a unit in a
  table's row label, column header or caption (`Revenue (€m)`, `Key figures (€m)`). A source
  cell under a label such as `Revenue 2025 (€m)` counts in millions.
- **Signs.** `(1,234)`, `-`, `−` and `–` are negative. If only a source value of the other
  sign matches, the number ties with `sign differs` (costs are often shown in parentheses).
- **Units.** %, pp, bps, ‰, multiples (`3.1x`), currency symbols and ISO codes, ranges
  (`10–12%`, `€10–12m`), and qualifiers: "around 1,300" may round to the nearest hundred;
  "more than 60%" must be at least 60 and round to it.
- **Rounding.** Source values are taken at 15 significant digits, as Excel stores them
  ([Microsoft: "Number precision: 15 digits"](https://support.microsoft.com/en-us/office/excel-specifications-and-limits-1672b34d-7043-467e-8e27-269d656771c3),
  checked 2026-09-24). Both half-up rounding (what Excel's ROUND does: `=ROUND(2.15, 1)` is
  2.2, [Microsoft](https://support.microsoft.com/en-us/office/round-function-c018c5d8-40fb-4053-90b1-b3e7f61a213c),
  checked 2026-09-24) and half-even rounding are accepted; the output says which was needed.
- **Excluded, with the reason** (`--explain`): years, dates, times, page and slide numbers,
  footnote markers, list and section numbering, phone numbers, labels (Scope 3, Figure 2,
  ISO 14001), codes (CO2, Q3, FY25, 5G), ordinals, unit labels ('000), digits in links,
  e-mail addresses and DOIs, Markdown code, and numbers inside a credential or query string.

Thresholds that are this tool's own choices, not standards:

| Choice | Value |
| --- | --- |
| A number is `ambiguous` when different source values match, or more than this many cells hold the value | 5 cells |
| An untied number shows the nearest source value within | ±10% |
| A bare four-digit integer is read as a year between | 1900 and 2100 |
| Files and decompressed parts larger than this are refused | 200 MB |
| Default `--check-links` timeout per request | 10 seconds |

## What it reads, what it sends

- **Reads:** the files you name, nothing else. Office files are read as zip archives with
  size limits; XML with a document type declaration is refused.
- **Sends:** nothing, unless you pass `--check-links`. Then it requests each http(s) URL in
  the deliverable (HEAD, then GET if HEAD fails; at most 64 KB of body is read) with the
  user agent `tieout/0.1.0`, and asks doi.org's documented Proxy Server REST API
  (`https://doi.org/api/handles/<doi>`, [DOI Foundation](https://www.doi.org/the-identifier/resources/factsheets/doi-resolution-documentation),
  checked 2026-09-24) whether each DOI is registered. Only DOIs matching Crossref's pattern
  ([Crossref](https://www.crossref.org/blog/dois-and-matching-regular-expressions/), checked 2026-09-24)
  are sent. URLs with credentials, private or local addresses, or redirects to them are not
  requested. The MCP server never uses the network.
- **Prints:** credentials in URLs, query strings and `key=value` secrets are masked as `***`
  in every output format.
- **Data:** none bundled. The only third-party information in the output is the HTTP status
  or doi.org's registered/not registered answer.

A 403 or 429 means the site refused an automated request; it is reported as "could not
check", not as a broken link. A page that answers 200 with a "not found" message cannot be
told apart from a real page.

## What this is not

`tieout` finds cells whose values match the numbers in a deliverable. A tie means a matching
value exists, not that it is the right line, year or definition: read the labels it shows.
An untied number is not necessarily wrong; it may come from another source, be computed
(growth rates, sums, differences are not derived) or be a target. It does not check that a
reference says what it is cited for, only (with `--check-links`) that the link or DOI
exists. It is an aid to a reviewer, not an audit opinion.

## Licence

MIT.
