#!/usr/bin/env python3
"""Rebuild the eu-taxonomy-mcp data files from their sources.

taxonomy.json comes from the EU Taxonomy Navigator's undocumented JSON API. Three
requests cover it: /sectors, /activities and /activities/matches/all (every
activity's criteria in one response). If the bulk request fails or lists nothing,
the crawler falls back to /activities/{id}/matches, one activity at a time.

nace.json comes from the Official Journal: the NACE Rev. 2 table in Annex I to
Regulation (EC) No 1893/2006 and the NACE Rev. 2.1 table in the Annex to Delegated
Regulation (EU) 2023/137, read from the Publications Office's Cellar over https.

Every response is checked before anything is written. A broken or changed source,
an empty result, or a result less than half the size of the previous one ends the
run with exit code 2 and leaves the existing files as they were. Output is written
with sorted keys and a fixed order, so the same data always gives the same bytes.
Standard library only.
"""
from __future__ import annotations

import datetime as dt
import email.utils
import hashlib
import html.parser
import http.client
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import eu_taxonomy_mcp as core

USER_AGENT = f"eu-taxonomy-mcp/{core.__version__} (+{core.REPO_URL})"
CELLAR = "https://publications.europa.eu/resource/celex/"
# Tool's choices, not the sources': the bulk response was 2.4 MB on 2026-09-24, so
# 64 MB means something else is being served; waits after a 429/503 are capped so a
# run cannot hang for hours; requests are never closer together than MIN_DELAY; a
# rebuild that shrinks the data to less than half is refused as a probable fault.
MAX_BODY = 64 * 1024 * 1024
RETRY_AFTER_CAP = 120.0
MIN_DELAY = 0.5
SHRINK_LIMIT = 0.5
# Tool's choice: the smallest NACE table accepted as complete. The Official Journal
# gives 21/88/272/615 (Rev. 2) and 22/87/287/651 (Rev. 2.1), counted 2026-09-24.
NACE_MINIMUM = {"sections": 20, "divisions": 80, "groups": 250, "classes": 600}
SOURCES_MARKER = "<!-- written by eu-taxonomy-mcp refresh -->"

# The only fields that enter the snapshot. Anything else the backend adds later
# (audit fields, user names from the admin side) is dropped here.
ACTIVITY_FIELDS = ("id", "name", "sector", "description", "naceCodes")
MATCH_FIELDS = ("id", "objective", "activityContributionType", "contributionDescription", "activityDescription",
                "criteria", "dnshCriterias")


class RefreshError(Exception):
    """A source could not be read or no longer looks as expected; nothing was written."""


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
    if re.fullmatch(r"[0-9]{1,10}", value):
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


