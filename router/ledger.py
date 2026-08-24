"""Token ledger. Measure or it didn't happen.

Every dispatch appends one JSONL row. `python -m router report` aggregates
by route so the expensive 20% is visible and optimizable.
"""

from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict

from .config import LEDGER_PATH


def record(route_id: str, tier0_hit: bool, usage: dict, cost_usd: float | None,
           duration_s: float) -> None:
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "route": route_id,
        "tier0": tier0_hit,
        "in": int(usage.get("input_tokens", 0) or 0),
        "out": int(usage.get("output_tokens", 0) or 0),
        "cache_read": int(usage.get("cache_read_input_tokens", 0) or 0),
        "cost_usd": round(cost_usd, 6) if isinstance(cost_usd, (int, float)) else None,
        "s": round(duration_s, 2),
    }
    with LEDGER_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def report() -> str:
    if not LEDGER_PATH.exists():
        return "ledger empty — nothing dispatched yet"
    agg: dict[str, dict] = defaultdict(lambda: {"n": 0, "t0": 0, "in": 0, "out": 0, "cost": 0.0})
    for line in LEDGER_PATH.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        a = agg[row.get("route", "?")]
        a["n"] += 1
        a["t0"] += 1 if row.get("tier0") else 0
        a["in"] += row.get("in", 0) or 0
        a["out"] += row.get("out", 0) or 0
        a["cost"] += row.get("cost_usd") or 0.0

    header = f"{'route':<16}{'runs':>6}{'t0%':>6}{'in_tok':>10}{'out_tok':>10}{'usd':>9}"
    lines = [header, "-" * len(header)]
    for route, a in sorted(agg.items(), key=lambda kv: -kv[1]["cost"]):
        t0 = 100 * a["t0"] // a["n"] if a["n"] else 0
        lines.append(f"{route:<16}{a['n']:>6}{t0:>5}%{a['in']:>10}{a['out']:>10}{a['cost']:>9.4f}")
    return "\n".join(lines)
