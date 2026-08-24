"""Two-tier routing. Tier-0 costs zero tokens; Tier-1 is a single haiku turn.

Tier-0: word-boundary trigger matching against the registry. If exactly one
route matches, dispatch — no model call at all. Clear requests ("cv'yi şu
ilana uyarla") never pay a routing toll.

Tier-1: only for ambiguous requests. The classifier sees the route table
(id + one-line desc, ~200 tokens), not the skills, not the tools, not the
memory. It returns JSON: the route id and, if the route uses memory, a
short retrieval query.
"""

from __future__ import annotations

import json
import re
import unicodedata

from .config import Registry, Route

_WORD = r"(?<![0-9a-zçğıöşü]){}(?![0-9a-zçğıöşü])"


def _fold(text: str) -> str:
    """Lowercase with Turkish-aware folding so 'İlan' matches 'ilan'."""
    text = text.replace("İ", "i").replace("I", "ı")
    return unicodedata.normalize("NFC", text.lower())


def tier0(request: str, registry: Registry) -> tuple[Route | None, list[Route]]:
    """Return (unique_match_or_None, all_candidates)."""
    folded = _fold(request)
    candidates = []
    for route in registry.routes:
        for trig in route.triggers:
            pattern = _WORD.format(re.escape(_fold(trig)))
            if re.search(pattern, folded):
                candidates.append(route)
                break
    unique = candidates[0] if len(candidates) == 1 else None
    return unique, candidates


def build_tier1_prompt(request: str, registry: Registry, candidates: list[Route]) -> str:
    """Compact classifier prompt. Candidates first if Tier-0 found several."""
    pool = candidates if len(candidates) > 1 else list(registry.routes)
    table = "\n".join(f"{r.id}: {r.desc}" for r in pool)
    return (
        "Route this request to exactly one id from the table.\n"
        'Reply ONLY minified JSON: {"route":"<id>","q":"<retrieval query or empty>"}\n'
        "Set q to a 3-8 word memory search query only if the request refers to "
        "past work, decisions, or preferences; else empty string.\n\n"
        f"{table}\n\nRequest: {request.strip()[:600]}"
    )


def parse_tier1_reply(reply: str, registry: Registry) -> tuple[Route, str]:
    """Strict parse with graceful fallback to the registry's fallback route."""
    match = re.search(r"\{.*\}", reply, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            return registry.route(str(data.get("route", ""))), str(data.get("q", ""))[:120]
        except (json.JSONDecodeError, KeyError):
            pass
    return registry.fallback, ""


async def tier1(request: str, registry: Registry, candidates: list[Route]) -> tuple[Route, str]:
    """Single-turn classification on the triage model. Requires claude-agent-sdk."""
    from claude_agent_sdk import ClaudeAgentOptions, query  # imported lazily

    prompt = build_tier1_prompt(request, registry, candidates)
    options = ClaudeAgentOptions(
        model=registry.models.get("triage", "haiku"),
        allowed_tools=[],
        max_turns=1,
        system_prompt="You are a request router. Output JSON only.",
    )
    reply = ""
    async for message in query(prompt=prompt, options=options):
        text = getattr(message, "result", None)
        if isinstance(text, str):
            reply = text
    return parse_tier1_reply(reply, registry)
