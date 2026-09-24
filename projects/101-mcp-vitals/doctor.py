#!/usr/bin/env python3
"""mcp-vitals: check the MCP servers you actually run.

agent-vitals (github.com/Keremozdemirra/agent-vitals) takes a daily census of
the agent tooling ecosystem. This measures the part of it on your machine. It reads the MCP server entries in the config files of the
clients installed here (Claude Code, Claude Desktop, Cursor, VS Code,
Windsurf, Gemini CLI, Codex), works out which package or repository each one
starts, and reports for each: when the repository behind it was last pushed,
whether it is archived, what licence it carries, whether the package is
deprecated, and whether the entry is pinned to a version at all.

Standard library only, one file, so it runs without installing anything:

  curl -sL https://raw.githubusercontent.com/Keremozdemirra/mcp-vitals/main/doctor.py | python3 -

What it reads and what it sends:

- From each config it reads the server name, `command`, `args` and `url`.
  It never reads `env` or `headers`, which is where API keys live, and
  nothing it prints or sends comes from them.
- It sends package names to the npm and PyPI registries and owner/name pairs
  to the GitHub API, and nothing else. `--offline` sends nothing and reports
  only what the config files themselves say.
- Nothing is installed, started or executed.

The findings are dates, flags and licence identifiers, never a verdict on
anyone's code. A finished tool can go a year without a push and still work.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

VERSION = "0.1.0"
UA = "mcp-vitals (+https://github.com/Keremozdemirra/mcp-vitals)"
CENSUS = "https://raw.githubusercontent.com/Keremozdemirra/agent-vitals/main/data/servers.json"

# Package runners, and where the package name sits in their arguments.
NODE_RUNNERS = {"npx", "bunx", "pnpx"}
DLX_RUNNERS = {"pnpm", "yarn", "bun"}  # `pnpm dlx pkg`, `yarn dlx pkg`, `bun x pkg`
PY_RUNNERS = {"uvx", "pipx", "uv"}      # `uvx pkg`, `pipx run pkg`, `uv tool run pkg`
# docker flags that take a value, so the image is not mistaken for one of them
DOCKER_VALUE_FLAGS = {"-e", "--env", "--env-file", "-v", "--volume", "-p", "--publish", "--name", "--network",
                      "--net", "-w", "--workdir", "--mount", "-u", "--user", "--entrypoint", "-l", "--label",
                      "--platform", "--pull", "--add-host", "-h", "--hostname", "--cpus", "-m", "--memory"}
GITHUB_URL = re.compile(r"github\.com[/:]([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?(?:[/#?].*)?$")


# ---------------------------------------------------------------- discovery

def config_locations(home: Path, cwd: Path) -> list[tuple[str, Path, str]]:
    """(client, path, key) for every config file a known client might use."""
    if sys.platform == "darwin":
        desktop = home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    elif sys.platform.startswith("win"):
        desktop = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming")) / "Claude" / "claude_desktop_config.json"
    else:
        desktop = home / ".config" / "Claude" / "claude_desktop_config.json"
    return [
        ("Claude Code", home / ".claude.json", "mcpServers"),
        ("Claude Code (project)", cwd / ".mcp.json", "mcpServers"),
        ("Claude Desktop", desktop, "mcpServers"),
        ("Cursor", home / ".cursor" / "mcp.json", "mcpServers"),
        ("Cursor (project)", cwd / ".cursor" / "mcp.json", "mcpServers"),
        ("VS Code (project)", cwd / ".vscode" / "mcp.json", "servers"),
        ("Windsurf", home / ".codeium" / "windsurf" / "mcp_config.json", "mcpServers"),
        ("Gemini CLI", home / ".gemini" / "settings.json", "mcpServers"),
        ("Codex", home / ".codex" / "config.toml", "mcp_servers"),
    ]


def read_config(path: Path) -> dict | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if path.suffix == ".toml":
        try:
            import tomllib
        except ImportError:  # Python < 3.11
            return None
        try:
            return tomllib.loads(text)
        except tomllib.TOMLDecodeError:
            return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def entries_in(data: dict, key: str) -> list[tuple[str, dict]]:
    """Server entries under `key`, plus Claude Code's per-project ones."""
    out = []
    block = data.get(key)
    if isinstance(block, dict):
        out += [(name, spec) for name, spec in block.items() if isinstance(spec, dict)]
    # ~/.claude.json keeps servers added with `--scope local` under projects.<path>.mcpServers
    projects = data.get("projects")
    if key == "mcpServers" and isinstance(projects, dict):
        for proj, pdata in projects.items():
            block = pdata.get("mcpServers") if isinstance(pdata, dict) else None
            if isinstance(block, dict):
                out += [(f"{name} [{Path(proj).name}]", spec) for name, spec in block.items() if isinstance(spec, dict)]
    return out


