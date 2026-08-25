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

# Turkish is agglutinative: "mülakat" surfaces as "mülakatımdan", "risk" as
# "riskleri", "kod inceleme" as "kod incelemesinden". A trailing word boundary
# alone misses every one of those and pushes the request down to the paid tier.
# Triggers of 4+ characters may therefore carry a suffix, restricted to the
# alphabet Turkish inflection actually uses — o, ö, f, h, j, p and v never
# occur in a suffix, which is what keeps "auditorium" out of the audit route
# and "projeksiyon" out of build-project.
_SUFFIX = r"(?<![0-9a-zçğıöşü]){}[aeıiuübcçdgğklmnrsştyz]{{0,8}}(?![0-9a-zçğıöşü])"
_MIN_SUFFIXABLE = 4


# Kerem types without diacritics — "mulakat", not "mülakat"; measured at 100%
# of his messages. Every trigger in registry.yaml carried them, so Tier-0
# matched only spellings he never writes and all 15 routes fell through to the
# paid Tier-1 classifier. Folding both the request and the trigger means either
# spelling resolves on the zero-token path.
_DIACRITICS = str.maketrans("çğıöşüâîû", "cgiosuaiu")


def _fold(text: str) -> str:
    """Lowercase and strip Turkish diacritics, so 'İlan', 'ilan' and 'ilan' agree."""
    text = text.replace("İ", "i").replace("I", "ı")
    text = unicodedata.normalize("NFC", text.lower())
    return text.translate(_DIACRITICS)


def _pattern(trigger: str) -> str:
    """Compile-ready pattern for one trigger. Short triggers stay exact-match."""
    folded = _fold(trigger)
    template = _SUFFIX if len(folded) >= _MIN_SUFFIXABLE else _WORD
    return template.format(re.escape(folded))


def tier0(request: str, registry: Registry) -> tuple[Route | None, list[Route]]:
    """Return (unique_match_or_None, all_candidates).

    A multi-word trigger outranks single-word ones: "niyet mektubunu yaz"
    matches career on "niyet mektubu" and writing on "yaz", and the phrase is
    the stronger signal by a wide margin. Only one phrase match may claim the
    request — two phrases mean the request genuinely spans capabilities, and
    Tier-1 gets it.
    """
    folded = _fold(request)
    candidates: list[Route] = []
    phrase_hits: list[Route] = []
    for route in registry.routes:
        # Every trigger is checked, not just the first hit: a route whose
        # single-word trigger matches early must still get credit for a phrase
        # match later in its list, or precedence would depend on trigger order.
        matched = [t for t in route.triggers if re.search(_pattern(t), folded)]
        if not matched:
            continue
        candidates.append(route)
        if any(" " in t.strip() for t in matched):
            phrase_hits.append(route)
    if len(candidates) == 1:
        return candidates[0], candidates
    if len(phrase_hits) == 1:
        return phrase_hits[0], candidates
    return None, candidates


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
