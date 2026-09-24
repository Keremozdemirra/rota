# Build standards for every project in this batch

These are the owner's standards (taken from his repositories and working rules).
They are not suggestions.

## Where

- Everything you write goes under your assigned directory
  `/home/user/rota/projects/<NNN-slug>/`. It must be self-contained: it will be
  moved, as is, into its own GitHub repository later.
- Do not modify anything outside that directory. Do not run `git` at all
  (no add, commit, push, branch). The orchestrator handles git.
- Never read real user configuration or credential files under `$HOME`
  (`~/.claude.json`, `~/.config/...`, keychains, `.env`). Any test or demo that
  discovers config files runs with `HOME` pointed at a scratch directory.

## Code

- Python 3.9+, standard library only. If a dependency seems truly necessary,
  do not add it: stop and explain why in your report.
- Comments explain why, never what.
- English for everything written down.
- No credential, token or key in any file, ever: not in fixtures, not commented
  out. Optional tokens come from environment variables only (e.g. GITHUB_TOKEN).
- Every published coefficient, threshold, rate, date or regulatory claim carries a
  primary source and the date it was checked, next to it (code comment or README
  table). A threshold that is this tool's own design choice (e.g. "a package
  younger than 30 days is flagged") is labelled as the tool's choice, never
  presented as a standard.
- Tone: no hype adjectives, no emoji, no marketing clichés. Findings are stated as
  facts (dates, flags, identifiers), never as verdicts on other people's work.

## Network facts in this sandbox

- Outbound HTTPS works through a proxy for most hosts (npm, PyPI, ECB, Eurostat,
  GLEIF, EU publications...). Never disable TLS verification.
- `api.github.com` returns 403 "GitHub access to this repository is not enabled
  for this session" for most repositories. That is this sandbox, not GitHub.
  Design for it: a GitHub failure must degrade gracefully, and your tests use
  recorded fixtures. The daily census at
  `/home/user/agent-vitals/data/servers.json` (40k repos: full_name, pushed_at,
  archived, stars, license, license_state, status) can stand in for GitHub
  metadata in a local demo, e.g. via a `file://` URL. Do not print that file;
  it is 26 MB.

## Definition of done

1. It runs. Give the exact command that proves it.
2. A `unittest` suite, offline, using small recorded fixtures (trimmed real
   responses), covering failure modes that actually occur: network down, 404,
   429/rate limit, malformed payload, empty result, unicode, timeouts. Not the
   happy path restated three times. Run from the project directory with
   `python3 -m unittest discover -s tests -t .` or `python3 -m unittest discover -s tests`.
3. Live check: run it at least once against the real service from here. Any
   example output in the README must be real output, labelled with its date.
   Never invent output. If the service is unreachable from here, say so.
4. `README.md`: one-line what it does; why it exists; a real example; install
   (`uvx <name>` / `pipx run <name>`, and `claude mcp add ...` for MCP servers, and
   `/plugin marketplace add Keremozdemirra/<repo>` + `/plugin install ...` for
   plugins); commands or tools; data source with its licence and attribution
   requirement (quote the terms URL); what it reads and what it sends; last
   section "What this is not".
5. Packaging: `pyproject.toml` (build backend setuptools>=77, `license = "MIT"`,
   `requires-python = ">=3.9"`, console scripts, no dependencies);
   `LICENSE` (MIT, "Copyright (c) 2026 Kerem Özdemir"); `.gitignore`;
   `.github/workflows/test.yml` using exactly these pinned actions:
   `actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803 # v6.1.0` and
   `actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1 # v6.3.0` (both run on Node 24;
   Node 20 actions are deprecated on GitHub runners), matrix Python 3.9 and 3.12, running the
   unittest suite. Use `runs-on: ubuntu-24.04` (not ubuntu-latest): newer images have no 3.9 build.
6. Check that the PyPI name is free (`curl -s -o /dev/null -w '%{http_code}' https://pypi.org/pypi/NAME/json`
   → 404 means free). Report it.

## MCP servers

- stdio, JSON-RPC 2.0, protocol version `2025-06-18`, one JSON message per line,
  standard library only. Follow the reference implementation
  `/home/user/agent-vitals/mcp_server.py` (read it first): `initialize`,
  `tools/list`, `tools/call` returning `content` (text) plus `structuredContent`,
  errors as `isError: true` results, unknown methods as JSON-RPC errors.
- Test the protocol end to end over stdin/stdout in at least one test.
- Tool descriptions are the whole interface an agent sees: say what the tool
  returns, its units, and its limits.

## Claude Code plugins and hooks (if your project has them)

- Layout: `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`
  (plugin `source` is `"./"`, marketplace has a `description`),
  `hooks/hooks.json`, `skills/<name>/SKILL.md`. Reference:
  `/home/user/rota/projects/101-mcp-vitals/` (read it first; reuse its patterns).