def discover(home: Path, cwd: Path, extra: list[Path]) -> tuple[list[dict], list[str]]:
    servers, searched = [], []
    locations = config_locations(home, cwd) + [("--config", p, "") for p in extra]
    seen_paths = set()
    for client, path, key in locations:
        path = path.expanduser()
        if path.resolve() in seen_paths or not path.is_file():
            continue
        seen_paths.add(path.resolve())
        data = read_config(path)
        if data is None:
            searched.append(f"{path} (unreadable)")
            continue
        searched.append(str(path))
        keys = [key] if key else ["mcpServers", "servers", "mcp_servers"]
        for k in keys:
            for name, spec in entries_in(data, k):
                # command/args/url only. env and headers carry secrets and are never touched.
                args = spec.get("args") if isinstance(spec.get("args"), list) else []
                servers.append({
                    "client": client, "config": str(path), "name": name,
                    "command": str(spec.get("command") or ""),
                    "args": [str(a) for a in args],
                    "url": str(spec.get("url") or spec.get("serverUrl") or spec.get("httpUrl") or ""),
                })
    return servers, searched


# ---------------------------------------------------------------- resolution

def split_spec(spec: str, sep: str) -> tuple[str, str | None]:
    """'@scope/pkg@1.2' -> ('@scope/pkg', '1.2'); 'pkg==1.2' -> ('pkg', '1.2')."""
    if sep == "@":
        at = spec.rfind("@")
        if at > 0:
            return spec[:at], spec[at + 1:] or None
        return spec, None
    m = re.match(r"^([A-Za-z0-9_.\-\[\]]+?)\s*(==|>=|<=|~=|@)\s*(.+)$", spec)
    if m:
        return re.sub(r"\[.*\]$", "", m.group(1)), m.group(3) if m.group(2) == "==" else None
    return re.sub(r"\[.*\]$", "", spec), None


def first_positional(args: list[str], value_flags: set[str] = frozenset()) -> tuple[int, str] | None:
    skip = False
    for i, a in enumerate(args):
        if skip:
            skip = False
            continue
        if a.startswith("-"):
            if a in value_flags:
                skip = True
            continue
        return i, a
    return None


def github_from(text: str) -> str | None:
    m = GITHUB_URL.search(text or "")
    return f"{m.group(1)}/{m.group(2)}" if m else None


def git_remote(path: Path) -> str | None:
    """owner/name of the GitHub origin of the checkout containing `path`, read from .git/config."""
    for d in [path, *path.parents]:
        cfg = d / ".git" / "config"
        if cfg.is_file():
            try:
                text = cfg.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return None
            m = re.search(r'\[remote "origin"\][^\[]*?url\s*=\s*(\S+)', text)
            return github_from(m.group(1)) if m else None
    return None


