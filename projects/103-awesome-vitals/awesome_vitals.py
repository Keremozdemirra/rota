#!/usr/bin/env python3
"""awesome-vitals: check every GitHub repository linked from a Markdown list.

Curated lists keep entries long after anyone maintains them. This reads one or
more Markdown files (an awesome list, a README, docs), finds every link to a
GitHub repository, and reports which entries are archived, gone, renamed,
abandoned, stale, or carry no licence file, with the line of each entry.

Standard library only, one file.

What it reads and what it sends:

- It reads the Markdown files named on the command line and, with --diff, the
  output of `git diff` for those files. Nothing else on disk.
- It sends owner/name pairs to the GitHub REST API, with GITHUB_TOKEN when that
  is set. When GitHub cannot answer, it downloads the agent-vitals census index
  once. Nothing else leaves the machine.
- It writes only to standard output.

The findings are dates, flags and licence identifiers from public metadata,
never a verdict on anyone's work. A finished tool can go a year without a push
and still work.
"""
from __future__ import annotations

import argparse
import datetime as dt
import http.client
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

VERSION = "0.1.0"
UA = f"awesome-vitals/{VERSION} (+https://github.com/Keremozdemirra/awesome-vitals)"
API = "https://api.github.com"
# The census collector asks for this API version too, so both read the same fields.
API_VERSION = "2022-11-28"
CENSUS = "https://raw.githubusercontent.com/Keremozdemirra/agent-vitals/main/data/servers.json"

# (key, label) in report order. The keys are what --fail-on takes.
FINDINGS = [
    ("archived", "archived"),
    ("gone", "gone"),
    ("renamed", "renamed"),
    ("abandoned", "abandoned"),
    ("stale", "stale"),
    ("no-licence", "no licence file"),
    ("non-standard-licence", "non-standard licence"),
    ("unchecked", "not checked"),
]
FINDING_KEYS = [k for k, _ in FINDINGS]
LABEL = dict(FINDINGS)
# People type the American spelling as often as not.
ALIASES = {"no-license": "no-licence", "non-standard-license": "non-standard-licence"}
DEFAULT_FAIL_ON = "archived,gone"


# ---------------------------------------------------------------- links

# First path segments that are sections of github.com rather than accounts, so
# github.com/<one of these>/<x> is never a repository.
SITE_SECTIONS = frozenset("""
about account advisories apps blog codespaces collections contact copilot customer-stories dashboard
education enterprise events explore features git-guides issues join login logout marketplace mobile new
nonprofit notifications open-source organizations orgs password_reset pricing pulls readme resources search
security sessions settings signup site solutions sponsors stars team topics trending user-attachments users
watching
""".split())

# A link into a repository's issues, pull requests, discussions or history cites
# one conversation or one change inside a list entry's description. The entry
# is the repository itself, so these are not checked. See the README.
CONVERSATIONS = frozenset({"issues", "pull", "pulls", "discussions", "commit", "commits", "compare", "security"})

# The lookbehind keeps gist.github.com, api.github.com, user@github.com and URLs
# nested inside another URL's path out, while still taking markdown targets,
# autolinks, href values, bare URLs and scheme-less github.com/owner/repo.
GITHUB_LINK = re.compile(
    r"(?:(?<![\w.@/:-])(?:https?:)?//|(?<![\w.@/:-]))(?:www\.)?github\.com/"
    r"([A-Za-z0-9_.-]*)"          # owner, or a site section
    r"(?:/([A-Za-z0-9_.-]*))?"    # repository
    r"(?:/([A-Za-z0-9_.-]*))?",   # what follows: tree, blob, issues, pull...
    re.IGNORECASE,
)
IMAGE = re.compile(r"!\[[^\]]*\]\(\s*<?([^)\s>]+)")
IMG_TAG = re.compile(r"<(?:img|source)\b[^>]*?\b(?:src|srcset)\s*=\s*[\"']?([^\"'\s>]+)", re.IGNORECASE)
CODE_SPAN = re.compile(r"(`+)(?!`).+?(?<!`)\1(?!`)")
# Indentation is not limited to three spaces: in lists, fences sit inside
# nested items, and missing one would check a `git clone` line as an entry.
FENCE_OPEN = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")
FENCE_CLOSE = re.compile(r"^\s*(`{3,}|~{3,})\s*$")
OWNER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
REPO = re.compile(r"^[A-Za-z0-9._-]{1,100}$")

