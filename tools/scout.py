#!/usr/bin/env python3
"""scout — GitHub capability discovery. Proposes; never installs.

Searches GitHub for repositories matching the topics in registry.yaml's
`scout:` section, scores them, and writes one proposal file per new
candidate into rota/proposals/. A proposal contains the evidence, a
suggested registry entry, and an approval checklist. Nothing is cloned,
nothing is executed, nothing touches the registry without a human commit.

Standard library only. GITHUB_TOKEN in env is optional (raises the search
rate limit); it is read from the environment and never written anywhere.

Usage:
    python3 tools/scout.py [--offline] [--limit N]
    python3 tools/scout.py --offline      # fixture run, no network
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PROPOSALS = REPO_ROOT / "proposals"
STATE_PATH = REPO_ROOT / "tools" / "scout_state.json"
FIXTURE = REPO_ROOT / "tools" / "fixtures" / "scout_sample.json"
API = "https://api.github.com/search/repositories"
GOOD_LICENSES = {"mit", "apache-2.0", "bsd-2-clause", "bsd-3-clause", "isc"}


def load_scout_config() -> dict:
    """Read the scout: section from registry.yaml without requiring PyYAML.

    The section is flat enough that a line parser handles it; if PyYAML is
    installed we use it instead.
    """
    text = (REPO_ROOT / "registry.yaml").read_text(encoding="utf-8")
    try:
        import yaml
        return dict(yaml.safe_load(text).get("scout", {}))
    except ImportError:
        pass
    section = re.search(r"^scout:\n((?:[ \t]+.+\n?)+)", text, re.MULTILINE)
    config: dict = {}
    if section:
        for line in section.group(1).splitlines():
            match = re.match(r"\s+(\w+):\s*(.+?)\s*(?:#.*)?$", line)
            if match:
                key, value = match.groups()
                if value.startswith("["):
                    config[key] = [v.strip() for v in value.strip("[]").split(",") if v.strip()]
                else:
                    config[key] = int(value) if value.isdigit() else value
    return config


def fetch(topic: str, config: dict) -> list[dict]:
    since = (dt.date.today() - dt.timedelta(days=int(config.get("max_age_days", 120)))).isoformat()
    q = f"topic:{topic} pushed:>{since} stars:>={int(config.get('min_stars', 30))}"
    url = f"{API}?{urllib.parse.urlencode({'q': q, 'sort': 'stars', 'per_page': config.get('per_topic', 8)})}"
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "rota-scout",
        **({"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}"}
           if os.environ.get("GITHUB_TOKEN") else {}),
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.load(resp).get("items", [])
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"[scout] {topic}: fetch failed ({exc}) — skipping", file=sys.stderr)
        return []


def score(item: dict, gaps: list[str]) -> tuple[float, list[str]]:
    reasons = []
    stars = item.get("stargazers_count", 0)
    s = 2.0 * math.log10(stars + 1)
    reasons.append(f"stars={stars} → {s:.1f}")

    pushed = item.get("pushed_at", "")[:10]
    if pushed:
        age = (dt.date.today() - dt.date.fromisoformat(pushed)).days
        bonus = 2.0 if age <= 30 else (1.0 if age <= 90 else 0.0)
        s += bonus
        reasons.append(f"pushed {age}d ago → +{bonus:.0f}")

    license_key = ((item.get("license") or {}).get("key") or "").lower()
    if license_key in GOOD_LICENSES:
        s += 1.0
        reasons.append(f"license {license_key} → +1")
    else:
        reasons.append(f"license {license_key or 'none'} → +0 (review!)")

    haystack = f"{item.get('name', '')} {item.get('description') or ''}".lower()
    hit_gaps = [g for g in gaps if g.lower() in haystack]
    if hit_gaps:
        s += 1.5
        reasons.append(f"matches gap {', '.join(hit_gaps)} → +1.5")
    return round(s, 2), reasons


def write_proposal(item: dict, total: float, reasons: list[str], topic: str) -> Path:
    PROPOSALS.mkdir(exist_ok=True)
    full_name = item["full_name"]
    slug = re.sub(r"[^a-z0-9-]+", "-", full_name.lower()).strip("-")
    path = PROPOSALS / f"{dt.date.today().isoformat()}-{slug}.md"
    desc = (item.get("description") or "").strip()
    suggested_id = re.sub(r"[^a-z0-9-]+", "-", item["name"].lower()).strip("-")
    path.write_text(f"""# Proposal: {full_name}

**Status: NOT installed. Human approval required before any integration.**

| | |
| --- | --- |
| URL | {item.get('html_url', '')} |
| Description | {desc or '—'} |
| Stars | {item.get('stargazers_count', 0)} |
| Last push | {item.get('pushed_at', '')[:10]} |
| License | {(item.get('license') or {}).get('spdx_id', 'NONE')} |
| Found via | topic:{topic} |
| Score | **{total}** — {'; '.join(reasons)} |

## Suggested registry entry (edit before use)

```yaml
- id: {suggested_id}
  desc: {desc[:70] or 'TODO'}
  triggers: []          # fill with real phrasing, TR + EN
  tools: []             # minimum set only
  model: sonnet
  budget: M
  memory: false
```

## Approval checklist

- [ ] Read the source. All of it, or do not integrate it.
- [ ] License compatible (MIT/Apache preferred).
- [ ] Pin a commit hash, not a branch.
- [ ] It needs no credentials — or credentials stay in env, never in files.
- [ ] It earns its place: which existing route fails without it?

Approve by acting on it; discard by deleting this file. scout will not
re-propose it either way (tracked in tools/scout_state.json).
""", encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(prog="scout")
    parser.add_argument("--offline", action="store_true", help="use bundled fixture, no network")
    parser.add_argument("--limit", type=int, default=5, help="max proposals per run")
    args = parser.parse_args()

    config = load_scout_config()
    gaps = [str(g) for g in config.get("gaps", [])]
    state = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {"seen": []}
    seen = set(state["seen"])

    candidates: list[tuple[float, list[str], dict, str]] = []
    topics = [str(t) for t in config.get("topics", ["claude-skill"])]
    if args.offline:
        items = json.loads(FIXTURE.read_text(encoding="utf-8"))
        for item in items:
            total, reasons = score(item, gaps)
            candidates.append((total, reasons, item, "fixture"))
    else:
        for topic in topics:
            for item in fetch(topic, config):
                total, reasons = score(item, gaps)
                candidates.append((total, reasons, item, topic))

    candidates.sort(key=lambda c: -c[0])
    written = 0
    for total, reasons, item, topic in candidates:
        if written >= args.limit:
            break
        if item["full_name"] in seen:
            continue
        path = write_proposal(item, total, reasons, topic)
        seen.add(item["full_name"])
        written += 1
        print(f"proposal: {path.name}  (score {total})")

    state["seen"] = sorted(seen)
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
    print(f"{written} new proposal(s); {len(seen)} repos tracked; nothing installed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
