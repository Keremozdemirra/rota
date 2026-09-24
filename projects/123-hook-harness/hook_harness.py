#!/usr/bin/env python3
"""hook-harness: test and lint Claude Code hooks in CI.

  hook-harness lint HOOKS.json
      Static checks on a plugin's hooks/hooks.json or a settings file: handlers that can never run, one tool call
      fanning out to many handler processes, `if` rules the group's matcher excludes, timeouts that look like
      milliseconds, ${CLAUDE_PLUGIN_ROOT} files that do not exist, shell hooks that miss PowerShell, JSON syntax
      errors with line numbers.

  hook-harness run HOOKS.json CASES.json
      For each case (an event and a tool call) works out which handlers Claude Code would start, runs each command
      handler the way the hooks docs describe (JSON payload on stdin, path placeholders, the handler's timeout),
      validates what it prints against the documented output shape for the event, and checks the case's
      expectations: decision, reason or context text, duration, number of handler processes.

Which handlers run is an approximation of Claude Code's own logic: the matcher and `if` rules from the hooks and
permissions docs (checked 2026-09-24), refined where Claude Code 2.1.281 was observed to behave differently or the
docs say nothing (tools/crosscheck_claude_code.py reproduces every observation). README.md lists each rule and its
source. Standard library only; nothing here touches the network.
"""
from __future__ import annotations

import argparse
import bisect
import json
import os
import posixpath
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import uuid
from dataclasses import dataclass, field
from pathlib import Path

VERSION = "0.1.0"
DOCS_CHECKED = "2026-09-24"
OBSERVED = "Claude Code 2.1.281"
HOOKS_DOC = "https://code.claude.com/docs/en/hooks"
GUIDE_DOC = "https://code.claude.com/docs/en/hooks-guide"
PERMISSIONS_DOC = "https://code.claude.com/docs/en/permissions"
TOOLS_DOC = "https://code.claude.com/docs/en/tools-reference"
PLUGINS_DOC = "https://code.claude.com/docs/en/plugins-reference"
PYWIN_DOC = "https://docs.python.org/3/using/windows.html"
PSALIAS_DOC = "https://learn.microsoft.com/en-us/powershell/scripting/learn/shell/using-aliases"

# ---------------------------------------------------------------- the documented model (hooks docs, 2026-09-24)

TOOL_EVENTS = ("PreToolUse", "PostToolUse", "PostToolUseFailure", "PermissionRequest", "PermissionDenied")
# "Matcher patterns": the input field each event's matcher is compared with.
MATCHER_FIELD = {
    **{e: "tool_name" for e in TOOL_EVENTS},
    "SessionStart": "source", "Setup": "trigger", "SessionEnd": "reason", "Notification": "notification_type",
    "SubagentStart": "agent_type", "SubagentStop": "agent_type", "PreCompact": "trigger", "PostCompact": "trigger",
    "PreModelSwitch": "to_model", "PostModelSwitch": "to_model", "ConfigChange": "source", "DirectoryAdded": "source",
    "FileChanged": "file_path", "StopFailure": "error", "InstructionsLoaded": "load_reason",
    "UserPromptExpansion": "command_name", "Elicitation": "mcp_server_name", "ElicitationResult": "mcp_server_name",
}
NO_MATCHER_EVENTS = {"UserPromptSubmit", "PostToolBatch", "Stop", "TeammateIdle", "TaskCreated", "TaskCompleted",
                     "WorktreeCreate", "WorktreeRemove", "MessageDisplay", "CwdChanged"}
EVENTS = set(MATCHER_FIELD) | NO_MATCHER_EVENTS
# FileChanged and StopFailure keep a narrower exact-match set: letters, digits, `_` and `|`.
NARROW_MATCHER_EVENTS = {"FileChanged", "StopFailure"}
# Documented matcher values, for spotting a typo such as "Startup"; free-form fields (agent types, models) are absent.
MATCHER_VALUES = {
    "SessionStart": {"startup", "resume", "clear", "compact", "fork"},
    "Setup": {"init", "maintenance"},
    "SessionEnd": {"clear", "resume", "logout", "prompt_input_exit", "other"},
    "PreCompact": {"manual", "auto"}, "PostCompact": {"manual", "auto"},
    "ConfigChange": {"user_settings", "project_settings", "local_settings", "policy_settings", "skills"},
    "DirectoryAdded": {"slash_command", "register_repo_root"},
    "InstructionsLoaded": {"session_start", "nested_traversal", "path_glob_match", "include", "compact"},
    "StopFailure": {"rate_limit", "overloaded", "authentication_failed", "oauth_org_not_allowed", "account_on_hold",
                    "billing_error", "invalid_request", "model_not_found", "server_error", "max_output_tokens",
                    "cloud_credential_error", "unknown"},
    "Notification": {"permission_prompt", "idle_prompt", "auth_success", "elicitation_dialog", "elicitation_url_dialog",
                     "elicitation_complete", "elicitation_response", "agent_needs_input", "agent_completed",
                     "quota_auto_resume_fired", "quota_auto_resume_stale", "quota_auto_resume_disabled"},
}
# "Exit code 2 behavior per event": the events an exit 2 blocks.
BLOCKING_EVENTS = {"PreToolUse", "UserPromptSubmit", "UserPromptExpansion", "Stop", "SubagentStop", "TeammateIdle",
                   "TaskCreated", "TaskCompleted", "ConfigChange", "PostToolBatch", "PreCompact", "PreModelSwitch",
                   "Elicitation", "ElicitationResult", "WorktreeCreate", "WorktreeRemove"}
# Events that show an exit-2 hook's stderr to Claude or the user without blocking anything.
FEEDBACK_EVENTS = {"PostToolUse", "PostToolUseFailure", "SubagentStart", "SessionStart", "SessionEnd", "CwdChanged",
                   "FileChanged", "PostCompact", "PostModelSwitch"}
# "Decision control": events whose top-level `decision` is "block".
TOP_DECISION_EVENTS = {"UserPromptSubmit", "UserPromptExpansion", "PostToolUse", "PostToolUseFailure", "PostToolBatch",
                       "Stop", "SubagentStop", "ConfigChange", "PreCompact", "TaskCreated", "PreModelSwitch"}
# "Exit code 0": events where plain-text stdout becomes context Claude can see.
PLAIN_CONTEXT_EVENTS = {"UserPromptSubmit", "UserPromptExpansion", "SessionStart", "PostModelSwitch"}
# Events whose JSON output Claude Code discards (per event section), apart from terminalSequence.
DISCARDED_OUTPUT_EVENTS = {"Setup", "InstructionsLoaded", "SessionEnd", "StopFailure", "WorktreeRemove"}
UNIVERSAL_FIELDS = {"continue": bool, "stopReason": str, "suppressOutput": bool, "systemMessage": str,
                    "terminalSequence": str}
_S, _B, _O, _L, _A = str, bool, dict, list, object
HSO_FIELDS = {
    "PreToolUse": {"permissionDecision": ("allow", "deny", "ask", "defer"), "permissionDecisionReason": _S,
                   "updatedInput": _O, "additionalContext": _S},
    "PermissionRequest": {"decision": _O},
    "PostToolUse": {"additionalContext": _S, "classifierContext": _S, "updatedToolOutput": _A,
                    "updatedMCPToolOutput": _A},
    "PostToolUseFailure": {"additionalContext": _S},
    "PostToolBatch": {"additionalContext": _S},
    "PermissionDenied": {"retry": _B},
    "UserPromptSubmit": {"additionalContext": _S, "sessionTitle": _S, "suppressOriginalPrompt": _B},
    "UserPromptExpansion": {"additionalContext": _S},
    "SessionStart": {"additionalContext": _S, "initialUserMessage": _S, "sessionTitle": _S, "watchPaths": _L,
                     "reloadSkills": _B},
    "SubagentStart": {"additionalContext": _S},
    "SubagentStop": {"additionalContext": _S},
    "Stop": {"additionalContext": _S},
    "PostModelSwitch": {"additionalContext": _S},
    "PreModelSwitch": {"permissionDecision": ("allow", "deny", "ask"), "permissionDecisionReason": _S},
    "MessageDisplay": {"displayContent": _S},
    "CwdChanged": {"watchPaths": _L},
    "FileChanged": {"watchPaths": _L},
    "Elicitation": {"action": ("accept", "decline", "cancel"), "content": _O},
    "ElicitationResult": {"action": ("accept", "decline", "cancel"), "content": _O},
    "WorktreeCreate": {"worktreePath": _S},
}
# Fields people put at the top level although they belong inside hookSpecificOutput ("Hook JSON has no effect").
NESTED_ONLY = {"permissionDecision", "permissionDecisionReason", "updatedInput", "additionalContext",
               "updatedToolOutput", "updatedMCPToolOutput", "retry", "watchPaths", "sessionTitle",
               "initialUserMessage", "reloadSkills", "displayContent", "classifierContext"}
PRECEDENCE = {"deny": 4, "defer": 3, "ask": 2, "allow": 1}  # PreToolUse: deny > defer > ask > allow
# "A hook's additionalContext, systemMessage ... are capped at 10,000 characters" (hooks docs, 2026-09-24).
CONTEXT_CAP = 10_000
HANDLER_TYPES = {"command", "http", "mcp_tool", "prompt", "agent"}
COMMON_FIELDS = {"type", "if", "timeout", "statusMessage", "once"}
TYPE_FIELDS = {"command": {"command", "args", "async", "asyncRewake", "shell"},
               "http": {"url", "headers", "allowedEnvVars"},
               "mcp_tool": {"server", "tool", "input"},
               "prompt": {"prompt", "model", "continueOnBlock"},
               "agent": {"prompt", "model"}}
REQUIRED_FIELDS = {"command": ("command",), "http": ("url",), "mcp_tool": ("server", "tool"), "prompt": ("prompt",),
                   "agent": ("prompt",)}
# "Only type: command and type: mcp_tool hooks are supported" on SessionStart; Setup runs command hooks only.
EVENT_TYPES = {"SessionStart": {"command", "mcp_tool"}, "Setup": {"command"}}
# Common fields: `timeout` defaults, in seconds.
DEFAULT_TIMEOUT = {"command": 600, "http": 600, "mcp_tool": 600, "prompt": 30, "agent": 60}
SHORT_TIMEOUT_EVENTS = {"UserPromptSubmit": 30, "PreModelSwitch": 30, "PostModelSwitch": 30, "MessageDisplay": 10,
                        "SessionEnd": 1.5}
# hook-harness's own threshold, not a Claude Code limit: 600 s is the documented default for command hooks, so a
# larger value is far more often milliseconds typed into a field that takes seconds.
MS_TIMEOUT_THRESHOLD = 600
# Events whose permission-style decision an async handler cannot deliver (hooks docs, "Run hooks in the background").
DECISION_EVENTS = {"PreToolUse", "PermissionRequest", "UserPromptSubmit", "UserPromptExpansion", "Stop",
                   "SubagentStop", "PostToolBatch", "PreCompact", "PreModelSwitch", "TaskCreated", "TaskCompleted",
                   "ConfigChange", "TeammateIdle"}
PERMISSION_MODES = ("default", "plan", "acceptEdits", "auto", "dontAsk", "bypassPermissions")
# Events whose documented stdin example carries permission_mode.
PERMISSION_MODE_EVENTS = set(TOOL_EVENTS) | {"UserPromptSubmit", "UserPromptExpansion", "Stop", "SubagentStop",
                                             "TeammateIdle", "PostToolBatch"}

# Tools reference, checked 2026-09-24. MultiEdit is "the legacy MultiEdit tool" on the permissions page.
KNOWN_TOOLS = {"Agent", "Artifact", "AskUserQuestion", "Bash", "CronCreate", "CronDelete", "CronList", "Edit",
               "EndConversation", "EnterPlanMode", "EnterWorktree", "ExitPlanMode", "ExitWorktree", "Glob", "Grep",
               "ListAgents", "ListMcpResourcesTool", "LSP", "Monitor", "NotebookEdit", "PowerShell",
               "PushNotification", "Read", "ReadMcpResourceTool", "RemoteTrigger", "ReportFindings", "ScheduleWakeup",
               "SendFeedback", "SendMessage", "SendUserFile", "ShareOnboardingGuide", "Skill", "SubagentHandback",
               "TaskCreate", "TaskGet", "TaskList", "TaskOutput", "TaskStop", "TaskUpdate", "TodoWrite", "ToolSearch",
               "WaitForMcpServers", "WebFetch", "WebSearch", "Workflow", "Write"}
LEGACY_TOOLS = {"MultiEdit"}
# Tools reference, "Configure tools with permission rules and hooks": which rule format each tool takes.
COMMAND_RULE_TOOLS = {"Bash", "Monitor"}
PATH_RULE_FIELDS = {"Read": "file_path", "Grep": "path", "Glob": "path", "LSP": "file_path", "Edit": "file_path",
                    "Write": "file_path", "NotebookEdit": "notebook_path", "MultiEdit": "file_path"}
# PreToolUse input: Claude Code makes these absolute before hooks run.
ABSOLUTE_PATH_FIELDS = {"Write": "file_path", "Edit": "file_path", "Read": "file_path", "MultiEdit": "file_path",
                        "NotebookEdit": "notebook_path"}
# Microsoft Learn, "Compatibility aliases in Windows" (checked 2026-09-24); the permissions docs name gci, ls and dir.
PS_ALIASES = {
    "Set-Location": ("sl", "cd", "chdir"), "Clear-Host": ("cls", "clear"), "Copy-Item": ("cpi", "cp", "copy"),
    "Remove-Item": ("ri", "del", "erase", "rd", "rm", "rmdir"), "Get-ChildItem": ("gci", "dir", "ls"),
    "Write-Output": ("write", "echo"), "New-Item": ("ni",), "Move-Item": ("mi", "move", "mv"),
    "Pop-Location": ("popd",), "Get-Location": ("gl", "pwd"), "Push-Location": ("pushd",),
    "Rename-Item": ("rni", "ren"), "Get-Content": ("gc", "cat", "type"),
}
PS_CANONICAL = {a.lower(): c for c, al in PS_ALIASES.items() for a in al}
# npm-installed commands are .cmd shims on Windows (hooks docs, exec form note).
WINDOWS_SHIMS = {"npm", "npx", "pnpm", "pnpx", "yarn", "eslint", "prettier", "tsc", "tsx", "biome", "jest", "vitest"}
PLACEHOLDERS = ("CLAUDE_PROJECT_DIR", "CLAUDE_PLUGIN_ROOT", "CLAUDE_PLUGIN_DATA")

# ---------------------------------------------------------------- text that leaves this program

_USERINFO = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^/\s@]+@")
_QUERY = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://[^\s?#]*)\?[^\s#>\"']*")
_KEYARG = re.compile(r"(?i)(--?[a-z0-9_-]*(?:key|token|secret|passw(?:or)?d|auth|credential)[a-z0-9_-]*)(=|\s+)"
                     r"(?!\*\*\*)([^\s\"']+)")
_KEYVAR = re.compile(r"\b([A-Za-z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|AUTH|CREDENTIAL)[A-Za-z0-9_]*)=(?!\*\*\*)"
                     r"([^\s\"']+)", re.I)
_BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}")
_TOKENS = re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}|"
                     r"xox[abprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|glpat-[A-Za-z0-9_-]{20,})")


def mask(text: str) -> str:
    """Hide what could be a secret: URL userinfo and query strings, --token-like arguments, KEY=value, bearer
    credentials and well-known token shapes. Hook output and commands are printed in CI logs."""
    text = _USERINFO.sub(r"\1***@", text)
    text = _QUERY.sub(r"\1?***", text)
    text = _KEYARG.sub(lambda m: m.group(1) + m.group(2) + "***", text)
    text = _KEYVAR.sub(r"\1=***", text)
    text = _BEARER.sub(lambda m: m.group(1) + " ***", text)
    return _TOKENS.sub("***", text)


