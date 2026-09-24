#!/usr/bin/env python3
"""pkg-vitals: check a package before a coding agent installs it.

Coding agents run `npm install X` and `pip install X` from memory. A model that
invents a package name tends to invent the same name again, and anyone can
register it. pkg-vitals asks the registries about every package an install
command names, before the command runs: is the name on the registry, when was
it first published, is the version deprecated or yanked, does it run scripts at
install time, does it link a source repository and is that repository
archived, which licence does it declare.

  pkg-vitals npm left-pad @scope/pkg@^2
  pkg-vitals pypi "requests==2.32.0"
  pkg-vitals -- npm install foo bar@2 -D

As a Claude Code hook (pkg_vitals_hook.py, which calls hook_main below) it runs
before each install command and asks the person when a package has a serious
flag. Otherwise it prints nothing.

Standard library only, one file, so it also runs without installing anything.

What it reads and what it sends:

- It reads the command line it is given and, to compare licences, the
  `license` field of the nearest package.json or pyproject.toml below $HOME.
- It sends package names that match the registry's name grammar, and pinned
  versions that look like versions, to registry.npmjs.org, api.npmjs.org and
  pypi.org, and owner/name pairs to api.github.com, with GITHUB_TOKEN if set.
  Local paths, git and URL specs, and every package a command installs from a
  private registry or index are reported here and never sent anywhere.
  `--offline` sends nothing.
- Nothing is installed or executed.

The findings are dates, flags and identifiers from public metadata, never a
verdict on anyone's package.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import fnmatch
import gzip
import http.client
import json
import os
import re
import shlex
import socket
import sys
import threading
import time
import tempfile
import traceback
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import zlib
from pathlib import Path

VERSION = "0.1.0"
UA = f"pkg-vitals/{VERSION} (+https://github.com/Keremozdemirra/pkg-vitals)"
CENSUS = "https://raw.githubusercontent.com/Keremozdemirra/agent-vitals/main/data/servers.json"

# pkg-vitals' own threshold, not a standard. A name registered to catch a
# hallucination is new by construction. Checking only that a name exists is not
# enough, because whoever registers the name makes it exist (Spracklen et al.,
# USENIX Security 2025, section 6.1; checked 2026-09-24).
NEW_DAYS = 30

# The census is 26 MB and is the largest thing read; anything bigger is refused.
MAX_BYTES = 64 * 1024 * 1024

# ---------------------------------------------------------------- flags

F_MISSING = "not on registry"
F_PLACEHOLDER = "security placeholder"
F_NEW = "new"
F_DEPRECATED = "deprecated"
F_YANKED = "yanked"
F_ARCHIVED = "archived"  # PyPI project status (PEP 792)
F_QUARANTINED = "quarantined"  # PyPI project status (PEP 792)
F_REPO_ARCHIVED = "repository archived"
F_SCRIPTS = "install scripts"
F_NO_REPO = "no repository"
F_REPO_MISSING = "repository not found"
F_ABANDONED = "abandoned"
F_NO_LICENCE = "no licence"
F_COPYLEFT = "copyleft"
F_NO_VERSION = "version not found"
F_NO_FILES = "no files"

# The flags the hook asks about and --strict fails on. Install scripts join them
# only in combination; see seriousness().
SERIOUS = {F_MISSING, F_PLACEHOLDER, F_NEW, F_DEPRECATED, F_YANKED, F_ARCHIVED, F_QUARANTINED, F_REPO_ARCHIVED}

# ---------------------------------------------------------------- names and text

# Only strings that match these are ever sent to a registry. npm's grammar for
# new package names (validate-npm-package-name: lowercase, 214 characters at
# most) and PEP 508's for PyPI; checked 2026-09-24.
NPM_NAME = re.compile(r"(@[a-z0-9-~][a-z0-9-._~]*/)?[a-z0-9-~][a-z0-9-._~]*")  # fullmatch only: `$` lets "\n" in
PYPI_NAME = re.compile(r"[A-Za-z0-9]|[A-Za-z0-9][A-Za-z0-9._-]*[A-Za-z0-9]")
PYPI_REQ = re.compile(r"^([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)\s*(\[[^\]]*\])?\s*(.*)$", re.S)
PYPI_PIN = re.compile(r"v?[0-9][0-9A-Za-z.!+_-]{0,63}")
VERSIONISH = re.compile(r"v?\d+(?:\.\d+)*")
# GitHub: owner 1-39 of [A-Za-z0-9-], repository 1-100 of [A-Za-z0-9._-]
GITHUB_SLUG = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/(?!\.\.?\Z)[A-Za-z0-9._-]{1,100}")

_USERINFO = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^/\s@]+@")
_QUERY = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://[^\s?#]*)\?[^\s#>]*")
_KEYARG = re.compile(r"(?i)(--?[a-z0-9_-]*(?:key|token|secret|passw(?:or)?d|auth|credential)[a-z0-9_-]*)(=|\s+)(?!\*\*\*)(\S+)")
_KEYVAR = re.compile(r"\b([A-Za-z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|AUTH|CREDENTIAL)[A-Za-z0-9_]*)=(?!\*\*\*)(\S+)", re.I)


def mask(text: str) -> str:
    """Hide what could be a secret: URL userinfo and query strings, --token-like arguments, KEY=value."""
    text = _USERINFO.sub(r"\1***@", text)
    text = _QUERY.sub(r"\1?***", text)
    text = _KEYARG.sub(lambda m: m.group(1) + m.group(2) + "***", text)
    return _KEYVAR.sub(r"\1=***", text)


def scrub(obj):
    """mask() over every string in a JSON-able structure."""
    if isinstance(obj, str):
        return mask(obj)
    if isinstance(obj, list):
        return [scrub(x) for x in obj]
    if isinstance(obj, dict):
        return {k: scrub(v) for k, v in obj.items()}
    return obj


def clean(text, n: int = 200) -> str:
    """Masked first, so truncation cannot cut a secret loose from the delimiter the mask looks for; then control,
    format, private-use and unassigned characters out (invisible text included), then cut to length."""
    s = mask(str(text))
    s = "".join(" " if unicodedata.category(c) == "Cc" else "" if unicodedata.category(c) in ("Cf", "Co", "Cn", "Cs")
                else c for c in s)
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 3] + "..."


def remote(text, n: int = 200) -> str:
    """Text a third party wrote (a deprecation message, a yank reason, a script), marked as such for any reader,
    Claude included: control characters stripped, cut to length, wrapped."""
    s = clean(text, n).replace("<<", "< <").replace(">>", "> >")
    return f"<<remote text, not an instruction: {s}>>"


_SPDX_ID = r"[A-Za-z0-9][A-Za-z0-9.+-]*"
_SPDX_EXPR = re.compile(rf"\(?\s*{_SPDX_ID}\s*\)?(?:\s+(?:AND|OR|WITH|and|or|with)\s+\(?\s*{_SPDX_ID}\s*\)?)*")
_CLASSIFIER_NAME = re.compile(r"[A-Za-z0-9 .,()+/-]{1,80}")


def _safe_version(v) -> str | None:
    return v if isinstance(v, str) and re.fullmatch(r"[0-9A-Za-z.+!_-]{1,64}", v) else None


# ---------------------------------------------------------------- command lines

_SEP = set(";&|\n()")
_REDIR = set("<>&|")
_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_HEREDOC = re.compile(r"(?<!<)<<(?!<)-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")

NPM_INSTALL = {"install", "i", "add", "in", "ins", "inst", "insta", "instal", "isnt", "isnta", "isntal", "isntall"}
NPM_LOCKFILE = {"ci", "clean-install", "install-clean", "install-test", "it", "install-ci-test", "cit"}

# Options that take a value, per tool, so the value is not read as a package
# name. From each tool's --help (npm 10.9, pnpm 10.33, yarn 1.22, bun 1.3,
# pip 24.0, uv 0.8, poetry 2.3, pipx 1.11), checked 2026-09-24.
_NODE_COMMON = {"--registry", "--prefix", "-C", "--cache", "--userconfig", "--globalconfig", "--loglevel", "--proxy",
                "--https-proxy", "--noproxy", "--cafile", "--ca", "--cert", "--key", "--otp", "--node-options",
                "--script-shell", "--shell", "--cwd", "--dir"}
NODE = {
    "npm": {"install": NPM_INSTALL, "run": {"exec", "x"}, "create": {"create", "init", "innit"},
            "values": _NODE_COMMON | {"--tag", "--omit", "--include", "--install-strategy", "-w", "--workspace", "--before",
                                      "--location", "--save-prefix", "--lockfile-version", "--audit-level", "--cpu", "--os",
                                      "--libc", "--scope", "--fetch-retries", "--fetch-timeout", "--local-address",
                                      "--auth-type"},
            "packages": {"--package"}, "run_values": {"-c", "--call"}},
    "pnpm": {"install": {"add", "install", "i"}, "run": {"dlx"}, "create": {"create"},
             "values": _NODE_COMMON | {"--store-dir", "--virtual-store-dir", "--modules-dir", "--global-dir", "-F", "--filter",
                                       "--filter-prod", "--changed-files-ignore-pattern", "--test-pattern", "--allow-build",
                                       "--reporter", "--save-catalog-name"},
             "packages": {"--package"}, "run_values": set()},
    "yarn": {"install": {"add"}, "run": {"dlx"}, "create": {"create"},
             "values": _NODE_COMMON | {"--use-yarnrc", "--link-folder", "--global-folder", "--modules-folder",
                                       "--preferred-cache-folder", "--cache-folder", "--mutex", "--network-concurrency",
                                       "--network-timeout", "--mode"},
             "packages": {"-p", "--package"}, "run_values": set()},
    "bun": {"install": {"add", "a", "install", "i"}, "run": {"x"}, "create": {"create", "c"},
            "values": _NODE_COMMON | {"-c", "--config", "--cache-dir", "--backend", "--concurrent-scripts",
                                      "--network-concurrency", "--omit", "--linker", "--minimum-release-age", "--cpu", "--os",
                                      "-F", "--filter"},
            "packages": {"-p", "--package"}, "run_values": set()},
}
# npx, pnpx and bunx are the run verbs of their manager with the verb already given
RUNNERS = {"npx": ("npm", "npx"), "pnpx": ("pnpm", "pnpx"), "bunx": ("bun", "bunx")}
NPX_VALUES = NODE["npm"]["values"] | {"-p", "--package", "-c", "--call"}

PIP_GENERAL = {"--python", "--log", "--log-file", "--local-log", "--proxy", "--retries", "--timeout", "--exists-action",
               "--trusted-host", "--cert", "--client-cert", "--cache-dir", "--use-feature", "--use-deprecated",
               "--resume-retries", "--keyring-provider"}
PIP_VALUES = PIP_GENERAL | {"-r", "--requirement", "-c", "--constraint", "-e", "--editable", "-t", "--target", "--platform",
                            "--python-version", "--implementation", "--abi", "--root", "--prefix", "--src",
                            "--upgrade-strategy", "-C", "--config-settings", "--global-option", "--build-option",
                            "--install-option", "--no-binary", "--only-binary", "--progress-bar", "--root-user-action",
                            "--report", "--group", "-i", "--index-url", "--extra-index-url", "-f", "--find-links"}
UV_GLOBAL = {"--cache-dir", "--color", "--config-file", "--directory", "--project", "--python-preference",
             "--allow-insecure-host"}
_UV_RESOLVE = UV_GLOBAL | {"--config-setting", "--config-settings-package", "--constraints", "--default-index",
                           "--exclude-newer", "--exclude-newer-package", "--extra-index-url", "--find-links",
                           "--fork-strategy", "--index", "--index-strategy", "--index-url", "--keyring-provider", "--link-mode",
                           "--no-binary-package", "--no-build-isolation-package", "--no-build-package", "--prerelease",
                           "--python", "--refresh-package", "--reinstall-package", "--resolution", "--upgrade-package",
                           "-C", "-P", "-c", "-f", "-i", "-p"}
UV_ADD_VALUES = _UV_RESOLVE | {"--bounds", "--branch", "--extra", "--group", "--marker", "--optional", "--package",
                               "--requirements", "--rev", "--script", "--tag", "-m", "-r"}
UV_PIP_VALUES = _UV_RESOLVE | {"--build-constraints", "--editable", "--extra", "--group", "--no-binary", "--only-binary",
                               "--overrides", "--prefix", "--python-platform", "--python-version", "--requirements",
                               "--target", "--torch-backend", "-b", "-e", "-r"}
UV_RUN_VALUES = _UV_RESOLVE | {"--build-constraints", "--env-file", "--from", "--overrides", "--python-platform", "--with",
                               "--with-editable", "--with-requirements", "--with-executables-from", "-b", "-w"}
POETRY_VALUES = {"-G", "--group", "-E", "--extras", "--optional", "--python", "--platform", "--markers", "--source", "-P",
                 "--project", "-C", "--directory"}
PIPX_VALUES = {"--suffix", "--python", "--preinstall", "--index-url", "-i", "--pip-args", "--spec", "--with", "--backend"}

# Where a registry or index other than the public one can come from, besides the command line.
NPM_REGISTRY_ENV = ("npm_config_registry", "NPM_CONFIG_REGISTRY", "YARN_REGISTRY", "YARN_NPM_REGISTRY_SERVER",
                    "BUN_CONFIG_REGISTRY")
PYPI_INDEX_ENV = ("PIP_INDEX_URL", "UV_INDEX_URL", "UV_DEFAULT_INDEX", "UV_INDEX")
PUBLIC_HOSTS = {"registry.npmjs.org", "registry.yarnpkg.com", "pypi.org", "pypi.python.org"}
UV_INDEX_ENV = ("UV_INDEX_URL", "UV_DEFAULT_INDEX", "UV_INDEX", "UV_EXTRA_INDEX_URL")

# From the user's own configuration only these keys are used. The files also hold
# auth tokens (`//host/:_authToken=`, passwords in URLs): every other line is
# skipped unparsed, and of a matching value only the host is kept.
_NPMRC_KEY = re.compile(r"\s*(registry|@[a-z0-9-~][a-z0-9-._~]*:registry)\s*=\s*(\S+)\s*", re.I)
_PIP_KEY = re.compile(r"\s*(index[-_]url|extra[-_]index[-_]url)\s*[=:]\s*(\S+)\s*", re.I)
_UV_KEY = re.compile(r"""\s*(index-url|extra-index-url|default-index|url)\s*=\s*(.+)""", re.I)


def _config_lines(path: Path, key: re.Pattern):
    """(key, value) for the lines of a config file that match `key`; nothing else leaves this function."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
    except OSError:
        return []
    return [(m.group(1).lower(), m.group(2)) for m in map(key.fullmatch, text.splitlines()) if m]