PROFILE, SITE_PAGE, CONVERSATION, IMAGE_LINK = "profile", "site-page", "conversation", "image"
NOT_ENTRIES = {  # (one, several)
    PROFILE: ("link to a profile or organisation", "links to profiles or organisations"),
    SITE_PAGE: ("link to a GitHub page that is not a repository", "links to GitHub pages that are not repositories"),
    CONVERSATION: ("link to an issue, pull request, discussion or commit",
                   "links to issues, pull requests, discussions or commits"),
    IMAGE_LINK: ("image", "images"),
}


def drop_comments(line: str, in_comment: bool) -> tuple[str, bool]:
    """The part of a line outside HTML comments, and whether a comment is still open after it."""
    kept, i = [], 0
    while True:
        if in_comment:
            j = line.find("-->", i)
            if j < 0:
                return " ".join(kept), True
            i, in_comment = j + 3, False
        else:
            j = line.find("<!--", i)
            if j < 0:
                kept.append(line[i:])
                return " ".join(kept), False
            kept.append(line[i:j])
            i, in_comment = j + 4, True


def classify(owner: str, repo: str | None, after: str | None) -> tuple[str | None, str | None]:
    """(owner/repo, None) for a link to a repository, (None, reason) for anything else."""
    if not repo or not repo.strip("."):
        name = owner.rstrip(".")
        if not name or name.lower() in SITE_SECTIONS or not OWNER.match(name):
            return None, SITE_PAGE
        return None, PROFILE
    if owner.lower() in SITE_SECTIONS or not OWNER.match(owner):
        return None, SITE_PAGE
    if after is None:
        # A bare URL at the end of a sentence carries the full stop with it.
        repo = repo.rstrip(".")
    if repo.lower().endswith(".git"):
        repo = repo[:-4]
    if not REPO.match(repo) or repo in (".", ".."):
        return None, SITE_PAGE
    if after and after.lower() in CONVERSATIONS:
        return None, CONVERSATION
    return f"{owner}/{repo}", None


def scan(text: str) -> tuple[list[tuple[int, str]], list[tuple[int, str, str]]]:
    """(line, owner/repo) for every repository link; (line, url, reason) for GitHub links that are not entries."""
    found, skipped = [], []
    fence: tuple[str, int] | None = None
    in_comment = False
    # split("\n"), not splitlines(): editors and git count only newlines, and a
    # U+2028 or form feed inside a description must not shift every line after it.
    for n, line in enumerate(text.split("\n"), 1):
        line = line.rstrip("\r")
        if fence:
            m = FENCE_CLOSE.match(line)
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= fence[1]:
                fence = None
            continue
        if not in_comment:
            m = FENCE_OPEN.match(line)
            # three backticks with more backticks after them on the line are inline code, not a fence
            if m and not (m.group(1)[0] == "`" and "`" in m.group(2)):
                fence = (m.group(1)[0], len(m.group(1)))
                continue
        line, in_comment = drop_comments(CODE_SPAN.sub(" ", line), in_comment)
        images = [m.span(1) for m in IMAGE.finditer(line)] + [m.span(1) for m in IMG_TAG.finditer(line)]
        for m in GITHUB_LINK.finditer(line):
            if any(a <= m.start() < b for a, b in images):
                skipped.append((n, m.group(0), IMAGE_LINK))
                continue
            name, reason = classify(m.group(1), m.group(2), m.group(3))
            if name:
                found.append((n, name))
            else:
                skipped.append((n, m.group(0), reason))
    return found, skipped


def norm(path: str) -> str:
    """A path relative to the working directory with forward slashes, which is how git diff names files."""
    p = os.path.normpath(path)
    try:
        p = os.path.relpath(os.path.abspath(p))
    except ValueError:  # another drive on Windows
        pass
    return p.replace(os.sep, "/")


def collect(sources: list[tuple[str, str]], selected: dict | None = None) -> tuple[list[dict], dict[str, int]]:
    """Entries deduplicated by repository (case-insensitive, as GitHub is), every location kept.

    `sources` is [(path as given, text)]; `selected` maps a normalised path (or
    None for every file) to the line numbers to keep, and limits the entries to them."""
    repos: dict[str, dict] = {}
    ignored: Counter = Counter()

    def wanted(path: str, n: int) -> bool:
        if selected is None:
            return True
        return any(n in selected[key] for key in (norm(path), None) if key in selected)

    for path, text in sources:
        found, skipped = scan(text)
        for n, _url, reason in skipped:
            if wanted(path, n):
                ignored[reason] += 1
        for n, name in found:
            if not wanted(path, n):
                continue
            entry = repos.setdefault(name.lower(), {"repository": name, "locations": []})
            loc = {"file": path, "line": n}
            if loc not in entry["locations"]:
                entry["locations"].append(loc)
    return list(repos.values()), dict(ignored)


