#!/usr/bin/env python3
"""vitals — answer vetting questions from the local ecosystem census.

The other half of this pipeline is `agent-vitals`, run by GitHub Actions. The
contract between them — field names, schedules, what each side may not assume
— is `agent-vitals/docs/PIPELINE.md`. Change that file before changing either
side.

`agent-vitals` measures 36,000+ MCP and agent repositories every morning:
licence, maintenance status, age, stars. Two uses, and the second is the one
that changes how tools get chosen here.

  lookup   Given a repository, answer the vetting questions offline and
           instantly, instead of three GitHub API calls. Licence state is the
           one that has twice stopped an install this week.

  gaps     Given a topic, list what is alive, properly licensed and popular —
           minus everything already installed. Vetting a link as it arrives is
           defensive; this asks what is missing, which is the question a link
           dump never answers.

The census is a snapshot with a date. It is evidence about a moment, not a
live check: for anything load-bearing, confirm against the source.

    python3 tools/vitals.py <owner/repo>
    python3 tools/vitals.py --gaps <substring> [--min-stars N] [--limit N]
    python3 tools/vitals.py --summary
"""

from __future__ import annotations

from remote_text import neutralise

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CENSUS = ROOT / "agent-vitals" / "data" / "servers.json"
HISTORY = ROOT / "agent-vitals" / "data" / "history.csv"
CLAUDE = Path.home() / ".claude"
CRITERIA = ROOT / "rota" / "vetting.yaml"

# Anything at or past this is a reason to look elsewhere before looking closer.
DEAD = {"abandoned"}
USABLE_LICENCE = "spdx"   # the census's own vocabulary: spdx | none | non-standard


STALE_AFTER_DAYS = 2


def load(warn: bool = True) -> dict:
    if not CENSUS.exists():
        sys.exit(f"census not found at {CENSUS.relative_to(ROOT)} — run agent-vitals first")
    d = json.loads(CENSUS.read_text(encoding="utf-8"))
    # The producer runs in CI and the consumer runs here. If the producer stops,
    # nothing here errors: this file keeps answering, and every answer is
    # yesterday's ground presented as today's. A pipeline whose halves cannot
    # see each other fails silently at the seam, so the seam is checked.
    if warn:
        import datetime as _dt
        try:
            age = (_dt.date.today()
                   - _dt.date.fromisoformat((d.get("generated_at") or "")[:10])).days
        except ValueError:
            age = None
        if age is not None and age > STALE_AFTER_DAYS:
            print(f"  [!] census is {age} days old (generated {d.get('generated_at','')[:10]}).")
            print("      The collector runs daily in CI; this old means it stopped, or the")
            print("      pull did. Fix that before trusting anything below.")
    return d


def crosscheck(counts: dict) -> tuple[list[str], str]:
    """Compare what we recomputed against what the collector already recorded.

    The collector writes its own totals to history.csv. Recomputing them here
    is a second, independent path to the same fact — and a second path is only
    worth having if it is compared. This checker exists because it was not:
    the first version of this file recomputed the licence split with the wrong
    vocabulary, printed 24.5% where the source said 16.7%, and nothing noticed
    until a human read both numbers side by side.

    A silent disagreement between two computations of one fact is worse than
    either being wrong alone, because it looks like corroboration.
    """
    # Read the COMMITTED history, not the working copy. The working copy is a
    # file anything downstream can rewrite, and a check that reads a file its
    # own side can touch is a check comparing an output against itself — which
    # reports "agree" and looks like corroboration. Found by the producer side:
    # the working copy had already been rewritten once by something that was
    # neither the collector nor this reader.
    import subprocess
    repo = HISTORY.parent.parent
    src, text = "committed (HEAD)", None
    r = subprocess.run(["git", "-C", str(repo), "show", "HEAD:data/history.csv"],
                       capture_output=True, text=True)
    if r.returncode == 0 and r.stdout.strip():
        text = r.stdout
        dirty = subprocess.run(["git", "-C", str(repo), "diff", "--quiet",
                                "HEAD", "--", "data/history.csv"])
        if dirty.returncode != 0:
            src = "committed (HEAD) — NOTE: the working copy differs from it"
    elif HISTORY.exists():
        src, text = "working copy — could not read HEAD, so this is unverified", HISTORY.read_text(encoding="utf-8")
    if text is None:
        return (["history.csv unreadable from HEAD and from disk"], src)
    rows = [r for r in text.splitlines() if r.strip()]
    if len(rows) < 2:
        return ([], src)
    head, last = rows[0].split(","), rows[-1].split(",")
    row = dict(zip(head, last))
    out = []
    for ours, theirs in (("repositories", "repositories"), ("active", "active"),
                         ("slowing", "slowing"), ("stale", "stale"),
                         ("abandoned", "abandoned"), ("none", "no_licence"),
                         ("odd", "nonstandard_licence")):
        if theirs not in row or ours not in counts:
            continue
        try:
            expected = int(row[theirs])
        except ValueError:
            continue
        if counts[ours] != expected:
            out.append(f"{ours}: this file says {counts[ours]:,}, "
                       f"the collector recorded {expected:,}")
    return (out, src)