def _pip_config_files(env) -> list[Path]:
    home = Path.home()
    files = [Path("/etc/pip.conf"), Path("/etc/xdg/pip/pip.conf"), home / ".pip" / "pip.conf",
             Path(env.get("XDG_CONFIG_HOME") or home / ".config") / "pip" / "pip.conf",
             home / "Library" / "Application Support" / "pip" / "pip.conf"]
    if env.get("APPDATA"):
        files.append(Path(env["APPDATA"]) / "pip" / "pip.ini")
    if env.get("VIRTUAL_ENV"):
        files.append(Path(env["VIRTUAL_ENV"]) / ("pip.ini" if os.name == "nt" else "pip.conf"))
    if env.get("PIP_CONFIG_FILE"):
        files.append(Path(env["PIP_CONFIG_FILE"]))
    return files


def registry_config(cwd: str | None, env) -> dict:
    """The registries and indexes the user configured: npm's `registry` and `@scope:registry` from the project's
    and the user's .npmrc, pip's `index-url` from pip's config files, uv's index settings from uv.toml and
    pyproject.toml. Values are hosts (None for a public registry); nothing else is read."""
    npmrcs = [Path.home() / ".npmrc"] + [d / ".npmrc" for d in reversed(list(_upward(cwd)))]
    npm = {}
    for f in npmrcs:  # later files (nearer the project) win, as they do for npm
        for k, v in _config_lines(f, _NPMRC_KEY):
            npm[k] = _index_host(v)
    pip = None
    for f in _pip_config_files(env):
        for k, v in _config_lines(f, _PIP_KEY):
            if k.replace("_", "-") == "index-url":
                pip = _index_host(v)
    uv = None
    uv_files = [Path(env.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "uv" / "uv.toml"]
    for d in reversed(list(_upward(cwd))):
        uv_files += [d / "uv.toml", d / "pyproject.toml"]
    for f in uv_files:
        section = None if f.name == "uv.toml" else ""
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines() if f.is_file() else []
        except OSError:
            lines = []
        for line in lines:
            head = line.strip()
            if head.startswith("["):
                section = head.strip("[] ")
                continue
            # uv.toml keys sit at the top level or in [[index]]; pyproject's under [tool.uv] and [[tool.uv.index]]
            m = _UV_KEY.fullmatch(line) if section in (None, "index", "tool.uv", "tool.uv.index") else None
            if m and (m.group(1).lower() != "url" or section in ("index", "tool.uv.index")):
                for url in re.findall(r"""["']([^"']+)["']""", m.group(2)):
                    uv = uv or _index_host(url)
    return {"npm": npm, "pip": pip, "uv": uv}


def tokenize(command: str, powershell: bool = False) -> list[str]:
    """Split a shell command line into words and operators the way the shell would.

    This is shlex with punctuation_chars=True and whitespace_split=True, so
    `a;b`, `a&&b` and `a|b` split, plus the newline as one more separator.
    PowerShell has no backslash escape: `"C:\app\"` is a whole string there."""
    if not powershell:
        command = re.sub(r"\\\r?\n", " ", command)  # backslash-newline continues a line
    text = _strip_comments(_strip_heredocs(command), powershell)
    lex = shlex.shlex(text, posix=True, punctuation_chars="();<>|&\n")
    lex.whitespace = " \t\r"  # a newline separates commands, so it must come through as a token
    lex.whitespace_split = True
    lex.commenters = ""  # comments are gone already; a `#` left is inside a word or a quote
    if powershell:
        lex.escape = ""
    try:
        return list(lex)
    except ValueError:  # unbalanced quotes: nothing here can be read reliably
        return []


def _strip_comments(text: str, powershell: bool = False) -> str:
    """Drop `# ...` comments before tokenizing, so an apostrophe in one (`# don't`) cannot unbalance the quotes.
    A `#` starts a comment only at the start of a word and outside quotes."""
    out, quote, i, start, tick = [], None, 0, True, None
    while i < len(text):
        c = text[i]
        if c == "`" and not powershell and quote != "'":
            # `cmd` runs cmd, inside double quotes too: split it out as a command of its own
            if tick is None:
                out.append('"\n' if quote == '"' else "\n")
                tick, quote = quote, None
            else:
                out.append('\n"' if tick == '"' else "\n")
                quote, tick = (tick if tick == '"' else None), None
            i += 1
            start = True
            continue
        if quote:
            out.append(c)
            if c == quote:
                quote = None
            elif c == "\\" and quote == '"' and not powershell and i + 1 < len(text):
                out.append(text[i + 1])
                i += 1
        elif c in "'\"":
            quote = c
            out.append(c)
        elif c == "\\" and not powershell and i + 1 < len(text):
            out += [c, text[i + 1]]
            i += 1
        elif c == "#" and start:
            nl = text.find("\n", i)
            if nl < 0:
                break
            i = nl
            continue
        else:
            out.append(c)
        start = quote is None and c in " \t\r\n;&|(){}"
        i += 1
    return "".join(out)


def _strip_heredocs(text: str) -> str:
    # A heredoc body is data, often prose with apostrophes the tokenizer cannot
    # balance, and sometimes a README that mentions `npm install`. Drop it.
    pos = 0
    while True:
        m = _HEREDOC.search(text, pos)
        if not m:
            return text
        nl = text.find("\n", m.end())
        if nl < 0:
            return text
        end = re.compile(r"^[ \t]*" + re.escape(m.group(2)) + r"[ \t]*$", re.M).search(text, nl + 1)
        text = text[:nl + 1] + (text[end.end():] if end else "")
        pos = m.end()


def _is_sep(t: str) -> bool:
    return bool(t) and (set(t) <= _SEP or t in ("{", "}"))


def _is_redirect(t: str) -> bool:
    return bool(t) and set(t) <= _REDIR and ("<" in t or ">" in t)


def split_commands(tokens: list[str]) -> list[list[str]]:
    out, cur = [], []
    for t in tokens:
        if _is_sep(t):
            if cur:
                out.append(cur)
            cur = []
        else:
            cur.append(t)
    if cur:
        out.append(cur)
    return out


def _drop_redirects(words: list[str]) -> list[str]:
    out, skip = [], False
    for w in words:
        if skip:
            skip = False
        elif _is_redirect(w):
            if out and out[-1].isdigit():  # the descriptor in `2>`
                out.pop()
            skip = True
        else:
            out.append(w)
    return out


def _strip_wrappers(words: list[str]) -> tuple[dict, list[str]]:
    """Leading VAR=value assignments and sudo/env/time/... prefixes, removed; the assignments returned."""
    env, i = {}, 0
    while i < len(words):
        w = words[i]
        base = os.path.basename(w)
        if _ASSIGN.match(w):
            k, _, v = w.partition("=")
            env[k] = v
            i += 1
        elif w in ("if", "then", "elif", "else", "do", "while", "until", "!", "{"):
            i += 1  # `if ...; then npm i x; fi`: what follows a keyword is still a command
        elif base in ("sudo", "doas"):
            i += 1
            while i < len(words) and words[i].startswith("-"):
                if words[i] == "--":
                    i += 1
                    break
                i += 2 if words[i] in ("-u", "-g", "-C", "-D", "-h", "-p", "-r", "-t", "-T", "-U") else 1
        elif base == "env":
            i += 1
            while i < len(words) and (words[i].startswith("-") or _ASSIGN.match(words[i])):
                if _ASSIGN.match(words[i]):
                    k, _, v = words[i].partition("=")
                    env[k] = v
                i += 2 if words[i] in ("-u", "--unset", "-C", "--chdir") else 1
        elif base in ("time", "nohup", "command", "builtin", "noglob", "exec", "nice", "stdbuf"):
            i += 1
            while i < len(words) and words[i].startswith("-"):
                i += 2 if words[i] in ("-n", "-a") else 1
        elif base == "xargs" and i + 1 < len(words) and not words[i + 1].startswith("-"):
            i += 1  # bare xargs runs its arguments as the command, as Claude Code's own rule matching assumes
        elif base == "timeout":
            i += 1
            while i < len(words) and words[i].startswith("-"):
                i += 2 if words[i] in ("-s", "-k", "--signal", "--kill-after") else 1
            i += 1  # the duration
        else:
            break
    return env, words[i:]


def scan(args: list[str], values: set, capture: set = frozenset(), first_only: bool = False):
    """Positional words, captured option values and seen options in an argument list.

    Options in `values` consume the next word, so a directory, URL or version
    after them is not taken for a package name. With `first_only` the scan stops
    at the first positional: for runners, what follows it belongs to the program.
    Returns (positionals as (index, word), {option: [values]}, set of options)."""
    pos, got, flags = [], {}, set()
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--":
            rest = [(j, args[j]) for j in range(i + 1, len(args))]
            pos += rest[:1] if first_only else rest
            break
        if a.startswith("--") and "=" in a:
            k, _, v = a.partition("=")
            flags.add(k)
            if k in capture:
                got.setdefault(k, []).append(v)
        elif a.startswith("-") and len(a) > 1:
            flags.add(a)
            if a in values:
                if i + 1 < len(args):
                    if a in capture:
                        got.setdefault(a, []).append(args[i + 1])
                    i += 1
            elif not a.startswith("--") and a[:2] in values and len(a) > 2:
                # `-rrequirements.txt`, `-C/some/dir`: a short option with its value attached
                flags.add(a[:2])
                if a[:2] in capture:
                    got.setdefault(a[:2], []).append(a[2:].lstrip("="))
        else:
            pos.append((i, a))
            if first_only:
                break
        i += 1
    return pos, got, flags


def _index_host(url: str) -> str | None:
    """The host of a registry or index URL, or None when it is the public one. Never the credentials in it."""
    name, eq, rest = url.partition("=")
    if eq and "://" in rest and "://" not in name:  # uv's named form: --index corp=https://...
        url = rest
    try:
        host = urllib.parse.urlsplit(url.strip()).hostname or ""
    except ValueError:
        return "an index URL that could not be read"
    if not host:
        return None if not url.strip() else "an index URL that could not be read"
    return None if host in PUBLIC_HOSTS else host


def npm_spec(token: str):
    """('target', name, spec) for a registry package, or ('skip', reason, None)."""
    t = token.strip()
    low = t.lower()
    if not t:
        return "skip", "empty", None
    m = re.match(r"^(@?[^@\s]+)@npm:(.+)$", t)  # an alias: foo@npm:bar@1 installs bar
    if m:
        return npm_spec(m.group(2))
    if t in (".", "..") or t.startswith(("./", "../", "/", "~")) or re.match(r"^[A-Za-z]:[\\/]", t):
        return "skip", "local path", None
    if low.startswith(("file:", "link:", "workspace:", "portal:", "patch:", "exec:")):
        return "skip", "local path", None
    if low.startswith(("git+", "git:", "git@", "github:", "gitlab:", "bitbucket:", "gist:", "http://", "https://", "ssh://")):
        return "skip", "git or URL", None
    if low.endswith((".tgz", ".tar.gz", ".tar")):
        return "skip", "tarball", None
    at = t.find("@", 1)
    name, spec = (t[:at], t[at + 1:].strip()) if at > 0 else (t, "")
    sl = spec.lower()
    if sl.startswith(("file:", "link:", "workspace:", "portal:", "patch:", ".", "/", "~")):
        return "skip", "local path", None
    if sl.startswith(("git+", "git:", "git@", "github:", "gitlab:", "bitbucket:", "gist:", "http://", "https://")) or \
            re.match(r"^[\w.-]+/[\w.-]+", spec):
        return "skip", "git or URL", None
    if "/" in name and not name.startswith("@"):
        return "skip", "GitHub shorthand (owner/repo)", None
    if not NPM_NAME.fullmatch(name) or len(name) > 214 or VERSIONISH.fullmatch(name):
        return "skip", "not a valid npm package name", None
    return "target", name, spec or None


def pypi_spec(token: str, at_syntax: bool = False):
    """('target', name, spec, pin) for a PyPI requirement, or ('skip', reason, None, None).

    `at_syntax` accepts `name@version` as poetry, uvx and uv tool install do."""
    t = token.strip()
    low = t.lower()
    if t in (".", "..") or t.startswith(("./", "../", "/", "~")) or re.match(r"^[A-Za-z]:[\\/]", t):
        return "skip", "local path", None, None
    if "://" in t or low.startswith(("git+", "hg+", "svn+", "bzr+", "file:")):
        return "skip", "git or URL", None, None
    if low.endswith((".whl", ".tar.gz", ".zip", ".tar.bz2", ".tgz", ".tar.xz", ".egg")):
        return "skip", "archive file", None, None
    m = PYPI_REQ.match(t)
    if not m or not PYPI_NAME.fullmatch(m.group(1)) or VERSIONISH.fullmatch(m.group(1)):
        return "skip", "not a valid PyPI package name", None, None
    name, rest = m.group(1), m.group(3).split(";", 1)[0].strip()  # drop environment markers
    if rest and not re.match(r"(===|==|!=|~=|<=|>=|<|>|@|,|\()", rest):  # `café` is not `caf` plus a version
        return "skip", "not a valid PyPI package name", None, None
    pin = None
    if rest.startswith("@"):
        after = rest[1:].strip()
        if not at_syntax or "://" in after or after.startswith(("git+", "file:")):
            return "skip", "direct reference", None, None
        spec = after or None
        # poetry and uvx read a bare version after @ as that exact version
        if spec and PYPI_PIN.fullmatch(spec):
            pin = spec
    else:
        spec = rest or None
        pm = re.fullmatch(r"(===?)\s*(\S+)", spec or "")
        if pm and PYPI_PIN.fullmatch(pm.group(2)):
            pin = pm.group(2)
    if spec and spec.lower() == "latest":
        spec = None
    return "target", name, spec, pin


def pep503(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _ignored(name: str, env) -> bool:
    patterns = [p for p in re.split(r"[,\s]+", env.get("PKG_VITALS_IGNORE", "")) if p]
    return any(fnmatch.fnmatchcase(name, p) or fnmatch.fnmatchcase(pep503(name), pep503(p)) for p in patterns)


def _upward(start: str | None):
    """`start` and its parents, stopping below $HOME: a project is never the home directory itself."""
    if not start:
        return
    try:
        home = Path.home().resolve()
    except (RuntimeError, OSError):
        home = None
    d = Path(start)
    for _ in range(40):
        if home is not None and (d == home or d in home.parents):
            return
        yield d
        if d.parent == d:
            return
        d = d.parent


def _local_bin(cwd: str | None, name: str) -> bool:
    """True if a project at or above `cwd` has `name` in node_modules/.bin, which npx runs instead of fetching."""
    for d in _upward(cwd):
        b = d / "node_modules" / ".bin"
        if (b / name).exists() or (b / (name + ".cmd")).exists():
            return True
    return False


class _Found:
    """What one command line would fetch from npm or PyPI, and what it names that is not a registry package."""

    def __init__(self, cwd: str | None, env, powershell: bool = False):
        self.cwd, self.env, self.powershell = cwd, env, powershell
        self.targets: list[dict] = []
        self.skipped: list[dict] = []
        self.seen: set = set()
        self.configs: dict = {}

    def skip(self, spec: str, via: str, reason: str):
        self.skipped.append({"spec": clean(spec, 120), "via": via, "reason": reason})

    def add(self, eco: str, token: str, via: str, scope: str, *, at_syntax=False, index=None, runner=False,
            requested=None, cwd=None):
        shown = requested or token
        if eco == "npm":
            kind, a, spec = npm_spec(token)
            pin = spec if spec and semver(spec.lstrip("=v")) else None
        else:
            kind, a, spec, pin = pypi_spec(token, at_syntax)
        if kind == "skip":
            self.skip(shown, via, a)
            return
        name = a
        here = cwd or self.cwd
        index = index or self._index_for(eco, name, via, here)
        if index:
            # the package comes from somewhere else; its name stays on this machine
            self.skip(shown, via, f"installs from {index}, which pkg-vitals does not query")
            return
        if runner and not spec and _local_bin(here, name):
            self.skip(shown, via, "runs the binary already in node_modules/.bin")
            return
        if _ignored(name, self.env):
            self.skip(shown, via, "matches PKG_VITALS_IGNORE")
            return
        key = (eco, name if eco == "npm" else pep503(name), spec)
        if key in self.seen:
            return
        self.seen.add(key)
        self.targets.append({"ecosystem": eco, "name": name, "spec": spec, "pin": pin, "requested": clean(shown, 120),
                             "via": via, "scope": scope, "cwd": here})

    def _index_for(self, eco: str, name: str, via: str, cwd: str | None) -> str | None:
        uv = via.startswith("uv")
        for k in NPM_REGISTRY_ENV if eco == "npm" else PYPI_INDEX_ENV + (UV_INDEX_ENV if uv else ()):
            if self.env.get(k):
                return _index_host(self.env[k])
        if eco == "pypi" and str(self.env.get("PIP_NO_INDEX", "")).lower() in ("1", "true", "yes", "on"):
            return "local files (PIP_NO_INDEX)"
        if cwd not in self.configs:
            self.configs[cwd] = registry_config(cwd, self.env)
        cfg = self.configs[cwd]
        if eco == "npm":
            scope = name.split("/")[0].lower() + ":registry" if name.startswith("@") else None
            return cfg["npm"][scope] if scope in cfg["npm"] else cfg["npm"].get("registry")
        return cfg["uv"] if uv else cfg["pip"]


def parse_command(command: str, cwd: str | None = None, env=None, powershell: bool = False) -> dict:
    """Every npm or PyPI package an install command line would fetch.

    Handles compound lines (`cd app && npm i a; pip install b | tee log`),
    `bash -c "..."`, `cmd /c ...`, sudo/env/time prefixes and each tool's
    value-taking options. Returns {"targets": [...], "skipped": [...]}; a target
    is a dict with ecosystem, name, spec (version or range as written), pin
    (exact version or None), via, scope ("project" or "tool") and cwd."""
    found = _Found(cwd, os.environ if env is None else env, powershell)
    _parse_into(found, command, 0)
    return {"targets": found.targets, "skipped": found.skipped}


def _parse_into(found: _Found, command: str, depth: int):
    if depth > 3:
        return
    for words in split_commands(tokenize(command, found.powershell)):
        assigned, words = _strip_wrappers(_drop_redirects(words))
        if not words:
            continue
        saved_env = found.env
        if assigned:
            found.env = {**found.env, **assigned}
        try:
            _parse_words(found, words, depth)
        finally:
            found.env = saved_env


def _parse_words(found: _Found, words: list[str], depth: int):
    head = os.path.basename(words[0].replace("\\", "/")).lower()
    for suffix in (".exe", ".cmd", ".bat", ".ps1"):
        if head.endswith(suffix):
            head = head[: -len(suffix)]
    args = words[1:]
    if head in ("cd", "pushd", "set-location", "sl"):
        if len(args) == 1 and args[0] != "-":
            base = Path(found.cwd) if found.cwd else Path.cwd()
            found.cwd = str(base / args[0])
        return
    if head in ("bash", "sh", "zsh", "dash", "ksh"):
        for i, a in enumerate(args):
            if re.fullmatch(r"-[A-Za-z]*c[A-Za-z]*", a) and i + 1 < len(args):
                _parse_into(found, args[i + 1], depth + 1)
                return
            if not a.startswith("-"):
                return
        return
    if head == "cmd":  # cmd /c npm install x
        for i, a in enumerate(args):
            if a.lower() in ("/c", "/k", "/s/c", "/s/k"):
                _parse_into(found, " ".join(args[i + 1:]), depth + 1)
                return
        return
    if head in ("powershell", "pwsh"):
        for i, a in enumerate(args):
            if a.lower() in ("-c", "-command", "/c", "/command") and i + 1 < len(args):
                _parse_into(found, " ".join(args[i + 1:]), depth + 1)
                return
        return
    if head in NODE:
        _node(found, head, args)
    elif head in RUNNERS:
        tool, via = RUNNERS[head]
        _node_run(found, tool, via, args)
    elif re.fullmatch(r"pip(3(\.\d+)?)?", head):
        _pip(found, args, "pip install", PIP_VALUES)
    elif re.fullmatch(r"(python|pypy)(3(\.\d+)?)?|py", head):
        i = 0
        while i < len(args) and args[i].startswith("-") and args[i] not in ("-m", "-c"):
            i += 2 if args[i] in ("-W", "-X") else 1  # `py -3.12`, `python -I` and the like come first
        if args[i:i + 2] == ["-m", "pip"]:
            _pip(found, args[i + 2:], "python -m pip install", PIP_VALUES)
    elif head == "uv":
        _uv(found, args)
    elif head == "uvx":
        _uv_run(found, args, "uvx")
    elif head == "poetry":
        _poetry(found, args)
    elif head == "pipx":
        _pipx(found, args)


def _verb(args: list[str], values: set) -> tuple[str | None, list[str]]:
    pos, _, _ = scan(args, values, first_only=True)
    if not pos:
        return None, []
    i, verb = pos[0]
    return verb, args[i + 1:]


def _dir_of(found: _Found, got: dict, keys) -> str | None:
    for k in keys:
        if got.get(k):
            base = Path(found.cwd) if found.cwd else Path.cwd()
            return str(base / got[k][-1])
    return None


def _registry(got: dict) -> str | None:
    for v in got.get("--registry", []):
        host = _index_host(v)
        if host:
            return host
    return None


def _node(found: _Found, tool: str, args: list[str]):
    cfg = NODE[tool]
    verb, rest = _verb(args, cfg["values"])
    if verb is None:
        return
    _, early, _ = scan(args[: len(args) - len(rest)], cfg["values"], capture={"--registry"})  # `npm --registry X i y`
    scope = "project"
    if tool == "yarn" and verb == "workspace" and rest:  # yarn workspace <name> add x
        _node(found, tool, rest[1:])
        return
    if tool == "yarn" and verb == "global":
        verb, rest = _verb(rest, cfg["values"])
        scope = "tool"
    if verb in cfg["install"]:
        pos, got, flags = scan(rest, cfg["values"], capture={"--registry", "--prefix", "-C", "--dir", "--cwd"})
        if flags & {"-g", "--global"}:
            scope = "tool"
        via = "yarn global add" if tool == "yarn" and scope == "tool" else f"{tool} {verb}"
        if not pos:
            if tool == "npm" or verb in ("install", "i"):
                found.skip(f"{tool} {verb}", via, "no package names: installs what package.json and the lockfile list")
            return
        index = _registry(got) or _registry(early)
        here = _dir_of(found, got, ("--prefix", "-C", "--dir", "--cwd"))
        for _, p in pos:
            found.add("npm", p, via, scope, index=index, cwd=here)
    elif verb in cfg["run"]:
        _node_run(found, tool, f"{tool} {verb}", rest, _registry(early))
    elif verb in cfg["create"]:
        _node_create(found, tool, verb, rest, _registry(early))
    elif tool == "npm" and verb in NPM_LOCKFILE:
        found.skip(f"npm {verb}", f"npm {verb}", "no package names: installs what the lockfile lists")


def _node_run(found: _Found, tool: str, via: str, args: list[str], index: str | None = None):
    cfg = NODE[tool]
    package_flags = {"-p", "--package"} if via in ("npx", "bunx", "yarn dlx", "bun x") else cfg["packages"]
    values = (NPX_VALUES if tool == "npm" else cfg["values"]) | package_flags | cfg["run_values"]
    pos, got, _ = scan(args, values, capture=package_flags | {"--registry"}, first_only=True)
    index = _registry(got) or index
    named = [v for k in sorted(package_flags) for v in got.get(k, [])]
    if named:  # the positional is then a command the named packages provide
        for p in named:
            found.add("npm", p, via, "tool", index=index)
    elif pos:
        found.add("npm", pos[0][1], via, "tool", index=index, runner=via in ("npx", "bunx", "npm exec", "npm x", "bun x"))


def _node_create(found: _Found, tool: str, verb: str, args: list[str], index: str | None = None):
    pos, got, _ = scan(args, NODE[tool]["values"], capture={"--registry"}, first_only=True)
    if not pos:  # `npm init` on its own writes a package.json and installs nothing
        return
    init = pos[0][1]
    bare_scope = re.fullmatch(r"(@[a-z0-9-~][a-z0-9-._~]*)(?:@(.+))?", init)  # `npm init @scope` is not a package name
    kind, name, spec = ("target", bare_scope.group(1), bare_scope.group(2)) if bare_scope else npm_spec(init)
    if kind == "skip":
        found.skip(init, f"{tool} {verb}", name)
        return
    # npm's initializer rule: foo -> create-foo, @scope -> @scope/create, @scope/foo -> @scope/create-foo
    if name.startswith("@"):
        scope_, _, rest = name.partition("/")
        pkg = f"{scope_}/create" + (f"-{rest}" if rest else "")
    else:
        pkg = f"create-{name}"
    found.add("npm", pkg + (f"@{spec}" if spec else ""), f"{tool} {verb}", "tool", index=_registry(got) or index,
              requested=init)


_UV_INDEX_FLAGS = ("-i", "--index-url", "--default-index", "--index", "--extra-index-url")


def _pypi_index(got: dict, flags: set, keys=("-i", "--index-url", "--default-index", "--index")) -> str | None:
    # `--index-url`/`--default-index` replace PyPI. uv searches its `--index` and `--extra-index-url` before PyPI
    # and takes the first that has the name (uv's default index strategy), so for uv those are private too. pip
    # asks PyPI as well as an `--extra-index-url`, so for pip that name reaches PyPI anyway and is checked.
    if "--no-index" in flags:
        return "local files (--no-index)"
    for k in keys:
        for v in got.get(k, []):
            host = _index_host(v)
            if host:
                return host
    return None


def _pip(found: _Found, args: list[str], via: str, values: set, index_flags=("-i", "--index-url", "--default-index",
                                                                              "--index")):
    verb, rest = _verb(args, PIP_GENERAL)
    if verb != "install":
        return
    cap = {"-r", "--requirement", "-e", "--editable"} | set(index_flags)
    pos, got, flags = scan(rest, values, capture=cap)
    for r in got.get("-r", []) + got.get("--requirement", []):
        found.skip(f"-r {r}", via, "requirements file: pass its names to `pkg-vitals pypi` to check them")
    for e in got.get("-e", []) + got.get("--editable", []):
        found.skip(f"-e {e}", via, "editable install from a path or URL")
    index = _pypi_index(got, flags, index_flags)
    for _, p in pos:
        found.add("pypi", p, via, "project", index=index)


def _uv(found: _Found, args: list[str]):
    verb, rest = _verb(args, UV_GLOBAL)
    if verb == "add":
        pos, got, flags = scan(rest, UV_ADD_VALUES, capture={"-r", "--requirements"} | set(_UV_INDEX_FLAGS))
        for r in got.get("-r", []) + got.get("--requirements", []):
            found.skip(f"-r {r}", "uv add", "requirements file: pass its names to `pkg-vitals pypi` to check them")
        index = _pypi_index(got, flags, _UV_INDEX_FLAGS)
        for _, p in pos:
            found.add("pypi", p, "uv add", "project", index=index)
    elif verb == "run":  # uv run --with x script.py: the --with packages are fetched
        _, got, flags = scan(rest, UV_RUN_VALUES, capture={"--with", "-w", "-i", "--index-url", "--default-index",
                                                           "--index", "--extra-index-url"}, first_only=True)
        index = _pypi_index(got, flags, _UV_INDEX_FLAGS)
        for w in got.get("--with", []) + got.get("-w", []):
            found.add("pypi", w, "uv run --with", "tool", index=index)
    elif verb == "pip":
        sub, rest2 = _verb(rest, UV_GLOBAL)
        if sub == "install":
            _pip(found, ["install"] + rest2, "uv pip install", UV_PIP_VALUES, _UV_INDEX_FLAGS)
    elif verb == "tool":
        sub, rest2 = _verb(rest, UV_GLOBAL)
        if sub == "run":
            _uv_run(found, rest2, "uv tool run")
        elif sub == "install":
            pos, got, flags = scan(rest2, UV_RUN_VALUES, capture={"--with", "-w"} | set(_UV_INDEX_FLAGS))
            index = _pypi_index(got, flags, _UV_INDEX_FLAGS)
            for _, p in pos:
                found.add("pypi", p, "uv tool install", "tool", at_syntax=True, index=index)
            for w in got.get("--with", []) + got.get("-w", []):
                found.add("pypi", w, "uv tool install", "tool", index=index)


def _uv_run(found: _Found, args: list[str], via: str):
    cap = {"--from", "--with", "-w"} | set(_UV_INDEX_FLAGS)
    pos, got, flags = scan(args, UV_RUN_VALUES, capture=cap, first_only=True)
    index = _pypi_index(got, flags, _UV_INDEX_FLAGS)
    if got.get("--from"):
        found.add("pypi", got["--from"][-1], via, "tool", at_syntax=True, index=index)
    elif pos:
        found.add("pypi", pos[0][1], via, "tool", at_syntax=True, index=index)
    for w in got.get("--with", []) + got.get("-w", []):
        found.add("pypi", w, via, "tool", index=index)


def _poetry(found: _Found, args: list[str]):
    verb, rest = _verb(args, {"-C", "--directory", "-P", "--project"})
    if verb != "add":
        return
    pos, got, _ = scan(rest, POETRY_VALUES, capture={"--source"})
    # a named source is an index poetry was told about; PyPI may not be where the package comes from
    index = "a poetry source named with --source" if got.get("--source") and got["--source"][-1].lower() != "pypi" else None
    for _, p in pos:
        found.add("pypi", p, "poetry add", "project", at_syntax=True, index=index)


def _pipx(found: _Found, args: list[str]):
    verb, rest = _verb(args, {"--python"})
    if verb == "install":
        pos, got, flags = scan(rest, PIPX_VALUES, capture={"--index-url", "-i", "--preinstall"})
        index = _pypi_index(got, flags, ("--index-url", "-i"))
        for _, p in pos:
            found.add("pypi", p, "pipx install", "tool", index=index)
        for p in got.get("--preinstall", []):
            found.add("pypi", p, "pipx install", "tool", index=index)
    elif verb == "inject":  # pipx inject <app> pkg...: the first positional is the app's environment
        pos, got, flags = scan(rest, PIPX_VALUES, capture={"--index-url", "-i"})
        index = _pypi_index(got, flags, ("--index-url", "-i"))
        for _, p in pos[1:]:
            found.add("pypi", p, "pipx inject", "tool", index=index)
    elif verb == "run":
        pos, got, flags = scan(rest, PIPX_VALUES, capture={"--spec", "--with", "--index-url", "-i"}, first_only=True)
        index = _pypi_index(got, flags, ("--index-url", "-i"))
        if got.get("--spec"):
            found.add("pypi", got["--spec"][-1], "pipx run", "tool", index=index)
        elif pos:
            found.add("pypi", pos[0][1], "pipx run", "tool", index=index)
        for w in got.get("--with", []):
            found.add("pypi", w, "pipx run", "tool", index=index)


# ---------------------------------------------------------------- semver
#
# npm resolves `pkg@^2` on the client; the registry has no endpoint for it
# (GET registry.npmjs.org/left-pad/%5E1 answers 404, checked 2026-09-24). This
# is node-semver's range grammar, enough to pick the version npm would install.

_SEMVER = re.compile(r"v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?")
_PART = re.compile(r"v?(\d+|[xX*])(?:\.(\d+|[xX*]))?(?:\.(\d+|[xX*]))?(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?")
_OP = re.compile(r"(<=|>=|<|>|=|~>|~|\^)?(.+)")


def _pre(s: str | None) -> tuple:
    return tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in s.split(".")) if s else ()


_LOWEST = _pre("0")  # the `-0` pre-release: below every other version with the same numbers


def semver(text) -> tuple | None:
    m = _SEMVER.fullmatch(text.strip()) if isinstance(text, str) else None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), _pre(m.group(4))) if m else None


