#!/usr/bin/env python3
"""inbox_add — pipe MEMORY+ lines into the gated memory inbox.

Reads stdin, extracts well-formed `MEMORY+ ...` lines, appends them to
memory/_inbox/ with provenance. Used by native sessions after a subagent
reply; the SDK path calls the same code directly.

    echo 'MEMORY+ kind=decision entity=rota text="..."' | python3 tools/inbox_add.py --src route:manual
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from router import config  # noqa: E402
from router.dispatch import parse_memory_lines  # noqa: E402
from router.mem_inbox import commit_lines  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(prog="inbox_add")
    parser.add_argument("--src", default="manual", help="provenance tag")
    args = parser.parse_args()
    lines = parse_memory_lines(sys.stdin.read())
    written = commit_lines(lines, config.load(), source=args.src)
    print(f"{written} fact(s) → memory/_inbox (awaiting review)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
