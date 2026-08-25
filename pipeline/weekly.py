#!/usr/bin/env python3
"""One autonomous project per week, from a backlog line to a pull request.

The loop:

    pick   the first unchecked BACKLOG.md item in the Queue section
    brief  expand that one line into a real brief using the template
    build  run the `project` workflow — plan, parallel build, integrate, verify
    land   hand the directory to ship.sh, which is the only thing that runs git

The model never runs git. That separation is not stylistic: an agent with git
push is an agent that can rewrite history on a bad turn, and the failure mode
is unrecoverable in a way a bad commit is not. ship.sh is deterministic shell —
read it once, trust it after.

    python -m pipeline.weekly --dry-run      show what would be built
    python -m pipeline.weekly                build it and open the PR
    python -m pipeline.weekly --item 003     build a specific backlog item
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from service import keyvault, runner            # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKLOG = REPO_ROOT / "BACKLOG.md"
PROJECTS = REPO_ROOT / "projects"
TEMPLATE = Path(__file__).resolve().parent / "templates" / "BRIEF.md"
SHIP = Path(__file__).resolve().parent / "ship.sh"
LOG = REPO_ROOT / "ledger" / "weekly.jsonl"

ITEM_RE = re.compile(r"^- \[ \] (?P<id>\d{3}) — (?P<text>.+?)(?=\n- \[|\n\n|\Z)",
                     re.MULTILINE | re.DOTALL)


@dataclass
class Item:
    id: str
    text: str

    @property
    def slug(self) -> str:
        words = re.findall(r"[a-z0-9]+", self.text.lower())[:4]
        return "-".join(words) or "project"

    @property
    def dirname(self) -> str:
        return f"{self.id}-{self.slug}"


def queue() -> list[Item]:
    """Unchecked items, in file order. The Queue is the priority order — if the
    top item is not what should be built this week, edit BACKLOG.md, not this."""
    body = BACKLOG.read_text(encoding="utf-8")
    section = body.split("## Queue", 1)[-1]
    return [Item(m.group("id"), " ".join(m.group("text").split()))
            for m in ITEM_RE.finditer(section)]


def build_brief(item: Item) -> str:
    template = TEMPLATE.read_text(encoding="utf-8")
    return template.replace("{{ID}}", item.id).replace("{{TASK}}", item.text) \
                   .replace("{{DIR}}", f"projects/{item.dirname}")


async def build(item: Item, *, cap_usd: float) -> dict:
    """Run the project workflow with the directory as the working root."""
    target = PROJECTS / item.dirname
    target.mkdir(parents=True, exist_ok=True)
    session = keyvault.owner_session(cap_usd)
    run_id = f"weekly-{item.id}-{int(time.time())}"
    phases: list[dict] = []

    async for event in runner.run_workflow(build_brief(item), "project", session,
                                           run_id=run_id, cwd=target):
        kind = event.get("event")
        if kind == "phase_start":
            print(f"  → {event['label']} ({event['model']})", flush=True)
        elif kind == "fan_out":
            for pkg in event["packages"]:
                print(f"      · {pkg}", flush=True)
        elif kind == "phase_done":
            print(f"  ✓ {event['label']}  {event['duration_s']}s  "
                  f"${event['cost_usd']:.3f}", flush=True)
            phases.append({"phase": event["phase"], "usd": event["cost_usd"],
                           "s": event["duration_s"]})
            (target / f".rota-{event['phase']}.md").write_text(event["text"], encoding="utf-8")
        elif kind == "error":
            print(f"  ✗ {event['kind']}: {event['message']}", file=sys.stderr)
            return {"ok": False, "error": event["message"], "phases": phases}
        elif kind == "run_done":
            return {"ok": True, "cost_usd": event["cost_usd"], "phases": phases,
                    "files": event["files"], "dir": str(target)}
    return {"ok": False, "error": "workflow ended without a result", "phases": phases}


def tick_backlog(item: Item) -> None:
    """Check the item off. Done only after ship.sh succeeds — an item marked
    done for a build that never landed is worse than one left open."""
    body = BACKLOG.read_text(encoding="utf-8")
    today = time.strftime("%Y-%m-%d")
    body = body.replace(f"- [ ] {item.id} — ", f"- [x] {item.id} — ", 1)
    marker = f"- [x] {item.id} — "
    index = body.find(marker)
    if index >= 0:
        end = body.find("\n- [", index + 1)
        end = end if end > 0 else body.find("\n\n", index)
        if end > 0:
            body = body[:end] + f" ({today})" + body[end:]
    BACKLOG.write_text(body, encoding="utf-8")


def ship(item: Item, result: dict) -> int:
    summary = (f"{item.id} — {item.text[:60]}\n\n"
               f"Built by the weekly pipeline: plan → parallel build → integrate → verify.\n"
               f"Cost ${result.get('cost_usd', 0):.2f}. Review .rota-verify.md before merging.")
    proc = subprocess.run(
        ["bash", str(SHIP), item.dirname, summary],
        cwd=str(REPO_ROOT), text=True,
    )
    return proc.returncode


def record(entry: dict) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(prog="weekly")
    parser.add_argument("--item", help="backlog id to build (default: first in Queue)")
    parser.add_argument("--cap", type=float, default=10.0, help="spend cap in USD")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-ship", action="store_true", help="build but do not open a PR")
    args = parser.parse_args()

    items = queue()
    if not items:
        print("backlog Queue is empty — nothing to build", file=sys.stderr)
        return 1
    item = next((i for i in items if i.id == args.item), None) if args.item else items[0]
    if item is None:
        print(f"no unchecked item {args.item!r}", file=sys.stderr)
        return 1

    print(f"[weekly] {item.id} — {item.text}")
    print(f"[weekly] → projects/{item.dirname}  cap ${args.cap:.2f}")
    if args.dry_run:
        print("\n--- brief ---\n" + build_brief(item))
        return 0

    started = time.time()
    result = asyncio.run(build(item, cap_usd=args.cap))
    entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "item": item.id,
             "dir": item.dirname, "s": round(time.time() - started, 1), **result}
    record(entry)

    if not result.get("ok"):
        print(f"[weekly] build failed: {result.get('error')}", file=sys.stderr)
        return 2
    if args.no_ship:
        print(f"[weekly] built in {result['dir']} — not shipped (--no-ship)")
        return 0

    code = ship(item, result)
    if code == 0:
        tick_backlog(item)
        print(f"[weekly] shipped {item.dirname}")
    else:
        print(f"[weekly] ship.sh exited {code}; backlog left unchecked", file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
