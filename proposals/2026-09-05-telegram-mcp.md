# Proposal: chigwell/telegram-mcp

- **Repo:** https://github.com/chigwell/telegram-mcp
- **Source:** agent-vitals census, data/servers.json (2026-09-04 snapshot)
- **Stars:** 1,554 · **Forks:** 404 · **Open issues:** 37
- **Licence:** Apache-2.0 (SPDX-identified)
- **Language:** Python
- **Created:** 2025-03-20 · **Last push:** 2026-09-03 (1 day before the census — active)
- **Not archived, not a fork.**

## What it claims to do (from its own description and topics)

An MCP server built on Telethon that lets an MCP client read chats, manage
groups, and send/modify messages, media, contacts, and settings on Telegram.
Topics: `telegram`, `telegram-api`, `telegram-client`, `chat-management`,
`messaging`, `mcp`.

## Why this looks like a registry gap

`rota/registry.yaml`'s `scout.gaps` list names `telegram` explicitly, and no
existing route touches Telegram — the registry has Gmail-adjacent and
messaging-shaped routes (`daily-brief`, `inbox-triyaj`) but nothing that
reaches Telegram specifically.

## What would have to be true for it to be worth installing

- Kerem would need an actual use case for Telegram access from an agent —
  the registry lists the gap, but nothing in current project context
  (career search, ESG toolkit work, site work) obviously needs it today.
  This is the weakest part of the case: a listed gap isn't the same as a
  live need, and 37 open issues on a personal-account chat/message tool is
  worth reading before trusting it with real credentials.
- Telethon-based tools authenticate as a real Telegram user account (not a
  bot), which means the server would hold session credentials capable of
  reading and sending as Kerem — matches the red line in `~/.claude/CLAUDE.md`
  §6 about not giving unattended things more authority than needed and
  clearing scope expansions first, so this needs explicit sign-off on what
  the server can do before any credential is ever generated for it.
- Maintenance signal (37 open issues against 1,554 stars) should be read
  before installing, not just counted.

## Checks before installing

1. Read through the open issues for anything security-relevant (auth
   handling, credential storage, unbounded message access).
2. Confirm whether it requires a full user-account Telegram session
   (Telethon) vs. a bot token — the risk profile is very different, and a
   user-session credential should never be dropped into a repo file per
   the credentials red line.
3. Identify the actual task this would serve before installing it — a gap
   in the wishlist is not itself a reason to add a standing capability with
   account-level access.
