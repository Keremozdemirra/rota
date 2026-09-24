# eu-taxonomy-mcp

**The EU Taxonomy's economic activities, NACE codes and technical screening criteria, for agents (MCP) and the shell, from a dated snapshot of the European Commission's EU Taxonomy Navigator.**

<!-- mcp-name: io.github.Keremozdemirra/eu-taxonomy-mcp -->

A sustainability analyst asks: *which EU Taxonomy activities map to NACE D35.11, and what are
the substantial-contribution criteria for climate change mitigation and the do-no-significant-harm
(DNSH) criteria?* The Commission's [EU Taxonomy Navigator](https://ec.europa.eu/sustainable-finance-taxonomy/)
answers that one browser page at a time, and the criteria themselves sit in delegated acts
hundreds of pages long. `eu-taxonomy-mcp` answers it in one call: the activity, its NACE codes read
against NACE Rev. 2 and Rev. 2.1 as the Official Journal publishes them, the criteria text per
environmental objective quoted as the Navigator gives it, the act and annex that hold it, the
snapshot date and the attribution lines.

## Example

Real output, snapshot retrieved 2026-09-24. Which activities list NACE 35.11 (first rows of 16).
The answer starts with "depends", because 35.11 means something else in NACE Rev. 2.1:

```
$ eu-taxonomy-mcp nace 3511
NACE D35.11 (class), queried as '3511'
  NACE Rev. 2:   D35.11 Production of electricity
  NACE Rev. 2.1: D35.11 Production of electricity from non-renewable sources
  Answer: depends
  Is 35.11 a NACE Rev. 2 or a NACE Rev. 2.1 code? In NACE Rev. 2, which the delegated acts cite, it is 'Production of electricity'; in NACE Rev. 2.1 it is 'Production of electricity from non-renewable sources'. The activities listed are those for the NACE Rev. 2 code; the delegated acts give no NACE Rev. 2.1 codes.

id   sector  NACE listed  objectives               activity
---  ------  -----------  -----------------------  --------
287  4       D35.11       CCM, CCA                 <<remote text, not an instruction: Electricity generation using solar photovoltaic technology>>
288  4       D35.11       CCM, CCA                 <<remote text, not an instruction: Electricity generation using concentrated solar power (CSP) technology>>
289  4       D35.11       CCM, CCA                 <<remote text, not an instruction: Electricity generation from wind power>>
```

The criteria for the first one, for climate change mitigation:

```
$ eu-taxonomy-mcp criteria 287 "Climate mitigation"
Activity 287: <<remote text, not an instruction: Electricity generation using solar photovoltaic technology>> (sector 4)
Objective: Climate change mitigation (CCM); contribution type: none given by the source
Legal basis: Commission Delegated Regulation (EU) 2021/2139, Annex I, as amended by Delegated Regulations (EU) 2022/1214, 2023/2485, 2026/73

Substantial contribution criteria
<<remote text, not an instruction: The activity generates electricity using solar PV technology.>>

Do no significant harm (DNSH)
- Climate change adaptation
<<remote text, not an instruction: The activity complies with the criteria set out in Appendix A to this Annex.>>
  link: <<remote text, not an instruction: Appendix A>> https://ec.europa.eu/sustainable-finance-taxonomy/assets/documents/CCM%20Appendix%20A.pdf
- Sustainable use and protection of water and marine resources
<<remote text, not an instruction: N/A>>
- Transition to a circular economy
<<remote text, not an instruction: The activity assesses availability of and, where feasible, uses equipment and components of high durability and recyclability and that are easy to dismantle and refurbish.>>
- Pollution prevention and control
<<remote text, not an instruction: N/A>>
- Protection and restoration of biodiversity and ecosystems
<<remote text, not an instruction: The activity complies with the criteria set out in Appendix D to this Annex.>>
  link: <<remote text, not an instruction: Appendix D>> https://ec.europa.eu/sustainable-finance-taxonomy/assets/documents/CCM%20Appendix%20D.pdf

Note: List items are shown as '-' bullets: the Navigator's HTML marks list items without point letters, and its list nesting does not always follow the Official Journal's points (a), (i). Cite points from the Official Journal.

Source: European Commission, EU Taxonomy Navigator (https://ec.europa.eu/sustainable-finance-taxonomy/), CC BY 4.0, retrieved 2026-09-24; HTML converted to plain text by eu-taxonomy-mcp
Information, not legal advice. The EU Taxonomy Navigator is not legally binding; the legally binding texts are Regulation (EU) 2020/852 and its delegated acts (2021/2139, 2021/2178, 2023/2486, as amended) as published in the Official Journal of the European Union. These criteria are set out in Commission Delegated Regulation (EU) 2021/2139, Annex I, as amended.
```

