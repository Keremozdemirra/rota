# Test fixtures

Real answers from ESMA's FIRDS register backend and the GLEIF API, recorded on 2026-09-24 through
firds-mcp's own request code (or with curl where noted), then trimmed. Nothing here was invented;
variants that the tests need (a sole proprietor, control characters in a name, a record without
relationship links, HTTP 429) are built from these files inside the tests, and say so there.

File names are the routes `tests/fakenet.py` derives from a request URL. `.404` and `.400` mark
answers with that HTTP status.

FIRDS data: ESMA, reproduction authorised provided the source is acknowledged
(https://www.esma.europa.eu/about-esma/legal-notice-and-data-protection). GLEIF data: CC0 1.0
(https://www.gleif.org/en/meta/lei-data-terms-of-use/). No record here names a natural person.

| File | Status | Recorded from | Changes |
| --- | --- | --- | --- |
| `firds/DE0005140008.json` | 200 | `https://registers.esma.europa.eu/solr/esma_registers_firds/select?q=isin%3ADE0005140008&fq=latest_received_flag%3A1&fl=isin%2Ctype_s%2Cst...` | trimmed: 8 of 92 venue records kept (MICs XETA, CEUX, JBUL, RFQN, XTXM, TNLK, VFSI, BAAD); numFound set to 8 to match |
| `firds/DE0005140008_rows4_start0.json` | 200 | `https://registers.esma.europa.eu/solr/esma_registers_firds/select?q=isin%3ADE0005140008&fq=latest_received_flag%3A1&fl=isin%2Ctype_s%2Cst...` | unchanged |
| `firds/DE0005140008_rows4_start4.json` | 200 | `https://registers.esma.europa.eu/solr/esma_registers_firds/select?q=isin%3ADE0005140008&fq=latest_received_flag%3A1&fl=isin%2Ctype_s%2Cst...` | unchanged |
| `firds/DE000C1D9NG7.json` | 200 | `https://registers.esma.europa.eu/solr/esma_registers_firds/select?q=isin%3ADE000C1D9NG7&fq=latest_received_flag%3A1&fl=isin%2Ctype_s%2Cst...` | unchanged |
| `firds/IE00B4L5Y983.json` | 200 | `https://registers.esma.europa.eu/solr/esma_registers_firds/select?q=isin%3AIE00B4L5Y983&fq=latest_received_flag%3A1&fl=isin%2Ctype_s%2Cst...` | trimmed: 4 of 77 venue records kept (MICs XETA, XAMS, XLON, XGRM); numFound set to 4 to match |
| `firds/XS0000000009.json` | 200 | `https://registers.esma.europa.eu/solr/esma_registers_firds/select?q=isin%3AXS0000000009&fq=latest_received_flag%3A1&fl=isin%2Ctype_s%2Cst...` | unchanged |
| `firds/XS1910948592.json` | 200 | `https://registers.esma.europa.eu/solr/esma_registers_firds/select?q=isin%3AXS1910948592&fq=latest_received_flag%3A1&fl=isin%2Ctype_s%2Cst...` | trimmed: 5 of 26 venue records kept (MICs XLUX, DUSD, TWEM, BERB, MAEL); numFound set to 5 to match |
| `firds/bad_query.400.json` | 400 | `https://registers.esma.europa.eu/solr/esma_registers_firds/select?q=isin:(&wt=json` | unchanged; a malformed query, recorded to have Solr's real error body |
| `gleif/5299004PWNHKYTR23649.json` | 200 | `https://api.gleif.org/api/v1/lei-records/5299004PWNHKYTR23649` | unchanged |
| `gleif/5299004PWNHKYTR23649_direct-children_size20_p1.json` | 200 | `https://api.gleif.org/api/v1/lei-records/5299004PWNHKYTR23649/direct-children?page%5Bsize%5D=20&page%5Bnumber%5D=1` | unchanged |
| `gleif/5299004PWNHKYTR23649_direct-parent-relationship.json` | 200 | `https://api.gleif.org/api/v1/lei-records/5299004PWNHKYTR23649/direct-parent-relationship` | unchanged |
| `gleif/5299004PWNHKYTR23649_ultimate-parent-relationship.json` | 200 | `https://api.gleif.org/api/v1/lei-records/5299004PWNHKYTR23649/ultimate-parent-relationship` | unchanged |
| `gleif/529900NNUPAGGOMPXZ31.json` | 200 | `https://api.gleif.org/api/v1/lei-records/529900NNUPAGGOMPXZ31` | unchanged |
| `gleif/529900VBK42Y5HHRMD23.json` | 200 | `https://api.gleif.org/api/v1/lei-records/529900VBK42Y5HHRMD23` | trimmed: eventGroups cut from 2 to 1 |
| `gleif/529900ZZZZZZZZZZZZ46.404.html` | 404 | `https://api.gleif.org/api/v1/lei-records/529900ZZZZZZZZZZZZ46` | unchanged; recorded with curl's default Accept header, which gets an HTML page instead of JSON |
| `gleif/529900ZZZZZZZZZZZZ46.404.json` | 404 | `https://api.gleif.org/api/v1/lei-records/529900ZZZZZZZZZZZZ46` | unchanged |
| `gleif/5493004330BCAPB3GT42.json` | 200 | `https://api.gleif.org/api/v1/lei-records/5493004330BCAPB3GT42` | trimmed: eventGroups cut from 5 to 1 |
| `gleif/5493004330BCAPB3GT42_ultimate-parent-relationship.json` | 200 | `https://api.gleif.org/api/v1/lei-records/5493004330BCAPB3GT42/ultimate-parent-relationship` | unchanged |
| `gleif/5493006W3QUS5LMH6R84.json` | 200 | `https://api.gleif.org/api/v1/lei-records/5493006W3QUS5LMH6R84` | unchanged |
| `gleif/549300PZLRJB7M8H1057.json` | 200 | `https://api.gleif.org/api/v1/lei-records/549300PZLRJB7M8H1057` | trimmed: eventGroups cut from 4 to 1 |
| `gleif/549300QS4Q1IT6XCA514.json` | 200 | `https://api.gleif.org/api/v1/lei-records/549300QS4Q1IT6XCA514` | trimmed: eventGroups cut from 2 to 1 |
| `gleif/549300QS4Q1IT6XCA514_direct-parent-reporting-exception.json` | 200 | `https://api.gleif.org/api/v1/lei-records/549300QS4Q1IT6XCA514/direct-parent-reporting-exception` | unchanged |
| `gleif/549300QS4Q1IT6XCA514_fund-manager-relationship.json` | 200 | `https://api.gleif.org/api/v1/lei-records/549300QS4Q1IT6XCA514/fund-manager-relationship` | unchanged |
| `gleif/549300QS4Q1IT6XCA514_ultimate-parent-reporting-exception.json` | 200 | `https://api.gleif.org/api/v1/lei-records/549300QS4Q1IT6XCA514/ultimate-parent-reporting-exception` | unchanged |
| `gleif/549300QS4Q1IT6XCA514_umbrella-fund-relationship.json` | 200 | `https://api.gleif.org/api/v1/lei-records/549300QS4Q1IT6XCA514/umbrella-fund-relationship` | unchanged |
| `gleif/7LTWFZYICNSX8D621K86.json` | 200 | `https://api.gleif.org/api/v1/lei-records/7LTWFZYICNSX8D621K86` | trimmed: bic list cut from 73 to 3; eventGroups cut from 11 to 1 |
| `gleif/7LTWFZYICNSX8D621K86_direct-children_size2_p1.json` | 200 | `https://api.gleif.org/api/v1/lei-records/7LTWFZYICNSX8D621K86/direct-children?page%5Bsize%5D=2&page%5Bnumber%5D=1` | unchanged |
| `gleif/7LTWFZYICNSX8D621K86_direct-children_size2_p2.json` | 200 | `https://api.gleif.org/api/v1/lei-records/7LTWFZYICNSX8D621K86/direct-children?page%5Bsize%5D=2&page%5Bnumber%5D=2` | unchanged |
| `gleif/7LTWFZYICNSX8D621K86_direct-parent-relationship.404.json` | 404 | `https://api.gleif.org/api/v1/lei-records/7LTWFZYICNSX8D621K86/direct-parent-relationship` | unchanged |
| `gleif/7LTWFZYICNSX8D621K86_direct-parent-reporting-exception.json` | 200 | `https://api.gleif.org/api/v1/lei-records/7LTWFZYICNSX8D621K86/direct-parent-reporting-exception` | unchanged |
| `gleif/7LTWFZYICNSX8D621K86_ultimate-parent-relationship.404.json` | 404 | `https://api.gleif.org/api/v1/lei-records/7LTWFZYICNSX8D621K86/ultimate-parent-relationship` | unchanged |
| `gleif/7LTWFZYICNSX8D621K86_ultimate-parent-reporting-exception.json` | 200 | `https://api.gleif.org/api/v1/lei-records/7LTWFZYICNSX8D621K86/ultimate-parent-reporting-exception` | unchanged |
