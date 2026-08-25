# rota

The routing layer for this agent ecosystem — and the only repository here
with a runtime.

Every other repo follows the agent-kit rule that skills fire on their
descriptions. That works, but it leaves two costs on the table: every
resident description is rent paid on every request, and nothing measures
where tokens actually go. rota closes both: requests are routed to exactly
one narrow worker (regex first — free; a haiku classifier only on
ambiguity), long-term memory is retrieved instead of re-read, every
dispatch lands in a ledger, and new capabilities arrive as reviewed
proposals rather than as impulse installs.

## The four pieces

| Piece | Where | What it does |
| --- | --- | --- |
| Orchestrator | `registry.yaml` + `router/` | Tier-0 regex → Tier-1 haiku → one worker with route-scoped tools, model, budget |
| Long-term memory | `../CLAUDE.md`, `../DEVAM.md`, `../memory/` + `tools/ltm.py` | Obsidian-compatible vault; FTS5 recall ≤ ~800 tokens, cited; writes gated through `_inbox` review |
| Self-improvement | `tools/scout.py` → `proposals/` | GitHub discovery, scored; proposes registry entries; **never installs** |
| Token standard | `docs/token-rules.md` | The ten rules every session and agent here follows |

Three things are built on top of those four:

| Piece | Where | Docs |
| --- | --- | --- |
| video-mcp | `mcpservers/video/` | Generate, encode and embed real video from a Claude session — [docs/video-mcp.md](docs/video-mcp.md) |
| Platform | `service/` | BYO-key web front end running the workflows on the caller's key — [docs/platform.md](docs/platform.md) |
| Weekly pipeline | `pipeline/` | One backlog line → one finished project → one PR, weekly — [docs/weekly-pipeline.md](docs/weekly-pipeline.md) |

```bash
rota serve            # platform on http://127.0.0.1:8787
rota build --dry-run  # next weekly project, no model call
```

## Quick start

```bash
cd ~/agents/rota
pip install -r requirements.txt     # pyyaml; claude-agent-sdk for live runs

python3 tools/ltm.py index          # build the memory index
python3 tools/ltm.py search "rota kararı"

python -m router routes             # see the routing table
python -m router run "cv'yi şu ilana uyarla" --dry-run   # free routing check
python -m router run "..."          # live dispatch (needs the SDK + auth)
python -m router report             # tokens by route

python3 tools/scout.py --offline    # discovery demo, no network
python3 tools/gen_agents.py         # registry → agents/*.md for native use
```

`--dry-run` and `ltm.py` need neither network nor the SDK — routing and
recall are free to test.

## Native use (Claude Code / Cowork)

`skills/rota` and `skills/hafiza-ara` sync like every other skill in this
ecosystem; `agents/*.md` (generated) link into `~/.claude/agents`. The
registry stays the single source of truth — edit it, rerun
`gen_agents.py`, done.

## What this is not

- Not a framework: one YAML file, four small tools, stdlib everywhere the
  SDK isn't strictly needed.
- Not autonomous self-modification: the scout proposes, a human approves.
  Memory promotion is a human step. Both by decision
  (`../memory/kararlar.md`, 2026-08-24), not by omission.

## Layout

See `docs/architecture.md` for the full tree and data flows.

## Licence

MIT. See [LICENSE](LICENSE).