def installed() -> set[str]:
    """Lowercased names of everything already here, to subtract from a gap list."""
    names: set[str] = set()
    for d in (CLAUDE / "skills", CLAUDE / "agents"):
        if d.is_dir():
            names |= {p.stem.lower() if p.is_file() else p.name.lower() for p in d.iterdir()}
    cfg = Path.home() / ".claude.json"
    if cfg.exists():
        try:
            names |= {k.lower() for k in (json.loads(cfg.read_text())
                                          .get("mcpServers") or {})}
        except (json.JSONDecodeError, OSError):
            pass
    pf = CLAUDE / "plugins" / "installed_plugins.json"
    if pf.exists():
        try:
            names |= {k.split("@")[0].lower()
                      for k in (json.loads(pf.read_text()).get("plugins") or {})}
        except (json.JSONDecodeError, OSError):
            pass
    return names


def criteria() -> dict:
    """Fit rules, declared in vetting.yaml rather than buried here.

    Reach is not fit. A repository with fifty thousand stars that does a job
    already covered is not a candidate, and one that matches a category
    already decided against is not a new question. Both judgements need to be
    arguable, which means they belong in a file the reader can edit.
    """
    if not CRITERIA.exists():
        return {}
    try:
        import yaml
    except ImportError:
        return {}
    try:
        return yaml.safe_load(CRITERIA.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def judge(r: dict, c: dict) -> tuple[str, str]:
    """(verdict, why) for one record against the declared criteria."""
    prior = (c.get("declined_repos") or {})
    for k, why in prior.items():
        if k.lower() == r["full_name"].lower():
            return "declined before", why
    req = c.get("require") or {}
    if r.get("stars", 0) < req.get("min_stars", 0):
        return "below floor", f"under {req['min_stars']} stars — noise floor, not a quality judgement"
    if req.get("min_age_days"):
        import datetime as _dt
        try:
            age = (_dt.date.today() - _dt.date.fromisoformat(r.get("created_at", ""))).days
            if age < req["min_age_days"]:
                return "too young", f"{age} days old — has not yet shown whether anyone maintains it"
        except ValueError:
            pass
    hay = (f"{r['full_name']} {r.get('description') or ''} "
           f"{' '.join(r.get('topics') or [])}").lower()
    for name, spec in (c.get("declined") or {}).items():
        if any(t in hay for t in spec.get("match", [])):
            return "declined", f"{name} — {spec.get('why','')}"
    for job, terms in (c.get("covered") or {}).items():
        if any(t in hay for t in terms):
            return "covered", f"'{job}' already has an incumbent here"
    doms = c.get("domains") or []
    if doms and not any(t in hay for row in doms for t in row):
        return "no target", "outside every domain the work actually touches"
    return "look", ""


def verdict(r: dict) -> list[str]:
    """The lines that decide, in the order they decide."""
    out = []
    lic, state = r.get("license"), (r.get("license_state") or "").lower()
    if state == "none":
        out.append("NO LICENCE FILE — grants nothing, whatever the README invites")
    elif state != USABLE_LICENCE:
        out.append(f"licence is present but not a standard identifier ({state}) — "
                   "licensed, yet not in a form a procurement review waves through")
    if r.get("archived"):
        out.append("ARCHIVED by its owner")
    if r.get("status") in DEAD:
        out.append(f"no push in {r.get('days_since_push')} days")
    if r.get("is_fork"):
        out.append("this is a FORK — check whether the upstream is what you want")
    return out


def show(r: dict, census_date: str) -> None:
    print(f"  {r['full_name']}  ({r.get('group')})")
    print(f"    {r.get('stars')}★  {r.get('forks')} fork  ·  {r.get('language') or '—'}"
          f"  ·  licence: {r.get('license') or 'NONE'} [{r.get('license_state')}]")
    print(f"    created {r.get('created_at')}  ·  last push {r.get('pushed_at')}"
          f" ({r.get('days_since_push')}d, {r.get('status')})")
    if r.get("description"):
        print(f"    {neutralise(r['description'])}")
    for line in verdict(r):
        print(f"    [!] {line}")
    print(f"    census {census_date} — confirm at the source before anything load-bearing")


def gap_hits(repos: list[dict], term: str, min_stars: int, have: set[str]) -> list[dict]:
    """Alive, SPDX-licensed, popular enough, matching the term, not installed; by stars."""
    hits = []
    for r in repos:
        if r.get("status") != "active" or r.get("archived") or r.get("is_fork"):
            continue
        if (r.get("license_state") or "") != "spdx":
            continue
        if r.get("stars", 0) < min_stars:
            continue
        hay = f"{r['full_name']} {r.get('description') or ''} {' '.join(r.get('topics') or [])}".lower()
        if term not in hay:
            continue
        short = r["full_name"].split("/")[-1].lower()
        if short in have or any(short in h or h in short for h in have if len(h) > 4):
            continue
        hits.append(r)
    hits.sort(key=lambda r: -r.get("stars", 0))
    return hits


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__.strip())
        return 2
    d = load()
    date = (d.get("generated_at") or "")[:10]
    repos = d["repositories"]

    if args[0] == "--summary":
        n = len(repos)
        by = {}
        for r in repos:
            by[r.get("status")] = by.get(r.get("status"), 0) + 1
        # Two different problems, and conflating them overstates one of them:
        # no licence file at all grants nothing; a licence GitHub cannot map to
        # an SPDX identifier is licensed, just not in a form procurement waves
        # through.
        none = sum(1 for r in repos if r.get("license_state") == "none")
        odd = sum(1 for r in repos if r.get("license_state") == "non-standard")
        print(f"  census {date} · {n:,} repositories")
        for k in ("active", "slowing", "stale", "abandoned"):
            if k in by:
                print(f"    {k:<12} {by[k]:>6,}  {100*by[k]/n:>5.1f}%")
        print(f"    no licence   {none:>6,}  {100*none/n:>5.1f}%  — grants nothing, whatever the README says")
        print(f"    non-standard {odd:>6,}  {100*odd/n:>5.1f}%  — licensed, but not in a form procurement accepts")

        counts = {"repositories": n, "none": none, "odd": odd, **by}
        problems, src = crosscheck(counts)
        # Two different severities. A totals mismatch means one of the two
        # computations is wrong and neither may be quoted. A working copy that
        # differs from HEAD is a provenance note: the numbers checked out, but
        # they were checked against what was published, not against what is on
        # disk. Reporting the second at the volume of the first is how a
        # checker earns the right to be ignored.
        if problems:
            print("\n  [!] this file and the collector disagree — do not quote either until resolved:")
            for line in problems:
                print(f"      {line}")
            return 1
        if "NOTE" in src:
            print("  totals agree with the committed history.csv. The working copy of that")
            print("  file differs from HEAD — the check read what was published, not what")
            print("  is on disk, which is the intent; noted so the provenance is visible.")
        else:
            print("  checked against the collector's committed history.csv — they agree")
        return 0

    if args[0] in ("--new", "--sync"):
        # --sync pulls first: the census is produced in CI every morning and a
        # local copy nobody refreshes is a stale answer that looks current.
        if args[0] == "--sync":
            import subprocess
            r = subprocess.run(["git", "-C", str(CENSUS.parent.parent), "pull",
                                "--ff-only", "-q"], capture_output=True, text=True)
            if r.returncode:
                print(f"  pull failed: {(r.stderr or r.stdout).strip()[:120]}")
            d = load()
            date = (d.get("generated_at") or "")[:10]
            repos = d["repositories"]

        days = int(args[args.index("--days") + 1]) if "--days" in args else 1
        limit = int(args[args.index("--limit") + 1]) if "--limit" in args else 12
        min_stars = int(args[args.index("--min-stars") + 1]) if "--min-stars" in args else 100
        seen = sorted({r.get("first_seen") for r in repos if r.get("first_seen")})
        if len(seen) < 2:
            print(f"  census {date}: one run so far, so nothing is new yet.")
            print("  Arrivals separate from the baseline on the second run.")
            return 0
        recent = set(seen[-days:])
        have = installed()
        c = criteria()
        pool = [r for r in repos
                if r.get("first_seen") in recent
                and r.get("status") == "active" and not r.get("archived")
                and not r.get("is_fork")
                and (r.get("license_state") or "") == "spdx"
                and r.get("stars", 0) >= min_stars
                and r["full_name"].split("/")[-1].lower() not in have]
        graded = [(r, *judge(r, c)) for r in pool]
        hits = [r for r, v, _ in graded if v == "look"]
        hits.sort(key=lambda r: -r.get("stars", 0))
        skipped = {}
        for _, v, why in graded:
            if v != "look":
                skipped[v] = skipped.get(v, 0) + 1
        print(f"  arrived in the last {days} census run(s) · active, SPDX, {min_stars}+ stars,"
              f" not already installed  ({len(hits)} of {sum(1 for r in repos if r.get('first_seen') in recent)} arrivals)")
        for r in hits[:limit]:
            print(f"    {r.get('stars'):>6,}★  {r.get('license'):<12} {r['full_name']}")
            if r.get("description"):
                print(f"             {neutralise(r['description'], 88)}")
        if not hits:
            print("    nothing worth a look — which is the usual answer and the point of filtering")
        if skipped:
            print("    filtered out: " + ", ".join(f"{n} {k}" for k, n in sorted(skipped.items())))
        return 0

    if args[0] == "--candidates":
        # Kerem, 2026-09-21: the census should surface repositories that could
        # become a product, a component of one, or a place to contribute, without
        # him forwarding links by hand. One term per domain word in vetting.yaml,
        # written to the ledger so the weekly brief can link it.
        out = ROOT / "rota" / "ledger" / "census-candidates.md"
        terms = [w for group in (criteria().get("domains") or []) for w in group]
        terms += ["automation", "n8n", "seo", "lead-generation", "linkedin", "game", "telemetry", "job-search"]
        have = installed()
        min_stars = int(args[args.index("--min-stars") + 1]) if "--min-stars" in args else 150
        lines = [f"# Census candidates, {date}", "",
                 "Written by `python3 rota/tools/vitals.py --candidates` (weekly). Active, SPDX-licensed, "
                 f"{min_stars}+ stars, not installed, matched on name, description or topics. A row is evidence "
                 "about a date; the tools chat vets before anything is installed. Product angle: a repository "
                 "here is a possible product, a component of one, or a place to contribute.", ""]
        seen: set[str] = set()
        for term in terms:
            hits = [r for r in gap_hits(repos, term.lower(), min_stars, have) if r["full_name"] not in seen]
            if not hits:
                continue
            lines += [f"## {term}", ""]
            for r in hits[:8]:
                seen.add(r["full_name"])
                lines.append(f"- {r.get('stars'):,}★ {r.get('license')} `{r['full_name']}`: {neutralise(r.get('description') or '', 110)}")
            lines.append("")
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"{out}: {len(seen)} repositories across {len(terms)} terms, census {date}")
        return 0

    if args[0] == "--gaps":
        if len(args) < 2:
            sys.exit("usage: --gaps <substring> [--min-stars N] [--limit N]")
        term = args[1].lower()
        min_stars = int(args[args.index("--min-stars") + 1]) if "--min-stars" in args else 200
        limit = int(args[args.index("--limit") + 1]) if "--limit" in args else 15
        have = installed()
        hits = gap_hits(repos, term, min_stars, have)
        print(f"  '{term}' · active, SPDX-licensed, {min_stars}+ stars, not already installed"
              f"  ({len(hits)} found, census {date})")
        for r in hits[:limit]:
            print(f"    {r.get('stars'):>6,}★  {r.get('license'):<12} {r['full_name']}")
            if r.get("description"):
                print(f"             {neutralise(r['description'], 88)}")
        if not hits:
            print("    nothing this census can offer that is not already here")
        return 0

    name = args[0].lower().removeprefix("https://github.com/").strip("/")
    exact = [r for r in repos if r["full_name"].lower() == name]
    if exact:
        show(exact[0], date)
        return 0
    short = name.split("/")[-1]
    near = [r for r in repos if r["full_name"].lower().split("/")[-1] == short]
    if near:
        print(f"  '{args[0]}' is not in the census, but the same name is, under other owners —")
        print("  the star gap is the tell:")
        for r in sorted(near, key=lambda r: -r.get("stars", 0))[:6]:
            print(f"    {r.get('stars'):>6,}★  {r['full_name']}")
        return 0
    print(f"  {args[0]} is not in this census.")
    print("  That is not a verdict: the census covers MCP and agent-tooling topics")
    print("  above a star floor. Vet it the long way.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
