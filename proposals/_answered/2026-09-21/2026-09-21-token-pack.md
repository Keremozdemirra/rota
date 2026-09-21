# Token pack: 23 repositories vetted, 2026-09-21

Five of the 23 are installed, three are scheduled behind the running workflows, four are kept as reference, and eleven are declined with the evidence recorded. Three installs were performed today. Nothing was bought, registered, published, committed, pushed or sent, and no credential was written to any file.

The pack is "23 things that stop Claude eating your tokens" (Charlie Hills), read on 2026-09-21. It supplies names alone, so every name was resolved to an owner and repository with `gh search repos "<name>" --sort stars --limit 5` and the one whose description matches the pack's claim was taken. Every star count, licence and version below was read on 2026-09-21. Where the pack's own star figure differs, the figure here is the one read today.

Full evidence per repository, four batch files under `/Users/keremozdemir/agents/projects/venture-studio/vetting/token-pack/`: `00-baseline.md`, `01-get-context-in.md`, `02-remember-it.md`, `03-see-the-burn.md`, `04-cut-the-burn.md`.

## The number every verdict was measured against

From `00-baseline.md`, produced by `ccusage` on 2026-09-21 over the 24 days with transcript data (2026-08-20 to 2026-09-21):

| Class | Tokens | Share |
|---|---|---|
| Cache read | 19,879,128,789 | 97.700% |
| Cache creation | 398,939,581 | 1.961% |
| Output | 68,231,485 | 0.335% |
| Input | 808,662 | 0.004% |
| Total | 20,347,108,517 | 100% |

Cache reads are 97.700% of every token this machine has spent. A candidate claiming to save tokens has to name which of those four rows it moves, and a candidate that adds always-on text raises the top row for every session that follows. That test decided ECC, superpowers, agentmemory and the plugin route of ponytail.

## Verdicts