def clean(text, limit: int = 300, lines: bool = False) -> str:
    """Masked first (a cut could separate a secret from the delimiter the mask looks for), then control and
    invisible characters out, then shortened. Terminal escapes in a hook's output must not reach the reader's
    terminal or be read as CI workflow commands."""
    s = mask(str(text))
    keep = "\n" if lines else ""
    s = "".join(c if c == keep or c == "\t" else " " if unicodedata.category(c) == "Cc"
                else "" if unicodedata.category(c) in ("Cf", "Co", "Cn", "Cs") else c for c in s)
    if not lines:
        s = " ".join(s.split())
    if len(s) > limit:
        s = s[:limit].rstrip() + f" [... {len(s) - limit} more characters]"
    return s


def scrub(obj):
    if isinstance(obj, str):
        return mask(obj)
    if isinstance(obj, list):
        return [scrub(x) for x in obj]
    if isinstance(obj, dict):
        return {k: scrub(v) for k, v in obj.items()}
    return obj


# ---------------------------------------------------------------- loading JSON with line numbers

@dataclass
class Finding:
    rule: str
    severity: str  # error: never runs or rejected; warning: runs, likely not as meant; note: worth knowing
    message: str
    path: tuple = ()
    line: int | None = None
    col: int | None = None
    source: str = ""

    def where(self) -> str:
        return "/".join(str(p) for p in self.path)


class _Positions:
    """Where each value (and each object key) starts, found by a second pass over text json.loads accepted."""

    def __init__(self, text: str):
        self.text, self.i = text, 0
        self.nl = [m.start() for m in re.finditer("\n", text)]
        self.values: dict[tuple, tuple[int, int]] = {}
        self.keys: dict[tuple, tuple[int, int]] = {}
        self.duplicates: list[tuple[tuple, int, int]] = []

    def lc(self, i: int) -> tuple[int, int]:
        n = bisect.bisect_left(self.nl, i)
        return n + 1, i - (self.nl[n - 1] + 1 if n else 0) + 1

    def ws(self):
        while self.i < len(self.text) and self.text[self.i] in " \t\r\n":
            self.i += 1

    def string(self) -> str:
        j = self.i + 1
        while self.text[j] != '"':
            j += 2 if self.text[j] == "\\" else 1
        s = json.loads(self.text[self.i:j + 1])
        self.i = j + 1
        return s

    def value(self, path: tuple):
        self.ws()
        self.values[path] = self.lc(self.i)
        c = self.text[self.i]
        if c == "{":
            self.i += 1
            seen = set()
            self.ws()
            if self.text[self.i] == "}":
                self.i += 1
                return
            while True:
                self.ws()
                at = self.i
                key = self.string()
                self.keys[path + (key,)] = self.lc(at)
                if key in seen:
                    self.duplicates.append((path + (key,),) + self.lc(at))
                seen.add(key)
                self.ws()
                self.i += 1  # ':'
                self.value(path + (key,))
                self.ws()
                c = self.text[self.i]
                self.i += 1
                if c == "}":
                    return
        elif c == "[":
            self.i += 1
            self.ws()
            if self.text[self.i] == "]":
                self.i += 1
                return
            n = 0
            while True:
                self.value(path + (n,))
                n += 1
                self.ws()
                c = self.text[self.i]
                self.i += 1
                if c == "]":
                    return
        elif c == '"':
            self.string()
        else:
            m = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null").match(self.text, self.i)
            self.i = m.end()


@dataclass
class Source:
    path: Path
    data: object = None
    kind: str = "other"  # plugin | settings | other
    plugin_root: Path | None = None
    project_dir: Path | None = None
    problems: list = field(default_factory=list)
    values: dict = field(default_factory=dict)
    keys: dict = field(default_factory=dict)
    readable: bool = True

    def at(self, path: tuple) -> tuple[int | None, int | None]:
        for p in (path, path[:-1], path[:-2]):
            if p in self.keys:
                return self.keys[p]
            if p in self.values:
                return self.values[p]
        return None, None

    def finding(self, rule, severity, message, path=(), source="") -> Finding:
        line, col = self.at(tuple(path)) if path else (None, None)
        return Finding(rule, severity, message, tuple(path), line, col, source)


def _json_error_hint(text: str, err: json.JSONDecodeError) -> str:
    before = text[:err.pos].rstrip()
    ahead = text[err.pos:err.pos + 2]
    if before.endswith(",") and ahead[:1] in "]}":
        return " (a trailing comma; JSON allows none)"
    if ahead.startswith("//") or ahead.startswith("/*") or ahead.startswith("#"):
        return " (a comment; JSON allows none)"
    if ahead[:1] == "'":
        return " (JSON strings take double quotes)"
    return ""


def load_source(path: Path, plugin_root: Path | None = None, project_dir: Path | None = None) -> Source:
    """Read a hooks file. Syntax problems become findings; an unreadable file leaves readable=False."""
    src = Source(path=path)
    try:
        raw = path.read_bytes()
    except OSError as e:
        src.readable = False
        src.problems.append(Finding("file", "error", f"cannot read {path}: {e.strerror or e}"))
        return src
    if raw.startswith(b"\xef\xbb\xbf"):
        src.problems.append(Finding("json-bom", "warning", "the file starts with a UTF-8 byte order mark; a JSON parser "
                                    "may reject it", (), 1, 1))
        raw = raw[3:]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        src.problems.append(Finding("json-syntax", "error", f"not UTF-8 text (byte {e.start})"))
        return src
    try:
        src.data = json.loads(text)
    except json.JSONDecodeError as e:
        src.problems.append(Finding("json-syntax", "error", f"JSON syntax error: {e.msg}{_json_error_hint(text, e)}",
                                    (), e.lineno, e.colno,
                                    f"{GUIDE_DOC} (\"trailing commas and comments aren't allowed\")"))
        return src
    except RecursionError:
        src.problems.append(Finding("json-syntax", "error", "JSON nested too deeply to read"))
        return src
    try:
        pos = _Positions(text)
        pos.value(())
        src.values, src.keys = pos.values, pos.keys
        for dpath, line, col in pos.duplicates:
            src.problems.append(Finding("duplicate-key", "warning", f"key {dpath[-1]!r} appears twice in one object; "
                                        "a JSON parser keeps the last one", dpath, line, col))
    except (IndexError, AttributeError, ValueError, RecursionError):
        pass  # positions are a convenience; findings then carry no line number
    parts = path.resolve().parts
    if len(parts) >= 2 and parts[-2:] == ("hooks", "hooks.json"):
        src.kind = "plugin"
        src.plugin_root = plugin_root or path.resolve().parent.parent
    elif len(parts) >= 2 and parts[-2] == ".claude" and parts[-1] in ("settings.json", "settings.local.json"):
        src.kind = "settings"
        src.project_dir = path.resolve().parent.parent
    if plugin_root is not None:
        src.kind, src.plugin_root = "plugin", plugin_root
    if project_dir is not None:
        src.project_dir = project_dir
    return src


# ---------------------------------------------------------------- handlers

@dataclass
class Handler:
    event: str
    gi: int
    hi: int
    matcher: object
    has_matcher: bool
    spec: dict
    path: tuple

    @property
    def label(self) -> str:
        return f"{self.event}[{self.gi}].hooks[{self.hi}]"

    @property
    def type(self):
        return self.spec.get("type")

    def key(self) -> tuple:
        """Claude Code starts one process per distinct key: equal command, args and `if` ran once even across
        groups; timeout and statusMessage made no difference (observed, Claude Code 2.1.281)."""
        args = self.spec.get("args")
        return (self.event, self.spec.get("type"), _hashable(self.spec.get("command")), _hashable(args),
                self.spec.get("shell"), _hashable(self.spec.get("if")), _hashable(self.spec.get("url")),
                _hashable(self.spec.get("prompt")), _hashable(self.spec.get("server")), _hashable(self.spec.get("tool")))


def _hashable(v):
    return json.dumps(v, sort_keys=True) if isinstance(v, (list, dict)) else v


def handlers_of(data) -> list[Handler]:
    out = []
    hooks = data.get("hooks") if isinstance(data, dict) else None
    if not isinstance(hooks, dict):
        return out
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            continue
        for gi, group in enumerate(groups):
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                continue
            for hi, spec in enumerate(group["hooks"]):
                if isinstance(spec, dict):
                    out.append(Handler(event, gi, hi, group.get("matcher"), "matcher" in group, spec,
                                       ("hooks", event, gi, "hooks", hi)))
    return out


# ---------------------------------------------------------------- matchers (hooks docs, "Matcher patterns")

_EXACT = re.compile(r"[A-Za-z0-9_\- ,|]*")
_EXACT_NARROW = re.compile(r"[A-Za-z0-9_|]*")


def matcher_mode(matcher, event: str):
    """("all", None), ("exact", [names]), ("regex", pattern) or ("invalid", why)."""
    if matcher is None or matcher in ("", "*"):
        return "all", None
    if not isinstance(matcher, str):
        return "invalid", "the matcher is not a string"
    narrow = event in NARROW_MATCHER_EVENTS
    if (_EXACT_NARROW if narrow else _EXACT).fullmatch(matcher):
        parts = re.split(r"\|" if narrow else r"[|,]", matcher)
        return "exact", [p.strip() for p in parts]
    return "regex", matcher


def js_regex(pattern: str):
    """A matcher regex is JavaScript's, tested with RegExp.prototype.test. Python's re agrees for what matchers use
    (alternation, classes, anchors, quantifiers) once named groups are respelled; \\d and \\w are ASCII in JS."""
    return re.compile(re.sub(r"\(\?<([A-Za-z_]\w*)>", r"(?P<\1>", pattern), re.ASCII)


def matcher_matches(matcher, event: str, value) -> tuple[bool, str]:
    if event in NO_MATCHER_EVENTS:
        return True, "no matcher support on this event (a matcher is ignored)"
    mode, arg = matcher_mode(matcher, event)
    value = "" if value is None else str(value)
    if event == "FileChanged":
        value = value.replace("\\", "/").rsplit("/", 1)[-1]
    if mode == "all":
        return True, "matcher matches every occurrence"
    if mode == "invalid":
        return False, arg
    if mode == "exact":
        hit = value in arg
        return hit, (f"matcher {matcher!r} lists {value!r}" if hit else f"matcher {matcher!r} does not list {value!r} "
                     "(exact names, case-sensitive)")
    try:
        hit = js_regex(arg).search(value) is not None
    except re.error as e:
        return False, f"matcher {matcher!r} is not a regular expression this tool can read ({e})"
    return hit, f"regex matcher {matcher!r} {'matches' if hit else 'does not match'} {value!r}"


# ---------------------------------------------------------------- `if` rules

_RULE = re.compile(r"\s*([^\s()]+)\s*(?:\((.*)\))?\s*", re.S)


@dataclass
class Rule:
    text: str
    tool: str = ""
    spec: str | None = None
    error: str | None = None


def parse_rule(text) -> Rule:
    """Permission rule syntax: `Tool` or `Tool(specifier)`; parentheses inside the specifier are literal."""
    if not isinstance(text, str):
        return Rule(str(text), error="the `if` value is not a string")
    m = _RULE.fullmatch(text)
    if not m:
        return Rule(text, error="not a permission rule; expected Tool or Tool(specifier)")
    return Rule(text, m.group(1), m.group(2))


@dataclass
class Verdict:
    fires: bool
    why: str
    basis: str = "docs"  # docs | observed | assumed


@dataclass
class Context:
    cwd: str
    project_dir: str
    home: str


def rule_fires(rule_text, tool: str, tool_input: dict, ctx: Context) -> Verdict:
    rule = parse_rule(rule_text)
    if rule.error:
        return Verdict(False, rule.error)
    if rule.tool != tool:
        # "A single `if` rule matches only one tool's calls" (hooks docs); tool-name globs and mcp__server prefixes
        # did not match either (observed).
        return Verdict(False, f"the rule names {rule.tool}, the call is {tool}", "docs")
    spec = rule.spec
    if spec is None or spec.strip() == "*":
        return Verdict(True, f"{rule.text} matches every {tool} call", "docs")
    if spec.strip() == "":
        return Verdict(True, f"{rule.text} has an empty specifier; assumed to match every call", "assumed")
    if tool in COMMAND_RULE_TOOLS:
        return bash_rule(spec, str(tool_input.get("command") or ""))
    if tool == "PowerShell":
        return powershell_rule(spec, str(tool_input.get("command") or ""))
    if tool in PATH_RULE_FIELDS:
        value = tool_input.get(PATH_RULE_FIELDS[tool])
        if value is None and tool in ("Grep", "Glob"):
            value = ctx.cwd  # they search the working directory when `path` is absent
        if not isinstance(value, str) or not value:
            return Verdict(False, f"the call has no {PATH_RULE_FIELDS[tool]}", "assumed")
        return path_rule(spec, value, ctx)
    observed = tool in ("WebFetch", "Agent") or tool.startswith("mcp__")
    return Verdict(False, f"{rule.text}: a specifier other than * never matched a {tool} call in an `if` ("
                   + (f"observed, {OBSERVED}" if observed else f"assumed: observed only for WebFetch, Agent and MCP "
                      f"tools, {OBSERVED}") + ")", "observed" if observed else "assumed")


# ---------------------------------------------------------------- Bash commands

