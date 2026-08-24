"""rota — registry-driven orchestrator for the ~/agents ecosystem.

Routes a request to exactly one narrow worker instead of loading every
skill and agent into one context. Three tiers:

  Tier-0  regex fast path            0 tokens
  Tier-1  haiku classifier           ~300 tokens, only when Tier-0 is ambiguous
  Tier-2  narrow worker              route-scoped tools, model and budget

Memory recall (SQLite FTS5 over the Obsidian-compatible vault) is injected
per route; durable facts exit through a gated inbox, never straight into
canonical memory files.
"""

__version__ = "0.1.0"