def resolve(s: dict) -> dict:
    """Work out what an entry starts: an npm or PyPI package, a container image, a checkout, a remote URL."""
    # split on both separators: a Windows config read on any platform still names npx.cmd
    cmd = re.split(r"[\\/]", s["command"])[-1].lower().removesuffix(".cmd").removesuffix(".exe")
    args = list(s["args"])
    r = {"kind": "unknown", "package": None, "version": None, "pinned": None, "repo": None, "detail": ""}

    if s["url"] and not cmd:
        r.update(kind="remote", detail=urllib.parse.urlsplit(s["url"]).netloc)
        return r

    if cmd in DLX_RUNNERS and args and args[0] in ("dlx", "x"):
        cmd, args = "npx", args[1:]
    if cmd in NODE_RUNNERS:
        # `npx -p pkg bin` names the package with -p; otherwise it is the first positional
        pkg = None
        for flag in ("-p", "--package"):
            if flag in args and args.index(flag) + 1 < len(args):
                pkg = args[args.index(flag) + 1]
        if pkg is None:
            pos = first_positional(args, {"-p", "--package", "-c", "--call"})
            pkg = pos[1] if pos else None
        if pkg:
            if pkg.startswith(("github:", "git+", "https://")) or github_from(pkg):
                r.update(kind="git", repo=github_from(pkg) or pkg.removeprefix("github:").split("#")[0], pinned="#" in pkg)
            else:
                name, ver = split_spec(pkg, "@")
                r.update(kind="npm", package=name, version=ver, pinned=bool(ver) and ver not in ("latest", "next"))
        return r

    if cmd in PY_RUNNERS:
        if cmd == "pipx" and args[:1] == ["run"]:
            args = args[1:]
        elif cmd == "uv":
            if args[:2] != ["tool", "run"]:
                return r
            args = args[2:]
        pkg = None
        if "--from" in args and args.index("--from") + 1 < len(args):
            pkg = args[args.index("--from") + 1]
        if pkg is None:
            pos = first_positional(args, {"--from", "--with", "--python", "-p", "--index", "--index-url", "--spec"})
            pkg = pos[1] if pos else None
        if pkg:
            if github_from(pkg):
                r.update(kind="git", repo=github_from(pkg), pinned="@" in pkg.split("github.com", 1)[-1])
            else:
                name, ver = split_spec(pkg, "==")
                r.update(kind="pypi", package=name, version=ver, pinned=bool(ver))
        return r

    if cmd in ("docker", "podman") and args[:1] == ["run"]:
        pos = first_positional(args[1:], DOCKER_VALUE_FLAGS)
        if pos:
            image = pos[1]
            digest = "@sha256:" in image
            tag = image.rsplit(":", 1)[1] if ":" in image.rsplit("/", 1)[-1] else None
            r.update(kind="image", package=image, pinned=digest or (tag not in (None, "latest")))
            m = re.match(r"^ghcr\.io/([^/]+)/([^/:@]+)", image)
            if m:
                r["repo"] = f"{m.group(1)}/{m.group(2)}"
        return r

    # node/python/a binary pointing at a local path: use the checkout's origin
    for a in [s["command"], *args]:
        if github_from(a):
            r.update(kind="git", repo=github_from(a))
            return r
    for a in [*args, s["command"]]:
        p = Path(os.path.expanduser(a))
        if p.is_absolute() and p.exists():
            r.update(kind="local", detail=str(p), repo=git_remote(p.parent if p.is_file() else p))
            return r
    return r


# ---------------------------------------------------------------- facts

