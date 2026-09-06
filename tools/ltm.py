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
import os
import re
import sqlite3
import sys
import urllib.error
import urllib.request
from array import array
from pathlib import Path

SCHEMA_VERSION = 3
EXCLUDED_DIRS = {"_index", "_inbox", ".obsidian", ".git"}
_TR_FOLD = str.maketrans("çğıöşüÇĞİÖŞÜI", "cgiosucgiosui")


def fold(text: str) -> str:
    """Turkish-aware fold so 'hafıza' matches ascii 'hafiza' and vice versa."""
    return text.translate(_TR_FOLD).lower()

# Semantic layer. Chat here is Turkish and every document is English, so a
# keyword index cannot bridge the query and the text it should match — there
# are no shared tokens to match on. Embeddings do bridge it. Local ollama
# only: no network, no key, and every failure falls back to plain BM25.
EMBED_MODEL = os.environ.get("LTM_EMBED_MODEL", "bge-m3")
EMBED_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
EMBED_TIMEOUT = float(os.environ.get("LTM_EMBED_TIMEOUT", "60"))
RRF_K = 60  # standard reciprocal-rank-fusion damping


def embed(texts: list[str]) -> list[list[float]] | None:
    """Embed via local ollama, L2-normalised. None on any failure — the caller
    then behaves exactly as it did before this layer existed."""
    if not texts or os.environ.get("LTM_NO_EMBED"):
        return None
    payload = json.dumps({"model": EMBED_MODEL, "input": texts}).encode()
    req = urllib.request.Request(
        f"{EMBED_HOST}/api/embed", data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=EMBED_TIMEOUT) as r:
            vectors = json.load(r).get("embeddings")
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
        return None
    if not vectors or len(vectors) != len(texts):
        return None
    out = []
    for v in vectors:
        norm = sum(x * x for x in v) ** 0.5 or 1.0
        out.append([x / norm for x in v])
    return out


def pack(vec: list[float]) -> bytes:
    return array("f", vec).tobytes()


