# ghg-factors-mcp

<!-- mcp-name: io.github.Keremozdemirra/ghg-factors-mcp -->

**Greenhouse-gas conversion factors with their provenance, for an agent over MCP or for a person in a terminal.**

A language model asked for "the DESNZ diesel factor per litre" can answer with a
plausible number that has no source behind it, and a report built on such a number
cannot be traced back. `ghg-factors-mcp` answers from published tables only: the
UK Government (DESNZ) conversion factors, Ember's yearly grid intensities and the
Umweltbundesamt's German power-mix figures. Every answer names the factor ID, the
unit, the year and the source (DESNZ answers also the scope) and carries the
attribution line the licence asks for. A factor that is not in the tables is reported
as not found; a conversion whose unit does not match the factor is refused, not guessed.

The tables ship with the package as a dated snapshot, so queries need no network.
`refresh` rebuilds the snapshot from the sources, with the standard library only.

## Example

Real output, 2026-09-24, from the snapshot retrieved the same day.

```
$ ghg-factors-mcp search "diesel average biofuel blend" --unit litres --limit 1
DESNZ 2026 (UK): 1 of 3 matches for 'diesel average biofuel blend' (unit litres)

desnz-2026:1_101_1011_8_1  Scope 1  Fuels > Liquid fuels > Diesel (average biofuel blend)
    2.58354 kg CO2e per litres   CO2 2.55035, CH4 0.00029, N2O 0.0329

DESNZ factors are UK-specific. The 2026 publication page says: "They are suitable for use by: UK-based organisations of all sizes; International organisations reporting on their UK operations". A row that names another country or an international journey is still part of this UK set. Rows published blank by DESNZ are included with value null.
Source: Department for Energy Security and Net Zero (DESNZ), UK Government GHG Conversion Factors for Company Reporting 2026, flat file version 1.2, retrieved 2026-09-24. Contains public sector information licensed under the Open Government Licence v3.0.

$ ghg-factors-mcp convert 1000 litres desnz-2026:1_101_1011_8_1
2583.54 kg CO2e
  1000 litres × 2.58354 kg CO2e per litres = 2583.54 kg CO2e
  CO2: 1000 × 2.55035 = 2550.35 kg CO2e of CO2
  CH4: 1000 × 0.00029 = 0.29 kg CO2e of CH4
  N2O: 1000 × 0.0329 = 32.9 kg CO2e of N2O
factor: desnz-2026:1_101_1011_8_1  Fuels > Liquid fuels > Diesel (average biofuel blend)
Computed by ghg-factors-mcp: amount × published factor. DESNZ publishes the factor, not this result.
note: DESNZ factors are UK-specific. [...]
Source: Department for Energy Security and Net Zero (DESNZ), UK Government GHG Conversion Factors for Company Reporting 2026, flat file version 1.2, retrieved 2026-09-24. Contains public sector information licensed under the Open Government Licence v3.0.
```

Natural gas per kWh: DESNZ publishes it on a net and on a gross calorific value basis
(0.20199 and 0.18231 kg CO2e per kWh). A bare "kWh" is refused rather than matched to
either:

```
$ ghg-factors-mcp search "natural gas" --unit kWh --limit 2
DESNZ 2026 (UK): 2 of 8 matches for 'natural gas' (unit kWh)

desnz-2026:1_100_1004_7_1  Scope 1  Fuels > Gaseous fuels > Natural gas
    0.20199 kg CO2e per kWh (Net CV)   CO2 0.20158, CH4 0.00031, N2O 0.0001

desnz-2026:1_100_1004_6_1  Scope 1  Fuels > Gaseous fuels > Natural gas
    0.18231 kg CO2e per kWh (Gross CV)   CO2 0.18194, CH4 0.00028, N2O 0.00009
[...]

$ ghg-factors-mcp convert 1000 kWh desnz-2026:1_100_1004_6_1
refused: unit mismatch: desnz-2026:1_100_1004_6_1 is a factor per 'kWh (Gross CV)' and the amount is in 'kWh'. Not converted. If the amount is on the factor's basis, pass unit='kWh (Gross CV)'. DESNZ 2026 publishes the same activity per tonnes: desnz-2026:1_100_1004_15_1; cubic metres: desnz-2026:1_100_1004_1_1; kWh (Net CV): desnz-2026:1_100_1004_7_1.

$ ghg-factors-mcp convert 1000 "kWh (Gross CV)" desnz-2026:1_100_1004_6_1
182.31 kg CO2e
  1000 kWh (Gross CV) × 0.18231 kg CO2e per kWh (Gross CV) = 182.31 kg CO2e
[...]
```

