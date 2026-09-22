# Proposal: gwittebolle/claude-carbon

- **Repo:** https://github.com/gwittebolle/claude-carbon
- **Source:** agent-vitals census, data/servers.json (2026-09-21 snapshot)
- **Stars:** 196 · **Forks:** 17 · **Open issues:** 0
- **Licence:** MIT (SPDX-identified)
- **Language:** Shell
- **Created:** 2026-04-05 (169 days) · **Last push:** 2026-09-21 (the day of the census)
- **Archived:** no. **Fork:** no. First seen in this census 2026-09-04.

## What it claims to do (from its description and topics only)

The description is one line: track the carbon footprint of your Claude
Code sessions. The topics add `carbon-accounting`, `carbon-emissions`,
`claude-code-plugin`, `cli` and `ai-sustainability`. Read together, that
is a meter: it reads what Claude Code already records about a session,
turns token counts into an energy figure and the energy figure into CO2
by some factor, and prints the result. Two topics say there are two
routes, a plugin and a CLI. The language is Shell, so the whole of it is
readable in one sitting, and 0 open issues on 17 forks after five months
says the tracker is quiet, nothing more.

## Which derived gap it fills

`domains` lists `[esg, climate, emissions, carbon, sustainability, cbam,
csrd]` and `[claude-code, agent-skills, mcp-server, harness, ...]`. Nothing
in `covered` touches emissions, carbon or climate; the nearest incumbents
are the usage meters, `ccusage` 20.0.23 and `claude-hud` 0.8.0, which
count tokens and stop there. A carbon figure for this machine's own AI
use sits at the intersection of the two domains and has no incumbent.

The reason it is worth a look rather than a shrug: the ESG work here
publishes numbers under the rule that every coefficient carries a primary
source and a date (`source-check`). A tool that turns the `ccusage`
baseline of 20.3 billion tokens into a kilogram figure is either a
publishable line on the site and in the venture-studio material, or a
worked example of why such figures are not publishable. Either outcome
is useful; both need the code read.

## What would have to be true for it to be worth installing

- **The factors must be in the repository, sourced and dated.** Energy
  per token, grid intensity, and any PUE or embodied-carbon term must be
  literal values in the code or a data file with a citation next to
  each. A factor fetched at runtime, or one with no source, makes every
  output an unsourced number, which the content rules forbid publishing.
  No per-token energy figure from Anthropic is known here, so the factor
  is most likely a third-party estimate; the proposal is only worth
  taking if that party and its date are named in the repository.
- **It must read local transcripts only.** `ccusage` proved the job can
  be done offline from `~/.claude/projects`. Any outbound call, for a
  grid-intensity feed or anything else, needs a flag that is off by
  default.
- **The CLI route must stand alone.** The `claude-code-plugin` topic
  means a hook may exist. The measured-cost precedent (agentmemory,
  superpowers, the ponytail plugin route) refuses anything that adds
  resident text to every session. If the plugin is a SessionStart or
  Stop hook, the CLI is the only route, and only if it works without the
  hook.
- **It must beat forty lines of Python.** `ccusage --json` already yields
  the token classes. Multiplying them by a sourced factor is trivial; the
  tool earns its place only if its factor set is better sourced than one
  Kerem would assemble himself, or if it separates cache reads from
  output tokens, which do not cost the same compute.

## Checks a human must run before installing

1. Read every shell file. It is Shell, so this is the whole tool; a
   `curl` or `wget` anywhere in it is the first thing to find.
2. Find the emission factors. For each, note the source, the date, and
   whether it distinguishes input, cache-read and output tokens. If a
   factor has no source, stop: the tool cannot produce a number the site
   is allowed to print.
3. Resolve the install route. If the README installs by plugin
   marketplace, list the hooks the plugin registers and the bytes each
   emits per session. If it installs by `curl | sh`, read the script
   first, per `tool-vetting`.
4. Run it once against the same transcript set `ccusage` read on
   2026-09-21 and check its token total against 20,347,108,517. A tool
   that cannot reproduce the token count cannot be trusted with the
   multiplication.
5. Decide what the figure is for before installing. If it is for the
   site, the `source-check` pass on the factors is the actual work and
   the tool is a convenience; if it is curiosity, a one-off script costs
   less than a permanent install.