class _HttpsOnlyRedirects(urllib.request.HTTPRedirectHandler):
    """Follow redirects over https only.

    Cellar answers an https request for a CELEX number with a redirect to a plain
    http document URL; the same document is served over https, so that one host is
    upgraded, and a redirect to http anywhere else is refused.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parts = urllib.parse.urlsplit(newurl)
        if parts.scheme == "http" and parts.hostname == "publications.europa.eu":
            newurl = urllib.parse.urlunsplit(("https",) + tuple(parts[1:]))
        elif parts.scheme != "https":
            raise urllib.error.HTTPError(req.full_url, code, f"refused redirect to {parts.scheme}", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def default_opener():
    return urllib.request.build_opener(_HttpsOnlyRedirects()).open


class Fetcher:
    """GET requests, one at a time, with a pause in between."""

    def __init__(self, base: str = core.API_BASE, opener=None, delay: float = 1.0, timeout: float = 120.0,
                 sleep=None, log=None):
        self.base = base
        self.opener = opener or default_opener()
        self.delay, self.timeout = delay, timeout
        self.sleep = sleep or time.sleep
        self.log = log or (lambda msg: print(msg, file=sys.stderr))
        self.requests = 0
        self.bytes = 0
        self.responses: list[dict] = []

    def _get(self, url: str, accept: str) -> bytes:
        headers = {"User-Agent": USER_AGENT, "Accept": accept, "Accept-Language": "eng"}
        req = urllib.request.Request(url, headers=headers)
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
            raise RefreshError(f"GET {url}: HTTP {e.code}{detail or ' ' + core.one_line(e.reason, 80)}") from None
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

    def _fetch(self, url: str, record: str, accept: str, parse, retries: int):
        attempt = 0
        while True:
            attempt += 1
            if self.requests:
                self.sleep(self.delay)
            self.requests += 1
            try:
                body = self._get(url, accept)
                if not body.strip():
                    raise _Retryable("empty response body")
                try:
                    text = body.decode("utf-8")
                except UnicodeDecodeError:
                    raise _Retryable("response is not UTF-8") from None
                data = parse(text)
            except _Retryable as e:
                if attempt <= retries:
                    wait = e.wait if e.wait is not None else max(self.delay, 1.0) * 5
                    self.log(f"  GET {record}: {e}; retrying in {wait:.0f} s")
                    self.sleep(wait)
                    continue
                raise RefreshError(f"GET {url}: {e}") from None
            self.bytes += len(body)
            self.responses.append({"path": record, "bytes": len(body), "sha256": _sha256(body)})
            return data

    def get_json(self, path: str, retries: int = 1):
        def parse(text):
            try:
                data = json.loads(text)
            except ValueError as e:
                raise _Retryable(f"response is not JSON ({e})") from None
            if data is None:
                raise _Retryable("response is JSON null")
            return data
        return self._fetch(self.base + path, path, "application/json", parse, retries)

    def get_act(self, celex: str, retries: int = 1) -> str:
        """The English XHTML of one act from Cellar; celex must be one of the fixed identifiers."""
        if not re.fullmatch(r"3[0-9]{4}[A-Z][0-9]{4}", celex):
            raise RefreshError(f"refusing to request {celex!r}: not a CELEX number")

        def parse(text):
            if "oj-doc-ti" not in text:
                raise _Retryable("response is not an Official Journal document")
            return text
        return self._fetch(CELLAR + celex, f"CELEX {celex}", "application/xhtml+xml;q=1, text/html;q=0.9", parse,
                           retries)


# ------------------------------------------------------------------ checks

def _changed(what: str, detail: str) -> RefreshError:
    return RefreshError(f"{what}: {detail}. The source may have changed; nothing was written.")


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
    # An empty list is valid here: one activity can have no criteria. Whether the
    # whole result is too small is decided in run(), on the totals.
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


def serialize(data: dict) -> bytes:
    return (json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8")


def crawl(fetcher: Fetcher, per_activity: bool = False) -> tuple[list, list, list, str]:
    sectors = check_sectors(fetcher.get_json("/sectors"))
    activities = check_activities(fetcher.get_json("/activities"), {s["id"] for s in sectors})
    ids = [a["id"] for a in activities]
    matches, mode = None, "bulk"
    if not per_activity:
        try:
            matches = check_matches(fetcher.get_json("/activities/matches/all"), set(ids))
            if not matches:
                raise RefreshError("GET /activities/matches/all: the bulk response lists no criteria")
        except RefreshError as e:
            fetcher.log(f"  bulk request failed ({e}); fetching criteria one activity at a time")
            matches = None
    if matches is None:
        mode, matches = "per-activity", []
        for aid in ids:
            path = f"/activities/{_id(aid, 'activity')}/matches"
            matches.extend(check_matches(fetcher.get_json(path), {aid}, what=path))
    return sectors, activities, matches, mode


def check_not_shrunk(new: dict, old: dict | None, keys: dict, where: Path) -> None:
    """Refuse an empty result, or one less than half of the previous file's size (tool's choice)."""
    before = (old or {}).get("counts") or {}
    for key, label in keys.items():
        if not new.get(key):
            raise RefreshError(f"the source returned no {label}; nothing was written, and {where} is kept")
        prev = before.get(key)
        if isinstance(prev, int) and prev > 0 and new[key] < prev * SHRINK_LIMIT:
            raise RefreshError(f"the source returned {new[key]} {label}, fewer than half of the {prev} in the previous "
                               f"file; nothing was written, and {where} is kept. If the drop is real, move that file "
                               f"away and run refresh again.")


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


# ------------------------------------------------------------------ NACE

class _AnnexRows(html.parser.HTMLParser):
    """Table rows between one annex heading of an Official Journal act and the next heading."""

    def __init__(self, heading: str):
        super().__init__(convert_charrefs=True)
        self.heading = heading
        self.state = "before"
        self.in_title, self.title = False, []
        self.rows: list[list[str]] = []
        self.row: list[str] | None = None
        self.cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "p" and "oj-doc-ti" in (a.get("class") or ""):
            self.in_title, self.title = True, []
        elif self.state == "inside" and tag == "tr":
            self.row = []
        elif self.state == "inside" and tag in ("td", "th") and self.row is not None:
            self.cell = []

    def handle_endtag(self, tag):
        if tag == "p" and self.in_title:
            self.in_title = False
            title = re.sub(r"\s+", " ", "".join(self.title)).strip()
            if self.state == "before" and title == self.heading:
                self.state = "inside"
            elif self.state == "inside" and title.startswith("ANNEX") and title != self.heading:
                self.state = "after"
        elif tag in ("td", "th") and self.cell is not None and self.row is not None:
            self.row.append(re.sub(r"\s+", " ", "".join(self.cell)).strip())
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if self.state == "inside" and any(self.row):
                self.rows.append(self.row)
            self.row = None

    def handle_data(self, data):
        if self.in_title:
            self.title.append(data)
        if self.cell is not None:
            self.cell.append(data)


def parse_nace_annex(xhtml: str, heading: str, rev: str) -> dict:
    """Sections, division-to-section map and titles from one NACE annex table."""
    parser = _AnnexRows(heading)
    parser.feed(xhtml)
    parser.close()
    what = f"NACE Rev. {rev} annex"
    if parser.state == "before":
        raise _changed(what, f"no heading {heading!r} in the document")
    sections, divisions, titles, current = {}, {}, {}, None
    for row in parser.rows:
        text = " ".join(c for c in row if c)
        m = re.fullmatch(r"SECTION ([A-Z]) [\u2014\u2013-] (.+)", text)
        if m:
            current = m.group(1)
            if current in sections:
                raise _changed(what, f"section {current} appears twice")
            sections[current] = m.group(2).strip()
            continue
        code = next((c for c in row[:3] if re.fullmatch(r"\d{2}(\.\d{1,2})?", c)), None)
        if not code:
            continue
        title = row[3] if len(row) > 3 else ""
        if not title:
            raise _changed(what, f"code {code} has no title")
        if code in titles:
            raise _changed(what, f"code {code} appears twice")
        if len(code) == 2:
            if not current:
                raise _changed(what, f"division {code} comes before any section")
            divisions[code] = current
        elif code[:len(code) - 1].rstrip(".") not in titles:
            raise _changed(what, f"code {code} comes before its parent")
        titles[code] = title
    return {"sections": sections, "divisions": divisions, "titles": titles}


def nace_counts(table: dict) -> dict:
    return {"sections": len(table["sections"]), "divisions": len(table["divisions"]),
            "groups": sum(1 for c in table["titles"] if len(c) == 4),
            "classes": sum(1 for c in table["titles"] if len(c) == 5)}


def build_nace(documents: dict, retrieved: str, minimum: dict | None = None) -> dict:
    """nace.json from the two Official Journal documents, keyed by revision ("2", "2.1")."""
    minimum = NACE_MINIMUM if minimum is None else minimum
    revisions = {}
    for rev, xhtml in documents.items():
        act = core.NACE_ACTS[rev]
        heading = "ANNEX I" if act["annex"] == "Annex I" else "ANNEX"
        table = parse_nace_annex(xhtml, heading, rev)
        counts = nace_counts(table)
        short = [f"{counts[k]} {k}" for k in minimum if counts[k] < minimum[k]]
        if short:
            raise _changed(f"NACE Rev. {rev} annex", "only " + ", ".join(short) + " found")
        revisions[rev] = dict(act, **table)
    return {"schema": core.NACE_SCHEMA, "retrieved": retrieved, "revisions": revisions}


# ------------------------------------------------------------------ SOURCES.md

def _block_markers(name: str) -> tuple[str, str]:
    return f"<!-- begin {name} -->", f"<!-- end {name} -->"


def _existing_block(text: str, name: str) -> str | None:
    begin, end = _block_markers(name)
    m = re.search(re.escape(begin) + r"\n(.*?)\n" + re.escape(end), text, re.S)
    return m.group(1) if m else None


def _responses_table(fetcher: Fetcher) -> list[str]:
    rows = []
    per = [r for r in fetcher.responses if re.fullmatch(r"/activities/\d+/matches", r["path"])]
    for r in fetcher.responses:
        if r not in per:
            rows.append(f"| GET {r['path']} | {r['bytes']:,} | `{r['sha256']}` |")
    if per:
        joined = hashlib.sha256()
        for r in sorted(per, key=lambda r: int(r["path"].split("/")[2])):
            joined.update(bytes.fromhex(r["sha256"]))
        rows.append(f"| GET /activities/{{id}}/matches, {len(per)} requests | {sum(r['bytes'] for r in per):,} | "
                    f"`{joined.hexdigest()}` (SHA-256 over the per-response SHA-256 digests, in id order) |")
    return ["| Request | Bytes | SHA-256 of the body |", "|---|---:|---|", *rows]


def taxonomy_block(snapshot: dict, payload: bytes, fetcher: Fetcher, mode: str, retrieved_at: str,
                   elapsed: float) -> str:
    c = snapshot["counts"]
    return "\n".join([
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
        f"Licence terms, quoted from {core.TERMS_URL} (read {core.READ_ON}): \"{core.LICENCE_QUOTE}\"",
        "",
        "Attribution line carried by every answer:",
        "",
        f"    Source: European Commission, EU Taxonomy Navigator ({core.NAVIGATOR_URL}), CC BY 4.0, retrieved "
        f"{snapshot['retrieved']}",
        "",
        "Raw responses:",
        "",
        *_responses_table(fetcher),
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
        "What the snapshot changes:",
        "",
        f"- Keeps only these fields: activities {', '.join(ACTIVITY_FIELDS)}; criteria sets "
        f"{', '.join(MATCH_FIELDS)}; sectors and objectives as served. Nothing else from the backend is stored.",
        "- Nests each activity's criteria sets under the activity and refers to objectives by id.",
        "- Strips surrounding whitespace from NACE codes (the source serves codes such as ' F42.22'). Other code "
        "forms ('A2', 'M71.1.2', 'Q84') are stored as served and read against NACE Rev. 2 only when answering.",
        "- Sorts sectors and activities by id, criteria sets and DNSH entries by objective order, and writes keys in "
        "sorted order, so the same data gives the same bytes.",
        "- Changes no text: names, descriptions and criteria are the HTML strings as served.",
        "",
        "Rebuild: `python3 eu_taxonomy_mcp.py refresh` in a source checkout (rewrites data/), or `eu-taxonomy-mcp "
        "refresh --out DIR` anywhere else, then `--snapshot DIR/taxonomy.json`. A result with no criteria sets, or "
        "with fewer than half the activities or criteria sets of the previous snapshot, is refused.",
    ])


def nace_block(data: dict, payload: bytes, fetcher: Fetcher, retrieved_at: str, elapsed: float) -> str:
    lines = [
        "| | |",
        "|---|---|",
    ]
    for rev in ("2", "2.1"):
        act = core.NACE_ACTS[rev]
        lines.append(f"| {act['name']} | {act['annex']} to {act['act']}, CELEX {act['celex']}, {act['eli']} "
                     f"(English text from Cellar, {CELLAR}{act['celex']}) |")
    lines += [
        "| Terms | Official Journal text, re-used under Commission Decision 2011/833/EU; see \"Texts of EU law\" "
        "below. Not labelled CC BY. |",
        f"| Retrieved | {retrieved_at} |",
        f"| Requests | {fetcher.requests} (at least {fetcher.delay:g} s apart), {fetcher.bytes:,} bytes, "
        f"{elapsed:.1f} s |",
        "",
        "Raw responses:",
        "",
        *_responses_table(fetcher),
        "",
        "| File | Bytes | SHA-256 |",
        "|---|---:|---|",
        f"| {core.NACE_FILE} | {len(payload):,} | `{_sha256(payload)}` |",
        "",
        "| Revision | Sections | Divisions | Groups | Classes |",
        "|---|---:|---:|---:|---:|",
    ]
    for rev in ("2", "2.1"):
        c = nace_counts(data["revisions"][rev])
        lines.append(f"| NACE Rev. {rev} | {c['sections']} | {c['divisions']} | {c['groups']} | {c['classes']} |")
    lines += [
        "",
        "What the file changes: nothing in the titles. It keeps the section letters and titles, which section each "
        "division belongs to, and the title of every division, group and class, as the annex tables give them; the "
        "ISIC Rev. 4 column of Regulation (EC) No 1893/2006 is left out.",
        "",
        "Rebuild: `python3 eu_taxonomy_mcp.py refresh --nace` (two requests to Cellar).",
    ]
    return "\n".join(lines)


def eu_law_section() -> str:
    d = core.DECISION_2011_833
    acts = [f"| {a['act']} | {a['celex']} | {a['eli']} |" for a in core.LEGAL_ACTS]
    acts += [f"| {a['act']} ({a['name']}) | {a['celex']} | {a['eli']} |" for a in core.NACE_ACTS.values()]
    return "\n".join([
        "The tool quotes titles and passages of EU acts (in `sources()` and the notes) and the NACE titles "
        "(`nace.json`) from the Official Journal, and one passage from a EUR-Lex consolidated text. Every answer "
        "that carries them says so in `attribution_eu_law` or `attribution_consolidated_text`.",
        "",
        f"EUR-Lex legal notice, {core.EURLEX_NOTICE_URL}, read {core.READ_ON}:",
        "",
        f"> {core.EURLEX_REUSE_QUOTE}",
        "",
        f"> {core.EURLEX_CC_QUOTE}",
        "",
        f"> {core.EURLEX_AUTHENTIC_QUOTE}",
        "",
        f"{d['act']} ({d['oj']}, CELEX {d['celex']}), read in Cellar on {core.READ_ON}:",
        "",
        f"> Article 4: {d['article_4']}",
        "",
        f"> Article 6(2): {d['article_6_2']}",
        "",
        "So: Official Journal texts are re-used under Decision 2011/833/EU, with the source acknowledged and the "
        "meaning not distorted; they are not labelled CC BY 4.0. The passage taken from the consolidated text of "
        "Delegated Regulation (EU) 2021/2139 (CELEX 02021R2139-20260101) is CC BY 4.0. The Navigator's own content "
        "is CC BY 4.0 under the Commission legal notice quoted above.",
        "",
        f"Acts read (English text from Cellar; titles, dates and ELI from the Publications Office SPARQL endpoint), "
        f"{core.READ_ON}:",
        "",
        "| Act | CELEX | ELI |",
        "|---|---|---|",
        *acts,
    ])


def write_sources(out: Path, taxonomy: str | None = None, nace: str | None = None) -> bytes:
    """SOURCES.md with one block replaced; the other file's block is kept as it was."""
    path = out / "SOURCES.md"
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    blocks = {}
    for name, new, how in (("taxonomy.json", taxonomy, "python3 eu_taxonomy_mcp.py refresh"),
                           ("nace.json", nace, "python3 eu_taxonomy_mcp.py refresh --nace")):
        blocks[name] = new if new is not None else (_existing_block(old, name) or f"Not built here yet: run `{how}`.")
    parts = [
        "# Sources of the data in this directory",
        "",
        SOURCES_MARKER,
        "",
        "Two data files, each rebuilt by a `refresh` command. The terms for each are quoted with the date read.",
    ]
    for name, title in (("taxonomy.json", "EU Taxonomy Navigator"), ("nace.json", "NACE Rev. 2 and NACE Rev. 2.1")):
        begin, end = _block_markers(name)
        parts += ["", f"## {name}: {title}", "", begin, blocks[name], end]
    parts += ["", "## Texts of EU law", "", eu_law_section(), ""]
    return "\n".join(parts).encode("utf-8")