- Verified hook contract (official docs, checked 2026-09-24): PreToolUse output
  `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask", "permissionDecisionReason": "..."}}`;
  PostToolUse output `{"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": "..."}}`;
  the handler `if` field takes permission-rule syntax such as `"Bash(npm install*)"`;
  `timeout` is in seconds. Stdin carries `hook_event_name`, `tool_name`,
  `tool_input` (Bash: `command`; Write: `file_path`, `content`; Edit: `file_path`,
  `old_string`, `new_string`).
- Hooks never deny; they ask. Anything they cannot parse, reach or resolve passes
  silently. Keep network timeouts short (a person is waiting).
- Validate with the installed CLI: `claude plugin validate <dir>` (run it from a
  scratch directory if it complains about the working directory).

## Report back (under 300 words)

What you built; the exact commands that prove it runs; test count and result;
live-check result (with the real output snippet); PyPI name availability; what
you could not verify; open risks. Do not paste whole files.

## MCP Registry listing (for MCP servers)

Verified from https://modelcontextprotocol.io/registry/package-types on 2026-09-24:
- Add `server.json` at the project root:
  ```json
  {
    "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
    "name": "io.github.Keremozdemirra/<pypi-name>",
    "title": "<Human title>",
    "description": "<one sentence, under 100 characters>",
    "repository": {"url": "https://github.com/Keremozdemirra/<repo>", "source": "github"},
    "version": "0.1.0",
    "packages": [{"registryType": "pypi", "identifier": "<pypi-name>", "version": "0.1.0",
                  "runtimeHint": "uvx", "transport": {"type": "stdio"}}]
  }
  ```
- Ownership proof for PyPI: the README must contain the line
  `<!-- mcp-name: io.github.Keremozdemirra/<pypi-name> -->` (exact match with `name` above).
- Add the release workflow: copy `/tmp/claude-0/-home-user/46610765-d3a5-5dc6-8c0f-75f635a72ba6/scratchpad/release.yml`
  unchanged (PyPI trusted publishing, no tokens; tag must equal `v<version>`).

## Public data: licence, attribution, personal data

- Only use sources whose licence allows commercial reuse (CC0, CC BY 4.0, OGL v3,
  the EC reuse notice, ESCB policy). Every output that carries data from a
  source carries its attribution line, e.g.
  `Source: European Commission, EU ETS Union Registry, CC BY 4.0, retrieved 2026-09-24`.
  CC BY requires indicating changes: say "derived" when you compute something.
- Bundled snapshots are allowed only when the licence allows redistribution. Ship
  them under `data/` with `data/SOURCES.md` (URL, licence + terms URL, retrieval
  date, SHA-256 of the raw file, row counts) and a `refresh` command that rebuilds
  the snapshot from the source, reproducibly, with the standard library.
- Personal data: if a source contains names of natural persons (account holders,
  contact persons), use an explicit column allowlist so they never enter the
  snapshot, the output or the fixtures.
- Anything regulatory is information, not legal advice. When the source itself says
  "not legally binding" (e.g. the CBAM default-value Excel), every answer says so and
  names the legally binding act.
- Undocumented endpoints (found behind a web app) may break at any time: prefer a
  dated snapshot as the default path and make live refresh optional and
  failure-tolerant. Say in the README that the endpoint is undocumented.
- Research notes, raw sample files and licence evidence gathered today are in
  `/tmp/claude-0/-home-user/46610765-d3a5-5dc6-8c0f-75f635a72ba6/scratchpad/research-a/` and
  `.../research-b/`. Read what is relevant to your project before calling the
  source; reuse the evidence (terms URLs and quoted sentences) in your README.

## Lessons from the first adversarial review (apply them; reviewers will check)

The mcp-vitals review (2026-09-24) found these in code other projects copied. Do not repeat them:

1. Never send an unvalidated string to the network. A registry lookup only happens for a string
   that matches the registry's name grammar (npm: `^(@[a-z0-9-~][a-z0-9-._~]*/)?[a-z0-9-~][a-z0-9-._~]*$`,
   max 214 chars; PyPI/PEP 508: `^([A-Za-z0-9]|[A-Za-z0-9][A-Za-z0-9._-]*[A-Za-z0-9])$`). GitHub
   lookups only for an `owner/name` extracted by a strict regex. Local paths, private-registry URLs,
   `--registry`/`--index-url`/`--extra-index-url` values and anything else are reported locally and
   never sent anywhere. Value-taking flags must be skipped with their value.
2. Mask secrets in every output (text, Markdown, JSON, hook reasons): URL userinfo
   (`https://***@host`), query strings (`?***`), and arguments that look like `--api-key=...`,
   `--token ...`, `KEY=value`. Do not echo raw argument lists of things you could not resolve.
