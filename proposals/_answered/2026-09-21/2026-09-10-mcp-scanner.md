# Proposal: cisco-ai-defense/mcp-scanner

- **Repo:** https://github.com/cisco-ai-defense/mcp-scanner
- **Source:** agent-vitals census, data/servers.json (2026-09-09 snapshot)
- **Stars:** 1,069 · **Forks:** 136 · **Open issues:** 60
- **Licence:** Apache-2.0 (SPDX-identified)
- **Language:** Python
- **Created:** 2025-09-24 (351 days) · **Last push:** 2026-09-08 (1 day before census)
- **Archived:** no. **Fork:** no. First seen in this census 2026-09-04.

## What it claims to do (from its description and topics only)

Scans MCP servers and reports potential threats and security findings. The
description is one sentence and the topics are four words (`agents`, `ai`,
`mcp`, `security`), so the metadata says what it points at and says almost
nothing about how. Whether it reads a server's tool manifest statically,
connects and enumerates tools at runtime, or does both is not stated, and
that is the first thing a reader has to establish.

Nothing here has been cloned, read or run. Everything above is metadata.

## Which derived gap it fills

`vetting.yaml` `domains` line 5 is `[claude-code, agent-skills, mcp-server,
harness, prompt-injection, supply-chain]`. The nearest `covered` entry is
`app security: [sast, vulnerability-scan, secret-scan, owasp]`, whose named
incumbents (`pre-launch-security-audit` and `claude-security`) audit
application source code that this setup wrote or is about to ship. Neither
points at the MCP servers the harness itself connects to.

That is the gap. The MCP surface is a trust boundary this setup crosses on
every session, and nothing in `covered` inspects it. `SkillSpector`
(proposed 2026-09-08) covers the adjacent half, skills, rather than
servers. Both `mcp-server` and `supply-chain` appear in `domains` as
declared targets, so the gap is derived from the file rather than argued
for.

## What would have to be true for it to be worth installing

- **The scan must be distinguishable from the attack.** This is the
  load-bearing condition. If auditing a server means connecting to it and
  invoking its tools, then running the scanner against a server you do not
  trust means executing the untrusted thing in order to decide whether to
  execute it. A static mode that reads a manifest, a package, or a config
  without a live session is what makes this safe to point at something
  unknown. If the only mode is dynamic, its value collapses to servers
  already installed and trusted, which is a much smaller job.
- **It must run locally with no callback.** A security scanner that ships
  the inventory of your connected servers (names, tools, endpoints) to a
  vendor endpoint is an exfiltration channel wearing a security badge. The
  vendor prefix here is a corporate AI-defence group, which raises that
  question rather than answering it. Local-only operation, verified by
  watching the network instead of reading the README, is a hard condition.
- **Its findings must be reproducible without the tool.** A finding that
  says a server is risky, and cannot be traced to a specific tool
  description, permission or code path, is unactionable and impossible to
  argue with. Findings need to name the artefact.
- **It must be worth its own attack surface.** A Python tool that parses
  hostile input (tool descriptions written by strangers, which is exactly
  what this census records) is itself a parser exposed to hostile input.
- **Sixty open issues against 136 forks is a number to read before it is a
  verdict.** Read what the open issues are actually about, then decide what
  the ratio means.

## Checks a human must run before installing

1. Determine whether a static-only mode exists, and confirm it by running
   it against a manifest file with no server reachable. If it needs a live
   connection, the safe scope is only already-installed servers.
2. Run it once with the network watched (`tcpdump`, Little Snitch, or an
   egress-denied container). Any outbound connection to somewhere other
   than the scanned server is a stop.
3. Read the dependency tree before the first `pip install`, per
   `tool-vetting`: resolve the PyPI package and the GitHub repository
   separately and confirm they are the same code. A security tool is a
   high-value name to typosquat.
4. Point it at one MCP server whose behaviour is already understood, and
   check whether the findings match what is known to be true. A scanner
   that reports nothing on a server with a known rough edge, or twenty
   findings on a clean one, is unusable either way.
5. Establish what it does with results: written where, retained how long,
   and whether any telemetry flag defaults to on.
6. Decide the overlap with `SkillSpector` before installing both. Skills
   and servers are different objects, but if both tools claim both, one of
   them is the incumbent and the other is a duplicate.