# ---------------------------------------------------------------- lines

class Lines(list):
    """Line ranges that answer `n in lines` like the sets a diff gives, without
    building a set for a range such as 1-100000."""

    def __contains__(self, n) -> bool:
        return any(n in r for r in self)


def parse_only_lines(spec: str) -> dict[str | None, Lines]:
    """'README.md:10-20,docs/x.md:5' -> {'README.md': [range(10, 21)], 'docs/x.md': [range(5, 6)]}.

    A range without a file applies to every file."""
    out: dict[str | None, Lines] = {}
    for part in (p.strip() for p in spec.split(",")):
        if not part:
            continue
        path, _, span = part.rpartition(":")
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", span.strip())
        if not m or int(m.group(2) or m.group(1)) < int(m.group(1)):
            raise ValueError(f"--only-lines takes FILE:START-END, not {part!r}")
        start, end = int(m.group(1)), int(m.group(2) or m.group(1))
        out.setdefault(norm(path) if path else None, Lines()).append(range(start, end + 1))
    return out


HUNK = re.compile(r"^@@ -\d+(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def unquote_path(s: str) -> str:
    """Undo git's C-style quoting of a path with unusual characters: "b/donn\\303\\251es.md"."""
    body = s[1:-1] if len(s) >= 2 and s.endswith('"') else s[1:]
    out, i = bytearray(), 0
    escapes = {"n": b"\n", "t": b"\t", '"': b'"', "\\": b"\\", "a": b"\a", "b": b"\b", "f": b"\f", "r": b"\r", "v": b"\v"}
    while i < len(body):
        c = body[i]
        if c == "\\" and i + 1 < len(body):
            octal = body[i + 1:i + 4]
            if re.fullmatch(r"[0-7]{3}", octal):
                out.append(int(octal, 8) & 0xFF)
                i += 4
                continue
            out += escapes.get(body[i + 1], body[i + 1].encode("utf-8"))
            i += 2
            continue
        out += c.encode("utf-8")
        i += 1
    return out.decode("utf-8", errors="replace")


def diff_path(s: str) -> str | None:
    s = unquote_path(s) if s.startswith('"') else s.split("\t")[0]
    if s == "/dev/null":
        return None
    return norm(s[2:] if s.startswith("b/") else s)


def parse_diff(text: str) -> dict[str, set[int]]:
    """Line numbers added on the new side of a unified diff, per file."""
    added: dict[str, set[int]] = {}
    path, new, old_left, new_left = None, 0, 0, 0
    for line in text.split("\n"):
        # Hunk bodies are consumed by their counts, never by their look: a
        # removed markdown line "-- x" shows as "--- x", like a file header.
        if old_left > 0 or new_left > 0:
            tag = line[:1]
            if tag == "+":
                if path is not None:
                    added.setdefault(path, set()).add(new)
                new, new_left = new + 1, new_left - 1
            elif tag == "-":
                old_left -= 1
            elif tag in (" ", ""):
                new, old_left, new_left = new + 1, old_left - 1, new_left - 1
            continue
        if line.startswith("diff --git ") or line.startswith("diff --cc "):
            path = None
        elif line.startswith("+++ "):
            path = diff_path(line[4:])
        else:
            m = HUNK.match(line)
            if m:
                old_left = int(m.group(1)) if m.group(1) is not None else 1
                new = int(m.group(2))
                new_left = int(m.group(3)) if m.group(3) is not None else 1
    return added


def git_added_lines(rev_range: str, files: list[str], run=None) -> dict[str, set[int]]:
    """Lines added to `files` in `rev_range`, by running git diff --unified=0.

    The line numbers are those of the range's second revision, so it should be
    what is checked out: BASE...HEAD, not BASE...some-other-commit."""
    run = run or subprocess.run
    if not rev_range or rev_range.startswith("-"):
        # passed to git as an argument; a leading dash would be read as an option
        raise ValueError(f"--diff takes a revision range such as origin/main...HEAD, not {rev_range!r}")
    # Explicit prefixes and no colour, external diff or textconv, whatever the
    # user's git config says; --relative names files the way they were given here.
    cmd = ["git", "-c", "core.quotePath=false", "diff", "--no-color", "--no-ext-diff", "--no-textconv",
           "--unified=0", "--src-prefix=a/", "--dst-prefix=b/", "--relative", rev_range, "--", *files]
    try:
        p = run(cmd, capture_output=True, timeout=120)
    except FileNotFoundError:
        raise RuntimeError("--diff needs git, and git is not on PATH") from None
    except subprocess.TimeoutExpired:
        raise RuntimeError("git diff did not finish within 120 seconds") from None
    if p.returncode != 0:
        err = p.stderr.decode("utf-8", errors="replace").strip().splitlines()
        # a shallow clone knows neither the base commit nor the merge base
        shallow = any(k in e for e in err for k in ("merge base", "unknown revision", "bad revision", "bad object"))
        hint = " (in GitHub Actions, check out with fetch-depth: 0)" if shallow else ""
        raise RuntimeError(f"git diff {rev_range} failed: {err[-1] if err else 'exit ' + str(p.returncode)}{hint}")
    return parse_diff(p.stdout.decode("utf-8", errors="replace"))


# ---------------------------------------------------------------- facts

BLANK = {"source": None, "source_date": "", "full_name": None, "renamed_to": None, "archived": None,
         "pushed_at": None, "license": None, "license_state": None, "stars": None, "gone": False,
         "http_status": None, "github": "", "note": ""}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Hand redirects back to the caller: a 301 is the rename signal, and the
    caller decides where the token may follow."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _json(body: bytes):
    try:
        return json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None


def licence_state(lic) -> tuple[str | None, str]:
    """(SPDX id or None, state), the three states the census distinguishes.

    A null licence object means GitHub found no licence file; NOASSERTION means
    a licence file exists that GitHub cannot map to a standard identifier."""
    if not isinstance(lic, dict) or not lic:
        return None, "none"
    spdx = lic.get("spdx_id")
    if spdx in (None, "", "NOASSERTION"):
        return None, "non-standard"
    return str(spdx), "spdx"


class GitHub:
    """Repository facts from the GitHub REST API, with the agent-vitals census behind it."""

    def __init__(self, token: str | None = None, census_url: str = CENSUS, source: str = "auto",
                 api: str = API, timeout: float = 20.0, proxies: dict | None = None):
        self.token, self.census_url, self.source = token, census_url, source
        self.api, self.timeout = api.rstrip("/"), timeout
        handlers: list = [_NoRedirect()]
        if proxies is not None:
            handlers.append(urllib.request.ProxyHandler(proxies))
        self.opener = urllib.request.build_opener(*handlers)
        self.requests = 0
        self.state = "not asked" if source == "census" else "ok"
        self.stop_reason = ""  # set once GitHub is given up on for the rest of the run
        self._census: dict | None = None
        self.census_date = ""
        self.census_error = ""

    def _get(self, url: str) -> tuple[int | None, dict, bytes, str]:
        """(status, lower-cased headers, body, error); status is None when nothing came back."""
        headers = {"User-Agent": UA, "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": API_VERSION}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        self.requests += 1
        try:
            with self.opener.open(urllib.request.Request(url, headers=headers), timeout=self.timeout) as resp:
                return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read(), ""
        except urllib.error.HTTPError as e:
            try:
                body = e.read()
            except (OSError, http.client.HTTPException):
                body = b""
            return e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, body, ""
        except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as e:
            reason = getattr(e, "reason", e)
            return None, {}, b"", (str(reason) or type(reason).__name__)[:80]

    def facts(self, name: str) -> dict:
        if self.source == "census":
            return self.from_census(name, "")
        if self.stop_reason:
            return self.from_census(name, self.stop_reason)
        url = f"{self.api}/repos/{name}"
        status, headers, body, err = self._get(url)
        # A renamed or transferred repository answers 301 with a Location on
        # /repositories/{id}. Follow it, but never take the token off the API host.
        for _ in range(3):
            if status not in (301, 302, 307, 308):
                break
            target = urllib.parse.urljoin(url, headers.get("location", ""))
            if not target.startswith(self.api + "/"):
                break
            url = target
            status, headers, body, err = self._get(url)
        if status is None:
            self.state, self.stop_reason = "unreachable", f"GitHub API unreachable ({err})"
            return self.from_census(name, self.stop_reason)
        data = _json(body)
        if status == 200:
            if isinstance(data, dict) and isinstance(data.get("full_name"), str):
                spdx, state = licence_state(data.get("license"))
                full = data["full_name"]
                return {**BLANK, "source": "github", "full_name": full, "http_status": 200,
                        "renamed_to": full if full.lower() != name.lower() else None,
                        "archived": bool(data.get("archived")),
                        "pushed_at": str(data.get("pushed_at") or "")[:10] or None,
                        "license": spdx, "license_state": state, "stars": data.get("stargazers_count")}
            return self.from_census(name, "GitHub API answered 200 without a repository in it")
        if status in (404, 410, 451):
            return {**BLANK, "source": "github", "gone": True, "http_status": status}
        message = str(data.get("message", "")) if isinstance(data, dict) else ""
        # GitHub signals both its primary and its secondary limits with 403 or 429:
        # docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api (checked 2026-09-24).
        if status == 429 or (status == 403 and (headers.get("x-ratelimit-remaining") == "0"
                                                or "retry-after" in headers or "rate limit" in message.lower())):
            self.state = "rate-limited"
            self.stop_reason = f"GitHub API rate limit reached ({status})"
            return self.from_census(name, self.stop_reason)
        if status == 401:
            self.state, self.stop_reason = "token rejected", "GitHub API rejected the token (401)"
            return self.from_census(name, self.stop_reason)
        # Any other refusal is about this repository or this network (SAML, an
        # allow list, a proxy), so the next repository still asks GitHub first.
        return self.from_census(name, f"GitHub API answered {status}")

    def census(self) -> dict | None:
        """The census index by lower-cased full name, downloaded once; None if it cannot be had."""
        if self._census is None and not self.census_error:
            url = self.census_url if "://" in self.census_url else Path(self.census_url).resolve().as_uri()
            try:
                req = urllib.request.Request(url, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=max(self.timeout, 60)) as resp:
                    data = json.load(resp)
                keep = ("full_name", "archived", "pushed_at", "license", "license_state", "stars")
                self._census = {r["full_name"].lower(): {k: r.get(k) for k in keep}
                                for r in data["repositories"]
                                if isinstance(r, dict) and isinstance(r.get("full_name"), str)}
                self.census_date = str(data.get("generated_at") or "")[:10]
            except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError, KeyError, TypeError) as e:
                reason = getattr(e, "reason", e)
                self.census_error = (str(reason) or type(reason).__name__)[:80]
        return self._census

    def from_census(self, name: str, why: str) -> dict:
        if self.source == "github":
            return {**BLANK, "github": why}
        index = self.census()
        if index is None:
            return {**BLANK, "github": why, "note": f"census unavailable ({self.census_error})"}
        r = index.get(name.lower())
        if r is None:
            return {**BLANK, "github": why, "note": "not in the census"}
        return {**BLANK, "source": "census", "source_date": self.census_date, "github": why,
                "full_name": r["full_name"], "archived": bool(r["archived"]),
                "pushed_at": str(r["pushed_at"] or "")[:10] or None, "license": r["license"],
                "license_state": r["license_state"], "stars": r["stars"]}


