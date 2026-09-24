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
import bisect
import datetime as dt
import http.client
import itertools
import json
import os
import re
import subprocess
import sys
import time
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
# An entry that could not be checked is not a finding one chooses to fail on:
# under --strict it is exit code 2, whatever --fail-on says.
FAIL_ON_KEYS = [k for k in FINDING_KEYS if k != "unchecked"]
LABEL = dict(FINDINGS)
# People type the American spelling as often as not.
ALIASES = {"no-license": "no-licence", "non-standard-license": "non-standard-licence"}
DEFAULT_FAIL_ON = "archived,gone"


# ---------------------------------------------------------------- links

# Names GitHub keeps for itself, so github.com/<name>/... is one of its own pages and never an
# account's repository: the list in github-reserved-names 2.2.0 (published 2026-05-28,
# https://github.com/Mottie/github-reserved-names, checked 2026-09-24). Its README says the list
# is not complete. None of these names owns a repository in the agent-vitals census of
# 2026-09-23; `github` and `skills`, which do, are not on it. The list is used under its licence:
#
#   The MIT License (MIT)
#
#   Copyright (c) Rob Garrison <wowmotty@gmail.com>
#
#   Permission is hereby granted, free of charge, to any person obtaining a copy
#   of this software and associated documentation files (the "Software"), to deal
#   in the Software without restriction, including without limitation the rights
#   to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
#   copies of the Software, and to permit persons to whom the Software is
#   furnished to do so, subject to the following conditions:
#
#   The above copyright notice and this permission notice shall be included in
#   all copies or substantial portions of the Software.
#
#   THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#   IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#   FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
#   AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#   LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
#   OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
#   THE SOFTWARE.
RESERVED = frozenset("""
300 302 400 401 402 403 404 405 406 407 408 409 410 411 412 413 414 415 416 417 418 419 420 421 422
423 424 425 426 427 428 429 430 431 500 501 502 503 504 505 506 507 508 509 510 511 693 694 695 900
about account admin advisories anonymous any api apps attributes auth billing blob blog bounty
branches business businesses c cache careers case-studies categories central certification changelog
chat cla cloud codereview codespaces collection collections comments commit commits companies
compare contact contributing cookbook copilot coupons customer customer-stories customers dashboard
dashboard-feed dashboards design develop developer diff discover discussions downloads downtime
editor editors edu education enterprise enterprises events explore featured features feed files
fixtures forked garage ghost gist gists git-guides github-copilot graphs groups guide guides help
help-wanted home hooks hosting hovercards identity images inbox individual info integration
interfaces introduction invalid-email-address investors issues jobs join journal journals lab labs
languages launch layouts learn legal library linux listings lists login logos logout mac maintenance
malware man marketplace mcp mention mentioned mentioning mentions migrating milestones mine mirrors
mobile navigation network new news newsletter newsroom none nonprofit nonprofits notices
notifications oauth offer open-source organisations organizations orgs pages partners payments
personal plans plugins popular popularity posts press preview pricing professional projects pulls
raw readme recommendations redeem releases render reply repos repositories resources restore revert
save-net-neutrality saved scraping search security services sessions settings shareholders showcases
signin signup site site-policy sitemap social-impact socials spam sponsors ssh staff starred stars
static status statuses storage store stories styleguide subscriptions suggest suggestion suggestions
support suspended talks teach teacher teachers teaching team teams ten terms timeline topic topics
tos tour train training translations tree trending undefined updates user-attachments username users
visualization w watching why-github wiki wikis windows works-with www0 www1 www2 www3 www4 www5 www6
www7 www8 www9
""".split())
# github.com sections that list does not have. This tool's additions; none of them owns a
# repository in the census either.
SITE_SECTIONS = RESERVED | {"models", "password_reset", "premium-support", "solutions"}
# The GitHub MCP Registry shows a server at github.com/mcp/<owner>/<repo>, e.g.
# github.com/mcp/github/github-mcp-server for github/github-mcp-server: a link to that repository.
MCP_REGISTRY = "mcp"