_ASSIGN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\[[^\]]*\])?\+?=")
_REDIR = re.compile(r"\d*(?:&>>|&>|>>|>&|>\||<>|<<<|<<-|<<|<&|>|<)")
_VAR = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[0-9]|[?$!#@*_-]")
_ONE_SUBST = re.compile(r"\$\((?:[^()]|\([^()]*\))*\)|`[^`]*`", re.S)
_ONE_VAR = re.compile(r"\$(?:[A-Za-z_][A-Za-z0-9_]*|[0-9]|[?$!#@*_-])")
_PREFIX_WORDS = {"!", "if", "then", "elif", "else", "do", "while", "until"}
# Commands that run code or another command given as an argument: with an argument known only at run time, every
# handler ran (observed, 2.1.281). npm, git, docker, make, ssh, sed, curl and the like did not trigger this.
_RUNS_CODE = {"sh", "bash", "zsh", "dash", "ksh", "fish", "pwsh", "powershell", "cmd", "python", "python3", "node",
              "deno", "bun", "ruby", "perl", "php", "lua", "awk", "eval", "exec", "source", ".", "env", "sudo",
              "timeout", "nohup", "nice", "time", "command", "builtin", "xargs", "watch", "find"}
_END_WORDS = {"fi", "done", "esac", "}"}
_HEADER_WORDS = {"for", "select"}
# Bash's analysis limit: "Commands longer than 10,000 characters always prompt because they exceed what the analysis
# parses" (permissions docs, 2026-09-24); a longer command ran every handler (observed).
MAX_ANALYSED = 10_000


class _Word:
    __slots__ = ("parts", "raw", "bare", "quoted", "subst")

    def __init__(self):
        self.parts, self.raw, self.bare, self.quoted, self.subst = [], "", 0, 0, 0

    @property
    def value(self) -> str:
        return "".join(self.parts)

    @property
    def dynamic(self) -> bool:
        return bool(self.bare or self.quoted or self.subst)


@dataclass
class ShellAnalysis:
    every: str | None = None      # why Claude Code runs every handler for this command
    specific: str | None = None   # why a pattern longer than a command name fires anyway
    commands: list = field(default_factory=list)  # candidate texts of each simple command
    top: int = 0
    compound: bool = False


class _BashParser:
    def __init__(self, s: str, a: ShellAnalysis):
        self.s, self.i, self.n, self.a = s, 0, len(s), a
        self.heredocs = []  # (delimiter, strip tabs) whose bodies start after the current line

    def every(self, why: str):
        if not self.a.every:
            self.a.every = why

    def blanks(self):
        while self.i < self.n:
            if self.s[self.i] in " \t\r":
                self.i += 1
            elif self.s.startswith("\\\n", self.i):
                self.i += 2
            else:
                return

    def skip_heredoc_bodies(self):
        for delim, tabs in self.heredocs:
            while self.i < self.n:
                j = self.s.find("\n", self.i)
                line = self.s[self.i:self.n if j < 0 else j]
                self.i = self.n if j < 0 else j + 1
                if (line.lstrip("\t") if tabs else line) == delim:
                    break
        self.heredocs = []

    def comment(self):
        j = self.s.find("\n", self.i)
        self.i = self.n if j < 0 else j

    def operator(self):
        for op in ("&&", "||", "|&", "|"):
            if self.s.startswith(op, self.i):
                self.i += len(op)
                return op
        if self.s[self.i] == "&" and not self.s.startswith("&>", self.i):
            self.i += 1
            return "&"
        return None

    def parse_list(self, stop: str | None = None, top: bool = True) -> tuple[int, bool]:
        count, pending = 0, None
        while True:
            self.blanks()
            if self.i >= self.n:
                break
            c = self.s[self.i]
            if stop and c == stop:
                self.i += 1
                if pending in ("&&", "||"):
                    self.every("a command ends with && or ||")
                return count, True
            if c == "#":
                self.comment()
                continue
            if c == "\n":
                self.i += 1
                self.skip_heredoc_bodies()
                continue
            if c == ";":
                if self.s.startswith((";;", ";&"), self.i):
                    self.every("a case statement")
                    self.i += 2
                    continue
                self.i += 1
                pending = None
                continue
            if c == ")":
                self.every("an unmatched )")
                self.i += 1
                continue
            op = self.operator()
            if op:
                pending = None if op == "&" else op
                continue
            before = self.i
            self.command(top)
            if self.i == before:
                self.i += 1
            count += 1
            pending = None
        if pending in ("&&", "||"):
            # "When && or || has nothing after it ... Claude Code treats the command as unparseable" (permissions
            # docs); a trailing | was tolerated (observed).
            self.every("the command ends with && or ||")
        if stop:
            self.every(f"an unclosed {'$(' if stop == ')' else stop}")
        return count, False

    def command(self, top: bool):
        s, i = self.s, self.i
        if s[i] == "(":
            if s.startswith("((", i):
                self.i = self._close(i + 2, "(", ")", 2)
                return
            self.i += 1
            if top:
                self.a.compound = True
            self.parse_list(")", top)
            words, targets = self.simple()
            for w in targets:
                self.note(w)
            return
        if s[i] == "{" and (i + 1 >= self.n or s[i + 1] in " \t\n"):
            self.every("a { ...; } group")
            self.i += 1
            return
        words, targets = self.simple()
        self.finish(words, targets, top)

    def simple(self) -> tuple[list, list]:
        words, targets, heredoc = [], [], False
        while True:
            self.blanks()
            if self.i >= self.n:
                break
            c = self.s[self.i]
            if c in "\n;|)" or (c == "&" and not self.s.startswith("&>", self.i)):
                break
            if c == "#":
                self.comment()
                break
            if c == "(":
                if len(words) == 1 and re.match(r"\(\s*\)", self.s[self.i:]):
                    self.every("a function definition")
                else:
                    self.every("a ( inside a command")
                self.i += 1
                continue
            if self.s.startswith(("<(", ">("), self.i):
                self.every("a process substitution")
                self.i += 1
                w = _Word()
                self.dollar_paren(w, self.i)
                words.append(w)
                continue
            m = _REDIR.match(self.s, self.i)
            if m:
                self.i = m.end()
                op = m.group(0).lstrip("0123456789")
                self.blanks()
                if op in ("<<", "<<-"):
                    delim = self.word() if self.i < self.n else _Word()
                    if not any(q in delim.raw for q in "'\"\\"):
                        self.every("a here-document with an unquoted delimiter")
                    self.heredocs.append((delim.value, op == "<<-"))
                    heredoc = True
                    continue
                if self.i < self.n and self.s[self.i] not in "\n;|&)":
                    targets.append(self.word())
                continue
            words.append(self.word())
        if heredoc and (targets or self.s.startswith("|", self.i)):
            self.every("a here-document together with another redirection or a pipe")
        if heredoc:
            targets.append(_Word())  # counts as a redirection for the checks in finish()
        return words, targets

    def word(self) -> _Word:
        w, start = _Word(), self.i
        while self.i < self.n:
            c = self.s[self.i]
            if c in " \t\r\n;&|()<>":
                break
            if c == "\\":
                nxt = self.s[self.i + 1:self.i + 2]
                if nxt == "\n":
                    self.i += 2
                    continue
                if nxt in (" ", "\t"):
                    self.every("a backslash-escaped space")
                w.parts.append(nxt)
                self.i += 2
                continue
            if c == "'":
                j = self.s.find("'", self.i + 1)
                if j < 0:  # an unbalanced quote swallows the rest of the line, as Claude Code 2.1.281 read it
                    w.parts.append(self.s[self.i + 1:])
                    self.i = self.n
                    break
                w.parts.append(self.s[self.i + 1:j])
                self.i = j + 1
                continue
            if c == '"':
                self.dquote(w)
                continue
            if c == "$":
                self.dollar(w, False)
                continue
            if c == "`":
                self.backtick(w)
                continue
            w.parts.append(c)
            self.i += 1
        w.raw = self.s[start:self.i]
        if w.bare and not _ONE_VAR.fullmatch(w.raw):
            self.every(f"a variable joined to other text in one word ({w.raw})")
        return w

    def dquote(self, w: _Word):
        start, subst_before = self.i, w.subst
        self.i += 1
        while self.i < self.n:
            c = self.s[self.i]
            if c == '"':
                self.i += 1
                if w.subst > subst_before and not _ONE_SUBST.fullmatch(self.s[start + 1:self.i - 1]):
                    w.subst = subst_before  # interpolated into a longer string
                return
            if c == "\\" and self.s[self.i + 1:self.i + 2] in ('$', '`', '"', '\\', '\n'):
                if self.s[self.i + 1] != "\n":
                    w.parts.append(self.s[self.i + 1])
                self.i += 2
                continue
            if c == "$":
                self.dollar(w, True)
                continue
            if c == "`":
                self.backtick(w)
                continue
            w.parts.append(c)
            self.i += 1

    def _close(self, j: int, opening: str, closing: str, depth: int = 1) -> int:
        quote = None
        while j < self.n and depth:
            c = self.s[j]
            if quote:
                if c == quote:
                    quote = None
                elif c == "\\" and quote == '"':
                    j += 1
            elif c in "'\"":
                quote = c
            elif c == "\\":
                j += 1
            elif c == opening:
                depth += 1
            elif c == closing:
                depth -= 1
            j += 1
        return min(j, self.n)

    def dollar_paren(self, w: _Word, open_at: int):
        start = open_at - 1
        self.i = open_at + 1
        count, closed = self.parse_list(")", top=False)
        if closed and count == 0:
            self.every("an empty $( )")
        w.parts.append(self.s[start:self.i])
        w.subst += 1

    def dollar(self, w: _Word, quoted: bool):
        s, i = self.s, self.i
        nxt = s[i + 1:i + 2]
        if s.startswith("$((", i):
            self.i = self._close(i + 3, "(", ")", 2)
            w.parts.append(s[i:self.i])
            if quoted:
                self.every("an arithmetic expansion inside double quotes")
            return
        if nxt == "(":
            self.dollar_paren(w, i + 1)
            return
        if nxt == "{":
            self.every("a ${...} expansion")
            self.i = self._close(i + 2, "{", "}")
            w.parts.append(s[i:self.i])
            return
        if nxt == "'" and not quoted:
            self.every("an ANSI-C $'...' string")
            j = i + 2
            while j < self.n and s[j] != "'":
                j += 2 if s[j] == "\\" else 1
            self.i = min(j + 1, self.n)
            w.parts.append(s[i:self.i])
            return
        if nxt == '"' and not quoted:
            self.i += 1
            self.dquote(w)
            return
        m = _VAR.match(s, i + 1)
        if not m:
            if not quoted:
                self.every("a $ that starts no expansion")
            w.parts.append("$")
            self.i += 1
            return
        name = m.group(0)
        w.parts.append("$" + name)
        self.i = m.end()
        if name == "HOME":
            return  # $HOME was treated as static (observed; every other variable tried was not)
        if quoted:
            w.quoted += 1
        else:
            w.bare += 1

    def backtick(self, w: _Word):
        j, buf = self.i + 1, []
        while j < self.n and self.s[j] != "`":
            if self.s[j] == "\\" and self.s[j + 1:j + 2] in ("`", "$", "\\"):
                buf.append(self.s[j + 1])
                j += 2
                continue
            buf.append(self.s[j])
            j += 1
        if j >= self.n:
            self.every("an unclosed backtick")
        inner = "".join(buf)
        if not inner.strip():
            self.every("an empty backtick substitution")
        _BashParser(inner, self.a).parse_list(top=False)
        w.parts.append(self.s[self.i:j + 1])
        w.subst += 1
        self.i = min(j + 1, self.n)

    def note(self, w: _Word):
        if w.quoted:
            self.every(f"a variable expanded inside double quotes ({w.raw})")
        elif (w.bare or w.subst) and not self.a.specific:
            self.a.specific = f"{w.raw} is only known when the command runs"

    def finish(self, words: list, targets: list, top: bool):
        k = 0
        while k < len(words) and _ASSIGN.match(words[k].raw):
            k += 1
        assigned, rest = k > 0, words[k:]
        while rest and rest[0].raw in _PREFIX_WORDS:
            if top:
                self.a.compound = True
            rest = rest[1:]
        if rest and rest[0].raw in _HEADER_WORDS:
            if top:
                self.a.compound = True
            for w in rest[1:] + targets:
                if w.dynamic:
                    self.note(w)
            return
        if rest and rest[0].raw == "case":
            self.every("a case statement")
            return
        if rest and rest[0].raw == "function":
            self.every("a function definition")
            return
        if len(rest) == 1 and rest[0].raw in _END_WORDS:
            return
        for w in targets:
            if w.bare:  # a redirect to $OUT ran every handler (observed)
                self.every(f"a redirection to {w.raw}")
        if not rest:
            for w in targets:
                if w.dynamic:
                    self.note(w)
            return
        if top:
            self.a.top += 1
        name = rest[0]
        if name.dynamic:
            # "Claude Code can't tell what the command name expands to, so it runs the hook" (hooks docs)
            self.every(f"the command name {name.raw} is only known when the command runs")
        dyn = [w for w in rest[1:] + targets if w.dynamic and not _ASSIGN.match(w.raw)]
        if dyn and assigned:
            self.every("a variable assignment in front of a command that expands variables")
        if dyn and targets:
            self.every("an expansion in a command with a redirection")
        if dyn and name.value in _RUNS_CODE:
            self.every(f"{name.value} runs code, and an argument is only known when the command runs")
        for w in dyn:
            self.note(w)
        values = [w.value for w in rest]
        if values[0] == "[":  # a [ ... ] test was matched as [[ ... ]] (observed)
            values[0] = "[["
            if values[-1] == "]":
                values[-1] = "]]"
        texts = [" ".join(" ".join(values).split())]
        if name.value == "xargs" and len(rest) > 1 and not rest[1].value.startswith("-"):
            # bare xargs is stripped, and the xargs form is checked too (observed)
            texts.append(" ".join(" ".join(w.value for w in rest[1:]).split()))
        self.a.commands.append(texts)


def analyze_bash(command: str) -> ShellAnalysis:
    a = ShellAnalysis()
    if len(command) > MAX_ANALYSED:
        a.every = f"the command is longer than {MAX_ANALYSED:,} characters"
        return a
    try:
        _BashParser(command, a).parse_list()
    except RecursionError:
        a.every = "the command nests too deeply to analyse"
    if not a.every and a.specific and (a.compound or a.top > 1):
        a.every = "the command combines several subcommands with an expansion (" + a.specific + ")"
    return a


def names_only(spec: str) -> bool:
    """`git *`, `git*` and `git:*` constrain only the command name. Anything else (an exact command, several
    words, a leading or inner wildcard, a glob character in the name) counts as more specific (observed)."""
    return re.fullmatch(r"[^\s*?\[\]]+(?: \*|\*|:\*)", spec.strip()) is not None


def command_pattern(spec: str, icase: bool = False):
    """permissions docs, "Wildcard patterns": * stands for any text, spaces included; a trailing ` *` that is the
    only wildcard also matches the bare command; `:*` at the end equals ` *`. Runs of whitespace in the rule count
    as one space (observed)."""
    p = " ".join(spec.split())
    if p.endswith(":*"):
        p = p[:-2].rstrip() + " *"
    if p.endswith(" *") and "*" not in p[:-2]:
        rx = re.escape(p[:-2]) + r"(?: .*)?"
    else:
        rx = ".*".join(re.escape(x) for x in p.split("*"))
    return re.compile(rx, re.S | (re.I if icase else 0))


def bash_rule(spec: str, command: str) -> Verdict:
    a = analyze_bash(command)
    if a.every:
        return Verdict(True, f"Claude Code runs every handler for this command: {a.every}",
                       "docs" if "command name" in a.every or "10,000" in a.every else "observed")
    if not names_only(spec) and a.specific:
        return Verdict(True, f"the pattern {spec!r} names more than a command, and {a.specific}; such patterns run "
                       "the hook anyway (hooks docs)", "docs")
    rx = command_pattern(spec)
    for texts in a.commands:
        for text in texts:
            if rx.fullmatch(text):
                return Verdict(True, f"subcommand {clean(text, 120)!r} matches {spec!r}", "docs")
    return Verdict(False, f"no subcommand matches {spec!r}", "docs")


# ---------------------------------------------------------------- PowerShell commands (docs only; not cross-checked)

def _ps_canonical(word: str) -> str:
    return PS_CANONICAL.get(word.lower(), word)


def analyze_powershell(command: str) -> ShellAnalysis:
    """Splits on ; | && || and newlines outside quotes, reads $( ), @( ), ( ) and { } bodies as commands, and marks
    $variables and subexpressions as only known at run time. From the permissions docs' PowerShell section."""
    a = ShellAnalysis()
    if len(command) > MAX_ANALYSED:
        a.every = f"the command is longer than {MAX_ANALYSED:,} characters"
        return a
    s, n = command, len(command)

    def parse(i: int, stop: str | None, top: bool) -> int:
        words, word, dyn, name_dyn = [], [], False, False

        def flush_word():
            nonlocal word
            if word:
                words.append("".join(word))
                word = []

        def flush_cmd():
            nonlocal words, dyn, name_dyn
            flush_word()
            ws = list(words)
            if ws and ws[0] in ("&", "."):
                ws = ws[1:]
            if ws:
                if top:
                    a.top += 1
                if name_dyn:
                    a.every = a.every or f"the command name {ws[0]} is only known when the command runs"
                if dyn and not a.specific:
                    a.specific = "a variable or subexpression is only known when the command runs"
                a.commands.append([" ".join([_ps_canonical(ws[0])] + ws[1:])])
            words, dyn, name_dyn = [], False, False

        while i < n:
            c = s[i]
            if stop and c == stop:
                flush_cmd()
                return i + 1
            if c in " \t\r":
                flush_word()
                i += 1
            elif c in "\n;":
                flush_cmd()
                i += 1
            elif s.startswith(("&&", "||"), i) or c == "|":
                flush_cmd()
                if top:
                    a.compound = True
                i += 2 if s[i] in "&" or s.startswith("||", i) else 1
            elif s.startswith("<#", i):
                j = s.find("#>", i + 2)
                i = n if j < 0 else j + 2
            elif c == "#" and not word:
                j = s.find("\n", i)
                i = n if j < 0 else j
            elif c == "'":
                j = i + 1
                while j < n and not (s[j] == "'" and s[j + 1:j + 2] != "'"):
                    j += 2 if s[j] == "'" else 1
                word.append(s[i + 1:j].replace("''", "'"))
                i = j + 1
                if j >= n:
                    a.every = a.every or "an unbalanced quote"
            elif c == '"':
                j = i + 1
                while j < n and s[j] != '"':
                    if s[j] == "`":
                        j += 1
                    elif s[j] == "$":
                        if s.startswith("$(", j):
                            j = parse(j + 2, ")", False) - 1
                        dyn = dyn or not words
                        dyn = True
                        name_dyn = name_dyn or not words and not word
                    j += 1
                word.append(s[i + 1:j])
                i = j + 1
                if j >= n:
                    a.every = a.every or "an unbalanced quote"
            elif c == "`":
                word.append(s[i + 1:i + 2])
                i += 2
            elif c == "$" and s.startswith("$(", i):
                if not words and not word:
                    name_dyn = True
                dyn = True
                i = parse(i + 2, ")", False)
                word.append("$( )")
            elif c == "@" and s.startswith("@(", i):
                i = parse(i + 2, ")", False)
                word.append("@( )")
            elif c in "({" and not word:
                if not words:
                    name_dyn = name_dyn or c == "("
                i = parse(i + 1, ")" if c == "(" else "}", top and c == "{")
                word.append("( )" if c == "(" else "{ }")
            elif c == "$":
                m = re.compile(r"\$(?:\{[^}]*\}|[A-Za-z_][\w:]*|[?$^_])").match(s, i)
                if not words and not word:
                    name_dyn = True
                dyn = True
                word.append(m.group(0) if m else "$")
                i = m.end() if m else i + 1
            elif c in "<>" or (c.isdigit() and s[i + 1:i + 2] == ">") or (c == "*" and s[i + 1:i + 2] == ">"):
                m = re.compile(r"[0-9*]?>>?(?:&[0-9])?|<").match(s, i)
                flush_word()
                i = m.end() if m else i + 1
                while i < n and s[i] in " \t":
                    i += 1
                if not (m and "&" in m.group(0)):
                    while i < n and s[i] not in " \t\n;|":
                        i += 1
            else:
                word.append(c)
                i += 1
        if stop:
            a.every = a.every or f"an unclosed {stop}"
        flush_cmd()
        return n

    parse(0, None, True)
    if not a.every and a.specific and (a.compound or a.top > 1):
        a.every = "the command combines several commands with a variable or subexpression"
    return a


def powershell_rule(spec: str, command: str) -> Verdict:
    a = analyze_powershell(command)
    if a.every:
        return Verdict(True, f"assumed to run every handler for this command: {a.every}", "assumed")
    if not names_only(spec) and a.specific:
        return Verdict(True, f"the pattern {spec!r} names more than a command and {a.specific}", "assumed")
    words = " ".join(spec.split()).split(" ", 1)
    words[0] = _ps_canonical(words[0])
    rx = command_pattern(" ".join(words), icase=True)
    for texts in a.commands:
        for text in texts:
            if rx.fullmatch(text):
                return Verdict(True, f"command {clean(text, 120)!r} matches {spec!r} (case-insensitive, aliases "
                               "canonicalized)", "docs")
    return Verdict(False, f"no command matches {spec!r}", "docs")


# ---------------------------------------------------------------- file path rules

def posix_path(p: str) -> str:
    """permissions docs: on Windows, paths are normalized to POSIX form before matching; C:\\Users\\alice becomes
    /c/Users/alice."""
    m = re.match(r"^([A-Za-z]):[\\/]", p)
    if m:
        p = "/" + m.group(1).lower() + "/" + p[3:]
    if m or p.startswith("\\\\"):
        p = p.replace("\\", "/")
    return posixpath.normpath(p) if p else p


def gitignore_regex(pat: str) -> str:
    """gitignore pattern syntax: * and ? stay within one path segment, ** crosses directories, [..] is a class."""
    if pat == "**":
        return ".*"
    out, i, n = [], 0, len(pat)
    while i < n:
        if pat.startswith("**/", i) and (i == 0 or pat[i - 1] == "/"):
            out.append("(?:.*/)?")
            i += 3
            continue
        if pat.startswith("/**", i) and i + 3 == n:
            out.append("/.*")
            i += 3
            continue
        c = pat[i]
        if c == "*":
            while i < n and pat[i] == "*":
                i += 1
            out.append("[^/]*")
            continue
        if c == "?":
            out.append("[^/]")
        elif c == "[":
            j = pat.find("]", i + 2)
            if j > 0:
                body = pat[i + 1:j]
                if body.startswith("!"):
                    body = "^" + body[1:]
                out.append("[" + body.replace("\\", "\\\\") + "]")
                i = j + 1
                continue
            out.append(re.escape(c))
        elif c == "\\" and i + 1 < n:
            out.append(re.escape(pat[i + 1]))
            i += 2
            continue
        else:
            out.append(re.escape(c))
        i += 1
    return "".join(out)


def _relative(path: str, base: str) -> str | None:
    base = base.rstrip("/") or "/"
    if base == "/":
        return path.lstrip("/")
    if path.lower() == base.lower():
        return ""
    if path.lower().startswith(base.lower() + "/"):
        return path[len(base) + 1:]
    return None


def path_rule(spec: str, value: str, ctx: Context) -> Verdict:
    s = spec.strip()
    if s in ("**",):
        return Verdict(True, f"{s!r} matched every path, inside the working directory or not (observed)", "observed")
    path = posix_path(value)
    if not path.startswith("/"):
        path = posixpath.normpath(posixpath.join(posix_path(ctx.cwd), path))
    if s.startswith("//"):
        base, pat, anchored, how = "/", s[2:].lstrip("/"), True, "the filesystem root"
    elif s.startswith("~/"):
        base, pat, anchored, how = posix_path(ctx.home), s[2:], True, "the home directory"
    elif s.startswith("/"):
        # the permissions docs anchor /path at the settings source; in an `if` it was the project directory for
        # a --settings file and for a plugin alike (observed)
        base, pat, anchored, how = posix_path(ctx.project_dir), s[1:], True, "the project directory"
    else:
        pat = s[2:] if s.startswith("./") else s  # ./x behaved like x, including the any-depth rule (observed)
        base, how = posix_path(ctx.cwd), "the working directory"
        anchored = "/" in pat.rstrip("/")
    if s == "*":
        return Verdict(True, "'*' matched every path, inside the working directory or not (observed)", "observed")
    rel = _relative(path, base)
    if rel is None:
        return Verdict(False, f"{value} is outside {how} ({base}) that {spec!r} is anchored at", "docs")
    dir_only = pat.endswith("/")
    pat = pat.rstrip("/")
    if not pat:
        return Verdict(True, f"{spec!r} covers everything under {how}", "docs")
    # Case-insensitive: SRC/APP.TS matched Edit(src/**) and Edit(*.ts) on a case-sensitive filesystem (observed).
    rx = re.compile(gitignore_regex(pat), re.I | re.S)
    segs = [x for x in rel.split("/") if x]
    if anchored:
        candidates = ["/".join(segs[:k]) for k in range(1, len(segs) + (0 if dir_only else 1))]
    else:
        candidates = segs[:-1] if dir_only else segs
    for cand in candidates:
        if rx.fullmatch(cand):
            what = "the path" if cand == "/".join(segs) or (not anchored and cand == segs[-1]) else f"directory {cand!r}"
            return Verdict(True, f"{what} matches {spec!r} (gitignore syntax, relative to {how})", "docs")
    return Verdict(False, f"{rel or path} does not match {spec!r} (gitignore syntax, relative to {how})", "docs")


# ---------------------------------------------------------------- choosing handlers for a call

@dataclass
class Choice:
    handler: Handler
    runs: bool
    why: str
    basis: str = "docs"
    duplicate_of: str | None = None


def choose(src: Source, event: str, payload: dict, ctx: Context) -> list[Choice]:
    out, seen = [], {}
    field_name = MATCHER_FIELD.get(event)
    value = payload.get(field_name) if field_name else None
    for h in handlers_of(src.data):
        if h.event != event:
            continue
        ok, why = matcher_matches(h.matcher, event, value)
        if not ok:
            out.append(Choice(h, False, why))
            continue
        basis = "docs"
        if "if" in h.spec:
            if event not in TOOL_EVENTS:
                out.append(Choice(h, False, "an `if` on an event without tool calls: the handler never runs (hooks "
                                  "docs)"))
                continue
            v = rule_fires(h.spec.get("if"), str(payload.get("tool_name") or ""),
                           payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}, ctx)
            if not v.fires:
                out.append(Choice(h, False, f"if {h.spec.get('if')!r}: {v.why}", v.basis))
                continue
            why, basis = f"{why}; if {h.spec.get('if')!r}: {v.why}", v.basis
        k = h.key()
        if k in seen:
            out.append(Choice(h, False, f"same command and `if` as {seen[k]}: Claude Code runs it once (observed)",
                              "observed", seen[k]))
            continue
        seen[k] = h.label
        out.append(Choice(h, True, why, basis))
    return out


