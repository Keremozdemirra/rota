#!/usr/bin/env python3
"""gen_agents — generate Claude Code subagent files from registry.yaml.

One .md per route into rota/agents/, so the native Claude Code / Cowork
side of the hybrid uses the exact same routing table as the SDK side.
Link or copy rota/agents into ~/.claude/agents to activate.

Generated files are overwritten on every run — edit registry.yaml, not them.

Usage: python3 tools/gen_agents.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from router import config  # noqa: E402

WORKER_BODY = """You are the `{id}` specialist for this ecosystem ({repo}).

Scope: {desc}
Out-of-scope requests get one line ("this belongs to `<route>`") and stop.

Rules:
- Be terse: no preamble, no recap. Target <= {response_tokens} output tokens.
- Tables for data, prose for reasoning. Never dump raw file contents.
- Memory: when the question depends on past decisions or preferences, run
  `python3 {rota_rel}/tools/ltm.py search "<query>"` and cite the returned
  paths. No hits means say "not in memory" — never guess.
- Durable new facts (stated or confirmed by the user only): end your reply with
  MEMORY+ kind=decision|preference|fact|correction entity=<slug> text="<one sentence>"
- Never write secrets to any file or MEMORY+ line.
"""

HEADER = "<!-- GENERATED from registry.yaml by tools/gen_agents.py — edit the registry, not this file -->"


def main() -> int:
    registry = config.load()
    out_dir = REPO_ROOT / "agents"
    out_dir.mkdir(exist_ok=True)
    count = 0
    for route in registry.routes:
        if route.id in ("chat",):  # fallback route needs no subagent file
            continue
        budget = registry.budgets.get(route.budget, {})
        triggers = ", ".join(f'"{t}"' for t in route.triggers[:6])
        description = route.desc.rstrip(".")
        if triggers:
            description += f". Use when the request says: {triggers}."
        frontmatter = [
            "---",
            f"name: {route.id}",
            f"description: {description}",
        ]
        if route.tools:
            frontmatter.append(f"tools: {', '.join(route.tools)}")
        frontmatter += [f"model: {route.model}", "---"]
        body = WORKER_BODY.format(
            id=route.id,
            repo=route.repo or "rota",
            desc=route.desc,
            response_tokens=budget.get("response_tokens", 900),
            rota_rel="rota",
        )
        (out_dir / f"{route.id}.md").write_text(
            "\n".join(frontmatter) + f"\n{HEADER}\n\n{body}", encoding="utf-8"
        )
        count += 1
    print(f"generated {count} agent file(s) in {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