| # | Name | Repo | Stars 2026-09-21 | Licence | Kind | Verdict | Reason | Install | Uninstall |
|---|---|---|---|---|---|---|---|---|---|
| 1 | context7 | https://github.com/upstash/context7 | 62,263 | MIT | MCP server (HTTP) | INSTALL NOW | Connected already; tools are deferred so the resident cost is one index line, and zero measured calls put it on notice to 2026-12-21. | `claude mcp add --scope user --transport http context7 https://mcp.context7.com/mcp` | `claude mcp remove context7 -s user` |
| 2 | codebase-memory-mcp | https://github.com/DeusData/codebase-memory-mcp | 43,930 | MIT | Native binary + MCP server (stdio) | INSTALL AFTER | A code graph displaces grep and read cycles, which is the 97.700% row; signed releases with SHA-256 verification, and a per-account daemon that waits for the workflows. | `curl -fsSL https://raw.githubusercontent.com/DeusData/codebase-memory-mcp/main/install.sh -o /tmp/cbm-install.sh && less /tmp/cbm-install.sh && bash /tmp/cbm-install.sh --skip-config && codebase-memory-mcp config set watcher_enabled false && codebase-memory-mcp config set auto_watch false && claude mcp add --scope user codebase-memory-mcp -- codebase-memory-mcp` | `claude mcp remove codebase-memory-mcp -s user && codebase-memory-mcp daemon stop && codebase-memory-mcp uninstall && rm -rf ~/.cache/codebase-memory-mcp` |
| 3 | haystack | https://github.com/deepset-ai/haystack | 26,565 | Apache-2.0 | Python library | REFERENCE | Resolution is a hedge on a bare name; it ships no MCP server and no CLI an agent harness calls, and `ltm.py` holds hybrid recall in 391 lines with the review gate. | `pip install haystack-ai==3.1.1` | `pip uninstall haystack-ai` |
| 4 | codegraph | https://github.com/colbymchenry/codegraph | 71,650 | MIT | Native binary + MCP server + installer | DECLINE | `install.sh` executes a 54 MB bundle with zero integrity checking while a SHA256SUMS asset ships unread; telemetry defaults on; the installer upserts a block into `~/.claude/CLAUDE.md`. | `curl -fsSL https://raw.githubusercontent.com/colbymchenry/codegraph/main/install.sh \| sh` | `curl -fsSL https://raw.githubusercontent.com/colbymchenry/codegraph/main/install.sh \| sh -s -- --uninstall` |
| 5 | OmniRoute | https://github.com/diegosouzapw/OmniRoute | 68,696 | MIT | Proxy / gateway | DECLINE | Shared secrets are fixed, `STORAGE_ENCRYPTION_KEY` is still empty by default and the host is still `0.0.0.0` with the guard only warning; a proxy over two Max seats is the ruled-out routing category. The ledger's GHSA-wmgv-ph3p-rv57 returns 404 today. | `npm install -g omniroute` | `npm rm -g omniroute` |
| 6 | 9router | https://github.com/decolua/9router | 29,490 | MIT | Proxy / gateway | DECLINE | 19 published advisories, 6 of them critical, including unauthenticated RCE and a full API key leak, in a component that would hold every provider credential on the machine. | `npm install -g 9router` | `npm rm -g 9router` |
| 7 | mempalace | https://github.com/MemPalace/mempalace | 59,189 | MIT | Python CLI (MCP server and hooks refused) | INSTALL NOW | Indexes 2,397 session transcripts (2.4 GB) that nothing else reads, embeds through the Ollama model already serving `ltm.py`, and adds no hook and no resident tokens. | `uv tool install mempalace` | `uv tool uninstall mempalace && rm -rf ~/.mempalace` |
| 8 | cognee | https://github.com/topoteretes/cognee | 30,874 | Apache-2.0 | Python library + MCP server + Docker stack | REFERENCE | Ontology-driven entity modelling has no target here; document recall is `ltm.py`, transcript recall is mempalace, graphs are graphify, and its Claude Code route is a hook plugin. | `uv pip install "cognee[gliner]"` | `uv pip uninstall cognee` |
| 9 | beads | https://github.com/gastownhall/beads | 27,329 | MIT | Go CLI (optional hooks, optional MCP) | REFERENCE | Clean provenance and checksum-verified installs, with no target: open work here sits in `NEXT.md` as flat lists, so `bd ready` has no dependency graph to compute over. | `brew install beads && bd init --stealth` | `brew uninstall beads && rm -rf <project>/.beads` |
| 10 | claude-mem | https://github.com/thedotmack/claude-mem | 94,365 | Apache-2.0 | Plugin + worker service + MCP server | DECLINE | 8 hook commands across 7 events capture every tool call and inject on `UserPromptSubmit` with no human step, against the memory protocol; the installer also provisions an account by email magic link. | `npx claude-mem install` (not run) | `npx claude-mem uninstall` |
| 11 | mem0 | https://github.com/mem0ai/mem0 | 65,739 | Apache-2.0 | Library + Docker server + hosted platform | DECLINE | The headline quickstart has the agent mint its own hosted account, which is outside what I perform; the library tier is the weakest by the project's own table and `ltm.py` covers the job offline. | `pip install mem0ai` (library route only) | `pip uninstall mem0ai` |
| 12 | agentmemory | https://github.com/rohitg00/agentmemory | 28,659 | Apache-2.0 | Node server + Claude Code plugin | DECLINE | Keyless and local by default, and still 12 hooks, 4 resident ports and 54 MCP tool definitions in every session, for transcript recall a CLI now covers at zero resident cost. | `npx -y @agentmemory/agentmemory@latest` (not run) | `npm uninstall -g @agentmemory/agentmemory && rm -rf ~/.agentmemory` |
| 13 | claude-hud | https://github.com/jarrodwatts/claude-hud | 28,079 | MIT | Claude Code plugin (statusline binary) | INSTALL NOW | Draws the 5-hour and 7-day Max windows from the `rate_limits` field `statusline.sh` ignores; 0 skills, 0 agents, 0 hooks, 0 MCP, ~0 always-on tokens, zero network calls. | `claude plugin marketplace add jarrodwatts/claude-hud && claude plugin install claude-hud@claude-hud` | `claude plugin uninstall claude-hud@claude-hud && claude plugin marketplace remove claude-hud` |
| 14 | ccusage | https://github.com/ccusage/ccusage | 18,658 | MIT (LICENSE file; the API reports NOASSERTION) | npm CLI, offline | INSTALL NOW | The measuring instrument the rest of the pack is judged with, previously resolved fresh by `npx` on every run; reproduces the baseline shares to three decimals in 0.72 s with no account and no endpoint. | `npm install -g ccusage` | `npm uninstall -g ccusage` |
| 15 | CodexBar | https://github.com/steipete/CodexBar | 21,684 | MIT | macOS 14+ menu bar app with a bundled CLI | INSTALL AFTER | Shows both Max seats' windows with no session open, which claude-hud cannot; a GUI asking for Keychain and system permissions, so the install belongs to Kerem, and no provider API key is set. | `brew install --cask codexbar` | `brew uninstall --cask codexbar && rm -rf ~/.config/codexbar ~/.codexbar` |
| 16 | ECC | https://github.com/affaan-m/ECC | 264,075 | MIT | Whole harness plugin (24 hooks, 292 skills, 68 agents) | DECLINE | 292 skill frontmatter blocks carry 88,660 characters, about 22,165 tokens in every session before a skill fires, and 9 of its 24 hooks are PreToolUse, 2 landing on rtk's Bash matcher. | `/plugin install ecc@ecc` (not run) | n/a, not installed |
| 17 | rtk | https://github.com/rtk-ai/rtk | 81,193 | Apache-2.0 | Rust CLI + PreToolUse Bash hook | INSTALL NOW | Incumbent, re-vetted and kept: it rewrites Bash commands and sets no base URL, and its honest saving is 36.4% once 23 pipeline rows are excluded from the 84.7% headline. | `brew install rtk` (already at 0.49.0) | delete the `Bash` matcher hook from `~/.claude/settings.json`, then `brew uninstall rtk && rm -rf ~/Library/Application\ Support/rtk` |
| 18 | ponytail | https://github.com/DietrichGebert/ponytail | 143,297 | MIT | Claude Code plugin, or a standalone skill | INSTALL AFTER | Skill route only: the plugin's SessionStart hook emits 5,825 characters at every session and subagent start, while the skill costs nothing until dispatched and has zero egress. | `git clone --depth 1 https://github.com/DietrichGebert/ponytail ~/agents/_vendor/ponytail && ln -s ~/agents/_vendor/ponytail/skills/ponytail ~/.claude/skills/ponytail` | `rm ~/.claude/skills/ponytail && rm -rf ~/agents/_vendor/ponytail` |
| 19 | deer-flow | https://github.com/bytedance/deer-flow | 82,778 | MIT | Standalone agent harness with Docker stack | REFERENCE | It runs its own model traffic on its own provider account, so money outside the two seats and a key on disk, and it compresses nothing in Claude Code; worth reading for the agency's automation line. | n/a | n/a |
| 20 | caveman | https://github.com/JuliusBrussee/caveman | 107,050 | MIT repo, BUSL-1.1 core (API: NOASSERTION) | Skill + local API proxy (Go) | DECLINE | The proxy half writes `ANTHROPIC_BASE_URL` into `settings.json` and its own INSTALL.md says that makes Remote Control unavailable; CLI telemetry is on by default. | n/a | n/a |
| 21 | headroom | https://github.com/headroomlabs-ai/headroom | 73,312 | Apache-2.0 | Python library, local proxy, MCP server | DECLINE | MCP mode compresses only what it is handed, so it cannot intercept; wrap mode points the base URL at loopback and its own source records that Claude Code 2.1.196+ then disables Remote Control. | n/a | n/a |
| 22 | oh-my-openagent | https://github.com/code-yeongyu/oh-my-openagent | 69,239 | Sustainable Use License 1.0 (API: NOASSERTION) | Plugin for OpenCode and Codex CLI | DECLINE | The licence is non-SPDX and limited to internal business use, a lawyer's question for an agency; and nothing in the three editions runs inside Claude Code. | n/a | n/a |
| 23 | superpowers | https://github.com/obra/superpowers | 289,417 | MIT | Claude Code plugin with a SessionStart hook | DECLINE | Its SessionStart hook emits 3,405 characters, 851 tokens, resident and re-read every turn, and its core loop is the unattended-subagent category declined 2026-08-25. | `/plugin install superpowers@claude-plugins-official` (not run) | `/plugin uninstall superpowers@claude-plugins-official` |