class Net:
    def __init__(self, offline: bool, token: str | None, timeout: float = 20, census: bool = True):
        self.offline, self.token, self.timeout = offline, token, timeout
        self.use_census = census  # off in the hook: the published index is 26 MB, too slow to wait on
        self.cache: dict[str, object] = {}
        self.github_down = False
        self.census: dict | None = None

    def get(self, url: str, headers: dict | None = None):
        if url in self.cache:
            return self.cache[url]
        req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                val = json.load(resp)
        except urllib.error.HTTPError as e:
            val = {"_error": e.code}
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
            val = {"_error": type(e).__name__}
        self.cache[url] = val
        return val

    def npm(self, name: str) -> dict:
        d = self.get("https://registry.npmjs.org/" + urllib.parse.quote(name, safe="@"))
        if "_error" in d:
            return {"error": f"npm {d['_error']}"}
        latest = (d.get("dist-tags") or {}).get("latest")
        v = (d.get("versions") or {}).get(latest) or {}
        repo = v.get("repository") or d.get("repository") or {}
        return {"latest": latest, "released": (d.get("time") or {}).get(latest),
                "deprecated": v.get("deprecated") or None,
                "repo": github_from(repo.get("url", "") if isinstance(repo, dict) else str(repo))
                or github_from(v.get("homepage") or d.get("homepage") or "")}

    def pypi(self, name: str) -> dict:
        d = self.get(f"https://pypi.org/pypi/{urllib.parse.quote(name)}/json")
        if "_error" in d:
            return {"error": f"PyPI {d['_error']}"}
        info = d.get("info") or {}
        urls = list((info.get("project_urls") or {}).values()) + [info.get("home_page") or ""]
        files = d.get("urls") or []
        released = min((f.get("upload_time_iso_8601") for f in files if f.get("upload_time_iso_8601")), default=None)
        repo = next((github_from(u) for u in urls if github_from(u)), None)
        return {"latest": info.get("version"), "released": released,
                "deprecated": "yanked: " + (info.get("yanked_reason") or "") if info.get("yanked") else None, "repo": repo}

    def github(self, repo: str) -> dict:
        if not self.github_down:
            h = {"Accept": "application/vnd.github+json"}
            if self.token:
                h["Authorization"] = f"Bearer {self.token}"
            d = self.get(f"https://api.github.com/repos/{repo}", h)
            if "_error" not in d:
                lic = d.get("license") or {}
                spdx = lic.get("spdx_id")
                return {"source": "GitHub API", "full_name": d.get("full_name"), "pushed_at": d.get("pushed_at"),
                        "archived": bool(d.get("archived")), "stars": d.get("stargazers_count"),
                        "open_issues": d.get("open_issues_count"),
                        "license": spdx if spdx and spdx != "NOASSERTION" else None,
                        "license_state": "none" if not lic else ("non-standard" if spdx in (None, "", "NOASSERTION") else "spdx")}
            if d["_error"] == 404:
                return {"error": "repository not found (deleted, renamed or private)"}
            # rate limited or unreachable: fall back to the census for the rest of the run
            self.github_down = True
        return self.from_census(repo)

    def from_census(self, repo: str) -> dict:
        if not self.use_census:
            return {"error": "GitHub API unavailable"}
        if self.census is None:
            data = self.get(CENSUS)
            self.census = {r["full_name"].lower(): r for r in (data.get("repositories") or []) if isinstance(r, dict)}
            self.census_date = (data.get("generated_at") or "")[:10]
        r = self.census.get(repo.lower())
        if not r:
            return {"error": "GitHub API unavailable and not in the census"}
        return {"source": f"census {self.census_date}", "full_name": r["full_name"], "pushed_at": r.get("pushed_at"),
                "archived": bool(r.get("archived")), "stars": r.get("stars"), "open_issues": r.get("open_issues"),
                "license": r.get("license"), "license_state": r.get("license_state")}


# Same thresholds as collect.py's bucket(), so a server reads the same here as in the census.
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
        return (today - dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).date()).days
    except ValueError:
        return None