# The lookbehind keeps gist.github.com, api.github.com, user@github.com and URLs nested in
# another URL's path out, while taking link destinations, autolinks, href values, bare URLs
# (also inside _emphasis_) and scheme-less github.com/owner/repo. Every repeat is bounded, so a
# hostile line costs time in proportion to its length.
GITHUB_LINK = re.compile(
    r"(?:(?<![A-Za-z0-9.@/:-])(?:https?:)?//|(?<![A-Za-z0-9.@/:-]))(?:www\.)?github\.com/"
    r"(?P<owner>[A-Za-z0-9_.-]{0,200})(?:/(?P<repo>[A-Za-z0-9_.-]{0,200}))?"
    r"(?P<rest>(?:/[^\s/?#<>()\[\]{}\"'`|\\^]{0,200}){0,8})",
    re.IGNORECASE,
)
# GFM leaves these out of the end of a bare URL: they end the sentence, not the link.
BARE_TRAILING = "?!.,:*_~"
IMAGE = re.compile(r"!\[(?:[^\[\]\n]|\[[^\[\]\n]{0,999}\]){0,999}\]\(\s{0,99}<?([^)\s>]{1,4000})")
# Any src or srcset value is something embedded (an image, mostly), never a link to follow,
# in whichever tag and on whichever line of a tag it stands.
SRC_ATTR = re.compile(r"(?<!\w)(?:src|srcset)\s{0,20}=\s{0,20}(?:\"([^\"]{0,4000})\"|'([^']{0,4000})'|([^\s\"'>]{1,4000}))",
                      re.IGNORECASE)
REF_DEF = re.compile(r"\s{0,3}\[(?P<label>[^\[\]\n]{1,999})\]:[ \t]*<?(?P<url>[^\s<>]{1,4000})")
BACKTICKS = re.compile(r"`+")
BRACKET = re.compile(r"[\[\]]")
# Indentation is not limited to three spaces: in lists, fences sit inside nested items.
FENCE_OPEN = re.compile(r"\s*(`{3,}|~{3,})(.*)")
FENCE_CLOSE = re.compile(r"\s*(`{3,}|~{3,})\s*")
LIST_ITEM = re.compile(r"\s*(?:[-+*]|\d{1,9}[.)])(?:\s|$)")
# Validators, always applied with fullmatch: "$" would also accept a trailing newline.
OWNER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
REPO = re.compile(r"[A-Za-z0-9._-]{1,100}")
# The only strings ever put into an API URL, and the only names ever printed.
REPO_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}/(?!\.{1,2}\Z)[A-Za-z0-9._-]{1,100}")
SPDX_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+-]{0,63}")
CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")

PROFILE, SITE_PAGE, CONVERSATION, IMAGE_LINK = "profile", "site-page", "conversation", "image"
NOT_ENTRIES = {
    PROFILE: ("link to a profile or organisation", "links to profiles or organisations"),
    SITE_PAGE: ("link to a GitHub page that is not a repository", "links to GitHub pages that are not repositories"),
    CONVERSATION: ("link to one issue, pull request, discussion, commit, comparison or advisory",
                   "links to single issues, pull requests, discussions, commits, comparisons or advisories"),
    IMAGE_LINK: ("image", "images"),
}
UNCLOSED_FENCE = "a code fence opened here is never closed; nothing after it was read"
UNCLOSED_COMMENT = "an HTML comment opened here is never closed; nothing after it was read"


def one_item(rest: list[str]) -> bool:
    """Whether the path after owner/repo names one issue, pull request, discussion, commit,
    comparison or security advisory. Such a link cites that item inside an entry's
    description; the entry is the repository. Its other pages, the issue list included, count."""
    first = rest[0].lower() if rest else ""
    item = rest[1] if len(rest) > 1 else ""
    if first in ("issues", "pull", "discussions"):
        return item.isdigit()
    if first in ("commit", "compare"):
        return bool(item)
    return first == "security" and item.lower() == "advisories" and len(rest) > 2 and bool(rest[2])


def classify(owner: str, repo: str | None, rest: list[str]) -> tuple[str | None, str | None]:
    """(owner/repo, None) for a link to a repository, (None, reason) for anything else."""
    if owner.lower() == MCP_REGISTRY and repo and rest:
        owner, repo, rest = repo, rest[0], rest[1:]
    if not repo:
        if not owner or owner.lower() in SITE_SECTIONS or not OWNER.fullmatch(owner):
            return None, SITE_PAGE
        return None, PROFILE
    if owner.lower() in SITE_SECTIONS or not OWNER.fullmatch(owner):
        return None, SITE_PAGE
    if repo.lower().endswith(".git"):
        repo = repo[:-4]
    if not REPO.fullmatch(repo) or repo in (".", ".."):
        return None, SITE_PAGE
    if one_item(rest):
        return None, CONVERSATION
    if not REPO_NAME.fullmatch(f"{owner}/{repo}"):
        return None, SITE_PAGE
    return f"{owner}/{repo}", None


