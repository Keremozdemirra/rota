#!/usr/bin/env python3
"""Rebuild the eu-taxonomy-mcp snapshot from the EU Taxonomy Navigator's backend.

The Navigator web app reads an undocumented JSON API. Three requests cover it:
/sectors, /activities and /activities/matches/all (every activity's criteria in
one response). If the bulk request fails, the crawler falls back to
/activities/{id}/matches, one activity at a time, with a pause between requests.

Every response is checked before anything is written: a changed or broken
backend ends the run with exit code 2 and leaves the existing snapshot as it was.
The snapshot is written with sorted keys and a fixed order, so the same data
always gives the same bytes. Standard library only.
"""
from __future__ import annotations

import datetime as dt
import email.utils
import hashlib
import http.client
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import eu_taxonomy_mcp as core

USER_AGENT = f"eu-taxonomy-mcp/{core.__version__} (+{core.REPO_URL})"
# Tool's choices, not the source's: the bulk response was 2.4 MB on 2026-09-24, so
# 64 MB means something else is being served; waits after a 429/503 are capped so
# a run cannot hang for hours; requests are never closer together than MIN_DELAY.
MAX_BODY = 64 * 1024 * 1024
RETRY_AFTER_CAP = 120.0
MIN_DELAY = 0.5
SOURCES_MARKER = "<!-- written by eu-taxonomy-mcp refresh -->"

# The only fields that enter the snapshot. Anything else the backend adds later
# (audit fields, user names from the admin side) is dropped here.
ACTIVITY_FIELDS = ("id", "name", "sector", "description", "naceCodes")
MATCH_FIELDS = ("id", "objective", "activityContributionType", "contributionDescription", "activityDescription",
                "criteria", "dnshCriterias")


class RefreshError(Exception):
    """The backend could not be read or no longer looks as expected; nothing was written."""


class _Retryable(Exception):
    def __init__(self, message: str, wait: float | None = None):
        super().__init__(message)
        self.wait = wait


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _retry_after(headers) -> float | None:
    value = (headers or {}).get("Retry-After") if hasattr(headers, "get") else None
    if not value:
        return None
    value = str(value).strip()
    if value.isdigit():
        return min(float(value), RETRY_AFTER_CAP)
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    return max(0.0, min((when - dt.datetime.now(dt.timezone.utc)).total_seconds(), RETRY_AFTER_CAP))


def _error_detail(body: bytes) -> str:
    """The backend's own error code and message, e.g. ACTIVITY_ID_NOT_FOUND, if it sent one."""
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, AttributeError):
        return ""
    if not isinstance(data, dict):
        return ""
    parts = [core.one_line(data.get(k), 80) for k in ("code", "error", "message") if data.get(k)]
    return (" (" + ", ".join(parts) + ")") if parts else ""