Grid intensity, Poland and Germany, 2025. The two German figures measure different
things, and the answer says so:

```
$ ghg-factors-mcp grid Poland --year 2025
ember:POL:2025  Poland 2025: 590.886 g CO2e/kWh (= 0.590886 kg per kWh)  (Ember)
basis: Lifecycle emissions per kWh generated in the area: Ember's figures "aim to include full lifecycle emissions including upstream methane, supply chain and manufacturing emissions" (Ember methodology). Emissions from generation divided by generation (Ember's 'Total generation' row); net imports are listed separately by Ember and not included.
Location-based: a grid-average figure, usable for the location-based method of Scope 2 (GHG Protocol Scope 2 Guidance, 2015, p. 8). It is not a market-based factor: it reflects no supplier contract, tariff or energy attribute certificate. Ember's figure is lifecycle; the GHG Protocol counts only generation emissions in Scope 2 and upstream emissions in Scope 3 category 3 (Scope 2 Guidance, p. 34), so check which basis your reporting framework asks for.
note: kg_per_kwh is derived by ghg-factors-mcp (g divided by 1000).
Source: Ember, Yearly Electricity Data (global), CC BY 4.0 (https://ember-energy.org/creative-commons/), retrieved 2026-09-24; values unchanged, rows and columns selected.

$ ghg-factors-mcp grid Germany --year 2025 --source all
ember:DEU:2025  Germany 2025: 334.117 g CO2e/kWh (= 0.334117 kg per kWh)  (Ember)
[...]
uba:DEU:2025  Germany 2025: 344 g CO2/kWh (= 0.344 kg per kWh)  (Umweltbundesamt)
basis: Direct CO2 emissions of electricity generation per kWh of electricity consumed in Germany, as stated by the Umweltbundesamt: CO2 only (no CH4, N2O or upstream emissions); emissions behind Germany's net electricity imports are not counted.
Location-based: a grid-average figure, usable for the location-based method of Scope 2 (GHG Protocol Scope 2 Guidance, 2015, p. 8). It is not a market-based factor: it reflects no supplier contract, tariff or energy attribute certificate.
note: kg_per_kwh is derived by ghg-factors-mcp (g divided by 1000).
Quelle/Source: Umweltbundesamt, Strom- und Wärmeversorgung in Zahlen (https://www.umweltbundesamt.de/themen/klima-energie/energieversorgung/strom-waermeversorgung-in-zahlen), retrieved 2026-09-24; figures reused under § 12a EGovG, unchanged.

The sources measure different things (see basis); they are not interchangeable.

$ ghg-factors-mcp grid Lesotho --year 2024
Ember lists Lesotho for 2024 without an emissions intensity (generation 0.0 TWh). No other year is substituted.
  nearest with a value: 2022: 22.917 (ember:LSO:2022)
Source: Ember, Yearly Electricity Data (global), CC BY 4.0 (https://ember-energy.org/creative-commons/), retrieved 2026-09-24; values unchanged, rows and columns selected.
```

`[...]` marks lines left out here; nothing else is edited. Over MCP the same answers
come as JSON. The `structuredContent` of a `search_factors` call with the text
"DESNZ 2026 factor for diesel (average biofuel blend) per litre, split into CO2, CH4
and N2O" and `limit` 1 (real reply, 2026-09-24; `query` and `note` left out, the gas
entries put on one line each):

```json
{
 "matches": 3,
 "returned": 1,
 "results": [
  {
   "factor_id": "desnz-2026:1_101_1011_8_1",
   "source": "DESNZ",
   "year": 2026,
   "region": "UK",
   "scope": "Scope 1",
   "name": "Fuels > Liquid fuels > Diesel (average biofuel blend)",
   "activity_unit": "litres",
   "value": 2.58354,
   "unit": "kg CO2e per litres",
   "gases": {
    "CO2": {"factor_id": "desnz-2026:1_101_1011_8_2", "value": 2.55035, "unit": "kg CO2e of CO2 per litres"},
    "CH4": {"factor_id": "desnz-2026:1_101_1011_8_3", "value": 0.00029, "unit": "kg CO2e of CH4 per litres"},
    "N2O": {"factor_id": "desnz-2026:1_101_1011_8_4", "value": 0.0329, "unit": "kg CO2e of N2O per litres"}
   }
  }
 ],
 "attribution": [
  "Source: Department for Energy Security and Net Zero (DESNZ), UK Government GHG Conversion Factors for Company Reporting 2026, flat file version 1.2, retrieved 2026-09-24. Contains public sector information licensed under the Open Government Licence v3.0."
 ]
}
```

