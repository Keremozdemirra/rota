#!/usr/bin/env python3
"""action-vitals hook: the same checks, right after Claude writes or edits a workflow.

PostToolUse on Write, Edit and MultiEdit of .github/workflows/*.yml or *.yaml.
For Edit and MultiEdit only the `uses:` lines inside the text the edit wrote are
checked; Write replaces the whole file, so every `uses:` line in it is. When a
line has a finding (a tag or branch instead of a commit SHA, an archived
repository, a runtime GitHub has retired, ...) Claude gets the facts as
additionalContext, with the pinned line where a tag could be resolved.

Clean lines pass silently. Anything the hook cannot parse, reach or resolve
passes silently too: it never blocks, never denies, and never edits a file.
All lookups share a short time budget, because someone is waiting.
ACTION_VITALS_OFFLINE=1 makes it send nothing; ACTION_VITALS_NO_RUNTIME=1 stops
it downloading other repositories' action.yml files.

Claude Code runs every matching handler as its own process, and a plugin's
handler and the same command in a settings file both run. So the first process
to see a tool_use_id takes an O_EXCL lock file in the temp directory and any
other copy exits without output.
"""
from __future__ import annotations

import bisect
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import action_vitals as av  # noqa: E402

# The tool's own choices: all lookups together get 10 seconds, each one at most 5.
BUDGET = 10.0
TIMEOUT = 5.0
MAX_LINES = 15
WORKFLOW = re.compile(r"(?:^|/)\.github/workflows/[^/]+\.ya?ml$")


def main() -> int:
    try:
        return _main()
    except Exception:  # noqa: BLE001  a bug here must not get in the way of the edit
        return 0


def _main() -> int:
    try:
        payload = json.loads(sys.stdin.read())
    except ValueError:
        return 0
    if not isinstance(payload, dict) or payload.get("hook_event_name") != "PostToolUse":
        return 0
    tool = payload.get("tool_name")
    ti = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    fp = ti.get("file_path")
    # the `if` rules in hooks.json narrow this already; this is the check that counts
    if tool not in ("Write", "Edit", "MultiEdit") or not isinstance(fp, str) or not WORKFLOW.search(fp.replace("\\", "/")):
        return 0
    if not first_claim(payload.get("tool_use_id")):
        return 0
    path = Path(fp)
    text, _ = av.read_text(path)
    if text is None:
        return 0
    uses = av.find_uses(av.scan_yaml(text))
    uses = [u for u in uses if u["value"] is not None]
    lines, written = touched(text, ti, tool)
    if lines is not None:
        chosen = [u for u in uses if u["line"] in lines or u.get("anchor_line") in lines]
        if not chosen and written:  # the file changed after the edit (a formatter): match on what the edit wrote
            chosen = [u for u in uses if any(u["value"] in w for w in written)]
        uses = chosen
    if not uses:
        return 0
    root = av.repo_root(path.parent) or path.parent
    entry = {"path": path, "root": root, "kind": "workflow", "text": text, "error": "", "uses": uses, "issues": []}
    token = (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip() or None
    offline = os.environ.get("ACTION_VITALS_OFFLINE") == "1"
    runtime = os.environ.get("ACTION_VITALS_NO_RUNTIME") != "1"
    net = None if offline else av.Net(token=token, census=None, timeout=TIMEOUT, git_timeout=TIMEOUT, retry=False,
                                      runtime=runtime, deadline=time.monotonic() + BUDGET)
    results = [x for x in av.check([entry], net, av._today(), runtime) if reportable(x)]
    if not results:
        return 0
    print(json.dumps(respond(explain(results, fp))))
    return 0


def reportable(x: dict) -> bool:
    """A finding worth Claude's attention: anything but a lookup that could not complete."""
    return any(f not in av.INCOMPLETE for f in x["flags"])


def touched(text: str, ti: dict, tool: str) -> tuple[set[int] | None, list[str]]:
    """The line numbers the edit's new text now occupies (None: the whole file), and that new text."""
    if tool == "Write" or "content" in ti:
        return None, []
    written = [ti["new_string"]] if isinstance(ti.get("new_string"), str) else []
    written += [e["new_string"] for e in ti.get("edits") or [] if isinstance(e, dict) and isinstance(e.get("new_string"), str)]
    starts = [0] + [m.end() for m in av.LINE_BREAK.finditer(text)]
    lines = set()
    for new in written:
        body = new.rstrip("\r\n")
        if not body.strip():
            continue
        i = text.find(body)
        while i >= 0:
            first, last = bisect.bisect_right(starts, i), bisect.bisect_right(starts, i + len(body) - 1)
            lines.update(range(first, last + 1))
            i = text.find(body, i + len(body))
    return lines, written


def first_claim(tool_use_id) -> bool:
    """True for the first process to see this tool call; False for a second copy of the handler."""
    if not isinstance(tool_use_id, str) or not tool_use_id:
        return True
    d = tempfile.gettempdir()
    name = os.path.join(d, "action-vitals-" + hashlib.sha256(tool_use_id.encode("utf-8", "replace")).hexdigest()[:40]
                        + ".lock")
    try:
        os.close(os.open(name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
    except FileExistsError:
        return False
    except OSError:
        return True  # no usable temp directory: better to answer twice than never
    sweep(d)
    return True


def sweep(d: str) -> None:
    """Remove this hook's lock files older than a day, so they do not pile up."""
    cutoff = time.time() - 86400
    try:
        with os.scandir(d) as it:
            for e in it:
                if e.name.startswith("action-vitals-") and e.name.endswith(".lock"):
                    try:
                        if e.stat().st_mtime < cutoff:
                            os.unlink(e.path)
                    except OSError:
                        pass
    except OSError:
        pass


def explain(results: list[dict], file_path: str) -> str:
    name = Path(file_path).name
    parts = [f"action-vitals checked the uses: lines this edit wrote in {av.clean(name, 80)}."]
    for x in results[:MAX_LINES]:
        repo = (x["facts"].get("repository") or {})
        facts = [av.pin_phrase(x, for_model=True), av.runtime_phrase(x) if x["runtime"] else "",
                 "" if repo.get("error") else av.repo_phrase(x)]
        facts += [n for n in x["notes"] if not n.startswith(("git ls-remote", "runtime:"))]
        line = f"Line {x['line']} `{av.clean(x['uses'], 160)}`: " + "; ".join(f for f in facts if f)
        line += f". Flags: {', '.join(f for f in x['flags'] if f not in av.INCOMPLETE)}."
        if x["suggestion"]:
            line += f" Pinned: `uses: {x['suggestion']} # {av.tag_text(x['tag'] or x['ref'], for_model=True)}`."
        parts.append(line)
    if len(results) > MAX_LINES:
        parts.append(f"And {len(results) - MAX_LINES} more lines with findings; run action-vitals for all of them.")
    if any("unpinned" in x["flags"] for x in results):
        parts.append(f'GitHub\'s secure-use reference: "{av.SECURE_USE_QUOTE}"')
    parts.append("These are refs from git ls-remote and metadata from GitHub, not a verdict on any action. "
                 "Tell the user; change a pin only if they want it changed.")
    return "\n".join(parts)


def respond(text: str) -> dict:
    return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": text[:9000]}}


if __name__ == "__main__":
    raise SystemExit(main())