class Fetcher:
    """GET requests to the Navigator backend, one at a time, with a pause in between."""

    def __init__(self, base: str = core.API_BASE, opener=None, delay: float = 1.0, timeout: float = 120.0,
                 sleep=time.sleep, log=None):
        self.base = base
        self.opener = opener or urllib.request.urlopen
        self.delay, self.timeout, self.sleep = delay, timeout, sleep
        self.log = log or (lambda msg: print(msg, file=sys.stderr))
        self.requests = 0
        self.bytes = 0
        self.responses: list[dict] = []

    def _get(self, url: str) -> bytes:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        try:
            with self.opener(req, timeout=self.timeout) as r:
                status = getattr(r, "status", None) or r.getcode()
                body = r.read(MAX_BODY + 1)
        except urllib.error.HTTPError as e:
            try:
                body = e.read(64 * 1024) or b""
            except Exception:
                body = b""
            detail = _error_detail(body)
            if e.code in (429, 503):
                raise _Retryable(f"HTTP {e.code}{detail}", _retry_after(e.headers)) from None
            if e.code >= 500:
                raise _Retryable(f"HTTP {e.code}{detail}") from None
            raise RefreshError(f"GET {url}: HTTP {e.code}{detail}") from None
        except (urllib.error.URLError, http.client.HTTPException, OSError) as e:
            # URLError (DNS, refused, TLS), IncompleteRead, RemoteDisconnected, BadStatusLine, timeouts.
            reason = getattr(e, "reason", None) or e
            raise _Retryable(f"{type(e).__name__}: {reason}") from None
        if status != 200:
            raise RefreshError(f"GET {url}: HTTP {status}, expected 200")
        if body is None:
            body = b""
        if len(body) > MAX_BODY:
            raise RefreshError(f"GET {url}: response larger than {MAX_BODY} bytes")
        return body

    def get_json(self, path: str, retries: int = 1):
        url = self.base + path
        attempt = 0
        while True:
            attempt += 1
            if self.requests:
                self.sleep(self.delay)
            self.requests += 1
            try:
                body = self._get(url)
                if not body.strip():
                    raise _Retryable("empty response body")
                try:
                    data = json.loads(body.decode("utf-8"))
                except UnicodeDecodeError:
                    raise _Retryable("response is not UTF-8") from None
                except ValueError as e:
                    raise _Retryable(f"response is not JSON ({e})") from None
                if data is None:
                    raise _Retryable("response is JSON null")
            except _Retryable as e:
                if attempt <= retries:
                    wait = e.wait if e.wait is not None else max(self.delay, 1.0) * 5
                    self.log(f"  GET {path}: {e}; retrying in {wait:.0f} s")
                    self.sleep(wait)
                    continue
                raise RefreshError(f"GET {url}: {e}") from None
            self.bytes += len(body)
            self.responses.append({"path": path, "bytes": len(body), "sha256": _sha256(body)})
            return data


# ------------------------------------------------------------------ checks

def _changed(what: str, detail: str) -> RefreshError:
    return RefreshError(f"{what}: {detail}. The backend may have changed; nothing was written.")


def _id(value, what: str) -> int:
    if not core._is_id(value):
        raise _changed(what, f"missing or invalid id {core.one_line(repr(value), 40)}")
    return value


def _text(value, what: str, required: bool = False):
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise _changed(what, f"expected text, got {type(value).__name__}")
    return value


def _list(value, what: str, allow_empty: bool = False) -> list:
    if not isinstance(value, list):
        raise _changed(what, f"expected a JSON list, got {type(value).__name__}")
    if not value and not allow_empty:
        raise _changed(what, "empty list")
    return value


def check_sectors(data) -> list[dict]:
    out, seen = [], set()
    for s in _list(data, "/sectors"):
        if not isinstance(s, dict):
            raise _changed("/sectors", "an entry is not an object")
        sid = _id(s.get("id"), "/sectors")
        if sid in seen:
            raise _changed("/sectors", f"sector {sid} listed twice")
        seen.add(sid)
        out.append({"id": sid, "name": _text(s.get("name"), f"/sectors {sid} name", True)})
    return out


def check_activities(data, sector_ids: set) -> list[dict]:
    out, seen = [], set()
    for a in _list(data, "/activities"):
        if not isinstance(a, dict):
            raise _changed("/activities", "an entry is not an object")
        aid = _id(a.get("id"), "/activities")
        if aid in seen:
            raise _changed("/activities", f"activity {aid} listed twice")
        seen.add(aid)
        sector = a.get("sector")
        if not isinstance(sector, dict):
            raise _changed(f"/activities {aid}", "no sector")
        sid = _id(sector.get("id"), f"/activities {aid} sector")
        if sid not in sector_ids:
            raise _changed(f"/activities {aid}", f"sector {sid} is not in /sectors")
        codes = a.get("naceCodes")
        codes = [] if codes is None else _list(codes, f"/activities {aid} naceCodes", allow_empty=True)
        if any(not isinstance(c, str) for c in codes):
            raise _changed(f"/activities {aid} naceCodes", "a code is not text")
        out.append({"id": aid, "name": _text(a.get("name"), f"/activities {aid} name", True), "sector_id": sid,
                    "description": _text(a.get("description"), f"/activities {aid} description"),
                    "naceCodes": [c.strip() for c in codes if c.strip()]})
    return out


