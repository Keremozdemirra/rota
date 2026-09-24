# mcp-vitals

**Before Claude adds an MCP server, find out whether anyone still maintains it.**

MCP servers are installed with one line and then forgotten. The line usually says
`npx -y some-package`, which starts whatever version is newest every time the
client opens, from a repository nobody on your side has looked at since. Some of
those repositories are archived. Some packages are deprecated on npm and still sit
in thousands of configs. Some never had a licence.

`mcp-vitals` checks. It reads the MCP configs on your machine, works out which
package or repository each server starts, and reports what the registries and
GitHub say about it. As a Claude Code plugin it does the same thing at the moment
a server is added, and asks you before it goes in.

```
server      client    starts                                   repository                status     push  licence  flags
----------  --------  ---------------------------------------  ------------------------  ---------  ----  -------  --------------------------------------------
github      --config  npm:@modelcontextprotocol/server-github                            unknown                   deprecated, unpinned, no source repository linked
whatsapp    --config  lharries/whatsapp-mcp                    lharries/whatsapp-mcp     abandoned  438d  MIT      abandoned, unpinned
github-new  --config  ghcr.io/github/github-mcp-server         github/github-mcp-server  active     2d    MIT      unpinned

3 servers · 1 unknown · 1 abandoned · 1 active · 2 worth a look · 3 unpinned
```

Real output for three real servers, 2026-09-24. The npm package in the first row
is deprecated on npm; GitHub now publishes its own server, in the third row.

## Install

### Claude Code plugin

```
/plugin marketplace add Keremozdemirra/mcp-vitals
/plugin install mcp-vitals@mcp-vitals
```

That adds:

- **A hook on `claude mcp add`.** If the server Claude is about to add is archived,
  abandoned, deprecated, gone, or has no licence file, you get a permission prompt
  with the facts before the command runs. Healthy servers pass without a prompt.
- **A hook on MCP config edits.** When Claude writes `.mcp.json`,
  `claude_desktop_config.json`, `.cursor/mcp.json` and the like, the same facts
  for the servers it just added go back to Claude, which tells you.
- **A skill.** Ask "check my MCP servers" or "is this MCP server maintained?" and
  Claude runs the check and explains the result.

The hooks need `python3` on your `PATH`. They never deny anything; the decision is
yours.

### Command line

No install, standard library only:

```bash
curl -sL https://raw.githubusercontent.com/Keremozdemirra/mcp-vitals/main/doctor.py | python3 -
```

Or from PyPI:

```bash
uvx mcp-vitals                                  # every server in every config found
uvx mcp-vitals npx -y @scope/some-server        # one server, before you add it
uvx mcp-vitals owner/repo                       # or a repository
uvx mcp-vitals --markdown                       # a table to paste into an issue
```

| Option | What it does |
| --- | --- |
| `--json` | Machine-readable output. |
| `--markdown` | A Markdown table, for an issue or a post. |
| `--strict` | Exit 1 if any server is archived, abandoned, deprecated, gone or unlicensed. |
| `--offline` | Send nothing; report only what the configs say. |
| `--config PATH` | Read another config file too. Repeatable. |

### In CI

Guard a shared `.mcp.json` so an abandoned server does not slip into the repository:

```yaml
- run: pipx run mcp-vitals --strict --config .mcp.json
```

### As a hook, without the plugin

```json
{
  "hooks": {
    "PreToolUse": [{ "matcher": "Bash", "hooks": [{ "type": "command", "if": "Bash(claude mcp add*)", "command": "uvx --from mcp-vitals mcp-vitals-hook", "timeout": 20 }] }],
    "PostToolUse": [{ "matcher": "Write|Edit|MultiEdit", "hooks": [{ "type": "command", "command": "uvx --from mcp-vitals mcp-vitals-hook", "timeout": 20 }] }]
  }
}
```

## What it reads, what it sends

- **Reads:** the `command`, `args` and `url` of each MCP entry in the configs of
  Claude Code, Claude Desktop, Cursor, VS Code, Windsurf, Gemini CLI and Codex.
  **Never** `env` or `headers`, which is where API keys live. The tests check this.
- **Sends:** package names to the npm and PyPI registries, `owner/name` to the GitHub
  API. Nothing else, and nothing with `--offline`.
- **Runs:** nothing. No server is started, no package installed.

Without a `GITHUB_TOKEN`, the GitHub API allows 60 requests an hour. Past that, the
CLI falls back to the daily [agent-vitals](https://github.com/Keremozdemirra/agent-vitals)
census of about 40,000 agent-tooling repositories, and says so. The hook skips the
fallback, because someone is waiting.

## What the flags mean

| Flag | Meaning |
| --- | --- |
| `archived` | The owner archived the repository. It is read-only. |
| `abandoned` | No push in over a year. |
| `deprecated` | The npm package is deprecated, or the PyPI release was yanked. The message is shown. |
| `no licence file` | GitHub found no licence. By default nobody else may use, copy or modify the code. |
| `non-standard licence` | A licence file exists, but GitHub cannot match it to a standard one. Read it. |
| `repository missing` | The linked repository is deleted, renamed or private. |
| `package not found` | The registry does not know the package. |
| `unpinned` | The entry starts whatever version is newest each time: `npx -y pkg`, `uvx pkg`, `:latest`. |
| `no source repository linked` | The package names no repository, so the rest cannot be checked. |

Status uses the same thresholds as the census: `active` means a push within 30
days, `slowing` 31 to 90, `stale` 91 to 365, `abandoned` over a year.

## What this is not

These are dates, flags and licence fields from public metadata. They are not a
security audit and not a verdict on anyone's code. A finished, correct tool can go
a year without a push and still work, and an active repository can still ship a bad
release. `mcp-vitals` tells you what is known, so you decide with the facts in front
of you.

## Licence

MIT.
