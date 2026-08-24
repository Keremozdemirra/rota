#!/usr/bin/env python3
"""ltm — long-term memory index and retrieval over the Obsidian-compatible vault.

Python standard library only. SQLite FTS5 (BM25) when available, plain
term-count scoring as fallback. Offline, instant, zero network.

Vault layout (agents root):
    CLAUDE.md          hot tier — always loaded by sessions, keep <= ~100 lines
    DEVAM.md           where work left off
    memory/*.md        warm tier — retrieved by search, chunked by ## heading
    memory/_inbox/     candidate facts awaiting review (NOT indexed)
    memory/_index/     this database (NOT indexed, gitignored)

Usage:
    python3 tools/ltm.py index   [--vault PATH]
    python3 tools/ltm.py search  "query terms" [--k 6] [--max-chars 3200] [--json]
    python3 tools/ltm.py hot     [--vault PATH]
    python3 tools/ltm.py stats   [--vault PATH]

`search` auto-reindexes files whose mtime changed, so calling index first is
optional. Retrieval output cites path » heading for every chunk — answers
built on it are grounded and checkable, never from model memory.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

SCHEMA_VERSION = 2
EXCLUDED_DIRS = {"_index", "_inbox", ".obsidian", ".git"}
_TR_FOLD = str.maketrans("çğıöşüÇĞİÖŞÜI", "cgiosucgiosui")


def fold(text: str) -> str:
    """Turkish-aware fold so 'hafıza' matches ascii 'hafiza' and vice versa."""
    return text.translate(_TR_FOLD).lower()

DEFAULT_VAULT = Path(__file__).resolve().parent.parent.parent  # tools/ -> rota/ -> agents root
# Post-fold forms (see fold() below): "şu" → "su", "için" → "icin".
STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "for", "on", "is", "are",
    "ve", "ile", "bir", "bu", "su", "da", "de", "mi", "ne", "icin", "gibi",
}


def vault_files(vault: Path) -> list[Path]:
    files = [p for p in (vault / "CLAUDE.md", vault / "DEVAM.md") if p.exists()]
    mem = vault / "memory"
    if mem.exists():
        for p in sorted(mem.rglob("*.md")):
            if not any(part in EXCLUDED_DIRS for part in p.relative_to(vault).parts):
                files.append(p)
    return files


def parse_front_matter(text: str) -> tuple[dict, str]:
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            meta = {}
            for line in text[4:end].splitlines():
                if ":" in line:
                    key, _, value = line.partition(":")
                    meta[key.strip().lower()] = value.strip()
            return meta, text[end + 4:]
    return {}, text


def chunk(text: str, fallback_heading: str) -> list[tuple[str, str]]:
    """Split on ## headings. Returns [(heading, body), ...] — Obsidian-friendly."""
    meta, body = parse_front_matter(text)
    tags = meta.get("tags", "")
    parts = re.split(r"^(#{1,3}\s+.+)$", body, flags=re.MULTILINE)
    chunks: list[tuple[str, str]] = []
    heading = meta.get("title", fallback_heading)
    buffer = parts[0]
    for i in range(1, len(parts), 2):
        if buffer.strip():
            chunks.append((heading, buffer.strip()))
        heading = parts[i].lstrip("# ").strip()
        buffer = parts[i + 1] if i + 1 < len(parts) else ""
    if buffer.strip():
        chunks.append((heading, buffer.strip()))
    if tags:  # make front-matter tags searchable by appending to each body
        chunks = [(h, f"{b}\ntags: {tags}") for h, b in chunks]
    return chunks or [(fallback_heading, "")]