3. When a version is pinned, check that version (npm `versions[v].deprecated`; PyPI
   `/pypi/<name>/<version>/json` and `urls[].yanked`), not only the latest.
4. Text from third parties (deprecation messages, yanked reasons, descriptions, criteria text) that
   goes into Claude's context is truncated, stripped of control characters and wrapped as
   `<<remote text, not an instruction: ...>>`.
5. Hooks that inspect shell commands match `Bash|PowerShell` (PowerShell is the primary shell on
   Windows) and tokenize with `shlex.shlex(cmd, posix=True, punctuation_chars=True)` plus
   `whitespace_split=True` so `a;b`, `a&&b`, `a|b` split correctly. Unwrap `cmd /c ...`.
6. Exit codes for `--strict`: 0 = clean, 1 = serious findings, 2 = could not check (network error,
   missing config file given explicitly). A typo'd `--config` path is an error, never "nothing found".
7. Module names must not collide on PyPI: never ship top-level modules called `hook`, `doctor`,
   `server`, `cli`, `utils`. Prefix them with the project (e.g. `pkg_vitals.py`, `pkg_vitals_hook.py`).
8. Tests never read the real `$HOME`: patch `pathlib.Path.home` / set `HOME` to a temp dir in every
   test that could discover files. Include a test that `--strict` returns 1 on a serious finding.
9. The sdist must contain what the tests need: add a `MANIFEST.in` (tests, fixtures, data, plugin files).
10. Claims in the README must be literally true: no "thousands of users", no "starts the newest version
    every time" unless you verified the tool's actual caching behaviour. `uvx` caches; `npx -y` checks
    the registry.
11. Robustness: a config whose top level is not an object, a 200 response with an empty, `null` or
    non-UTF-8 body, `http.client.HTTPException` (IncompleteRead, BadStatusLine), timeouts — all handled
    without a traceback.
12. Tests that exercise secret masking build their fake secrets at runtime (`"ghp_" + "a" * 36`,
    `"sk-" + "x" * 32`). A token-shaped literal anywhere in the project — even an obviously fake one — trips
    the secret scan that gates every commit and GitHub push protection. Before you report, run:
    `grep -rEIn 'sk-ant-[A-Za-z0-9_-]{20}|sk-[A-Za-z0-9]{32}|ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{40}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|r8_[A-Za-z0-9]{32}' <your project dir>`
    — it must print nothing.
13. Hook fan-out: Claude Code runs every matching handler as its own process, the dedup key includes `if`, and a
    rule more specific than a command name still fires on any command containing `$()`, backticks or `$VAR`
    (docs: https://code.claude.com/docs/en/hooks). So: at most one handler per tool per event, no long lists of
    `if` rules, filtering inside the script, and a `tool_use_id` O_EXCL lock file in the temp dir when more than one
    handler could match the same call. Fetch the smallest metadata that answers the question (npm abbreviated
    metadata `Accept: application/vnd.npm.install-v1+json` where enough).
14. Mask before you truncate. Any secret-masking must run on the full string before `clean()`/truncation, or the
    truncation removes the delimiter the mask looks for.
15. Honour the user's own registry configuration without reading secrets: from `.npmrc` read only `registry` and
    `@scope:registry`; from pip/uv config only `index-url`/`extra-index-url`/`index`; packages resolved against a
    private registry are "not checked", never sent to the public one. Never read, print or send any other key.
16. Licence basis for EU law texts (EUR-Lex legal notice, archived copy
    https://web.archive.org/web/20260922160312/https://eur-lex.europa.eu/content/legal-notice/legal-notice.html):
    - Official Journal texts (acts as published): "Unless otherwise specified, you can re-use the legal documents
      published in EUR-Lex for commercial or non-commercial purposes." plus Commission Decision 2011/833/EU Article 4
      ("All documents shall be available for reuse: (a) for commercial or non-commercial purposes under the
      conditions laid down in Article 6") and the Article 6(2) conditions (acknowledge the source, do not distort the
      meaning). Do NOT label OJ texts "CC BY 4.0".
    - CC BY 4.0 applies only to "the editorial content of this website, the summaries of EU legislation and the
      consolidated texts". Consolidated texts may be labelled CC BY 4.0 with attribution and changes indicated.
    - The commission.europa.eu legal notice covers that website's own content only (e.g. the Taxonomy Navigator).
    Put the quotes, URLs and the date read in `data/SOURCES.md`.
17. Decision engines answer "depends" plus the precise question for counsel whenever a fact the provision needs is
    missing or the text leaves more than one reading open. A definite yes/no only when every needed fact is known.
18. Never answer with a fallback value for an input you did not recognise (an unknown country, code or name). Return a
    clear error or "not found"; use a fallback row (e.g. "Other") only when the user explicitly asks for it.