And by name:

```
$ eu-taxonomy-mcp search manufacture of cement
id   sector  NACE listed  objectives               activity
---  ------  -----------  -----------------------  --------
272  3       C23.51       CCM (Transitional), CCA  <<remote text, not an instruction: Manufacture of cement>>

1 matching activity
```

Through MCP, an agent asks the same with `nace_lookup("D35.11")` and
`criteria(287, "Climate mitigation")` and gets the same content as JSON.

## Install

As an MCP server in Claude Code:

```
claude mcp add eu-taxonomy -- uvx eu-taxonomy-mcp
```

Any other MCP client: the command is `uvx eu-taxonomy-mcp` (stdio). On the command line:

```
uvx eu-taxonomy-mcp nace D35.11
pipx run eu-taxonomy-mcp criteria 287 "Climate mitigation"
```

From a checkout, standard library only, Python 3.9 or later:

```
python3 eu_taxonomy_mcp.py nace D35.11                         # command line
claude mcp add eu-taxonomy -- python3 /path/to/eu_taxonomy_mcp.py   # MCP server
```

The snapshot and the NACE tables ship inside the package, so answers need no network.

## MCP tools

Protocol version 2025-06-18, JSON-RPC 2.0 over stdio. Every answer carries `snapshot_date`, the
attribution line and a legal note (the Navigator is not legally binding; the delegated acts are);
answers that quote EU law also carry `attribution_eu_law`.

| Tool | Returns |
| --- | --- |
| `list_sectors()` | The Navigator's 16 sectors with their number of activities; the six environmental objectives with the source's labels, the Commission's abbreviation, the number of activities with criteria, and the act and annex holding the criteria. |
| `search_activities(text, nace, objective, sector, limit)` | Activities matching words in the name or description and/or a NACE code, best first (`limit` 1 to 200, default 25): id, name, sector, NACE codes as listed and normalised, the objectives with criteria and their contribution type (Enabling, Transitional or none), and how each matched. With `nace`, also what the code means in each NACE revision. |
| `get_activity(activity_id, max_chars)` | One activity: its description (quoted), NACE codes with a note wherever the source writes one in a form NACE Rev. 2 does not use, and per objective the contribution type, legal basis and the length of the criteria text. |
| `criteria(activity_id, objective, max_chars, format)` | The substantial-contribution criteria for one objective and the DNSH criteria for the other five, quoted, with footnotes, links to the Navigator's appendix PDFs, the activity description for that objective and the legal basis (act, annex, the acts that amend that annex, ELI). |
| `nace_lookup(code)` | The code read in NACE Rev. 2 and Rev. 2.1 with both titles, and the activities whose listed NACE code is the same as, broader or narrower than it; the activities that list no NACE code at all; notes on reading NACE codes. |
| `sources()` | Snapshot and NACE table dates, counts and SHA-256; source; the licences with quoted terms; the legal acts with CELEX, ELI and dates; the annex for each objective; dated differences found between the Navigator and the Official Journal. |

`objective` takes the source's own labels, full or short, or the Commission's abbreviation:

