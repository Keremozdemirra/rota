"""Shared test helpers: fixture loading, a fake HTTP opener, a snapshot built from fixtures.

The fixtures are trimmed real responses from the Navigator backend, recorded on
2026-09-24: seven of the 151 activities and their criteria. Activity 346's
criteria were left out of matches_all.json on purpose, to stand for an activity
the backend returns without criteria.
"""
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest.mock
import urllib.error
from email.message import Message
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
FIXTURES = HERE / "fixtures"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import eu_taxonomy_mcp as core  # noqa: E402
import eu_taxonomy_mcp_refresh as refresh  # noqa: E402

# Nothing under test may look at the real home directory: point HOME at an empty
# scratch directory and make any attempt to resolve it fail loudly.
SCRATCH_HOME = tempfile.mkdtemp(prefix="eu-taxonomy-mcp-home-")
os.environ["HOME"] = SCRATCH_HOME
os.environ.pop(core.SNAPSHOT_ENV, None)
unittest.mock.patch.object(pathlib.Path, "home", side_effect=AssertionError("tests must not read $HOME")).start()

API = core.API_BASE
FIXTURE_IDS = [272, 287, 296, 346, 360, 361, 389]


def raw(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def load(name: str):
    return json.loads(raw(name).decode("utf-8"))


class FakeResponse(io.BytesIO):
    def __init__(self, body: bytes, status: int = 200):
        super().__init__(body)
        self.status = status

    def getcode(self):
        return self.status


def http_error(url: str, code: int, body: bytes = b"", headers=None) -> urllib.error.HTTPError:
    msg = Message()
    for k, v in (headers or {}).items():
        msg[k] = v
    return urllib.error.HTTPError(url, code, "error", msg, io.BytesIO(body))


def per_activity_body(aid: int) -> bytes:
    rows = [m for m in load("matches_all.json") if m["activity"]["id"] == aid]
    return json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class FakeOpener:
    """Answers requests from a route table instead of the network and records every URL.

    A route value is bytes (a 200 body), an exception instance (raised), or a list of
    those, consumed one per request (the last one repeats).
    """

    def __init__(self, routes=None):
        self.routes = dict(routes or {})
        self.urls = []
        self.headers = []

    @classmethod
    def healthy(cls, **overrides):
        routes = {"/sectors": raw("sectors.json"), "/activities": raw("activities.json"),
                  "/activities/matches/all": raw("matches_all.json")}
        for aid in FIXTURE_IDS:
            routes[f"/activities/{aid}/matches"] = per_activity_body(aid)
        routes.update({k.replace("__", "/"): v for k, v in overrides.items()})
        return cls(routes)

    def __call__(self, req, timeout=None):
        url = req.full_url
        self.urls.append(url)
        self.headers.append(dict(req.header_items()))
        assert url.startswith(API), url
        path = url[len(API):]
        answer = self.routes.get(path)
        if isinstance(answer, list):
            answer = answer.pop(0) if len(answer) > 1 else answer[0]
        if answer is None:
            raise http_error(url, 404, raw("error_404.json"))
        if isinstance(answer, urllib.error.HTTPError) and hasattr(answer.fp, "seek"):
            answer.fp.seek(0)  # the same error object may be served twice; a real one is fresh
        if isinstance(answer, BaseException):
            raise answer
        if isinstance(answer, tuple):  # (status, body) for a non-200 success code
            return FakeResponse(answer[1], answer[0])
        return FakeResponse(answer)


def fetcher(opener) -> "refresh.Fetcher":
    sleeps = []
    f = refresh.Fetcher(opener=opener, delay=1.0, timeout=5, sleep=sleeps.append, log=lambda msg: None)
    f.sleeps = sleeps
    return f


def fixture_snapshot(retrieved: str = "2026-09-24") -> dict:
    sectors = refresh.check_sectors(load("sectors.json"))
    activities = refresh.check_activities(load("activities.json"), {s["id"] for s in sectors})
    matches = refresh.check_matches(load("matches_all.json"), {a["id"] for a in activities})
    return refresh.build_snapshot(sectors, activities, matches, retrieved)


class SnapshotCase(unittest.TestCase):
    """Each test reads a snapshot built from the fixtures, in a temporary directory."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.snapshot_path = Path(self.tmp.name) / "taxonomy.json"
        self.snapshot_path.write_bytes(refresh.serialize(fixture_snapshot()))
        core.configure(str(self.snapshot_path))

    def tearDown(self):
        core.configure(None)
        self.tmp.cleanup()
