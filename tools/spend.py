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
import time

PROJECTS = os.path.expanduser("~/.claude/projects")


FRESH_WINDOW = 6 * 3600  # a transcript touched this recently may be a live session


class Ambiguous(Exception):
    """More than one session could be the caller's, so no number is safe."""

    def __init__(self, candidates):
        super().__init__("ambiguous transcript")
        self.candidates = candidates


def transcripts(root: str | None = None) -> list[str]:
    # Read the global at call time; a default bound at def time cannot be
    # redirected, which made the resolver untestable and scanned the real machine.
    root = PROJECTS if root is None else root
    return [f for f in glob.glob(f"{root}/**/*.jsonl", recursive=True)
            if "/subagents/" not in f]


def resolve_transcript(session: str | None = None, root: str | None = None,
                       window: int = FRESH_WINDOW, now: float | None = None) -> str | None:
    """The transcript to measure, or Ambiguous when the machine cannot tell.

    "Newest" resolves to a different session between two calls seconds apart
    when several lanes run at once. On 2026-09-07 a --mark returned 1534 and the
    next returned 1475, a decrease an append-only log cannot produce; on
    2026-09-08 a lane's receipt carried 8,710k that belonged to another session,
    because the earlier version warned on stderr and the caller was piping
    through tail. A number that reads as measured and names the wrong session is
    the failure this tool exists to prevent, so ambiguity is refused rather than
    reported.
    """
    if session:
        return session
    files = transcripts(root)
    if not files:
        return None
    now = time.time() if now is None else now
    fresh = sorted((f for f in files if now - os.path.getmtime(f) <= window),
                   key=os.path.getmtime, reverse=True)
    if len(fresh) > 1:
        raise Ambiguous(fresh)
    if fresh:
        return fresh[0]
    # Nothing has been written for hours, so no other lane is live to confuse.
    return max(files, key=os.path.getmtime)


def session_id(path: str) -> str:
    return os.path.basename(path)[:-len(".jsonl")] if path.endswith(".jsonl") else os.path.basename(path)


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

    try:
        path = resolve_transcript(args.session)
    except Ambiguous as amb:
        hours = FRESH_WINDOW // 3600
        print(f"  refusing to guess: {len(amb.candidates)} transcripts were written "
              f"in the last {hours} hours.")
        print("  pass --session with your own; each session's scratchpad directory "
              "is named for its transcript.")
        for f in amb.candidates:
            print(f"    {session_id(f)}")
            print(f"      {f}")
        return 2
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
