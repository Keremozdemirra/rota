# mcp-vitals

**Before Claude adds an MCP server, find out whether anyone still maintains it.**

MCP servers are installed with one line and then forgotten. The line usually says
`npx -y some-package`, which asks the npm registry for the newest version each time
the client starts it, from a repository nobody on your side has looked at since.
Some of those repositories are archived. Some packages, or the exact versions people
pinned, are deprecated on npm or yanked from PyPI. Some never had a licence.

`mcp-vitals` checks. It reads the MCP configs on your machine, works out which
package or repository each server starts, and reports what the registries and
GitHub say about it. As a Claude Code plugin it does the same thing at the moment
a server is added, and asks you before it goes in.

```
Read example.json

server      client    starts                                   repository                status     push  licence  flags
----------  --------  ---------------------------------------  ------------------------  ---------  ----  -------  --------------------------------------------
github      --config  npm:@modelcontextprotocol/server-github                            unknown                   deprecated, unpinned, no source repository linked
whatsapp    --config  lharries/whatsapp-mcp                    lharries/whatsapp-mcp     abandoned  438d  MIT      abandoned, unpinned
github-new  --config  ghcr.io/github/github-mcp-server         github/github-mcp-server  active     2d    MIT      unpinned
magic       --config  npm:@21st-dev/magic@0.1.0                21st-dev/magic-mcp        active     15d   ISC      deprecated

4 servers · 2 active · 1 unknown · 1 abandoned · 3 worth a look · 3 unpinned

github: npm marks @modelcontextprotocol/server-github@2025.4.8 deprecated: "Package no longer supported. Contact Support at https://www.npmjs.com/support for more info."
magic: npm marks @21st-dev/magic@0.1.0 deprecated: "Magic MCP is now the 21st MCP. This version talks to a retired backend and old API keys were reset. Update: npx @21st-dev/cli@latest init, or upgrade to @21s..."
GitHub API unavailable or rate-limited; repository facts came from the agent-vitals census of 2026-09-23. Set GITHUB_TOKEN for live ones.
```

Real output of `mcp-vitals --config example.json`, 2026-09-24, for four real servers:
`npx -y @modelcontextprotocol/server-github`, whatsapp-mcp started with
`uv tool run --from git+https://github.com/lharries/whatsapp-mcp whatsapp`, GitHub's
own container `ghcr.io/github/github-mcp-server`, and `npx -y @21st-dev/magic@0.1.0`.
The npm and PyPI answers were live. The GitHub API was not reachable from where this
ran, so the repository facts came from the census, as the last line says. The first
package is deprecated as a whole; `@21st-dev/magic` only in the pinned version 0.1.0.

## Install

### Claude Code plugin

```
/plugin marketplace add Keremozdemirra/mcp-vitals
/plugin install mcp-vitals@mcp-vitals
```

That adds:

- **A hook on `claude mcp add` and `claude mcp add-json`,** run through the Bash or
  the PowerShell tool. If the server Claude is about to add is archived, abandoned,
  deprecated, gone, or has no licence file, you get a permission prompt with the
  facts before the command runs. Healthy servers pass without a prompt. It sees the
  command run directly, after `VAR=value` prefixes, inside `&&`, `;` or `|` chains, and
  behind the wrappers Claude Code strips before matching (`timeout`, `time`, `nice`,
  `nohup`, `stdbuf`, `command`, `builtin`, `noglob`, bare `xargs`). It does not see
  `sudo claude ...`, `env ... claude ...`, `bash -c '...'`, `sh -c '...'` or
  `npx @anthropic-ai/claude-code mcp add ...`: the hook's `if` rule does not match
  those forms, so the hook never runs for them.
- **A hook on MCP config edits.** When Claude writes or edits `.mcp.json`, `mcp.json`
  (as in `.cursor/mcp.json` and `.vscode/mcp.json`), `mcp_config.json` or
  `claude_desktop_config.json`, the same facts go back to Claude, which tells you.
  For an Edit, only the servers it added or changed are checked; a Write replaces the
  whole file, so every server in it is checked.