def _objective(value, what: str) -> dict:
    if not isinstance(value, dict):
        raise _changed(what, "no objective")
    order = value.get("sortOrder")
    if order is not None and (not isinstance(order, int) or isinstance(order, bool)):
        raise _changed(what, "objective sortOrder is not a number")
    return {"id": _id(value.get("id"), what + " objective"),
            "name": _text(value.get("name"), what + " objective name", True),
            "shortName": _text(value.get("shortName"), what + " objective shortName"),
            "sortOrder": order}


def check_matches(data, activity_ids: set, what: str = "/activities/matches/all") -> list[dict]:
    out = []
    for m in _list(data, what, allow_empty=True):
        if not isinstance(m, dict):
            raise _changed(what, "an entry is not an object")
        mid = _id(m.get("id"), what)
        activity = m.get("activity")
        if not isinstance(activity, dict):
            raise _changed(f"{what} match {mid}", "no activity")
        aid = _id(activity.get("id"), f"{what} match {mid} activity")
        if aid not in activity_ids:
            raise _changed(f"{what} match {mid}", f"activity {aid} is not in /activities")
        dnsh = []
        for d in _list(m.get("dnshCriterias") if m.get("dnshCriterias") is not None else [],
                       f"{what} match {mid} dnshCriterias", allow_empty=True):
            if not isinstance(d, dict):
                raise _changed(f"{what} match {mid}", "a DNSH entry is not an object")
            dnsh.append({"objective": _objective(d.get("objective"), f"{what} match {mid} DNSH"),
                         "criteria": _text(d.get("criteria"), f"{what} match {mid} DNSH criteria")})
        out.append({"id": mid, "activity_id": aid, "objective": _objective(m.get("objective"), f"{what} match {mid}"),
                    "activityContributionType": _text(m.get("activityContributionType"), f"{what} match {mid} type"),
                    "contributionDescription": _text(m.get("contributionDescription"), f"{what} match {mid}"),
                    "activityDescription": _text(m.get("activityDescription"), f"{what} match {mid}"),
                    "criteria": _text(m.get("criteria"), f"{what} match {mid} criteria"),
                    "dnshCriterias": dnsh})
    return out


# ------------------------------------------------------------------ snapshot

def build_snapshot(sectors: list[dict], activities: list[dict], matches: list[dict], retrieved: str) -> dict:
    """The snapshot as a plain dict: fixed field set, sorted, text untouched."""
    objectives: dict[int, dict] = {}
    for m in matches:
        for o in [m["objective"]] + [d["objective"] for d in m["dnshCriterias"]]:
            known = objectives.setdefault(o["id"], o)
            if known["name"] != o["name"]:
                raise _changed("objectives", f"objective {o['id']} is called both {known['name']!r} and {o['name']!r}")
    order = {oid: (o["sortOrder"] if o["sortOrder"] is not None else 99, oid) for oid, o in objectives.items()}
    sector_name = {s["id"]: s["name"] for s in sectors}
    by_activity: dict[int, list[dict]] = {}
    seen_pairs, seen_ids = set(), set()
    for m in matches:
        pair = (m["activity_id"], m["objective"]["id"])
        if pair in seen_pairs:
            raise _changed("criteria", f"activity {pair[0]} has two criteria sets for objective {pair[1]}")
        if m["id"] in seen_ids:
            raise _changed("criteria", f"criteria set {m['id']} appears twice")
        seen_pairs.add(pair)
        seen_ids.add(m["id"])
        by_activity.setdefault(m["activity_id"], []).append({
            "id": m["id"], "objective": m["objective"]["id"],
            "activityContributionType": m["activityContributionType"],
            "contributionDescription": m["contributionDescription"],
            "activityDescription": m["activityDescription"],
            "criteria": m["criteria"],
            "dnshCriterias": [{"objective": d["objective"]["id"], "criteria": d["criteria"]}
                              for d in sorted(m["dnshCriterias"], key=lambda d: order[d["objective"]["id"]])]})
    out_activities = []
    for a in sorted(activities, key=lambda a: a["id"]):
        out_activities.append({
            "id": a["id"], "name": a["name"], "sector": {"id": a["sector_id"], "name": sector_name[a["sector_id"]]},
            "description": a["description"], "naceCodes": list(a["naceCodes"]),
            "matches": sorted(by_activity.get(a["id"], []), key=lambda m: (order[m["objective"]], m["id"]))})
    counts = {
        "sectors": len(sectors), "activities": len(activities), "criteria_sets": len(matches),
        "dnsh_entries": sum(len(m["dnshCriterias"]) for m in matches), "objectives": len(objectives),
        "activities_without_nace_codes": sum(1 for a in activities if not a["naceCodes"]),
        "activities_without_criteria": sum(1 for a in activities if a["id"] not in by_activity),
    }
    return {
        "schema": core.SCHEMA,
        "retrieved": retrieved,
        "source": {"name": "EU Taxonomy Navigator", "publisher": "European Commission", "url": core.NAVIGATOR_URL,
                   "api": core.API_BASE, "licence": "CC BY 4.0", "terms_url": core.TERMS_URL},
        "counts": counts,
        "objectives": [dict(objectives[oid]) for oid in sorted(objectives, key=lambda oid: order[oid])],
        "sectors": sorted(({"id": s["id"], "name": s["name"]} for s in sectors), key=lambda s: s["id"]),
        "activities": out_activities,
    }


