#!/usr/bin/env python3
"""destroy-guard hook: PreToolUse on Bash and PowerShell.

Reads the hook payload on stdin. When the command would run `terraform
destroy`, `kubectl delete`, `helm uninstall`, `git push --force` or another
operation destroy_guard.py knows, and no fresh, verified backup of exactly that
target is on record, it answers "ask" with the facts and the one command that
makes the backup. Otherwise it prints nothing, and Claude Code's normal
permission flow decides.

It never answers "allow" or "deny". It runs no command, writes no file and
sends nothing anywhere: it reads the command, a few small files that say where
the command points (.terraform/environment, .git/HEAD and config, the
kubeconfig's current-context line, manifest files named by `kubectl delete -f`)
and the manifests under .destroy-guard/backups. Any error inside it lets the
command through to the normal flow and is noted on stderr, which Claude Code
keeps in its debug log.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import destroy_guard as dg  # noqa: E402


def main() -> int:
    try:
        return _main()
    except Exception as e:  # noqa: BLE001  a bug here must not stop the person's work
        print(f"destroy-guard hook: internal error, command not checked: {type(e).__name__}: "
              f"{dg.clean(dg.mask_text(str(e)), 200)}", file=sys.stderr)
        return 0


def _main() -> int:
    raw = sys.stdin.buffer.read() if hasattr(sys.stdin, "buffer") else sys.stdin.read().encode("utf-8")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        print("destroy-guard hook: stdin is not a JSON hook payload; command not checked", file=sys.stderr)
        return 0
    if not isinstance(payload, dict):
        return 0
    if payload.get("hook_event_name") != "PreToolUse" or payload.get("tool_name") not in ("Bash", "PowerShell"):
        return 0
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str) or not dg.QUICK.search(command):
        return 0  # the cheap test first: most commands name none of the tools
    cwd = payload.get("cwd")
    cwd = cwd if isinstance(cwd, str) and os.path.isdir(cwd) else os.getcwd()
    shell = "powershell" if payload.get("tool_name") == "PowerShell" else "bash"
    results = dg.evaluate(command, shell, cwd)
    text = dg.reason(results, cwd)
    if text is None:
        return 0
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "ask",
        "permissionDecisionReason": text,
        # the reason is shown to the person only; this tells Claude the same facts next to the result
        "additionalContext": text + " If the person wants the backup, run that backup command on its own first,"
                                    " check that it prints `verified backup`, then run the original command again.",
    }}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
