#!/usr/bin/env python3
"""destroy-guard hook: PreToolUse on Bash and PowerShell.

Reads the hook payload on stdin. When the command would run `terraform
destroy`, `kubectl delete`, `helm uninstall`, `git push --force` or another
operation destroy_guard.py knows, and no fresh, verified backup of exactly that
target is on record, it answers "ask" with the facts and the one command that
makes the backup. Otherwise it prints nothing, and Claude Code's normal
permission flow decides.

It never answers "allow" or "deny". It runs no command and sends nothing
anywhere: it reads the command, a few small files that say where the command
points (.terraform/environment, .git/HEAD and config, the kubeconfig's
current-context and that context's namespace, manifest files named by
`kubectl delete -f`) and the manifests under .destroy-guard/backups. The one
file it writes, when it asks, is an empty claim for that tool call in a
private temporary directory, so that a second copy of this hook (plugin and
settings both installed) stays silent. Any error inside it lets the command through to the
normal flow and is noted on stderr, which Claude Code keeps in its debug log.
"""
from __future__ import annotations

import json
import os
import re
import stat
import sys
import tempfile
import time
from pathlib import Path

# The documented cap is 10,000 characters; beyond it Claude gets a file path instead of the text.
CONTEXT_LIMIT = 9000
CLAIM_MAX_AGE = 600  # seconds: a claim older than this belongs to a tool call that has finished


def main() -> int:
    try:
        return _main()
    except Exception as e:  # noqa: BLE001  a bug here must not stop the person's work
        try:
            import destroy_guard as dg
            detail = dg.clean(dg.mask_text(str(e)), 200)
        except Exception:  # noqa: BLE001  the module itself may be what failed
            detail = ""
        print(f"destroy-guard hook: internal error, command not checked: {type(e).__name__}: {detail}",
              file=sys.stderr)
        return 0


def claim(tool_use_id) -> bool:
    """True for the first process that takes this tool call.

    Claude Code runs every matching handler as its own process, and a plugin's copy and a settings
    copy of this hook stay separate, so both would answer. An O_EXCL file per tool_use_id in a
    per-user temporary directory lets exactly one of them answer. When no claim can be made, answer
    anyway: a question asked twice is better than none.
    """
    key = re.sub(r"[^A-Za-z0-9_-]", "", str(tool_use_id or ""))[:120]
    if not key:
        return True
    try:
        uid = os.getuid() if hasattr(os, "getuid") else None
        d = Path(tempfile.gettempdir()) / f"destroy-guard-{uid if uid is not None else 'user'}"
        d.mkdir(mode=0o700, exist_ok=True)
        st = os.lstat(d)
        if not stat.S_ISDIR(st.st_mode) or (uid is not None and st.st_uid != uid):
            return True
        now = time.time()
        for e in os.scandir(d):
            try:
                if now - e.stat(follow_symlinks=False).st_mtime > CLAIM_MAX_AGE:
                    os.unlink(e.path)
            except OSError:
                pass
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
        os.close(os.open(str(d / key), flags, 0o600))
        return True
    except FileExistsError:
        return False
    except OSError:
        return True


def _main() -> int:
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    import destroy_guard as dg  # inside the guard: a broken install must pass, not fail with a traceback

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
    if not isinstance(command, str) or not dg.quick(command):
        return 0  # the cheap test first: most commands name none of the tools
    cwd = payload.get("cwd")
    cwd = cwd if isinstance(cwd, str) and os.path.isdir(cwd) else os.getcwd()
    shell = "powershell" if payload.get("tool_name") == "PowerShell" else "bash"
    results = dg.evaluate(command, shell, cwd)
    text = dg.reason(results, cwd, shell=shell)
    if text is None:
        return 0
    if not claim(payload.get("tool_use_id")):
        return 0  # another copy of this hook has answered for this tool call
    context = dg.reason(results, cwd, shell=shell, limit=CONTEXT_LIMIT)
    # ASCII JSON: a Windows pipe encodes stdout in the ANSI code page, where a path or name in another
    # script would raise UnicodeEncodeError and the question would never be asked.
    sys.stdout.write(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "ask",
        "permissionDecisionReason": text,
        # the reason is shown to the person only; this tells Claude the same facts next to the result
        "additionalContext": context + " If the person asks for the backup, run that command, check that it"
                                       " prints `verified backup`, then run the original command again.",
    }}) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