def unpack(blob: bytes) -> array:
    a = array("f")
    a.frombytes(blob)
    return a


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
            for table in ("chunks", "files", "vectors"):
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
        # Keyed on the chunk rowid so a re-indexed file drops its vectors with
        # its chunks; `dim` guards against a model swap producing mixed widths.
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS vectors "
            "(chunk_id INTEGER PRIMARY KEY, path TEXT, dim INTEGER, vec BLOB)"
        )

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
            self.conn.execute("DELETE FROM vectors WHERE path = ?", (rel,))
            pending: list[tuple[int, str]] = []
            for heading, body in chunk(f.read_text(encoding="utf-8"), f.stem):
                if body:
                    cur = self.conn.execute(
                        "INSERT INTO chunks (folded, body, heading, path) "
                        "VALUES (?, ?, ?, ?)",
                        (fold(f"{heading}\n{body}"), body, heading, rel),
                    )
                    pending.append((cur.lastrowid, f"{heading}\n{body}"))
            self._embed_chunks(rel, pending)
            self.conn.execute(
                "INSERT OR REPLACE INTO files (path, mtime) VALUES (?, ?)", (rel, mtime)
            )
            updated += 1
        removed = 0
        for rel in set(known) - seen:
            self.conn.execute("DELETE FROM chunks WHERE path = ?", (rel,))
            self.conn.execute("DELETE FROM vectors WHERE path = ?", (rel,))
            self.conn.execute("DELETE FROM files WHERE path = ?", (rel,))
            removed += 1
        self.conn.commit()
        return updated, removed

    def _embed_chunks(self, rel: str, pending: list[tuple[int, str]]) -> None:
        vectors = embed([text for _, text in pending])
        if not vectors:
            return
        self.conn.executemany(
            "INSERT OR REPLACE INTO vectors (chunk_id, path, dim, vec) "
            "VALUES (?, ?, ?, ?)",
            [(cid, rel, len(v), pack(v)) for (cid, _), v in zip(pending, vectors)],
        )

    def _tokens(self, query: str) -> list[str]:
        words = re.findall(r"\w{2,}", fold(query))
        return [w for w in words if w not in STOPWORDS] or words

    def _lexical(self, query: str, limit: int) -> list[tuple[int, float]]:
        """(chunk_id, score) best-first. Score is BM25 (negative) or -term count."""
        tokens = self._tokens(query)
        if not tokens:
            return []
        if self.fts:
            match = " OR ".join(f'"{t}"' for t in tokens)
            return list(self.conn.execute(
                "SELECT rowid, bm25(chunks) AS score FROM chunks "
                "WHERE chunks MATCH ? ORDER BY score LIMIT ?",
                (match, limit),
            ))
        rows = []
        for rowid, folded in self.conn.execute("SELECT rowid, folded FROM chunks"):
            score = -sum(folded.count(t) for t in tokens)
            if score < 0:
                rows.append((rowid, score))
        rows.sort(key=lambda r: r[1])
        return rows[:limit]

    def _semantic(self, query: str, limit: int) -> list[tuple[int, float]]:
        """(chunk_id, cosine) best-first. Empty when the vector table is cold
        or ollama is unreachable — the lexical side then carries the result."""
        rows = self.conn.execute(
            "SELECT chunk_id, dim, vec FROM vectors"
        ).fetchall()
        if not rows:
            return []
        vectors = embed([query])
        if not vectors:
            return []
        q = vectors[0]
        scored = []
        for chunk_id, dim, blob in rows:
            if dim != len(q):  # model changed since indexing; skip, do not guess
                continue
            v = unpack(blob)
            scored.append((chunk_id, sum(a * b for a, b in zip(q, v))))
        scored.sort(key=lambda r: -r[1])
        return scored[:limit]

    def search(self, query: str, k: int) -> list[dict]:
        pool = max(k * 4, 20)
        lex = self._lexical(query, pool)
        sem = self._semantic(query, pool)
        if not lex and not sem:
            return []
        # Reciprocal rank fusion. BM25 is negative and unbounded, cosine is
        # 0..1; fusing on rank avoids inventing a scale between the two.
        fused: dict[int, float] = {}
        for ranked in (lex, sem):
            for rank, (chunk_id, _) in enumerate(ranked):
                fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank + 1)
        top = sorted(fused.items(), key=lambda kv: -kv[1])[:k]
        if not top:
            return []
        placeholders = ",".join("?" * len(top))
        meta = {
            row[0]: row[1:] for row in self.conn.execute(
                f"SELECT rowid, path, heading, body FROM chunks "
                f"WHERE rowid IN ({placeholders})",
                [cid for cid, _ in top],
            )
        }
        out = []
        for chunk_id, score in top:
            if chunk_id in meta:
                path, heading, body = meta[chunk_id]
                out.append({"path": path, "heading": heading, "body": body,
                            "score": round(score, 5)})
        return out


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
        vecs = index.conn.execute("SELECT COUNT(*) FROM vectors").fetchone()[0]
        print(f"indexed: {updated} updated, {removed} removed "
              f"({'fts5' if index.fts else 'fallback'}), {vecs} vectors")
        return 0
    if args.cmd == "stats":
        files = index.conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        chunks_n = index.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        vecs = index.conn.execute("SELECT COUNT(*) FROM vectors").fetchone()[0]
        engine = "fts5" if index.fts else "like-fallback"
        if vecs:
            # Degrading to BM25 is safe but silent, and a silent downgrade is
            # how you keep using a broken half for weeks. Say it out loud.
            live = embed(["ping"]) is not None
            engine += f" + {EMBED_MODEL} hybrid" if live else \
                f" [!] {vecs} vectors indexed but {EMBED_MODEL} unreachable — " \
                f"keyword-only until ollama is up"
        print(f"vault: {vault}\ndb: {index.db_path}\n"
              f"files: {files}  chunks: {chunks_n}  vectors: {vecs}  "
              f"engine: {engine}")
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