# ------------------------------------------------------------------ runs

def _write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def resolve_out(value: str | None) -> Path:
    if value:
        return Path(value)
    if (core.HERE / "pyproject.toml").is_file() and (core.HERE / "data").is_dir():
        return core.HERE / "data"
    raise RefreshError("--out DIR is required outside a source checkout (the bundled data inside an installed "
                       "package is not rewritten); then run with --snapshot DIR/taxonomy.json")


def _read_ours(path: Path, schema: str) -> dict | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        data = None
    if not isinstance(data, dict) or data.get("schema") != schema:
        raise RefreshError(f"{path} exists and was not written by eu-taxonomy-mcp; choose another --out")
    return data


def _guard(out: Path) -> tuple[dict | None, dict | None]:
    """The previous files in out, if any; refuses to overwrite files this tool did not write."""
    notes = out / "SOURCES.md"
    if notes.exists():
        try:
            ours = SOURCES_MARKER in notes.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            raise RefreshError(f"cannot read {notes}: {e}") from None
        if not ours:
            raise RefreshError(f"{notes} exists and was not written by eu-taxonomy-mcp; choose another --out")
    return _read_ours(out / core.SNAPSHOT_FILE, core.SCHEMA), _read_ours(out / core.NACE_FILE, core.NACE_SCHEMA)


