"""The parsed indexes, kept in the user's cache directory.

One JSON file per workbook version, named after the workbook's SHA-256, plus a
registry that maps version keys to those files and to the workbook each came
from. Nothing leaves the machine. If the cache cannot be written (read-only home,
full disk), the index still works for the running process and the problem is
reported instead of raised.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import tempfile
from pathlib import Path

from .parse import PARSER_VERSION, MissingFile, parse_workbook, sha256_file
from .xlsx import XlsxError

ENV_FILES = "ESRS_DATAPOINTS_XLSX"
ENV_CACHE = "ESRS_DATAPOINTS_CACHE"
APP = "esrs-datapoints-mcp"


def default_cache_dir() -> Path:
    override = os.environ.get(ENV_CACHE)
    if override:
        return Path(os.path.expanduser(override))
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / APP / "Cache"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / APP
    return Path(os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")) / APP


def env_paths(value=None) -> list:
    """The workbook paths named in ESRS_DATAPOINTS_XLSX, separated like PATH entries."""
    raw = os.environ.get(ENV_FILES, "") if value is None else value
    return [os.path.expanduser(p.strip()) for p in raw.split(os.pathsep) if p.strip()]


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


class Store:
    def __init__(self, directory=None):
        self.dir = Path(directory) if directory else default_cache_dir()
        self.problems: list = []
        self.memory: dict = {}   # key -> index, for indexes the cache could not hold

    # -------------------------------------------------------------- registry

    @property
    def registry_path(self) -> Path:
        return self.dir / "registry.json"

    def stamp(self):
        try:
            st = self.registry_path.stat()
            return (st.st_mtime_ns, st.st_size)
        except OSError:
            return None

    def read_registry(self) -> dict:
        try:
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"format": 1, "entries": []}
        except (OSError, ValueError, UnicodeDecodeError) as e:
            self.problems.append({"path": str(self.registry_path),
                                  "error": f"cache registry unreadable ({type(e).__name__}); starting empty"})
            return {"format": 1, "entries": []}
        if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
            self.problems.append({"path": str(self.registry_path), "error": "cache registry malformed; starting empty"})
            return {"format": 1, "entries": []}
        data["entries"] = [e for e in data["entries"] if isinstance(e, dict) and isinstance(e.get("key"), str)
                           and isinstance(e.get("sha256"), str)]
        return data

    def _write_json(self, path: Path, data) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    # -------------------------------------------------------------- indexing

    def add(self, path, origin: str = "cli") -> dict:
        """Parse a workbook (or reuse its cached index) and register it. Raises XlsxError."""
        p = Path(os.path.expanduser(str(path)))
        if not p.exists():
            raise MissingFile(p)
        if p.is_dir():
            raise XlsxError(f"{p} is a directory, not a workbook")
        reg = self.read_registry()
        resolved = str(p.resolve())
        st = p.stat()
        for e in reg["entries"]:
            if (e.get("path") == resolved and e.get("bytes") == st.st_size and e.get("mtime") == st.st_mtime
                    and e.get("parser") == PARSER_VERSION):
                ix = self.load_entry(e)
                if ix is not None:
                    return ix
        digest = sha256_file(p)
        for e in reg["entries"]:
            if e.get("sha256") == digest and e.get("parser") == PARSER_VERSION:
                ix = self.load_entry(e)
                if ix is not None:
                    self._register(reg, ix, resolved, st, origin, e.get("index"))
                    return ix
        ix = parse_workbook(p)
        taken = {e["key"]: e["sha256"] for e in reg["entries"]}
        taken.update({k: v["file"]["sha256"] for k, v in self.memory.items()})
        if ix["key"] in taken and taken[ix["key"]] != ix["file"]["sha256"]:
            # Two different files with the same layout and date keep both indexes.
            ix["key"] = f"{ix['key']}-{ix['file']['sha256'][:8]}"
        index_name = f"index-{ix['file']['sha256'][:16]}.json"
        try:
            self._write_json(self.dir / index_name, ix)
            self._register(reg, ix, resolved, st, origin, index_name)
        except OSError as e:
            self.memory[ix["key"]] = ix
            self.problems.append({"path": str(self.dir),
                                  "error": f"cannot write the cache ({e.strerror or type(e).__name__}); "
                                           f"{ix['key']} is kept in memory for this process only"})
        return ix

    def _register(self, reg: dict, ix: dict, resolved: str, st, origin: str, index_name: str) -> None:
        entries = [e for e in reg["entries"] if e["key"] != ix["key"] and e.get("path") != resolved]
        entries.append({"key": ix["key"], "sha256": ix["file"]["sha256"], "path": resolved,
                        "bytes": st.st_size, "mtime": st.st_mtime, "index": index_name,
                        "parser": PARSER_VERSION, "origin": origin, "indexed_at": _now()})
        reg["entries"] = sorted(entries, key=lambda e: e["key"])
        self._write_json(self.registry_path, reg)

    def load_entry(self, entry: dict):
        name = entry.get("index") or ""
        if not name.startswith("index-") or "/" in name or "\\" in name:
            return None
        try:
            ix = json.loads((self.dir / name).read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            return None
        if (not isinstance(ix, dict) or not isinstance(ix.get("datapoints"), list)
                or ix.get("file", {}).get("sha256") != entry.get("sha256")):
            return None
        ix["key"] = entry["key"]
        ix["origin"] = entry.get("origin")
        return ix

    def load(self, env_value=None) -> list:
        """Every usable index: the workbooks named in ESRS_DATAPOINTS_XLSX first, then the cache."""
        self.problems = [p for p in self.problems if "cannot write the cache" in p.get("error", "")]
        for path in env_paths(env_value):
            try:
                self.add(path, origin="env")
            except XlsxError as e:
                self.problems.append({"path": path, "error": str(e)})
            except OSError as e:
                self.problems.append({"path": path, "error": f"cannot read {path} ({e.strerror or type(e).__name__})"})
        out = {}
        for e in self.read_registry()["entries"]:
            ix = self.load_entry(e)
            if ix is None:
                ix = self._reparse(e)
            if ix is not None:
                ix["source_present"] = os.path.exists(e.get("path") or "")
                out[ix["key"]] = ix
        for k, ix in self.memory.items():
            out.setdefault(k, ix)
        return sorted(out.values(), key=lambda ix: (ix.get("list_date") or "", ix["key"]))

    def _reparse(self, entry: dict):
        path = entry.get("path") or ""
        if not os.path.exists(path):
            self.problems.append({"path": path, "error": f"cached index for {entry['key']} is missing or damaged "
                                                         "and the workbook is no longer at this path"})
            return None
        try:
            return self.add(path, origin=entry.get("origin") or "cli")
        except (XlsxError, OSError) as e:
            self.problems.append({"path": path, "error": str(e)})
            return None

    def forget(self, key=None) -> list:
        """Remove one version (or all, key=None) from the cache. Returns the removed keys."""
        reg = self.read_registry()
        keep, gone = [], []
        for e in reg["entries"]:
            if key is None or e["key"] == key:
                gone.append(e["key"])
                name = e.get("index") or ""
                if name.startswith("index-") and "/" not in name and "\\" not in name:
                    try:
                        (self.dir / name).unlink()
                    except OSError:
                        pass
            else:
                keep.append(e)
        if gone:
            reg["entries"] = keep
            self._write_json(self.registry_path, reg)
        for k in list(self.memory):
            if key is None or k == key:
                gone.append(k)
                del self.memory[k]
        return gone
