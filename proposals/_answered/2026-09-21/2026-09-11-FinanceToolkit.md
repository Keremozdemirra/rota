# Proposal: JerBouma/FinanceToolkit

- **Repo:** https://github.com/JerBouma/FinanceToolkit
- **Source:** agent-vitals census, data/servers.json (2026-09-10 snapshot)
- **Stars:** 5,312 · **Forks:** 616 · **Open issues:** 8
- **Licence:** MIT (SPDX-identified)
- **Language:** Python
- **Created:** 2019-04-08 (2,712 days) · **Last push:** 2026-09-08 (2 days before census)
- **Archived:** no. **Fork:** no. First seen in this census 2026-09-04.

## What it claims to do (from its description and topics only)

The description is three words, "Transparent and Efficient Financial
Analysis", and the twelve topics carry the rest: `financial-statements`,
`fundamental-analysis`, `fundamentals`, `factor-analysis`,
`performance-analysis`, `market-data`, `equities`, and, added at some point,
`mcp-server`. Read together, that is a library that takes company
financial statements and market data and computes ratios, factor exposures
and performance figures from them, now also exposed as an MCP server. The
word "transparent" in the description is the interesting claim: it suggests
the formulas are visible rather than returned from a black box, which is
the property `source-check` demands of any published figure.

Where the statements come from is unstated in the metadata. A seven-year
Python finance library almost certainly reads from a data vendor, and
which one, at what price, decides most of the fit.

Nothing here has been cloned, read or run. Everything above is metadata.

## Which derived gap it fills

`vetting.yaml` `domains` line 2 is `[finance, valuation, financial,
accounting, fundamentals, sec-filings]`. No `covered` entry names a
finance job at all: the ten covered jobs are research, docs, review,
security, browser, diagrams, memory, orchestration, spreadsheets and
slides. Finance is therefore a declared domain with no named incumbent,
which is exactly the derivation this file asks for.

Two things sit next to the gap without filling it. The `sec-edgar` MCP
server returns fundamentals from filings, which is the input side of this
job. `valuation-review` is a skill that reviews a valuation someone else
built. A library that turns statements into a documented ratio set is the
missing middle between the two.

Eight open issues against 616 forks, on a repository seven years old, is
an unusually quiet issue tracker for its size. That is worth reading
before it is worth trusting: it is consistent with disciplined
maintenance and also with issues being closed unanswered.

## What would have to be true for it to be worth installing

- **The data source must be free or already paid for.** If every call
  needs a vendor key on a paid plan, the library is an interface to a
  subscription, and the subscription becomes the real decision. A free
  tier that covers annual statements for listed companies would be
  enough for the work here; a free tier limited to a handful of tickers a
  day would fall short.
- **The formulas must be readable and cited.** "Transparent" has to mean
  the ratio definitions are in the source with their conventions stated
  (which EBITDA, which share count, which fiscal-year alignment). A
  number that cannot be traced to a formula cannot be published under
  the `source-check` rule.
- **The MCP server half must be optional.** The library is the value; an
  MCP server that ships a vendor key through a tool call is a second
  surface with a second set of questions. Install the library, decide
  the server separately.
- **It must earn a place next to `sec-edgar`.** If the fundamentals it
  computes are already what `sec-edgar` returns, the only new thing is
  the ratio layer, and that could be forty lines of code in `finance`
  instead of a dependency with its own transitive tree.

## Checks a human must run before installing

1. Identify the data vendor(s) it reads from, and read the vendor's free
   tier limits before the library's README. Decide whether the free
   tier covers the tickers and years the ESG and valuation work actually
   needs.
2. Resolve the PyPI package and the GitHub repository separately and
   confirm they are the same code, per `tool-vetting`. Check the
   dependency tree size: a finance library that pulls in a plotting stack
   and three HTTP clients is heavier than its job.
3. Pick one ratio the work already computes by hand (a margin, a
   coverage ratio, a return on capital) and compare the library's number
   for one company against the hand calculation from the same filing. A
   mismatch with no explanation in the formula is a stop.
4. Read the eight open issues and the last twenty closed ones. Closed by
   fix and closed by silence look the same in a count.
5. If the MCP server is considered at all, run it once with the network
   watched and confirm the only outbound connection is to the data
   vendor.
6. Decide the overlap with `sec-edgar` and the `finance` agent in
   writing before installing: which one is the source of fundamentals,
   and which one computes from them. Two sources of the same number is
   how figures drift.