## Install

### As an MCP server

Claude Code:

```bash
claude mcp add ghg-factors -- uvx ghg-factors-mcp
```

Any other MCP client: command `uvx`, arguments `["ghg-factors-mcp"]`, transport stdio.
The server speaks MCP 2025-06-18 over stdin and stdout and needs Python 3.9 or newer;
the snapshot is inside the package, so it starts without network access.

### Command line

```bash
uvx ghg-factors-mcp search "natural gas" --unit kWh
pipx run ghg-factors-mcp grid Poland --year 2025
```

Without a command, `ghg-factors-mcp` runs the MCP server and waits for JSON-RPC on stdin.

## MCP tools

| Tool | Returns |
| --- | --- |
| `search_factors(text, scope, year, unit, limit)` | DESNZ factors whose labels contain the words, best match first: `factor_id`, `value`, `unit` (e.g. `kg CO2e per litres`), `activity_unit`, `scope`, `year`, `region: "UK"`, the CO2/CH4/N2O split where DESNZ publishes one, and the attribution line. At most 50 results. A year or "scope 1" written in the text is used as a filter. |
| `get_factor(factor_id)` | One factor with its full name, notes, gas split, and the same ID in the other bundled DESNZ year with the change in percent (derived). Also takes grid IDs. |
| `convert(amount, unit, factor_id)` | `amount × factor` with the arithmetic written out, in the factor's output unit, marked as derived, with the attribution line. Refuses a unit that is not the factor's unit and lists the IDs DESNZ publishes for the same activity in other units. |
| `grid_intensity(country, year, source)` | Grid carbon intensity: `source="ember"` (default, g CO2e/kWh, lifecycle, over 200 countries plus regions), `"uba"` (Germany, g CO2/kWh, CO2 only), `"all"`. Always labelled location-based. A year without a value returns `found: false` with the nearest years that have one. |
| `sources()` | Publisher, licence, terms, attribution line, retrieval date, SHA-256 and row count of each source, the Scope 2 caveat, and the sources left out. |

Factor IDs: `desnz-2026:1_101_1011_8_1` is the ID column of the DESNZ flat file
prefixed with the set's year (DESNZ reuses IDs across years); `ember:POL:2025` and
`uba:DEU:2025` name a grid figure. Regions without an ISO code use their Ember name
with hyphens, e.g. `ember:EU:2025`, `ember:World:2025`.

## Commands

| Command | Does |
| --- | --- |
| `search TEXT [--unit U] [--scope S] [--year Y] [--limit N]` | as `search_factors` |
| `get FACTOR_ID` | as `get_factor` |
| `convert AMOUNT UNIT FACTOR_ID` | as `convert` |
| `grid COUNTRY [--year Y] [--source ember\|uba\|all]` | as `grid_intensity` |
| `sources` | as `sources` |
| `refresh [--out DIR] [--only desnz,ember,uba] [--desnz-years 2026,2025]` | downloads the sources and rebuilds the snapshot |
| `serve` | the MCP server (also the default) |

`--json` prints the structured result. Exit codes: 0 answered, 1 not found or refused,
2 usage error, unreadable snapshot, or a source that could not be refreshed.

## Data

The code is MIT-licensed. The bundled data keeps the licences of its sources:

### Sources

