"""Shared by the tests: recorded CELLAR answers, a stand-in for urlopen, and a home directory that is not yours.

Every test built on `Isolated` runs with HOME, USERPROFILE, APPDATA and XDG_CONFIG_HOME
pointing at a temporary directory, `Path.home()` patched, and `urllib.request.urlopen`
replaced: a request nobody prepared an answer for fails the test instead of reaching
the network.
"""
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
FIXTURES = HERE / "fixtures"
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import csrd_scope  # noqa: E402
import csrd_scope_cellar  # noqa: E402

DATA = csrd_scope.Data()


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def fixture(name: str):
    return json.loads(fixture_bytes(name).decode("utf-8"))


class Response(io.BytesIO):
    def __init__(self, body: bytes, url: str):
        super().__init__(body)
        self._url = url

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def sparql_router(overrides=None):
    """Answer each fixed query with its recorded fixture, chosen by what the query asks for."""
    overrides = overrides or {}

    def route(url):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("query", [""])[0]
        if "expression_uses_language ?l" in q:
            key = "langs"
        elif "resource_legal_corrects_resource_legal" in q:
            key = "after"
        elif "resource_legal_amends_resource_legal" in q:
            key = "amending"
        elif "act_consolidated_consolidates_resource_legal" in q:
            key = "consolidated"
        elif "measure_national_implementing" in q:
            key = "nim"
        elif "resource_legal_in-force" in q:
            key = "acts"
        else:
            return None
        if key in overrides:
            return overrides[key]
        name = {"langs": "sparql-langs.json", "after": "sparql-after.json", "consolidated": "sparql-consolidated.json",
                "amending": "sparql-amending.json",
                "nim": "sparql-nim-trimmed.json", "acts": "sparql-acts.json"}[key]
        return fixture_bytes(name)
    return route


class Web:
    """Stands in for urlopen. `route(url)` returns bytes (served), an int (HTTP error), an
    exception (raised) or None (no answer prepared: the test fails)."""

    def __init__(self, route):
        self.route = route
        self.urls = []

    def __call__(self, req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        self.urls.append(url)
        answer = self.route(url)
        if answer is None:
            raise AssertionError(f"unexpected request: {url[:200]}")
        if isinstance(answer, BaseException):
            raise answer
        if isinstance(answer, int):
            raise urllib.error.HTTPError(url, answer, "status", {"Retry-After": "120"}, None)
        return Response(answer, url)


class Isolated(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        home = self._tmp.name
        env = {"HOME": home, "USERPROFILE": home, "APPDATA": home, "XDG_CONFIG_HOME": home}
        self._env = mock.patch.dict(os.environ, env)
        self._env.start()
        self._home = mock.patch.object(Path, "home", return_value=Path(home))
        self._home.start()
        self.web = Web(lambda url: None)
        self._net = mock.patch("urllib.request.urlopen", self.web)
        self._net.start()

    def tearDown(self):
        self._net.stop()
        self._home.stop()
        self._env.stop()
        self._tmp.cleanup()

    def serve(self, route):
        self.web.route = route


def eu(years, **kw):
    # designated_pie is a fact the user states; cases about an unknown designation pass it explicitly.
    base = {"currency": "EUR", "eu_undertaking": True, "legal_form_in_annex_i_or_ii": True, "designated_pie": False,
            "financial_years": years}
    base.update(kw)
    return base


def non_eu(years, **kw):
    base = {"currency": "EUR", "eu_undertaking": False, "financial_years": years}
    base.update(kw)
    return base


def fy(year, to=None, emp=None, bst=None, **kw):
    d = {"year": year}
    for k, v in (("net_turnover_eur", to), ("average_employees", emp), ("balance_sheet_total_eur", bst)):
        if v is not None:
            d[k] = v
    d.update(kw)
    return d


def statuses(result) -> dict:
    return {f["financial_year"]: f["in_scope"] for f in result["by_financial_year"]}


def question_ids(result) -> set:
    return {q["id"] for q in result["questions_for_counsel"]}