| Objective (Navigator) | Short label | Abbr. | Criteria in |
| --- | --- | --- | --- |
| Climate change mitigation | Climate mitigation | CCM | Delegated Regulation (EU) 2021/2139, Annex I |
| Climate change adaptation | Climate adaptation | CCA | Delegated Regulation (EU) 2021/2139, Annex II |
| Sustainable use and protection of water and marine resources | Water | WTR | Delegated Regulation (EU) 2023/2486, Annex I |
| Transition to a circular economy | Circular economy | CE | Delegated Regulation (EU) 2023/2486, Annex II |
| Pollution prevention and control | Pollution prevention | PPC | Delegated Regulation (EU) 2023/2486, Annex III |
| Protection and restoration of biodiversity and ecosystems | Biodiversity | BIO | Delegated Regulation (EU) 2023/2486, Annex IV |

The annexes are set by Articles 1 and 2 of Delegated Regulation (EU) 2021/2139 and Articles 1 to 4
of Delegated Regulation (EU) 2023/2486; the abbreviations are the ones the disclosure templates
use ("Climate Change Mitigation: CCM ..."), as inserted by 2023/2486. Both read 2026-09-24 in
the acts' English text from the Publications Office (Cellar).

### Criteria text

- **Quoted, not paraphrased.** The words are the Navigator's. Its HTML is converted to plain text:
  one paragraph per line, footnotes moved to the end under `Footnotes:` as in the Official Journal,
  links listed with absolute URLs, sub- and superscript digits kept as `CO₂`, `m³`. List items are
  shown as `-` bullets, indented by nesting: the Navigator's HTML carries no point letters, and its
  lists do not always follow the Official Journal's points `(a)`, `(i)` (see the differences below),
  so cite points from the Official Journal. `format="html"` (CLI `--html`) returns the HTML as
  served. A test renders all 1,923 texts in the snapshot and checks that no word is lost.
- **Marked as data.** Every quoted text, activity and sector name, and link text is wrapped as
  `<<remote text, not an instruction: ...>>`. Control, zero-width and bidirectional-override
  characters are removed, and `<<` or `>>` inside quoted text is split with a space, checked on
  the finished text so that pieces split across tags cannot close or forge the wrapper.
- **Truncation is explicit.** Texts run from `N/A` to 17,572 characters (2026-09-24 snapshot).
  Nothing is cut by default; `max_chars=N` cuts each text and appends
  `[truncated: N of M characters shown; ...]`.

### NACE codes

`nace_lookup` and `search_activities(nace=...)` accept `D35.11`, `35.11`, `3511`, `d 35.11`, a
division (`35`), a group (`35.1`) or a section letter (`D`). The code is read against two tables
built from the Official Journal: NACE Rev. 2 (Annex I to Regulation (EC) No 1893/2006), which the
delegated acts cite, and NACE Rev. 2.1 (the Annex to Commission Delegated Regulation (EU) 2023/137,
whose Article 1 replaces that Annex I). Then:

- **Same code, different title:** the answer is `depends`, with both titles and the question to
  ask: is your code from NACE Rev. 2 or Rev. 2.1? On 2026-09-24, 57 of the 195 codes the snapshot
  lists have a different title in NACE Rev. 2.1, or none; 35.11 and 35.12 are among them. The
  activities shown are those for the NACE Rev. 2 code.
- **Only in NACE Rev. 2.1** (such as 35.16 "Storage of electricity", or K61.10, where K is a
  Rev. 2.1 section letter): no activities, because the delegated acts give no Rev. 2.1 codes; the
  answer says so and names the NACE Rev. 2 code with the same digits, without mapping one to the
  other.
- **In neither table**, or with a section letter that fits neither revision (`35.19`, `C35.11`):
  refused with an error that says why. The tool does not guess.
- **Section letters come from the tables**, not from the source: `84` is read as O84.