| Source | Used | Licence and terms | Attribution carried in every answer |
| --- | --- | --- | --- |
| DESNZ, UK Government GHG Conversion Factors for Company Reporting, [2026](https://www.gov.uk/government/publications/greenhouse-gas-reporting-conversion-factors-2026) (flat file v1.2, updated July 2026) and [2025](https://www.gov.uk/government/publications/greenhouse-gas-reporting-conversion-factors-2025) (flat file v1) | all 8,740 rows of each flat file (7,035 and 7,029 with a value; DESNZ publishes the others blank) | [Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/). GOV.UK footer: "All content is available under the Open Government Licence v3.0, except where otherwise stated". The OGL: "If the Information Provider does not provide a specific attribution statement, you must use the following: Contains public sector information licensed under the Open Government Licence v3.0." | `Contains public sector information licensed under the Open Government Licence v3.0.` plus publisher, set, version and retrieval date |
| [Ember, Yearly Electricity Data](https://ember-energy.org/data/yearly-electricity-data/) (global CSV) | the "Total generation" row per area and year: emissions intensity (gCO2e/kWh), emissions, generation; 6,305 rows, 224 areas | CC BY 4.0. [Terms](https://ember-energy.org/creative-commons/): "Ember content is released under a Creative Commons Attribution Licence (CC-BY-4.0)"; "This means you’re free to share and adapt our work – as long as you credit us." | `Source: Ember, Yearly Electricity Data (global), CC BY 4.0 [...]`; conversions are marked derived, as CC BY asks for changes to be indicated |
| [Umweltbundesamt, Strom- und Wärmeversorgung in Zahlen](https://www.umweltbundesamt.de/themen/klima-energie/energieversorgung/strom-waermeversorgung-in-zahlen) | the CO2 factor of the German power mix for 2023, 2024, 2025 (379, 353, 344 g CO2/kWh); numbers only | [Terms](https://www.umweltbundesamt.de/datenschutz-haftung-urheberrecht), section C: "Soweit nicht anders gekennzeichnet, ist die Nutzung von Daten im Sinne des § 12a EGovG zulässig. [...] Bei der Nutzung ist sicherzustellen, dass das Umweltbundesamt im Quellenvermerk enthalten ist." UBA texts and graphics are CC BY-NC-ND 4.0 on the same page, so no text of the page is copied. | `Quelle/Source: Umweltbundesamt, [...] figures reused under § 12a EGovG, unchanged.` |

Retrieval dates, SHA-256 of every raw file and row counts are in
[`data/SOURCES.md`](data/SOURCES.md) and `data/manifest.json`, both written by `refresh`.

### Facts the answers rely on

| Fact | Primary source | Checked |
| --- | --- | --- |
| The 2026 DESNZ set is "suitable for use by: UK-based organisations of all sizes; International organisations reporting on their UK operations" | [GOV.UK publication page 2026](https://www.gov.uk/government/publications/greenhouse-gas-reporting-conversion-factors-2026) | 2026-09-24 |
| The 2026 flat file was republished in July 2026 to leave blank the values wrongly reported as 0 (version 1.2) | same page, "Update: July 2026"; flat file front page | 2026-09-24 |
| "the 2025 publication used 2023 data, and the 2026 publication uses 2025 data" for UK electricity | [DESNZ 2026 methodology paper](https://assets.publishing.service.gov.uk/media/6a2940543b15d05a7ce3202e/2026-GHG-conversion-factors-methodology-report.pdf), para 3.8, p. 27 | 2026-09-24 |
| Ember's figures "aim to include full lifecycle emissions including upstream methane, supply chain and manufacturing emissions, and include all gases, converted into CO2 equivalent over a 100-year timescale" | [Ember methodology](https://files.ember-energy.org/public-downloads/ember_electricity_data_methodology.pdf) | 2026-09-24 |
| Ember's overall intensity equals emissions divided by generation on the "Total generation" row (e.g. Germany 2025: 166.068 Mt / 497.035 TWh = 334.117 g/kWh) | computed from the Ember CSV | 2026-09-24 |
| UBA: 344 g CO2 per kWh of electricity consumed in Germany in 2025, 353 in 2024, 379 in 2023; direct CO2 emissions; emissions of the import surplus not counted | [UBA page](https://www.umweltbundesamt.de/themen/klima-energie/energieversorgung/strom-waermeversorgung-in-zahlen) | 2026-09-24 |
| "A location-based method reflects the average emissions intensity of grids on which energy consumption occurs (using mostly grid-average emission factor data)." | [GHG Protocol Scope 2 Guidance](https://ghgprotocol.org/scope-2-guidance) (2015), p. 8 | 2026-09-24 |
| "Scope 2 includes indirect emissions from generation only; other upstream emissions [...] are tracked in scope 3, category 3" | GHG Protocol Scope 2 Guidance (2015), p. 34 | 2026-09-24 |

### Left out, on licence grounds

| Source | Why | Evidence (checked 2026-09-24) |
| --- | --- | --- |
| IPCC Emission Factor Database (EFDB) | personal, non-commercial use only, no redistribution | [ipcc.ch/copyright](https://www.ipcc.ch/copyright/): "You may freely download and copy the material contained on this website for your personal, non-commercial use, without any right to resell or redistribute it or to compile or create derivative works there from" |
| PCAF emission factor database | a benefit of PCAF membership, not an open licence | [carbonaccountingfinancials.com/join-pcaf](https://carbonaccountingfinancials.com/join-pcaf): "The PCAF Database provides PCAF signatories and accredited partners with physical- and economic-activity-based emission factors" |
| IEA-EDGAR CO2 | CC BY-NC-ND 4.0: no commercial use, no derivatives | [edgar.jrc.ec.europa.eu/report_2026](https://edgar.jrc.ec.europa.eu/report_2026): "IEA-EDGAR CO 2 (v5) data are based on data from IEA (2025) Greenhouse Gas Emissions from Energy [...] licensed under CC BY-NC-ND 4.0." |

The Ember API needs a personal key and is not used; the public CSV is.

### Refresh

```bash
ghg-factors-mcp refresh                              # in a source checkout: rewrites data/
ghg-factors-mcp refresh --out ~/ghg-data             # installed package: write elsewhere, then
GHG_FACTORS_DATA=~/ghg-data ghg-factors-mcp serve    # point the server at it
```

It fetches the GOV.UK Content API entry of each DESNZ year, the flat-file XLSX it
lists (only from `assets.publishing.service.gov.uk`), the Ember CSV (about 16 MB) and
the UBA page, parses them with `zipfile`, `xml.etree` and `csv`, and writes the
snapshot. Rebuilt from the same raw files, the data files are byte-identical;
`manifest.json` and `SOURCES.md` also record the retrieval date. A source
that fails (network down, HTTP 404 or 429, empty or non-UTF-8 body, a changed
format, a malformed XLSX) keeps its previous snapshot and is reported; the exit code
is then 2. "An update is published each year" (GOV.UK page); the 2026 front page gives
June 2027 as the next publication date. Add the new year with `--desnz-years 2027,2026`. The UBA figures are read
from the text of a web page and stop refreshing, with an error, when the page changes.

## Scope 2: location-based only

Grid figures from Ember and UBA, and the DESNZ UK electricity factor, are averages of
a grid. They serve the location-based method of Scope 2 reporting. None of them is a
market-based factor: none reflects a supplier contract, a green tariff or an energy
attribute certificate, and the tools never present one as market-based. Ember's
figures are lifecycle figures: they include more than the generation emissions the
GHG Protocol counts in Scope 2. UBA's are CO2 only. Every grid answer says which.

## Choices this tool makes

These are the tool's own choices, not rules from a standard or a source:

- **Default year.** `search_factors` uses the newest DESNZ set bundled (2026) unless a
  year is given; `grid_intensity` uses the latest year with a value and says so.
- **Result size.** `search_factors` returns 10 results by default and at most 50.
- **Refresh checks.** A UBA figure outside 100 to 1500 g CO2/kWh, a table cell longer
  than 200 characters, or a flat file whose header names another year stops that
  source's refresh.
- **Units.** Spelling variants of one unit are accepted (litre, litres, L; m3, cubic
  metres; tonne, t). Exact decimal steps within one kind are converted and shown:
  Wh, kWh, MWh, GWh; kg, tonnes; litres, cubic metres, million litres. Nothing else is
  converted: not km to miles, not GJ to kWh, not net to gross calorific value.
- **Arithmetic.** Decimal arithmetic on the published figures, no rounding of results.
- **Search words.** Words that describe the request rather than the activity ("factor",
  "per", "split", "CO2", "please"...) are not matched. Any other word must appear in a
  DESNZ label; if one does not, the result is empty and the word is named.
- **Country names.** A name or ISO 3166-1 alpha-3 code as Ember lists it, ignoring case
  and accents, plus a short alias list (UK, US, Turkey, Czech Republic, Vietnam...).
  Two-letter codes are not guessed.
- **Change between years** (`same_id_other_years`) is computed by this tool and labelled
  derived.

## What it reads, what it sends

- **Reads:** the snapshot in the package (`ghg_factors_mcp/data`), in `data/` of a
  source checkout, or in the directory named by `GHG_FACTORS_DATA` (`HOME` only to
  expand a `~` in it). No configuration file, no credentials. `refresh` uses the
  proxy settings of the environment (`HTTPS_PROXY`), as Python's `urllib` does.
- **Sends:** nothing while answering. The MCP tools and the query commands work
  offline. Only `refresh` goes online, with plain HTTPS GET requests to `www.gov.uk`,
  `assets.publishing.service.gov.uk`, `files.ember-energy.org` and
  `www.umweltbundesamt.de`. No query, amount or factor ID leaves the machine.

## What this is not

- Not an emissions inventory or a carbon accounting system. It returns published
  factors and multiplies; choosing the right factor for an activity, the boundary and
  the method stays with you.
- Not advice on what a reporting framework (SECR, CSRD/ESRS, CDP, the GHG Protocol)
  requires. DESNZ publishes its factors for UK company reporting and says they "may
  also be used for other purposes, but users do so at their own risk".
- Not a source of market-based Scope 2 factors, residual mixes or supplier-specific
  rates.
- Not a replacement for the source tables. When a figure matters, check it against the
  file named in `sources()`; the snapshot records which file, retrieved when, with
  which SHA-256.
