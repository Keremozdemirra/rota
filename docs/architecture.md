# rota — architecture

One registry, three tiers, gated memory, propose-only self-improvement.
The published artifact renders the diagram; this file is the repo-local
source of truth.

## Request flow

```
                 request (TR/EN)
                       │
        ┌──────────────▼──────────────┐
        │ TIER 0 · trigger regex      │  0 tokens
        │ registry.yaml triggers      │──── unique hit ──┐
        └──────────────┬──────────────┘                  │
              ambiguous │ (several/none)                 │
        ┌──────────────▼──────────────┐                  │
        │ TIER 1 · haiku classifier   │  ~300 tokens     │
        │ sees id+desc table only     │                  │
        └──────────────┬──────────────┘                  │
                       └────────────┬────────────────────┘
                                    ▼
        ┌───────────────────────────────────────────┐
        │ TIER 2 · one worker                       │
        │ tools: route-scoped   model: per route    │
        │ budget: S/M/L         skill: loaded now   │
        │ memory: ≤800 tok recall, cited            │
        └───────┬───────────────────────┬───────────┘
                ▼                       ▼
             answer               MEMORY+ lines
                │                       ▼
                │             memory/_inbox/ (provenance)
                │                       ▼
                │              human review → promote
                ▼                       ▼
         ledger/usage.jsonl    CLAUDE.md / memory/*.md
```

## Memory tiers

| Tier | What | When loaded | Cost |
| --- | --- | --- | --- |
| hot | CLAUDE.md + DEVAM.md | session start | ~1-2k tokens |
| warm | memory/*.md via FTS5 | per request, if route.memory | ≤ ~800 tokens |
| cold | full file | only when a citation demands it | on demand |

Writes go the other way through one gate: worker → `MEMORY+` line →
`_inbox` (hashed, provenance-stamped, secret-scanned) → human review →
canonical file. The old memory failed because this gate did not exist.

## Self-improvement loop

```
scout.py ──GitHub search API──▶ score (stars, recency, license, gap match)
   │                                        │
   ▼                                        ▼
tools/scout_state.json (dedupe)     proposals/*.md
                                            │
                              human reads, approves or deletes
                                            │
                              registry.yaml entry (human commit)
                                            │
                              gen_agents.py → agents/*.md
```

The scout has no write access to the registry and executes nothing it
finds. Capability growth is a pull request against the registry, made by
a person.

## Hybrid deployment

Same registry, two frontends:

- **Native (Claude Code / Cowork):** `gen_agents.py` emits `agents/*.md`
  (link into `~/.claude/agents`); `skills/rota` and `skills/hafiza-ara`
  sync like every other skill. Routing happens by description matching,
  discipline comes from the skills.
- **SDK (headless):** `python -m router run "..."` for the weekly job and
  for batch work. Same routes, same budgets, plus the ledger. It once also
  served a daily loop, which was retired on 2026 08 25.

## Directory tree

```
~/agents/
├── CLAUDE.md                 hot memory (≤100 lines, gated writes only)
├── DEVAM.md                  where work left off
├── memory/                   warm tier — Obsidian-compatible vault
│   ├── kararlar.md           decision log, dated, with rationale
│   ├── repolar.md            repo inventory
│   ├── altyapi.md            infrastructure notes
│   ├── araclar.md            tooling notes
│   ├── kariyer.md            career notes (rebuilt empty)
│   ├── _inbox/               candidate facts awaiting review (not indexed)
│   └── _index/               ltm.sqlite (derived, gitignored)
├── rota/                     ← this repo (the only one with a runtime)
│   ├── registry.yaml         single source of truth
│   ├── router/               __main__, config, triage, dispatch,
│   │                         mem_inbox, ledger
│   ├── tools/                ltm.py, scout.py, gen_agents.py, inbox_add.py,
│   │                         eval_routes.py + fixtures/routes_eval.yaml
│   ├── agents/               generated subagents (from registry)
│   ├── skills/               rota, hafiza-ara
│   ├── docs/                 architecture.md, token-rules.md
│   ├── proposals/            scout output — approval inbox
│   └── ledger/               usage.jsonl
├── agent-kit/                conventions (unchanged)
└── *-agent/                  11 domain repos (unchanged)
```