# The census's thresholds (agent-vitals collect.py, bucket()), so an entry reads
# the same here as in the census. A design choice of that project, not a standard.
def bucket(days: int | None, archived: bool) -> str:
    if archived:
        return "archived"
    if days is None:
        return "unknown"
    if days <= 30:
        return "active"
    if days <= 90:
        return "slowing"
    if days <= 365:
        return "stale"
    return "abandoned"


def days_since(iso: str | None, today: dt.date) -> int | None:
    if not iso:
        return None
    try:
        return (today - dt.date.fromisoformat(iso[:10])).days
    except ValueError:
        return None


def examine(entries: list[dict], gh: GitHub, today: dt.date, progress=None) -> list[dict]:
    out = []
    for i, e in enumerate(entries, 1):
        f = gh.facts(e["repository"])
        days = days_since(f["pushed_at"], today)
        if f["gone"]:
            status = "gone"
        elif f["source"] is None:
            status = "unchecked"
        else:
            status = bucket(days, bool(f["archived"]))
        findings = []
        if status in ("archived", "gone"):
            findings.append(status)
        if f["renamed_to"]:
            findings.append("renamed")
        if status in ("abandoned", "stale"):
            findings.append(status)
        if f["license_state"] == "none":
            findings.append("no-licence")
        elif f["license_state"] == "non-standard":
            findings.append("non-standard-licence")
        if status == "unchecked":
            findings.append("unchecked")
        out.append({**e, "status": status, "findings": findings, "days_since_push": days, **f})
        if progress:
            progress(i, len(entries))
    return out