def _key(v: tuple) -> tuple:
    return v[0], v[1], v[2], 0 if v[3] else 1, v[3]


def _partial(text: str):
    m = _PART.fullmatch(text)
    if not m:
        return None
    nums = [None if g is None or g in ("x", "X", "*") else int(g) for g in (m.group(1), m.group(2), m.group(3))]
    for j in (1, 2):  # 1.x.3 means 1.x
        if nums[j - 1] is None:
            nums[j] = None
    return nums, _pre(m.group(4))


def _comparators(op: str, text: str):
    p = _partial(text)
    if p is None:
        return None
    (M, m, pt), pre = p
    lo = lambda a, b, c: (a, b, c, ())  # noqa: E731
    hi = lambda a, b, c: (a, b, c, _LOWEST)  # noqa: E731
    if M is None:
        return [("<", hi(0, 0, 0))] if op in ("<", ">") else []
    if op in ("", "="):
        if m is None:
            return [(">=", lo(M, 0, 0)), ("<", hi(M + 1, 0, 0))]
        if pt is None:
            return [(">=", lo(M, m, 0)), ("<", hi(M, m + 1, 0))]
        return [("=", (M, m, pt, pre))]
    if op in ("~", "~>"):
        if m is None:
            return [(">=", lo(M, 0, 0)), ("<", hi(M + 1, 0, 0))]
        return [(">=", (M, m, pt or 0, pre)), ("<", hi(M, m + 1, 0))]
    if op == "^":
        if m is None:
            return [(">=", lo(M, 0, 0)), ("<", hi(M + 1, 0, 0))]
        if pt is None:
            return [(">=", lo(M, m, 0)), ("<", hi(M + 1, 0, 0) if M else hi(0, m + 1, 0))]
        upper = hi(M + 1, 0, 0) if M else hi(0, m + 1, 0) if m else hi(0, 0, pt + 1)
        return [(">=", (M, m, pt, pre)), ("<", upper)]
    if op == ">":
        if m is None:
            return [(">=", lo(M + 1, 0, 0))]
        if pt is None:
            return [(">=", lo(M, m + 1, 0))]
        return [(">", (M, m, pt, pre))]
    if op == ">=":
        return [(">=", (M, m or 0, pt or 0, pre))]
    if op == "<":
        if m is None:
            return [("<", hi(M, 0, 0))]
        if pt is None:
            return [("<", hi(M, m, 0))]
        return [("<", (M, m, pt, pre))]
    if m is None:  # <=
        return [("<", hi(M + 1, 0, 0))]
    if pt is None:
        return [("<", hi(M, m + 1, 0))]
    return [("<=", (M, m, pt, pre))]


