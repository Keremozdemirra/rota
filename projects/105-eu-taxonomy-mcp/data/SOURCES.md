# Sources of taxonomy.json

<!-- written by eu-taxonomy-mcp refresh -->

| | |
|---|---|
| Source | EU Taxonomy Navigator, European Commission (DG FISMA): https://ec.europa.eu/sustainable-finance-taxonomy/ |
| Backend | https://webgate.ec.europa.eu/sft/api/v1/en: the undocumented JSON API behind the Navigator web app. No API documentation, terms of use or service level were found (checked 2026-09-24); it may change or stop without notice. |
| Licence | CC BY 4.0, per the European Commission legal notice that the Navigator's footer links to: https://commission.europa.eu/legal-notice_en |
| Retrieved | 2026-09-24T09:23:08Z |
| Requests | 3 (bulk; at least 1 s apart), 2,612,100 bytes, 14.1 s |
| Client | `User-Agent: eu-taxonomy-mcp/0.1.0 (+https://github.com/Keremozdemirra/eu-taxonomy-mcp)` |

Licence terms, quoted from https://commission.europa.eu/legal-notice_en: "Unless otherwise indicated (e.g. in individual copyright notices), content owned by the EU on this website is licensed under the Creative Commons Attribution 4.0 International (CC BY 4.0) licence. This means that reuse is allowed, provided appropriate credit is given and changes are indicated."

Attribution line carried by every answer:

    Source: European Commission, EU Taxonomy Navigator (https://ec.europa.eu/sustainable-finance-taxonomy/), CC BY 4.0, retrieved 2026-09-24

## Raw responses

| Request | Bytes | SHA-256 of the body |
|---|---:|---|
| GET /sectors | 745 | `fc7b3c9d8df9ad071dfd03da78910c8a5ae7809c77ba482d93b5be1db7bcab8a` |
| GET /activities | 212,004 | `90baa0d0cbe9fffb98b7f1ff899756fa651e2fa5b80bfe5351d48830c75d1c2e` |
| GET /activities/matches/all | 2,399,351 | `017da8b7fc72cada3a27c9c272e9c7c7f9eee77a62f958a88f285cf6cb13a800` |

## Snapshot

| File | Bytes | SHA-256 |
|---|---:|---|
| taxonomy.json | 2,239,085 | `f813701e7f42eddaa17c28549395b2e8cbeb44ebeaa5367e4b2a03b454a2ec9d` |

| Rows | Count |
|---|---:|
| sectors | 16 |
| activities | 151 |
| criteria sets (one activity, one objective with substantial-contribution criteria) | 242 |
| DNSH entries | 1210 |
| environmental objectives | 6 |
| activities without NACE codes | 8 |
| activities without criteria | 0 |

## What the snapshot changes

- Keeps only these fields: activities id, name, sector, description, naceCodes; criteria sets id, objective, activityContributionType, contributionDescription, activityDescription, criteria, dnshCriterias; sectors and objectives as served. Nothing else from the backend is stored.
- Nests each activity's criteria sets under the activity and refers to objectives by id.
- Strips surrounding whitespace from NACE codes (the source serves codes such as ' F42.22'). Other code quirks ('A2', 'M71.1.2') are stored as served and normalised only when answering.
- Sorts sectors and activities by id, criteria sets and DNSH entries by objective order, and writes keys in sorted order, so the same data gives the same bytes.
- Changes no text: names, descriptions and criteria are the HTML strings as served.

## Rebuild

    python3 eu_taxonomy_mcp.py refresh            # in a source checkout: rewrites data/
    eu-taxonomy-mcp refresh --out DIR             # anywhere else; then --snapshot DIR/taxonomy.json