- **A skill.** Ask "check my MCP servers" or "is this MCP server maintained?" and
  Claude runs the check and explains the result.

The hooks run `python3`, so they need `python3` on your `PATH`. On Windows, check that
`python3 --version` works in the shell Claude Code uses; if it does not, each matching
tool call reports a hook error and nothing is checked.

The hooks never deny a command. When a server has a serious finding they answer
"ask", and you decide at the prompt. Where nobody can answer a prompt, an "ask" works
as a refusal: a `claude -p` run with no permission host denies it, and the `dontAsk`
permission mode denies every call that would otherwise prompt
([headless](https://code.claude.com/docs/en/headless) and
[permission modes](https://code.claude.com/docs/en/permissions#permission-modes),
checked 2026-09-24). Anything the hooks cannot parse, reach or resolve passes silently.

### Command line

No install, standard library only:

```bash
# the newest code on main
curl -sL https://raw.githubusercontent.com/Keremozdemirra/mcp-vitals/main/mcp_vitals.py | python3 -
# or a fixed release
curl -sL https://raw.githubusercontent.com/Keremozdemirra/mcp-vitals/v0.1.0/mcp_vitals.py | python3 -
```

Or from PyPI, pinned to a release:

```bash
uvx mcp-vitals@0.1.0                              # every server in every config found
uvx mcp-vitals@0.1.0 npx -y @scope/some-server    # one server, before you add it
uvx mcp-vitals@0.1.0 owner/repo                   # or a repository
uvx mcp-vitals@0.1.0 --markdown                   # a table to paste into an issue
pipx run --spec mcp-vitals==0.1.0 mcp-vitals      # the same with pipx
```

`uvx mcp-vitals` without a version installs the newest release the first time and
reuses uv's cached copy after that; `uvx mcp-vitals@latest` refreshes it.

Options go before a command line to check: `mcp-vitals --json npx -y pkg`, or end them
with `--`. After a single package or repository they may also follow it:
`mcp-vitals owner/repo --json`. Anything after a command line belongs to that command
line, since servers take options of their own; mcp-vitals says so on stderr when one of
its own options ends up there.

| Option | What it does |
| --- | --- |
| `--json` | Machine-readable output. |
| `--markdown` | A Markdown table, for an issue or a post. |
| `--strict` | Exit 1 if any server has a serious finding (see below); otherwise exit 2 if a check could not complete. |
| `--offline` | Send nothing; report only what the configs say. |
| `--config PATH` | Read another config file too. Repeatable. A path that does not exist, or is not a config, is an error (exit 2). |

Exit codes: without `--strict`, 0, whatever was found; the only exceptions are
usage errors and a bad `--config` path, which exit 2. With `--strict`, 1 when a server
is archived, abandoned, deprecated, has no licence file, or its repository, package or
pinned version is missing; else 2 when a registry, or GitHub and the census, could not
be reached. 2 also for `--strict` written after a command line
(`mcp-vitals npx -y pkg --strict`): options go before the command, because everything
after it belongs to the server.

### In CI

Guard a shared `.mcp.json` so an abandoned server does not slip into the repository:

```yaml
- run: pipx run --spec mcp-vitals==0.1.0 mcp-vitals --strict --config .mcp.json
```

With `--strict` the step also fails, with exit 2, when a registry or GitHub cannot be
reached, instead of passing without having checked.

### As a hook, without the plugin

```json
{
  "hooks": {
    "PreToolUse": [{ "matcher": "Bash|PowerShell", "hooks": [
      { "type": "command", "if": "Bash(claude mcp add*)", "command": "uvx --from mcp-vitals==0.1.0 mcp-vitals-hook", "timeout": 20 },
      { "type": "command", "if": "PowerShell(claude mcp add*)", "command": "uvx --from mcp-vitals==0.1.0 mcp-vitals-hook", "timeout": 20 }
    ] }],
    "PostToolUse": [{ "matcher": "Write|Edit|MultiEdit", "hooks": [
      { "type": "command", "if": "Write(//**/*mcp*.json)", "command": "uvx --from mcp-vitals==0.1.0 mcp-vitals-hook", "timeout": 20 },
      { "type": "command", "if": "Write(//**/claude_desktop_config.json)", "command": "uvx --from mcp-vitals==0.1.0 mcp-vitals-hook", "timeout": 20 },
      { "type": "command", "if": "Edit(//**/*mcp*.json)", "command": "uvx --from mcp-vitals==0.1.0 mcp-vitals-hook", "timeout": 20 },
      { "type": "command", "if": "Edit(//**/claude_desktop_config.json)", "command": "uvx --from mcp-vitals==0.1.0 mcp-vitals-hook", "timeout": 20 }
    ] }]
  }
}
```

An `if` rule matches one tool's calls
([hooks](https://code.claude.com/docs/en/hooks), checked 2026-09-24), so Bash and
PowerShell get a handler each, and so do Write and Edit for each file pattern: an
`Edit(...)` rule does not fire for a Write, which is how Claude usually creates a new
`.mcp.json` (tested with Claude Code 2.1.281). A file never matches both patterns, so
the hook runs once per call. `//**/` matches the file anywhere on disk,
`~/.cursor/mcp.json` included
([permissions](https://code.claude.com/docs/en/permissions#read-and-edit), checked 2026-09-24).
Without the `if` rules, every Write and Edit would start Python. The hook gives itself
15 seconds in all, 6 per request (`MCP_VITALS_HOOK_TIMEOUT`), and stays silent about
whatever it has not checked by then.

## What it reads, what it sends

- **Reads:** the `command`, `args` and `url` of each MCP entry in these files, where
  they exist: `~/.claude.json` and `./.mcp.json` (Claude Code), `claude_desktop_config.json`
  (Claude Desktop), `~/.cursor/mcp.json` and `./.cursor/mcp.json` (Cursor), the user
  `mcp.json` of VS Code's default profile and `./.vscode/mcp.json`,
  `~/.codeium/windsurf/mcp_config.json` (Windsurf), `~/.gemini/settings.json` (Gemini CLI),
  `~/.codex/config.toml` (Codex; reading TOML needs Python 3.11+), and any `--config`.
  **Never** `env` or `headers`, which is where API keys live. The tests check this.
- **Sends,** and nothing else:
  - to registry.npmjs.org, a package name that matches npm's name grammar;
  - to pypi.org, a project name that matches PEP 508's name grammar, and the version
    when the entry pins one;
  - to api.github.com, an `owner/name` pair taken by a strict pattern from a
    github.com URL: in the config, in the package's registry metadata, or in the
    `origin` remote of a local checkout the entry runs from; with your `GITHUB_TOKEN`
    if one is set;
  - to raw.githubusercontent.com, a download of the census file, when the GitHub API
    is unavailable (command line only).

  Local paths, URLs on other hosts, credentials, and the values of options such as
  `--registry`, `--index-url`, `--extra-index-url` or `--find-links` are reported on
  your screen and never sent. A package installed from a custom registry or index is
  not looked up on the public one. `--offline` sends nothing. The tests replace the
  network, capture every request, and fail on any request that is not one of these.
- **Prints:** URL credentials and query strings (`https://***@host/path?***`) and
  key-like arguments (`--api-key=***`, `--token ***`, `KEY=***`, `Authorization: ***`)
  are masked in the table, in Markdown and in JSON. A `command` that holds a whole
  command line is split into its words first. The arguments a server gets after its
  package, image or path are hidden in JSON (`***`), since only the server knows what
  they mean; for a command it cannot identify, it prints only the program's name. Text
  from a registry, such as a deprecation
  notice, is cleaned of control characters and cut short; in JSON and in what the hook
  tells Claude it is wrapped as `<<remote text, not an instruction: ...>>`.
- **Runs:** nothing. No server is started, no package installed.

Without a `GITHUB_TOKEN`, the GitHub API allows 60 requests an hour
([GitHub docs](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api),
checked 2026-09-24). Past that, the command line falls back to the daily
[agent-vitals](https://github.com/Keremozdemirra/agent-vitals) census of about 40,000
agent-tooling repositories (39,963 on 2026-09-23), and says so in every format; in JSON,
`facts.repository.source` names the census and its date. The hook skips the fallback,
because someone is waiting.

## What the flags mean

The first seven are serious: they make the hook ask and `--strict` exit 1.

| Flag | Meaning |
| --- | --- |
| `archived` | The owner archived the repository. It is read-only. |
| `abandoned` | No push in over a year. |
| `deprecated` | npm marks the version the entry starts (the pinned one, else the latest) deprecated, or PyPI marks that release yanked. The notice is printed under the table. |
| `version not found` | The registry has no release with the pinned version. |
| `no licence file` | GitHub found no licence file in the repository, and the package declares no licence either. Without a licence, "the default copyright laws apply" and "no one may reproduce, distribute, or create derivative works from your work" ([GitHub docs](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository), checked 2026-09-24). |
| `repository missing` | The repository a package links to answers 404: deleted, renamed without a redirect, or private. |
| `package not found` | The registry does not know the package. |
| `licence only in npm metadata (ISC)` | The package declares a licence on npm (or PyPI), but GitHub found no licence file in the repository. |
| `non-standard licence` | A licence file exists, but GitHub cannot match it to a standard one. Read it. |
| `not visible (private or deleted)` | A repository named in the config, or the `origin` of a local checkout, answers 404. It may simply be private. |
| `unpinned` | The entry names no exact version, so what starts depends on the runner. `npx -y pkg` asks the registry for the newest version each time, unless the package is installed in the project or globally. `uvx pkg` installs the newest version the first time and then uses its cached copy until the cache is refreshed or pruned. `docker run img` and `img:latest` use the local image if there is one and pull only when it is missing. |
| `tag (mutable)` | A container tag other than `latest`, such as `:1.0`. A tag can be pushed again; only a digest (`@sha256:...`) fixes the image. |
| `ref (mutable)` | A git branch or tag, such as `#main` or `@v1.0.0`. Only a commit SHA fixes the code. |
| `custom registry, not checked` | The entry installs from a registry or index other than npm's or PyPI's, so the name is not looked up on the public one. |
| `source not checked` | A tarball or git URL on a host other than GitHub. |
| `no source repository linked` | The package names no repository, so the rest cannot be checked. |
| `could not tell what this starts` | The command is not a runner mcp-vitals knows (npx, bunx, pnpx, npm exec, pnpm/yarn dlx, bun x, uvx, uv, pipx, docker, podman, a local checkout). |
| `registry unreachable`, `repository unknown` | A registry, or GitHub and the census, could not be reached or gave no usable answer. |

Sources for the `unpinned` row, checked 2026-09-24: npm's `libnpmexec` 9.0.4 (bundled
with npm 10.9.7) fetches the manifest with `preferOnline: true` when it checks for a
newer version (`lib/index.js`); uv's docs say "After that, uvx will use the cached
version of the tool unless a different version is requested, the cache is pruned, or
the cache is refreshed" ([uv tools](https://docs.astral.sh/uv/concepts/tools/)); Docker's
docs describe the default `--pull missing` as "Pull the image if it was not found in the
image cache, or use the cached image otherwise"
([docker container run](https://docs.docker.com/reference/cli/docker/container/run/)).

Status uses the same thresholds as the census, which are agent-vitals' own choice, not
a standard: `active` means a push within 30 days, `slowing` 31 to 90, `stale` 91 to
365, `abandoned` over a year.

## What this is not

These are dates, flags and licence fields from public metadata. They are not a
security audit and not a verdict on anyone's code. A finished, correct tool can go
a year without a push and still work, and an active repository can still ship a bad
release. `mcp-vitals` tells you what is known, so you decide with the facts in front
of you.

## Licence

MIT.