# ---------------------------------------------------------------- running a handler

@dataclass
class Run:
    label: str
    argv: list = field(default_factory=list)
    exit_code: int | None = None
    timed_out: bool = False
    duration: float = 0.0
    stdout: str = ""
    stderr: str = ""
    stdout_utf8: bool = True
    truncated: bool = False
    error: str | None = None
    timeout: float = 0.0


OUTPUT_CAP = 1_000_000  # bytes kept per stream; the rest is read and dropped so the hook never blocks on a pipe


def _drain(stream, sink: list, cap: int, flags: dict):
    kept = 0
    try:
        while True:
            chunk = stream.read(65536)
            if not chunk:
                break
            if kept < cap:
                sink.append(chunk[:cap - kept])
                kept += min(len(chunk), cap - kept)
                if len(chunk) > cap - kept + min(len(chunk), cap - kept) and kept >= cap:
                    flags["truncated"] = True
            else:
                flags["truncated"] = True
    except (OSError, ValueError):
        pass


def _kill_tree(proc):
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        proc.kill()
    except OSError:
        pass


def execute(argv: list, stdin_bytes: bytes, cwd: str, env: dict, timeout: float, label: str = "") -> Run:
    """Start the handler in its own session (hooks run "in their own session without a controlling terminal" on
    macOS and Linux), feed the payload, and kill the whole process group at the timeout."""
    run = Run(label=label, argv=list(argv), timeout=timeout)
    kwargs = {"start_new_session": True} if os.name == "posix" else \
        {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
    t0 = time.monotonic()
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd,
                                env=env, **kwargs)
    except OSError as e:
        run.error = f"could not start {argv[0]!r}: {e.strerror or e}"
        run.duration = time.monotonic() - t0
        return run
    out, err, flags = [], [], {}
    readers = [threading.Thread(target=_drain, args=(proc.stdout, out, OUTPUT_CAP, flags), daemon=True),
               threading.Thread(target=_drain, args=(proc.stderr, err, OUTPUT_CAP, flags), daemon=True)]
    for t in readers:
        t.start()

    def feed():
        try:
            proc.stdin.write(stdin_bytes)
            proc.stdin.close()
        except (OSError, ValueError):
            pass  # a hook that exits without reading its input is fine

    writer = threading.Thread(target=feed, daemon=True)
    writer.start()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        run.timed_out = True
        _kill_tree(proc)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
    else:
        if os.name == "posix":
            try:  # children the hook left behind would keep the pipes open
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
    for t in readers + [writer]:
        t.join(timeout=5)
    run.duration = time.monotonic() - t0
    run.exit_code = proc.returncode
    raw_out, raw_err = b"".join(out), b"".join(err)
    run.truncated = bool(flags.get("truncated"))
    try:
        run.stdout = raw_out.decode("utf-8")
    except UnicodeDecodeError:
        run.stdout, run.stdout_utf8 = raw_out.decode("utf-8", "replace"), False
    run.stderr = raw_err.decode("utf-8", "replace")
    return run


def _git_bash() -> str | None:
    """Claude Code runs shell-form hooks through Git Bash on Windows; WSL's bash.exe in System32 is not it."""
    for cand in (os.environ.get("CLAUDE_CODE_GIT_BASH_PATH"), r"C:\Program Files\Git\bin\bash.exe",
                 r"C:\Program Files (x86)\Git\bin\bash.exe", shutil.which("bash")):
        if cand and os.path.isfile(cand) and "system32" not in cand.lower():
            return cand
    return None


def substitute(text: str, values: dict, powershell: bool = False) -> str:
    for name in PLACEHOLDERS:
        token = "${" + name + "}"
        if token in text and name in values:
            # As of v2.1.198 PowerShell shell-form commands get ${env:NAME} (hooks docs, Windows PowerShell tool).
            text = text.replace(token, "${env:%s}" % name if powershell else values[name])
    return text


_USER_CONFIG = re.compile(r"\$\{user_config\.([A-Za-z0-9_.-]+)\}")


HARNESS_GAP = "cannot emulate here: "


def spawn_plan(h: Handler, values: dict, user_config: dict, plugin: bool) -> tuple[list | None, str | None]:
    """The argv Claude Code would start for a command handler (hooks docs, "Exec form and shell form"). A reason
    starting with HARNESS_GAP is a limit of this run; any other reason is a failure Claude Code would meet too."""
    spec = h.spec
    command = spec.get("command")
    if not isinstance(command, str) or not command.strip():
        return None, "the handler has no command"
    args = spec.get("args")
    if args is not None:
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            return None, "args is not a list of strings"

        def sub(t):
            t = substitute(t, values)
            if plugin:
                missing = [k for k in _USER_CONFIG.findall(t) if k not in user_config]
                if missing:
                    raise KeyError(missing[0])
                t = _USER_CONFIG.sub(lambda m: str(user_config[m.group(1)]), t)
            return t

        try:
            exe, rest = sub(command), [sub(a) for a in args]
        except KeyError as e:
            return None, (f"{HARNESS_GAP}${{user_config.{e.args[0]}}} has no value (give it under \"user_config\" in the "
                          "cases file)")
        found = exe if os.path.sep in exe or (os.altsep and os.altsep in exe) else shutil.which(exe)
        if not found:
            return None, f"exec form: {exe!r} is not an executable on PATH, so the spawn fails"
        return [found] + rest, None
    if plugin and _USER_CONFIG.search(command):
        return None, ("a shell-form plugin hook that references ${user_config.*} fails with an error instead of "
                      "running (hooks docs)")
    shell = spec.get("shell")
    if shell == "powershell" or (os.name == "nt" and shell != "bash" and not _git_bash()):
        ps = shutil.which("pwsh") or shutil.which("powershell")
        if not ps:
            return None, f"{HARNESS_GAP}a PowerShell hook, and neither pwsh nor powershell is on PATH"
        return [ps, "-NoProfile", "-NonInteractive", "-Command", substitute(command, values, True)], None
    if os.name == "nt":
        return [_git_bash(), "-c", substitute(command, values)], None
    return [shutil.which("sh") or "/bin/sh", "-c", substitute(command, values)], None