def label_key(label: str) -> str:
    return " ".join(label.split()).casefold()


def indent(line: str) -> int:
    expanded = line.expandtabs(4)
    return len(expanded) - len(expanded.lstrip(" "))


def closing_run(line: str, start: int, run: int) -> int:
    """Where the next run of exactly `run` backticks starts, or -1."""
    j = start
    while True:
        j = line.find("`" * run, j)
        if j < 0:
            return -1
        k = BACKTICKS.match(line, j).end()
        if k - j == run:
            return j
        j = k


def strip_inline(line: str, in_comment: bool) -> tuple[str, bool, bool]:
    """The line without code spans and HTML comments; whether a comment is open at its end;
    whether that comment opened on this line. Whichever starts first wins, as in CommonMark:
    `<!--` inside a code span is code, and a comment ends at the first -->, in backticks or not."""
    out, i, opened = [], 0, False
    while i < len(line):
        if in_comment:
            j = line.find("-->", i)
            if j < 0:
                return "".join(out), True, opened
            out.append(" ")
            i, in_comment, opened = j + 3, False, False
            continue
        tick, start = line.find("`", i), line.find("<!--", i)
        if start >= 0 and (tick < 0 or start < tick):
            out.append(line[i:start] + " ")
            # <!--> and <!---> are whole comments already
            for whole in ("<!-->", "<!--->"):
                if line.startswith(whole, start):
                    i = start + len(whole)
                    break
            else:
                i, in_comment, opened = start + 4, True, True
            continue
        if tick < 0:
            out.append(line[i:])
            break
        run = BACKTICKS.match(line, tick).end() - tick
        close = closing_run(line, tick + run, run)
        if close < 0:  # backticks without a partner are text
            out.append(line[i:tick + run])
            i = tick + run
        else:
            out.append(line[i:tick] + " ")
            i = close + run
    return "".join(out), in_comment, opened


def visible(text: str, warnings: list | None = None, path: str = "") -> list[tuple[int, str]]:
    """(line number, text) for what a reader sees as Markdown: no fenced code, HTML comments or
    code spans. A fence or comment still open at the end of the file goes into `warnings`."""
    out: list[tuple[int, str]] = []
    fence: tuple | None = None  # (character, length, indentation, ends with its list item, line)
    comment_line = 0
    prev = ""
    # split("\n"), not splitlines(): editors and git count only newlines, and a
    # U+2028 or form feed inside a description must not shift every line after it.
    for n, line in enumerate(text.split("\n"), 1):
        line = line.rstrip("\r")
        if fence:
            m = FENCE_CLOSE.fullmatch(line)
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= fence[1]:
                fence = None
                continue
            # A block inside a list item ends when the item does, closed or not, as on GitHub.
            if not (fence[3] and line.strip() and indent(line) < fence[2]):
                continue
            fence = None
        if not comment_line:
            m = FENCE_OPEN.fullmatch(line)
            # three backticks with more backticks after them on the line are inline code, not a fence
            if m and not (m.group(1)[0] == "`" and "`" in m.group(2)):
                depth = indent(line)
                in_item = depth >= 2 and bool(prev) and (bool(LIST_ITEM.match(prev)) or indent(prev) >= 2)
                fence = (m.group(1)[0], len(m.group(1)), depth, in_item, n)
                continue
        seen, still_open, opened = strip_inline(line, bool(comment_line))
        comment_line = n if opened else (comment_line if still_open else 0)
        if line.strip():
            prev = line
        out.append((n, seen))
    if warnings is not None:
        if fence:
            warnings.append({"file": path, "line": fence[4], "message": UNCLOSED_FENCE})
        if comment_line:
            warnings.append({"file": path, "line": comment_line, "message": UNCLOSED_COMMENT})
    return out