# ---------------------------------------------------------------- report

def parse_fail_on(text: str) -> set[str]:
    keys = set()
    for k in (p.strip().lower() for p in text.split(",")):
        if not k:
            continue
        k = ALIASES.get(k, k)
        if k not in LABEL:
            raise ValueError(f"--fail-on: unknown finding {k!r}; choose from {', '.join(FINDING_KEYS)}")
        keys.add(k)
    return keys


def summary(results: list[dict]) -> dict:
    s = {"repositories": len(results), "links": sum(len(r["locations"]) for r in results)}
    s.update({k: sum(1 for r in results if k in r["findings"]) for k in FINDING_KEYS})
    s["no finding"] = sum(1 for r in results if not r["findings"])
    return s


def source_notes(results: list[dict], gh: GitHub) -> list[str]:
    """Where the facts came from, and why not from GitHub when they did not."""
    by = Counter(r["source"] for r in results)
    parts = []
    if by["github"]:
        parts.append(f"{by['github']} from the GitHub API")
    if by["census"]:
        parts.append(f"{by['census']} from the agent-vitals census of {gh.census_date or 'unknown date'}")
    if by[None]:
        parts.append(f"{by[None]} not checked")
    notes = ["Facts: " + ", ".join(parts) + "."] if parts else []
    if gh.source == "census":
        notes.append("GitHub API not asked (--source census).")
    elif gh.stop_reason:
        then = "were not checked" if gh.source == "github" else "came from the census where it had them"
        # 5,000 an hour with a token, 60 without: GitHub's rate-limit page (see README, checked 2026-09-24).
        notes.append(f"{gh.stop_reason}; the repositories after that {then}."
                     + (" Set GITHUB_TOKEN for 5,000 requests an hour." if gh.state == "rate-limited" and not gh.token else ""))
    refused = Counter(r["github"] for r in results if r["github"] and r["github"] != gh.stop_reason)
    for why, n in refused.most_common():
        notes.append(f"{why} for {n} {'repository' if n == 1 else 'repositories'}.")
    return notes