# ---------------------------------------------------------------- what the handler printed

@dataclass
class Reading:
    kind: str = "empty"  # empty | json | plain | parse-failure
    obj: dict | None = None
    problems: list = field(default_factory=list)  # (severity, message)
    outcome: str = "success"
    decision: str | None = None
    reasons: list = field(default_factory=list)
    contexts: list = field(default_factory=list)
    stops: bool = False


def classify_stdout(text: str) -> tuple[str, object]:
    """hooks docs, "Exit code 0": output starting with { and ending with } is parsed as JSON; several lines that
    each parse on their own are plain text unless one of them sets an output field, which makes a parse failure."""
    s = text.strip()
    if not s:
        return "empty", None
    if not (s.startswith("{") and s.endswith("}")):
        return "plain", None
    try:
        obj = json.loads(s)
        return ("json", obj) if isinstance(obj, dict) else ("parse-failure", None)
    except ValueError:
        pass
    lines = [ln for ln in s.splitlines() if ln.strip()]
    if len(lines) >= 2:
        parsed = []
        for ln in lines:
            try:
                parsed.append(json.loads(ln))
            except ValueError:
                return "parse-failure", None
        known = set(UNIVERSAL_FIELDS) | {"decision", "reason", "hookSpecificOutput"}
        if any(isinstance(p, dict) and set(p) & known for p in parsed):
            return "parse-failure", None
        return "plain", None
    return "parse-failure", None


def _type_ok(value, want) -> bool:
    if want is object:
        return True
    if isinstance(want, tuple):
        return value in want
    if want is bool:
        return isinstance(value, bool)
    return isinstance(value, want) and not isinstance(value, bool)


def _type_name(want) -> str:
    if isinstance(want, tuple):
        return "one of " + ", ".join(repr(v) for v in want)
    return {str: "a string", bool: "true or false", dict: "an object", list: "an array"}.get(want, "any value")


def validate_output(event: str, obj: dict) -> list:
    """The documented JSON output shape for the event. Returns (severity, message) pairs."""
    probs = []
    known_top = set(UNIVERSAL_FIELDS) | {"hookSpecificOutput"}
    if event in TOP_DECISION_EVENTS or event == "PreToolUse":
        known_top |= {"decision", "reason"}
    if event == "UserPromptSubmit":
        known_top.add("suppressOriginalPrompt")
    for k, v in obj.items():
        if k in UNIVERSAL_FIELDS:
            if not _type_ok(v, UNIVERSAL_FIELDS[k]):
                probs.append(("error", f"{k} must be {_type_name(UNIVERSAL_FIELDS[k])}"))
        elif k not in known_top:
            if k in NESTED_ONLY:
                probs.append(("error", f"{k} is at the top level; it belongs inside hookSpecificOutput, and Claude "
                              "Code ignores it where it is (hooks guide, \"Hook JSON has no effect\")"))
            else:
                probs.append(("warning", f"unrecognized key {k!r}; Claude Code ignores it"))
    if "decision" in obj:
        d = obj["decision"]
        if event == "PreToolUse":
            if d in ("approve", "block"):
                probs.append(("warning", f"top-level decision {d!r} is deprecated for PreToolUse; use "
                              "hookSpecificOutput.permissionDecision (it maps to "
                              f"{'allow' if d == 'approve' else 'deny'})"))
            else:
                probs.append(("error", f"top-level decision {d!r} is not a PreToolUse value"))
        elif d != "block":
            probs.append(("error", f"decision must be \"block\" (the only value) on {event}, not {d!r}"))
    if "reason" in obj and not isinstance(obj["reason"], str):
        probs.append(("error", "reason must be a string"))
    if "hookSpecificOutput" in obj:
        hso = obj["hookSpecificOutput"]
        if not isinstance(hso, dict):
            probs.append(("error", "hookSpecificOutput must be an object"))
        else:
            name = hso.get("hookEventName")
            if name is None:
                probs.append(("error", "hookSpecificOutput has no hookEventName (it must name the event)"))
            elif name != event:
                probs.append(("error", f"hookSpecificOutput.hookEventName is {name!r}, the event is {event!r}"))
            allowed = HSO_FIELDS.get(event, {})
            for k, v in hso.items():
                if k == "hookEventName":
                    continue
                if k not in allowed:
                    probs.append(("warning", f"hookSpecificOutput.{k} is not a documented field for {event}; Claude "
                                  "Code ignores it"))
                elif not _type_ok(v, allowed[k]):
                    probs.append(("error", f"hookSpecificOutput.{k} must be {_type_name(allowed[k])}, not "
                                  f"{clean(json.dumps(v), 60)}"))
            if event == "PermissionRequest" and isinstance(hso.get("decision"), dict):
                dec = hso["decision"]
                if dec.get("behavior") not in ("allow", "deny"):
                    probs.append(("error", "hookSpecificOutput.decision.behavior must be \"allow\" or \"deny\""))
                for k, want in (("updatedInput", dict), ("updatedPermissions", list), ("message", str),
                                ("interrupt", bool)):
                    if k in dec and not _type_ok(dec[k], want):
                        probs.append(("error", f"hookSpecificOutput.decision.{k} must be {_type_name(want)}"))
            ctx = hso.get("additionalContext")
            if isinstance(ctx, str) and len(ctx) > CONTEXT_CAP:
                probs.append(("warning", f"additionalContext has {len(ctx):,} characters; above {CONTEXT_CAP:,} Claude "
                              "Code saves it to a file and passes a path and a 2,000-character preview (hooks docs)"))
    if isinstance(obj.get("systemMessage"), str) and len(obj["systemMessage"]) > CONTEXT_CAP:
        probs.append(("warning", f"systemMessage has more than {CONTEXT_CAP:,} characters (hooks docs cap)"))
    return probs


def read_run(event: str, run: Run, is_async: bool = False) -> Reading:
    """What Claude Code makes of one handler's exit code and output (hooks docs, "Exit code output")."""
    r = Reading()
    if run.error:
        r.outcome = "not started: " + run.error
        r.problems.append(("error", run.error))
        return r
    if run.timed_out:
        r.outcome = f"timed out after {run.timeout:g} s: Claude Code discards the output"
        r.problems.append(("error", f"timed out after {run.timeout:g} s"))
        return r
    if not run.stdout_utf8:
        r.problems.append(("warning", "stdout is not valid UTF-8"))
    if run.truncated:
        r.problems.append(("warning", f"more than {OUTPUT_CAP:,} bytes of output; only the start was kept"))
    code = run.exit_code
    r.kind, obj = classify_stdout(run.stdout)
    valid = False
    if r.kind == "json":
        r.obj = obj
        shape = validate_output(event, obj)
        r.problems.extend(shape)
        valid = not any(sev == "error" for sev, _ in shape)
    elif r.kind == "parse-failure":
        r.problems.append(("error", "stdout starts with { and ends with } but is not one JSON object: Claude Code "
                           "reports a JSON parse error and ignores it"))
    elif r.kind == "plain" and event not in PLAIN_CONTEXT_EVENTS and event != "WorktreeCreate":
        r.problems.append(("warning", "stdout is plain text, not JSON: on this event Claude Code writes it to the "
                           "debug log only (a shell profile that echoes can cause this)"))
    if event in DISCARDED_OUTPUT_EVENTS and r.kind == "json":
        r.problems.append(("note", f"Claude Code discards JSON output on {event} (hooks docs)"))
    if code == 2 and event in BLOCKING_EVENTS:
        r.outcome = "blocking error (exit 2)"
    elif code == 2 and event in FEEDBACK_EVENTS:
        r.outcome = "exit 2: stderr is shown, nothing is blocked"
    elif code not in (0, 2) and not valid:
        r.outcome = f"non-blocking error (exit {code}): Claude Code shows a hook error notice and proceeds"
    elif r.kind in ("json",) and not valid:
        r.outcome = "non-blocking error: the JSON fails validation and has no effect"
    if is_async:
        r.problems.append(("note", "async handler: its decision fields have no effect (hooks docs)"))
    if valid and not is_async and event not in DISCARDED_OUTPUT_EVENTS:
        hso = obj.get("hookSpecificOutput") if isinstance(obj.get("hookSpecificOutput"), dict) else {}
        if obj.get("continue") is False:
            r.stops = True
            if isinstance(obj.get("stopReason"), str):
                r.reasons.append(obj["stopReason"])
        if event in ("PreToolUse", "PreModelSwitch"):
            if hso.get("permissionDecision") in PRECEDENCE:
                r.decision = hso["permissionDecision"]
            elif event == "PreToolUse" and obj.get("decision") in ("approve", "block"):
                r.decision = "allow" if obj["decision"] == "approve" else "deny"
            if isinstance(hso.get("permissionDecisionReason"), str):
                r.reasons.append(hso["permissionDecisionReason"])
        if event == "PermissionRequest" and isinstance(hso.get("decision"), dict):
            r.decision = hso["decision"].get("behavior")
            if isinstance(hso["decision"].get("message"), str):
                r.reasons.append(hso["decision"]["message"])
        if event in TOP_DECISION_EVENTS and obj.get("decision") == "block":
            r.decision = "block"
        if isinstance(obj.get("reason"), str):
            r.reasons.append(obj["reason"])
        if isinstance(hso.get("additionalContext"), str):
            r.contexts.append(hso["additionalContext"])
    if code == 0 and r.kind == "plain" and event in PLAIN_CONTEXT_EVENTS:
        r.contexts.append(run.stdout.strip())
    if code == 2 and not is_async:
        if event == "PreToolUse":
            r.decision = "deny"  # "A hook that blocks by exiting 2 routes the same way as deny"
        elif event in BLOCKING_EVENTS:
            r.decision = "block"
        if not r.reasons and run.stderr.strip():
            r.reasons.append(run.stderr.strip())
        elif event in FEEDBACK_EVENTS and run.stderr.strip():
            r.reasons.append(run.stderr.strip())
    return r


def combine(event: str, readings: list) -> str:
    decisions = [r.decision for r in readings if r.decision]
    if not decisions:
        return "none"
    if event in ("PreToolUse", "PreModelSwitch"):
        return max(decisions, key=lambda d: PRECEDENCE.get(d, 0))
    if "deny" in decisions:
        return "deny"
    if "block" in decisions:
        return "block"
    return decisions[0]


# ---------------------------------------------------------------- cases

EXPECT_KEYS = {"decision", "reason_contains", "context_contains", "max_duration", "max_handlers", "min_handlers",
               "handlers"}
DECISIONS = {"none", "allow", "ask", "deny", "defer", "block"}
CASE_KEYS = {"name", "event", "tool_name", "tool_input", "tool_response", "error", "cwd", "env", "payload", "expect"}


class CaseFileError(Exception):
    pass


@dataclass
class Suite:
    path: Path
    cases: list
    project_dir: Path | None = None
    plugin_root: Path | None = None
    env: dict = field(default_factory=dict)
    user_config: dict = field(default_factory=dict)


def _strings(value, what: str) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
        raise CaseFileError(f"{what} must be an object of strings")
    return dict(value)


def load_suite(path: Path) -> Suite:
    try:
        data = json.loads(path.read_bytes().decode("utf-8-sig"))
    except OSError as e:
        raise CaseFileError(f"cannot read {path}: {e.strerror or e}") from None
    except UnicodeDecodeError:
        raise CaseFileError(f"{path} is not UTF-8 text") from None
    except json.JSONDecodeError as e:
        raise CaseFileError(f"{path}:{e.lineno}:{e.colno}: JSON syntax error: {e.msg}") from None
    top = {}
    if isinstance(data, list):
        cases = data
    elif isinstance(data, dict):
        top, cases = data, data.get("cases")
        unknown = set(data) - {"cases", "project_dir", "plugin_root", "env", "user_config", "$schema", "description"}
        if unknown:
            raise CaseFileError(f"unknown top-level key(s) in the cases file: {', '.join(sorted(unknown))}")
    else:
        cases = None
    if not isinstance(cases, list) or not cases:
        raise CaseFileError("the cases file needs a non-empty list of cases (a JSON array, or {\"cases\": [...]})")
    base = path.resolve().parent
    suite = Suite(path=path, cases=[], env=_strings(top.get("env"), "env"))
    for key in ("project_dir", "plugin_root"):
        if top.get(key) is not None:
            if not isinstance(top[key], str):
                raise CaseFileError(f"{key} must be a string")
            setattr(suite, key, (base / top[key]).resolve())
    uc = top.get("user_config") or {}
    if not isinstance(uc, dict):
        raise CaseFileError("user_config must be an object")
    suite.user_config = uc
    names = set()
    for n, case in enumerate(cases):
        where = f"case {n + 1}"
        if not isinstance(case, dict):
            raise CaseFileError(f"{where} is not an object")
        unknown = set(case) - CASE_KEYS
        if unknown:
            raise CaseFileError(f"{where}: unknown key(s) {', '.join(sorted(unknown))}")
        name = case.get("name") or f"case {n + 1}"
        if not isinstance(name, str):
            raise CaseFileError(f"{where}: name must be a string")
        if name in names:
            raise CaseFileError(f"{where}: the name {name!r} is used twice")
        names.add(name)
        event = case.get("event", "PreToolUse")
        if event not in EVENTS:
            raise CaseFileError(f"{name}: unknown event {event!r}")
        if event in TOOL_EVENTS and not isinstance(case.get("tool_name"), str):
            raise CaseFileError(f"{name}: a {event} case needs tool_name")
        tool = case.get("tool_name")
        if isinstance(tool, str) and tool not in KNOWN_TOOLS | LEGACY_TOOLS and not tool.startswith("mcp__"):
            near = [t for t in KNOWN_TOOLS if t.lower() == tool.lower()]
            raise CaseFileError(f"{name}: unknown tool_name {tool!r}" + (f" (tool names are case-sensitive: {near[0]})"
                                if near else " (not in the tools reference; MCP tools are named mcp__server__tool)"))
        fld = MATCHER_FIELD.get(event)
        if fld and event not in TOOL_EVENTS and not isinstance((case.get("payload") or {}).get(fld), str):
            raise CaseFileError(f"{name}: a {event} case needs payload.{fld}, the value its matchers are compared with")
        for key in ("tool_input", "payload", "tool_response"):
            if key in case and not isinstance(case[key], dict) and not (key == "tool_response"):
                raise CaseFileError(f"{name}: {key} must be an object")
        if case.get("cwd") is not None and not isinstance(case["cwd"], str):
            raise CaseFileError(f"{name}: cwd must be a string")
        _strings(case.get("env"), f"{name}: env")
        expect = case.get("expect") or {}
        if not isinstance(expect, dict):
            raise CaseFileError(f"{name}: expect must be an object")
        unknown = set(expect) - EXPECT_KEYS
        if unknown:
            raise CaseFileError(f"{name}: unknown expectation(s) {', '.join(sorted(unknown))} (known: "
                                f"{', '.join(sorted(EXPECT_KEYS))})")
        if "decision" in expect and expect["decision"] not in DECISIONS:
            raise CaseFileError(f"{name}: decision must be one of {', '.join(sorted(DECISIONS))}")
        for key in ("max_duration",):
            if key in expect and (not isinstance(expect[key], (int, float)) or isinstance(expect[key], bool)
                                  or expect[key] <= 0):
                raise CaseFileError(f"{name}: {key} must be a positive number of seconds")
        for key in ("max_handlers", "min_handlers", "handlers"):
            if key in expect and (not isinstance(expect[key], int) or isinstance(expect[key], bool) or expect[key] < 0):
                raise CaseFileError(f"{name}: {key} must be a whole number")
        for key in ("reason_contains", "context_contains"):
            v = expect.get(key)
            if v is not None and not (isinstance(v, str) or (isinstance(v, list) and all(isinstance(x, str) for x in v))):
                raise CaseFileError(f"{name}: {key} must be a string or a list of strings")
        suite.cases.append(dict(case, name=name, event=event, expect=expect))
    return suite