def serialize(snapshot: dict) -> bytes:
    return (json.dumps(snapshot, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8")


def crawl(fetcher: Fetcher, per_activity: bool = False) -> tuple[list, list, list, str]:
    sectors = check_sectors(fetcher.get_json("/sectors"))
    activities = check_activities(fetcher.get_json("/activities"), {s["id"] for s in sectors})
    ids = [a["id"] for a in activities]
    matches, mode = None, "bulk"
    if not per_activity:
        try:
            matches = check_matches(fetcher.get_json("/activities/matches/all"), set(ids))
        except RefreshError as e:
            fetcher.log(f"  bulk request failed ({e}); fetching criteria one activity at a time")
    if matches is None:
        mode, matches = "per-activity", []
        for aid in ids:
            path = f"/activities/{_id(aid, 'activity')}/matches"
            matches.extend(check_matches(fetcher.get_json(path), {aid}, what=path))
    return sectors, activities, matches, mode


def diff(old: dict | None, new: dict) -> str:
    if not old:
        return "no previous snapshot"
    oa = {a["id"]: a for a in old.get("activities") or [] if isinstance(a, dict) and "id" in a}
    na = {a["id"]: a for a in new["activities"]}
    added, removed = sorted(set(na) - set(oa)), sorted(set(oa) - set(na))

    def fp(a):
        return _sha256(json.dumps(a, sort_keys=True, ensure_ascii=False).encode("utf-8"))

    changed = sorted(i for i in set(na) & set(oa) if fp(na[i]) != fp(oa[i]))
    if not (added or removed or changed):
        return "no change in activities or criteria"
    parts = []
    for label, ids in (("added", added), ("removed", removed), ("changed", changed)):
        if ids:
            shown = ", ".join(str(i) for i in ids[:20]) + (" ..." if len(ids) > 20 else "")
            parts.append(f"{len(ids)} activities {label} ({shown})")
    return "; ".join(parts)


def sources_md(snapshot: dict, payload: bytes, fetcher: Fetcher, mode: str, retrieved_at: str,
               elapsed: float) -> str:
    c = snapshot["counts"]
    rows = []
    per = [r for r in fetcher.responses if r["path"].endswith("/matches") and r["path"] != "/activities/matches/all"]
    for r in fetcher.responses:
        if r not in per:
            rows.append(f"| GET {r['path']} | {r['bytes']:,} | `{r['sha256']}` |")
    if per:
        joined = hashlib.sha256()
        for r in sorted(per, key=lambda r: int(r["path"].split("/")[2])):
            joined.update(bytes.fromhex(r["sha256"]))
        rows.append(f"| GET /activities/{{id}}/matches, {len(per)} requests | {sum(r['bytes'] for r in per):,} | "
                    f"`{joined.hexdigest()}` (SHA-256 over the per-response SHA-256 digests, in id order) |")
    return "\n".join([
        f"# Sources of {core.SNAPSHOT_FILE}",
        "",
        SOURCES_MARKER,
        "",
        "| | |",
        "|---|---|",
        f"| Source | EU Taxonomy Navigator, European Commission (DG FISMA): {core.NAVIGATOR_URL} |",
        f"| Backend | {core.API_BASE}: the undocumented JSON API behind the Navigator web app. No API documentation, "
        f"terms of use or service level were found (checked 2026-09-24); it may change or stop without notice. |",
        f"| Licence | CC BY 4.0, per the European Commission legal notice that the Navigator's footer links to: "
        f"{core.TERMS_URL} |",
        f"| Retrieved | {retrieved_at} |",
        f"| Requests | {fetcher.requests} ({mode}; at least {fetcher.delay:g} s apart), {fetcher.bytes:,} bytes, "
        f"{elapsed:.1f} s |",
        f"| Client | `User-Agent: {USER_AGENT}` |",
        "",
        f"Licence terms, quoted from {core.TERMS_URL}: \"{core.LICENCE_QUOTE}\"",
        "",
        "Attribution line carried by every answer:",
        "",
        f"    Source: European Commission, EU Taxonomy Navigator ({core.NAVIGATOR_URL}), CC BY 4.0, retrieved "
        f"{snapshot['retrieved']}",
        "",
        "## Raw responses",
        "",
        "| Request | Bytes | SHA-256 of the body |",
        "|---|---:|---|",
        *rows,
        "",
        "## Snapshot",
        "",
        "| File | Bytes | SHA-256 |",
        "|---|---:|---|",
        f"| {core.SNAPSHOT_FILE} | {len(payload):,} | `{_sha256(payload)}` |",
        "",
        "| Rows | Count |",
        "|---|---:|",
        f"| sectors | {c['sectors']} |",
        f"| activities | {c['activities']} |",
        f"| criteria sets (one activity, one objective with substantial-contribution criteria) | {c['criteria_sets']} |",
        f"| DNSH entries | {c['dnsh_entries']} |",
        f"| environmental objectives | {c['objectives']} |",
        f"| activities without NACE codes | {c['activities_without_nace_codes']} |",
        f"| activities without criteria | {c['activities_without_criteria']} |",
        "",
        "## What the snapshot changes",
        "",
        f"- Keeps only these fields: activities {', '.join(ACTIVITY_FIELDS)}; criteria sets "
        f"{', '.join(MATCH_FIELDS)}; sectors and objectives as served. Nothing else from the backend is stored.",
        "- Nests each activity's criteria sets under the activity and refers to objectives by id.",
        "- Strips surrounding whitespace from NACE codes (the source serves codes such as ' F42.22'). Other code "
        "quirks ('A2', 'M71.1.2') are stored as served and normalised only when answering.",
        "- Sorts sectors and activities by id, criteria sets and DNSH entries by objective order, and writes keys in "
        "sorted order, so the same data gives the same bytes.",
        "- Changes no text: names, descriptions and criteria are the HTML strings as served.",
        "",
        "## Rebuild",
        "",
        "    python3 eu_taxonomy_mcp.py refresh            # in a source checkout: rewrites data/",
        "    eu-taxonomy-mcp refresh --out DIR             # anywhere else; then --snapshot DIR/taxonomy.json",
        "",
    ])


def _write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def resolve_out(value: str | None) -> Path:
    if value:
        return Path(value)
    if (core.HERE / "pyproject.toml").is_file() and (core.HERE / "data").is_dir():
        return core.HERE / "data"
    raise RefreshError("--out DIR is required outside a source checkout (the bundled snapshot inside an installed "
                       "package is not rewritten); then run with --snapshot DIR/taxonomy.json")


def _guard(out: Path) -> dict | None:
    """The previous snapshot in out, if any; refuses to overwrite files this tool did not write."""
    snap, notes = out / core.SNAPSHOT_FILE, out / "SOURCES.md"
    if notes.exists():
        try:
            ours = SOURCES_MARKER in notes.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            raise RefreshError(f"cannot read {notes}: {e}") from None
        if not ours:
            raise RefreshError(f"{notes} exists and was not written by eu-taxonomy-mcp; choose another --out")
    if not snap.exists():
        return None
    try:
        old = json.loads(snap.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        raise RefreshError(f"{snap} exists and is not an eu-taxonomy-mcp snapshot; choose another --out") from None
    if not isinstance(old, dict) or old.get("schema") != core.SCHEMA:
        raise RefreshError(f"{snap} exists and is not an eu-taxonomy-mcp snapshot; choose another --out")
    return old


def run(out: Path, fetcher: Fetcher, per_activity: bool = False, now=None, clock=time.monotonic) -> dict:
    """Crawl, check, write. Returns a summary; raises RefreshError with nothing written."""
    old = _guard(out)
    started = clock()
    now = now or dt.datetime.now(dt.timezone.utc)
    sectors, activities, matches, mode = crawl(fetcher, per_activity)
    snapshot = build_snapshot(sectors, activities, matches, now.strftime("%Y-%m-%d"))
    payload = serialize(snapshot)
    try:
        core.Taxonomy(json.loads(payload.decode("utf-8")))
    except core.SnapshotError as e:
        raise RefreshError(f"the new snapshot does not load: {e}; nothing was written") from None
    elapsed = clock() - started
    notes = sources_md(snapshot, payload, fetcher, mode, now.strftime("%Y-%m-%dT%H:%M:%SZ"), elapsed)
    try:
        out.mkdir(parents=True, exist_ok=True)
        _write_atomic(out / core.SNAPSHOT_FILE, payload)
        _write_atomic(out / "SOURCES.md", notes.encode("utf-8"))
    except OSError as e:
        raise RefreshError(f"cannot write to {out}: {e}") from None
    return {"requests": fetcher.requests, "bytes": fetcher.bytes, "elapsed": elapsed, "mode": mode,
            "counts": snapshot["counts"], "retrieved": snapshot["retrieved"], "changes": diff(old, snapshot),
            "path": str(out / core.SNAPSHOT_FILE), "sha256": _sha256(payload), "size": len(payload)}


def main(args) -> int:
    delay = max(float(args.delay), MIN_DELAY)
    fetcher = Fetcher(delay=delay, timeout=max(float(args.timeout), 1.0))
    try:
        out = resolve_out(args.out)
        print(f"refresh: {core.API_BASE} -> {out}", file=sys.stderr)
        s = run(out, fetcher, per_activity=args.per_activity)
    except RefreshError as e:
        print(f"eu-taxonomy-mcp refresh: {e}", file=sys.stderr)
        print(f"({fetcher.requests} requests made; the existing snapshot, if any, is unchanged)", file=sys.stderr)
        return 2
    c = s["counts"]
    print(f"refresh: {s['requests']} requests ({s['mode']}), {s['bytes']:,} bytes, {s['elapsed']:.1f} s")
    print(f"snapshot: {c['sectors']} sectors, {c['activities']} activities, {c['criteria_sets']} criteria sets, "
          f"{c['dnsh_entries']} DNSH entries, {c['objectives']} objectives; retrieved {s['retrieved']}")
    print(f"changes against the previous snapshot: {s['changes']}")
    print(f"wrote {s['path']} ({s['size']:,} bytes, sha256 {s['sha256']}) and SOURCES.md")
    return 0


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out")
    p.add_argument("--delay", type=float, default=1.0)
    p.add_argument("--timeout", type=float, default=120.0)
    p.add_argument("--per-activity", action="store_true")
    raise SystemExit(main(p.parse_args()))
