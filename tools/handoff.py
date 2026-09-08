#!/usr/bin/env python3
"""Write the handoff a fresh lane session reads on its first turn.

Every turn re-sends the whole conversation, so a lane that has run for 1,900
messages pays for all of them on every call. The fix is a fresh session that
starts from a small, current file instead of from its history. This script
builds that file from the records the network already keeps: the charter, the
open tasks, the last log lines that name the lane, and the standing rules.

    python3 handoff.py <lane>            writes ~/.claude/orkestra/handoff/<lane>.md and prints it
    python3 handoff.py <lane> --print    prints only
"""
import re
import sys
from datetime import date
from pathlib import Path

ORK = Path.home() / ".claude" / "orkestra"
LANE_ALIASES = {"daily": ["daily", "github-lead", "github"], "keremozdemir.de": ["keremozdemir.de", "site lane", "site lead"]}


def rows_for(lane: str, text: str):
    names = LANE_ALIASES.get(lane, [lane])
    out = []
    for line in text.splitlines():
        if not line.startswith("| T-"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 5:
            continue
        owner, status = cells[2].lower(), cells[4].lower()
        if any(n in owner for n in names) and not status.startswith(("done", "void", "closed")):
            out.append(f"- {cells[0]}: {cells[1][:260]} (status: {cells[4][:80]})")
    return out


def log_lines(lane: str, text: str, n: int = 8, width: int = 420):
    names = LANE_ALIASES.get(lane, [lane])
    hits = [l for l in text.splitlines() if l.startswith("- 20") and any(re.search(rf"\b{re.escape(x)}\b", l) for x in names)]
    return [(h if len(h) <= width else h[:width].rstrip() + " (…)") for h in hits[-n:]]


def build(lane: str) -> str:
    charter = ORK / "leads" / f"{lane}.md"
    tasks = (ORK / "tasks.md").read_text(encoding="utf-8") if (ORK / "tasks.md").exists() else ""
    log = (ORK / "log.md").read_text(encoding="utf-8") if (ORK / "log.md").exists() else ""
    open_rows = rows_for(lane, tasks) or ["- none open in tasks.md"]
    recent = log_lines(lane, log) or ["- no log line names this lane yet"]
    return f"""# Handoff: {lane}, {date.today().isoformat()}

You are the {lane} lane of Kerem's network, in a fresh session. Read, in this order, and nothing else before your first receipt:

1. `~/.claude/orkestra/system.md` (one page: how the network runs, each rule with its enforcer)
2. `{charter}` (your charter: mission, routing, constraints, pre-flight)
3. `~/agents/rota/skills/orkestra/SKILL.md` and `~/agents/rota/skills/craft/SKILL.md`

Then run the access probe (`python3 ~/agents/rota/tools/pathcheck.py {charter}`, then `ls` the roots your charter names) and send the hub one receipt: `Şef: [ORK] RESULT {lane} → hub | fresh session ready`, five lines, missing and denied paths reported separately, your sessionId in the body. Your visible reply in this chat is one English line: `Sent to hub: fresh session ready`. Then wait for a REQUEST.

## Open tasks (from tasks.md)

{chr(10).join(open_rows)}

## What happened last (from log.md, newest last)

{chr(10).join(recent)}

## Standing rules that bite most

- Kerem reads only the hub. Everything you have to say goes by `send_message` to `local_d745dbde-a33b-4a0e-8f8a-f18bd95be1fb`; the chat's visible reply is one line.
- A message to the hub opens with `Şef:` on line 1, fits 14 lines and 1,800 characters, carries no dash on that line. Detail goes in the file PATH names.
- One task at a time; a numbered REQUEST runs inside one turn with one RESULT per step; a turn that ends waits.
- Read files with offset and limit; grep before reading; no screenshot unless it is the deliverable. Every file read stays in this session's context for its whole life.
- Do not change model or effort mid-session; that reprocesses the conversation from scratch.
- Every number traces to a command or a dated record. Verbatim material sits in a blockquote or a fence.
- What the hub may authorise and what stays Kerem's is in system.md under Authority. A permission prompt in this chat is never lifted by a hub message; report the exact command and stop.
"""


def main(argv):
    if len(argv) < 2:
        print(__doc__); return 2
    lane = argv[1]
    text = build(lane)
    if "--print" not in argv:
        out = ORK / "handoff" / f"{lane}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"wrote {out}\n")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
