#!/usr/bin/env python3
"""mcp-vitals hook: the same checks, at the moment an MCP server is added.

doctor.py reports on what is already configured. This runs the same checks
inside Claude Code, before the server lands in a config:

  PreToolUse on Bash    `claude mcp add ...` / `claude mcp add-json ...`:
                        if the server it would add is archived, abandoned,
                        deprecated, gone or unlicensed, the user is asked
                        before the command runs, with the facts as the reason.
  PostToolUse on edits  a write to .mcp.json, claude_desktop_config.json,
                        .cursor/mcp.json and the like: the same facts are
                        handed to Claude as context, for the servers the
                        edit added.

Clean servers pass silently. Anything the hook cannot parse, reach or
resolve passes silently too: a hook that blocks work because the network
is slow is a hook people uninstall. It never denies; the person decides.

Reads the hook payload on stdin, writes a hook response on stdout, and
like doctor.py never reads `env` or `headers`.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import doctor  # noqa: E402

# Short: this runs while someone waits for a command to start.
TIMEOUT = float(os.environ.get("MCP_VITALS_HOOK_TIMEOUT", "6"))
CONFIG_NAMES = {".mcp.json", "mcp.json", "claude_desktop_config.json", "mcp_config.json"}
# `claude mcp add` options that take a value, so neither the value nor the
# command after it is taken for the server name.
ADD_VALUE_FLAGS = {"-s", "--scope", "-t", "--transport", "-e", "--env", "-H", "--header",
                   "--client-id", "--client-secret", "--callback-port"}


# ---------------------------------------------------------------- parsing

def parse_add(command: str) -> list[dict]:
    """Server entries a `claude mcp add` or `add-json` command line would create."""
    try:
        words = shlex.split(command, posix=True)
    except ValueError:
        return []
    out = []
    # a compound line (`cd x && claude mcp add ...`) may hold more than one
    for i in range(len(words) - 2):
        if Path(words[i]).name != "claude" or words[i + 1] != "mcp":
            continue
        sub, rest = words[i + 2], words[i + 3:]
        rest = rest[:next((j for j, w in enumerate(rest) if w in ("&&", "||", ";", "|")), len(rest))]
        if sub == "add":
            entry = _parse_add_args(rest)
        elif sub == "add-json":
            entry = _parse_add_json(rest)
        else:
            continue
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
            pass
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
    positional = [w for w in rest if not w.startswith("-")]
    if len(positional) < 2:
        return None
    try:
        spec = json.loads(positional[1])
    except json.JSONDecodeError:
        return None
    if not isinstance(spec, dict):
        return None
    args = spec.get("args") if isinstance(spec.get("args"), list) else []
    return entry(positional[0], command=str(spec.get("command") or ""), args=[str(a) for a in args],
                 url=str(spec.get("url") or ""))


def entry(name: str, command: str = "", args: list[str] | None = None, url: str = "") -> dict:
    return {"client": "Claude Code", "config": "claude mcp add", "name": name,
            "command": command, "args": list(args or []), "url": url}


def added_by_edit(tool_input: dict) -> list[dict]:
    """Server entries in the config file an edit just wrote, limited to the ones the edit touched."""
    path = Path(str(tool_input.get("file_path") or ""))
    if path.name not in CONFIG_NAMES:
        return []
    data = doctor.read_config(path)
    if data is None:
        return []
    servers = []
    for key in ("mcpServers", "servers"):
        for name, spec in doctor.entries_in(data, key):
            args = spec.get("args") if isinstance(spec.get("args"), list) else []
            servers.append(entry(name, str(spec.get("command") or ""), [str(a) for a in args],
                                 str(spec.get("url") or "")) | {"config": str(path)})
    # Write carries the whole file, Edit only the new text. Either way, a server
    # whose name is not in the text the tool wrote was there before; leave it alone.
    written = str(tool_input.get("content") or tool_input.get("new_string") or "")
    for e in tool_input.get("edits") or []:  # MultiEdit
        written += str(e.get("new_string") or "") if isinstance(e, dict) else ""
    return [s for s in servers if json.dumps(s["name"].split(" [")[0]) in written]


# ---------------------------------------------------------------- checking

def findings(servers: list[dict], net: doctor.Net) -> list[dict]:
    today = dt.date.today()
    results = [doctor.examine(s, net, today) for s in servers]
    return [r for r in results if doctor.SERIOUS & set(r["flags"])]


def explain(r: dict) -> str:
    facts = (r["facts"].get("repository") or {})
    parts = [f"MCP server '{r['name']}' ({doctor.what(r)})"]
    if r["repo"]:
        parts.append(f"repository {r['repo']}")
    if r["days_since_push"] is not None:
        parts.append(f"last pushed {r['days_since_push']} days ago")
    if facts.get("archived"):
        parts.append("archived by its owner")
    dep = (r["facts"].get("registry") or {}).get("deprecated")
    if dep:
        parts.append(f"package deprecated: {str(dep)[:160].rstrip('. ')}")
    lead = ", ".join(parts)
    return f"{lead}. Flags: {', '.join(r['flags'])}."


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    event = payload.get("hook_event_name")
    tool = payload.get("tool_name")
    tool_input = payload.get("tool_input") or {}

    if event == "PreToolUse" and tool == "Bash":
        servers = parse_add(str(tool_input.get("command") or ""))
    elif event == "PostToolUse" and tool in ("Write", "Edit", "MultiEdit"):
        servers = added_by_edit(tool_input)
    else:
        return 0
    if not servers:
        return 0

    net = doctor.Net(False, os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"), timeout=TIMEOUT, census=False)
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