def image_only_labels(lines: list[tuple[int, str]]) -> set[str]:
    """Reference labels used as images and never as links: [![CI][badge]][runs] makes `badge`
    one. Their definitions point at images, so their URLs are not entries."""
    images, links = set(), set()
    for _, line in lines:
        if "[" not in line:
            continue
        stack, close_of = [], {}
        for m in BRACKET.finditer(line):
            if m.group() == "[":
                stack.append(m.start())
            elif stack:
                close_of[stack.pop()] = m.start()
        lead = len(line) - len(line.lstrip())
        consumed = set()
        for open_ in sorted(close_of):
            if open_ in consumed:
                continue
            close = close_of[open_]
            nxt = line[close + 1:close + 2]
            if nxt == "(" or (nxt == ":" and open_ == lead):  # inline link, or a definition
                continue
            if nxt == "[" and close + 1 in close_of:  # [text][label], or [label][] for short
                label = line[close + 2:close_of[close + 1]] or line[open_ + 1:close]
                consumed.add(close + 1)
            else:
                label = line[open_ + 1:close]
            if 0 < len(label) < 1000:
                (images if open_ > 0 and line[open_ - 1] == "!" else links).add(label_key(label))
    return images - links


def scan(text: str, warnings: list | None = None, path: str = ""
         ) -> tuple[list[tuple[int, str]], list[tuple[int, str, str]]]:
    """(line, owner/repo) for every repository link; (line, url, reason) for GitHub links that are not entries."""
    found, skipped = [], []
    lines = visible(text, warnings, path)
    image_labels = image_only_labels(lines)
    for n, line in lines:
        spans = [m.span(1) for m in IMAGE.finditer(line)]
        spans += [m.span(m.lastindex) for m in SRC_ATTR.finditer(line) if m.lastindex]
        ref = REF_DEF.match(line)
        if ref and label_key(ref.group("label")) in image_labels:
            spans.append(ref.span("url"))
        spans.sort()
        starts = [a for a, _ in spans]
        ends = list(itertools.accumulate((b for _, b in spans), max))
        for m in GITHUB_LINK.finditer(line):
            start, end = m.span()
            k = bisect.bisect_right(starts, start)
            if k and start < ends[k - 1]:
                skipped.append((n, m.group(0), IMAGE_LINK))
                continue
            delimited = (line[max(0, start - 3):start].endswith(("](", "](<", "<", '"', "'", "="))
                         or bool(ref and ref.start("url") == start))
            if not delimited:
                while end > start and line[end - 1] in BARE_TRAILING:
                    end -= 1
                m = GITHUB_LINK.match(line, start, end) or m
            rest = [seg for seg in m.group("rest").split("/")[1:]]
            name, reason = classify(m.group("owner"), m.group("repo"), rest)
            if name:
                found.append((n, name))
            else:
                skipped.append((n, m.group(0), reason))
    return found, skipped


def inside_cwd(path: str) -> bool:
    try:
        rel = os.path.relpath(os.path.abspath(path))
    except ValueError:  # another drive on Windows
        return False
    return rel != os.pardir and not rel.startswith(os.pardir + os.sep)


def norm(path: str) -> str:
    """A path relative to the working directory with forward slashes, which is how git diff names files."""
    p = os.path.normpath(path)
    try:
        p = os.path.relpath(os.path.abspath(p))
    except ValueError:  # another drive on Windows
        pass
    return p.replace(os.sep, "/")


def collect(sources: list[tuple[str, str]], selected: dict | None = None,
            warnings: list | None = None) -> tuple[list[dict], dict[str, int]]:
    """Entries deduplicated by repository (case-insensitive, as GitHub is), every location kept.

    `sources` is [(path as given, text)]; `selected` maps a normalised path (or None for
    every file) to the line numbers to keep, and limits the entries to them. A fence or
    comment left open goes into `warnings`."""
    repos: dict[str, dict] = {}
    ignored: Counter = Counter()

    def wanted(path: str, n: int) -> bool:
        if selected is None:
            return True
        return any(n in selected[key] for key in (norm(path), None) if key in selected)

    for path, text in sources:
        found, skipped = scan(text, warnings, path)
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
    """Undo git's C-style quoting of a path with unusual characters: "b/donn\\303\\251es.md".
    The name ends at the closing quote; git puts a tab after it when the name has a space."""
    out, i = bytearray(), 1
    escapes = {"n": b"\n", "t": b"\t", '"': b'"', "\\": b"\\", "a": b"\a", "b": b"\b", "f": b"\f", "r": b"\r", "v": b"\v"}
    while i < len(s) and s[i] != '"':
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            octal = s[i + 1:i + 4]
            if re.fullmatch(r"[0-7]{3}", octal):
                out.append(int(octal, 8) & 0xFF)
                i += 4
                continue
            out += escapes.get(s[i + 1], s[i + 1].encode("utf-8"))
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


