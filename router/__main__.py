"""CLI entry point.

    python -m router run "cv'yi şu ilana uyarla" [--dry-run] [--route ID] [--json]
    python -m router routes
    python -m router report

--dry-run resolves the route (Tier-0 only, no model call, no SDK needed) and
prints the dispatch plan: route, model, tools, budget, whether memory would
be injected. Use it to test routing for free.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time

from . import config, ledger, triage
from .config import Registry, Route


def _plan(route: Route, registry: Registry, tier0_hit: bool, memory_query: str) -> dict:
    budget = registry.budgets.get(route.budget, {})
    return {
        "route": route.id,
        "tier0": tier0_hit,
        "model": route.model,
        "tools": list(route.tools),
        "budget": {"class": route.budget, **budget},
        "memory": route.memory,
        "memory_query": memory_query or None,
        "skill": route.skill or None,
        "repo": route.repo or None,
    }


async def _resolve(request: str, registry: Registry, forced: str | None,
                   dry_run: bool) -> tuple[Route, bool, str]:
    if forced:
        return registry.route(forced), True, ""
    route, candidates = triage.tier0(request, registry)
    if route is not None:
        return route, True, ""
    if dry_run:
        # No model call in dry-run: report ambiguity, fall back.
        ids = [c.id for c in candidates] or ["<none>"]
        print(f"# tier-0 ambiguous ({', '.join(ids)}) — tier-1 would classify", file=sys.stderr)
        return registry.fallback, False, ""
    route, memory_query = await triage.tier1(request, registry, candidates)
    return route, False, memory_query


async def _run(args: argparse.Namespace) -> int:
    registry = config.load()
    request = args.request.strip()
    if not request:
        print("empty request", file=sys.stderr)
        return 2

    route, tier0_hit, memory_query = await _resolve(request, registry, args.route, args.dry_run)
    plan = _plan(route, registry, tier0_hit, memory_query)

    if args.dry_run:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0

    from . import dispatch  # SDK import happens inside
    from .mem_inbox import commit_lines

    started = time.monotonic()
    result = await dispatch.run(request, route, registry, tier0_hit, memory_query)
    duration = time.monotonic() - started

    ledger.record(result.route_id, result.tier0_hit, result.usage, result.cost_usd, duration)
    committed = commit_lines(result.memory_lines, registry, source=f"route:{result.route_id}")

    if args.json:
        print(json.dumps({"plan": plan, "text": result.text,
                          "memory_committed": committed, "usage": result.usage},
                         ensure_ascii=False, indent=2))
    else:
        print(result.text)
        if committed:
            print(f"\n[rota] {committed} fact(s) → memory/_inbox (awaiting review)", file=sys.stderr)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="rota")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run_p = sub.add_parser("run", help="route and execute a request")
    run_p.add_argument("request")
    run_p.add_argument("--route", help="skip triage, force this route id")
    run_p.add_argument("--dry-run", action="store_true", help="resolve route only, no model call")
    run_p.add_argument("--json", action="store_true")

    sub.add_parser("routes", help="list routes")
    sub.add_parser("report", help="token ledger by route")

    args = parser.parse_args()
    if args.cmd == "routes":
        registry = config.load()
        for r in registry.routes:
            mem = "mem" if r.memory else "   "
            print(f"{r.id:<16} {r.model:<8} {r.budget} {mem}  {r.desc}")
        return 0
    if args.cmd == "report":
        print(ledger.report())
        return 0
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
