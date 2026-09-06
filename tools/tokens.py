#!/usr/bin/env python3
"""tokens — where context actually goes, and whether the rule is working.

Measured 2026-08-31: 86% of context was tool output, `Read` alone 61.6% at an
average 170 KB per call, screenshots 29%, `Bash` only 5.9% across 6,786 calls.
CLAUDE.md §8 was written from that. A rule nobody measures again is a rule
nobody follows, so this runs inside the weekly brief and reports the trend
against the last run instead of leaving a date in a file.

Stdlib only, reads local transcripts, sends nothing anywhere.

    python3 tools/tokens.py [--days 7] [--json]
"""

from __future__ import annotations

import glob
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
STATE = ROOT / "memory" / "_index" / "tokens.json"
PROJECTS = Path.home() / ".claude" / "projects"
SAMPLE = 12          # largest transcripts; the tail is noise
WATCH = ("Read", "Bash")


def measure(days: int) -> dict:
    cutoff = time.time() - days * 86400
    files = [f for f in glob.glob(str(PROJECTS / "**" / "*.jsonl"), recursive=True)
             if os.path.getmtime(f) > cutoff]
    files.sort(key=os.path.getsize, reverse=True)
    total = 0
    by_tool: dict[str, list[int]] = {}
    pending: dict[str, str] = {}
    for f in files[:SAMPLE]:
        try:
            handle = open(f, encoding="utf-8", errors="ignore")
        except OSError:
            continue
        with handle:
            for line in handle:
                try:
                    blocks = (json.loads(line).get("message") or {}).get("content")
                except (json.JSONDecodeError, AttributeError):
                    continue
                if not isinstance(blocks, list):
                    continue
                for b in blocks:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "tool_use":
                        pending[b.get("id")] = b.get("name") or "?"
                    elif b.get("type") == "tool_result":
                        c = b.get("content")
                        n = len(c if isinstance(c, str) else json.dumps(c))
                        total += n
                        by_tool.setdefault(pending.get(b.get("tool_use_id"), "?"), []).append(n)
    return {
        "days": days,
        "sessions": len(files),
        "sampled": min(SAMPLE, len(files)),
        "tool_result_bytes": total,
        "tools": {k: {"calls": len(v), "bytes": sum(v), "avg": sum(v) // len(v)}
                  for k, v in sorted(by_tool.items(), key=lambda x: -sum(x[1]))[:8]},
    }


def main() -> int:
    days = 7
    if "--days" in sys.argv:
        try:
            days = int(sys.argv[sys.argv.index("--days") + 1])
        except (IndexError, ValueError):
            pass
    now = measure(days)
    prev = {}
    if STATE.exists():
        try:
            prev = json.loads(STATE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            prev = {}

    if "--json" in sys.argv:
        print(json.dumps({"now": now, "prev": prev}, indent=2))
    else:
        tot = now["tool_result_bytes"] or 1
        print(f"last {days}d · {now['sessions']} sessions · {now['sampled']} largest sampled")
        print(f"{'tool':<22}{'calls':>7}{'avg bytes':>12}{'share':>8}{'vs last':>10}")
        for name, d in now["tools"].items():
            was = (prev.get("tools") or {}).get(name, {}).get("avg")
            delta = "—" if not was else f"{100*(d['avg']-was)/was:+.0f}%"
            print(f"{name[:21]:<22}{d['calls']:>7}{d['avg']:>12,}{100*d['bytes']/tot:>7.1f}%{delta:>10}")
        for name in WATCH:
            d = now["tools"].get(name)
            was = (prev.get("tools") or {}).get(name, {}).get("avg")
            if d and was and d["avg"] > was:
                print(f"\n[!] {name} average grew {was:,} → {d['avg']:,} bytes — "
                      f"CLAUDE.md §8 is not holding.")
        if not prev:
            print("\nbaseline stored — the next run reports the trend.")

    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(now, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
