#!/usr/bin/env python3
"""lessons — surface the observation backlog so the loop closes.

Friction gets captured automatically by task-observer. Acting on it does not:
the review ran once, by hand, after the file had said `never` for eleven days
and twenty-four observations had piled up. Capture without surfacing is a
diary, not a loop.

This prints what is waiting and how long it has waited, grouped by the skill
it would improve — the grouping is the signal, because several observations
against one skill mean that skill is the next thing to fix, not the oldest
one. Judgement stays human on purpose: the review gate is why this vault is
trustworthy, and a script that promoted its own findings would be the failure
it exists to catch.

    python3 tools/lessons.py [--days N]
"""

from __future__ import annotations

import collections
import datetime as dt
import re
import sys
from pathlib import Path

LOG = (Path.home() / ".claude" / "projects" / "-Users-keremozdemir-agents"
       / "skill-observations" / "log.md")
LAST = LOG.parent / "last-review-date.txt"
ARCHIVE = LOG.parent / "archive"


# Resolved entries are moved out of the live log into archive/ by design. A
# reader that counts only the live file reports "0 actioned" on a log where
# everything actioned was correctly filed away — which reads as "the review
# never produced anything" and is the opposite of the truth. This cost a false
# alarm and nearly a duplicate-restore of eight entries that were never lost:
# a count that dropped is not evidence of loss until you look where it went.
def parse(text: str) -> list[dict]:
    out, cur = [], None
    for line in text.splitlines():
        m = re.match(r"^### Observation (\d+):\s*(.*)$", line)
        if m:
            cur = {"n": int(m.group(1)), "title": m.group(2).strip(),
                   "status": "OPEN", "skill": "?", "date": ""}
            out.append(cur)
        elif cur is not None:
            for key, pat in (("status", r"^\*\*Status:\*\*\s*(\S+)"),
                             ("date", r"^\*\*Date:\*\*\s*(\S+)"),
                             ("skill", r"^\*\*Skill:\*\*\s*(.+?)\s*$")):
                mm = re.match(pat, line)
                if mm:
                    cur[key] = mm.group(1)
    return out


def main() -> int:
    if not LOG.exists():
        print("  no observation log yet")
        return 0
    obs = parse(LOG.read_text(encoding="utf-8"))
    open_ = [o for o in obs if o["status"].upper().startswith("OPEN")]
    done = len(obs) - len(open_)
    archived = 0
    if ARCHIVE.is_dir():
        for f in ARCHIVE.glob("*.md"):
            archived += len(parse(f.read_text(encoding="utf-8")))
    done += archived
    last = LAST.read_text(encoding="utf-8").strip() if LAST.exists() else "never"

    print(f"  {len(open_)} open · {done} resolved ({archived} filed to archive/)"
          f" · last review: {last}")
    if not open_:
        print("  nothing waiting")
        return 0

    today = dt.date.today()
    ages = []
    for o in open_:
        try:
            ages.append((today - dt.date.fromisoformat(o["date"])).days)
        except (ValueError, KeyError):
            pass
    if ages:
        print(f"  oldest has waited {max(ages)} days")

    by = collections.Counter(re.sub(r"^\**Skill:\**\s*", "", o["skill"]).split("(")[0].strip()
                             for o in open_)
    print("  by skill — the cluster is the signal, not the age:")
    for skill, n in by.most_common(6):
        mark = "  ← fix this one next" if n >= 3 else ""
        print(f"    {n:>2}  {skill[:44]}{mark}")

    if last == "never" or (ages and max(ages) > 14):
        print("\n  → run the review: it is the half of the loop that produces value,")
        print("    and it is the half that does not happen on its own.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