# Everything below that is printed comes from GitHub or from a census file the
# user may point anywhere, so each value is held to its expected form first.
def valid_name(value) -> bool:
    return isinstance(value, str) and bool(REPO_NAME.fullmatch(value))


def iso_date(value) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return dt.date.fromisoformat(value[:10]).isoformat()
    except ValueError:
        return None


def plain(text: object, limit: int = 80) -> str:
    return CONTROL.sub(" ", str(text))[:limit]


def mask_text(text: str) -> str:
    """Error text with anything shaped like URL credentials or a query string hidden."""
    return re.sub(r"\?[^\s'\"]*", "?***", re.sub(r"[^\s/@'\"]+@", "***@", text))


def mask_url(url: str) -> str:
    """A URL with any user:password@ and query string hidden, for printing."""
    try:
        u = urllib.parse.urlsplit(url)
    except ValueError:
        return "***"
    netloc = "***@" + u.netloc.rsplit("@", 1)[1] if "@" in u.netloc else u.netloc
    return urllib.parse.urlunsplit((u.scheme, netloc, u.path, "***" if u.query else "", ""))


def licence_state(lic) -> tuple[str | None, str]:
    """(SPDX id or None, state), the three states the census distinguishes.

    A null licence object means GitHub found no licence file; NOASSERTION means
    a licence file exists that GitHub cannot map to a standard identifier."""
    if not isinstance(lic, dict) or not lic:
        return None, "none"
    spdx = lic.get("spdx_id")
    if spdx == "NOASSERTION" or not isinstance(spdx, str) or not SPDX_ID.fullmatch(spdx):
        return None, "non-standard"
    return spdx, "spdx"


# What a token can hold: printable ASCII, no spaces. Anything else would either break the
# request header or be quoted back in an error message.
TOKEN_FORM = re.compile(r"[\x21-\x7e]{1,1000}")
# The longest wait this tool accepts before its one retry of a rate-limited request. The
# tool's choice: a person may be waiting.
MAX_WAIT = 60


def is_rate_limit(status: int | None, headers: dict, data) -> bool:
    """GitHub signals both its primary and its secondary limits with 403 or 429:
    docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api (checked 2026-09-24)."""
    message = str(data.get("message", "")) if isinstance(data, dict) else ""
    return status == 429 or (status == 403 and (headers.get("x-ratelimit-remaining") == "0"
                                                or "retry-after" in headers or "rate limit" in message.lower()))