def parse_range(spec: str):
    """A node-semver range as a list of comparator sets (any one may match), or None if it is not one."""
    sets = []
    for part in (spec or "").split("||"):
        part = part.strip()
        if re.search(r"\s-\s", part):
            a, b = re.split(r"\s+-\s+", part, maxsplit=1)
            pa, pb = _partial(a), _partial(b)
            if not pa or not pb:
                return None
            (M, m, pt), pre = pa
            comps = [] if M is None else [(">=", (M, m or 0, pt or 0, pre))]
            (M2, m2, pt2), pre2 = pb
            if M2 is not None:
                if m2 is None:
                    comps.append(("<", (M2 + 1, 0, 0, _LOWEST)))
                elif pt2 is None:
                    comps.append(("<", (M2, m2 + 1, 0, _LOWEST)))
                else:
                    comps.append(("<=", (M2, m2, pt2, pre2)))
        else:
            part = re.sub(r"(<=|>=|<|>|=|~>|~|\^)\s+", r"\1", part)
            comps = []
            for tok in part.split() or ["*"]:
                m = _OP.fullmatch(tok)
                c = _comparators(m.group(1) or "", m.group(2)) if m else None
                if c is None:
                    return None
                comps += c
        sets.append(comps)
    return sets


def _satisfies(v: tuple, comps: list) -> bool:
    k = _key(v)
    for op, c in comps:
        ck = _key(c)
        if not ((op == "=" and k == ck) or (op == "<" and k < ck) or (op == "<=" and k <= ck)
                or (op == ">" and k > ck) or (op == ">=" and k >= ck)):
            return False
    if v[3]:  # a pre-release only matches a range that names a pre-release of the same version
        return any(c[3] and c[:3] == v[:3] for _, c in comps)
    return True