Counts: INSTALL NOW 5, INSTALL AFTER 3, REFERENCE 4, DECLINE 11.

## Installed today, with the verification output

Three packages were installed on 2026-09-21. Two of the five INSTALL NOW rows were already running before the pass began: `context7` was connected, and `rtk` 0.49.0 was in `/opt/homebrew/bin` with its hook at `~/.claude/settings.json` line 60. Both were re-vetted and kept.

### ccusage 20.0.23

```
$ npm install -g ccusage
added 2 packages in 1s
$ ccusage --version
ccusage 20.0.23
$ CI=1 ccusage daily --json | …
days: 24
total 20,406,625,044
cache read     19,936,816,378  97.698%
cache create      400,377,541   1.962%
output             68,620,377   0.336%
input                 810,748   0.004%
cost USD 13966.23
```

The four shares reproduce the baseline table to three decimal places, with totals a little higher because this session was writing into today's row. A run takes 0.72 s against an npm download on every earlier run.

### claude-hud 0.8.0

```
$ claude plugin marketplace add jarrodwatts/claude-hud
$ claude plugin install claude-hud@claude-hud
$ claude plugin details claude-hud
Skills 0 · Agents 0 · Hooks 0 · MCP 0 · Always-on ~0 tok
$ node ~/.claude/plugins/cache/claude-hud/claude-hud/0.8.0/dist/index.js   # real session payload
[Opus 5] │ rota git:(main*)
Context ██████░░░░ 62% │ Usage █████░░░░░ 49%
```

