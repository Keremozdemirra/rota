# Bundled data

## subsectors.json

The Climate TRACE API's own definitions: the 10 sector names, and for each of the
69 subsectors the record `GET /v7/definitions/subsectors/{name}` returns (its
sector, display names, whether asset-level and country-level data exist, and
`dataLeads`, the organisations behind that subsector's estimates).

Every answer names the data leads of the subsectors it reports. A whole-country
answer covers about 60 subsectors; looking each one up live would cost about 60
requests per answer, and the API asks its users to "keep volume low"
(https://climatetrace.org/data). So the definitions ship with the package, and
the `sectors` tool compares them with the live lists whenever it runs.

| | |
| --- | --- |
| Source | `https://api.climatetrace.org/v7/definitions/sectors`, `/v7/definitions/subsectors` and `/v7/definitions/subsectors/{name}`; API version 7.2.0 |
| Licence | CC BY 4.0. "The emissions data and associated metadata has been made available via Climate TRACE under the Creative Commons Attribution 4.0 International License (CC BY 4.0), with the exception of external datasets listed below." (https://climatetrace.org/terms, checked 2026-09-24). These definitions are Climate TRACE's metadata, not one of the external datasets. |
| Attribution | Source: Climate TRACE (climatetrace.org), CC BY 4.0, retrieved 2026-09-24 |
| Retrieved | 2026-09-24 |
| SHA-256 | `455e5fee1f099b3b3b52e631e992ffa3a4daa04970a1c7e3626553e5292b87bf` |
| Rows | 10 sectors; 69 subsectors, of which 51 name at least one data lead and 47 have asset-level data |
| Changes | None to the records: each is stored as the API returned it. The file adds the API version, the retrieval date and the source URL, with keys sorted. |
| Personal data | None: organisation names and their website URLs. |
| Rebuild | `climate-trace-mcp refresh` (standard library only): one request per subsector, 0.3 s apart, written atomically. Same answers from the API give the same bytes: on 2026-09-24 the file was also rebuilt from definitions fetched separately earlier that day, and the SHA-256 matched. |

After a refresh, update the SHA-256, the counts and the date above.
