# climate-trace-mcp

**Climate TRACE emission estimates for facilities and countries, over MCP or the command line, with each figure's unit, GWP horizon, year, owners, source dataset and licence.**

<!-- mcp-name: io.github.Keremozdemirra/climate-trace-mcp -->

Climate TRACE publishes modelled emission estimates for individual facilities
(steel plants, power stations, landfills and more) and for every country, through
a free API that needs no key. An analyst who asks an agent "What are Climate
TRACE's 2024 estimates for steel plants in Germany, and who owns them?" needs more
than a number. They need the unit, whether it is CO2 or CO2-equivalent and over
which GWP horizon, the year, and the fact that it is an estimate rather than a
reported figure. They also need to know where it comes from. Climate TRACE
licenses its data under CC BY 4.0 "with the exception of external datasets"
(EDGAR, FAOSTAT, E-PRTR, US EPA and others), and one of those, IEA-EDGAR CO2, is
licensed CC BY-NC-ND 4.0.

The API returns the numbers alone. This server returns them with those labels
attached, so an agent can pass them on.

## Example

Real output, 2026-09-24, from the live API:

```
$ climate-trace-mcp search --country Germany --subsector iron-and-steel --year 2024 --limit 25
Climate TRACE assets, 2024: iron-and-steel, Germany (DEU)
Emissions: t CO2e, co2e_100yr, 100-year GWP (IPCC AR6). Modelled estimates.

asset_id  emissions t CO2e  country  type     name
1566771         15,212,776  DEU      BF/BOF   ThyssenKrupp Steel Duisburg steel plant
1566774          8,456,276  DEU      BF/BOF   Salzgitter Flachstahl steel plant
1566772          6,413,329  DEU      BF/BOF   Hüttenwerke Krupp Mannesmann (HKM) steel plant
1566776          5,728,777  DEU      BF/BOF   ArcelorMittal Bremen steel plant
1566773          4,223,508  DEU      BF/BOF   AG der Dillinger Hüttenwerke Dillingen steel plant
1566782          3,289,902  DEU      BOF      Saarstahl Völklingen steel plant
1566775          2,663,968  DEU      BF/BOF   ArcelorMittal Eisenhüttenstadt steel plant
1566778          1,584,027  DEU      BOF      ArcelorMittal Duisburg steel plant
1566779            163,978  DEU      EAF      Kehler Baden Steel Works
1566777            163,420  DEU      DRI-EAF  ArcelorMittal Hamburg steel plant
1566780            118,064  DEU      EAF      Riva Brandenburg Electric Steel Works
1566786             91,828  DEU      EAF      ESF Elbe Stahlwerke Feralpi Riesa steel plant
1566787             91,828  DEU      EAF      Lech Stahlwerke Meitingen steel plant
1566784             72,150  DEU      EAF      CSN Stahlwerk Thüringen Unterwellenborn steel plant
1566783             65,591  DEU      EAF      Salzgitter Peiner Träger Peine steel plant
1566781             65,591  DEU      EAF      Riva Hennigsdorfer Electric Steel Works
42741860            42,634  DEU      EAF      Georgsmarienhütte Osnabrück steel plant
1566785             42,634  DEU      EAF      Benteler Steel Tube Lingen plant
1566788             39,355  DEU      EAF      Deutsche Edelstahlwerke steel plant

19 asset(s).
Source dataset, iron-and-steel: Climate TRACE, subsector iron-and-steel (data leads named by the API: TransitionZero, Global Energy Monitor)
Values rounded to whole tonnes for display. Climate TRACE figures are modelled estimates, not measured or company-reported values; Climate TRACE says its models "are continually evolving and are expected to be updated over time". A difference from a company's reported figure reflects different methods, scope and boundaries. It does not show that either figure is wrong.
Source: Climate TRACE (climatetrace.org), CC BY 4.0, retrieved 2026-09-24
```

The owners of the five largest, from `climate-trace-mcp owners <asset_id> --json`
run for each on 2026-09-24:

