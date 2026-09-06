# Proposal: Graphify-Labs/graphify

**Status: NOT installed. Human approval required before any integration.**

| | |
| --- | --- |
| URL | https://github.com/Graphify-Labs/graphify |
| Description | Turn any codebase, with its docs, SQL schemas, configs, and PDFs, into a queryable knowledge graph. A /graphify skill for Claude Code, Cursor, Codex, and Gemini CLI: local deterministic AST parsing, every edge explained, no vector store. |
| Stars | 112768 |
| Last push | 2026-08-30 |
| License | Apache-2.0 |
| Found via | topic:claude-code |
| Score | **14.6** — stars=112768 → 10.1; pushed 1d ago → +2; license apache-2.0 → +1; matches gap pdf → +1.5 |

## Suggested registry entry (edit before use)

```yaml
- id: graphify
  desc: Turn any codebase, with its docs, SQL schemas, configs, and PDFs, into
  triggers: []          # fill with real phrasing, TR + EN
  tools: []             # minimum set only
  model: sonnet
  budget: M
  memory: false
```

## Approval checklist

- [ ] Read the source. All of it, or do not integrate it.
- [ ] License compatible (MIT/Apache preferred).
- [ ] Pin a commit hash, not a branch.
- [ ] It needs no credentials — or credentials stay in env, never in files.
- [ ] It earns its place: which existing route fails without it?

Approve by acting on it; discard by deleting this file. scout will not
re-propose it either way (tracked in tools/scout_state.json).
