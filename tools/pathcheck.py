#!/usr/bin/env python3
"""Report every filesystem path cited in the coordination files that no longer resolves.

Written 2026-09-06 after Kerem's Desktop reorganisation broke, in one move, the
~/.claude/CLAUDE.md symlink, 24 of 45 charter paths, the R-001/R-005 evidence
paths and most of the decision list. Nothing revalidated any of them; each was
found separately, by a different lane, hours apart.

A cited path is a claim about the machine. This checks the claims.

    python3 pathcheck.py                  # the orkestra tree
    python3 pathcheck.py FILE [FILE ...]  # named files
    python3 pathcheck.py --quiet          # exit 1 if anything is stale, no output

Exit status is the number of stale citations, capped at 125, so it can gate a hook.
"""
import os
import re
import sys

HOME = os.path.expanduser("~")
DEFAULT_ROOT = os.path.join(HOME, ".claude", "orkestra")

# A path citation: ~/... or /Users/... or an explicit ./relative, ending at
# whitespace, a closing bracket/quote/backtick, or sentence punctuation.
PATH_RE = re.compile(r"(?<![\w/])(~/[^\s`'\"()\[\],;]+|/Users/[^\s`'\"()\[\],;]+)")

# Trailing characters that are punctuation in prose, never part of a filename.
TRAILING = ".,;:!?)]}>*_"


def clean(raw: str) -> str:
    p = raw
    while p and p[-1] in TRAILING:
        p = p[:-1]
    return p


def resolve(p: str) -> str:
    return os.path.expanduser(p)


def is_glob(p: str) -> bool:
    return any(c in p for c in "*?[")


def is_template(p: str) -> bool:
    """A citation with a placeholder is a shape, not a claim about this machine.

    `~/.claude/orkestra/leads/<title>.md` and `~/agents/{concepts,ideas}` describe
    where a class of file lives; there is nothing on disk for them to match.
    """
    return any(c in p for c in "<>{}")


def check_file(path: str):
    """Yield (lineno, cited_path, reason) for each citation that does not resolve."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except OSError as e:
        yield (0, path, f"unreadable: {e}")
        return

    for n, line in enumerate(lines, 1):
        for raw in PATH_RE.findall(line):
            cited = clean(raw)
            if len(cited) < 4 or is_template(cited):
                continue
            target = resolve(cited)
            if is_glob(cited):
                # Check the deepest non-glob ancestor instead.
                parts = cited.split("/")
                keep = []
                for part in parts:
                    if is_glob(part):
                        break
                    keep.append(part)
                target = resolve("/".join(keep))
                if not keep or os.path.exists(target):
                    continue
                yield (n, cited, f"glob parent missing: {keep[-1]}")
                continue
            if os.path.lexists(target):
                if os.path.islink(target) and not os.path.exists(target):
                    yield (n, cited, f"dangling symlink -> {os.readlink(target)}")
                continue
            yield (n, cited, "does not exist")


def gather(argv):
    if argv:
        return [a for a in argv if os.path.isfile(a)]
    out = []
    for dp, dn, fn in os.walk(DEFAULT_ROOT):
        dn[:] = [d for d in dn if not d.startswith(".")]
        for f in fn:
            if f.endswith((".md", ".tsv", ".txt")):
                out.append(os.path.join(dp, f))
    return sorted(out)


def main():
    args = [a for a in sys.argv[1:] if a != "--quiet"]
    quiet = "--quiet" in sys.argv[1:]

    files = gather(args)
    if not files:
        print("no files to check", file=sys.stderr)
        return 0

    stale = 0
    cited = 0
    for f in files:
        rows = list(check_file(f))
        cited += 1
        if not rows:
            continue
        stale += len(rows)
        if quiet:
            continue
        print(f"\n{f.replace(HOME, '~')}")
        for n, p, why in rows:
            print(f"  {n}: {p}  — {why}")

    if not quiet:
        print(f"\n{len(files)} files, {stale} stale citation(s)")
        if stale:
            print("A cited path is a claim. These claims are false.")
    return min(stale, 125)


if __name__ == "__main__":
    sys.exit(main())