| asset_id | Asset | Owner as the API lists it | Climate TRACE owner id | LEI |
| --- | --- | --- | --- | --- |
| 1566771 | ThyssenKrupp Steel Duisburg steel plant | Thyssenkrupp Steel Europe AG | E100001000542 | none returned |
| 1566774 | Salzgitter Flachstahl steel plant | Salzgitter Flachstahl GmbH | E100000003954 | none returned |
| 1566772 | Hüttenwerke Krupp Mannesmann (HKM) steel plant | Hüttenwerke Krupp Mannesmann GmbH | E100000003277 | none returned |
| 1566776 | ArcelorMittal Bremen steel plant | ArcelorMittal Bremen GmbH | E100001000494 | none returned |
| 1566773 | AG der Dillinger Hüttenwerke Dillingen steel plant | AG der Dillinger Hüttenwerke AG | E100000002380 | none returned |

```
$ climate-trace-mcp owners 1566774
Owners of Salzgitter Flachstahl steel plant (asset 1566774), as the Climate TRACE API lists them
  Salzgitter Flachstahl GmbH (Climate TRACE owner id E100000003954; LEI: none returned by the API)
Ownership shares: not provided by the API.
Note: The API returned no LEI for these owners. climate_trace_owner_id is Climate TRACE's own identifier; it is not an LEI (an LEI has 20 characters, ISO 17442).
Note: The API listed 4 owner entries for 1 distinct owner.
Ownership data: Climate TRACE: "Facility ownership information has been made available from a variety of sources, including primary sources such as company websites, secondary sources such as industry news articles, and aggregators such as PermID, OpenCorporates, and Wikipedia." (https://climatetrace.org/terms, checked 2026-09-24)
Source: Climate TRACE (climatetrace.org), CC BY 4.0, retrieved 2026-09-24
```

Country totals for Poland's power sector. One subsector comes from an external
dataset, and the answer says so:

```
$ climate-trace-mcp country Poland --sector power --years 2020-2024
Climate TRACE country totals: Poland (POL), sector power
Emissions: t CO2e, co2e_100yr, 100-year GWP (IPCC AR6). Modelled estimates.

                               2020         2021         2022         2023         2024
total                   145,785,559  166,736,968  159,313,253  133,989,351  127,313,186
months with data                 12           12           12           12           12
electricity-generation  133,742,980  153,271,930  146,730,350  123,307,603  116,774,550
heat-plants               9,846,464   10,898,615   10,042,709    8,616,030    8,616,030
other-energy-use *        2,196,115    2,566,423    2,540,194    2,065,718    1,922,606

* includes data Climate TRACE reproduces from an external dataset (below).
Source dataset, electricity-generation: Climate TRACE, subsector electricity-generation (data leads named by the API: WattTime, TransitionZero, Global Energy Monitor)
Source dataset, heat-plants: Climate TRACE, subsector heat-plants (the API names no data lead)
Source dataset, other-energy-use: Climate TRACE, subsector other-energy-use (the API names no data lead); per climatetrace.org/terms: country-level estimates reproduced from EDGAR
Note: These subsectors include data Climate TRACE reproduces from external datasets: other-energy-use. See source_datasets and external_dataset_terms.
Licence: Climate TRACE names EDGAR (in its terms or as a data lead) for: other-energy-use. EDGAR licenses its CO2 data (IEA-EDGAR CO2) under CC BY-NC-ND 4.0 (non-commercial, no derivatives); its other EU-owned data are CC BY 4.0 (https://edgar.jrc.ec.europa.eu/dataset_ghg2026, checked 2026-09-24). If a figure includes CO2 taken from EDGAR, non-commercial terms may apply to that part: check before commercial use.
Values rounded to whole tonnes for display. Climate TRACE figures are modelled estimates, not measured or company-reported values; Climate TRACE says its models "are continually evolving and are expected to be updated over time". A difference from a company's reported figure reflects different methods, scope and boundaries. It does not show that either figure is wrong.
Source: Climate TRACE (climatetrace.org), CC BY 4.0, retrieved 2026-09-24
```

Over MCP the same answers come as JSON: the unrounded values, and on every figure
its `unit`, `gas`, `gwp_horizon`, `year`, `estimate_type: "modelled"` and
`source_dataset`, plus `attribution`, `licence` and, where it applies,
`licence_note` and `external_dataset_terms`. An excerpt of the first asset above:

```json
"emissions": {
 "value": 15212775.994043015,
 "unit": "t CO2e",
 "gas": "co2e_100yr",
 "gwp_horizon": "100-year GWP (IPCC AR6)",
 "year": 2024,
 "estimate_type": "modelled",
 "source_dataset": "Climate TRACE, subsector iron-and-steel (data leads named by the API: TransitionZero, Global Energy Monitor)"
}
```

## Install

As an MCP server in Claude Code:

```bash
claude mcp add climate-trace -- uvx climate-trace-mcp
```

Other clients (Claude Desktop, Cursor and others) take the same command:

```json
{ "mcpServers": { "climate-trace": { "command": "uvx", "args": ["climate-trace-mcp"] } } }
```

On the command line, with no install:

```bash
uvx climate-trace-mcp search --country DE --subsector iron-and-steel --year 2024
pipx run climate-trace-mcp country Poland --sector power --years 2020-2024
```

`uvx` keeps the version it downloaded first; `uvx climate-trace-mcp@latest` asks
PyPI for the newest release. Python 3.9 or newer, standard library only, no API key.
From a checkout, `python3 -m climate_trace_mcp ...` does the same.

Started with no subcommand and stdin not a terminal (which is how an MCP client
starts it), it runs the MCP server on stdio; `climate-trace-mcp serve` does so
explicitly.

## Tools

| Tool | Returns | Limits |
| --- | --- | --- |
| `search_assets(name, country, sector, subsector, year, limit)` | Assets ranked by emissions for one year: id, name, country, subsector, asset type, emissions (t CO2e, 100-year GWP), emissions factor, activity and capacity with units, coordinates, source dataset. | Years 2021 to the current year (default: the last complete year). `limit` 1-100. `name` is matched locally over at most the top 500 assets for the other filters; the answer says whether that covered everything. |
| `asset(asset_id, years, gas)` | One asset by year: value, unit, Climate TRACE's confidence label, emissions factor, activity, capacity, global rank in its subsector; owners; source dataset and licence. | Years 2021 to the current year (default: 2021 to the last complete year). Years without data are listed, not shown as zero. |
| `country_emissions(country, sector, years, gas)` | Country totals per year with months of data, broken down by subsector (with a sector) or by sector; flags subsectors taken from external datasets and possible non-commercial terms. | Years 2015 to the current year, at most 12 per call (default: the last complete year). `sector="all_no_forest"` matches climatetrace.org's default view. |
| `owners(asset_id)` | Owner names and Climate TRACE owner ids, duplicates removed; an LEI only if the API returns a valid one. | The API gives no ownership shares. |
| `sectors()` | Sectors and subsectors (the valid filter values), asset-level availability, data leads, external datasets per the terms, gas codes; compared with the live lists. | From a dated snapshot of the API's definitions. |
| `sources()` | Licence, attribution line, caveat, external datasets and their licences, GWP definitions, live API version, what this is not. | |

`country` takes an ISO 3166-1 alpha-3 code (as the API expects), an alpha-2 code
or an English name: `DEU`, `de`, `Germany`; `Türkiye` and `Turkey`; `UK`.
`gas` is one of `co2e_100yr` (default), `co2e_20yr`, `co2`, `ch4`, `n2o`.

## Command line

```
climate-trace-mcp search  [--name N] [--country C] [--sector S] [--subsector S] [--year Y] [--limit N] [--json]
climate-trace-mcp asset   ASSET_ID [--years 2021-2024] [--gas G] [--json]
climate-trace-mcp country COUNTRY [--sector S] [--years 2020-2024] [--gas G] [--json]
climate-trace-mcp owners  ASSET_ID [--json]
climate-trace-mcp sectors [--json]
climate-trace-mcp sources [--json]
climate-trace-mcp serve
climate-trace-mcp refresh [--out PATH]
```

Tables round to whole tonnes and say so; `--json` prints the unrounded result the
MCP tools return. Exit codes: 0 answered; 1 input rejected or asset not found;
2 could not check (network, timeout, rate limit, API error, malformed answer).

## Data source, licence and attribution

