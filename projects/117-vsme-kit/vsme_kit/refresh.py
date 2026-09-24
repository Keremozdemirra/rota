"""Rebuild the bundled snapshots from the Official Journal, through CELLAR.

Only two fixed CELEX numbers are requested, from one host, over HTTPS. Nothing a
user types reaches the network. Redirects to another host are refused; CELLAR's
redirects to plain http on the same host are upgraded to https.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import http.client
import json
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import VERSION, ojparse

HOST = "publications.europa.eu"
USER_AGENT = f"vsme-kit/{VERSION} (+https://github.com/Keremozdemirra/vsme-kit)"
TIMEOUT = 60
RETRIES = 2
RETRY_DELAY = 3.0  # seconds, doubled per attempt; the tests set it to 0
MAX_BYTES = 20 * 1024 * 1024
DATA = Path(__file__).resolve().parent / "data"

ACTS = {
    "2026": {"celex": "32026R1560", "eli": "http://data.europa.eu/eli/reg_del/2026/1560/oj",
             "short": "Commission Delegated Regulation (EU) 2026/1560",
             "standard": "sustainability reporting standard for voluntary use ('Voluntary Standard'), Annex I"},
    "2025": {"celex": "32025H1710", "eli": "http://data.europa.eu/eli/reco/2025/1710/oj",
             "short": "Commission Recommendation (EU) 2025/1710",
             "standard": "voluntary sustainability reporting standard for SMEs (VSME), Annex I"},
}
LICENCE = {
    "terms": "https://commission.europa.eu/legal-notice_en",
    "quote": ("Unless otherwise indicated (e.g. in individual copyright notices), content owned by the EU on this "
              "website is licensed under the Creative Commons Attribution 4.0 International (CC BY 4.0) licence. This "
              "means that reuse is allowed, provided appropriate credit is given and changes are indicated."),
    "policy": "Commission Decision 2011/833/EU on the reuse of Commission documents, http://data.europa.eu/eli/dec/2011/833/oj",
    "licence": "CC BY 4.0, https://creativecommons.org/licenses/by/4.0/",
    "checked": "2026-09-24",
}
CHANGES = ("Text extracted from the English XHTML of the Official Journal: whitespace normalised, table layout "
           "flattened (cells joined by ' | '), footnotes and appendices left out, images replaced by a marker.")
ORDINALS = {"first": 1, "second": 2, "third": 3, "fifth": 5, "tenth": 10, "twentieth": 20}
MONTHS = {m: i for i, m in enumerate(("january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"), 1)}


class RefreshError(RuntimeError):
    """The source could not be read or did not have the expected structure."""


class _SameHostHttps(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parts = urllib.parse.urlsplit(newurl)
        if parts.hostname != HOST:
            raise RefreshError(f"redirect to another host refused: {parts.hostname}")
        if parts.scheme == "http":
            newurl = urllib.parse.urlunsplit(("https",) + tuple(parts)[1:])
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open(request, timeout):
    """(status, headers, body). Replaced by a fake in the tests."""
    opener = urllib.request.build_opener(_SameHostHttps())
    with opener.open(request, timeout=timeout) as resp:
        return resp.status, dict(resp.headers.items()), resp.read(MAX_BYTES + 1)


def fetch(celex: str) -> dict:
    if not re.fullmatch(r"3\d{4}[A-Z]\d{4}", celex):
        raise RefreshError(f"not a CELEX number of this tool: {celex[:20]!r}")
    url = f"https://{HOST}/resource/celex/{celex}"
    headers = {"Accept": "application/xhtml+xml", "Accept-Language": "eng", "User-Agent": USER_AGENT}
    last = "no attempt"
    for attempt in range(RETRIES + 1):
        if attempt:
            time.sleep(RETRY_DELAY * (2 ** (attempt - 1)))
        try:
            status, resp_headers, body = _open(urllib.request.Request(url, headers=headers), TIMEOUT)
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code in (429, 500, 502, 503, 504):
                continue
            raise RefreshError(f"{last} for {url}") from None
        except RefreshError:
            raise
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, http.client.HTTPException, OSError) as e:
            last = f"{type(e).__name__}: {getattr(e, 'reason', e)}"
            continue
        if status != 200:
            raise RefreshError(f"HTTP {status} for {url}")
        if not body:
            raise RefreshError(f"empty response from {url}")
        if len(body) > MAX_BYTES:
            raise RefreshError(f"response larger than {MAX_BYTES} bytes from {url}")
        lowered = {k.lower(): v for k, v in resp_headers.items()}
        if "html" not in (lowered.get("content-type") or "").lower():
            raise RefreshError(f"expected XHTML from {url}, got {lowered.get('content-type') or 'no content type'}")
        return {"url": url, "body": body, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
                "etag": lowered.get("etag"), "last_modified": lowered.get("last-modified")}
    raise RefreshError(f"{last} for {url} after {RETRIES + 1} attempts")


def _date(text: str):
    m = re.search(r"(\d{1,2}) (" + "|".join(MONTHS) + r") (\d{4})", text, re.I)
    return dt.date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1))) if m else None


def build(edition: str, record: dict, today: dt.date) -> dict:
    """The snapshot for one edition from the fetched XHTML."""
    act = ACTS[edition]
    root = ojparse.parse(record["body"])
    head = ojparse.header(root)
    annex_i = ojparse.annex(root, "I")
    annex_ii = ojparse.annex(root, "II")
    if annex_i is None or annex_ii is None:
        raise RefreshError(f"{act['celex']}: Annex I or Annex II not found")
    snap = {
        "edition": edition, "celex": act["celex"], "eli": act["eli"], "act": act["short"], "standard": act["standard"],
        "title": head["title"], "oj": "OJ L, {}, {d.day}.{d.month}.{d.year}".format(head["oj_number"], d=dt.date.fromisoformat(head["published"])),
        "published": head["published"],
        "source": {"url": record["url"], "sha256": record["sha256"], "bytes": record["bytes"], "etag": record["etag"],
                   "last_modified": record["last_modified"], "retrieved": today.isoformat()},
        "licence": LICENCE, "changes": CHANGES,
        "annex_i": ojparse.paragraphs(annex_i),
    }
    if edition == "2025":
        snap["annex_ii_guidance"] = ojparse.paragraphs(annex_ii, stop_at_appendix=False)
    else:
        snap["value_chain_cap"] = ojparse.value_chain_cap(annex_ii)
        art4 = ojparse.subdivision(root, "art_4")
        rule = re.search(r"enter into force on the (\w+) day following that of its publication", art4)
        if not rule or rule.group(1) not in ORDINALS:
            raise RefreshError("Article 4: entry-into-force rule not found")
        applies = re.search(r"Article 3 shall apply from the financial years beginning on or after ([^.]+)", art4)
        published = dt.date.fromisoformat(head["published"])
        snap["entry_into_force"] = (published + dt.timedelta(days=ORDINALS[rule.group(1)])).isoformat()
        snap["value_chain_cap_applies"] = ("financial years beginning on or after "
                                           + _date(applies.group(1)).isoformat()) if applies and _date(applies.group(1)) else None
        snap["article_4"] = art4
        snap["recital_5"] = ojparse.subdivision(root, "rct_5")
        if "Recommendation (EU) 2025/1710" not in snap["recital_5"]:
            raise RefreshError("recital 5 no longer mentions Recommendation (EU) 2025/1710")
    codes = {p["code"] for p in snap["annex_i"] if p["code"]}
    expected = {f"B{i}" for i in range(1, 12)} | {f"C{i}" for i in range(1, 10)}
    if codes != expected:
        raise RefreshError(f"{act['celex']}: disclosures found {sorted(codes)}, expected B1-B11 and C1-C9")
    return snap


def run(out_dir=None, today=None) -> list:
    """Fetch both acts and write the snapshots. Returns one summary line per edition."""
    out = Path(out_dir) if out_dir else DATA
    out.mkdir(parents=True, exist_ok=True)
    today = today or dt.date.today()
    lines = []
    for edition, act in ACTS.items():
        record = fetch(act["celex"])
        try:
            snap = build(edition, record, today)
        except ojparse.ParseError as e:
            raise RefreshError(f"{act['celex']}: {e}") from None
        path = out / f"standard-{edition}.json"
        path.write_text(json.dumps(snap, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        extra = (f", {len(snap['annex_ii_guidance'])} guidance paragraphs" if edition == "2025"
                 else f", {len(snap['value_chain_cap'])} value chain cap rows")
        lines.append(f"{path.name}: {act['celex']}, {record['bytes']} bytes, sha256 {record['sha256']}, "
                     f"{len(snap['annex_i'])} Annex I paragraphs{extra}")
    return lines
