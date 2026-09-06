#!/usr/bin/env python3
"""spend — what this session actually cost, from its own transcript.

The receipt in `docs/token-rules.md` rule 11 asks every RESULT to carry the
task's token spend. Without a way to read it, every lead types an estimate, and
a number typed into a receipt reads as measured because it is written down —
which is the failure the receipt was added to avoid. This reads the usage the
API already recorded.

Attribution is the honest limit: the transcript records usage per API call, not
per task. `--since-calls N` scopes to the last N calls, which is the closest a
lead can get without marking task boundaries. Say which one you used.

    python3 tools/spend.py                     # whole session
    python3 tools/spend.py --since-calls 120   # roughly the last task
    python3 tools/spend.py --session <path>
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys

PROJECTS = os.path.expanduser("~/.claude/projects")


def newest_transcript() -> str | None:
    files = glob.glob(f"{PROJECTS}/**/*.jsonl", recursive=True)
    files = [f for f in files if "/subagents/" not in f]
    return max(files, key=os.path.getmtime) if files else None


def usages(path: str) -> list[dict]:
    out = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except Exception:
                continue
            msg = d.get("message")
            if isinstance(msg, dict) and isinstance(msg.get("usage"), dict):
                out.append(msg["usage"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser(prog="spend")
    ap.add_argument("--session", help="transcript path (default: most recent)")
    ap.add_argument("--since-calls", type=int, help="only the last N API calls")
    ap.add_argument("--mark", action="store_true",
                    help="print the current call index, to subtract from later")
    ap.add_argument("--from-call", type=int, metavar="INDEX",
                    help="only calls after INDEX (from an earlier --mark)")
    args = ap.parse_args()

    path = args.session or newest_transcript()
    if not path or not os.path.exists(path):
        sys.exit("no transcript found")

    rows = usages(path)
    total_calls = len(rows)

    if args.mark:
        # Record this before starting a task; pass it to --from-call after.
        print(f"  mark: {total_calls}   (start the task, then: spend.py --from-call {total_calls})")
        return 0

    scope = "whole session"
    if args.from_call is not None:
        rows = rows[args.from_call:]
        scope = f"calls {args.from_call}–{total_calls}"
    elif args.since_calls:
        # Rolling window. Successive tasks OVERLAP: a task measured this way
        # carries the cost of whatever preceded it inside the window. Every
        # figure this network reported on 2026-09-06 was measured like this and
        # overstates its task. Use --mark / --from-call for a real task cost.
        rows = rows[-args.since_calls:]
        scope = f"last {args.since_calls} API calls (ROLLING — overlaps earlier tasks)"

    fresh = sum(r.get("input_tokens", 0) + r.get("cache_creation_input_tokens", 0) for r in rows)
    cached = sum(r.get("cache_read_input_tokens", 0) for r in rows)
    out = sum(r.get("output_tokens", 0) for r in rows)

    print(f"  {os.path.basename(path)[:12]} · {scope} · {len(rows)} calls")
    print(f"    new input (billable)  {fresh:>14,}")
    print(f"    cache reads           {cached:>14,}")
    print(f"    output                {out:>14,}")
    print()
    # The receipt wants one number. New input plus output is what the session
    # added; cache reads are what it re-sent, and they dwarf both.
    print(f"    receipt figure: [~{round((fresh + out) / 1000):,}k]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
