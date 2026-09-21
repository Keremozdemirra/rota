# Proposal: step-security/dev-machine-guard

- **Repo:** https://github.com/step-security/dev-machine-guard
- **Source:** agent-vitals census, data/servers.json (2026-09-13 snapshot)
- **Stars:** 175 · **Forks:** 23 · **Open issues:** 26
- **Licence:** Apache-2.0 (SPDX-identified)
- **Language:** Go
- **Created:** 2026-03-10 (187 days) · **Last push:** 2026-09-11 (2 days before census)
- **Archived:** no. **Fork:** no. First seen in this census 2026-09-04.

## What it claims to do (from its description and topics only)

The description is one sentence: scan a developer machine for AI agents,
MCP servers, IDE extensions and suspicious packages, in seconds. The
topics add `endpoint-security`, `supply-chain-security`, `mcp-servers`
and `vscode-extensions`. Read together, that is an inventory tool: it
walks the places where agent tooling installs itself and lists what it
finds, with some rule that marks a package as suspicious.

The word that matters is "scan" rather than "test" or "guard". The three
proposals already open on this domain read the content of a skill or an
MCP server and judge it. This one, on its metadata, answers the prior
question: what is installed at all. That is the first step of the
`tool-vetting` skill ("enumerate the installed surface, derive the
gaps"), which today is done by hand across `~/.claude`, the plugin
directory and the MCP configuration.

The owner is a vendor whose other products are hosted. A Go binary with
"endpoint-security" in its topics may report to a service by default.
Nothing in the metadata says either way.

Nothing here has been cloned, read or run. Everything above is metadata.

## Which derived gap it fills

`vetting.yaml` `domains` line 5 is `[claude-code, agent-skills,
mcp-server, harness, prompt-injection, supply-chain]`. `covered` names
`app security` (`pre-launch-security-audit`, `claude-security`), which
audits application source this setup writes. The tooling the harness
itself loads has no incumbent. That gap is derived, and it already
carries three unanswered proposals: `NVIDIA/SkillSpector` (2026-09-08),
`cisco-ai-defense/mcp-scanner` (2026-09-10) and `Tencent/AI-Infra-Guard`
(2026-09-11).

This is a different job from those three. They inspect the content of
what is installed; this one claims to produce the list they would be run
against. If none of the three is installed, the list is still worth
having, because the installed surface here spans skills, plugins, MCP
servers in several configuration files and IDE extensions, and no single
command enumerates it today. If one of the three is installed, its input
is this tool's output.

26 open issues on 23 forks after six months is an active tracker for a
project of this size, and says nothing about quality in either direction.

## What would have to be true for it to be worth installing

- **It must run entirely offline.** An inventory of every agent, server
  and extension on this machine is exactly the list a red line says to
  keep on the machine. A vendor binary that phones home with the scan
  result, even anonymised, is a stop. If there is a cloud mode, it must
  be off by default and provably off.
- **The "suspicious" rule must ship with the code.** If the package
  judgement comes from a vendor feed fetched at runtime, the tool is a
  client for a service, and the category is the one already ruled out
  for scanners that need the platform to be useful.
- **It must find what is actually here.** Claude Code skills under
  `~/.claude/skills`, plugins, `settings.json` MCP entries, and the
  desktop app's own MCP configuration. A scanner built for VS Code and
  Cursor that reads none of those enumerates a machine this is not.
- **It must beat a shell script.** The honest alternative is forty lines
  of `find` and `jq` over the known paths. The tool earns its place only
  if it knows install locations this setup does not already know, or
  if its package rules catch something a path listing cannot.

## Checks a human must run before installing

1. Resolve the install route and the repository separately and confirm
   they fetch the same code, per `tool-vetting`. A curl-to-shell installer
   or a Homebrew tap pointing at a prebuilt binary is a stop until the
   source that built it is identified.
2. Read the network code before the first run: every outbound host, and
   whether any is contacted without a flag. Then run it once with the
   network watched and confirm zero connections.
3. Read the "suspicious package" rule. Confirm it is shipped in the
   binary or in a file in the repository, and never fetched.
4. List the directories it scans and compare with the real install
   surface here. Note what it misses; that is the gap a script would
   still have to cover.
5. Read what it writes and where. An inventory file is sensitive by
   construction; decide its location and whether it is gitignored before
   the tool creates it.
6. Decide the three pending proposals on this domain first, or at the
   same time. This tool is proportionate on its own; it is no reason to
   install the others.