def _save(out: Path, name: str, payload: bytes, sources: bytes) -> None:
    try:
        out.mkdir(parents=True, exist_ok=True)
        _write_atomic(out / name, payload)
        _write_atomic(out / "SOURCES.md", sources)
    except OSError as e:
        raise RefreshError(f"cannot write to {out}: {e}") from None


def run(out: Path, fetcher: Fetcher, per_activity: bool = False, now=None, clock=time.monotonic) -> dict:
    """Crawl, check, write taxonomy.json. Returns a summary; raises RefreshError with nothing written."""
    old, _ = _guard(out)
    started = clock()
    now = now or dt.datetime.now(dt.timezone.utc)
    sectors, activities, matches, mode = crawl(fetcher, per_activity)
    snapshot = build_snapshot(sectors, activities, matches, now.strftime("%Y-%m-%d"))
    check_not_shrunk(snapshot["counts"], old, {"activities": "activities", "criteria_sets": "criteria sets"},
                     out / core.SNAPSHOT_FILE)
    payload = serialize(snapshot)
    try:
        core.Taxonomy(json.loads(payload.decode("utf-8")), _nace_for_check(out))
    except core.SnapshotError as e:
        raise RefreshError(f"the new snapshot does not load: {e}; nothing was written") from None
    elapsed = clock() - started
    block = taxonomy_block(snapshot, payload, fetcher, mode, now.strftime("%Y-%m-%dT%H:%M:%SZ"), elapsed)
    _save(out, core.SNAPSHOT_FILE, payload, write_sources(out, taxonomy=block))
    return {"requests": fetcher.requests, "bytes": fetcher.bytes, "elapsed": elapsed, "mode": mode,
            "counts": snapshot["counts"], "retrieved": snapshot["retrieved"], "changes": diff(old, snapshot),
            "path": str(out / core.SNAPSHOT_FILE), "sha256": _sha256(payload), "size": len(payload)}