class GitHub:
    """Repository facts from the GitHub REST API, with the agent-vitals census behind it."""

    def __init__(self, token: str | None = None, census_url: str = CENSUS, source: str = "auto",
                 api: str = API, timeout: float = 20.0, proxies: dict | None = None,
                 token_name: str = "GITHUB_TOKEN", sleep=None):
        usable = token is None or bool(TOKEN_FORM.fullmatch(token))
        self.token = token if usable else None
        self.token_note = "" if usable else (f"{token_name} is set but is not a token (it holds characters no token has); "
                                             "it was not sent.")
        self.census_url, self.source = census_url, source
        self.sleep = sleep or time.sleep
        self.api, self.timeout = api.rstrip("/"), timeout
        proxy = [urllib.request.ProxyHandler(proxies)] if proxies is not None else []
        self.opener = urllib.request.build_opener(_NoRedirect(), *proxy)
        self.census_opener = urllib.request.build_opener(*proxy)
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
        except urllib.error.URLError as e:
            # A socket's own error names the network problem; anything else may quote the
            # request back, headers and all, so only its kind is kept.
            why = str(e.reason) if isinstance(e.reason, OSError) else ""
            return None, {}, b"", mask_text(plain(why or type(e.reason).__name__))
        except http.client.HTTPException as e:
            return None, {}, b"", type(e).__name__
        except OSError as e:
            return None, {}, b"", mask_text(plain(str(e) or type(e).__name__))
        except ValueError as e:
            return None, {}, b"", f"request not sent, {type(e).__name__}"

    def _ask(self, url: str) -> tuple[int | None, dict, bytes, str]:
        """_get, with one retry after a short wait when the failure may pass: no answer, a 5xx,
        or a rate limit whose retry-after is short. GitHub's advice is to wait and retry:
        docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api
        (checked 2026-09-24)."""
        answer = self._get(url)
        status, headers, body, _ = answer
        wait = None
        if status is None or status in (500, 502, 503, 504):
            wait = 1
        elif is_rate_limit(status, headers, _json(body)) and headers.get("x-ratelimit-remaining") != "0":
            # A primary limit resets within the hour, too long to wait for; a secondary one
            # names its wait in retry-after, or else asks for at least a minute.
            after = headers.get("retry-after", "60").strip()
            wait = int(after) if after.isdigit() and int(after) <= MAX_WAIT else None
        if wait is None:
            return answer
        if wait >= 5:
            print(f"awesome-vitals: GitHub API asked to wait {wait} s; waiting once", file=sys.stderr)
        self.sleep(wait)
        return self._get(url)

    def facts(self, name: str) -> dict:
        if not valid_name(name):
            return {**BLANK, "note": "not a repository name, not looked up"}
        if self.source == "census":
            return self.from_census(name, "")
        if self.stop_reason:
            return self.from_census(name, self.stop_reason)
        url = f"{self.api}/repos/{name}"
        status, headers, body, err = self._ask(url)
        # A renamed or transferred repository answers 301 with a Location on
        # /repositories/{id}. Follow it, but never take the token off the API host.
        for _ in range(3):
            if status not in (301, 302, 307, 308):
                break
            if not headers.get("location"):
                return self.from_census(name, f"GitHub API answered {status} without a Location")
            target = urllib.parse.urljoin(url, headers["location"])
            if not target.startswith(self.api + "/") or target == url:
                break
            url = target
            status, headers, body, err = self._ask(url)
        if status is None:
            self.state, self.stop_reason = "unreachable", f"GitHub API unreachable ({err})"
            return self.from_census(name, self.stop_reason)
        data = _json(body)
        if status == 200:
            if isinstance(data, dict) and valid_name(data.get("full_name")):
                spdx, state = licence_state(data.get("license"))
                full = data["full_name"]
                stars = data.get("stargazers_count")
                return {**BLANK, "source": "github", "full_name": full, "http_status": 200,
                        "renamed_to": full if full.lower() != name.lower() else None,
                        "archived": data.get("archived") is True, "pushed_at": iso_date(data.get("pushed_at")),
                        "license": spdx, "license_state": state, "stars": stars if isinstance(stars, int) else None}
            return self.from_census(name, "GitHub API answered 200 without a repository in it")
        if status in (404, 410, 451):
            return {**BLANK, "source": "github", "gone": True, "http_status": status}
        if is_rate_limit(status, headers, data):
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
                with self.census_opener.open(req, timeout=max(self.timeout, 60)) as resp:
                    data = json.load(resp)
                keep = ("full_name", "archived", "pushed_at", "license", "license_state", "stars")
                self._census = {r["full_name"].lower(): {k: r.get(k) for k in keep}
                                for r in data["repositories"]
                                if isinstance(r, dict) and valid_name(r.get("full_name"))}
                self.census_date = iso_date(data.get("generated_at")) or ""
            except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError, KeyError, TypeError,
                    AttributeError) as e:
                reason = getattr(e, "reason", e)
                self.census_error = mask_text(plain(str(reason) or type(reason).__name__))
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
        state = r["license_state"] if r["license_state"] in ("spdx", "none", "non-standard") else None
        spdx = r["license"] if isinstance(r["license"], str) and SPDX_ID.fullmatch(r["license"]) else None
        if state == "spdx" and spdx is None:
            state = None  # the census says licensed but names no usable identifier: unknown, not a finding
        return {**BLANK, "source": "census", "source_date": self.census_date, "github": why,
                "full_name": r["full_name"], "archived": r["archived"] is True, "pushed_at": iso_date(r["pushed_at"]),
                "license": spdx if state == "spdx" else None, "license_state": state,
                "stars": r["stars"] if isinstance(r["stars"], int) else None}


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
        if not k or k == "none":
            continue
        k = ALIASES.get(k, k)
        if k == "unchecked":
            raise ValueError("--fail-on: entries that could not be checked always give exit code 2 under --strict")
        if k not in FAIL_ON_KEYS:
            raise ValueError(f"--fail-on: unknown finding {k!r}; choose from {', '.join(FAIL_ON_KEYS)} or none")
        keys.add(k)
    return keys