@dataclass
class Options:
    plugin_root: Path | None = None
    project_dir: Path | None = None
    dry_run: bool = False
    scratch_home: bool = False
    strict: bool = False
    only: str | None = None


def _home(env: dict) -> str:
    return env.get("HOME") or env.get("USERPROFILE") or os.path.expanduser("~")


def build_payload(case: dict, cwd: str, home: str, session: str, transcript: str) -> dict:
    """The stdin JSON: the documented common fields, the event's own fields, then whatever the case adds."""
    event = case["event"]
    p = {"session_id": session, "transcript_path": transcript, "cwd": cwd, "hook_event_name": event}
    if event in PERMISSION_MODE_EVENTS:
        p["permission_mode"] = "default"
    if event in TOOL_EVENTS:
        tool = case["tool_name"]
        tool_input = dict(case.get("tool_input") or {})
        fld = ABSOLUTE_PATH_FIELDS.get(tool)
        if fld and isinstance(tool_input.get(fld), str) and tool_input[fld]:
            # "Claude Code expands ~ and relative paths before hooks run" (hooks docs, PreToolUse input)
            v = tool_input[fld]
            if v == "~" or v.startswith("~/"):
                v = home + v[1:]
            windows = re.match(r"^[A-Za-z]:[\\/]", v) or v.startswith("\\\\")
            if not windows and not os.path.isabs(v):
                v = os.path.normpath(os.path.join(cwd, v))
            tool_input[fld] = v
        p["tool_name"] = tool
        p["tool_input"] = tool_input
        if event != "PermissionRequest":
            p["tool_use_id"] = "toolu_hh_" + uuid.uuid4().hex[:20]
        if event == "PostToolUse":
            p["tool_response"] = case.get("tool_response", {})
        if event == "PostToolUseFailure":
            p["error"] = case.get("error", "Exit code 1")
        if event == "PermissionDenied":
            p["reason"] = "[hook-harness case]"
    p.update(case.get("payload") or {})
    return p


@dataclass
class CaseResult:
    name: str
    event: str
    tool: str | None
    status: str = "pass"  # pass | fail | error
    choices: list = field(default_factory=list)
    runs: list = field(default_factory=list)  # (Choice, Run, Reading)
    decision: str = "none"
    duration: float = 0.0
    processes: int = 0
    checks: list = field(default_factory=list)  # (what, expected, actual, ok)
    notes: list = field(default_factory=list)
    errors: list = field(default_factory=list)


def run_case(src: Source, suite: Suite, case: dict, opts: Options, workdir: Path) -> CaseResult:
    event = case["event"]
    res = CaseResult(case["name"], event, case.get("tool_name"))
    base = suite.path.resolve().parent
    project = opts.project_dir or suite.project_dir or src.project_dir or Path.cwd()
    plugin_root = opts.plugin_root or suite.plugin_root or src.plugin_root
    plugin = src.kind == "plugin" or plugin_root is not None and (opts.plugin_root or suite.plugin_root) is not None
    cwd = str((base / case["cwd"]).resolve()) if case.get("cwd") else str(project)
    env = {k: v for k, v in os.environ.items() if not k.startswith("OTEL_")}
    if opts.scratch_home:
        env["HOME"] = env["USERPROFILE"] = str(workdir / "home")
    env.update(suite.env)
    env.update(case.get("env") or {})
    values = {"CLAUDE_PROJECT_DIR": str(project)}
    env.pop("CLAUDE_PLUGIN_ROOT", None)
    env.pop("CLAUDE_PLUGIN_DATA", None)
    if plugin and plugin_root is not None:
        values["CLAUDE_PLUGIN_ROOT"] = str(plugin_root)
        values["CLAUDE_PLUGIN_DATA"] = str(workdir / "plugin-data")
        for k, v in suite.user_config.items():
            env["CLAUDE_PLUGIN_OPTION_" + re.sub(r"[^A-Za-z0-9]", "_", k).upper()] = str(v)
    env.update(values)
    home = _home(env)
    transcript = workdir / "transcript.jsonl"
    payload = build_payload(case, cwd, home, "hook-harness-" + workdir.name, str(transcript))
    ctx = Context(cwd=str(payload.get("cwd") or cwd), project_dir=str(project), home=home)
    res.choices = choose(src, event, payload, ctx)
    chosen = [c for c in res.choices if c.runs]
    res.processes = sum(1 for c in chosen if c.handler.type == "command")
    for c in chosen:
        if c.handler.type != "command":
            res.notes.append(f"{c.handler.label} is a {c.handler.type} handler: matched, not run by hook-harness")
        if c.basis == "assumed":
            res.notes.append(f"{c.handler.label}: {c.why}")
    expect = case["expect"]
    if not opts.dry_run:
        stdin = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        jobs = []
        for c in chosen:
            if c.handler.type != "command":
                continue
            argv, why = spawn_plan(c.handler, values, suite.user_config, plugin)
            timeout = c.handler.spec.get("timeout")
            if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
                timeout = SHORT_TIMEOUT_EVENTS.get(event, DEFAULT_TIMEOUT["command"])
            if argv is None:
                jobs.append((c, None, Run(label=c.handler.label, error=why, timeout=timeout)))
            else:
                jobs.append((c, argv, timeout))
        results = {}

        def work(idx, c, argv, timeout):
            results[idx] = execute(argv, stdin, cwd, env, timeout, c.handler.label)

        threads = []
        t0 = time.monotonic()
        for idx, job in enumerate(jobs):
            c, argv, extra = job
            if argv is None:
                results[idx] = extra
                continue
            t = threading.Thread(target=work, args=(idx, c, argv, extra), daemon=True)
            t.start()
            threads.append(t)
        for t in threads:
            t.join()
        res.duration = time.monotonic() - t0
        readings = []
        for idx, (c, _argv, _extra) in enumerate(jobs):
            run = results[idx]
            reading = read_run(event, run, bool(c.handler.spec.get("async")))
            res.runs.append((c, run, reading))
            readings.append(reading)
            if run.error and run.error.startswith(HARNESS_GAP):
                res.errors.append(f"{c.handler.label}: {run.error[len(HARNESS_GAP):]}")
                continue
        res.decision = combine(event, readings)
        reasons = [x for r in readings for x in r.reasons]
        contexts = [x for r in readings for x in r.contexts]
        if "decision" in expect:
            res.checks.append(("decision", expect["decision"], res.decision, expect["decision"] == res.decision))
        for key, pool in (("reason_contains", reasons), ("context_contains", contexts)):
            if key in expect:
                wants = [expect[key]] if isinstance(expect[key], str) else expect[key]
                blob = "\n".join(pool)
                for want in wants:
                    res.checks.append((key, want, clean(blob, 160) if blob else "(nothing)", want in blob))
        if "max_duration" in expect:
            res.checks.append(("max_duration", f"<= {expect['max_duration']:g} s", f"{res.duration:.2f} s",
                               res.duration <= expect["max_duration"]))
        for c, run, reading in res.runs:
            if run.error and run.error.startswith(HARNESS_GAP):
                continue
            for sev, msg in reading.problems:
                if sev == "error" or (sev == "warning" and opts.strict):
                    res.checks.append(("output", f"{c.handler.label} valid for {event}", msg, False))
    for key, op in (("max_handlers", "<="), ("min_handlers", ">="), ("handlers", "==")):
        if key in expect:
            want = expect[key]
            ok = {"<=": res.processes <= want, ">=": res.processes >= want, "==": res.processes == want}[op]
            res.checks.append((key, f"{op} {want}", str(res.processes), ok))
    if opts.strict and any(c.basis == "assumed" for c in chosen):
        res.checks.append(("strict", "no assumed matches", "an `if` result was assumed", False))
    if res.errors:
        res.status = "error"
    if any(not ok for *_x, ok in res.checks):
        res.status = "fail"
    return res


def run_suite(src: Source, suite: Suite, opts: Options) -> list:
    out = []
    with tempfile.TemporaryDirectory(prefix="hook-harness-") as tmp:
        for n, case in enumerate(suite.cases):
            if opts.only and opts.only not in case["name"]:
                continue
            workdir = Path(tmp) / f"case{n + 1}"
            (workdir / "home").mkdir(parents=True)
            (workdir / "plugin-data").mkdir()
            (workdir / "transcript.jsonl").write_text("", encoding="utf-8")
            out.append(run_case(src, suite, case, opts, workdir))
    return out


# ---------------------------------------------------------------- lint

_PLUGIN_REF = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}\"?[/\\]([^\s\"'`;|&<>()$]+)")
_PROJECT_REF = re.compile(r"\$\{CLAUDE_PROJECT_DIR\}\"?[/\\]([^\s\"'`;|&<>()$]+)")
_BARE_PLACEHOLDER = re.compile(r"(?<![{:\w])\$(CLAUDE_PROJECT_DIR|CLAUDE_PLUGIN_ROOT|CLAUDE_PLUGIN_DATA)\b")


def _unquoted_placeholder(command: str, name: str) -> bool:
    token = "${" + name + "}"
    quote = None
    i = 0
    while i < len(command):
        c = command[i]
        if quote == "'":
            if c == "'":
                quote = None
        elif c == "\\":
            i += 1
        elif c == '"':
            quote = None if quote == '"' else '"'
        elif c == "'" and quote is None:
            quote = "'"
        elif command.startswith(token, i) and quote is None:
            return True
        i += 1
    return False


def _first_word(command: str) -> str:
    try:
        words = shlex.split(command, posix=True)
    except ValueError:
        words = command.split()
    while words and _ASSIGN.match(words[0]):
        words = words[1:]
    return words[0] if words else ""


def _matcher_can_match(matcher, event, tool) -> bool:
    return matcher_matches(matcher, event, tool)[0]


def _tool_rules(h: Handler):
    if "if" not in h.spec:
        return None
    r = parse_rule(h.spec.get("if"))
    return None if r.error else r


def _applies(h: Handler, tool: str) -> bool:
    if not _matcher_can_match(h.matcher, h.event, tool):
        return False
    if "if" not in h.spec:
        return True
    r = parse_rule(h.spec.get("if"))
    return not r.error and r.tool == tool


def _path_witnesses(pattern: str) -> list[str]:
    """Paths a file rule matches, for testing whether two rules can both match one call."""
    p = pattern.strip()
    for prefix in ("//", "~/", "./", "/"):
        if p.startswith(prefix):
            p = p[len(prefix):]
            break
    p = p.rstrip("/") or "x"
    base = re.sub(r"\[[^\]]*\]", "a", p).replace("?", "a")
    outs = set()
    for fill in ("x", "mcp", "src", "a.json"):
        s = base.replace("**", "d").replace("*", fill)
        outs.add(s)
        outs.add("d/" + s)
    return sorted(outs)


def lint(src: Source) -> list[Finding]:
    f = list(src.problems)
    data = src.data
    if data is None:
        return f
    if not isinstance(data, dict):
        f.append(Finding("json-shape", "error", "the top level is not a JSON object", (), 1, 1))
        return f
    if data.get("disableAllHooks") is True:
        f.append(src.finding("disable-all-hooks", "warning", "disableAllHooks is true in this file: none of its hooks "
                             "run", ("disableAllHooks",), HOOKS_DOC))
    hooks = data.get("hooks")
    if hooks is None:
        stray = [k for k in data if k in EVENTS]
        if stray:
            f.append(src.finding("hooks-key", "error", f"event names ({', '.join(stray)}) at the top level; Claude Code "
                                 "reads them only under \"hooks\"", (stray[0],), PLUGINS_DOC))
        else:
            f.append(Finding("hooks-key", "error", "no \"hooks\" object in this file", (), 1, 1))
        return f
    if not isinstance(hooks, dict):
        f.append(src.finding("hooks-key", "error", "\"hooks\" is not an object", ("hooks",)))
        return f
    for event, groups in hooks.items():
        path = ("hooks", event)
        if event not in EVENTS:
            near = [e for e in EVENTS if e.lower() == event.lower()]
            hint = f" (event names are case-sensitive: {near[0]})" if near else ""
            f.append(src.finding("unknown-event", "error", f"{event!r} is not a hook event, so these handlers never "
                                 f"run{hint}", path, PLUGINS_DOC))
            continue
        if not isinstance(groups, list):
            f.append(src.finding("hooks-shape", "error", f"{event} must be a list of matcher groups", path))
            continue
        for gi, group in enumerate(groups):
            gpath = path + (gi,)
            if not isinstance(group, dict):
                f.append(src.finding("hooks-shape", "error", "a matcher group must be an object", gpath))
                continue
            for k in set(group) - {"matcher", "hooks"}:
                f.append(src.finding("unknown-field", "warning", f"unknown key {k!r} in a matcher group",
                                     gpath + (k,)))
            _lint_matcher(src, f, event, group, gpath)
            hs = group.get("hooks")
            if not isinstance(hs, list):
                f.append(src.finding("hooks-shape", "error", "a matcher group needs a \"hooks\" list", gpath))
                continue
            if not hs:
                f.append(src.finding("hooks-shape", "warning", "empty \"hooks\" list", gpath + ("hooks",)))
            for hi, spec in enumerate(hs):
                hpath = gpath + ("hooks", hi)
                if not isinstance(spec, dict):
                    f.append(src.finding("hooks-shape", "error", "a handler must be an object", hpath))
                    continue
                _lint_handler(src, f, Handler(event, gi, hi, group.get("matcher"), "matcher" in group, spec, hpath))
    all_handlers = handlers_of(data)
    for event in sorted({h.event for h in all_handlers} & set(TOOL_EVENTS)):
        hs = [h for h in all_handlers if h.event == event]
        _lint_coverage(src, f, event, hs)
        _lint_fanout(src, f, event, hs)
    return _collapse(f)


def _collapse(findings: list) -> list:
    """One line for a note that repeats word for word on several handlers."""
    out, index = [], {}
    for x in findings:
        k = (x.rule, x.message) if x.severity == "note" else None
        if k and k in index:
            index[k][1] += 1
            continue
        entry = [x, 1]
        if k:
            index[k] = entry
        out.append(entry)
    result = []
    for x, n in out:
        if n > 1:
            x = Finding(x.rule, x.severity, f"{x.message} ({n} handlers)", x.path, x.line, x.col, x.source)
        result.append(x)
    return result