def _nace_for_check(out: Path):
    try:
        return core.Nace.load(core.nace_path_for(out / core.SNAPSHOT_FILE))
    except core.SnapshotError as e:
        raise RefreshError(f"no NACE table to check the snapshot against ({e}); run refresh --nace first") from None


def run_nace(out: Path, fetcher: Fetcher, now=None, clock=time.monotonic, minimum: dict | None = None) -> dict:
    """Fetch both NACE annexes from Cellar, check, write nace.json. Raises RefreshError with nothing written."""
    _, old = _guard(out)
    started = clock()
    now = now or dt.datetime.now(dt.timezone.utc)
    documents = {rev: fetcher.get_act(core.NACE_ACTS[rev]["celex"]) for rev in ("2", "2.1")}
    data = build_nace(documents, now.strftime("%Y-%m-%d"), minimum)
    for rev in ("2", "2.1"):
        previous = {"counts": nace_counts(old["revisions"][rev])} if old else None
        check_not_shrunk(nace_counts(data["revisions"][rev]), previous,
                         {"divisions": f"NACE Rev. {rev} divisions", "classes": f"NACE Rev. {rev} classes"},
                         out / core.NACE_FILE)
    payload = serialize(data)
    try:
        core.Nace(json.loads(payload.decode("utf-8")))
    except core.SnapshotError as e:
        raise RefreshError(f"the new NACE table does not load: {e}; nothing was written") from None
    elapsed = clock() - started
    block = nace_block(data, payload, fetcher, now.strftime("%Y-%m-%dT%H:%M:%SZ"), elapsed)
    _save(out, core.NACE_FILE, payload, write_sources(out, nace=block))
    return {"requests": fetcher.requests, "bytes": fetcher.bytes, "elapsed": elapsed,
            "counts": {rev: nace_counts(data["revisions"][rev]) for rev in ("2", "2.1")},
            "path": str(out / core.NACE_FILE), "sha256": _sha256(payload), "size": len(payload)}


def main(args) -> int:
    delay = max(float(args.delay), MIN_DELAY)
    fetcher = Fetcher(delay=delay, timeout=max(float(args.timeout), 1.0))
    nace = getattr(args, "nace", False)
    try:
        out = resolve_out(args.out)
        print(f"refresh: {CELLAR if nace else core.API_BASE} -> {out}", file=sys.stderr)
        s = run_nace(out, fetcher) if nace else run(out, fetcher, per_activity=args.per_activity)
    except RefreshError as e:
        print(f"eu-taxonomy-mcp refresh: {e}", file=sys.stderr)
        print(f"({fetcher.requests} requests made; the existing files, if any, are unchanged)", file=sys.stderr)
        return 2
    if nace:
        print(f"refresh --nace: {s['requests']} requests, {s['bytes']:,} bytes, {s['elapsed']:.1f} s")
        for rev, c in s["counts"].items():
            print(f"NACE Rev. {rev}: " + ", ".join(f"{v} {k}" for k, v in c.items()))
    else:
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
    p.add_argument("--nace", action="store_true")
    raise SystemExit(main(p.parse_args()))