def max_satisfying(versions: dict, sets: list, latest: str | None = None) -> str | None:
    """The version npm would pick for a range, as npm-pick-manifest 10 does: the `latest` tag if it matches and is
    not deprecated, else the highest match that is not deprecated, else the highest match. (npm also weighs the
    `engines` field against the local Node version, which a check made elsewhere cannot know.)"""
    matches = []
    for text, man in versions.items():
        v = semver(text)
        if v and any(_satisfies(v, s) for s in sets):
            matches.append((_key(v), text, bool(isinstance(man, dict) and man.get("deprecated"))))
    if not matches:
        return None
    if any(t == latest and not dep for _, t, dep in matches):
        return latest
    live = [x for x in matches if not x[2]]
    return max(live or matches, key=lambda x: x[0])[1]


# ---------------------------------------------------------------- network

def _reason(e: BaseException) -> str:
    r = getattr(e, "reason", e)
    if isinstance(r, (socket.timeout, TimeoutError)) or "timed out" in str(r):
        return "timeout"
    return type(r).__name__


def describe(code) -> str:
    return f"HTTP {code}" if isinstance(code, int) else str(code)


class Net:
    """GET for JSON with short timeouts, a cache and a time budget.

    Every failure comes back as {"_error": <HTTP status or reason>} rather than
    an exception: a fact that cannot be fetched is unknown, never a finding."""

    def __init__(self, timeout: float = 20.0, token: str | None = None, census: bool = True,
                 budget: float | None = None, env=None):
        env = os.environ if env is None else env
        self.timeout = timeout
        self.token = token
        self.use_census = census  # off in the hook: the census is 26 MB, too slow to wait on
        self.deadline = time.monotonic() + budget if budget else None
        # Overrides exist for a mirror that serves the same APIs, and for the tests' local server.
        self.npm_url = env.get("PKG_VITALS_NPM_REGISTRY", "https://registry.npmjs.org").rstrip("/")
        self.downloads_url = env.get("PKG_VITALS_NPM_DOWNLOADS", "https://api.npmjs.org/downloads/point").rstrip("/")
        self.pypi_url = env.get("PKG_VITALS_PYPI", "https://pypi.org").rstrip("/")
        self.github_url = env.get("PKG_VITALS_GITHUB_API", "https://api.github.com").rstrip("/")
        self.census_url = env.get("PKG_VITALS_CENSUS", CENSUS)
        self.cache: dict = {}
        self.down: set = set()
        self.github_down = False
        self.census: dict | None = None
        self.census_date = ""
        self.lock = threading.Lock()
        self.census_lock = threading.Lock()
        self.opener = urllib.request.build_opener()

    @staticmethod
    def host(url: str) -> str:
        return urllib.parse.urlsplit(url).hostname or "the registry"

    def get(self, url: str, headers: dict | None = None) -> dict:
        key = url + "\0" + json.dumps(headers or {}, sort_keys=True)
        with self.lock:
            if key in self.cache:
                return self.cache[key]
        host = urllib.parse.urlsplit(url).netloc
        if host in self.down:
            return {"_error": "unreachable"}
        timeout = self.timeout
        if self.deadline is not None:
            left = self.deadline - time.monotonic()
            if left < 0.5:
                return {"_error": "out of time"}
            timeout = min(timeout, left)
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip", **(headers or {})})
        try:
            with self.opener.open(req, timeout=timeout) as resp:
                raw = resp.read(MAX_BYTES + 1)
                gz = (resp.headers.get("Content-Encoding") or "").lower() == "gzip"
        except urllib.error.HTTPError as e:
            e.close()
            val = {"_error": e.code}
        except (urllib.error.URLError, OSError, http.client.HTTPException, ValueError) as e:
            # refused, unresolvable, TLS failure, timeout, a broken answer: the next request to this host would
            # most likely fail the same way
            with self.lock:
                self.down.add(host)
            val = {"_error": _reason(e)}
        else:
            try:
                if len(raw) > MAX_BYTES:
                    raise ValueError("response too large")
                val = json.loads((gzip.decompress(raw) if gz else raw).decode("utf-8"))
                if not isinstance(val, dict):
                    val = {"_error": "malformed"}
            except (ValueError, EOFError, OSError, zlib.error):
                val = {"_error": "malformed"}
        with self.lock:
            self.cache[key] = val
        return val

    def github(self, slug: str) -> dict:
        if not GITHUB_SLUG.fullmatch(slug):
            return {"error": "not an owner/name"}
        if not self.github_down:
            h = {"Accept": "application/vnd.github+json"}
            if self.token:
                h["Authorization"] = f"Bearer {self.token}"
            d = self.get(f"{self.github_url}/repos/{slug}", h)
            code = d.get("_error")
            if code is None:
                lic = _d(d.get("license"))
                spdx = lic.get("spdx_id") if isinstance(lic.get("spdx_id"), str) else None
                name = d.get("full_name") if isinstance(d.get("full_name"), str) and GITHUB_SLUG.fullmatch(d["full_name"]) else slug
                return {"source": "GitHub API", "full_name": name, "pushed_at": _iso(d.get("pushed_at")),
                        "archived": d.get("archived") is True, "stars": _int(d.get("stargazers_count")),
                        "license": clean(spdx, 40) if spdx and spdx != "NOASSERTION" else None}
            if code == 404:
                return {"error": "not found"}
            # rate-limited, refused (this is what a sandbox without GitHub access answers) or offline:
            # the census stands in for the rest of the run
            self.github_down = True
        return self.from_census(slug)

    def from_census(self, slug: str) -> dict:
        if not self.use_census:
            return {"error": "GitHub API unavailable"}
        with self.census_lock:
            if self.census is None:
                data = self.get(self.census_url)
                rows = data.get("repositories") if isinstance(data.get("repositories"), list) else []
                self.census = {r["full_name"].lower(): r for r in rows
                               if isinstance(r, dict) and isinstance(r.get("full_name"), str)}
                when = _date(data.get("generated_at"))
                self.census_date = when.isoformat() if when else "undated"
        r = self.census.get(slug.lower())
        if not r:
            return {"error": "GitHub API unavailable and not in the census"}
        return {"source": f"agent-vitals census {self.census_date}", "full_name": slug, "pushed_at": _iso(r.get("pushed_at")),
                "archived": r.get("archived") is True, "stars": _int(r.get("stars")),
                "license": clean(r["license"], 40) if isinstance(r.get("license"), str) else None}


# ---------------------------------------------------------------- registry facts

def _d(x) -> dict:
    return x if isinstance(x, dict) else {}


def _date(iso) -> dt.date | None:
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", iso) if isinstance(iso, str) else None
    try:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None
    except ValueError:
        return None


def _iso(value) -> str | None:
    d = _date(value)
    return d.isoformat() if d else None


def _int(value) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def days_since(iso, today: dt.date) -> int | None:
    d = _date(iso)
    return (today - d).days if d else None


# Same thresholds as the agent-vitals census (collect.py bucket()) and mcp-upkeep,
# so a repository reads the same in all three.
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


FORGES = ("github.com", "gitlab.com", "bitbucket.org", "codeberg.org", "sr.ht", "gitee.com")
_REPO_URL = re.compile(r"(?:git@|//(?:[^@/\s]+@)?)([A-Za-z0-9.-]+\.[A-Za-z]{2,})[:/]([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+?)"
                       r"(?:\.git)?(?:[/#?].*)?$")
_PLAIN_URL = re.compile(r"https?://[A-Za-z0-9.-]+(?::\d+)?(?:/[A-Za-z0-9._~%/+-]*)?")


def repo_url(text) -> str | None:
    """A browsable https URL for an npm `repository` value or a project URL, without credentials."""
    if not isinstance(text, str) or not text.strip() or len(text) > 300:
        return None
    t = text.strip()
    m = re.fullmatch(r"(github:|gitlab:|bitbucket:)?([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+?)(?:\.git)?", t)
    if m:  # npm shorthand: owner/repo means GitHub
        host = {"gitlab:": "gitlab.com", "bitbucket:": "bitbucket.org"}.get(m.group(1) or "", "github.com")
        return f"https://{host}/{m.group(2)}/{m.group(3)}"
    m = _REPO_URL.search(t)
    if m:
        host = m.group(1).lower()
        return f"https://{'github.com' if host == 'www.github.com' else host}/{m.group(2)}/{m.group(3)}"
    t = _USERINFO.sub(r"\1", t).split("?")[0].split("#")[0]
    return t[:120] if _PLAIN_URL.fullmatch(t) else None


def github_slug(url: str | None) -> str | None:
    m = re.fullmatch(r"https://github\.com/([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+)", url or "")
    slug = f"{m.group(1)}/{m.group(2)}" if m else None
    return slug if slug and GITHUB_SLUG.fullmatch(slug) else None


def _on_forge(url) -> bool:
    try:
        host = (urllib.parse.urlsplit(url).hostname or "") if isinstance(url, str) else ""
    except ValueError:
        return False
    return any(host == f or host.endswith("." + f) for f in FORGES)


def npm_licence(m: dict) -> str | None:
    lic = m.get("license")
    if isinstance(lic, str) and lic.strip():
        return lic.strip()
    if isinstance(lic, dict) and isinstance(lic.get("type"), str):
        return lic["type"]
    lics = m.get("licenses")  # the old array form
    if isinstance(lics, list):
        types = [x["type"] for x in lics if isinstance(x, dict) and isinstance(x.get("type"), str)] or \
                [x for x in lics if isinstance(x, str)]
        if types:
            return " OR ".join(types)
    return None


def npm_repo(m: dict) -> str | None:
    repo = m.get("repository")
    url = repo_url(repo.get("url") if isinstance(repo, dict) else repo)
    if url:
        return url
    for cand in (m.get("homepage"), _d(m.get("bugs")).get("url")):
        if _on_forge(cand):
            return repo_url(cand)
    return None


