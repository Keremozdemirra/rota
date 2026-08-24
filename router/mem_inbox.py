"""Gated memory writes.

Lesson learned the hard way (see _to_delete-claude-yanlis-hafiza): a model
that writes canonical memory directly will eventually write fiction into it.
So workers append candidate facts HERE, with provenance, and a human (or a
reviewed weekly distill) promotes them into CLAUDE.md / memory/*.md.

Inbox format — one dated file per day, one block per fact:

    - [ ] kind=decision entity=rota text="..." (src: route:github-audit, 2026-08-24)

Checked = promoted. Unchecked = pending. Duplicates are skipped by hash.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re

from .config import Registry

_SECRET_RE = re.compile(
    r"(api[_-]?key|token|secret|password|şifre|bearer\s+[a-z0-9]|ghp_[A-Za-z0-9]|sk-[A-Za-z0-9])",
    re.IGNORECASE,
)


def _fact_hash(kind: str, entity: str, text: str) -> str:
    norm = re.sub(r"\s+", " ", f"{kind}|{entity}|{text}".lower()).strip()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:12]


def commit_lines(lines: list[dict], registry: Registry, source: str) -> int:
    """Append candidate facts to the inbox. Returns how many were written."""
    if not lines:
        return 0
    inbox = registry.inbox_path()
    inbox.mkdir(parents=True, exist_ok=True)
    today = dt.date.today().isoformat()
    target = inbox / f"{today}.md"

    existing = ""
    for f in inbox.glob("*.md"):
        existing += f.read_text(encoding="utf-8")

    written = 0
    out = []
    seen_hashes: set[str] = set()
    for fact in lines:
        kind = fact.get("kind", "fact").lower()
        entity = fact.get("entity", "genel")
        text = (fact.get("text") or "").strip()
        if not text or _SECRET_RE.search(text):
            continue  # never persist secrets, even to the inbox
        h = _fact_hash(kind, entity, text)
        if h in existing or h in seen_hashes:
            continue  # duplicate (across files or within this batch)
        seen_hashes.add(h)
        out.append(
            f'- [ ] `{h}` kind={kind} entity={entity} text="{text}" '
            f"(src: {source}, {today})"
        )
        written += 1

    if out:
        header = "" if target.exists() else f"# Memory inbox — {today}\n\n"
        with target.open("a", encoding="utf-8") as fh:
            fh.write(header + "\n".join(out) + "\n")
    return written