The `settings.json` hash changed by one `extraKnownMarketplaces` key. The `statusLine` value and all six hooks are byte-identical, so the two running workflows are untouched. The status line swap itself is left for Kerem.

### mempalace

```
$ uv tool install mempalace
$ curl -s http://127.0.0.1:11434/v1/embeddings -d '{"model":"bge-m3","input":"test"}'
OK dims= 1024 model= bge-m3
$ cat ~/.mempalace/config.json
{"embedding_model": "openai-compat",
 "embedding_api_url": "http://127.0.0.1:11434/v1/embeddings",
 "embedding_api_model": "bge-m3"}
$ mempalace mine ~/.claude/projects/-Users-keremozdemir-agents --mode convos --wing agents-sessions --limit 3 --direct
  Files processed: 3
  Drawers filed: 821
$ mempalace search "vetting ledger declined repositories"
  [1] agents-sessions / technical
      Source: 7b812ad8-30b7-4ad9-a88c-b7116153b6ff.jsonl
      Match:  cosine_sim=0.529  bm25=0.0
```

The matched drawer was Turkish prose recovered by an English query with `bm25=0.0`, the cross-lingual case `ltm.py` keeps an embedding layer for, and the two tools now share one local model. Mining writes to `~/.mempalace/palace`; canonical files and `memory/_inbox/` are untouched, every hit cites its source transcript, and the auto-save hooks were left unwired. Three of 2,397 transcripts are mined so far.

## The INSTALL AFTER schedule

The rule: one section at a time, a few days each, and a `ccusage` reading before the next section starts. The reading that matters is the cache-read row against the 97.700% baseline above, per active day, since daily totals on this machine swing from 45 million to 2.95 billion tokens and a calendar comparison proves nothing on its own.

None of these starts while the two workflows are running.