The delegated acts write some codes in forms NACE Rev. 2 does not use, and the Navigator repeats
them. They are read as NACE Rev. 2 codes, and the answer says so next to each one: `A2` (A02),
`A2.40`, `B9.10`, `H49.3.9`, `M71.1.2`; `Q84` for "Emergency Services" (division 84 is in section O)
and `E42.99` for "Depollution and dismantling of end-of-life products" (division 42 is in section F).

The delegated acts give NACE codes as examples: the activity descriptions say an activity "could be
associated with several NACE codes, in particular ...". The description, not the code, sets the
scope. 8 of the 151 activities list no NACE code at all (for example "Storage of electricity");
`nace_lookup` lists them with every answer.

## Command line

| Command | What it does |
| --- | --- |
| *(none)* or `serve` | MCP server on stdio. |
| `sectors` | Sectors and objectives. |
| `search WORDS [--nace CODE] [--objective OBJ] [--sector S] [--limit N]` | Find activities. |
| `activity ID [--max-chars N]` | One activity. |
| `criteria ID OBJECTIVE [--max-chars N] [--html]` | Criteria for one activity and objective. |
| `nace CODE` | Activities for a NACE code, read in both NACE revisions. |
| `sources` | Snapshot, NACE table, licences, attribution, legal acts, known differences. |
| `refresh [--out DIR] [--delay S] [--timeout S] [--per-activity]` | Rebuild the snapshot from the Navigator's backend. |
| `refresh --nace [--out DIR]` | Rebuild the NACE tables from the Official Journal. |

`--json` prints what the MCP tool returns. `--snapshot PATH` (or the environment variable
`EU_TAXONOMY_MCP_SNAPSHOT`) reads another snapshot, such as one written by `refresh --out`; a
`nace.json` next to it is used, else the bundled one. Numbers outside their range (`--limit -5`,
`--max-chars` below 0) are refused, not replaced. Exit codes: 0 answer, 1 nothing found, 2 error
(bad input, unreadable snapshot, failed refresh).

## Data sources and licences

- **EU Taxonomy Navigator** (activities, NACE codes as listed, criteria):
  <https://ec.europa.eu/sustainable-finance-taxonomy/>, European Commission (the site says it is
  managed by DG FISMA). Its footer links to the European Commission legal notice,
  <https://commission.europa.eu/legal-notice_en>, which says: "Unless otherwise indicated (e.g. in
  individual copyright notices), content owned by the EU on this website is licensed under the
  Creative Commons Attribution 4.0 International (CC BY 4.0) licence. This means that reuse is
  allowed, provided appropriate credit is given and changes are indicated." (read 2026-09-24).
  Every answer carries:
  `Source: European Commission, EU Taxonomy Navigator (https://ec.europa.eu/sustainable-finance-taxonomy/), CC BY 4.0, retrieved 2026-09-24`,
  plus "HTML converted to plain text by eu-taxonomy-mcp" or "NACE normalisation and matching
  derived by eu-taxonomy-mcp" where the tool changed or computed something.
