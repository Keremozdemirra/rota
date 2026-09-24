# hook-harness

Test and lint Claude Code hooks in CI: which handlers a tool call starts, what each one prints, and whether the hooks decide what you expect.

## Why

A hook that misbehaves is found by its users, one tool call at a time. Two ways it happens, both in the official docs (checked 2026-09-24):

- **Fan-out.** Claude Code runs every matching handler as its own process ("All matching hooks run in parallel", [hooks reference](https://code.claude.com/docs/en/hooks#hook-handler-fields)), and an `if` pattern that names more than a command "run[s] the hook anyway on `$()`, backticks, or `$VAR`" ([Bash matching table](https://code.claude.com/docs/en/hooks#bash-if-matching)). A hooks file with one `if` rule per install command therefore starts dozens of processes for one ordinary command.
- **An `if` rule that never matches.** "A single `if` rule matches only one tool's calls" ([hooks reference](https://code.claude.com/docs/en/hooks#how-a-hook-resolves)). A handler with `"if": "Edit(...)"` under a `Write|Edit` matcher never runs for Write, and nothing reports it.

`claude plugin validate` checks a hooks file's schema. hook-harness checks its behaviour: it runs your hook scripts against the calls you describe and fails the build when the result differs from what you expect.

## Example

Real output, 2026-09-24, against the hooks of two plugins from the same author, [mcp-vitals](https://github.com/Keremozdemirra/mcp-vitals) and [pkg-vitals](https://github.com/Keremozdemirra/pkg-vitals), at their current versions and at the versions before their reviews. Commands run from a scratch directory holding copies of both plugins and of `examples/`.

An earlier pkg-vitals `hooks.json` had 72 handlers, one per install command and shell, all running the same script:

```
$ hook-harness lint old-pkg-vitals/hooks/hooks.json
hook-harness 0.1.0 lint old-pkg-vitals/hooks/hooks.json (plugin hooks file; hooks docs checked 2026-09-24)
old-pkg-vitals/hooks/hooks.json:8:11: warning [fan-out] 36 PreToolUse handlers run 'python3 "${CLAUDE_PLUGIN_ROOT}/pkg_vitals_hook.py"' for Bash calls, one process per matching handler. A single Bash command with a $(...) or $VAR argument starts 32 of them at once; a compound command with one, or a command Claude Code cannot analyse (a here-document, ${VAR}, "$VAR"), starts all 36. One handler that filters inside the script starts one
[... a note and the same warning for PowerShell ...]
0 error(s), 2 warning(s), 1 note(s).

$ hook-harness run old-pkg-vitals/hooks/hooks.json examples/fan-out.cases.json --dry-run
hook-harness 0.1.0 run old-pkg-vitals/hooks/hooks.json examples/fan-out.cases.json (dry run)
PASS  an install command  (PreToolUse Bash, 1 process; not run)
FAIL  a command substitution  (PreToolUse Bash, 32 processes; not run)
      FAIL max_handlers: expected <= 1, got 32
      runs PreToolUse[0].hooks[0] (line 8): matcher 'Bash|PowerShell' lists 'Bash'; if 'Bash(npm install*)': the pattern 'npm install*' names more than a command, and "$(date)" is only known when the command runs; such patterns run the hook anyway (hooks docs)
[...]
FAIL  a variable in a compound command  (PreToolUse Bash, 36 processes; not run)
[...]
FAIL  a here-document  (PreToolUse Bash, 36 processes; not run)
[...]
PASS  a plain command  (PreToolUse Bash, 0 processes; not run)
5 case(s): 2 passed, 3 failed, 0 could not run.
```

Claude Code 2.1.281 started exactly 1, 32, 36, 36 and 0 processes for these five commands (`tools/crosscheck_claude_code.py`, below). The current pkg-vitals file has one handler and passes all five.

An earlier mcp-vitals `hooks.json` guarded `.mcp.json` edits with `Edit(...)` rules only:

```
$ hook-harness run old-mcp-vitals/hooks/hooks.json examples/mcp-vitals.cases.json --scratch-home --only "Write of .mcp.json"
hook-harness 0.1.0 run old-mcp-vitals/hooks/hooks.json examples/mcp-vitals.cases.json
FAIL  Write of .mcp.json gives Claude the facts  (PostToolUse Write, 0 processes, decision none, 0.00 s)
      FAIL context_contains: expected deprecated, got (nothing)
      FAIL handlers: expected == 1, got 0
      skip PostToolUse[0].hooks[0] (line 27): if 'Edit(//**/*mcp*.json)': the rule names Edit, the call is Write
      skip PostToolUse[0].hooks[1] (line 33): if 'Edit(//**/claude_desktop_config.json)': the rule names Edit, the call is Write
1 case(s): 0 passed, 1 failed, 0 could not run.
```

`hook-harness lint` flags the same file without running anything:

```
old-mcp-vitals/hooks/hooks.json:25:9: warning [if-uncovered-tool] Write calls reach this group's matcher, but every handler has an `if` for another tool, so nothing runs for Write (a single `if` rule matches only one tool's calls)
```

The current versions, running their real scripts (these look packages up on npm and PyPI, so the results depend on the registries on the day):

```
$ hook-harness run pkg-vitals/hooks/hooks.json examples/pkg-vitals.cases.json --scratch-home
hook-harness 0.1.0 run pkg-vitals/hooks/hooks.json examples/pkg-vitals.cases.json
PASS  npm install of a deprecated package asks  (PreToolUse Bash, 1 process, decision ask, 1.27 s)
PASS  a package name that is not on npm asks  (PreToolUse Bash, 1 process, decision ask, 0.27 s)
PASS  PowerShell installs are checked too  (PreToolUse PowerShell, 1 process, decision ask, 0.87 s)
PASS  a healthy install passes silently  (PreToolUse Bash, 1 process, decision none, 0.32 s)
PASS  a command with no installer starts one process and returns fast  (PreToolUse Bash, 1 process, decision none, 0.03 s)
PASS  file tools start nothing  (PreToolUse Write, 0 processes, decision none, 0.00 s)
6 case(s): 6 passed, 0 failed, 0 could not run.

$ hook-harness run mcp-vitals/hooks/hooks.json examples/mcp-vitals.cases.json --scratch-home
hook-harness 0.1.0 run mcp-vitals/hooks/hooks.json examples/mcp-vitals.cases.json
PASS  claude mcp add of a deprecated npm server asks  (PreToolUse Bash, 1 process, decision ask, 0.32 s)
PASS  the same command through PowerShell asks too  (PreToolUse PowerShell, 1 process, decision ask, 0.22 s)
PASS  an unrelated command starts no handler  (PreToolUse Bash, 0 processes, decision none, 0.00 s)
PASS  an unrelated command with $PATH still starts the handler, which stays silent  (PreToolUse Bash, 1 process, decision none, 0.07 s)
PASS  Write of .mcp.json gives Claude the facts  (PostToolUse Write, 1 process, decision none, 0.17 s)
PASS  Edit of .mcp.json gives Claude the facts  (PostToolUse Edit, 1 process, decision none, 0.62 s)
PASS  Write of another JSON file starts no handler  (PostToolUse Write, 0 processes, decision none, 0.00 s)
7 case(s): 7 passed, 0 failed, 0 could not run.
```

## Install

```
uvx hook-harness lint hooks/hooks.json
pipx run hook-harness run hooks/hooks.json tests/hooks.cases.json
```

Python 3.9 or later, standard library only. `hook_harness.py` is a single file and also runs as `python3 hook_harness.py ...`.

## Commands

`hook-harness lint HOOKS.json` checks a plugin's `hooks/hooks.json` or a settings file (`.claude/settings.json`) without running anything. `--plugin-root DIR` names the directory `${CLAUDE_PLUGIN_ROOT}` stands for (default: the parent of `hooks/`); `--project-dir DIR` does the same for `${CLAUDE_PROJECT_DIR}`.

`hook-harness run HOOKS.json CASES.json` runs the cases. Options: `--dry-run` shows which handlers each case starts and runs nothing; `--scratch-home` runs every handler with `HOME` set to an empty temporary directory, so a hook under test cannot read your own configuration; `--only TEXT` runs the cases whose name contains TEXT; `-v` shows details for passing cases too.

Both take `--json`, `--markdown` (for `$GITHUB_STEP_SUMMARY`) and `--strict`.

| Exit code | `lint` | `run` |
|---|---|---|
| 0 | read and checked (without `--strict`, findings do not change the code) | every case passed |
| 1 | with `--strict`: an error or warning | a case failed; with `--strict`, an output warning or an assumed `if` result fails the case too |
| 2 | the file could not be read, or an option names a missing directory | a file could not be read or is not a valid cases file, or a handler could not be run on this machine (no PowerShell, a `${user_config.*}` value the cases file does not give) |

A JSON syntax error in the hooks file is a finding (`lint`) with its line and column: Claude Code cannot load that file either.

## Cases

```json
{
  "project_dir": "fixture-project",
  "env": {"PKG_VITALS_TIMEOUT": "5"},
  "cases": [
    {
      "name": "npm install of a deprecated package asks",
      "event": "PreToolUse",
      "tool_name": "Bash",
      "tool_input": {"command": "npm install left-pad"},
      "expect": {"handlers": 1, "decision": "ask", "reason_contains": "deprecated", "max_duration": 20}
    }
  ]
}
```

Case fields: `name`, `event` (default `PreToolUse`), `tool_name` (required on tool events; checked against the tools reference, so `bash` is an error), `tool_input`, `tool_response` (PostToolUse), `error` (PostToolUseFailure), `cwd` (relative to the cases file; default the project directory), `env`, and `payload` for anything else the stdin JSON should carry. Events that are not about a tool need the field their matcher is compared with, e.g. `"payload": {"source": "startup"}` for SessionStart. Top level: `project_dir`, `plugin_root`, `env`, `user_config` (values for `${user_config.*}`).

Expectations, all optional:

| Key | Meaning |
|---|---|
| `decision` | `none`, `allow`, `ask`, `deny`, `defer` or `block`, after combining every handler (PreToolUse precedence deny > defer > ask > allow; exit 2 counts as deny on PreToolUse and as block on the other events that can block) |
| `reason_contains` | text (or a list) found in the permissionDecisionReason, `reason`, `stopReason`, or the stderr of an exit 2 |
| `context_contains` | text (or a list) found in additionalContext (and in plain stdout on the events that add it as context) |
| `max_duration` | seconds, wall clock for the case, handlers running in parallel |
| `handlers`, `max_handlers`, `min_handlers` | how many handler processes the call starts, after duplicates are merged |

An unknown key is an error, so a typo cannot pass silently. Every handler's output is also checked against the documented shape for the event; an error there (wrong `hookEventName`, a `permissionDecision` that is not a documented value, `permissionDecision` at the top level, JSON that does not parse) fails the case.

## GitHub Actions

```yaml
name: hooks
on: [push, pull_request]
permissions:
  contents: read
jobs:
  hooks:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803 # v6.1.0
      - uses: actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1 # v6.3.0
        with:
          python-version: "3.12"
      - run: python -m pip install hook-harness==0.1.0
      - run: hook-harness lint hooks/hooks.json --strict
      - run: hook-harness run hooks/hooks.json tests/hooks.cases.json --scratch-home --markdown >> "$GITHUB_STEP_SUMMARY"
```

The last step writes its report to the job summary; its exit code still fails the job, since a redirect keeps the command's status.

## How it decides which handlers run

This is an approximation of Claude Code's own logic. It implements these documented rules (hooks reference, hooks guide, permissions and tools reference pages, checked 2026-09-24):

- Matchers: `*`, `""` or none match everything; letters, digits, `_`, `-`, spaces, `,` and `|` form an exact, case-sensitive list; anything else is an unanchored regular expression (Python's `re`, which agrees with JavaScript's for what matchers use). FileChanged and StopFailure use the narrower exact set. Events without matcher support ignore it.
- `if` holds one permission rule and is evaluated only on the five tool events; on any other event a handler with `if` never runs. One rule matches one tool's calls.
- Bash rules: `*` matches any text, a trailing ` *` also matches the bare command, `:*` equals ` *`; each subcommand of a compound command is checked (`&&`, `||`, `;`, `|`, `|&`, `&`, newlines), commands inside `$()`, backticks, subshells and control-flow bodies too; leading `VAR=value` assignments are stripped; a command name only known at run time runs every handler; patterns naming more than a command run on `$()`, backticks and `$VAR`; a command that cannot be analysed runs every handler.
- File rules (Read, Edit, Write, NotebookEdit, Grep, Glob, LSP): gitignore syntax; `//` is the filesystem root, `~/` the home directory, `/` the project; a bare name matches at any depth; `src/**` only at the working directory (the depth the hooks docs give for `if`); Windows paths become `/c/...`.
- PowerShell rules: the Bash shape, case-insensitive, aliases canonicalized (the Windows compatibility aliases from [Microsoft Learn](https://learn.microsoft.com/en-us/powershell/scripting/learn/shell/using-aliases), checked 2026-09-24).
- Duplicates: the same handler defined twice runs once; a plugin's copy runs separately.

Where the docs are silent or Claude Code 2.1.281 behaved differently, hook-harness follows what was observed:

| Behaviour in an `if` | Observed with Claude Code 2.1.281 |
|---|---|
| Wrappers | `timeout`, `nice`, `nohup`, `command`, `time`, `stdbuf`, `builtin`, `noglob` are not stripped (the permissions page strips them for permission rules); bare `xargs` is |
| Quotes and spacing | removed before matching: `git 'push' origin main` matches `Bash(git push *)` (the permissions page says a deny rule does not); runs of spaces count as one |
| `$HOME` | treated as static; every other variable is not |
| Commands that run every handler | a double-quoted `"$VAR"`; `${VAR}`; a variable joined to other text (`a$DIR`); a `$` that starts nothing; an unquoted here-document delimiter, or a quoted one next to a pipe or another redirection; `$'...'`; `{ ...; }`, `case`, functions, `<(...)`; a backslash-escaped space; any expansion in a compound command, in a command with a redirection, after an assignment, or as an argument of a command that runs code (`bash`, `sh`, `python`, `node`, `eval`, `env`, `sudo`, `timeout`, `xargs`, `find`, and others) |
| Not dynamic | `$(( ))` outside quotes; `$( )` inside a double-quoted string that holds other text; `$( )` in an assignment |
| `[ ... ]` | matched as `[[ ... ]]` |
| File rules | case-insensitive; `/path` anchored at the project for a `--settings` file and a plugin alike; `./x` behaves like `x`; `*` and `**` match any path, outside the project too |
| Other tools | `WebFetch(domain:...)`, `Agent(name)` and MCP rules with a specifier never matched; only the bare name or `(*)` did. Tool-name globs (`mcp__*`, `*`) and server-level `mcp__server` never matched |
| Duplicates | same `command`, `args` and `if` run once, across groups; `timeout` and `statusMessage` make no difference; a different `if` makes a second process |

`tools/crosscheck_claude_code.py` reproduces all of this with an installed Claude Code: it sends scripted tool calls through the real CLI (a local stand-in for the Messages API, a placeholder key only that stand-in sees, an empty temporary HOME, a catch-all hook that denies every call so nothing probed runs) and compares, rule by rule, which handlers started. Results on 2026-09-24 with Claude Code 2.1.281:

| Corpus | Agreement |
|---|---|
| `fitted`: the probes the rules above were derived from | 7433 of 7433 rule/call pairs |
| `heldout`: written after the first model | 991 of 1045 before the model was revised on it, 1045 of 1045 after |
| `heldout2`: written after that revision, run once | 660 of 688. The 20 misses on a here-document feeding a pipe were then fixed; 8 remain on `wc -l $(git ls-files '*.py')`, where Claude Code ran every handler and hook-harness predicts only the longer patterns |
| `hooks` mode on the four real hooks files above | 22 of 22 cases agree on the number of processes (PowerShell cases not counted: the PowerShell tool is not enabled on the Linux machine used) |

PowerShell matching follows the docs only and is not cross-checked. A new Claude Code version can change any observed row; re-run the tool against yours.

## How it runs a handler

As the hooks reference describes: the payload on stdin (`session_id`, `transcript_path` pointing at an empty file, `cwd`, `permission_mode`, `hook_event_name`, and for tool events `tool_name`, `tool_input` with file paths made absolute, `tool_use_id` fresh for every case, `tool_response` on PostToolUse); `${CLAUDE_PROJECT_DIR}`, `${CLAUDE_PLUGIN_ROOT}` and `${CLAUDE_PLUGIN_DATA}` substituted and exported (the plugin ones only for a plugin's hooks file, as observed); shell form through `sh -c` (Git Bash or PowerShell on Windows), exec form spawned directly when `args` is present; the parent environment minus `OTEL_*`; each handler in its own session, all matching handlers in parallel, the whole process group killed at the handler's `timeout` in seconds (default 600, 30 on UserPromptSubmit and the model-switch events, 10 on MessageDisplay). Output is read the way Claude Code reads it: JSON only when stdout starts with `{` and ends with `}`, exit 2 blocks on the events that can block, other non-zero codes are non-blocking errors unless the JSON is valid, a timed-out handler's output is discarded. `http`, `mcp_tool`, `prompt` and `agent` handlers are matched and counted but not run.

## Lint rules

| Rule | Severity | What it reports |
|---|---|---|
| `json-syntax`, `json-bom`, `json-shape`, `duplicate-key`, `hooks-key`, `hooks-shape` | error / warning | syntax errors with line and column, a byte order mark, keys given twice, event names outside `"hooks"` |
| `unknown-event`, `handler-type`, `missing-field`, `unknown-field` | error / warning | names Claude Code does not know (case-sensitive), a handler without its required field, typos in field names |
| `fan-out`, `duplicate-handler`, `if-wide` | warning / note | several handlers running one command for one tool, with the number of processes per call shape; duplicates that run once; `if` patterns that also fire on every `$(...)` or `$VAR` command |
| `if-outside-matcher`, `if-uncovered-tool`, `if-non-tool-event`, `if-syntax`, `if-tool-name`, `if-specifier`, `if-param-rule`, `if-path` | error / warning | handlers that can never run, tools in a matcher that no handler covers, `&&` or lists in an `if`, rule forms that matched nothing in Claude Code 2.1.281 |
| `matcher-ignored`, `matcher-invalid`, `matcher-unknown-tool`, `matcher-mcp`, `matcher-unknown-value`, `matcher-legacy-tool` | error / warning / note | matchers that are ignored, do not compile, match no tool (`bash`, `mcp__server`), or misspell a documented value |
| `timeout-ms`, `timeout` | warning / error | a `timeout` above 600, which looks like milliseconds (hook-harness's own threshold: 600 s is Claude Code's default for command hooks), or not a positive number |
| `plugin-file`, `script-not-executable`, `project-file`, `plugin-root`, `placeholder-quotes`, `user-config-shell`, `exec-command`, `shell` | error / warning | `${CLAUDE_PLUGIN_ROOT}/...` files that do not exist or are not executable, unquoted placeholders in shell form, forms the docs say fail |
| `windows-powershell`, `windows-exec-shim`, `windows-interpreter`, `powershell-env` | warning / note | shell hooks that miss the PowerShell tool (the primary shell on Windows), exec form on `.cmd` shims, `python3` as the interpreter ([Python docs](https://docs.python.org/3/using/windows.html): its `python3` on Windows "is not meant to be widely used or recommended", checked 2026-09-24), bare `$CLAUDE_PROJECT_DIR` in PowerShell |
| `async-decision`, `once-ignored`, `disable-all-hooks` | warning / note | fields that do nothing where they are |

## Sources, what it reads, what it sends

The rules come from Anthropic's Claude Code documentation: [hooks reference](https://code.claude.com/docs/en/hooks), [hooks guide](https://code.claude.com/docs/en/hooks-guide), [permissions](https://code.claude.com/docs/en/permissions), [tools reference](https://code.claude.com/docs/en/tools-reference) and [plugins reference](https://code.claude.com/docs/en/plugins-reference), all read on 2026-09-24, plus the Microsoft Learn and Python pages linked above. hook-harness quotes a few short phrases from them and bundles no data.

It reads the hooks file and the cases file you name, and the files a hooks file references under `${CLAUDE_PLUGIN_ROOT}` or `${CLAUDE_PROJECT_DIR}` (only whether they exist). `run` executes the hook commands in the hooks file, with your environment, so run it only on hooks you would let Claude Code run. hook-harness itself makes no network request; the hooks it runs may (the pkg-vitals and mcp-vitals examples query npm, PyPI and GitHub). Printed output masks what looks like a secret (URL credentials and query strings, `--token`-style arguments, `KEY=value`, bearer tokens, common token formats), removes control characters, and prefixes captured hook output so that it cannot be read as a CI workflow command.

## What this is not

- Not Claude Code. Which handlers run is an approximation, cross-checked against Claude Code 2.1.281 only; a later version may differ, and the docs say the `if` filter itself is best-effort.
- Not a schema validator: `claude plugin validate` checks plugin manifests and hooks files against Claude Code's own schema.
- Not a sandbox: `run` executes your hook scripts for real.
- It does not read hooks from skill or subagent frontmatter, or inline in `plugin.json`, and it does not merge several settings files.
- It does not run `http`, `mcp_tool`, `prompt` or `agent` handlers, and it does not evaluate permission rules, permission modes or the auto mode classifier.