1. **ponytail, skill route.** Lightest of the three: one symlink, no hook, no daemon, no network. Install and uninstall commands in row 18. Measurement: record the floor with `CI=1 ccusage session --json`, then run ten build-shaped tasks with the skill dispatched and ten without, alternating, in the same repository, and compare median `outputTokens` and median session total. Keep it when the median falls and the diff stays correct. The honest prior: its 22% came from Haiku 4.5 on green-field tickets, and most work here is prose and research.
2. **codebase-memory-mcp.** Heaviest change, so it goes second and alone. Install with `--skip-config` so no hook, no CLAUDE.md write and no agent config is touched, then switch the watcher off before the first session. Commands in row 2. Measurement after two weeks, three readings: `lsof -i -a -p $(pgrep -f codebase-memory-mcp)` across one session, with any connection beyond loopback ending it that day; `ccusage daily --json` for the 14 days either side, comparing the cache-read row per active day; and a count of `tool_use` blocks naming `mcp__codebase-memory-mcp__*` in transcripts, where zero calls in two weeks is the same verdict context7 is on notice for.
3. **CodexBar.** Kerem's own hands, after the claude-hud status line has run a week, because claude-hud may already carry the job. Commands and settings in the next section. Measurement after two weeks: has the menu bar reading moved the start time of a long task at least once?

## Kerem's own hands

These need a password, a GUI, an account or a decision, so they are recorded as commands and left unperformed.

1. **Swap the status line to claude-hud.** Run `/claude-hud:setup` inside a session once the workflows end. It backs `settings.json` up to a timestamped `.bak` file before it rewrites the `statusLine` key. To undo, restore that `.bak`. Measurement: inside a week, does the Usage bar change one decision, meaning a long task started or deferred because of the reset countdown? If it does not, `statusline.sh` comes back.
2. **CodexBar, if the answer to step 3 of the schedule is yes.** `brew install --cask codexbar` (cask 0.63.0 from Homebrew/homebrew-cask, release v0.63.0 published 2026-09-20, 2,132 installs in 30 days). Enable Claude alone through OAuth reuse, decline Full Disk Access, decline agent-aware refresh, and set no API key for any provider: `codexbar config set-api-key` writes a provider key in plain text into `~/.config/codexbar/config.json`, which section 6 of `~/.claude/CLAUDE.md` forbids. Uninstall in row 15.
3. **Two `covered:` lines in `vetting.yaml`.** Proposed text, left to Kerem because sibling passes were reading that file while this ran:

```yaml
  bash output compression: [token-reduction, output-compression, cli-proxy]  # rtk 0.49.0, PreToolUse Bash hook
  usage metering: [token-usage, cost-tracking, statusline, quota, rate-limit]  # ccusage 20.0.23, claude-hud 0.8.0
```

4. **The `memory and recall` incumbent line** gains a second name once mempalace has passed its 2026-10-21 check: `ltm.py hybrid + review gate, mempalace CLI for session transcripts`.
5. **Stop quoting rtk's 84.7%.** The measured figure is 36.4% once the 23 `cat build.log` pipeline rows are excluded, and the ledger carries the honest one.
6. **Mine the remaining transcripts.** 3 of 2,397 are indexed; the rest is one long `mempalace mine` command for a session able to watch it run.

## What this pass changed on the machine

Installed: `ccusage` 20.0.23 (global npm), `claude-hud` 0.8.0 (plugin, no hooks), `mempalace` (uv tool, CLI only). Configured: `~/.mempalace/config.json` pointing at the local Ollama embedding endpoint. Added to `settings.json`: one `extraKnownMarketplaces` key. Untouched: `statusLine`, all six hooks, `CLAUDE.md`, `memory/_inbox/`, every canonical memory file, and every existing MCP server entry.

## Limits

The `ccusage` totals count days with transcript data, so a missing day means no transcript was found and not that no work happened. The cost column is list-price arithmetic against an invoice nobody receives on a Max seat. The haystack row rests on a name the pack never disambiguated, and the resolution is recorded as a hedge. Star counts move; each one above carries its retrieval date and nothing more. Eleven of the twenty-three were declined on evidence read today, and four of those eleven had a dated decline already, each re-checked against the upstream repository before the reason was written.
