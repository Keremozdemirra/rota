#!/usr/bin/env python3
"""eval_routes — regression guard for the zero-token routing tier.

Tier-0 is the only tier that costs nothing. Every request it fails to resolve
buys a classifier call, so the hit rate on real phrasing is the single number
that decides what routing costs. Triggers drift as routes are added; this
harness pins the behaviour to `fixtures/routes_eval.yaml` and runs entirely
offline — no SDK, no network, no model call.

    python3 tools/eval_routes.py            # run the eval set
    python3 tools/eval_routes.py --verbose  # also print the passing cases

Exit code 1 on any failure, so it can gate a commit.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml  # noqa: E402

from router import config, triage  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "routes_eval.yaml"


def run(fixture: Path, verbose: bool) -> int:
    registry = config.load()
    cases = yaml.safe_load(fixture.read_text(encoding="utf-8")) or {}
    failures: list[str] = []
    resolved = 0
    total = 0

    for case in cases.get("expect", []):
        total += 1
        route, candidates = triage.tier0(case["q"], registry)
        if route is None:
            ids = [c.id for c in candidates] or ["<none>"]
            failures.append(f"MISS   {case['q']!r} → tier-1 ({', '.join(ids)}), want {case['route']}")
        elif route.id != case["route"]:
            failures.append(f"WRONG  {case['q']!r} → {route.id}, want {case['route']}")
        else:
            resolved += 1
            if verbose:
                print(f"ok     {case['q']!r} → {route.id}")

    for case in cases.get("ambiguous", []):
        total += 1
        route, candidates = triage.tier0(case["q"], registry)
        ids = {c.id for c in candidates}
        if route is not None:
            failures.append(f"NARROW {case['q']!r} → resolved to {route.id}, expected ambiguity")
        elif not set(case["among"]) <= ids:
            missing = ", ".join(sorted(set(case["among"]) - ids))
            failures.append(f"THIN   {case['q']!r} → candidates missing: {missing}")
        elif verbose:
            print(f"ok     {case['q']!r} → tier-1 ({', '.join(sorted(ids))})")

    for query in cases.get("reject", []):
        total += 1
        _, candidates = triage.tier0(query, registry)
        if candidates:
            hits = ", ".join(c.id for c in candidates)
            failures.append(f"FALSE  {query!r} → matched {hits}, expected nothing")
        elif verbose:
            print(f"ok     {query!r} → no match")

    for line in failures:
        print(f"  {line}", file=sys.stderr)
    sys.stderr.flush()

    expected = len(cases.get("expect", []))
    if expected:
        print(f"tier-0 resolved {resolved}/{expected} of the requests that should "
              f"cost zero tokens ({resolved / expected:.0%})")
    if failures:
        print(f"{len(failures)} failure(s) across {total} cases")
        return 1
    print(f"{total} cases pass")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="eval_routes")
    parser.add_argument("--fixture", type=Path, default=FIXTURE)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    return run(args.fixture, args.verbose)


if __name__ == "__main__":
    raise SystemExit(main())