def examine(s: dict, net: Net | None, today: dt.date) -> dict:
    r = resolve(s)
    out = {**s, **r, "flags": [], "status": "unknown", "days_since_push": None, "facts": {}}
    reg = {}
    if net and r["kind"] == "npm":
        reg = net.npm(r["package"])
    elif net and r["kind"] == "pypi":
        reg = net.pypi(r["package"])
    if reg:
        out["facts"]["registry"] = reg
        out["repo"] = out["repo"] or reg.get("repo")
        if reg.get("deprecated"):
            out["flags"].append("deprecated")
        if reg.get("error"):
            out["flags"].append("package not found" if "404" in reg["error"] else "registry unreachable")
    if net and out["repo"]:
        gh = net.github(out["repo"])
        out["facts"]["repository"] = gh
        if gh.get("error"):
            out["flags"].append("repository missing" if "not found" in gh["error"] else "repository unknown")
        else:
            out["repo"] = gh.get("full_name") or out["repo"]
            out["days_since_push"] = days_since(gh.get("pushed_at"), today)
            out["status"] = bucket(out["days_since_push"], gh.get("archived"))
            if gh.get("license_state") == "none":
                out["flags"].append("no licence file")
            elif gh.get("license_state") == "non-standard":
                out["flags"].append("non-standard licence")
    if r["kind"] in ("npm", "pypi", "image", "git") and r["pinned"] is False:
        out["flags"].append("unpinned")
    if r["kind"] == "remote":
        out["status"] = "remote"
    elif r["kind"] == "unknown":
        out["flags"].append("could not tell what this starts")
    elif r["kind"] in ("npm", "pypi", "image", "local") and not out["repo"] and net:
        out["flags"].append("no source repository linked")
    if out["status"] in ("abandoned", "archived"):
        out["flags"].insert(0, out["status"])
    return out


# ---------------------------------------------------------------- report

# The flags worth failing a CI job over. `unpinned` and `stale` are worth a look, not a red build.
SERIOUS = {"archived", "abandoned", "deprecated", "no licence file", "repository missing", "package not found"}


def what(r: dict) -> str:
    if r["kind"] in ("npm", "pypi"):
        return f"{r['kind']}:{r['package']}" + (f"@{r['version']}" if r["version"] else "")
    if r["kind"] == "image":
        return r["package"]
    if r["kind"] == "remote":
        return r["detail"]
    if r["kind"] == "local":
        return r["repo"] or "local checkout"
    if r["kind"] == "git":
        return r["repo"] or "git"
    return (r["command"] + " " + " ".join(r["args"][:2])).strip()[:40] or "?"


def age(r: dict) -> str:
    d = r["days_since_push"]
    return "" if d is None else f"{d}d"


def render_text(results: list[dict], searched: list[str]) -> str:
    if not searched:
        return "No MCP client config found. Pass one with --config PATH.\n"
    lines = [] if searched == ["command line"] else ["Read " + ", ".join(searched), ""]
    if not results:
        return "\n".join(lines + ["No MCP servers configured."]) + "\n"
    cols = [("server", lambda r: r["name"]), ("client", lambda r: r["client"]), ("starts", what),
            ("repository", lambda r: r["repo"] or ""), ("status", lambda r: r["status"]), ("push", age),
            ("licence", lambda r: ((r["facts"].get("repository") or {}).get("license") or "")),
            ("flags", lambda r: ", ".join(r["flags"]))]
    rows = [[str(f(r)) for _, f in cols] for r in results]
    widths = [min(max(len(h), *(len(row[i]) for row in rows)), 44) for i, (h, _) in enumerate(cols)]
    # every column but the last is cut to its width; the flags are the point, so they never are
    fmt = lambda cells: "  ".join([c[:w].ljust(w) for c, w in zip(cells[:-1], widths)] + [cells[-1]]).rstrip()
    lines += [fmt([h for h, _ in cols]), fmt(["-" * w for w in widths])] + [fmt(row) for row in rows]
    lines += ["", summary_line(results)]
    return "\n".join(lines) + "\n"


def summary_line(results: list[dict]) -> str:
    serious = [r for r in results if SERIOUS & set(r["flags"])]
    unpinned = sum(1 for r in results if "unpinned" in r["flags"])
    by = {}
    for r in results:
        by[r["status"]] = by.get(r["status"], 0) + 1
    parts = [f"{len(results)} server{'s' * (len(results) != 1)}"]
    parts += [f"{n} {k}" for k, n in sorted(by.items(), key=lambda kv: -kv[1])]
    parts += [f"{len(serious)} worth a look", f"{unpinned} unpinned"]
    return " · ".join(parts)


