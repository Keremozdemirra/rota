"""Worker dispatch: one route, its tools, its model, its budget — nothing else.

The worker's system prompt is assembled at dispatch time from three parts,
all pay-per-use:

  1. the worker contract (~120 tokens, below)
  2. the route's skill body, if any — read from disk only now
  3. up to memory.max_chars of vault recall, if the route uses memory

Durable facts leave through `MEMORY+` lines parsed from the result and
appended to memory/_inbox/ with provenance. Workers never write canonical
memory files directly — that gate is what prevents fabricated memory.
"""

from __future__ import annotations

import dataclasses
import re
import subprocess
import sys
from pathlib import Path

from .config import REPO_ROOT, Registry, Route

WORKER_CONTRACT = """You are a specialist worker dispatched by rota for exactly one job.
Rules:
- Do only the routed job. If the request is out of your scope, say so in one line and stop.
- Be terse. No preamble, no recap, no restating the request. Target <= {response_tokens} output tokens.
- Prefer tables for data, prose for reasoning. Never dump raw file contents into the reply.
- If memory context is provided below, treat it as ground truth and cite the path (e.g. memory/kararlar.md) when you rely on it. If it contradicts the request, say so.
- If this session establishes a durable fact (a decision, a preference, a correction), emit one line per fact at the very end, exactly:
  MEMORY+ kind=decision|preference|fact|correction entity=<slug> text="<one verifiable sentence>"
  Only facts stated or confirmed by the user. Never inferred, never guessed.
- Never write secrets (tokens, keys, credentials) to any file or MEMORY+ line."""

MEMORY_RE = re.compile(
    r'^MEMORY\+\s+kind=(?P<kind>decision|preference|fact|correction)\s+'
    r'entity=(?P<entity>[\w\-çğıöşü]+)\s+text="(?P<text>[^"\n]{1,300})"\s*$',
    re.MULTILINE | re.IGNORECASE,
)


@dataclasses.dataclass
class RunResult:
    route_id: str
    tier0_hit: bool
    text: str
    memory_lines: list[dict]
    usage: dict
    cost_usd: float | None


def recall(query_text: str, registry: Registry) -> str:
    """Vault recall via tools/ltm.py in a subprocess (stdlib, offline, fast)."""
    if not query_text.strip():
        return ""
    ltm = REPO_ROOT / "tools" / "ltm.py"
    proc = subprocess.run(
        [sys.executable, str(ltm), "search", query_text,
         "--k", str(registry.memory.get("k", 6)),
         "--max-chars", str(registry.memory.get("max_chars", 3200))],
        capture_output=True, text=True, timeout=20,
    )
    return proc.stdout.strip() if proc.returncode == 0 else ""


def build_system_prompt(route: Route, registry: Registry, memory_block: str) -> str:
    budget = registry.budgets.get(route.budget, {"response_tokens": 900})
    parts = [WORKER_CONTRACT.format(response_tokens=budget.get("response_tokens", 900))]
    for skill in route.skills:
        skill_path = REPO_ROOT / skill
        if skill_path.exists():
            parts.append(f"--- skill: {skill} ---\n{skill_path.read_text(encoding='utf-8')}")
    if memory_block:
        parts.append(f"--- memory (cite paths when used) ---\n{memory_block}")
    return "\n\n".join(parts)


def parse_memory_lines(text: str) -> list[dict]:
    return [m.groupdict() for m in MEMORY_RE.finditer(text or "")]


async def run(request: str, route: Route, registry: Registry,
              tier0_hit: bool, memory_query: str) -> RunResult:
    """Execute the routed job on the Claude Agent SDK."""
    from claude_agent_sdk import ClaudeAgentOptions, query  # imported lazily

    memory_block = recall(memory_query or request, registry) if route.memory else ""
    budget = registry.budgets.get(route.budget, {"max_turns": 8})
    options = ClaudeAgentOptions(
        model=route.model,
        allowed_tools=list(route.tools),
        max_turns=int(budget.get("max_turns", 8)),
        system_prompt=build_system_prompt(route, registry, memory_block),
        cwd=str(registry.vault_path()),
    )

    text, usage, cost = "", {}, None
    async for message in query(prompt=request, options=options):
        result = getattr(message, "result", None)
        if isinstance(result, str):
            text = result
            usage = dict(getattr(message, "usage", {}) or {})
            cost = getattr(message, "total_cost_usd", None)

    return RunResult(
        route_id=route.id,
        tier0_hit=tier0_hit,
        text=text,
        memory_lines=parse_memory_lines(text),
        usage=usage,
        cost_usd=cost,
    )