- **Backend:** `https://webgate.ec.europa.eu/sft/api/v1/en`, the JSON API the Navigator web app
  reads (its address is in the app's JavaScript). It is **undocumented**: no API documentation,
  terms of use or service level were found (checked 2026-09-24). It may change or stop without
  notice, which is why answers come from a dated snapshot and `refresh` is a separate, optional step.
- **Official Journal texts** (act titles and passages quoted in `sources()` and the notes; the NACE
  titles): the EUR-Lex legal notice, <https://eur-lex.europa.eu/content/legal-notice/legal-notice.html>,
  says: "The Commission’s document reuse policy is based on Decision 2011/833/EU. Unless otherwise
  specified, you can re-use the legal documents published in EUR-Lex for commercial or
  non-commercial purposes." Commission Decision 2011/833/EU, Article 4: "All documents shall be
  available for reuse: (a) for commercial or non-commercial purposes under the conditions laid down
  in Article 6;"; Article 6(2) lists "the obligation for the reuser to acknowledge the source of the
  documents" and "the obligation not to distort the original meaning or message of the documents".
  These texts are therefore not labelled CC BY here; answers that carry them add
  `attribution_eu_law`, naming the Official Journal, EUR-Lex and Cellar, the date read and
  Decision 2011/833/EU.
- **Consolidated texts:** the same EUR-Lex notice says: "The copyright for the editorial content of
  this website, the summaries of EU legislation and the consolidated texts, which is owned by the EU,
  is licensed under the Creative Commons Attribution 4.0 International licence." The one passage
  quoted from a consolidated text (`73,4 %`, below) carries its own CC BY 4.0 attribution.
- **Legal status:** the Commission legal notice says: "Only the Official Journal of the European
  Union (the printed edition or, since 1 July 2013, the electronic edition on the EUR-Lex website)
  is authentic and produces legal effects." Every answer therefore says the Navigator is not
  legally binding and names the acts that are.

All quotes above were read on 2026-09-24; [`data/SOURCES.md`](data/SOURCES.md) repeats them with
the URLs.

### Snapshot, NACE tables and refresh

`data/taxonomy.json` holds the snapshot of 2026-09-24: 16 sectors, 151 activities, 242 criteria
sets (one activity and one objective with substantial-contribution criteria) and 1,210 DNSH entries.
`data/nace.json` holds the two NACE tables: NACE Rev. 2 with 21 sections, 88 divisions, 272 groups
and 615 classes, and NACE Rev. 2.1 with 22, 87, 287 and 651, as the two annexes give them.
[`data/SOURCES.md`](data/SOURCES.md) lists for each file the URLs, terms, retrieval time, the
SHA-256 of each raw response and of the file, and the counts. Both files keep only what the tool
needs, store all text as served, and are written with sorted keys and a fixed order.

`refresh` rebuilds the snapshot with three GET requests at least one second apart: `/sectors`,
`/activities` and `/activities/matches/all`. If the bulk request fails or lists nothing, it fetches
`/activities/{id}/matches` for each activity instead, one request per activity (151 on
2026-09-24). Every response is checked. It exits with code 2 and writes nothing on an HTTP error, an
empty, `null`, non-UTF-8 or non-JSON body, a changed payload shape or a timeout, and also when the
result has no criteria sets, or fewer than half the activities or criteria sets of the previous
snapshot (the half is this tool's choice: a probable fault, not a real change; move the old file
away to accept one). The live run from 2026-09-24:

```
$ python3 eu_taxonomy_mcp.py refresh
refresh: https://webgate.ec.europa.eu/sft/api/v1/en -> /home/user/rota/projects/105-eu-taxonomy-mcp/data
refresh: 3 requests (bulk), 2,612,100 bytes, 14.5 s
snapshot: 16 sectors, 151 activities, 242 criteria sets, 1210 DNSH entries, 6 objectives; retrieved 2026-09-24
changes against the previous snapshot: no change in activities or criteria
wrote /home/user/rota/projects/105-eu-taxonomy-mcp/data/taxonomy.json (2,239,085 bytes, sha256 f813701e7f42eddaa17c28549395b2e8cbeb44ebeaa5367e4b2a03b454a2ec9d) and SOURCES.md
```

Three runs that day wrote the same bytes. `refresh --nace` reads the two acts' English text from
the Publications Office's Cellar over https (Cellar redirects to a plain-http address, which the
tool upgrades to https; any other redirect to http is refused), parses the annex tables, and
refuses a table smaller than 20 sections, 80 divisions, 250 groups or 600 classes (this tool's
floor). The live run:

```
$ python3 eu_taxonomy_mcp.py refresh --nace
refresh: https://publications.europa.eu/resource/celex/ -> /home/user/rota/projects/105-eu-taxonomy-mcp/data
refresh --nace: 2 requests, 1,760,621 bytes, 4.4 s
NACE Rev. 2: 21 sections, 88 divisions, 272 groups, 615 classes
NACE Rev. 2.1: 22 sections, 87 divisions, 287 groups, 651 classes
wrote /home/user/rota/projects/105-eu-taxonomy-mcp/data/nace.json (124,254 bytes, sha256 642a19add78c8149049337480a42baadbc8962597a95f1f63482e8d6d91a8fbb) and SOURCES.md
```