def ignored_note(ignored: dict[str, int]) -> str:
    if not ignored:
        return ""
    return "Not entries, not checked: " + ", ".join(f"{n} {NOT_ENTRIES[why][n != 1]}"
                                                  for why, n in sorted(ignored.items(), key=lambda kv: -kv[1])) + "."


def where(r: dict, many_files: bool, limit: int | None = 6) -> str:
    locs = [f"{loc['file']}:{loc['line']}" if many_files else str(loc["line"]) for loc in r["locations"]]
    if limit and len(locs) > limit:
        return ", ".join(locs[:limit]) + f" +{len(locs) - limit}"
    return ", ".join(locs)


def last_push(r: dict, long: bool = False) -> str:
    if not r["pushed_at"]:
        return ""
    d = r["days_since_push"]
    if d is None:
        return r["pushed_at"]
    return f"{r['pushed_at']} ({d} {'day' if d == 1 else 'days'})" if long else f"{r['pushed_at']} {d:>4}d"


def licence(r: dict) -> str:
    if r["license"]:
        return r["license"]
    return {"none": "none", "non-standard": "non-standard"}.get(r["license_state"] or "", "")


def source(r: dict) -> str:
    if r["source"] == "github":
        return "GitHub API"
    if r["source"] == "census":
        return f"census {r['source_date']}".strip()
    return ""


def note(r: dict, key: str) -> str:
    if key == "renamed":
        return f"now {r['renamed_to']}"
    if key == "gone":
        return {410: "HTTP 410: gone", 451: "HTTP 451: unavailable for legal reasons"}.get(
            r["http_status"], f"HTTP {r['http_status']}: deleted, or private")
    if key == "unchecked":
        return "; ".join(x for x in (r["github"], r["note"]) if x)
    return ""


def groups(results: list[dict]) -> list[tuple[str, list[dict]]]:
    return [(k, [r for r in results if k in r["findings"]]) for k in FINDING_KEYS
            if any(k in r["findings"] for r in results)]


def summary_line(s: dict) -> str:
    parts = [f"{s['repositories']} {'repository' if s['repositories'] == 1 else 'repositories'}"]
    parts += [f"{s[k]} {LABEL[k]}" for k in FINDING_KEYS if s[k]]
    parts.append(f"{s['no finding']} with no finding")
    return " · ".join(parts)


