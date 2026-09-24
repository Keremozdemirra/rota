---
name: tieout
description: Tie out the numbers in a report or deck against the source workbook. Use when the user asks to tie out a deck or report, check the numbers against the model or spreadsheet, verify the figures in a .docx, .pptx, .md or .txt before it goes out, or find numbers that do not appear in a source .xlsx or .csv.
---

# tieout

`tieout.py` in this plugin reads a deliverable (.docx paragraphs, tables, footnotes, text
boxes, headers and footers; .pptx slides, tables, speaker notes, SmartArt and cached chart
values; .md; .txt), extracts every number, and finds the source cells (.xlsx cached values,
.csv) each one could have come from, allowing for rounding, percentages and scale. It reads
local files only and sends nothing.

## Tie out a deliverable

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/tieout.py" --json deck.pptx model.xlsx
python3 "${CLAUDE_PLUGIN_ROOT}/tieout.py" --json report.docx model.xlsx data.csv
```

Useful options: `--locale de` if the number format is detected wrongly (see
`number_format` in the output), `--source-unit million` when the model holds values in
millions without saying so in a row label or column header, `--min-digits 2` to skip
single-digit numbers, `--explain` for how each number was read and why numbers were excluded.

PDF is not read. Ask the user for the .docx/.pptx, or convert with
`pdftotext -layout report.pdf report.txt` if poppler is installed.

## Reporting back

- Lead with `untied` numbers: quote `written`, `where` and `context`, and the `nearest`
  source value if there is one (for example "62% on slide 2 does not tie; the model has
  0.6149, which rounds to 61%"). Then `ambiguous` numbers with their candidate cells.
- "Untied" means no source cell matches, not that the number is wrong. It may come from
  another source, be a calculation, or be a forward-looking target. Say what you found and
  let the user decide.
- "Tied" means a cell with a matching value exists. Check the candidate's `label` (row and
  column) against the sentence: a 2025 figure that ties to a 2024 column is worth a mention.
- `sign_differs` usually reflects a presentation convention (costs shown in parentheses);
  mention it once, not as an error.
- Mention the `warnings` (for example formula cells without saved values: the workbook
  must be opened and saved in Excel or LibreOffice first) and any `errors`.
- `--markdown` gives a table the user can paste into a review note if they ask for one.

## Links, only when asked

`--check-links` requests every URL and DOI in the deliverable (HEAD, then GET; DOIs through
doi.org). It uses the network, so run it only when the user asks to check the references.
