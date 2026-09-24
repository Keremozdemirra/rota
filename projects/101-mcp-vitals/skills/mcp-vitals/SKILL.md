---
name: mcp-vitals
description: Check MCP servers for maintenance, licence, deprecation and pinning. Use when the user asks to check, audit or clean up the MCP servers they have configured; asks whether an MCP server is maintained, abandoned, archived or licensed; or before you recommend or add an MCP server they have not installed yet.
---

# mcp-vitals

`doctor.py` in this plugin reads MCP client configs (Claude Code, Claude Desktop,
Cursor, VS Code, Windsurf, Gemini CLI, Codex), resolves each server to its npm or
PyPI package, container image or checkout, and reports on the repository behind it.
It reads `command`, `args` and `url` only, never `env` or `headers`.

## Everything configured on this machine

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/doctor.py" --json
```

## One server, before adding it

Pass the command line the server would be started with, or a package or repository:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/doctor.py" --json npx -y @scope/server-name
python3 "${CLAUDE_PLUGIN_ROOT}/doctor.py" --json pypi:mcp-server-fetch
python3 "${CLAUDE_PLUGIN_ROOT}/doctor.py" --json owner/repo
```

## Reporting back

- Lead with the servers whose `flags` include `archived`, `abandoned`, `deprecated`,
  `no licence file`, `repository missing` or `package not found`. Say what the flag
  means in plain words and quote `days_since_push` or the deprecation message.
- `unpinned` means the entry starts whatever version is newest each time. Mention it
  once, as an option, not an alarm.
- These are dates and registry fields, not a verdict on the code. A finished tool can
  go a year without a push and still work. Never call a server unsafe or bad on this
  evidence; say what the facts are and let the user decide.
- If the output says the GitHub API was unavailable, the facts came from the
  agent-vitals census and may be a day old. Suggest setting `GITHUB_TOKEN`.
- `--markdown` gives a table the user can paste into an issue or post, if they ask.
