# Proposal: NVIDIA/SkillSpector

- **Repo:** https://github.com/NVIDIA/SkillSpector
- **Source:** agent-vitals census, data/servers.json (2026-09-07 snapshot)
- **Stars:** 16,515 · **Forks:** 1,404 · **Open issues:** 108
- **Licence:** Apache-2.0 (SPDX-identified)
- **Language:** Python
- **Created:** 2026-03-21 (171 days) · **Last push:** 2026-09-07 (day of census)
- **Not archived, not a fork.** First seen in this census 2026-09-04.

## What it claims to do (from its description and topics only)

A static security scanner you point at an agent skill or MCP server *before*
installing it. Its description names five classes of finding — general
vulnerabilities, malicious patterns, prompt injection, data exfiltration, and
supply-chain risk — across Claude Code, Codex and MCP skills. Topics:
`agent-security`, `agent-skills`, `ai-security`, `claude-code`, `mcp`,
`prompt-injection`, `security-scanner`, `supply-chain-security`.

Nothing here has been run, cloned or read. This is what the metadata says it
is, not what it was observed to do.

## Which derived gap it fills

`vetting.yaml` `domains` line 5 is `[claude-code, agent-skills, mcp-server,
harness, prompt-injection, supply-chain]`. Nothing in `covered` answers it.
The nearest incumbent is `app security` (pre-launch-security-audit,
claude-security), and that is a different job: those audit an application
Kerem is *building*. This audits third-party agent code Kerem is about to
*install* — the supply-chain direction, which currently has no tooling at all.

That gap is not theoretical here. The `tool-vetting` skill already defines the
pre-install decision procedure, and `declined_repos` shows it running: the
OmniRoute entry records shared secrets, an empty storage key and a bind to
0.0.0.0 found by hand, after installation. `tool-vetting` is an entirely
manual reading pass today; this would be the first mechanical check under it.

## What would have to be true for it to be worth installing

- **It is a scanner, not a runtime agent.** The proposal rests on this. A
  static tool that reads files on demand and prints findings grants no
  standing authority and touches no red line. The neighbouring candidates in
  this same gap — `luckyPipewrench/pipelock`, `hashgraph-online/hol-guard`,
  `secureagentics/Adrian` — are all *runtime* interceptors that sit in the
  traffic path, and that is a different and much larger grant. If SkillSpector
  turns out to want a daemon, a hook, or egress interception, it becomes one
  of those and this proposal does not apply to it.
- **It must run offline.** A scanner that uploads candidate source to a
  vendor endpoint for analysis is exfiltrating third-party code from Kerem's
  machine. Verify where analysis happens before the first run.
- **Its findings must be readable, not just counted.** `tool-vetting`'s value
  is the recorded reason in `declined_repos`. A scanner that emits a score
  without a citable file and line adds nothing to that record.
- **It must not become the decision.** The fit test in `vetting.yaml` is a
  judgement about coverage, and a clean scan is not a fit verdict. This tool
  answers one narrow question — does the code do something hostile — and the
  risk of installing it is that a green result starts substituting for the
  rest of the read.
- **The NVIDIA namespace is not evidence.** It raises the prior on
  maintenance, nothing more; 108 open issues on a six-month-old repository
  says the same thing the star count does, which is that people are using it.

## Checks a human must run before installing

1. Read `SKILL.md` / entrypoint and the install command as an execution path,
   per `tool-vetting`: what runs, with what permissions, at install time and
   at scan time. A security scanner that itself installs a hook is the
   scenario the scanner exists to catch.
2. Confirm no network egress during a scan — run one with the network off and
   see whether it still produces findings.
3. Run it against a known-bad input: point it at the OmniRoute commit already
   recorded in `declined_repos`. If it does not flag the bind to 0.0.0.0 or
   the empty storage key, it does not detect the class of defect that
   motivated installing it, and the proposal fails on its own evidence.
4. Run it against the installed skills already trusted here and read every
   false positive. A scanner that flags `~/.claude/skills` broadly is noise,
   and noise in a security tool is worse than no tool.
5. Check the licence file is the Apache-2.0 the API reports, and check whether
   any detection ruleset ships under a different licence from the code.
6. Decide explicitly whether `cisco-ai-defense/mcp-scanner` (Apache-2.0, 1,066
   stars, active, created 2025-09-24) is the better shape: it scans MCP
   servers only, so it is narrower and correspondingly less to audit. These
   two answer the same gap and installing both would be duplication.
