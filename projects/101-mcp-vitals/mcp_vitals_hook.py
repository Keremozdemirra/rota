#!/usr/bin/env python3
"""mcp-vitals hook: the same checks, at the moment an MCP server is added.

mcp_vitals.py reports on what is already configured. This runs the same checks
inside Claude Code, before the server lands in a config:

  PreToolUse on Bash    `claude mcp add ...` / `claude mcp add-json ...`:
  and PowerShell        if the server it would add is archived, abandoned,
                        deprecated, gone or unlicensed, the user is asked
                        before the command runs, with the facts as the reason.
  PostToolUse on edits  a write to .mcp.json, claude_desktop_config.json,
                        .cursor/mcp.json and the like: the same facts are
                        handed to Claude as context. For Edit, only the
                        servers the edit added or changed are checked; Write
                        replaces the whole file, so every server in it is.

Clean servers pass silently. Anything the hook cannot parse, reach or
resolve passes silently too: a hook that blocks work because the network
is slow is a hook people uninstall. It never denies; the person decides.
("ask" still stops a command where nobody can answer a prompt, such as
`claude -p` or the dontAsk mode.)

Reads the hook payload on stdin, writes a hook response on stdout, and
like mcp_vitals.py never reads `env` or `headers`.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mcp_vitals  # noqa: E402

# Short: this runs while someone waits for a command to start.
TIMEOUT = float(os.environ.get("MCP_VITALS_HOOK_TIMEOUT", "6"))
CONFIG_NAMES = {".mcp.json", "mcp.json", "claude_desktop_config.json", "mcp_config.json"}
# `claude mcp add` options that take a value, so neither the value nor the
# command after it is taken for the server name (`claude mcp add --help`,
# Claude Code 2.1.281). --client-secret takes none: it prompts.
ADD_VALUE_FLAGS = {"-s", "--scope", "-t", "--transport", "-e", "--env", "-H", "--header",
                   "--client-id", "--callback-port"}
ADD_JSON_VALUE_FLAGS = {"-s", "--scope"}

# ---------------------------------------------------------------- parsing

PUNCTUATION = "();<>|&\n"
REDIRECTS = {">", ">>", "<", "<<", "<<<", ">&", "<&", "&>", "&>>", ">|", "<>"}
# Commands that run another command, and their options that take a value.
WRAPPERS = {"sudo": {"-u", "-g", "-C", "-D", "-h", "-p", "-r", "-t", "-U", "--user", "--group"},
            "doas": {"-u", "-C"}, "env": {"-u", "--unset", "-C", "--chdir", "-S", "--split-string"},
            "timeout": {"-s", "--signal", "-k", "--kill-after"}, "time": set(), "nohup": set(),
            "command": set(), "exec": {"-a"}}
WINDOWS_PATH = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:\\")


def split_commands(command: str, shell: str = "bash") -> list[list[str]]:
    """The simple commands in a shell line: `a; b`, `a&&b`, `a | b` and newlines all separate."""
    lx = shlex.shlex(command, posix=True, punctuation_chars=PUNCTUATION)
    lx.whitespace_split = True
    lx.whitespace = " \t\r"  # a newline separates commands; it is not just a space
    lx.commenters = ""  # `#` inside a word, as in github:o/n#main, is not a comment
    if shell == "powershell" or WINDOWS_PATH.search(command):
        # PowerShell's escape character is the backtick, and C:\Users\x is a path, not three escapes
        lx.escape = ""
    try:
        tokens = list(lx)
    except ValueError:  # unbalanced quotes
        return []
    commands, current, skip = [], [], False
    for t in tokens:
        if skip:
            skip = False
            continue
        if t in REDIRECTS:
            if current and current[-1].isdigit():  # the 2 in 2>&1
                current.pop()
            skip = True  # and the redirect's target
            continue
        if t and all(c in PUNCTUATION for c in t):
            if current:
                commands.append(current)
            current = []
            continue
        current.append(t)
    if current:
        commands.append(current)
    return commands


def _claude_at(words: list[str]) -> int | None:
    """Index of `claude` when it is the command word, after `VAR=x` prefixes and wrappers like sudo."""
    i = 0
    while i < len(words):
        w = words[i]
        name = mcp_vitals._basename(w)
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", w, re.S):
            i += 1
        elif name in WRAPPERS:
            i += 1
            while i < len(words) and words[i].startswith("-"):
                i += 2 if words[i] in WRAPPERS[name] else 1
            if name == "timeout" and i < len(words) and re.fullmatch(r"[0-9.]+[smhd]?", words[i]):
                i += 1  # the duration
        else:
            return i if name == "claude" else None
    return None


def parse_add(command: str, shell: str = "bash") -> list[dict]:
    """Server entries a `claude mcp add` or `add-json` command line would create."""
    out = []
    # a compound line (`cd x && claude mcp add ...`) may hold more than one
    for words in split_commands(command, shell):
        i = _claude_at(words)
        if i is None or words[i + 1:i + 2] != ["mcp"] or len(words) < i + 3:
            continue
        sub, rest = words[i + 2], words[i + 3:]
        entry = _parse_add_args(rest) if sub == "add" else _parse_add_json(rest) if sub == "add-json" else None
        if entry:
            out.append(entry)
    return out


def _parse_add_args(rest: list[str]) -> dict | None:
    positional, skip, i = [], False, 0
    while i < len(rest):
        w = rest[i]
        if w == "--":
            positional += rest[i + 1:]
            break
        if skip:
            skip = False
        elif w in ADD_VALUE_FLAGS:
            skip = True
            # -e and -H are variadic: `-e A=1 B=2 name cmd`. Values carry `=` or `:`,
            # a server name does not, so consume while they look like values.
            if w in ("-e", "--env", "-H", "--header"):
                while i + 2 < len(rest) and ("=" in rest[i + 2] or ":" in rest[i + 2]) and not rest[i + 2].startswith("-"):
                    i += 1
        elif w.startswith("-"):
            pass  # a boolean flag, or --flag=value
        else:
            positional.append(w)
            if len(positional) >= 2:  # name and command/url; everything after is the server's own args
                positional += [a for a in rest[i + 1:] if a != "--"]
                break
        i += 1
    if len(positional) < 2:
        return None
    name, target, args = positional[0], positional[1], positional[2:]
    if target.startswith(("http://", "https://")):
        return entry(name, url=target)
    return entry(name, command=target, args=args)


def _parse_add_json(rest: list[str]) -> dict | None:
    positional, skip = [], False
    for i, w in enumerate(rest):
        if skip:
            skip = False
        elif w == "--":
            positional += rest[i + 1:]
            break
        elif w in ADD_JSON_VALUE_FLAGS:
            skip = True
        elif w.startswith("-") and not w.startswith("{"):
            pass  # --client-secret, --scope=user
        else:
            positional.append(w)
    if len(positional) < 2:
        return None
    try:
        spec = json.loads(positional[1])
    except ValueError:
        return None
    if not isinstance(spec, dict):
        return None
    return mcp_vitals.server_entry("Claude Code", "claude mcp add", positional[0], spec)


def entry(name: str, command: str = "", args: list[str] | None = None, url: str = "") -> dict:
    return {"client": "Claude Code", "config": "claude mcp add", "name": name,
            "command": command, "args": list(args or []), "url": url}


def _servers(data: dict, path: Path) -> dict[str, dict]:
    found = {}
    for key in ("mcpServers", "servers"):
        for name, spec in mcp_vitals.entries_in(data, key):
            found[name] = mcp_vitals.server_entry("Claude Code", str(path), name, spec)
    return found


def _edits(tool_input: dict) -> list[tuple[str, str]]:
    pairs = [(tool_input.get("old_string"), tool_input.get("new_string"))]
    pairs += [(e.get("old_string"), e.get("new_string")) for e in tool_input.get("edits") or [] if isinstance(e, dict)]
    return [(str(o or ""), str(n)) for o, n in pairs if isinstance(n, str)]


def _undo(text: str, edits: list[tuple[str, str]]) -> str | None:
    """The file before the edits, when each new string appears exactly once and can be put back."""
    for old, new in reversed(edits):
        if not new or text.count(new) != 1:
            return None
        text = text.replace(new, old, 1)
    return text


def _mentioned(written: str, name: str, s: dict) -> bool:
    if re.search(re.escape(json.dumps(name)) + r"\s*:", written):
        return True
    tokens = [s["command"], s["url"], *s["args"]]
    return any(len(t) >= 4 and json.dumps(t)[1:-1] in written for t in tokens if t and not t.startswith("-"))


def added_by_edit(tool_input: dict, tool: str = "Edit") -> list[dict]:
    """Server entries in the config file an edit just wrote, limited to the ones the edit touched."""
    path = Path(str(tool_input.get("file_path") or ""))
    if path.name not in CONFIG_NAMES:
        return []
    data, _ = mcp_vitals.read_config(path)
    if data is None:
        return []
    now = _servers(data, path)
    if tool == "Write" or "content" in tool_input:
        return list(now.values())  # Write replaces the whole file: every server in it is checked
    edits = _edits(tool_input)
    try:
        before = _undo(path.read_text(encoding="utf-8"), edits)
    except (OSError, UnicodeDecodeError):
        before = None
    if before is not None:
        try:
            old = json.loads(before)
        except ValueError:
            old = None
        was = _servers(old, path) if isinstance(old, dict) else {}
        keys = ("command", "args", "url")
        return [s for n, s in now.items() if n not in was or any(was[n][k] != s[k] for k in keys)]
    # The file could not be rewound: fall back to what the edit wrote. A server counts
    # as touched if its name, as a key, or one of its longer words appears in it.
    written = " ".join(new for _, new in edits)
    return [s for n, s in now.items() if _mentioned(written, n.split(" [")[0], s)]


# ---------------------------------------------------------------- checking

def findings(servers: list[dict], net: mcp_vitals.Net) -> list[dict]:
    today = dt.date.today()
    results = [mcp_vitals.examine(s, net, today) for s in servers]
    return [r for r in results if mcp_vitals.SERIOUS & set(r["flags"])]


def explain(r: dict) -> str:
    facts = r["facts"].get("repository") or {}
    reg = r["facts"].get("registry") or {}
    parts = [f"MCP server '{r['name']}' ({mcp_vitals.what(r)})"]
    if r["repo"]:
        parts.append(f"repository {r['repo']}")
    if r["days_since_push"] is not None:
        parts.append(f"last pushed {r['days_since_push']} days ago")
    if facts.get("archived"):
        parts.append("archived by its owner")
    if reg.get("version_missing"):
        parts.append(f"{reg['registry']} has no version {r['version']}")
    if reg.get("deprecated"):
        # the registry's words are data from a third party: cut short, cleaned, and marked as such
        parts.append(f"{reg['registry']} marks {reg.get('version') or 'it'} deprecated: {mcp_vitals.remote_text(reg['deprecated'])}")
    return f"{', '.join(parts)}. Flags: {', '.join(r['flags'])}."


def main() -> int:
    try:
        return _main()
    except Exception:  # noqa: BLE001  a bug here must not get in the way of the command
        return 0


def _main() -> int:
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    if not isinstance(payload, dict):
        return 0
    event = payload.get("hook_event_name")
    tool = payload.get("tool_name")
    tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}

    if event == "PreToolUse" and tool in ("Bash", "PowerShell"):
        servers = parse_add(str(tool_input.get("command") or ""), "powershell" if tool == "PowerShell" else "bash")
    elif event == "PostToolUse" and tool in ("Write", "Edit", "MultiEdit"):
        servers = added_by_edit(tool_input, tool)
    else:
        return 0
    if not servers:
        return 0

    net = mcp_vitals.Net(False, os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"), timeout=TIMEOUT, census=False)
    found = findings(servers, net)
    if not found:
        return 0
    text = " ".join(explain(r) for r in found) + (
        " These are dates and registry flags from mcp-vitals, not a verdict on the code; a finished tool can go"
        " a year without a push and still work.")
    print(json.dumps(respond(event, text)))
    return 0


def respond(event: str, text: str) -> dict:
    if event == "PreToolUse":
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask",
                                       "permissionDecisionReason": text}}
    return {"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                   "additionalContext": text + " Tell the user before relying on this server."}}


if __name__ == "__main__":
    raise SystemExit(main())