def _lint_matcher(src, f, event, group, gpath):
    if "matcher" not in group:
        return
    m = group["matcher"]
    mpath = gpath + ("matcher",)
    if event in NO_MATCHER_EVENTS:
        if m not in (None, "", "*"):
            f.append(src.finding("matcher-ignored", "warning", f"{event} has no matcher support: the matcher {m!r} is "
                                 "silently ignored and the group runs on every occurrence", mpath, HOOKS_DOC))
        return
    mode, arg = matcher_mode(m, event)
    if mode == "invalid":
        f.append(src.finding("matcher-invalid", "error", arg, mpath))
    elif mode == "regex":
        try:
            js_regex(arg)
        except re.error as e:
            f.append(src.finding("matcher-invalid", "error", f"the matcher {m!r} is not a valid regular expression "
                                 f"({e})", mpath))
        if event in TOOL_EVENTS and re.fullmatch(r"mcp__[A-Za-z0-9_-]+__\*", arg):
            f.append(src.finding("matcher-mcp", "note", f"{m!r} is a regular expression (`_*` repeats the "
                                 "underscore); mcp__server__.* is the documented form", mpath, HOOKS_DOC))
    elif mode == "exact":
        for name in arg:
            if not name:
                continue
            if event in TOOL_EVENTS:
                if name.startswith("mcp__"):
                    if name.count("__") < 2:
                        f.append(src.finding("matcher-mcp", "error", f"{name!r} is compared as an exact tool name and "
                                             f"matches no tool; write {name}__.* for every tool of that server",
                                             mpath, HOOKS_DOC + " (Match MCP tools)"))
                elif name in LEGACY_TOOLS:
                    f.append(src.finding("matcher-legacy-tool", "note", f"{name} is a legacy tool name (permissions "
                                         "docs) and not in the tools reference", mpath, TOOLS_DOC))
                elif name not in KNOWN_TOOLS:
                    near = [t for t in KNOWN_TOOLS if t.lower() == name.lower()]
                    if near:
                        f.append(src.finding("matcher-unknown-tool", "error", f"{name!r} matches no tool: matchers are "
                                             f"case-sensitive (the tool is {near[0]})", mpath, GUIDE_DOC))
                    else:
                        f.append(src.finding("matcher-unknown-tool", "warning", f"{name!r} is not a built-in tool name "
                                             f"(tools reference, {DOCS_CHECKED})", mpath, TOOLS_DOC))
            elif event in MATCHER_VALUES and name not in MATCHER_VALUES[event]:
                near = [v for v in MATCHER_VALUES[event] if v.lower() == name.lower()]
                f.append(src.finding("matcher-unknown-value", "warning", f"{name!r} is not a documented {event} matcher "
                                     f"value{f' (did you mean {near[0]!r}?)' if near else ''}", mpath, HOOKS_DOC))


def _lint_handler(src: Source, f: list, h: Handler):
    spec, path, event = h.spec, h.path, h.event
    t = spec.get("type")
    if t not in HANDLER_TYPES:
        f.append(src.finding("handler-type", "error", f"type {t!r} is not one of {', '.join(sorted(HANDLER_TYPES))}; "
                             "the handler never runs", path + ("type",), HOOKS_DOC))
        return
    for k in REQUIRED_FIELDS[t]:
        if not isinstance(spec.get(k), str) or not spec.get(k).strip():
            f.append(src.finding("missing-field", "error", f"a {t} handler needs {k!r}", path, HOOKS_DOC))
    for k in set(spec) - COMMON_FIELDS - TYPE_FIELDS[t]:
        f.append(src.finding("unknown-field", "warning", f"{k!r} is not a documented field of a {t} handler",
                             path + (k,), HOOKS_DOC))
    if event in EVENT_TYPES and t not in EVENT_TYPES[event]:
        f.append(src.finding("handler-type", "error", f"{event} supports only {', '.join(sorted(EVENT_TYPES[event]))} "
                             "handlers", path + ("type",), HOOKS_DOC))
    if "timeout" in spec:
        v = spec["timeout"]
        if not isinstance(v, (int, float)) or isinstance(v, bool) or v <= 0:
            f.append(src.finding("timeout", "error", "timeout must be a positive number of seconds",
                                 path + ("timeout",), HOOKS_DOC))
        elif v > MS_TIMEOUT_THRESHOLD:
            f.append(src.finding("timeout-ms", "warning", f"timeout {v:g} is in seconds ({v / 60:.0f} minutes); a "
                                 f"value above {MS_TIMEOUT_THRESHOLD} looks like milliseconds (hook-harness's threshold: "
                                 "600 s is Claude Code's own default)", path + ("timeout",), HOOKS_DOC))
        elif event == "SessionEnd" and v > 60:
            f.append(src.finding("timeout", "note", "SessionEnd hooks share a budget raised to at most 60 seconds",
                                 path + ("timeout",), HOOKS_DOC))
    if spec.get("once") is True:
        f.append(src.finding("once-ignored", "note", "once is honoured only in skill frontmatter and ignored here",
                             path + ("once",), HOOKS_DOC))
    if spec.get("async") is True and event in DECISION_EVENTS:
        f.append(src.finding("async-decision", "warning", f"an async handler cannot block or decide anything on "
                             f"{event}: its decision fields have no effect", path + ("async",), HOOKS_DOC))
    if "if" in spec:
        _lint_if(src, f, h)
    if t == "command" and isinstance(spec.get("command"), str):
        _lint_command(src, f, h)


def _lint_if(src: Source, f: list, h: Handler):
    ipath = h.path + ("if",)
    value = h.spec.get("if")
    if h.event not in TOOL_EVENTS:
        f.append(src.finding("if-non-tool-event", "error", f"`if` on {h.event}: a handler with `if` runs only on tool "
                             "events, so this one never runs", ipath, HOOKS_DOC))
        return
    if isinstance(value, list):
        f.append(src.finding("if-syntax", "error", "`if` holds exactly one permission rule, not a list; define a "
                             "handler per rule", ipath, HOOKS_DOC))
        return
    rule = parse_rule(value)
    if rule.error:
        f.append(src.finding("if-syntax", "error", rule.error, ipath, HOOKS_DOC))
        return
    if re.search(r"\)\s*(?:&&|\|\||,)\s*[A-Za-z_]\w*\s*\(", rule.text) or re.search(r"\s(?:&&|\|\|)\s", rule.tool):
        f.append(src.finding("if-syntax", "error", "`if` holds exactly one permission rule; there is no &&, || or list "
                             "syntax, so this is read as one rule that matches nothing", ipath, HOOKS_DOC))
        return
    tool = rule.tool
    if "*" in tool or (tool.startswith("mcp__") and tool.count("__") < 2):
        f.append(src.finding("if-tool-name", "warning", f"{tool!r}: in an `if` the tool name must be exact; `*`, "
                             f"`mcp__*` and a server-level mcp__server did not match any call ({OBSERVED})", ipath))
    elif tool not in KNOWN_TOOLS and tool not in LEGACY_TOOLS and not tool.startswith("mcp__"):
        near = [k for k in KNOWN_TOOLS if k.lower() == tool.lower()]
        f.append(src.finding("if-tool-name", "error" if near else "warning", f"{tool!r} is not a tool name"
                             + (f" (tool names are case-sensitive: {near[0]})" if near else ""), ipath, TOOLS_DOC))
    if not _matcher_can_match(h.matcher, h.event, tool):
        f.append(src.finding("if-outside-matcher", "error", f"the rule names {tool}, but the group's matcher "
                             f"{h.matcher!r} never matches {tool}: the handler never runs", ipath, HOOKS_DOC))
    spec = rule.spec
    if spec is None or spec.strip() in ("*", ""):
        return
    if tool in COMMAND_RULE_TOOLS or tool == "PowerShell":
        m = re.fullmatch(r"\s*([A-Za-z_]\w*)\s*:\s*(.+)", spec)
        if m and m.group(1) in ("command", "description", "timeout", "run_in_background") and not spec.endswith(":*"):
            f.append(src.finding("if-param-rule", "warning", f"{rule.text!r}: in an `if`, {OBSERVED} read this as a "
                                 "command pattern, not a parameter rule, so it matches no command (it still fires "
                                 "on commands with $( ))", ipath, PERMISSIONS_DOC))
    elif tool in PATH_RULE_FIELDS:
        if ".." in spec.split("/"):
            f.append(src.finding("if-path", "warning", f"{rule.text!r}: a pattern with .. matched nothing ({OBSERVED})",
                                 ipath))
    else:
        f.append(src.finding("if-specifier", "warning", f"{rule.text!r}: the tools reference documents this rule "
                             f"format, but in an `if` only {tool} or {tool}(*) matched a call ({OBSERVED}; tried "
                             "WebFetch(domain:...), Agent(name), MCP tools)", ipath, TOOLS_DOC))


def _lint_command(src: Source, f: list, h: Handler):
    spec, cpath = h.spec, h.path + ("command",)
    command = spec["command"]
    args = spec.get("args")
    exec_form = args is not None
    if exec_form and not (isinstance(args, list) and all(isinstance(a, str) for a in args)):
        f.append(src.finding("args", "error", "args must be a list of strings", h.path + ("args",), HOOKS_DOC))
        return
    if "shell" in spec and spec["shell"] not in ("bash", "powershell"):
        f.append(src.finding("shell", "error", "shell must be \"bash\" or \"powershell\"", h.path + ("shell",),
                             HOOKS_DOC))
    texts = [command] + (list(args) if exec_form else [])
    plugin = src.kind == "plugin"
    for text in texts:
        if "${CLAUDE_PLUGIN_ROOT}" in text and not plugin:
            f.append(src.finding("plugin-root", "warning", "${CLAUDE_PLUGIN_ROOT} is set only for plugin hooks; this "
                                 "file is not a plugin's hooks/hooks.json (a settings hook ran without it, "
                                 f"{OBSERVED})", cpath, HOOKS_DOC))
            break
    if plugin and src.plugin_root is not None:
        for text in texts:
            for rel in _PLUGIN_REF.findall(text):
                target = src.plugin_root / rel
                if not target.exists():
                    f.append(src.finding("plugin-file", "error", f"${{CLAUDE_PLUGIN_ROOT}}/{rel} does not exist under "
                                         f"{src.plugin_root}", cpath, HOOKS_DOC))
                elif not exec_form and _first_word(substitute(command, {"CLAUDE_PLUGIN_ROOT": str(src.plugin_root)})) \
                        == str(target) and os.name == "posix" and not os.access(target, os.X_OK):
                    f.append(src.finding("script-not-executable", "error", f"{rel} is run directly but is not "
                                         "executable (chmod +x)", cpath, GUIDE_DOC))
    if src.project_dir is not None:
        for text in texts:
            for rel in _PROJECT_REF.findall(text):
                if not (src.project_dir / rel).exists():
                    f.append(src.finding("project-file", "warning", f"${{CLAUDE_PROJECT_DIR}}/{rel} does not exist "
                                         f"under {src.project_dir}", cpath))
    if exec_form:
        if re.search(r"\s", command.strip()) and not re.search(r"[/\\]", command):
            f.append(src.finding("exec-command", "error", f"exec form: command {command!r} has spaces; it must be the "
                                 "executable alone, with the rest in args, or the spawn fails", cpath, HOOKS_DOC))
        base = re.split(r"[/\\]", command.strip())[-1].lower()
        if base.endswith((".cmd", ".bat")) or base in WINDOWS_SHIMS:
            f.append(src.finding("windows-exec-shim", "warning", f"exec form with {command!r}: on Windows the npm "
                                 "command shims are .cmd files, which exec form cannot start; the docs suggest "
                                 "\"node\" plus the script path", cpath, HOOKS_DOC))
    else:
        for name in PLACEHOLDERS:
            if _unquoted_placeholder(command, name):
                f.append(src.finding("placeholder-quotes", "warning", f"${{{name}}} is outside double quotes in a "
                                     "shell-form command; a path with a space splits it (docs: wrap each placeholder "
                                     "in double quotes, or use exec form)", cpath, HOOKS_DOC))
                break
        if plugin and _USER_CONFIG.search(command):
            f.append(src.finding("user-config-shell", "error", "a shell-form plugin hook that references "
                                 "${user_config.*} fails with an error instead of running; use exec form or "
                                 "$CLAUDE_PLUGIN_OPTION_<KEY>", cpath, HOOKS_DOC))
        if spec.get("shell") == "powershell" and _BARE_PLACEHOLDER.search(command):
            f.append(src.finding("powershell-env", "warning", "in a PowerShell hook, a bare $CLAUDE_PROJECT_DIR is an "
                                 "undefined PowerShell variable ($null); write ${CLAUDE_PROJECT_DIR} or "
                                 "$env:CLAUDE_PROJECT_DIR", cpath, HOOKS_DOC))
        first = _first_word(command)
        prog = re.split(r"[/\\]", first)[-1]
        if spec.get("shell") != "powershell" and prog in ("python3", "python3.exe"):
            f.append(src.finding("windows-interpreter", "note", "the command starts with python3. On Windows, "
                                 "Python's install manager provides python, py and pymanager; its python3 'is not "
                                 "meant to be widely used or recommended' (docs.python.org, Using Python on "
                                 f"Windows, checked {DOCS_CHECKED}). Where it is missing, the shell exits 127 and "
                                 "Claude Code reports a non-blocking hook error on every call (hooks docs)",
                                 cpath, PYWIN_DOC))
        elif spec.get("shell") != "powershell" and prog.endswith(".sh"):
            f.append(src.finding("windows-interpreter", "note", "the command runs a .sh script; on Windows Claude Code "
                                 "runs shell-form hooks with Git Bash, or with PowerShell where Git Bash is not "
                                 "installed, and PowerShell cannot run it", cpath, HOOKS_DOC))


def _lint_coverage(src: Source, f: list, event: str, hs: list):
    groups = {}
    for h in hs:
        groups.setdefault(h.gi, []).append(h)
    for gi, members in groups.items():
        matcher = members[0].matcher
        mode, arg = matcher_mode(matcher, event)
        if mode != "exact" or not all("if" in h.spec for h in members):
            continue
        named = {r.tool for h in members for r in [_tool_rules(h)] if r}
        for tool in arg:
            if tool and tool not in named and (tool in KNOWN_TOOLS or tool in LEGACY_TOOLS or tool.startswith("mcp__")):
                if tool in LEGACY_TOOLS:
                    continue
                f.append(src.finding("if-uncovered-tool", "warning", f"{tool} calls reach this group's matcher, but "
                                     f"every handler has an `if` for another tool, so nothing runs for {tool} (a "
                                     "single `if` rule matches only one tool's calls)", ("hooks", event, gi, "matcher"),
                                     HOOKS_DOC))
    targets_bash = any(("Bash" in (matcher_mode(h.matcher, event)[1] or []) if matcher_mode(h.matcher, event)[0] ==
                        "exact" else False) or (lambda r: r is not None and r.tool == "Bash")(_tool_rules(h)) for h in hs)
    if targets_bash and not any(_applies(h, "PowerShell") for h in hs):
        first = next(h for h in hs if _applies(h, "Bash"))  if any(_applies(h, "Bash") for h in hs) else hs[0]
        f.append(src.finding("windows-powershell", "warning", f"{event} handlers inspect Bash commands but none runs for "
                             "the PowerShell tool. On Windows, Claude Code routes shell commands through PowerShell "
                             "where it is enabled, and without Git Bash it registers no Bash tool, so these hooks "
                             "never fire there (match Bash|PowerShell)", first.path, HOOKS_DOC + " (PowerShell)"))


