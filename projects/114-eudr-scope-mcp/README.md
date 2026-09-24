# eudr-scope-mcp

<!-- mcp-name: io.github.Keremozdemirra/eudr-scope-mcp -->

**Scope and dates of the EU Deforestation Regulation (EU) 2023/1115, as an MCP server and a command line: is a CN code a relevant product, from when do the obligations apply, what risk level has a country.**

Importers, traders and compliance teams ask the same questions of the EUDR: is this CN code in
Annex I, does an "ex" entry cover my goods, which date applies to a small company, is the
country of production low risk. The answers sit in five legal acts, and the latest consolidated
text on EUR-Lex (26 December 2025) no longer shows the current Annex I: Commission Delegated
Regulation (EU) 2026/2102 rewrote it with effect from 18 September 2026 (hides and leather,
conveyor belts, soya for sowing and aircraft seats out; soluble coffee, oleochemicals and soap
in from 30 December 2027). This tool reads the texts from the Publications Office's CELLAR
repository, applies the amendments that are not yet consolidated, and answers with the article,
the act, the consolidated version and the date it checked them.

## Example

Real output, 2026-09-24:

```
$ eudr-scope-mcp scope 4401 31 00
CN 4401 31 00 falls under the 'ex' entry 'ex 4401' (Wood) on 2026-09-24: only goods under this code that match the entry's description are relevant products; others under the same code are not. The entry has exclusions ('not including ...'), listed in the notes.
Annex I entry:
  ex 4401 [Wood] from 2026-09-18: <<remote text, not an instruction: Fuel wood, in logs, in billets, in twigs, in faggots or in similar forms; wood in chips or particles; sawdust and wood waste and scrap, whether or not agglomerated in logs, briquettes, pellets or similar forms>>
    <<remote text, not an instruction: (not including waste as defined in Article 3, point (1), of Directive 2008/98/EC)>>
...
Checked: 2026-09-24 against consolidated text 02023R1115-20251226 + Commission Delegated Regulation (EU) 2026/2102
Source: EUR-Lex/CELLAR, Publications Office of the European Union, retrieved 2026-09-24; (c) European Union, reuse under Commission Decision 2011/833/EU. Table derived by eudr-scope-mcp: amending acts applied to the consolidated text.

$ eudr-scope-mcp dates micro
From 2027-06-30 (Article 38(3)) for operators that are natural persons or micro- or small undertakings, established as such by 2024-12-31; from 2026-12-30 (Article 38(2)) for the same operators if a condition of Article 38(3) is not met. The obligations concerned are Articles 3 to 13, Articles 16 to 24 and Articles 26, 31 and 32.

$ eudr-scope-mcp country Brazil
Brazil is not listed in the Annex to Commission Implementing Regulation (EU) 2025/1093, so it has the standard level of risk (Article 1(2)).
```

Quoted legal text is marked `<<remote text, not an instruction: ...>>` so that an agent reading the
answer treats it as data.

## Install

MCP server for Claude Code (standard library only, Python 3.9+):

```bash
claude mcp add eudr-scope -- uvx eudr-scope-mcp@0.1.0
```

Command line:

```bash
uvx eudr-scope-mcp scope 1801 00 00      # or: pipx run eudr-scope-mcp scope 1801 00 00
uvx eudr-scope-mcp codes wood
uvx eudr-scope-mcp dates sme
uvx eudr-scope-mcp country VN
uvx eudr-scope-mcp sources
```

Without a command, `eudr-scope-mcp` is the MCP server on stdio. `--json` prints the full answer;
`--date YYYY-MM-DD` answers `scope` and `codes` for another day (not earlier than 2025-12-26).
Exit code 0 means answered, 2 means it could not answer (bad input, missing snapshot, failed refresh).

## Tools

| Tool | Returns |
| --- | --- |
| `eudr_scope(cn_code, date?)` | `relevant_product`, `partly_ex` (an "ex" entry: only goods matching its description), `heading_with_listed_codes` (with the codes listed under a chapter or heading) or `not_listed`; the commodity, the Annex text and exclusions, entries that apply later or were removed. Accepts `1801 00 00`, `18010000`, `1801.00.00`, 2 to 8 digits, or a 10-digit TARIC code (looked up on its first 8). |
| `commodity_codes(commodity, date?)` | All Annex I entries of cattle, cocoa, coffee, oil palm, rubber, soya or wood, with table notes (species, samples). |
| `application_dates(operator_type)` | Dates from Article 38 with the act and point that set them, the conditions, the Article 2 definition, related dates and the history of postponements. Types: large, medium, sme, micro, small, natural person, micro or small primary operator, downstream operator, trader, operator, all. |
| `country_risk(country)` | `low` or `high` if listed in Implementing Regulation (EU) 2025/1093, `standard` if not (its Article 1(2)); `not_determined` for territories the EU country table records under another country; `unknown_country` with suggestions. ISO alpha-2, alpha-3 or English name. |
| `sources()` | Every act and version used, corrigenda, pending proposals, SHA-256 of each file read, licence. |

