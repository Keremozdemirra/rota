"""Shared test helpers: a stand-in for CELLAR built from recorded responses.

The fixtures are real responses from publications.europa.eu recorded on
2026-09-24, trimmed: the consolidated text keeps its header, Articles 1, 2
(seven definitions), 37, 38 and the whole of Annex I; the delegated act keeps
16 of its 57 amendment points; the country act keeps 12 of its 144 names; the
country authority table keeps 24 entries.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import urllib.error
import urllib.parse
from pathlib import Path

from eudr_scope_mcp import cellar, lookup, refresh

FIXTURES = Path(__file__).resolve().parent / "fixtures"
TODAY = "2026-09-24"

DOCS = {
    "02023R1115-20251226": "cons_02023R1115-20251226.xhtml",
    "32023R1115": "act_32023R1115.xhtml",
    "32024R3234": "act_32024R3234.xhtml",
    "32025R2650": "act_32025R2650.xhtml",
    "32026R2102": "act_32026R2102.xhtml",
    "32025R1093": "act_32025R1093.xhtml",
}


def sparql_key(query: str) -> str:
    celex = re.search(r'"([0-9A-Z()\-]+)"\^\^xsd:string', query)
    if "owl:versionInfo" in query:
        return "nal_version"
    if "skosxl:altLabel" in query:
        return "nal_alt"
    if "ISO_3166_1_ALPHA_2" in query:
        return "nal"
    if "expression_uses_language ?lang" in query:
        return "languages_corrigenda"
    if "act_consolidated_consolidates_resource_legal" in query:
        return "consolidated_" + celex.group(1)
    if "resource_legal_amends_resource_legal" in query:
        return "related_" + celex.group(1)
    if "VALUES ?p" in query:
        return "work_" + celex.group(1)
    raise AssertionError(f"unexpected query: {query[:120]}")


class FakeCellar:
    """Replaces cellar._open. `overrides` maps a key ('sparql:work_32023R1115'
    or 'doc:32026R2102') to bytes, an exception, or a callable(key) -> bytes."""

    def __init__(self, overrides=None, edits=None):
        self.overrides = dict(overrides or {})
        self.edits = dict(edits or {})  # key -> function(text) -> text
        self.calls = []

    def __call__(self, request, timeout):
        url = request.full_url
        if url == cellar.SPARQL:
            query = urllib.parse.parse_qs(request.data.decode("utf-8"))["query"][0]
            key = "sparql:" + sparql_key(query)
            path = FIXTURES / f"sparql_{key.split(':', 1)[1]}.json"
            ctype = "application/sparql-results+json"
            final = url
        else:
            m = re.match(r"^https://publications\.europa\.eu/resource/celex/(.+)$", url)
            assert m, url
            celex = urllib.parse.unquote(m.group(1))
            key = "doc:" + celex
            path = FIXTURES / DOCS[celex]
            ctype = "application/xhtml+xml;charset=UTF-8"
            final = f"https://publications.europa.eu/resource/cellar/fixture-{celex}/DOC_1"
        self.calls.append(key)
        override = self.overrides.get(key)
        if callable(override) and not isinstance(override, BaseException):
            override = override(key)
        if isinstance(override, BaseException):
            raise override
        if isinstance(override, bytes):
            return 200, {"Content-Type": ctype}, override, final
        body = path.read_bytes()
        if key in self.edits:
            body = self.edits[key](body.decode("utf-8")).encode("utf-8")
        return 200, {"Content-Type": ctype, "ETag": '"fixture"'}, body, final


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://publications.europa.eu/x", code, "error", {}, None)


class Patched:
    """Context manager: fake network, no retry delay, small country table allowed."""

    def __init__(self, fake: FakeCellar):
        self.fake = fake

    def __enter__(self):
        self.saved = (cellar._open, cellar.RETRY_DELAY, refresh.MIN_COUNTRIES)
        cellar._open = self.fake
        cellar.RETRY_DELAY = 0
        refresh.MIN_COUNTRIES = 10
        return self.fake

    def __exit__(self, *exc):
        cellar._open, cellar.RETRY_DELAY, refresh.MIN_COUNTRIES = self.saved
        return False


def build_snapshot(directory: Path, fake: FakeCellar | None = None) -> dict:
    with Patched(fake or FakeCellar()):
        result = refresh.build(today=TODAY)
    refresh.write(result, directory)
    return result


class SnapshotEnv:
    """Point lookups at a snapshot built from the fixtures; freeze 'today'."""

    def __init__(self, directory: Path, day: str = TODAY):
        self.directory, self.day = directory, day

    def __enter__(self):
        self.saved_env = os.environ.get(lookup.DATA_ENV)
        self.saved_today = lookup.today
        os.environ[lookup.DATA_ENV] = str(self.directory)
        lookup.today = lambda: self.day
        lookup.reset_cache()
        return self

    def __exit__(self, *exc):
        if self.saved_env is None:
            os.environ.pop(lookup.DATA_ENV, None)
        else:
            os.environ[lookup.DATA_ENV] = self.saved_env
        lookup.today = self.saved_today
        lookup.reset_cache()
        return False


_shared = {}


def shared_snapshot() -> Path:
    """One fixture snapshot per test run."""
    if "dir" not in _shared:
        tmp = tempfile.mkdtemp(prefix="eudr-snapshot-")
        build_snapshot(Path(tmp))
        _shared["dir"] = Path(tmp)
    return _shared["dir"]


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))
