# Token rules — the systemic standard

Every rule here exists because context is billed twice: once as money,
once as attention — a model reasoning over irrelevant context produces
worse answers, not just pricier ones. These rules bind every session,
skill, and agent in this ecosystem.

## 1. Resident bytes are rent

Anything always loaded — CLAUDE.md, skill descriptions, MCP tool schemas —
is paid on every single request. Budget them like rent:

- CLAUDE.md ≤ 100 lines. Overflow moves to `memory/` and is retrieved.
- Skill `description` ≤ ~40 words, written to fire on real phrasing
  (agent-kit standard). The body is pay-per-use; the description is not.
- MCP servers with unused tool schemas get disconnected. Deferred loading
  (ToolSearch-style) where the platform offers it.

## 2. Route before you load

One request → one route → one capability's context. The three tiers:

| Tier | Mechanism | Cost |
| --- | --- | --- |
| 0 | trigger regex over the registry | 0 tokens |
| 1 | haiku classifier, route table only | ~300 tokens |
| 2 | one worker, route-scoped tools | the job itself |

Loading two skills for one job means the routing failed — fix the
triggers, do not widen the load.

## 3. Model tiering

Cheapest model that survives the job: haiku for triage, recall and
mechanical transforms; sonnet as the working default; opus/deep only for
planning and adversarial verification (mimar/doğrulayıcı roles). The
tier lives in the registry, not in habit.

## 4. Context carries conclusions, not evidence

Subagents read the files, run the greps, hold the dumps — and return
structured findings. Raw file contents never cross an agent boundary.
Corollary for replies: tables for data, prose for reasoning, no restating
the request, no recap of steps.

## 5. Memory beats history

Re-reading old conversations is the most expensive way to remember.
The vault replaces it: hot tier (CLAUDE.md + DEVAM.md, ~2 files, always),
warm tier (FTS5 search, ≤ ~800 tokens injected), cold tier (full file
only when a citation demands it). New chats are ~16x the marginal cost of
continuing one — one conversation per topic.

## 6. Writes are distilled and gated

A durable fact is one sentence, verifiable, source-stamped
(`MEMORY+ … → _inbox → review`). Never paragraphs, never inferred, never
straight into canonical files. A wrong memory is worse than no memory —
it gets injected into every future request that matches it.

## 7. Cache-shaped prompts

Stable prefix, volatile tail. System prompts and route tables change
rarely and in whole; timestamps, request text, and memory blocks go last.
This keeps prompt-cache hit rates high on every platform that caches.

## 8. Budgets are contracts, not vibes

Every route declares S/M/L: max turns and a target output size injected
into the worker's prompt. Exceeding budget is a defect to fix in the
registry, not a mood of the model.

## 9. Measure, then cut

The ledger (`ledger/usage.jsonl`, `python -m router report`) says which
route actually burns tokens. Optimize the top line of the report, not the
rule you most recently read about. Anything uninstrumented is assumed
expensive.

## 10. Zero-token paths are the best paths

If a regex, a SQL query, or 30 lines of Python answers deterministically,
no model call happens at all. Tier-0 routing, FTS5 recall, the scout's
scoring — all deliberately model-free. The best prompt is the one never
sent.
