# BACKLOG

## Done

- [x] registry.yaml — routes for the 11 domain repos + kit orchestration,
  budgets, model tiers, scout config (2026-08-24)
- [x] router: Tier-0 regex triage, Tier-1 haiku classifier, narrow
  dispatch, S/M/L budgets, JSONL ledger + report (2026-08-24)
- [x] ltm.py: FTS5 index over the vault, mtime auto-refresh, cited
  retrieval, LIKE fallback for sqlite builds without FTS5 (2026-08-24)
- [x] gated memory inbox: MEMORY+ protocol, hash dedupe, secret scan,
  provenance stamps (2026-08-24)
- [x] scout.py: GitHub topic search, scoring, dedupe state, proposal
  files with approval checklist — propose-only (2026-08-24)
- [x] gen_agents.py + skills/rota + skills/hafiza-ara — native bridge
  (2026-08-24)
- [x] docs: architecture.md, token-rules.md (2026-08-24)

## Queue

- [ ] 001 — weekly distill: reviewed `_inbox` facts → canonical files as a
  guided flow (extends hafiza-guncelle rather than replacing it)
- [ ] 002 — scheduled scout: weekly run via a scheduled task, proposals
  surfaced in the Monday session
- [ ] 003 — ledger → simple HTML panel (reuse agent-kit tools/inventory
  rendering approach)
- [ ] 004 — embeddings upgrade for ltm.py behind the same search CLI, only
  if FTS5 recall demonstrably misses (record misses first)
- [ ] 005 — route-level eval set: 30 real requests with expected route ids,
  run in CI to catch trigger drift