def render_text(results: list[dict], files: list[str], scope: str, today: dt.date,
                gh: GitHub, ignored: dict[str, int]) -> str:
    many = len(files) > 1
    s = summary(results)
    head = f"awesome-vitals · {', '.join(files)} · {scope} · {today.isoformat()}"
    lines = [head, f"{s['links']} {'link' if s['links'] == 1 else 'links'} to "
                   f"{s['repositories']} {'repository' if s['repositories'] == 1 else 'repositories'}", ""]
    cols = ["line", "repository", "last push", "licence", "source", "note"]
    table = [(k, [[where(r, many), r["repository"], last_push(r), licence(r), source(r), note(r, k)] for r in rs])
             for k, rs in groups(results)]
    if table:
        rows = [row for _, rs in table for row in rs]
        widths = [min(max(len(cols[i]), *(len(row[i]) for row in rows)), 48) for i in range(len(cols) - 1)]

        def fmt(cells):
            # every column but the note is cut to its width; the note is the explanation, so it never is
            return ("  " + "  ".join([c[:w].ljust(w) for c, w in zip(cells[:-1], widths)] + [cells[-1]])).rstrip()

        lines += [fmt(cols), fmt(["-" * w for w in widths] + ["-" * 4])]
        for k, rs in table:
            lines.append(f"{LABEL[k]} ({len(rs)})")
            lines += [fmt(row) for row in rs]
        lines.append("")
    else:
        lines += ["No finding.", ""]
    lines.append(summary_line(s))
    lines += source_notes(results, gh)
    if ignored_note(ignored):
        lines.append(ignored_note(ignored))
    return "\n".join(lines) + "\n"


def esc(text: object) -> str:
    return (str(text).replace("\\", "\\\\").replace("|", "\\|").replace("<", "&lt;").replace(">", "&gt;")
            .replace("\n", " "))


def render_markdown(results: list[dict], files: list[str], scope: str, today: dt.date,
                    gh: GitHub, ignored: dict[str, int], fail_on: set[str] | None) -> str:
    many = len(files) > 1
    s = summary(results)
    out = [f"### awesome-vitals: {esc(', '.join(files))}, {esc(scope)}, {today.isoformat()}", "",
           f"{s['links']} {'link' if s['links'] == 1 else 'links'} to {summary_line(s)}.", ""]
    if fail_on:
        failing = sum(1 for r in results if fail_on & set(r["findings"]))
        out += [f"This check fails on: {', '.join(LABEL[k] for k in FINDING_KEYS if k in fail_on)}. "
                f"{failing} {'entry' if failing == 1 else 'entries'} matched.", ""]
    for k, rs in groups(results):
        out += [f"#### {LABEL[k].capitalize()} ({len(rs)})", "",
                "| Line | Repository | Last push | Licence | Source | Note |",
                "| --- | --- | --- | --- | --- | --- |"]
        for r in rs:
            repo = f"[{esc(r['repository'])}](https://github.com/{r['repository']})"
            out.append(f"| {esc(where(r, many, None))} | {repo} | {esc(last_push(r, True))} | {esc(licence(r))} "
                       f"| {esc(source(r))} | {esc(note(r, k))} |")
        out.append("")
    out += [" ".join(source_notes(results, gh))]
    if ignored_note(ignored):
        out += ["", ignored_note(ignored)]
    out += ["", f"<sub>Checked with [awesome-vitals](https://github.com/Keremozdemirra/awesome-vitals) {VERSION}. "
                "Dates, flags and licence identifiers from public repository metadata, "
                "not a verdict on anyone's work.</sub>"]
    return "\n".join(out) + "\n"


def render_json(results: list[dict], files: list[str], scope: str, today: dt.date,
                gh: GitHub, ignored: dict[str, int], fail_on: set[str] | None) -> str:
    doc = {
        "tool": "awesome-vitals", "version": VERSION, "checked": today.isoformat(), "files": files, "scope": scope,
        "fail_on": sorted(fail_on, key=FINDING_KEYS.index) if fail_on is not None else None,
        "summary": summary(results),
        "github": {"state": gh.state, "requests": gh.requests, "stopped": gh.stop_reason or None},
        "census": {"url": gh.census_url, "date": gh.census_date or None, "error": gh.census_error or None},
        "notes": source_notes(results, gh),
        "ignored": ignored,
        "repositories": results,
    }
    return json.dumps(doc, indent=1, ensure_ascii=False) + "\n"