def pypi_licence(info: dict) -> tuple[str | None, bool]:
    """(licence, from PyPI's fixed classifier vocabulary). Free text only when nothing else is declared."""
    expr = info.get("license_expression")
    if isinstance(expr, str) and expr.strip():
        return expr.strip(), False
    lic = info.get("license") if isinstance(info.get("license"), str) else ""
    lic = lic.strip()
    if lic and len(lic) <= 80 and "\n" not in lic:
        return lic, False
    cls = [c.split("::")[-1].strip() for c in info.get("classifiers") or [] if isinstance(c, str) and c.startswith("License ::")]
    if cls:
        return ", ".join(cls), True
    return (lic.splitlines()[0] if lic else None), False  # a whole licence text pasted in: its first line names it


def pypi_repo(info: dict) -> str | None:
    urls = [(str(k), v) for k, v in _d(info.get("project_urls")).items() if isinstance(v, str)]
    for k, v in urls:
        if re.search(r"source|repo|code|github|gitlab", k, re.I) and v.startswith(("http://", "https://")):
            url = repo_url(v)
            if url:
                return url
    for _, v in urls + [("home_page", info.get("home_page") or ""), ("download_url", info.get("download_url") or "")]:
        if _on_forge(v):
            return repo_url(v)
    return None


def project_status(simple: dict) -> tuple[str | None, str | None]:
    """PEP 792 status from PyPI's JSON simple API.

    PyPI answers {"project-status": {"status": ...}}, as the PyPA simple
    repository API spec defines it. PEP 792's own text says `state`, and the
    spec's example puts it under `meta`; both are read too (checked 2026-09-24)."""
    ps = simple.get("project-status")
    if isinstance(ps, dict):
        state, why = ps.get("status") or ps.get("state"), ps.get("reason")
    else:
        meta = _d(simple.get("meta"))
        state, why = meta.get("project-status"), meta.get("project-status-reason")
    if state not in ("active", "archived", "quarantined", "deprecated"):
        state = None if state is None else "other"
    return state, why if isinstance(why, str) and why.strip() else None


_WEAK = re.compile(r"\bLGPL[\w.+-]*|GNU (Lesser|Library) General Public License[\w .+-]*", re.I)
_STRONG = re.compile(r"\bA?GPL|General Public License", re.I)


def strong_copyleft(lic: str | None) -> bool:
    """True when every alternative of a licence expression names GPL or AGPL (LGPL does not count)."""
    if not lic:
        return False
    alts = [a for a in re.split(r"\s+or\s+", lic.replace("(", " ").replace(")", " "), flags=re.I) if a.strip()]
    return bool(alts) and all(_STRONG.search(_WEAK.sub("", a)) for a in alts)


def show_licence(lic: str | None, vocabulary: bool = False) -> str | None:
    """The licence as it may be printed bare: an SPDX expression or a classifier name. Anything else is remote text."""
    if not lic:
        return None
    if (vocabulary and _CLASSIFIER_NAME.fullmatch(lic)) or (len(lic) <= 80 and _SPDX_EXPR.fullmatch(lic.strip())):
        return lic
    return remote(lic, 80)


def project_licence(eco: str, cwd: str | None) -> dict | None:
    """The licence the project at `cwd` declares: package.json for npm, pyproject.toml for PyPI."""
    fname = "package.json" if eco == "npm" else "pyproject.toml"
    for d in _upward(cwd):
        f = d / fname
        if f.is_file():
            lic = _read_licence(f)
            return {"file": f.name, "licence": lic} if lic else None
        if (d / ".git").exists():
            return None
    return None


def _read_licence(f: Path) -> str | None:
    try:
        text = f.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if f.name == "package.json":
        try:
            data = json.loads(text)
        except ValueError:
            return None
        lic = npm_licence(data) if isinstance(data, dict) else None
        return clean(lic, 80) if lic else None
    try:
        import tomllib
    except ImportError:  # Python < 3.11: the two lines that matter, read by hand
        return _toml_licence(text)
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return None
    for table in (_d(data.get("project")), _d(_d(data.get("tool")).get("poetry"))):
        for key in ("license", "license-expression"):
            v = table.get(key)
            if isinstance(v, str) and v.strip():
                return clean(v, 80)
            if isinstance(v, dict) and isinstance(v.get("text"), str) and v["text"].strip():
                return clean(v["text"], 80)
    return None


def _toml_licence(text: str) -> str | None:
    section = None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("["):
            section = s.strip("[] ")
            continue
        if section in ("project", "tool.poetry"):
            m = re.match(r"""license(?:-expression)?\s*=\s*(?:\{\s*text\s*=\s*)?["']([^"']+)["']""", s)
            if m:
                return clean(m.group(1), 80)
    return None


def _result(t: dict) -> dict:
    return {"ecosystem": t["ecosystem"], "name": t["name"], "requested": t["requested"], "spec": t["spec"],
            "via": t["via"], "scope": t["scope"], "exists": None, "version": None, "first_published": None,
            "age_days": None, "version_published": None, "deprecated": None, "yanked": None, "project_status": None,
            "install_scripts": {}, "licence": None, "repository": None, "repo": None, "downloads_week": None,
            "flags": [], "serious": [], "notes": [], "errors": [], "complete": True, "_licence_raw": None}


def _flag(r: dict, flag: str, text: str | None = None):
    if flag not in r["flags"]:
        r["flags"].append(flag)
    if text:
        r["notes"].append({"flag": flag, "text": text})


def _not_found(r: dict, host: str, detail: str = "HTTP 404"):
    r["exists"] = False
    _flag(r, F_MISSING, f"not on {host} ({detail}): the name may be mistyped or invented, or served by a private "
                        "registry pkg-vitals does not query")


CORGI = {"Accept": "application/vnd.npm.install-v1+json"}  # npm's abbreviated metadata


def _downloaded_before(net: Net, name: str, today: dt.date, new_days: int) -> bool:
    """True if the package was downloaded in the year before the `new` window, so it was published before it:
    a small answer that spares fetching a popular package's full metadata to learn its creation date."""
    end = today - dt.timedelta(days=new_days + 1)
    d = net.get(f"{net.downloads_url}/{(end - dt.timedelta(days=364)).isoformat()}:{end.isoformat()}/{name}")
    return _int(d.get("downloads")) is not None and d["downloads"] > 0


def check_npm(t: dict, net: Net, today: dt.date, light: bool = False, new_days: int = NEW_DAYS) -> dict:
    """npm facts. `light` (the hook) reads the abbreviated metadata and the one version's manifest instead of the
    full document, which runs to 31 MB for a popular package (next, checked 2026-09-24)."""
    r = _result(t)
    host = net.host(net.npm_url)
    if not NPM_NAME.fullmatch(t["name"]):  # parse_command never makes one, but callers can build targets by hand
        r["errors"].append("not a valid npm package name; not sent")
        return r
    base = f"{net.npm_url}/{urllib.parse.quote(t['name'], safe='@')}"
    doc = net.get(base, CORGI if light else None)
    code = doc.get("_error")
    if code == 404:
        _not_found(r, host)
        return r
    if code is not None:
        r["errors"].append(f"{host}: {describe(code)}")
        return r
    versions = {k: v for k, v in _d(doc.get("versions")).items() if isinstance(v, dict)}
    times = _d(doc.get("time"))
    if not versions:
        gone = _date(_d(times.get("unpublished")).get("time"))
        if gone:
            _not_found(r, host, f"every version unpublished on {gone.isoformat()}")
        else:
            r["errors"].append(f"{host}: no versions in the answer")
        return r
    r["exists"] = True
    tags = {k: v for k, v in _d(doc.get("dist-tags")).items() if isinstance(v, str)}
    latest = tags.get("latest") if tags.get("latest") in versions else None
    version, problem = _resolve_npm(versions, tags, t["spec"], latest)
    if problem:
        _flag(r, F_NO_VERSION, problem)
    r["version"] = _safe_version(version)
    man = versions.get(version, {}) if version else {}
    top = versions.get(latest, {}) if latest else man
    if light:
        for v in {version, latest if latest and latest.endswith("-security") else None} - {None}:
            full = net.get(f"{base}/{urllib.parse.quote(v, safe='')}")
            if full.get("_error") is None:
                versions[v] = full
            elif v == version:
                r["errors"].append(f"{host}: {describe(full['_error'])} for version {r['version']}")
                r["complete"] = False
        man = versions.get(version, {}) if version else {}
        top = versions.get(latest, {}) if latest else man
        if not times.get("created"):
            modified = _date(doc.get("modified"))
            if modified and (today - modified).days >= new_days:
                pass  # unchanged since before the window, so created before it: not new, date not needed
            elif not _downloaded_before(net, t["name"], today, new_days):
                times = _d(net.get(base).get("time"))  # new or unused: its full metadata is small
                if not times:
                    r["errors"].append(f"{host}: publish dates unavailable")
                    r["complete"] = False

    created = times.get("created") or min((times[v] for v in versions if isinstance(times.get(v), str)), default=None)
    r["first_published"] = _date(created).isoformat() if _date(created) else None
    r["age_days"] = days_since(created, today)
    vt = _date(times.get(version)) if version else None
    r["version_published"] = vt.isoformat() if vt else None

    # A latest version `0.0.x-security`, described as a "security holding package" and
    # linked to github.com/npm/security-holder, is npm's placeholder on a name it holds.
    if latest and latest.endswith("-security") and ("security holding" in str(top.get("description") or "").lower()
                                                     or "npm/security-holder" in str(npm_repo(top) or "")):
        _flag(r, F_PLACEHOLDER, f"the latest version is npm's security placeholder ({_safe_version(latest)}, "
                                "\"security holding package\"): npm holds this name")
    dep = man.get("deprecated")  # the version that would be installed, not only the latest
    if dep:
        r["deprecated"] = remote(dep) if isinstance(dep, str) else "deprecated"
        _flag(r, F_DEPRECATED, f"version {r['version']} is deprecated: {r['deprecated']}")
    scripts = _d(man.get("scripts"))
    r["install_scripts"] = {k: remote(scripts[k], 120) for k in ("preinstall", "install", "postinstall")
                            if isinstance(scripts.get(k), str) and scripts[k].strip()}
    raw = npm_licence(man) or npm_licence(top) or npm_licence(doc)
    r["_licence_raw"], r["licence"] = raw, show_licence(raw)
    if F_PLACEHOLDER not in r["flags"]:  # npm's holder repository is not the package's
        r["repository"] = npm_repo(man) or npm_repo(top) or npm_repo(doc)
    return r


def _resolve_npm(versions: dict, tags: dict, spec: str | None, latest: str | None):
    if not spec or spec.strip() == "*":
        # npm takes the `latest` tag for a bare name or `*` whatever it is, pre-release included, unless deprecated
        if latest and not versions[latest].get("deprecated"):
            return latest, None
        v = max_satisfying(versions, parse_range("*"), latest)
        return (v, None) if v else (None, "no published version npm would install")
    shown = clean(spec, 40)
    if spec in tags:
        v = tags[spec]
        return (v, None) if v in versions else (None, f"dist-tag '{shown}' points at a version that is not listed")
    exact = spec.lstrip("=v").strip()
    if exact in versions:
        return exact, None
    sets = parse_range(spec)
    if sets is None:
        if re.fullmatch(r"[A-Za-z][\w.-]*", spec):
            return None, f"no dist-tag or version '{shown}'"
        return None, f"version spec '{shown}' not understood"
    v = max_satisfying(versions, sets, latest)
    return (v, None) if v else (None, f"no published version matches '{shown}'")