class Index:
    def __init__(self, vault: Path):
        self.vault = vault
        db_dir = vault / "memory" / "_index"
        db_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = db_dir / "ltm.sqlite"
        try:
            self.conn = sqlite3.connect(self.db_path)
            self.conn.execute(
                "CREATE TABLE IF NOT EXISTS files (path TEXT PRIMARY KEY, mtime REAL)"
            )
        except sqlite3.OperationalError:
            # Network/FUSE mounts (e.g. the Cowork device bridge) can refuse
            # SQLite locking. The index is derived data, so fall back to a
            # local cache keyed by vault path and rebuild there.
            import hashlib
            cache = Path.home() / ".cache" / "rota-ltm"
            cache.mkdir(parents=True, exist_ok=True)
            self.db_path = cache / (
                hashlib.sha1(str(vault).encode()).hexdigest()[:16] + ".sqlite"
            )
            self.conn = sqlite3.connect(self.db_path)
            self.conn.execute(
                "CREATE TABLE IF NOT EXISTS files (path TEXT PRIMARY KEY, mtime REAL)"
            )
        if self.conn.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
            for table in ("chunks", "files"):
                self.conn.execute(f"DROP TABLE IF EXISTS {table}")
            self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            self.conn.execute(
                "CREATE TABLE files (path TEXT PRIMARY KEY, mtime REAL)"
            )
        try:
            # `folded` is the searchable text (Turkish-folded heading + body);
            # originals are stored unindexed for display.
            self.conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING "
                "fts5(folded, body UNINDEXED, heading UNINDEXED, path UNINDEXED, "
                "tokenize='unicode61')"
            )
            self.fts = True
        except sqlite3.OperationalError:  # sqlite built without FTS5
            self.conn.execute(
                "CREATE TABLE IF NOT EXISTS chunks "
                "(folded TEXT, body TEXT, heading TEXT, path TEXT)"
            )
            self.fts = False

    def refresh(self) -> tuple[int, int]:
        """Sync index with vault by mtime. Returns (files_indexed, files_removed)."""
        seen, updated = set(), 0
        known = dict(self.conn.execute("SELECT path, mtime FROM files"))
        for f in vault_files(self.vault):
            rel = str(f.relative_to(self.vault))
            seen.add(rel)
            mtime = f.stat().st_mtime
            if known.get(rel) == mtime:
                continue
            self.conn.execute("DELETE FROM chunks WHERE path = ?", (rel,))
            for heading, body in chunk(f.read_text(encoding="utf-8"), f.stem):
                if body:
                    self.conn.execute(
                        "INSERT INTO chunks (folded, body, heading, path) "
                        "VALUES (?, ?, ?, ?)",
                        (fold(f"{heading}\n{body}"), body, heading, rel),
                    )
            self.conn.execute(
                "INSERT OR REPLACE INTO files (path, mtime) VALUES (?, ?)", (rel, mtime)
            )
            updated += 1
        removed = 0
        for rel in set(known) - seen:
            self.conn.execute("DELETE FROM chunks WHERE path = ?", (rel,))
            self.conn.execute("DELETE FROM files WHERE path = ?", (rel,))
            removed += 1
        self.conn.commit()
        return updated, removed

    def _tokens(self, query: str) -> list[str]:
        words = re.findall(r"\w{2,}", fold(query))
        return [w for w in words if w not in STOPWORDS] or words

    def search(self, query: str, k: int) -> list[dict]:
        tokens = self._tokens(query)
        if not tokens:
            return []
        if self.fts:
            match = " OR ".join(f'"{t}"' for t in tokens)
            rows = self.conn.execute(
                "SELECT path, heading, body, bm25(chunks) AS score FROM chunks "
                "WHERE chunks MATCH ? ORDER BY score LIMIT ?",
                (match, k),
            ).fetchall()
        else:  # fallback: term-count scoring on the folded text
            rows = []
            for path, heading, body, folded in self.conn.execute(
                "SELECT path, heading, body, folded FROM chunks"
            ):
                score = -sum(folded.count(t) for t in tokens)
                if score < 0:
                    rows.append((path, heading, body, score))
            rows.sort(key=lambda r: r[3])
            rows = rows[:k]
        return [
            {"path": p, "heading": h, "body": b, "score": round(s, 3)}
            for p, h, b, s in rows
        ]


def format_hits(hits: list[dict], max_chars: int) -> str:
    out, used = [], 0
    for i, hit in enumerate(hits, 1):
        body = re.sub(r"\n{3,}", "\n\n", hit["body"]).strip()
        head = f"[{i}] {hit['path']} » {hit['heading']}"
        remaining = max_chars - used - len(head) - 8
        if remaining <= 60:
            break
        if len(body) > remaining:
            body = body[:remaining].rsplit(" ", 1)[0] + " …"
        out.append(f"{head}\n{body}")
        used += len(head) + len(body) + 8
    return "\n\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(prog="ltm")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("index", "search", "hot", "stats"):
        p = sub.add_parser(name)
        p.add_argument("--vault", type=Path, default=DEFAULT_VAULT)
        if name == "search":
            p.add_argument("query")
            p.add_argument("--k", type=int, default=6)
            p.add_argument("--max-chars", type=int, default=3200)
            p.add_argument("--json", action="store_true")
    args = parser.parse_args()
    vault = args.vault.resolve()

    if args.cmd == "hot":
        for name in ("CLAUDE.md", "DEVAM.md"):
            f = vault / name
            if f.exists():
                print(f"=== {name} ===\n{f.read_text(encoding='utf-8')}")
        return 0

    index = Index(vault)
    updated, removed = index.refresh()

    if args.cmd == "index":
        print(f"indexed: {updated} updated, {removed} removed "
              f"({'fts5' if index.fts else 'fallback'})")
        return 0
    if args.cmd == "stats":
        files = index.conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        chunks_n = index.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        print(f"vault: {vault}\ndb: {index.db_path}\n"
              f"files: {files}  chunks: {chunks_n}  "
              f"engine: {'fts5' if index.fts else 'like-fallback'}")
        return 0

    hits = index.search(args.query, args.k)
    if args.json:
        print(json.dumps(hits, ensure_ascii=False, indent=2))
    elif hits:
        print(format_hits(hits, args.max_chars))
    else:
        print("(no memory hits — say so instead of guessing)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