def _progress(i: int, n: int) -> None:
    sys.stderr.write(f"\rchecked {i}/{n}" + ("\n" if i == n else ""))
    sys.stderr.flush()


def main(argv: list[str] | None = None, *, today: dt.date | None = None, api: str = API,
         proxies: dict | None = None) -> int:
    """The command line. `today`, `api` and `proxies` exist for the tests."""
    ap = argparse.ArgumentParser(
        prog="awesome-vitals",
        description="Check every GitHub repository linked from a Markdown list and report which entries are "
                    "archived, gone, renamed, abandoned, stale or unlicensed, with their line numbers.")
    ap.add_argument("files", nargs="+", metavar="FILE", help="Markdown files to read")
    fmt = ap.add_mutually_exclusive_group()
    fmt.add_argument("--markdown", action="store_true", help="print a Markdown report, for an issue or a job summary")
    fmt.add_argument("--json", action="store_true", help="print JSON")
    ap.add_argument("--strict", action="store_true",
                    help=f"exit 1 if any entry has a finding named in --fail-on (default {DEFAULT_FAIL_ON})")
    ap.add_argument("--fail-on", metavar="LIST",
                    help="comma-separated findings that make --strict fail; implies --strict. "
                         "One or more of: " + ", ".join(FINDING_KEYS))
    sel = ap.add_mutually_exclusive_group()
    sel.add_argument("--only-lines", metavar="FILE:START-END,...",
                     help="report only entries on these lines, e.g. README.md:40-52,README.md:97")
    sel.add_argument("--diff", metavar="BASE...HEAD",
                     help="report only entries on lines added in this git revision range (pull-request mode)")
    ap.add_argument("--census", metavar="URL", default=CENSUS,
                    help="census index used when GitHub cannot answer; https://, file:// or a path "
                         "(default: the published agent-vitals index)")
    ap.add_argument("--source", choices=["auto", "github", "census"], default="auto",
                    help="auto: GitHub API, census when it cannot answer (default); "
                         "github: GitHub API only; census: census only, nothing sent to GitHub")
    ap.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):  # a console that cannot print a character should not crash the run
        sys.stdout.reconfigure(errors="replace")

    try:
        fail_on = parse_fail_on(a.fail_on if a.fail_on is not None else DEFAULT_FAIL_ON)
        only = parse_only_lines(a.only_lines) if a.only_lines else None
    except ValueError as e:
        ap.error(str(e))
    strict = a.strict or a.fail_on is not None

    sources = []
    for f in a.files:
        try:
            sources.append((f, Path(f).read_bytes().decode("utf-8-sig", errors="replace")))
        except OSError as e:
            print(f"awesome-vitals: cannot read {f}: {e.strerror or e}", file=sys.stderr)
            return 2

    scope = "all entries"
    selected = only
    if only is not None:
        scope = "selected lines"
    elif a.diff:
        try:
            selected = git_added_lines(a.diff, a.files)
        except (ValueError, RuntimeError) as e:
            print(f"awesome-vitals: {e}", file=sys.stderr)
            return 2
        scope = f"lines added in {a.diff}"

    entries, ignored = collect(sources, selected)
    token = (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip() or None
    gh = GitHub(token=token, census_url=a.census, source=a.source, api=api, proxies=proxies)
    today = today or dt.date.today()
    try:
        results = examine(entries, gh, today, _progress if sys.stderr.isatty() and entries else None)
    except KeyboardInterrupt:
        return 130

    if a.json:
        sys.stdout.write(render_json(results, a.files, scope, today, gh, ignored, fail_on if strict else None))
    elif not entries:
        msg = f"No links to GitHub repositories {'on those lines' if selected is not None else 'found'}."
        if a.markdown:
            msg = f"### awesome-vitals: {esc(', '.join(a.files))}, {esc(scope)}, {today.isoformat()}\n\n{msg}"
        else:
            msg = f"awesome-vitals · {', '.join(a.files)} · {scope} · {today.isoformat()}\n{msg}"
        sys.stdout.write(msg + "\n" + (ignored_note(ignored) + "\n" if ignored_note(ignored) else ""))
    elif a.markdown:
        sys.stdout.write(render_markdown(results, a.files, scope, today, gh, ignored, fail_on if strict else None))
    else:
        sys.stdout.write(render_text(results, a.files, scope, today, gh, ignored))
    if strict and any(fail_on & set(r["findings"]) for r in results):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