def check_pypi(t: dict, net: Net, today: dt.date) -> dict:
    r = _result(t)
    norm = pep503(t["name"])
    host = net.host(net.pypi_url)
    if not PYPI_NAME.fullmatch(t["name"]):
        r["errors"].append("not a valid PyPI package name; not sent")
        return r
    simple = net.get(f"{net.pypi_url}/simple/{norm}/", {"Accept": "application/vnd.pypi.simple.v1+json"})
    code = simple.get("_error")
    if code == 404:
        _not_found(r, host)
        return r
    if code is not None:
        r["errors"].append(f"{host}: {describe(code)}")
        return r
    r["exists"] = True
    state, why = project_status(simple)
    r["project_status"] = state
    status_note = {
        "archived": "PyPI marks the project archived (PEP 792 status): no new releases are expected",
        "quarantined": "PyPI marks the project quarantined (PEP 792 status): the index considers it unsafe "
                       "and offers no files",
        "deprecated": "PyPI marks the project deprecated (PEP 792 status): obsolete, perhaps superseded",
    }
    if state in status_note:
        flag = {"archived": F_ARCHIVED, "quarantined": F_QUARANTINED, "deprecated": F_DEPRECATED}[state]
        _flag(r, flag, status_note[state] + (f"; reason given: {remote(why)}" if why else ""))
    files = [f for f in simple.get("files") or [] if isinstance(f, dict)] if isinstance(simple.get("files"), list) else []
    uploads = [f["upload-time"] for f in files if isinstance(f.get("upload-time"), str) and _date(f["upload-time"])]
    if uploads:
        r["first_published"] = _date(min(uploads)).isoformat()
        r["age_days"] = days_since(min(uploads), today)
    if not files and state != "quarantined":
        _flag(r, F_NO_FILES, "PyPI lists no files for it: there is nothing to install")

    base = f"{net.pypi_url}/pypi/{norm}"
    pinned = False
    if t["pin"] and PYPI_PIN.fullmatch(t["pin"]):
        doc = net.get(f"{base}/{urllib.parse.quote(t['pin'], safe='')}/json")
        if doc.get("_error") == 404:
            _flag(r, F_NO_VERSION, f"version {clean(t['pin'], 64)} is not on {host}")
            doc = net.get(f"{base}/json")
        else:
            pinned = True
    else:
        doc = net.get(f"{base}/json")
    if doc.get("_error") is not None:
        # without the release's metadata the yank status, licence and repository are unknown, not absent
        r["errors"].append(f"{host} JSON API: {describe(doc['_error'])}")
        r["complete"] = False
    info = _d(doc.get("info"))
    r["version"] = _safe_version(info.get("version"))
    urls = [u for u in doc.get("urls") or [] if isinstance(u, dict)] if isinstance(doc.get("urls"), list) else []
    # PEP 592: installers must skip a yanked release when a non-yanked one satisfies the request, and it
    # suggests using a yanked file only for an exact pin (`==` without `.*`, or `===`). So pins are what is
    # checked. PyPI marks the release and each file; a release whose every file is yanked counts too.
    if pinned and (info.get("yanked") is True or (urls and all(u.get("yanked") is True for u in urls))):
        why = info.get("yanked_reason") or next((u.get("yanked_reason") for u in urls if u.get("yanked_reason")), None)
        r["yanked"] = remote(why) if why else "yanked"
        _flag(r, F_YANKED, f"version {r['version']} was yanked" + (f": {r['yanked']}" if why else ""))
    ups = [u["upload_time_iso_8601"] for u in urls if isinstance(u.get("upload_time_iso_8601"), str)]
    r["version_published"] = _date(min(ups)).isoformat() if ups and _date(min(ups)) else None
    raw, vocabulary = pypi_licence(info)
    r["_licence_raw"], r["licence"] = raw, show_licence(raw, vocabulary)
    r["repository"] = pypi_repo(info)
    return r


def repo_facts(r: dict, net: Net, today: dt.date):
    slug = github_slug(r["repository"])
    if not slug:
        return
    gh = net.github(slug)
    r["repo"] = gh
    if gh.get("error") == "not found":
        _flag(r, F_REPO_MISSING, f"the linked repository {slug} is not on GitHub (deleted, renamed or private)")
        return
    if gh.get("error"):
        return
    days = days_since(gh.get("pushed_at"), today)
    gh["days_since_push"] = days
    gh["status"] = bucket(days, gh.get("archived"))
    name = gh.get("full_name") or slug
    if gh["archived"]:
        pushed = _date(gh.get("pushed_at"))
        _flag(r, F_REPO_ARCHIVED, f"its repository {name} is archived (read-only)"
                                  + (f", last push {pushed.isoformat()}" if pushed else ""))
    elif gh["status"] == "abandoned":
        # Informational only: a finished library (left-pad, a date parser) can go
        # years without a push and still be correct. Archival is the owner saying
        # it is over; silence is not.
        _flag(r, F_ABANDONED, f"its repository {name} was last pushed {days} days ago; finished libraries go quiet too")


def seriousness(r: dict) -> list[str]:
    serious = [f for f in r["flags"] if f in SERIOUS]
    # Install scripts run code at install time with the user's rights, before
    # anyone reads it. Plenty of established packages need them (native builds,
    # binary downloads: esbuild, bcrypt), so on their own they are a fact to
    # report. On a package days old, or with no source to read, there is neither
    # a history nor a repository to check the script against.
    if r["install_scripts"] and {F_NEW, F_NO_REPO, F_REPO_MISSING} & set(r["flags"]):
        serious.append(F_SCRIPTS)
    return serious


_ORDER = {f: i for i, f in enumerate([F_MISSING, F_PLACEHOLDER, F_QUARANTINED, F_YANKED, F_DEPRECATED, F_ARCHIVED,
                                      F_REPO_ARCHIVED, F_NEW, F_SCRIPTS])}


def examine(targets: list[dict], net: Net | None, today: dt.date, *, new_days: int = NEW_DAYS,
            downloads: str = "all", light: bool = False) -> list[dict]:
    """Registry, repository and licence facts for each target, with flags.

    `downloads` is "all", "serious" (the hook: only to give an ask some context)
    or "none"."""
    if net is None:
        out = []
        for t in targets:
            r = _result(t)
            r["notes"].append({"flag": None, "text": "not checked (--offline)"})
            del r["_licence_raw"]
            out.append(r)
        return out
    licences: dict = {}
    licence_lock = threading.Lock()

    def one(t: dict) -> dict:
        r = check_npm(t, net, today, light, new_days) if t["ecosystem"] == "npm" else check_pypi(t, net, today)
        raw = r.pop("_licence_raw", None)
        if r["exists"]:
            if r["age_days"] is not None and r["age_days"] < new_days:
                _flag(r, F_NEW, f"first published {r['first_published']}, {r['age_days']} days ago; pkg-vitals flags "
                                f"packages first published less than {new_days} days ago (its own threshold)")
            if r["repository"]:
                repo_facts(r, net, today)
            elif F_PLACEHOLDER not in r["flags"] and r["complete"]:
                _flag(r, F_NO_REPO, "the package metadata links no source repository")
            if r["install_scripts"]:
                what = "; ".join(f"{k}: {v}" for k, v in r["install_scripts"].items())
                _flag(r, F_SCRIPTS, f"runs code at install time ({what})")
            if raw is None and F_PLACEHOLDER not in r["flags"] and r["complete"]:
                _flag(r, F_NO_LICENCE, "declares no licence")
            if t["scope"] == "project" and strong_copyleft(raw):
                key = (t["ecosystem"], t["cwd"])
                with licence_lock:
                    if key not in licences:
                        licences[key] = project_licence(t["ecosystem"], t["cwd"])
                proj = licences[key]
                if proj and not strong_copyleft(proj["licence"]):
                    _flag(r, F_COPYLEFT, f"licence {r['licence']} is strong copyleft (GPL/AGPL); the project here "
                                         f"declares '{proj['licence']}' in {proj['file']}. A fact to check, "
                                         "not a legal conclusion")
        r["serious"] = seriousness(r)
        r["flags"].sort(key=lambda f: (f not in r["serious"], _ORDER.get(f, 99)))
        r["notes"].sort(key=lambda n: (n["flag"] not in r["serious"], _ORDER.get(n["flag"], 99)))
        if t["ecosystem"] == "npm" and r["exists"] and (downloads == "all" or (downloads == "serious" and r["serious"])):
            d = net.get(f"{net.downloads_url}/last-week/{t['name']}")
            if isinstance(d.get("downloads"), int) and not isinstance(d.get("downloads"), bool):
                r["downloads_week"] = d["downloads"]
        return r

    if not targets:
        return []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(targets))) as pool:
        return list(pool.map(one, targets))


# ---------------------------------------------------------------- output

def label(r: dict) -> str:
    return f"{r['ecosystem']}:{r['name']}"


def show_flag(r: dict, f: str) -> str:
    text = f"new ({r['age_days']} d)" if f == F_NEW else f
    return ("!" + text) if f in r["serious"] else text


def short_repo(url: str | None) -> str:
    if not url:
        return ""
    return github_slug(url) or re.sub(r"^https?://(www\.)?", "", url)


def repo_status(r: dict) -> str:
    gh = r.get("repo") or {}
    if not r["repository"]:
        return ""
    if gh.get("status"):
        d = gh.get("days_since_push")
        return gh["status"] + (f" {d}d" if d is not None and gh["status"] != "archived" else "")
    return "not checked" if not github_slug(r["repository"]) else "unknown"


def unchecked(results: list[dict]) -> list[dict]:
    return [r for r in results if r["exists"] is None or not r.get("complete", True)]


# Skips that are not a failure to check: nothing is fetched, or the user asked for it
BENIGN_SKIPS = ("no package names", "runs the binary already in node_modules/.bin", "matches PKG_VITALS_IGNORE")


def unchecked_skips(skipped: list[dict]) -> list[dict]:
    return [s for s in skipped if not s["reason"].startswith(BENIGN_SKIPS)]


def summary_line(results: list[dict]) -> str:
    serious = sum(1 for r in results if r["serious"])
    missing = sum(1 for r in results if r["exists"] is False)
    parts = [f"{len(results)} package{'s' * (len(results) != 1)}", f"{serious} with a serious flag"]
    if missing:
        parts.append(f"{missing} not found")
    if unchecked(results):
        parts.append(f"{len(unchecked(results))} not checked")
    return " · ".join(parts)


def _notes(results: list[dict]) -> list[str]:
    out = []
    for r in results:
        head = label(r) + (f" {r['version']}" if r["version"] else "")
        for n in r["notes"]:
            out.append(f"{head}: {n['text']}")
        for e in r["errors"]:
            out.append(f"{head}: could not check, {e}")
    return out


def sources_line(report: dict) -> str:
    hosts = report.get("hosts") or {"npm": "registry.npmjs.org and api.npmjs.org", "pypi": "pypi.org"}
    used = sorted({hosts[r["ecosystem"]] for r in report["packages"] if r["exists"] is not None})
    if any((r.get("repo") or {}).get("source") == "GitHub API" for r in report["packages"]):
        used.append("the GitHub REST API")
    if any(str((r.get("repo") or {}).get("source", "")).startswith("agent-vitals") for r in report["packages"]):
        used.append("the agent-vitals census (CC0 1.0)")
    return f"Sources: {', '.join(used)}; retrieved {report['checked']}." if used else ""


def render_text(report: dict) -> str:
    results, skipped = report["packages"], report["skipped"]
    lines = []
    if not results:
        lines.append("Nothing to check: no npm or PyPI package names found.")
    else:
        cols = [("package", label), ("version", lambda r: r["version"] or ""),
                ("first published", lambda r: r["first_published"] or ""),
                ("downloads/wk", lambda r: f"{r['downloads_week']:,}" if isinstance(r["downloads_week"], int) else ""),
                ("repository", lambda r: short_repo(r["repository"])), ("repo status", repo_status),
                ("licence", lambda r: r["licence"] if r["licence"] and not r["licence"].startswith("<<") else
                 ("see notes" if r["licence"] else "")),
                ("flags", lambda r: ", ".join(show_flag(r, f) for f in r["flags"]))]
        rows = [[str(f(r)) for _, f in cols] for r in results]
        widths = [min(max(len(h), *(len(row[i]) for row in rows)), 44) for i, (h, _) in enumerate(cols)]

        def fmt(cells):
            # every column but the last is cut to its width; the flags are the point, so they never are
            out = [(c[:w].rjust(w) if i == 3 else c[:w].ljust(w)) for i, (c, w) in enumerate(zip(cells[:-1], widths))]
            return "  ".join(out + [cells[-1]]).rstrip()
        lines += [fmt([h for h, _ in cols]), fmt(["-" * w for w in widths])] + [fmt(row) for row in rows]
        lines += ["", summary_line(results)]
        notes = _notes(results)
        for r in results:
            if r["licence"] and r["licence"].startswith("<<"):
                notes.append(f"{label(r)}: licence field {r['licence']}")
        if notes:
            lines += [""] + notes
    if skipped:
        lines += ["", "Not checked: " + "; ".join(f"{s['spec']} ({s['reason']})" for s in skipped)]
    if results and not report.get("offline"):
        lines += ["", f"! marks a serious flag: the hook asks before installing and --strict exits 1. 'new' means first "
                      f"published less than {report['new_days']} days ago, pkg-vitals' own threshold."]
        if report.get("github") != "api" and any(github_slug(r["repository"]) for r in results):
            lines.append("The GitHub API refused or rate-limited the lookups, so repository facts came from the agent-vitals "
                         "census where it lists the repository (it covers agent tooling). If the limit was the cause, "
                         "GITHUB_TOKEN raises it.")
        if any(r["ecosystem"] == "pypi" for r in results):
            lines.append("PyPI publishes no download counts through its API, so that column is empty for PyPI.")
        src = sources_line(report)
        if src:
            lines.append(src)
    return mask("\n".join(lines) + "\n")


