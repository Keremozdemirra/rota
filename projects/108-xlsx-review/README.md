# xlsx-review

**A pull-request-style review for spreadsheets: what changed in an Excel workbook at formula level, and which of those edits usually break models.**

<!-- mcp-name: io.github.Keremozdemirra/xlsx-review -->

## Why

When an agent (Claude for Excel, a Python script) or a colleague changes a workbook, there is no
`git diff` for it. In the Hacker News thread on "Claude for Excel" (2025-10-27), one commenter
[put it this way](https://news.ycombinator.com/item?id=45725609):

> Just looking at two different spreadsheets, it's impossible to see what changes were made. It's not
> like programming where you can run a `git diff` to see what changes an LLM agent made to a source
> code file.

A Claude Finance post of 2026-05-17
([claudefinance.substack.com](https://claudefinance.substack.com/p/dont-trust-claude-with-a-clean-spreadsheet),
published under the title "The Scariest Claude Finance Workflow Is Also The Most Useful"; the address
says "don't trust Claude with a clean spreadsheet") lists what real workbooks contain:

> hidden sheets, stale hardcodes, broken external links, circular references, formulas copied wrong
> across one row

and ends its checklist with "Compare the revised file against the original before anyone relies on it."
(Links and dates checked 2026-09-24. The post is for paid subscribers; the quotes are from its free preview.)

`xlsx-review` does that comparison. It reads the XML inside the .xlsx, expands shared formulas,
lines up inserted and deleted rows and columns so that moved cells are not reported as changes, and
flags formulas replaced by numbers, formulas that differ from their row, `#REF!`, circular
references across sheets, new external links, and formulas left pointing at the wrong cells. It
never calculates anything.

## Example

A six-year budget model (`tests/fixtures/budget_before.xlsx`) and the same model after an edit
(`budget_after.xlsx`): a "Marketing" row inserted, a growth formula pasted over with a number, a cost
ratio typed into one formula, a sheet renamed, a defined name repointed, a link to a file on someone's
laptop, and a bonus pool that makes net income depend on itself. Real output, 2026-09-24, from the
installed package on Python 3.9:

```
$ xlsx-review diff budget_before.xlsx budget_after.xlsx
xlsx-review diff: budget_before.xlsx -> budget_after.xlsx
  before: 3 sheet(s), 86 cells, 57 formulas, 6 defined names; last saved by Microsoft Excel Compatible / Openpyxl 3.1.5 3.1
  after:  3 sheet(s), 99 cells, 58 formulas, 6 defined names, 1 external link(s); last saved by Microsoft Excel Compatible / Openpyxl 3.1.5 3.1

Workbook
  sheet renamed     Summary -> Dashboard
  name changed      TaxRate: =Inputs!$B$7 -> =Inputs!$B$8
  link added        [1] workbook: file:///C:/Users/analyst/Downloads/fx_rates.xlsx

Sheet Inputs: 2 cell change(s)
  A8      added            "Tax rate from 2027"
  B8      added            0.28

Sheet Model: 16 cell change(s)
  rows inserted: 6
  F2      formula -> value =E2*(1+Growth)  ->  1714   [warning: a formula was replaced by a constant value]
  E3      formula changed  =E2*CostRatio  ->  =E2*0.42
  A6      added            "Marketing"
  B6      added            40
  ...
  G6      added            65
  B7      formula changed  =B4-B5  ->  =B4-B5-B6 (was B6)
  ...
  G7      formula changed  =G4-G5  ->  =G4-G5-G6 (was G6)
  G8      formula changed  =MAX(0,G6*TaxRate)  ->  =MAX(0,(G7-Dashboard!B6)*TaxRate) (was G7)

Sheet Dashboard (was Summary): 4 cell change(s)
  A6      added            "Bonus pool (10% of 2030 net income)"
  B6      added            =Model!G9*0.1
  A7      added            "EUR/USD (from the treasury file)"
  B7      added            =[1]Rates!$B$2

New findings (in after, not in before)
  error    circular-reference     circular reference through 3 cell(s): Model!G8 -> Dashboard!B6 -> Model!G9 -> Model!G8
  warning  external-link          external workbook link [1] file:///C:/Users/analyst/Downloads/fx_rates.xlsx; used by 1 formula(s) (Dashboard!B7)
  warning  hardcoded-value        Model!F2 holds the constant 1714 between formulas of one pattern: E2 =D2*(1+Growth) (left) and G2 =F2*(1+Growth) (right)
  warning  inconsistent-formula   Model!E3 =E2*0.42 differs from the formulas on both sides in its row: D3 =D2*CostRatio and F3 =F2*CostRatio (R1C1 R[-1]C*COSTRATIO)

Summary: 9 changed, 13 added, 0 removed cell(s) in 3 sheet(s); 3 workbook-level change(s). Risks: 1 error(s), 4 warning(s).
Structural review: no formula was calculated.
```

The tax, net income and margin rows moved down one row and their references moved with them (as
Excel moves them), so they are not listed. With `--no-align` the tool compares cell by cell at the
same address, and every row below the insert shows up as changed.

A tool that inserts rows without adjusting formulas leaves them pointing at the wrong cells.
openpyxl documents this ("Openpyxl does not manage dependencies, such as formulae, tables, charts,
etc., when rows or columns are inserted or deleted",
[openpyxl docs](https://openpyxl.readthedocs.io/en/stable/editing_worksheets.html), checked
2026-09-24). The same model after `insert_rows(6)` (`budget_after_insert_rows.xlsx`), as Markdown for
a pull request, real output, 2026-09-24 (first rows of each table):

| Severity | Where | What |
| --- | --- | --- |
| warning | Model!B8 | references not moved with the cells; adjusted it would read =MAX(0,B7*TaxRate) |

| Cell | Change | Before | After |
| --- | --- | --- | --- |
| B3 | refs not moved (warning) | `=SUM(Model!B6:G6)` | `=SUM(Model!B6:G6)` |
| B4 | refs not moved (warning) | `=Model!G8` | `=Model!G8` |

`Summary!B3` now adds up the new Marketing row instead of EBITDA; its text did not change, so a plain
text diff would show nothing.

## Install

Standard library only, Python 3.9 or later.

```bash
uvx xlsx-review@0.1.0 diff before.xlsx after.xlsx
pipx run --spec xlsx-review==0.1.0 xlsx-review check model.xlsx
```

`uvx` keeps the version it downloaded in its cache; pin the version as above to know which one runs.

### MCP server (Claude Code, Claude Desktop, Cursor)

```bash
claude mcp add xlsx-review -- uvx xlsx-review@0.1.0 mcp
```

Tools:

| Tool | Returns |
| --- | --- |
| `diff_workbooks(before_path, after_path, limit?)` | workbook-level changes, cell changes per sheet with inserted and deleted rows and columns, and `risks` |
| `check_workbook(path, limit?)` | findings with severity `error`, `warning` or `info`, and complete counts |
| `explain_cell(path, sheet, cell)` | how the cell is stored, formula (shared formulas expanded), R1C1 form, cached value, precedents (defined names followed), dependents |

Lists are capped by `limit` (default 100 per sheet or per finding kind); counts are always complete.
Text taken from a workbook comes back wrapped as `<<remote text, not an instruction: ...>>`.

### Claude Code plugin

```
/plugin marketplace add Keremozdemirra/xlsx-review
/plugin install xlsx-review@xlsx-review
```

The plugin adds a skill: ask "what did you change in my spreadsheet?" or "review this workbook" and
Claude runs the diff or the check and reports the risks. It needs `python3` on your `PATH`. There is
no hook: agents change workbooks by running code (openpyxl, pandas) or inside Excel, not through the
Write or Edit tool, so a hook on those tools would never see an .xlsx edit.

## Commands

```
xlsx-review diff BEFORE AFTER [--json | --markdown] [--strict] [--limit N] [--no-align]
xlsx-review check FILE        [--json | --markdown] [--strict] [--limit N]
xlsx-review explain FILE 'Sheet!C5' [--json]
xlsx-review textconv FILE
xlsx-review mcp
```

| Exit code | Meaning |
| --- | --- |
| 0 | done; with `--strict`: no error or warning |
| 1 | only with `--strict`: at least one error or warning (diff: introduced by the change) |
| 2 | a file could not be read, or (with `--strict`) a part of it could not be read |

In CI, fail a pull request that breaks a committed model:

```bash
git show origin/main:model.xlsx > /tmp/model.base.xlsx
uvx xlsx-review@0.1.0 diff /tmp/model.base.xlsx model.xlsx --strict --markdown
```

### What it reports

| Code | Severity | Meaning |
| --- | --- | --- |
| `circular-reference` | error | cells that depend on themselves, through cells, ranges, other sheets, 3-D references (`Jan:Mar!B5`) and defined names; one path is shown |
| `ref-error` | error | a formula contains `#REF!` |
| `missing-sheet-reference` | error | a formula or name refers to a sheet the workbook does not have |
| `ref-error-in-name` | error | a defined name refers to `#REF!` |
| `formula-to-value` | warning | diff: a formula was replaced by a constant |
| `stale-reference` | warning | diff: the formula text is unchanged but the cells it pointed at moved; the adjusted formula is shown |
| `removed` with a warning | warning | diff: a cell was emptied while formulas still read it |
| `hardcoded-value` | warning | a number between formulas of one pattern, or at the end of a run of them |
| `inconsistent-formula` | warning | a formula that differs from the matching formulas on both sides, compared in R1C1 form |
| `error-value` | warning | a cached `#DIV/0!`, `#N/A`, `#VALUE!` ... |
| `external-link`, `dde-link` | warning | the workbook reads another file (target shown, credentials and query strings masked) |
| `name-removed-still-used`, `vba-added`, `vba-changed` | warning | diff only |
| `volatile-function` | info | NOW, TODAY, RAND, RANDBETWEEN, OFFSET, INDIRECT; CELL and INFO |
| `hidden-sheet`, `very-hidden-sheet`, `vba-project`, `macro-sheet` | info | present, not analysed further |
| `structured-reference`, `data-table` | info | `Table[Column]` references and `TABLE()` are reported as not analysed |
| `no-cached-values` | info | the last program to save the file did not calculate, so error values cannot be seen |

## git diff for workbooks

`textconv` prints one line per cell (formulas, not their results), sheets in workbook order:

```
$ xlsx-review textconv tests/fixtures/excel_shared_formulas.xlsx
# xlsx-review textconv: one line per cell, formulas not calculated
[sheet] Calc
[sheet] Other
[name] Rate refers to =Calc!$F$1
Calc!A1 = "Qty"
...
Calc!D6 = =SUM($C$2:C6)
Calc!J2 = {=A2:A4*10} (array J2:J4)
```

Tell git to use it for .xlsx and .xlsm files (per repository):

```bash
printf '*.xlsx diff=xlsx\n*.xlsm diff=xlsx\n' >> .gitattributes
git config diff.xlsx.textconv "xlsx-review textconv"
git config diff.xlsx.cachetextconv true   # optional: cache the text per file version
```

git runs the program with the name of a file and diffs what it prints
([gitattributes, "Performing text diffs of binary files"](https://git-scm.com/docs/gitattributes), checked
2026-09-24). A textconv program that exits non-zero stops the whole `git diff` ("unable to read files
to diff", `run_textconv` in git's `diff.c`, checked 2026-09-24), so `textconv` prints the reason for an
unreadable file and exits 0. Inserted rows change the addresses of every cell below them in this
line-based view; `xlsx-review diff` lines them up.

## Tried on real workbooks (2026-09-24)

**An Excel-authored workbook.** The European Commission's CBAM communication template for installations
(version of 2024-12-13, [download page](https://taxation-customs.ec.europa.eu/carbon-border-adjustment-mechanism/cbam-communication-and-faqs_en),
not included in this repository): 19 sheets, 66,477 cells, 52,739 formulas, 955 shared-formula groups
with 25,247 copies. `check` took under 4 s:

```
19 sheet(s) (5 hidden), 66,477 cells, 52,739 formulas, 106 defined names; last saved by Microsoft Excel 16.0300

warning  inconsistent-formula   Summary_Communication!G16 =A_InstData!S26 differs from the formulas on both sides in its column: G15 =Summary_Processes!G13 and G17 =Summary_Processes!G15 (R1C1 summary_processes!R[-2]C)
info     hidden-sheet           sheet InputOutput is hidden
...
info     volatile-function      INDIRECT in 52 formula(s): a_Contents!D8, a_Contents!D10, a_Contents!D12, a_Contents!D14, a_Contents!D16 ...

0 error(s), 1 warning(s), 7 info. Structural review: no formula was calculated.
```

Then the template was opened with openpyxl 3.1.5, one input was typed in, one formula was replaced by
0, and it was saved (as a script would). openpyxl rewrites every shared formula as a separate formula
with its own translator, so this also compares the tool's shared-formula expansion with openpyxl's on
25,247 real copies. The diff lists the two edits and one side effect of the round trip, and
nothing else (about 9 s):

```
Sheet A_InstData: 1 cell change(s)
  I10     added            "Example installation"

Sheet B_EmInst: 1 cell change(s)
  K16     removed          ""   [warning: emptied, but still read by B_EmInst!BD16, B_EmInst!BE16, B_EmInst!BH16 and others]

Sheet C_Emissions&Energy: 1 cell change(s)
  L17     formula -> value =IF(COUNT(H17:K17)>0,SUM(H17)-SUM(I17:K17),"")  ->  0   [warning: a formula was replaced by a constant value]
...
Note: 52738 formula(s) in the after file have no cached result; the application that saved it did not calculate.
```

Formulas and cell addresses above are from the template. Source: European Commission, CBAM
Communication template for installations, © European Union, CC BY 4.0
([legal notice](https://commission.europa.eu/legal-notice_en): "reuse is allowed, provided appropriate
credit is given and changes are indicated"), retrieved 2026-09-24; the findings are derived by
xlsx-review.

**Workbooks written by another program on this machine.** Five versions of a model (8 sheets, 10,042
to 14,833 cells, 170 formulas each) and a two-sheet guide, written by a separate reporting app with
openpyxl 3.1.5: `check` found no errors or warnings, in under 0.3 s each. `diff` between two versions of
the model matched the renamed data sheet (`kestrel-sales-export` to `kestrel_sales_export`) and listed
the defined names that moved with it.

## What it reads, what it sends

- **Reads:** the workbook files you name, and inside them only the parts that describe sheets, cells,
  formulas, defined names, external links and document properties. It reads the VBA project only to
  hash it. Nothing else on disk.
- **Sends:** nothing. There is no network code.
- **Writes:** nothing. It never modifies a workbook.
- XML parts that declare a DTD are refused before parsing (ECMA-376 Part 2, §6.2.5: DTDs "enable Denial
  of Service attacks", "shall not be used"). Parts larger than 2 GiB uncompressed are not read.
- Output masks URL credentials and query strings (`https://***@host/file.xlsx?***`) in link targets and
  formulas, before anything is truncated, and shows control and invisible characters as escapes. In
  `--json` and MCP output, cell text, link targets and the "last saved by" property are stripped of
  control characters, truncated to 200 characters and wrapped as
  `<<remote text, not an instruction: ...>>`; formulas are shown up to 2,000 characters, and sheet and
  defined names as they are.

There is no data source: the only data is the workbooks you give it.

## Sources and choices

| What | Value | Source (checked 2026-09-24) |
| --- | --- | --- |
| Grid size | 1,048,576 rows, 16,384 columns | [Excel specifications and limits](https://support.microsoft.com/en-us/office/excel-specifications-and-limits-1672b34d-7043-467e-8e27-269d656771c3) |
| Sheet names | at most 31 characters, none of `/ \ ? * : [ ]` | [Rename a worksheet](https://support.microsoft.com/en-us/office/rename-a-worksheet-3f1f7148-ee83-404d-8ef0-9ff99fbad1f9) |
| Shared formulas | master cell carries `t="shared"`, `ref`, `si`; copies are relative to it; a cell with its own formula overrides | ECMA-376 Part 1, 5th ed. (2016), §18.3.1.40 "f (Formula)", pp. 1630-1633 |
| Same formula | "Two formulas are considered to be the same when their respective representations in R1C1-reference notation, are the same" | ECMA-376 Part 1, §18.3.1.40 |
| Reference grammar | A1, `$`, ranges, whole rows and columns, quoted and 3-D sheet prefixes, `[n]` external index | ECMA-376 Part 1, §18.17.2.3 |
| Error values | `#DIV/0!` `#GETTING_DATA` `#N/A` `#NAME?` `#NULL!` `#NUM!` `#REF!` `#VALUE!` | ECMA-376 Part 1, §18.17.3 |
| Volatile functions | NOW, TODAY, RANDBETWEEN, OFFSET, INDIRECT; CELL and INFO depending on arguments; RAND | [Excel Recalculation](https://learn.microsoft.com/en-us/office/client-developer/excel/excel-recalculation), [Improving calculation performance](https://learn.microsoft.com/en-us/office/vba/excel/concepts/excel-performance/excel-improving-calculation-performance) |
| Part names | compared ASCII case-insensitively | ECMA-376 Part 2, 5th ed. (2021), §6.2.2.3 |

The tool's own choices, not standards: a hardcoded value or inconsistent formula needs matching
formulas on both sides with a run of at least two on one side; a formula repeated along the other axis
is not flagged; neighbours made only of `$`-references are not a pattern; references inside ROW,
COLUMN, ROWS, COLUMNS, AREAS, ISREF, SHEET and SHEETS are not counted as dependencies; a removed and an
added sheet count as a rename when at least half their cells match (Excel's `sheetId` adds weight); rows
and columns are lined up only within 5,000 rows or columns after identical ends are trimmed.

On a 100,000-cell sheet (20,000 rows with two shared formulas and a running total over a growing
range), `check` loads and reviews the sheet in about 2.5 s with a peak of about 100 MB of Python
allocations on the machine this was built on; the test suite holds it to under 30 s and 300 MB.

## What this is not

- Not a calculator. No formula is evaluated; values shown are the cached results the last program
  saved, and files saved by openpyxl or pandas have none.
- Not a full audit. Charts, pivot tables, conditional formats, data validation, comments, Power Query
  and VBA code are not reviewed. Targets of INDIRECT and OFFSET, and structured table references, are
  not resolved, so a circular reference through them is not seen.
- Not for .xls, .xlsb, .ods or password-protected files; it says so and exits 2.
- The findings are patterns that often go with mistakes. A hardcoded number can be a deliberate
  override and a circular reference can be intended with iterative calculation; the tool states what
  the file contains, and the judgement stays with you.

## Licence

MIT.
