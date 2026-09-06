# rota weekly brief — 2026-09-05

## Tokens by route
```
route             runs   t0%    in_tok   out_tok      usd
---------------------------------------------------------
memory-recall        1  100%        18       896   0.0609
```

## Scout
```
[scout] claude-skill: fetch failed (<urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate (_ssl.c:1082)>) — skipping
[scout] claude-code: fetch failed (<urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate (_ssl.c:1082)>) — skipping
[scout] mcp-server: fetch failed (<urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate (_ssl.c:1082)>) — skipping
[scout] agent-skills: fetch failed (<urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate (_ssl.c:1082)>) — skipping
0 new proposal(s); 6 repos tracked; nothing installed.
```

## Drift — recorded vs actual
```
installed  skills:38 · agents:33 · mcp:15 · plugins:10 · enabled_plugins:10 · unauthorised:2
changes    none since last run
wrote memory/_generated/inventory.md
```

## Context cost — is CLAUDE.md §8 holding?
```
last 7d · 136 sessions · 12 largest sampled
tool                    calls   avg bytes   share   vs last
Read                      794     168,905   71.1%       -0%
mcp__Claude_Browser__     532      36,810   10.4%       -0%
Bash                    12686         901    6.1%       +0%
mcp__plugin_chrome-de      49     190,479    5.0%       +0%
mcp__Claude_Browser__     281      30,840    4.6%       +0%
mcp__playwright__brow     156      10,899    0.9%       +0%
mcp__computer-use__ap       7      73,822    0.3%       +0%
mcp__computer-use__ap      13      39,339    0.3%       +0%
```

## Diagrams — re-rendered from source
```
[ok] memory-and-drift.architecture.json → memory-and-drift.html
```

## MCP endpoints — does the record still describe reality?
```
  14 remote endpoints · 13 answering · 1 local (not probed)
    [unreachable] gitmcp: curl exit 28: 

  → a recorded server that cannot answer is not a capability. Decide:
    fix the address, or remove it and write down why.
```

## Ecosystem census — what the ground looks like
```
warning: in the working copy of 'data/history.csv', CRLF will be replaced by LF the next time Git touches it
  census 2026-09-04 · 36,593 repositories
    active       17,376   47.5%
    slowing       7,064   19.3%
    stale         9,360   25.6%
    abandoned     2,223    6.1%
    no licence    6,117   16.7%  — grants nothing, whatever the README says
    non-standard  2,846    7.8%  — licensed, but not in a form procurement accepts
  totals agree with the committed history.csv. The working copy of that
  file differs from HEAD — the check read what was published, not what
  is on disk, which is the intent; noted so the provenance is visible.
```

## Arrivals — what the daily census brought, after vetting.yaml
```
## 2026-09-05
```
  census 2026-09-04: one run so far, so nothing is new yet.
  Arrivals separate from the baseline on the second run.
```

```

## Lessons — captured, waiting to be acted on
```
  44 open · 9 resolved (9 filed to archive/) · last review: 2026-08-31
  oldest has waited 11 days
  by skill — the cluster is the signal, not the age:
     4  new-project-scaffold  ← fix this one next
     4  proje  ← fix this one next
     4  New skill candidate: filesystem-tidy  ← fix this one next
     4  New skill candidate: behaviour-benchmark  ← fix this one next
     3  task-observer  ← fix this one next
     2  New skill candidate: third-party-tool-vettin
```

## Memory inbox — pending review
- [ ] Reviewed and applied to `memory/araclar.md`
- [ ] Reviewed and applied to `memory/araclar.md`

## Proposals awaiting a decision
- 2026-08-31-affaan-m-ecc.md
- 2026-08-31-graphify-labs-graphify.md
- 2026-08-31-nexu-io-open-design.md
- 2026-09-05-keeper-sh.md
- 2026-09-05-pdf-reader-mcp.md
- 2026-09-05-telegram-mcp.md

Ritual: promote checked inbox facts → CLAUDE.md / memory/*.md; approve or delete proposals; tune the most expensive route.