def strict_line(results: list[dict], fail_on: set[str]) -> str:
    matched = sum(1 for r in results if fail_on & set(r["findings"]))
    unchecked = sum(1 for r in results if r["status"] == "unchecked")
    named = " or ".join(LABEL[k] for k in FAIL_ON_KEYS if k in fail_on)
    what = f"an entry that is {named}, or one that could not be checked" if named else "an entry that could not be checked"
    return f"This check fails on {what}: {matched} matched, {unchecked} not checked."


def summary(results: list[dict]) -> dict:
    s = {"repositories": len(results), "links": sum(len(r["locations"]) for r in results)}
    s.update({k: sum(1 for r in results if k in r["findings"]) for k in FINDING_KEYS})
    s["no-finding"] = sum(1 for r in results if not r["findings"])
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
    if gh.token_note:
        notes.append(gh.token_note)
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


def warning_lines(warnings: list[dict]) -> list[str]:
    return [f"Warning: {w['file']}:{w['line']}: {w['message']}." for w in warnings]


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
    parts.append(f"{s['no-finding']} with no finding")
    return " · ".join(parts)


def render_text(results: list[dict], files: list[str], scope: str, today: dt.date,
                gh: GitHub, ignored: dict[str, int], fail_on: set[str] | None = None,
                warnings: list[dict] = ()) -> str:
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
        # Columns are as wide as their widest cell and nothing is cut: a shortened name or
        # line list would point at the wrong repository or hide where it is.
        widths = [max(len(cols[i]), *(len(row[i]) for row in rows)) for i in range(len(cols) - 1)]

        def fmt(cells):
            return ("  " + "  ".join([c.ljust(w) for c, w in zip(cells[:-1], widths)] + [cells[-1]])).rstrip()

        lines += [fmt(cols), fmt(["-" * w for w in widths] + ["-" * 4])]
        for k, rs in table:
            lines.append(f"{LABEL[k]} ({len(rs)})")
            lines += [fmt(row) for row in rs]
        lines.append("")
    else:
        lines += ["No finding.", ""]
    lines.append(summary_line(s))
    if fail_on is not None:
        lines.append(strict_line(results, fail_on))
    lines += source_notes(results, gh)
    if ignored_note(ignored):
        lines.append(ignored_note(ignored))
    lines += warning_lines(warnings)
    return "\n".join(lines) + "\n"


def esc(text: object) -> str:
    return (str(text).replace("\\", "\\\\").replace("|", "\\|").replace("<", "&lt;").replace(">", "&gt;")
            .replace("\n", " "))


def render_markdown(results: list[dict], files: list[str], scope: str, today: dt.date,
                    gh: GitHub, ignored: dict[str, int], fail_on: set[str] | None,
                    warnings: list[dict] = ()) -> str:
    many = len(files) > 1
    s = summary(results)
    out = [f"### awesome-vitals: {esc(', '.join(files))}, {esc(scope)}, {today.isoformat()}", "",
           f"{s['links']} {'link' if s['links'] == 1 else 'links'} to {summary_line(s)}.", ""]
    if fail_on is not None:
        out += [strict_line(results, fail_on), ""]
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
    for line in warning_lines(warnings):
        out += ["", esc(line)]
    out += ["", f"<sub>Checked with [awesome-vitals](https://github.com/Keremozdemirra/awesome-vitals) {VERSION}. "
                "Dates, flags and licence identifiers from public repository metadata, "
                "not a verdict on anyone's work.</sub>"]
    return "\n".join(out) + "\n"


def render_json(results: list[dict], files: list[str], scope: str, today: dt.date,
                gh: GitHub, ignored: dict[str, int], fail_on: set[str] | None,
                warnings: list[dict] = ()) -> str:
    doc = {
        "tool": "awesome-vitals", "version": VERSION, "checked": today.isoformat(), "files": files, "scope": scope,
        "fail_on": sorted(fail_on, key=FINDING_KEYS.index) if fail_on is not None else None,
        "summary": summary(results),
        "github": {"state": gh.state, "requests": gh.requests, "stopped": gh.stop_reason or None},
        "census": {"url": mask_url(gh.census_url), "date": gh.census_date or None, "error": gh.census_error or None},
        "notes": source_notes(results, gh),
        "ignored": ignored,
        "warnings": list(warnings),
        "repositories": results,
    }
    return json.dumps(doc, indent=1, ensure_ascii=False) + "\n"


def _progress(i: int, n: int) -> None:
    sys.stderr.write(f"\rchecked {i}/{n}" + ("\n" if i == n else ""))
    sys.stderr.flush()