In a checkout, `refresh` rewrites `data/`. An installed package never rewrites its bundled copy:
use `refresh --out DIR`, then `--snapshot DIR/taxonomy.json`. `refresh` refuses to overwrite a
`SOURCES.md`, `taxonomy.json` or `nace.json` it did not write, and each run keeps the other file's
section of `SOURCES.md` as it was.

## Legal basis

Read 2026-09-24: CELEX numbers, titles, dates and ELI identifiers through the Publications Office
SPARQL endpoint (<https://publications.europa.eu/webapi/rdf/sparql>); application dates, the
annex for each objective and which annexes each act amends in the acts' English text from Cellar.

| Act | CELEX | Adopted | What it does |
| --- | --- | --- | --- |
| Regulation (EU) 2020/852 | 32020R0852 | 2020-06-18 | The Taxonomy Regulation; Article 9 lists the environmental objectives. |
| Commission Delegated Regulation (EU) 2021/2139 | 32021R2139 | 2021-06-04 | Technical screening criteria for climate change mitigation (Annex I) and adaptation (Annex II). Applies from 2022-01-01. |
| Commission Delegated Regulation (EU) 2021/2178 | 32021R2178 | 2021-07-06 | Disclosure: what undertakings report and how. |
| Commission Delegated Regulation (EU) 2022/1214 | 32022R1214 | 2022-03-09 | Amends Annexes I and II to 2021/2139 (Article 1), and 2021/2178, as regards economic activities in certain energy sectors. |
| Commission Delegated Regulation (EU) 2023/2485 | 32023R2485 | 2023-06-27 | Amends Annexes I and II to 2021/2139 (Article 1): additional criteria for the climate objectives. Published 2023-11-21; applies from 2024-01-01, point (28) of Annex I and point (26) of Annex II from 2025-01-01. |
| Commission Delegated Regulation (EU) 2023/2486 | 32023R2486 | 2023-06-27 | Criteria for water (Annex I), circular economy (Annex II), pollution (Annex III), biodiversity (Annex IV); amends 2021/2178. Published 2023-11-21, applies from 2024-01-01. |
| Commission Delegated Regulation (EU) 2024/3215 | 32024R3215 | 2024-06-28 | Corrects certain language versions of 2021/2139. Its Article 1 reads "(Does not concern the English language.)", so it changes nothing in the English text quoted here. Published 2024-12-19. |
| Commission Delegated Regulation (EU) 2026/73 | 32026R0073 | 2025-07-04 | Simplification: amends 2021/2178, and replaces Appendix C (generic DNSH criteria on chemicals) of Annexes I and II to 2021/2139 (Article 2) and of Annexes I, II and IV to 2023/2486 (Article 3). Published 2026-01-08, applies from 2026-01-01; for a financial year starting in 2025 undertakings may apply the acts as they stood on 2025-12-31 (Article 4). |

So each objective's legal basis names only the acts that amend its annex: Annexes I and II to
2021/2139 are amended by 2022/1214, 2023/2485 and 2026/73; Annexes I, II and IV to 2023/2486 by
2026/73; Annex III to 2023/2486 (pollution) by none. The Publications Office lists consolidated
versions of 2021/2139, 2021/2178 and 2023/2486 dated 2026-01-01 (CELEX 02021R2139-20260101,
02021R2178-20260101, 02023R2486-20260101). We found no statement in the Navigator of which version
its text reflects.

### Differences found between the Navigator and the Official Journal

Observed on 2026-09-24; `sources()` returns them too, and `criteria()` repeats the first one when
the criteria point to an Appendix C (76 criteria sets do).

- The Navigator's appendix file `CCM Appendix C.pdf` still had the wording that Delegated
  Regulation (EU) 2026/73 replaced from 1 January 2026: its point (c) cites Regulation (EC) No
  1005/2009, where the replacement text cites Regulation (EU) 2024/590. Only that one appendix file
  was checked.
- The Navigator's text is not always character-identical to the Official Journal: the climate
  change mitigation criteria of "Manufacture of hydrogen" (activity 275) read `73.4%` where the
  consolidated text of 2021/2139 (version of 1 January 2026) reads `73,4 %`.
- The Navigator's lists do not always follow the Official Journal's points. For "Transport by
  motorbikes, passenger cars and light commercial vehicles" (activity 334), climate change
  mitigation, the consolidated text has point (a) "for vehicles of category M1 and N1 ..." with
  points (i) "until 31 December 2025 ..." and (ii) "from 1 January 2026 ..." under it; the
  Navigator's HTML puts all three in one list with the point for category L vehicles. Hence the
  bullets.
- The delegated acts write some NACE codes in forms NACE Rev. 2 does not use (`A2`, `A2.40`,
  `B9.10`, `H49.3.9`, `M71.1.2`, `Q84`, `E42.99`; see above), and the Navigator repeats them.
- The Navigator does not give the annex section numbers of the activities (such as 4.1); the ids
  in this tool are the Navigator's own.

## What it reads, what it sends

- **Reads:** the snapshot and NACE table: the bundled ones, or the snapshot named by `--snapshot`
  or `EU_TAXONOMY_MCP_SNAPSHOT` and a `nace.json` next to it. Nothing else: no configuration files,
  nothing in your home directory.
- **Sends:** nothing while answering; the MCP tools and the query commands work offline. Only
  `refresh` goes online: GET requests to `webgate.ec.europa.eu` for the paths above, and with
  `--nace` to `publications.europa.eu` for the two CELEX numbers 32006R1893 and 32023R0137, with
  `User-Agent: eu-taxonomy-mcp/0.1.0 (+https://github.com/Keremozdemirra/eu-taxonomy-mcp)`, no
  cookies, no tokens. The only variable part of a URL is an activity id from the backend's own list,
  checked to be a number first.
- **Writes:** only `refresh`, and only `taxonomy.json` or `nace.json` and `SOURCES.md` in its
  output directory.

## Development

```
python3 -m unittest discover -s tests
```

95 tests, offline, against trimmed responses recorded on 2026-09-24 (seven activities from the
backend, excerpts of the two NACE annexes from Cellar): NACE forms and revisions, searching,
criteria, truncation, rendering, the remote-text wrapper, legal basis per annex, licences, snapshot
errors, the refresh failure modes (HTTP 500, 404, 429 with `Retry-After`, empty, `null`, non-UTF-8
and HTML bodies, empty or shrunk results, `IncompleteRead`, dropped connections, timeouts, changed
payloads), byte-identical rebuilds, the https-only redirects, and an MCP session over stdin and
stdout.

## Licence

MIT for the code. The data in `data/` is © European Union: the snapshot is CC BY 4.0 (Navigator
content); the NACE tables are Official Journal text, re-used under Decision 2011/833/EU. See
[`data/SOURCES.md`](data/SOURCES.md).

## What this is not

- Not legal advice and not an alignment assessment. It shows what the criteria say; it does not
  check whether an activity meets them, and it does not compute turnover, CapEx or OpEx KPIs or
  assess minimum safeguards.
- Not the legal text. The Navigator is a web rendering and not legally binding; the delegated acts
  in the Official Journal are. The appendices the criteria refer to (A to E) are PDFs on the
  Navigator site; the tool links to them but does not include them.
- Not live. Answers are as of the snapshot date shown with each one; run `refresh` for a newer one.
- Not a NACE classifier or a NACE Rev. 2 to Rev. 2.1 converter. NACE codes in the delegated acts
  are examples, not a test of eligibility.
- Not a Commission product, and not affiliated with the European Commission.
