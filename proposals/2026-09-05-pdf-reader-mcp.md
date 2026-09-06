# Proposal: SylphxAI/pdf-reader-mcp

- **Repo:** https://github.com/SylphxAI/pdf-reader-mcp
- **Source:** agent-vitals census, data/servers.json (2026-09-04 snapshot)
- **Stars:** 915 · **Forks:** 81 · **Open issues:** 2
- **Licence:** MIT (SPDX-identified)
- **Language:** TypeScript
- **Created:** 2025-04-04 · **Last push:** 2026-09-04 (same day as the census — actively maintained)
- **Not archived, not a fork.**

## What it claims to do (from its own description and topics)

An MCP server that gives an AI agent "eyes for PDFs": it returns structured
text, extracted tables, OCR output for scanned/image content, and
page-level citations back to the source document, positioned as a
"native Rust, local-first" tool (despite the repo language tag reading
TypeScript — worth resolving before trusting the local-first / no-cloud-call
claim). Topics: `pdf`, `ocr`, `document-processing`, `document-intelligence`,
`citations`, `mcp`.

## Why this looks like a registry gap

`rota/registry.yaml`'s `scout.gaps` list names `pdf` and `ocr` explicitly,
and neither appears in any existing route's tools or skills — there is
currently no PDF- or OCR-handling capability wired into rota at all. Kerem's
own work (CBAM/ESG source documents, `source-check` requirements) routinely
involves pulling numbers out of published PDFs; this repo would fill both
listed gaps with a single dedicated server rather than two separate tools.

## What would have to be true for it to be worth installing

- The "native Rust" claim in the description needs reconciling with the
  repo's actual TypeScript language tag — if it shells out to a bundled
  Rust binary that's fine, but if the description is simply wrong that's a
  documentation-quality flag worth noting before trusting other claims (like
  "local-first").
- OCR quality and page-citation accuracy need a hands-on check against a
  real CBAM/ESG-style scanned PDF, not just the README's examples.
- Its MCP tool surface needs to actually integrate cleanly with the
  `uygulayici`/`veri-analisti` style workers rota already routes to, without
  pulling in a heavyweight runtime dependency the project doesn't already have.
- License (MIT) is unambiguous and workplace-safe, so no legal blocker there.

## Checks before installing

1. Clone and run it against one real ESG/CBAM PDF Kerem already has, compare
   extracted numbers against the source by hand.
2. Confirm what actually runs locally vs. what (if anything) is a cloud
   call — the "local-first" claim should be verified, not assumed.
3. Check the two open issues for known extraction failure modes.
4. Confirm it doesn't duplicate anything `poppler` (already on PATH per
   `memory/araclar.md`) already covers well enough that a new dependency
   isn't worth adding.