def main(argv: list[str] | None = None, *, today: dt.date | None = None, api: str = API,
         proxies: dict | None = None, sleep=None) -> int:
    """The command line. `today`, `api`, `proxies` and `sleep` exist for the tests."""
    ap = argparse.ArgumentParser(
        prog="awesome-vitals",
        description="Check every GitHub repository linked from a Markdown list and report which entries are "
                    "archived, gone, renamed, abandoned, stale or unlicensed, with their line numbers.")
    ap.add_argument("files", nargs="+", metavar="FILE", help="Markdown files to read")
    fmt = ap.add_mutually_exclusive_group()
    fmt.add_argument("--markdown", action="store_true", help="print a Markdown report, for an issue or a job summary")
    fmt.add_argument("--json", action="store_true", help="print JSON")
    ap.add_argument("--strict", action="store_true",
                    help=f"exit 1 if an entry has a finding named in --fail-on (default {DEFAULT_FAIL_ON}), "
                         "else 2 if an entry could not be checked")
    ap.add_argument("--fail-on", metavar="LIST",
                    help="comma-separated findings that make --strict exit 1, or none; implies --strict unless none. "
                         "One or more of: " + ", ".join(FAIL_ON_KEYS))
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
                         "github: GitHub API only; census: census only, nothing sent to the GitHub API")
    ap.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):  # a console that cannot print a character should not crash the run
        sys.stdout.reconfigure(errors="replace")

    try:
        fail_on = parse_fail_on(a.fail_on if a.fail_on is not None else DEFAULT_FAIL_ON)
        only = parse_only_lines(a.only_lines) if a.only_lines else None
    except ValueError as e:
        ap.error(str(e))
    # --fail-on none reports without failing; --strict on top of it fails only on what could not be checked
    strict = a.strict or bool(a.fail_on is not None and fail_on)

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
        # git diff --relative leaves out a file outside the working directory, which would
        # read as "nothing added" and pass a strict check without looking at it.
        outside = [f for f in a.files if not inside_cwd(f)]
        if outside:
            print(f"awesome-vitals: --diff: {plain(outside[0], 400)} is outside the working directory; "
                  "run from a directory that contains every file, such as the repository root", file=sys.stderr)
            return 2
        try:
            selected = git_added_lines(a.diff, a.files)
        except (ValueError, RuntimeError) as e:
            print(f"awesome-vitals: {plain(e, 400)}", file=sys.stderr)
            return 2
        scope = f"lines added in {a.diff}"

    warnings: list[dict] = []
    entries, ignored = collect(sources, selected, warnings)
    token_name = "GITHUB_TOKEN" if os.environ.get("GITHUB_TOKEN") else "GH_TOKEN"
    token = (os.environ.get(token_name) or "").strip() or None
    gh = GitHub(token=token, census_url=a.census, source=a.source, api=api, proxies=proxies,
                token_name=token_name, sleep=sleep)
    today = today or dt.date.today()
    try:
        results = examine(entries, gh, today, _progress if sys.stderr.isatty() and entries else None)
    except KeyboardInterrupt:
        return 130

    if a.json:
        sys.stdout.write(render_json(results, a.files, scope, today, gh, ignored, fail_on if strict else None,
                                     warnings))
    elif not entries:
        msg = f"No links to GitHub repositories {'on those lines' if selected is not None else 'found'}."
        if a.markdown:
            msg = f"### awesome-vitals: {esc(', '.join(a.files))}, {esc(scope)}, {today.isoformat()}\n\n{msg}"
        else:
            msg = f"awesome-vitals · {', '.join(a.files)} · {scope} · {today.isoformat()}\n{msg}"
        extra = ([ignored_note(ignored)] if ignored_note(ignored) else []) + warning_lines(warnings)
        sys.stdout.write(msg + "\n" + "".join((esc(x) if a.markdown else x) + "\n" for x in extra))
    elif a.markdown:
        sys.stdout.write(render_markdown(results, a.files, scope, today, gh, ignored, fail_on if strict else None,
                                         warnings))
    else:
        sys.stdout.write(render_text(results, a.files, scope, today, gh, ignored, fail_on if strict else None,
                                     warnings))
    if strict and any(fail_on & set(r["findings"]) for r in results):
        return 1
    if strict and any(r["status"] == "unchecked" for r in results):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
