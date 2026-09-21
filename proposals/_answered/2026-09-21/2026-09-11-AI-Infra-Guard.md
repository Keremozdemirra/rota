# Proposal: Tencent/AI-Infra-Guard

- **Repo:** https://github.com/Tencent/AI-Infra-Guard
- **Source:** agent-vitals census, data/servers.json (2026-09-10 snapshot)
- **Stars:** 6,218 · **Forks:** 581 · **Open issues:** 35
- **Licence:** Apache-2.0 (SPDX-identified)
- **Language:** Python
- **Created:** 2024-12-25 (624 days) · **Last push:** 2026-09-10 (day of census)
- **Archived:** no. **Fork:** no. First seen in this census 2026-09-07.

## What it claims to do (from its description and topics only)

A "full-stack AI Red Teaming platform" with five named scanners: Agent
Scan, Skills Scan, MCP scan, AI Infra scan, and LLM jailbreak evaluation.
The topics repeat the framing (`ai-red-teaming`, `agent-security`,
`llm-jailbreak`, `mcp-scan`). Two of the five scanners, skills and MCP
servers, point at exactly the objects this setup installs; the other
three (agents as deployed services, AI infrastructure, jailbreak
evaluation of models) point at things this setup does not run.

"Platform" and "full-stack" are the words to weigh. The metadata
describes something with a web interface and a service behind it, which
is a larger installation than either of the two pending proposals it
overlaps.

The vendor prefix is a large corporate group. That is neither a
recommendation nor a warning; it is a fact about who maintains it and
what its defaults are likely to assume about telemetry.

Nothing here has been cloned, read or run. Everything above is metadata.

## Which derived gap it fills

`vetting.yaml` `domains` line 5 is `[claude-code, agent-skills,
mcp-server, harness, prompt-injection, supply-chain]`. The nearest
`covered` entry, `app security`, names `pre-launch-security-audit` and
`claude-security`, both of which audit application source that this
setup writes. Neither inspects the skills and MCP servers the harness
itself loads. That gap is derived, and it is the same gap two earlier
proposals addressed one half each: `SkillSpector` (2026-09-08) for skills,
`cisco-ai-defense/mcp-scanner` (2026-09-10) for servers.

This is proposed as the alternative to that pair. One tool claiming both
halves is worth considering against two tools claiming one each, and the
census only saw it on 2026-09-07, after the first of those two proposals
was written. The decision is one of three: this, the pair, or neither.
Installing all three is the wrong answer whichever way the comparison
goes.

## What would have to be true for it to be worth installing

- **The two useful scanners must run without the platform.** If Skills
  Scan and MCP scan are reachable only through a web console backed by a
  database and a service, the installation is a running app to maintain
  in exchange for two checks. A CLI entry point for those two, with the
  rest left uninstalled, is what makes this proportionate.
- **Scanning must not mean executing.** Same load-bearing condition as
  the `mcp-scanner` proposal: if the MCP scan connects to a server and
  invokes its tools, the scanner runs the untrusted thing to judge it. A
  static mode reading manifests and tool descriptions is the safe scope;
  dynamic-only collapses the value to servers already trusted.
- **It must run locally with no callback.** A red-teaming platform from a
  large vendor is the kind of thing that ships an inventory home by
  default. Verify by watching the network rather than reading the
  README.
- **Findings must name the artefact.** A skill flagged "risky" without a
  line, a tool description, or a permission cited is unactionable.
- **The 2026-09-07 arrival needs an explanation.** The repository is
  624 days old, so the census first saw it three days after the index
  started because its topics or description changed to match a query.
  What changed is worth knowing before reading anything else.

## Checks a human must run before installing

1. Establish whether Skills Scan and MCP scan have a CLI that runs
   without the web platform. If they do not, the proportionate answer is
   the pending pair or nothing.
2. Run the MCP scan against a manifest with no server reachable. If it
   requires a live connection, restrict its scope to already-installed
   servers and record that limit.
3. Run once with egress denied or watched (`tcpdump`, Little Snitch, a
   network-less container). Any outbound connection to somewhere other
   than the scanned target is a stop.
4. Resolve the install route separately from the repository link, per
   `tool-vetting`: the PyPI package, the container image and the GitHub
   tree can be three different things.
5. Point Skills Scan at one skill whose contents are known, and the MCP
   scan at one server whose behaviour is understood. Compare findings to
   what is true. Silence on a known rough edge, or noise on a clean
   target, disqualifies it either way.
6. Compare its two relevant scanners against `SkillSpector` and
   `mcp-scanner` on the same targets, then choose one of the three
   outcomes and record the other two in `declined_repos` with the reason.