def _lint_fanout(src: Source, f: list, event: str, hs: list):
    tools = set()
    for h in hs:
        mode, arg = matcher_mode(h.matcher, event)
        if mode == "exact":
            tools.update(t for t in arg if t)
        r = _tool_rules(h)
        if r:
            tools.add(r.tool)
    if any(matcher_mode(h.matcher, event)[0] in ("all", "regex") for h in hs):
        tools.update({"Bash", "PowerShell", "Write", "Edit"})
    for tool in sorted(tools):
        seen, uniq = set(), []
        for h in hs:
            if h.type == "command" and _applies(h, tool) and h.key() not in seen:
                seen.add(h.key())
                uniq.append(h)
        by_command = {}
        for h in uniq:
            by_command.setdefault((h.spec.get("command"), _hashable(h.spec.get("args")), h.spec.get("shell")),
                                  []).append(h)
        for (command, _a, _s), same in by_command.items():
            if len(same) < 2:
                continue
            shown = clean(command, 80)
            if tool in COMMAND_RULE_TOOLS or tool == "PowerShell":
                specific = [h for h in same if "if" not in h.spec or not names_only((_tool_rules(h) or Rule("")).spec
                                                                                     or "*")]
                if tool == "PowerShell":
                    more = (f"A command with a $variable or $(...) is assumed to start {len(specific)} of them at once "
                            f"(PowerShell matching is not cross-checked)")
                else:
                    more = (f"A single Bash command with a $(...) or $VAR argument starts {len(specific)} of them at once; "
                            f"a compound command with one, or a command Claude Code cannot analyse (a here-document, "
                            f"${{VAR}}, \"$VAR\"), starts all {len(same)}")
                f.append(src.finding("fan-out", "warning", f"{len(same)} {event} handlers run {shown!r} for {tool} calls, "
                                     f"one process per matching handler. {more}. One handler that filters inside the "
                                     "script starts one", same[0].path, HOOKS_DOC))
            elif tool in PATH_RULE_FIELDS:
                rules = [(h, (_tool_rules(h) or Rule("")).spec) for h in same]
                if any(spec is None for _h, spec in rules):
                    f.append(src.finding("fan-out", "warning", f"{len(same)} {event} handlers run {shown!r} for {tool} "
                                         "calls and at least one has no `if`, so one call starts several processes",
                                         same[0].path, HOOKS_DOC))
                    continue
                witness = None
                ctx = Context(cwd="/w", project_dir="/w", home="/h")
                for _h, spec in rules:
                    for cand in _path_witnesses(spec):
                        path = "/w/" + cand
                        hits = [s for _x, s in rules if path_rule(s, path, ctx).fires]
                        if len(hits) >= 2:
                            witness = (cand, hits)
                            break
                    if witness:
                        break
                if witness:
                    f.append(src.finding("fan-out", "warning", f"{len(same)} {event} handlers run {shown!r} for {tool} "
                                         f"calls, and one path ({witness[0]}) matches {len(witness[1])} of their "
                                         f"rules: {', '.join(witness[1][:4])}", same[0].path, HOOKS_DOC))
            else:
                f.append(src.finding("fan-out", "warning", f"{len(same)} {event} handlers run {shown!r} for {tool} calls",
                                     same[0].path, HOOKS_DOC))
    for tool in ("Bash", "PowerShell"):
        wide = [h for h in hs if h.type == "command" and "if" in h.spec and (_tool_rules(h) or Rule("")).tool == tool
                and (_tool_rules(h).spec or "*").strip() not in ("*", "") and not names_only(_tool_rules(h).spec)]
        if wide and len(wide) <= 3:
            f.append(src.finding("if-wide", "note", f"{', '.join(repr(h.spec['if']) for h in wide)} names more than a "
                                 f"command, so Claude Code also runs {'this handler' if len(wide) == 1 else 'these handlers'}"
                                 f" for any {tool} command with a $(...) or $VAR argument, and for every command it "
                                 "cannot analyse; the script sees those commands too", wide[0].path + ("if",),
                                 HOOKS_DOC + " (Bash matching table)"))
    keys = {}
    for h in hs:
        if h.key() in keys:
            f.append(src.finding("duplicate-handler", "note", f"same command and `if` as {keys[h.key()].label}: Claude "
                                 f"Code runs it once ({OBSERVED})", h.path))
        else:
            keys[h.key()] = h


# ---------------------------------------------------------------- output

SEVERITY_ORDER = {"error": 0, "warning": 1, "note": 2}


def lint_report(src: Source, findings: list) -> dict:
    counts = {s: sum(1 for x in findings if x.severity == s) for s in ("error", "warning", "note")}
    return {"tool": f"hook-harness {VERSION}", "command": "lint", "file": str(src.path), "kind": src.kind,
            "plugin_root": str(src.plugin_root) if src.plugin_root else None,
            "docs_checked": DOCS_CHECKED, "observed_with": OBSERVED,
            "findings": [{"rule": x.rule, "severity": x.severity, "line": x.line, "column": x.col, "where": x.where(),
                          "message": clean(x.message, 1000), "source": x.source} for x in
                         sorted(findings, key=lambda x: (x.line or 0, SEVERITY_ORDER[x.severity]))],
            "summary": counts}


def render_lint_text(rep: dict) -> str:
    out = [f"{rep['tool']} lint {rep['file']} ({rep['kind']} hooks file; hooks docs checked {rep['docs_checked']})"]
    for x in rep["findings"]:
        loc = f"{rep['file']}:{x['line']}:{x['column']}" if x["line"] else rep["file"]
        out.append(f"{loc}: {x['severity']} [{x['rule']}] {x['message']}")
    s = rep["summary"]
    out.append(f"{s['error']} error(s), {s['warning']} warning(s), {s['note']} note(s).")
    return "\n".join(out) + "\n"


def _md(text: str) -> str:
    return clean(text, 600).replace("|", "\\|")


def render_lint_markdown(rep: dict) -> str:
    s = rep["summary"]
    out = [f"### hook-harness lint: `{rep['file']}`", "",
           f"{s['error']} error(s), {s['warning']} warning(s), {s['note']} note(s). Hooks docs checked "
           f"{rep['docs_checked']}; `if` behaviour as observed with {rep['observed_with']}.", ""]
    if rep["findings"]:
        out += ["| Line | Severity | Rule | Finding |", "|---:|---|---|---|"]
        for x in rep["findings"]:
            out.append(f"| {x['line'] or ''} | {x['severity']} | `{x['rule']}` | {_md(x['message'])} |")
    return "\n".join(out) + "\n"


def run_report(src: Source, suite: Suite, results: list, opts: Options) -> dict:
    cases = []
    for r in results:
        handlers = []
        for c in r.choices:
            entry = {"handler": c.handler.label, "line": src.at(c.handler.path)[0], "runs": c.runs, "why": clean(c.why, 400),
                     "basis": c.basis, "command": clean(c.handler.spec.get("command") or "", 200)}
            handlers.append(entry)
        runs = []
        for c, run, reading in r.runs:
            runs.append({"handler": c.handler.label, "argv": [clean(a, 200) for a in run.argv],
                         "exit_code": run.exit_code, "timed_out": run.timed_out, "duration": round(run.duration, 3),
                         "outcome": reading.outcome, "stdout_kind": reading.kind, "decision": reading.decision,
                         "reasons": [clean(x, 400) for x in reading.reasons],
                         "contexts": [clean(x, 400) for x in reading.contexts],
                         "problems": [{"severity": s, "message": clean(m, 400)} for s, m in reading.problems],
                         "stdout": clean(run.stdout, 2000, lines=True), "stderr": clean(run.stderr, 2000, lines=True)})
        cases.append({"name": r.name, "event": r.event, "tool_name": r.tool, "status": r.status,
                      "processes": r.processes, "duration": round(r.duration, 3), "decision": r.decision,
                      "handlers": handlers, "runs": runs,
                      "checks": [{"check": w, "expected": clean(str(e), 200), "actual": clean(str(a), 200), "ok": ok}
                                 for w, e, a, ok in r.checks],
                      "notes": [clean(n, 400) for n in r.notes], "errors": [clean(e, 400) for e in r.errors]})
    counts = {s: sum(1 for c in cases if c["status"] == s) for s in ("pass", "fail", "error")}
    return {"tool": f"hook-harness {VERSION}", "command": "run", "hooks_file": str(src.path),
            "cases_file": str(suite.path), "dry_run": opts.dry_run, "docs_checked": DOCS_CHECKED,
            "observed_with": OBSERVED, "cases": cases,
            "summary": {"cases": len(cases), "passed": counts["pass"], "failed": counts["fail"],
                        "errors": counts["error"]}}


def _case_line(c: dict, dry: bool = False) -> str:
    tool = f" {c['tool_name']}" if c["tool_name"] else ""
    procs = f"{c['processes']} process{'es' if c['processes'] != 1 else ''}"
    if dry:
        return f"{c['status'].upper():5} {c['name']}  ({c['event']}{tool}, {procs}; not run)"
    return f"{c['status'].upper():5} {c['name']}  ({c['event']}{tool}, {procs}, decision {c['decision']}, " \
           f"{c['duration']:.2f} s)"


def render_run_text(rep: dict, verbose: bool = False) -> str:
    out = [f"{rep['tool']} run {rep['hooks_file']} {rep['cases_file']}" + (" (dry run)" if rep["dry_run"] else "")]
    for c in rep["cases"]:
        out.append(_case_line(c, rep["dry_run"]))
        detail = verbose or c["status"] != "pass"
        for ch in c["checks"]:
            if not ch["ok"] or verbose:
                out.append(f"      {'ok  ' if ch['ok'] else 'FAIL'} {ch['check']}: expected {ch['expected']}, got "
                           f"{ch['actual']}")
        if detail:
            for runs in (True, False):
                hs = [h for h in c["handlers"] if h["runs"] == runs]
                limit = len(hs) if verbose else 8
                for h in hs[:limit]:
                    out.append(f"      {'runs' if h['runs'] else 'skip'} {h['handler']} (line {h['line']}): {h['why']}")
                if len(hs) > limit:
                    out.append(f"      ... and {len(hs) - limit} more handler(s) that {'run' if runs else 'do not run'}"
                               " (--verbose or --json lists them)")
            for run in c["runs"]:
                out.append(f"      {run['handler']}: {run['outcome']}; exit {run['exit_code']}, {run['duration']:.2f} s, "
                           f"stdout {run['stdout_kind']}")
                for p in run["problems"]:
                    out.append(f"        {p['severity']}: {p['message']}")
                for label, text in (("stdout", run["stdout"]), ("stderr", run["stderr"])):
                    if text.strip() and (verbose or c["status"] != "pass"):
                        # a prefix on every line, so hook output is never read as a CI workflow command
                        out.extend(f"        {label} | {ln}" for ln in text.strip().splitlines()[:12])
            for n in c["notes"] + c["errors"]:
                out.append(f"      note: {n}")
    s = rep["summary"]
    out.append(f"{s['cases']} case(s): {s['passed']} passed, {s['failed']} failed, {s['errors']} could not run.")
    return "\n".join(out) + "\n"


def render_run_markdown(rep: dict) -> str:
    s = rep["summary"]
    out = [f"### hook-harness run: `{rep['hooks_file']}`", "",
           f"{s['cases']} case(s): {s['passed']} passed, {s['failed']} failed, {s['errors']} could not run."
           + (" Dry run: nothing was executed." if rep["dry_run"] else ""), "",
           "| Case | Status | Event | Processes | Decision | Seconds |", "|---|---|---|---:|---|---:|"]
    for c in rep["cases"]:
        tool = f" {c['tool_name']}" if c["tool_name"] else ""
        decision, secs = ("not run", "") if rep["dry_run"] else (c["decision"], f"{c['duration']:.2f}")
        out.append(f"| {_md(c['name'])} | {c['status']} | {c['event']}{tool} | {c['processes']} | {decision} | {secs} |")
    for c in rep["cases"]:
        if c["status"] == "pass":
            continue
        out += ["", f"**{_md(c['name'])}**", ""]
        out += [f"- {'ok' if ch['ok'] else 'failed'}: {ch['check']}: expected {_md(ch['expected'])}, got "
                f"{_md(ch['actual'])}" for ch in c["checks"] if not ch["ok"]]
        out += [f"- {'runs' if h['runs'] else 'skipped'} `{h['handler']}`: {_md(h['why'])}" for h in c["handlers"]]
        out += [f"- note: {_md(n)}" for n in c["notes"] + c["errors"]]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- command line

def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="hook-harness",
        description="Test and lint Claude Code hooks: which handlers a tool call starts, what they print, whether "
                    "they decide what you expect, and static problems in the hooks file.",
        epilog="exit codes: 0 all good; 1 a case failed (run) or, with --strict, a finding (lint) or a warning (run); "
               "2 a file could not be read or a case could not run",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    sub = ap.add_subparsers(dest="cmd")

    def common(p):
        p.add_argument("--plugin-root", type=Path, metavar="DIR",
                       help="the plugin directory ${CLAUDE_PLUGIN_ROOT} stands for (default: the parent of hooks/)")
        p.add_argument("--project-dir", type=Path, metavar="DIR", help="the project directory "
                       "(${CLAUDE_PROJECT_DIR}; default: the cases file's project_dir, else the current directory)")
        fmt = p.add_mutually_exclusive_group()
        fmt.add_argument("--json", action="store_true", help="print a JSON report")
        fmt.add_argument("--markdown", action="store_true", help="print Markdown, e.g. for $GITHUB_STEP_SUMMARY")
        p.add_argument("--strict", action="store_true", help="lint: exit 1 on any error or warning; run: output "
                       "warnings and assumed `if` results fail a case too")

    lp = sub.add_parser("lint", help="static checks on a hooks file")
    lp.add_argument("hooks", type=Path, metavar="HOOKS.json")
    common(lp)
    rp = sub.add_parser("run", help="run test cases against a hooks file")
    rp.add_argument("hooks", type=Path, metavar="HOOKS.json")
    rp.add_argument("cases", type=Path, metavar="CASES.json")
    common(rp)
    rp.add_argument("--dry-run", action="store_true", help="show which handlers each case starts, run nothing")
    rp.add_argument("--scratch-home", action="store_true", help="run handlers with HOME set to an empty temporary "
                    "directory, so a hook under test cannot read your own configuration")
    rp.add_argument("--only", metavar="TEXT", help="run only cases whose name contains TEXT")
    rp.add_argument("-v", "--verbose", action="store_true", help="details for passing cases too")
    return ap


def main(argv: list | None = None) -> int:
    ap = _parser()
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 2
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(errors="replace")
        except (ValueError, OSError):
            pass
    for opt in ("plugin_root", "project_dir"):
        v = getattr(a, opt)
        if v is not None and not v.is_dir():
            print(f"hook-harness: --{opt.replace('_', '-')} {v} is not a directory", file=sys.stderr)
            return 2
    plugin_root = a.plugin_root.resolve() if a.plugin_root else None
    project_dir = a.project_dir.resolve() if a.project_dir else None
    src = load_source(a.hooks, plugin_root, project_dir)
    if not src.readable:
        print(f"hook-harness: {src.problems[0].message}", file=sys.stderr)
        return 2
    if a.cmd == "lint":
        findings = lint(src)
        rep = lint_report(src, findings)
        if a.json:
            print(json.dumps(rep, indent=1, ensure_ascii=False))
        elif a.markdown:
            sys.stdout.write(render_lint_markdown(rep))
        else:
            sys.stdout.write(render_lint_text(rep))
        if a.strict and (rep["summary"]["error"] or rep["summary"]["warning"]):
            return 1
        return 0
    if src.data is None or not isinstance(src.data, dict) or not isinstance(src.data.get("hooks"), dict):
        why = src.problems[0] if src.problems else None
        loc = f":{why.line}:{why.col}" if why and why.line else ""
        print(f"hook-harness: cannot run cases: {a.hooks}{loc}: " + (why.message if why else "no \"hooks\" object"),
              file=sys.stderr)
        return 2
    try:
        suite = load_suite(a.cases)
    except CaseFileError as e:
        print(f"hook-harness: {e}", file=sys.stderr)
        return 2
    opts = Options(plugin_root=plugin_root, project_dir=project_dir, dry_run=a.dry_run, scratch_home=a.scratch_home,
                   strict=a.strict, only=a.only)
    results = run_suite(src, suite, opts)
    if not results:
        print(f"hook-harness: no case name contains {a.only!r}", file=sys.stderr)
        return 2
    rep = run_report(src, suite, results, opts)
    if a.json:
        print(json.dumps(scrub(rep), indent=1, ensure_ascii=False))
    elif a.markdown:
        sys.stdout.write(render_run_markdown(rep))
    else:
        sys.stdout.write(render_run_text(rep, a.verbose))
    s = rep["summary"]
    if s["failed"]:
        return 1
    return 2 if s["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