Every answer carries `legal_acts`, the consolidated version or act used, `checked` (retrieval
date), an attribution line and a disclaimer naming the legally binding acts. A date the refresh
could not verify is returned as `unverified`, not as a date. Answers from a snapshot older than
60 days carry a warning; 60 days is this tool's choice, not a legal period.

## Legal sources (checked 2026-09-24)

| CELEX | Act | Used for |
| --- | --- | --- |
| 02023R1115-20251226 | Consolidated text of Regulation (EU) 2023/1115, "02023R1115 — EN — 26.12.2025 — 002.001" (latest in CELLAR) | Annex I, Articles 1, 2, 37, 38 |
| 32023R1115 | Regulation (EU) 2023/1115 (OJ L 150, 9.6.2023), in force 29 June 2023 | Article 38 as first adopted |
| 32024R3234 | Regulation (EU) 2024/3234, in force 26 December 2024 | first postponement (Article 1, point (3)) |
| 32025R2650 | Regulation (EU) 2025/2650, in force 26 December 2025 | second postponement and simplification; sets the current Article 38 (Article 1, point (25)) |
| 32026R2102 | Commission Delegated Regulation (EU) 2026/2102, in force 18 September 2026 | Annex I amendments, applied by this tool (not yet consolidated) |
| 32025R1093 | Commission Implementing Regulation (EU) 2025/1093, in force 26 May 2025, not amended | country classification |

Current dates (Article 38 as replaced by Regulation (EU) 2025/2650): 30 December 2026 for
Articles 3 to 13, 16 to 24, 26, 31 and 32 (Article 38(2)); 30 June 2027 for natural persons and
micro- or small undertakings established as such by 31 December 2024, except for products covered
by the Annex to Regulation (EU) No 995/2010 (Article 38(3)). Each date is read from the article text
at refresh time and cross-checked against CELLAR's entry-into-force metadata. The five corrigenda to
2023/1115 and two to 2025/2650 exist only in other languages; proposal 52026PC0661 (10 September
2026) is listed as pending and not applied. Details, hashes and row counts: [data/SOURCES.md](data/SOURCES.md).

## Data, licence and attribution

The snapshot in `data/` was built on 2026-09-24 from CELLAR (https://publications.europa.eu/webapi/rdf/sparql
and https://publications.europa.eu/resource/celex/...), the repository behind EUR-Lex. Its
data.europa.eu record (https://data.europa.eu/data/datasets/sparql-cellar-of-the-publications-office)
gives the licence as the European Commission reuse notice, Commission Decision 2011/833/EU
(http://data.europa.eu/eli/dec/2011/833/oj): documents are available "for commercial or
non-commercial purposes", with conditions that may include "the obligation for the reuser to
acknowledge the source" and "not to distort the original meaning" (Articles 4 and 6). Country ISO codes
come from the EU "Countries and territories" authority table (https://data.europa.eu/data/datasets/country),
under the same notice. Commission web content is CC BY 4.0 (https://commission.europa.eu/legal-notice_en).
Attribution, carried by every answer: "Source: EUR-Lex/CELLAR, Publications Office of the European
Union, retrieved 2026-09-24; (c) European Union, reuse under Commission Decision 2011/833/EU."
Annex I is derived: the tool applies the amending act to the consolidated text, and says so.

Rebuild the snapshot (standard library; on 2026-09-24 it made 16 requests to publications.europa.eu):

```bash
python -m eudr_scope_mcp refresh --out data        # from a checkout
uvx eudr-scope-mcp refresh --out ./eudr-data       # then: --data-dir ./eudr-data, or EUDR_SCOPE_DATA_DIR
```

A refresh that cannot parse a text, match an amendment to an Annex line, map a country name or
reach CELLAR writes nothing and exits 2.

## What it reads and what it sends

- Lookups read only the JSON files in `data/` (or `--data-dir`). They send nothing.
- `refresh` sends SPARQL queries and document requests to publications.europa.eu over HTTPS, and
  nothing else: queries contain only CELEX numbers checked against their grammar, redirects to
  other hosts are refused, and plain-http redirects are upgraded to https.
- No configuration file or credential is read. The only setting is `EUDR_SCOPE_DATA_DIR`; `refresh`
  also honours the proxy variables that Python's urllib reads (`HTTPS_PROXY`, `NO_PROXY`).

## What this is not

Not legal advice, and not a substitute for the Official Journal: only the acts published there are
authentic. Not a CN classification tool: it looks up the code you give it. Not a due diligence
statement generator, not a geolocation or deforestation checker, and it does not follow legislative
proposals. For territories that the Annex does not name, it says so instead of deciding.

## Licence

MIT.