def render_markdown(results: list[dict], today: dt.date) -> str:
    out = [f"### MCP servers on this machine, {today.isoformat()}", "",
           "| Server | Starts | Repository | Status | Last push | Licence | Flags |",
           "| --- | --- | --- | --- | ---: | --- | --- |"]
    esc = lambda t: str(t).replace("|", "\\|")
    for r in results:
        repo = f"[{r['repo']}](https://github.com/{r['repo']})" if r["repo"] else ""
        lic = (r["facts"].get("repository") or {}).get("license") or ""
        out.append(f"| {esc(r['name'])} | `{esc(what(r))}` | {repo} | {r['status']} | {age(r)} | {lic} | {esc(', '.join(r['flags']))} |")
    out += ["", summary_line(results), "",
            "_Checked with [mcp-vitals](https://github.com/Keremozdemirra/mcp-vitals). "
            "Dates and licence fields from public metadata, not a verdict on anyone's code._"]
    return "\n".join(out) + "\n"


def target_entry(words: list[str]) -> dict:
    """An entry for a server named on the command line rather than read from a config."""
    e = {"client": "command line", "config": "", "name": words[0], "command": "", "args": [], "url": ""}
    one = words[0] if len(words) == 1 else None
    if one and one.startswith("npm:"):
        return e | {"name": one[4:], "command": "npx", "args": [one[4:]]}
    if one and one.startswith("pypi:"):
        return e | {"name": one[5:], "command": "uvx", "args": [one[5:]]}
    if one and (github_from(one) or re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", one)):
        repo = github_from(one) or one
        return e | {"name": repo, "command": "git", "args": [f"https://github.com/{repo}"]}
    if one and one.startswith(("http://", "https://")):
        return e | {"url": one, "name": urllib.parse.urlsplit(one).netloc}
    if one:  # a bare name is taken for an npm package, the commonest case
        return e | {"command": "npx", "args": [one]}
    return e | {"name": " ".join(words[:3]), "command": words[0], "args": words[1:]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="mcp-vitals", description="Check the MCP servers configured on this machine: "
                                 "is the repository behind each one still maintained, licensed, pinned?")
    ap.add_argument("--config", action="append", type=Path, default=[], metavar="PATH",
                    help="an extra MCP config file to read (repeatable)")
    ap.add_argument("--json", action="store_true", help="print JSON instead of a table")
    ap.add_argument("--markdown", action="store_true", help="print a Markdown table, for an issue or a post")
    ap.add_argument("--offline", action="store_true", help="send nothing; report only what the configs say")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 if any server is archived, abandoned, deprecated, missing or has no licence file")
    ap.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    ap.add_argument("target", nargs=argparse.REMAINDER,
                    help="check one server before adding it instead of reading configs: a command line "
                         "(npx -y @scope/pkg), npm:NAME, pypi:NAME, owner/repo or a GitHub URL")
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):  # a Windows console that cannot print the separators should not crash
        sys.stdout.reconfigure(errors="replace")

    today = dt.date.today()
    target = a.target[1:] if a.target[:1] == ["--"] else a.target
    if target:
        servers, searched = [target_entry(target)], ["command line"]
    else:
        servers, searched = discover(Path.home(), Path.cwd(), a.config)
    net = None if a.offline else Net(False, os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"))
    results = [examine(s, net, today) for s in servers]

    if a.json:
        print(json.dumps({"checked": today.isoformat(), "configs": searched, "servers": results}, indent=1))
    elif a.markdown:
        sys.stdout.write(render_markdown(results, today))
    else:
        sys.stdout.write(render_text(results, searched))
        if net and net.github_down:
            sys.stdout.write("GitHub API unavailable or rate-limited; repository facts came from the daily census. "
                             "Set GITHUB_TOKEN for live ones.\n")
    if a.strict and any(SERIOUS & set(r["flags"]) for r in results):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
