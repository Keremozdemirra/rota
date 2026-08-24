---
name: hafiza-ara
description: Search long-term memory before answering anything about past decisions, preferences, project state, or people. Use when the user says "hatırla", "ne karar vermiştik", "nerede kalmıştık", "geçen sefer", "remember", "what did we decide", "last time", or when a request depends on context from earlier sessions.
---

# hafiza-ara — grounded recall

Memory questions are answered from the vault, with citations — never from
model memory. This is the NotebookLM principle applied locally: retrieval
returns sources, and the answer must stand on them.

## Procedure

1. Hot tier first (cheap, usually enough):

       python3 ~/agents/rota/tools/ltm.py hot

   `CLAUDE.md` + `DEVAM.md` — identity, rules, where work left off.

2. If the question needs detail, search the warm tier:

       python3 ~/agents/rota/tools/ltm.py search "<3-8 word query>" --k 6

   The index refreshes itself from file mtimes; no manual reindex needed.

3. Answer from the returned chunks and cite each used path, e.g.
   `(memory/kararlar.md » 2026-08-24 rota)`.

## Rules

- No hits → say "bu hafızada yok" and offer to record it. Never fill the
  gap with a plausible guess — that is exactly the failure that got the
  old memory quarantined.
- Do not cat whole memory files into context; the search output (≤ ~800
  tokens) is the budget.
- `memory/_inbox/` is unreviewed and off-limits for answers.
- On the user's computer the vault lives at `~/agents`; from a Cowork
  cloud session, run the same commands through the device bridge.