**Climate TRACE API v7**, `https://api.climatetrace.org/v7`, OpenAPI document
version 7.2.0 (checked 2026-09-24). No key. Climate TRACE describes it as a beta:
"As a beta release, we cannot guarantee availability of the Climate TRACE API;
please keep volume low and use it with caution in production settings."
(https://climatetrace.org/data, checked 2026-09-24)

**Licence.** "The emissions data and associated metadata has been made available
via Climate TRACE under the Creative Commons Attribution 4.0 International License
(CC BY 4.0), with the exception of external datasets listed below."
(https://climatetrace.org/terms, checked 2026-09-24;
https://creativecommons.org/licenses/by/4.0/). Every answer carries the line

    Source: Climate TRACE (climatetrace.org), CC BY 4.0, retrieved YYYY-MM-DD

with the date the data was fetched. CC BY 4.0 also requires saying when you
changed the data: call anything you compute from these figures "derived". Climate
TRACE's own citation guidance:
https://github.com/climatetracecoalition/methodology-documents/tree/main/2025/README.

**External datasets.** The terms page names datasets that Climate TRACE reproduces
and that keep their own terms. This tool maps each named category to the API's
subsector (its reading of the page) and labels the figures accordingly:

| Dataset | Subsectors (per climatetrace.org/terms, 2026-09-24) | Licence as the provider states it |
| --- | --- | --- |
| EDGAR (European Commission, JRC) | Country-level estimates: other-energy-use, railways, other-transport, other-onsite-fuel-usage, other-solid-fuels, other-fossil-fuel-operations, other-manufacturing, solid-waste-disposal, biological-treatment-of-solid-waste-and-biogenic, incineration-and-open-burning-of-waste, fluorinated-gases | CC BY 4.0 for EU-owned material; "IEA-EDGAR CO2 (v5) data ... licensed under CC BY-NC-ND 4.0" (https://edgar.jrc.ec.europa.eu/dataset_ghg2026, checked 2026-09-24) |
| FAOSTAT (FAO) | Country-level estimates: rice-cultivation (in some geographies), other-agricultural-soil-emissions, enteric-fermentation-other, manure-management-other, other-onsite-fuel-usage | CC BY 4.0 with FAO's database terms of use (https://www.fao.org/contact-us/terms/db-terms-of-use/en/, checked 2026-09-24) |
| E-PRTR (EEA) | Some source-level records in other-manufacturing and solid-waste-disposal | not checked by this tool |
| US EPA FLIGHT | Some source-level records in other-manufacturing and solid-waste-disposal | not checked by this tool |
| Israel PRTR | Some source-level records in other-manufacturing | not checked by this tool |
| US EPA LMOP | Some source-level records in solid-waste-disposal (some landfills only) | not checked by this tool |
| Canada GHGRP, facility data | Some source-level records in solid-waste-disposal | Open Government Licence - Canada (https://open.canada.ca/data/en/dataset/a8ba14b7-7f23-462a-bdbb-83b0ef629823, checked 2026-09-24) |

The API itself names the organisations behind each subsector (`dataLeads`); for
`cropland-fires` it names EDGAR. When EDGAR is named for a figure that includes CO2
(`co2`, `co2e_100yr`, `co2e_20yr`), the answer sets
`non_commercial_terms_may_apply` and explains why. The API does not say which
individual records came from E-PRTR, US EPA or the other source-level datasets,
and the answers say that too. In Climate TRACE's words: "It is the sole
responsibility of the user to review the terms and conditions for all the above
sources prior to using the data."

**Units and GWP.** Quantities are metric tonnes. CO2e is "available (100 year and
20 year time frame using IPCC Sixth Assessment Report (AR6) Global Warming
Potentials)" (OpenAPI 7.2.0, field `gas`, checked 2026-09-24).

**Bundled data.** The API's sector and subsector definitions, with their data
leads, ship in `climate_trace_mcp/data/subsectors.json` (CC BY 4.0; retrieval date,
SHA-256 and row counts in `climate_trace_mcp/data/SOURCES.md`).
`climate-trace-mcp refresh` rebuilds that file from the API. The table that turns
country names into codes is in `climate_trace_mcp/countries.py`. ISO 3166-1 is
maintained by the ISO 3166 Maintenance Agency
(https://www.iso.org/iso-3166-country-codes.html, which answered HTTP 403 to this
build's network). The codes were therefore read from the UN Statistics Division's
M49 table, https://unstats.un.org/unsd/methodology/m49/overview/ (248 rows), and,
for Taiwan, from the EU Publications Office authority table, all on 2026-09-24.
XKX (Kosovo) and ZNC are Climate TRACE's codes, not ISO ones.

## What it reads and what it sends

- **Sends:** HTTPS GET requests to `api.climatetrace.org` and nothing else. The
  parameters are an alpha-3 code taken from the bundled table, sector and subsector
  names that appear in the API's own lists, a year, a gas code, an integer asset
  id and paging numbers. What you type as a country or a name is never sent: the
  name filter runs locally, because the API has no name search (it ignores a
  `name` parameter). The User-Agent is
  `climate-trace-mcp/0.1.0 (+https://github.com/Keremozdemirra/climate-trace-mcp)`.
  No key, no cookies.
- **Volume:** usually one request per tool call. `country_emissions` makes one
  per year (at most 12), a name search up to 5, `sectors` 2 and `sources` 1.
  Answers are cached in the process for an hour, and requests are made one after
  another, never in parallel.
- **Reads:** its bundled snapshot, and two optional environment variables:
  `CLIMATE_TRACE_API_BASE` (an `https://` URL, or `http://` on localhost for tests
  and staging; URLs with credentials or a query are refused) and
  `CLIMATE_TRACE_TIMEOUT` (1-60 seconds). It reads no configuration files and
  nothing in your home directory.
- **Writes:** nothing, except `refresh`, which rewrites the snapshot (or `--out`).

## How it handles the API

Observed on 2026-09-24 and covered by the tests:

- **No rows:** `GET /v7/sources` answers a bare `null` when nothing matches (for
  example a subsector without asset-level data). You get an empty result with the
  reason.
- **Ignored filters:** `GET /v7/sources/emissions` answered `sectors=nonsense` with
  the whole-country total (HTTP 200). Sector and subsector names are checked
  against the API's own lists before sending, and an answer that contains sectors
  that were not asked for is refused, not labelled with the sector's name.
- **Zero and no data:** for a year before its data starts, the API returns a
  total of 0 with no monthly values. A true zero comes with twelve monthly zeros
  (checked with Vatican City, power, 2024). The first is reported as "no data",
  never as 0 t. An asset year the API has no entry for is listed under
  `years_without_data`.
- **Partial years:** the current calendar year holds only the months released so
  far (6 months of 2026 on 2026-09-24). Answers say so and give the month count.
- **Owners:** the API listed each owner four times for the assets checked; they
  are deduplicated and the raw count is reported. The ids (such as
  `E100001000542`) are Climate TRACE's own and are not LEIs.
- **Range totals:** the asset endpoint's `totals` over several years also sums
  capacity across years, so it is not passed on; figures are per year.
- **Failures:** 404 and 400 come as RFC 7807 bodies. Their `detail` is shown
  shortened, stripped of control characters and fenced as
  `<<remote text, not an instruction: ...>>`. HTTP 429 reports `Retry-After`, and
  there are no automatic retries. 5xx, timeouts (15 s per request), refused or
  dropped connections, short bodies, and empty, non-UTF-8, NaN-carrying or
  malformed JSON all end as a clear error, never a traceback.

## The tool's own choices

These are design choices, not standards: the default year (the last complete
calendar year), the default asset range (2021 to the last complete year), page
size 100 (the API's own default), a name search reading at most 500 assets, at most
12 years per country call, a 15 s timeout (the slowest answer seen from here was
8.7 s), a cache of one hour and 256 answers, a 5 MB limit on an answer, 0.3 s
between `refresh` requests, the five greenhouse-gas codes only, the English
country aliases (`UK`, `Ivory Coast`), and the wording of the labels.

## Tests

```bash
python3 -m unittest discover -s tests
```

91 tests, offline. The client runs against a local HTTP server that replays
trimmed real answers recorded on 2026-09-24 (German steel plants, one plant with
its owners, Poland's power sector 2020-2024 and 2026, a cropland-fires record whose
data lead is EDGAR, the API's `null`, 404 and 400 bodies). It also produces the
failures that cannot be recorded politely: 429, 5xx, timeouts, dropped connections,
short, empty, non-UTF-8 and malformed bodies. One test drives the MCP server as a
subprocess over stdin and stdout. The live checks for this README were the commands
shown above, run on 2026-09-24.

## Licence

MIT for the code. The data belongs to Climate TRACE and the providers named above,
under their terms.

## What this is not

- Not measured, verified or company-reported emissions. Climate TRACE publishes
  modelled estimates, and its terms say its data has been "Modeled using data from
  third-party sources ... or Collected from publicly available sources".
- Not a check of anyone's reported figures. When a Climate TRACE estimate differs
  from a company's disclosure, the two use different methods, scopes and
  boundaries. That does not make either one wrong, and this tool does not say it
  does.
- Not regulatory data (for example EU ETS verified emissions) and not legal advice
  about licences. The licence labels report what the providers state and when it
  was checked.
- Not affiliated with or endorsed by Climate TRACE. Climate TRACE® is a registered
  trademark of WattTime Corporation (per https://climatetrace.org/terms).