def render_markdown(report: dict) -> str:
    esc = lambda t: str(t).replace("|", "\\|")  # noqa: E731
    out = [f"### Packages checked with pkg-vitals, {report['checked']}", "",
           "| Package | Version | First published | Downloads/week | Repository | Repo status | Licence | Flags |",
           "| --- | --- | --- | ---: | --- | --- | --- | --- |"]
    for r in report["packages"]:
        url = r["repository"]
        repo = f"[{esc(short_repo(url))}]({url})" if url else ""
        dl = f"{r['downloads_week']:,}" if isinstance(r["downloads_week"], int) else ""
        flags = ", ".join((f"**{esc(show_flag(r, f)[1:])}**" if f in r["serious"] else esc(show_flag(r, f))) for f in r["flags"])
        out.append(f"| `{esc(label(r))}` | {esc(r['version'] or '')} | {r['first_published'] or ''} | {dl} | {repo} | "
                   f"{repo_status(r)} | {esc(r['licence'] or '')} | {flags} |")
    out += ["", summary_line(report["packages"])]
    notes = _notes(report["packages"])
    if notes:
        out += [""] + [f"- {esc(n)}" for n in notes]
    if report["skipped"]:
        out += ["", "Not checked: " + "; ".join(f"`{esc(s['spec'])}` ({s['reason']})" for s in report["skipped"])]
    src = sources_line(report)
    out += ["", "_Registry facts from [pkg-vitals](https://github.com/Keremozdemirra/pkg-vitals), "
                "not a verdict on anyone's package." + (f" {src}" if src else "") + "_"]
    return mask("\n".join(out) + "\n")


# ---------------------------------------------------------------- command line

INSTALLERS = {"npm", "npx", "pnpm", "pnpx", "yarn", "bun", "bunx", "pip", "pip3", "python", "python3", "uv", "uvx",
              "poetry", "pipx"}


def utc_today() -> dt.date:
    return dt.datetime.now(dt.timezone.utc).date()


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def main(argv: list[str] | None = None) -> int:
    """Exit codes: 0 done (with --strict: nothing serious), 1 a serious flag under --strict,
    2 a usage error, or under --strict a package that could not be checked."""
    argv = list(sys.argv[1:] if argv is None else argv)
    command = None
    if "--" in argv:
        i = argv.index("--")
        argv, command = argv[:i], argv[i + 1:]
    ap = argparse.ArgumentParser(
        prog="pkg-vitals",
        description="Check npm and PyPI packages before installing them: does the name exist, is it brand new, "
                    "deprecated or yanked, does it run install scripts, is its repository archived, which licence?",
        epilog="examples:\n  pkg-vitals npm left-pad @scope/pkg@^2\n  pkg-vitals pypi 'requests==2.32.0' httpx\n"
               "  pkg-vitals -- npm install foo bar@2 -D\n  pkg-vitals -- 'cd app && npm i x; pip install y'\n\n"
               "exit codes: 0 done; with --strict, 1 = a serious flag, 2 = a package could not be checked",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ecosystem", nargs="?", metavar="npm|pypi", help="the registry the names belong to")
    ap.add_argument("names", nargs="*", metavar="NAME", help="package names, with an optional version or range")
    ap.add_argument("--json", action="store_true", help="print JSON")
    ap.add_argument("--markdown", action="store_true", help="print a Markdown table, for an issue or a pull request")
    ap.add_argument("--offline", action="store_true", help="send nothing; only show what the command line names")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 if any package has a serious flag, 2 if any could not be checked")
    ap.add_argument("--new-days", type=int, default=int(_env_float("PKG_VITALS_NEW_DAYS", NEW_DAYS)), metavar="N",
                    help=f"flag packages first published less than N days ago (default {NEW_DAYS}, this tool's own choice)")
    ap.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    a, extra = ap.parse_known_intermixed_args(argv)
    if extra:
        ap.error(f"unrecognized arguments: {mask(' '.join(extra))} (put an install command after --, "
                 "as in: pkg-vitals -- npm install foo -D)")
    eco, names = (a.ecosystem or "").lower(), list(a.names)
    if command is None and eco in INSTALLERS and (eco != "npm" or (names and names[0] in NPM_INSTALL | NPM_LOCKFILE
                                                                   | {"exec", "x", "create", "init"})):
        command, eco, names = [a.ecosystem] + names, "", []  # `pkg-vitals npm install foo` means the command line
    if command is not None and (eco or names):
        ap.error("give either npm|pypi NAMES or an install command after --, not both")
    if command is None and eco not in ("npm", "pypi"):
        ap.error("say npm or pypi and the package names, or pass an install command after --")
    if command is None and not names:
        ap.error(f"no package names given for {eco}")
    if hasattr(sys.stdout, "reconfigure"):  # a console that cannot print a character should not crash the run
        sys.stdout.reconfigure(errors="replace")

    today = utc_today()
    cwd = os.getcwd()
    if command is not None:
        text = command[0] if len(command) == 1 else shlex.join(command)
        parsed = parse_command(text, cwd=cwd)
    else:
        found = _Found(cwd, os.environ)
        for n in names:
            found.add(eco, n, eco, "project", at_syntax=True)
        parsed = {"targets": found.targets, "skipped": found.skipped}
    net = None if a.offline else Net(timeout=_env_float("PKG_VITALS_TIMEOUT", 20.0),
                                     token=os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"))
    results = examine(parsed["targets"], net, today, new_days=a.new_days, downloads="all")
    report = {"checked": today.isoformat(), "tool": f"pkg-vitals {VERSION}", "new_days": a.new_days,
              "offline": a.offline, "github": "offline" if net is None else ("census" if net.github_down else "api"),
              "hosts": {} if net is None else {"npm": f"{net.host(net.npm_url)} and {net.host(net.downloads_url)}",
                                               "pypi": net.host(net.pypi_url)},
              "packages": results, "skipped": parsed["skipped"]}
    if a.json:
        report["sources"] = sources_line(report)
        print(json.dumps(scrub(report), indent=1, ensure_ascii=False))
    elif a.markdown:
        sys.stdout.write(render_markdown(report))
    else:
        sys.stdout.write(render_text(report))
    if a.strict and not a.offline:
        if any(r["serious"] for r in results):
            return 1
        if unchecked(results) or unchecked_skips(parsed["skipped"]):
            return 2
    return 0


# ---------------------------------------------------------------- hook

SHELL_TOOLS = ("Bash", "PowerShell")


def explain(found: list[dict]) -> str:
    """The permission prompt's reason: the facts behind each serious flag, one sentence per package."""
    parts = []
    for r in found[:5]:
        what = f"{'PyPI' if r['ecosystem'] == 'pypi' else 'npm'} package '{r['name']}'" + (f" {r['version']}" if r["version"] else "")
        facts = [n["text"] for n in r["notes"] if n["flag"] in r["serious"]]
        if F_NO_REPO in r["flags"]:
            facts.append("it links no source repository")
        if isinstance(r["downloads_week"], int):
            facts.append(f"{r['downloads_week']:,} downloads last week")
        parts.append(f"{what}: " + "; ".join(facts) + ".")
    if len(found) > 5:
        parts.append(f"{len(found) - 5} more package(s) have serious flags; run pkg-vitals on the command to see them.")
    return mask("pkg-vitals: " + " ".join(parts) + " Registry facts, not a verdict on the package.")


def hook_response(payload, net: Net | None = None, today: dt.date | None = None) -> dict | None:
    """The PreToolUse answer for a Bash or PowerShell tool call, or None to stay silent."""
    if not isinstance(payload, dict) or payload.get("hook_event_name") != "PreToolUse" \
            or payload.get("tool_name") not in SHELL_TOOLS:
        return None
    command = _d(payload.get("tool_input")).get("command")
    if not isinstance(command, str) or not command.strip():
        return None
    cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) else None
    parsed = parse_command(command, cwd=cwd, powershell=payload.get("tool_name") == "PowerShell")
    if not parsed["targets"]:
        return None
    if net is None:
        # Short: someone is waiting for the command to start. The budget stays
        # under the 20 s timeout in hooks.json, so the hook answers or stays
        # silent before Claude Code gives up on it.
        net = Net(timeout=_env_float("PKG_VITALS_TIMEOUT", 5.0), census=False,
                  token=os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"),
                  budget=_env_float("PKG_VITALS_BUDGET", 15.0))
    results = examine(parsed["targets"], net, today or utc_today(),
                      new_days=int(_env_float("PKG_VITALS_NEW_DAYS", NEW_DAYS)), downloads="serious", light=True)
    found = [r for r in results if r["serious"]]
    if not found:
        return None
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask",
                                   "permissionDecisionReason": explain(found)}}


# A command that names none of these cannot install from npm or PyPI. The hook
# runs on every shell command, so this check comes before any real work.
QUICK = re.compile(r"(?i)\b(npm|npx|pnpm|pnpx|yarn|bun|bunx|pip[0-9.]*|pipx|python[0-9.]*|pypy[0-9.]*|py|uv|uvx|poetry)\b")


def claim(tool_use_id) -> bool:
    """True for the first process that takes this tool call. Claude Code runs every matching handler as its own
    process (a plugin copy and a settings copy of the same hook both run); an O_EXCL file per tool_use_id lets
    exactly one of them work. When no lock can be taken, work anyway: a check done twice beats none."""
    key = re.sub(r"[^A-Za-z0-9_-]", "", str(tool_use_id or ""))[:120]
    if not key:
        return True
    try:
        uid = os.getuid() if hasattr(os, "getuid") else None
        d = Path(tempfile.gettempdir()) / f"pkg-vitals-{uid if uid is not None else 'user'}"
        d.mkdir(mode=0o700, exist_ok=True)
        if d.is_symlink() or (uid is not None and d.stat().st_uid != uid):
            return True
        now = time.time()
        for e in os.scandir(d):  # claims older than ten minutes belong to finished calls
            try:
                if now - e.stat().st_mtime > 600:
                    os.unlink(e.path)
            except OSError:
                pass
        os.close(os.open(str(d / key), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
        return True
    except FileExistsError:
        return False
    except OSError:
        return True


def hook_main(raw=None) -> int:
    """Claude Code PreToolUse hook: reads the payload on stdin, answers on stdout, never denies."""
    try:
        if raw is None:
            # bytes, decoded here: a Windows console's default encoding is not the UTF-8 Claude Code sends
            raw = sys.stdin.buffer.read() if hasattr(sys.stdin, "buffer") else sys.stdin.read()
        payload = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
    except (ValueError, UnicodeDecodeError, OSError):
        return 0
    try:
        command = _d(_d(payload).get("tool_input")).get("command")
        if not isinstance(command, str) or not QUICK.search(command) or not claim(payload.get("tool_use_id")):
            return 0
        out = hook_response(payload)
    except Exception:  # noqa: BLE001 - a hook that breaks the tool call over its own bug is worse than none
        traceback.print_exc()  # stderr of a hook that exits 0 goes to Claude Code's debug log only
        return 0
    if out:
        print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
