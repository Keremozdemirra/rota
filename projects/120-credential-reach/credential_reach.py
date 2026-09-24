#!/usr/bin/env python3
"""credential-reach: which credentials could an AI agent session on this machine use?

An agent that runs commands as you inherits your environment variables, your
cloud CLI logins, your kubeconfig, your registry tokens, your SSH keys and
whatever sits in the project's .env files. This lists them, grouped by what
they reach, without printing a secret: names, locations, hosts, profiles,
lengths and presence only.

Standard library only, one file, so it runs without installing anything:

  curl -sL https://raw.githubusercontent.com/Keremozdemirra/credential-reach/main/credential_reach.py | python3 -

What it reads, sends and changes:

- Reads the credential files of the AWS CLI, gcloud, the Azure CLI, kubectl,
  Docker, npm, twine (.pypirc), netrc, git, gh, OpenSSH and Terraform in their
  standard places (and where their own environment variables point), the
  process environment, the project's .env and secret-named files, and Claude
  Code transcripts. Values are parsed only to tell what kind of credential
  sits there; no value leaves the process.
- Sends nothing, unless --probe is given. Then each GitHub token it found for
  github.com goes once to GET https://api.github.com/user, to read the scopes
  GitHub reports for it. That uses the token.
- Changes nothing, unless --redact is given and confirmed at a terminal. Then
  secret-shaped strings in Claude Code transcripts are replaced in place with
  [REDACTED:<type>], after each changed file is copied to a backup directory.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import codecs
import configparser
import datetime as dt
import fnmatch
import http.client
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path, PurePath

VERSION = "0.1.0"
UA = f"credential-reach/{VERSION} (+https://github.com/Keremozdemirra/credential-reach)"
GITHUB_USER_API = "https://api.github.com/user"
MAX_FILE = 4 * 1024 * 1024  # credential files are small; anything bigger is not one, and is not read
SEVERITIES = ("high", "medium", "info")

# ---------------------------------------------------------------- secret shapes
# A token starts at a word edge, so that `task-...` is not taken for an `sk-` key.
_B = r"(?<![A-Za-z0-9])"
# Order matters: a pattern replaces its matches before the next one runs, so a key
# inside a private-key block, or a JWT after "Bearer", is counted once.
# The first seven are the shapes ship.sh and publish.sh scan for; the rest are common ones.
SECRET_PATTERNS = [(name, re.compile(rx)) for name, rx in (
    ("private-key", r"-{5}BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-{5}"
                    r"(?:[\s\S]*?-{5}END (?:[A-Z0-9]+ )*PRIVATE KEY-{5}|[A-Za-z0-9+/=\s:,-]*)"),
    ("anthropic-api-key", _B + r"sk-ant-[A-Za-z0-9_-]{20,}"),
    ("openai-api-key", _B + r"sk-(?:(?:proj|svcacct|admin)-[A-Za-z0-9_-]{20,}|[A-Za-z0-9]{32,})"),
    ("github-classic-pat", _B + r"ghp_[A-Za-z0-9]{36,}"),
    ("github-fine-grained-pat", _B + r"github_pat_[A-Za-z0-9_]{22,}"),
    ("aws-access-key-id", _B + r"(?:AKIA|ASIA)[0-9A-Z]{16}(?![0-9A-Za-z])"),
    ("replicate-api-token", _B + r"r8_[A-Za-z0-9]{32,}"),
    ("github-oauth-token", _B + r"gho_[A-Za-z0-9]{36,}"),
    # ghs_ has had a second, stateless form (ghs_APPID_JWT) since 2026-04-27 (GitHub docs, checked 2026-09-24)
    ("github-app-token", _B + r"gh[usr]_(?:[0-9]+_[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+|[A-Za-z0-9]{36,})"),
    ("aws-secret-access-key", r"(?i:aws_secret_access_key|secretaccesskey)\\*[\"']?\s*[:=]\s*\\*[\"']?"
                              r"(?P<s>[A-Za-z0-9/+]{40})(?![A-Za-z0-9/+])"),
    ("slack-token", _B + r"xox[abprse]-[A-Za-z0-9-]{10,}"),
    ("gitlab-token", _B + r"glpat-[A-Za-z0-9_-]{20,}"),
    ("google-api-key", _B + r"AIza[0-9A-Za-z_-]{35}(?![0-9A-Za-z_-])"),
    ("stripe-secret-key", _B + r"[sr]k_live_[0-9A-Za-z]{24,}"),
    ("npm-token", _B + r"npm_[A-Za-z0-9]{36,}"),
    ("pypi-token", _B + r"pypi-AgEIcHlwaS5vcmc[A-Za-z0-9_-]{50,}"),
    ("huggingface-token", _B + r"hf_[A-Za-z0-9]{34,}"),
    ("jwt", _B + r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    # only the password part is replaced; `${VAR}`, `***` and `<...>` are references, not passwords
    ("url-password", r"[A-Za-z][A-Za-z0-9+.-]*://[^\s:/@\"'<>\[\]]+:(?P<s>(?!\[REDACTED)(?![$*<{])[^\s@/\"'<>]{1,256})@"),
    ("bearer-token", r"(?i:\bbearer)\s+(?P<s>(?!\[REDACTED)[A-Za-z0-9._~+/-]{20,}=*)"),
)]
SECRET_LABELS = {
    "private-key": "private key", "anthropic-api-key": "Anthropic API key", "openai-api-key": "OpenAI API key",
    "github-classic-pat": "GitHub personal access token (classic)",
    "github-fine-grained-pat": "GitHub fine-grained personal access token",
    "aws-access-key-id": "AWS access key ID", "replicate-api-token": "Replicate API token",
    "github-oauth-token": "GitHub OAuth token", "github-app-token": "GitHub App token",
    "aws-secret-access-key": "AWS secret access key", "slack-token": "Slack token",
    "gitlab-token": "GitLab access token", "google-api-key": "Google API key",
    "stripe-secret-key": "Stripe secret key", "npm-token": "npm access token", "pypi-token": "PyPI API token",
    "huggingface-token": "Hugging Face token", "jwt": "JSON Web Token",
    "url-password": "URL with an embedded password", "bearer-token": "bearer token",
}
# A cheap first look at a raw transcript line; only lines that pass are decoded, parsed and matched.
# Substring tests run at C speed; one regex alternation over every line ran at about 15 MB/s.
_ANYWHERE = (b"AKIA", b"ASIA", b"PRIVATE KEY", b"AIza", b"pypi-", b"eyJ")
_ANYWHERE_LOWER = (b"bearer", b"secret_access_key", b"secretaccesskey")
_AT_EDGE = (b"sk-", b"sk_live_", b"rk_live_", b"ghp_", b"gho_", b"ghu_", b"ghs_", b"ghr_", b"github_pat_", b"r8_",
            b"xox", b"glpat-", b"npm_", b"hf_")
_URL_USERINFO = re.compile(rb"://[^/\s\"@]*@")


def triggered(body: bytes) -> bool:
    """False only when no secret pattern can match anywhere in `body`."""
    if any(x in body for x in _ANYWHERE):
        return True
    low = body.lower()
    if any(x in low for x in _ANYWHERE_LOWER):
        return True
    for lit in _AT_EDGE:
        i = body.find(lit)
        while i != -1:
            if i == 0 or not body[i - 1:i].isalnum():
                return True
            i = body.find(lit, i + 1)
    return b"@" in body and _URL_USERINFO.search(body) is not None


def redact_text(text: str) -> tuple[str, dict]:
    """`text` with every secret-shaped string replaced by [REDACTED:<type>], and the count per type."""
    counts: dict = {}
    for name, rx in SECRET_PATTERNS:
        def repl(m, name=name, rx=rx):
            counts[name] = counts.get(name, 0) + 1
            label = f"[REDACTED:{name}]"
            if "s" in rx.groupindex and m.group("s") is not None:
                whole, start = m.group(0), m.start()
                return whole[:m.start("s") - start] + label + whole[m.end("s") - start:]
            return label
        text = rx.sub(repl, text)
    return text, counts


def looks_like(value: str) -> str | None:
    """The type of the first secret shape found in `value`, or None."""
    for name, rx in SECRET_PATTERNS:
        if rx.search(value):
            return name
    return None


# ---------------------------------------------------------------- cleaning and masking
CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u200b-\u200f\u2028\u2029\u202a-\u202e\u2066-\u2069\ufeff]")
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?")  # colour codes, terminal titles
URL_IN_TEXT = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s\"'<>`]+")


def clean(text, limit: int = 120) -> str:
    """Text made safe to print: no control or bidi characters, one line, bounded."""
    t = re.sub(r"\s+", " ", CONTROL.sub(" ", ANSI.sub("", str(text)))).strip()
    return t if len(t) <= limit else t[:limit - 3].rstrip() + "..."


def _secret_segment(seg: str) -> bool:
    # a path segment like a key: long, letters mixed with digits (tokens some registries put in the URL path)
    return looks_like(seg) is not None or (
        len(seg) >= 24 and re.fullmatch(r"[A-Za-z0-9_\-+=.~]+", seg) is not None
        and re.search(r"[0-9]", seg) is not None and re.search(r"[A-Za-z]", seg) is not None)


def mask_url(u: str) -> str:
    """`https://user:pw@host/p/<key>?k=v#f` -> `https://***@host/p/***?***#***`."""
    try:
        p = urllib.parse.urlsplit(u)
        host, port = p.hostname or "", p.port
    except ValueError:
        return "***"
    if not p.scheme or not p.netloc:
        return "***" if looks_like(u) else u
    host = f"[{host}]" if ":" in host else host
    netloc = ("***@" if "@" in p.netloc else "") + host + (f":{port}" if port else "")
    path = "/".join("***" if _secret_segment(s) else s for s in p.path.split("/"))
    return f"{p.scheme}://{netloc}{path}" + ("?***" if p.query else "") + ("#***" if p.fragment else "")


def safe(text, limit: int = 120) -> str:
    """Anything read from a file or the environment, fit to print. Masks first, then cuts, so a cut
    cannot remove the delimiter a mask looks for."""
    masked = URL_IN_TEXT.sub(lambda m: mask_url(m.group(0)), str(text))
    return clean(redact_text(masked)[0], limit)


def host_of(url: str) -> str:
    try:
        p = urllib.parse.urlsplit(url if "://" in url else "https://" + url)
        host, port = p.hostname or "", p.port
    except ValueError:
        return "?"
    if not re.fullmatch(r"[A-Za-z0-9.\-_:]{1,253}", host or "-"):
        return "?"
    host = f"[{host}]" if ":" in host else host
    return (host + (f":{port}" if port else "")) or "?"


# ---------------------------------------------------------------- files
def decode_bytes(data: bytes) -> str:
    """UTF-8 with or without a BOM, UTF-16 with a BOM (PowerShell 5 redirection writes that), else Latin-1."""
    if data.startswith(codecs.BOM_UTF8):
        return data[3:].decode("utf-8", "replace")
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return data.decode("utf-16", "replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def is_regular(p) -> bool:
    try:
        return stat.S_ISREG(os.stat(p).st_mode)
    except (OSError, ValueError):
        return False


def exists(p) -> bool:
    try:
        os.stat(p)
        return True
    except (OSError, ValueError):
        return False


def read_file(p, limit: int = MAX_FILE) -> tuple[str | None, str]:
    """(text, "") or (None, why). A FIFO or device is never opened, so a read cannot block."""
    if not is_regular(p):
        return None, "not a regular file" if exists(p) else "missing"
    try:
        with open(p, "rb") as f:
            data = f.read(limit + 1)
    except OSError as e:
        return None, f"unreadable ({type(e).__name__})"
    if len(data) > limit:
        return None, f"larger than {limit // 1024} KB, not read"
    return decode_bytes(data), ""


def load_json(text: str):
    """The parsed JSON value, or raise ValueError."""
    return json.loads(text)


def ini(text: str) -> configparser.ConfigParser:
    # AWS calls a real profile `default`, so configparser's DEFAULT section handling is switched off;
    # interpolation is off because values are secrets, not templates.
    cp = configparser.ConfigParser(interpolation=None, strict=False, default_section="\x00none")
    cp.read_string(text)
    return cp


# ---------------------------------------------------------------- where things live
class Context:
    """Where to look: a home directory, an environment and an operating system, all replaceable in tests."""

    def __init__(self, home, env=None, system: str | None = None, project=None, probe: bool = False,
                 now: dt.datetime | None = None):
        # normalised, so that a HOME like /home/me/work/.. still prints paths as ~/...
        self.home = Path(os.path.abspath(home)) if isinstance(home, (str, Path)) else home
        self.env = dict(os.environ if env is None else env)
        self.system = system or platform.system()
        self.project = project
        self.probe = probe
        self.now = now or dt.datetime.now(dt.timezone.utc)
        # token -> where it was found. In memory for --probe only; never printed, logged or written.
        self.github_tokens: dict = {}

    @property
    def windows(self) -> bool:
        return self.system == "Windows"

    def get(self, name: str) -> str | None:
        v = self.env.get(name)
        return v if v else None

    def path_env(self, *names: str) -> Path | None:
        for n in names:
            if self.get(n):
                return Path(os.path.expanduser(self.env[n]))
        return None

    def config_home(self) -> Path:
        return self.path_env("XDG_CONFIG_HOME") or Path(self.home) / ".config"

    def appdata(self) -> Path:
        return self.path_env("APPDATA") or Path(self.home) / "AppData" / "Roaming"

    def claude_dir(self) -> Path:
        return self.path_env("CLAUDE_CONFIG_DIR") or Path(self.home) / ".claude"

    def show(self, p) -> str:
        """A path as printed: under the home directory as ~/..., with the platform's separator."""
        p = p if isinstance(p, PurePath) else Path(p)
        try:
            rel = p.relative_to(self.home)
        except ValueError:
            return safe(str(p), 200)
        sep = "\\" if self.windows else "/"
        return "~" if not rel.parts else safe("~" + sep + sep.join(rel.parts), 200)

    def add_token(self, token: str, where: str, strict_github: bool = True) -> None:
        if not self.probe or not isinstance(token, str):
            return
        token = token.strip()
        if GITHUB_TOKEN_SHAPE.fullmatch(token) or (not strict_github and LEGACY_GITHUB_TOKEN.fullmatch(token)):
            self.github_tokens.setdefault(token, [])
            if where not in self.github_tokens[token]:
                self.github_tokens[token].append(where)


# ---------------------------------------------------------------- report model
class Section:
    def __init__(self, sid: str, title: str):
        self.id, self.title = sid, title
        self.paths: list = []
        self.findings: list = []
        self.notes: list = []
        self.errors: list = []
        self.store_note = ""
        self.found = False

    def add(self, severity: str, item: str, detail: str, reach: str = "", **facts) -> dict:
        f = {"severity": severity, "item": item, "detail": detail}
        if reach:
            f["reach"] = reach
        f.update({k: v for k, v in facts.items() if v is not None})
        self.findings.append(f)
        self.found = True
        return f

    def error(self, where: str, why: str) -> None:
        self.errors.append(f"{where}: {why}")
        self.found = True

    def as_dict(self) -> dict:
        order = {s: i for i, s in enumerate(SEVERITIES)}
        return {"id": self.id, "title": self.title, "paths": self.paths,
                "findings": sorted(self.findings, key=lambda f: order[f["severity"]]),
                "notes": self.notes, "errors": self.errors, "not_visible": self.store_note}


def program_name(text) -> str:
    """The base name of the program a config names, or "a program" when it is anything but a plain name:
    a command line or an assignment there may carry a secret."""
    m = re.match(r"\s*(?:\"([^\"]*)\"|'([^']*)'|(\S+))", str(text or ""))
    first = next((g for g in m.groups() if g), "") if m else ""
    base = re.split(r"[\\/]", first)[-1]
    return base if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,63}", base) else "a program"


def _a(label: str) -> str:
    return ("an " if label[:1].lower() in "aeio" else "a ") + label


def _count(n: int, word: str, plural: str = "") -> str:
    return f"{n} {word if n == 1 else plural or word + 's'}"


# ---------------------------------------------------------------- environment
AWS_SECRET_NAMES = {"AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_SECURITY_TOKEN",
                    "AWS_BEARER_TOKEN_BEDROCK", "AWS_CONTAINER_AUTHORIZATION_TOKEN"}
SECRET_NAMES = {"PGPASSWORD", "MYSQL_PWD", "REDISCLI_AUTH", "DOCKER_AUTH_CONFIG"}
SECRET_WORDS = {"TOKEN", "TOKENS", "SECRET", "SECRETS", "PASSWORD", "PASSWORDS", "PASSWD", "PASS", "PWD",
                "PASSPHRASE", "APIKEY", "CREDENTIAL", "CREDENTIALS", "PAT", "AUTHTOKEN", "PRIVATEKEY",
                "ACCESSKEY", "SECRETKEY", "WEBHOOK"}
NOT_SECRET_NAMES = {"PWD", "OLDPWD"}  # the shell's working directories
PATH_WORDS = {"FILE", "PATH", "DIR", "LOCATION"}
PLACEHOLDER = re.compile(r"(?i)<[^>]*>|\$\{[^}]*\}|\$[A-Za-z_][A-Za-z0-9_]*|%[A-Za-z_][A-Za-z0-9_]*%|x{3,}|\*{3,}"
                         r"|\.{3}|change[-_ ]?me|your[-_ ].*|todo|tbd|\[redacted[^\]]*\]")


def is_placeholder(value: str) -> bool:
    return PLACEHOLDER.fullmatch(value.strip().strip("\"'")) is not None


def env_kind(name: str, value: str) -> str | None:
    """secret, path (to a credential file), setting (an AWS_ variable that holds none), or None."""
    up = name.upper()
    if up in NOT_SECRET_NAMES:
        return None
    words = [w for w in re.split(r"[^A-Z0-9]+", up) if w]
    named = (up in AWS_SECRET_NAMES or up in SECRET_NAMES or bool(SECRET_WORDS & set(words))
             or (len(words) > 1 and words[-1] in ("KEY", "KEYS")))
    if up == "GOOGLE_APPLICATION_CREDENTIALS" or (named and words[-1] in PATH_WORDS):
        return "path"
    if named or (value and looks_like(value)):
        return "secret"
    if up.startswith("AWS_"):
        return "setting"
    return None


def github_reach(kind: str) -> str:
    if kind == "github-classic-pat":
        return "a classic token reaches every repository the account can access"
    if kind == "github-fine-grained-pat":
        return "its repositories and permissions were chosen when it was created"
    if kind in ("github-oauth-token", "github-app-token"):
        return "what it reaches depends on its scopes or app permissions"
    return ""


def scan_env(ctx: Context) -> Section:
    sec = Section("environment", "Environment variables")
    for name in sorted(ctx.env):
        value = ctx.env[name] or ""
        kind = env_kind(name, value)
        if kind is None:
            continue
        shown = safe(name, 80)
        shape = looks_like(value) if value else None
        facts = {"length": len(value), "kind": kind, "looks_like": shape}
        if kind == "setting":
            sec.add("info", shown, f"{len(value)} chars, setting", **facts)
        elif not value.strip():
            sec.add("info", shown, "empty", **facts)
        elif kind == "path":
            target = Path(os.path.expanduser(value.strip()))
            there = "an existing file" if is_regular(target) else "a path that is not a file here"
            sev = "medium" if is_regular(target) else "info"
            sec.add(sev, shown, f"{len(value)} chars, points to {there}",
                    reach=f"Environment: {shown} points to a credential file" if sev == "medium" else "", **facts)
        elif is_placeholder(value):
            sec.add("info", shown, f"{len(value)} chars, placeholder-like value", **facts)
        else:
            label = SECRET_LABELS.get(shape, "credential-like value")
            detail = f"{len(value)} chars, {label}"
            if name.upper() == "AWS_ACCESS_KEY_ID":
                detail += ", long-term" if value.startswith("AKIA") else ", temporary" if value.startswith("ASIA") else ""
            extra = github_reach(shape or "")
            reach = f"Environment: {shown} holds {_a(label)}" + (f"; {extra}" if extra else "")
            sec.add("high", shown, detail, reach=reach, **facts)
            if name.upper() in ("GITHUB_TOKEN", "GH_TOKEN"):
                ctx.add_token(value, f"${shown}", strict_github=False)
            elif shape and shape.startswith("github") and not re.search(r"ENTERPRISE|GHE", name.upper()):
                ctx.add_token(value, f"${shown}")
    if ctx.get("CLAUDECODE") == "1":
        scrub = ctx.get("CLAUDE_CODE_SUBPROCESS_ENV_SCRUB") == "1"
        sec.notes.append("Started inside Claude Code: this is the environment its Bash tool passes to commands"
                         + (", after CLAUDE_CODE_SUBPROCESS_ENV_SCRUB removed the credentials it recognises."
                            if scrub else ". CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1 strips credentials it recognises "
                            "from that environment (Claude Code env-vars docs)."))
    sec.found = bool(sec.findings)
    return sec


# ---------------------------------------------------------------- AWS
def _iso_time(s) -> dt.datetime | None:
    if not isinstance(s, str):
        return None
    t = s.strip().replace("UTC", "+00:00")
    t = t[:-1] + "+00:00" if t.endswith("Z") else t
    try:
        d = dt.datetime.fromisoformat(t)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def _role(arn: str) -> str:
    m = re.fullmatch(r"arn:aws[a-z-]*:iam::(\d{12}):role/([\w+=,.@/-]{1,128})", arn.strip())
    return f"role {m.group(2)} in account {m.group(1)}" if m else "a role"


def scan_aws(ctx: Context) -> Section:
    sec = Section("aws", "AWS CLI")
    sec.store_note = ("Profiles that use credential_process run another program, which may read macOS Keychain "
                      "or Windows Credential Manager; what it returns is not visible here.")
    aws = Path(ctx.home) / ".aws"
    files = [(ctx.path_env("AWS_SHARED_CREDENTIALS_FILE") or aws / "credentials", False),
             (ctx.path_env("AWS_CONFIG_FILE") or aws / "config", True)]
    profiles: dict = {}
    for path, is_config in files:
        sec.paths.append(ctx.show(path))
        text, why = read_file(path)
        if text is None:
            if why != "missing":
                sec.error(ctx.show(path), why)
            continue
        sec.found = True
        try:
            cp = ini(text)
        except (configparser.Error, ValueError) as e:
            sec.error(ctx.show(path), f"could not parse ({type(e).__name__})")
            continue
        for section in cp.sections():
            if is_config:
                if section.strip() == "default":
                    name = "default"
                elif section.startswith("profile "):
                    name = section[8:].strip()
                else:
                    continue  # sso-session, services, plugins: not profiles
            else:
                name = section.strip()
            p = profiles.setdefault(name, {"where": [], "auth": []})
            p["where"].append(ctx.show(path))
            s = {k: (v or "").strip() for k, v in cp[section].items()}
            here = ctx.show(path)
            if s.get("aws_secret_access_key"):
                temporary = bool(s.get("aws_session_token")) or s.get("aws_access_key_id", "").startswith("ASIA")
                p["auth"].append(("keys-temporary" if temporary else "keys", "", here))
            elif s.get("aws_access_key_id"):
                p["auth"].append(("keys-incomplete", "", here))
            if s.get("sso_session") or s.get("sso_start_url"):
                p["auth"].append(("sso", safe(s.get("sso_session", ""), 64), here))
            if s.get("role_arn"):
                via = s.get("source_profile") or s.get("credential_source") or ""
                p["auth"].append(("role", f"{_role(s['role_arn'])}" + (f", via {safe(via, 64)}" if via else ""), here))
            if s.get("credential_process"):
                p["auth"].append(("process", program_name(s["credential_process"]), here))
            if s.get("web_identity_token_file"):
                p["auth"].append(("web-identity", "", here))
    active = ctx.get("AWS_PROFILE") or ctx.get("AWS_DEFAULT_PROFILE")
    for name in sorted(profiles):
        p = profiles[name]
        item = f"profile {safe(name, 64)}" + (" (active)" if name == active or (not active and name == "default")
                                                else "")
        if not p["auth"]:
            sec.add("info", item, "settings only, no credentials", where=", ".join(dict.fromkeys(p["where"])))
        for kind, extra, where in dict.fromkeys(p["auth"]):
            if kind == "keys":
                sec.add("high", item, "long-term access keys", where=where,
                        reach=f"AWS: long-term access keys for profile {safe(name, 64)} ({where})")
            elif kind == "keys-temporary":
                sec.add("medium", item, "temporary access keys with a session token", where=where,
                        reach=f"AWS: temporary access keys for profile {safe(name, 64)}, until they expire")
            elif kind == "keys-incomplete":
                sec.add("info", item, "access key ID without a secret key", where=where)
            elif kind == "sso":
                sec.add("medium", item, "IAM Identity Center (SSO)" + (f", session {extra}" if extra else ""),
                        where=where, reach=f"AWS: profile {safe(name, 64)} signs in through IAM Identity Center; "
                                           "usable while a cached SSO session is valid")
            elif kind == "role":
                sec.add("medium", item, f"assumes {extra}", where=where,
                        reach=f"AWS: profile {safe(name, 64)} assumes {extra}")
            elif kind == "process":
                sec.add("medium", item, f"credential_process runs {extra or 'a program'}", where=where,
                        reach=f"AWS: profile {safe(name, 64)} gets credentials from {extra or 'a program'}")
            elif kind == "web-identity":
                sec.add("medium", item, "web identity token file", where=where)
    total, valid, latest = 0, 0, None
    for sub in ("sso/cache", "cli/cache"):
        d = aws / sub
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        for n in names:
            if not n.endswith(".json"):
                continue
            total += 1
            text, _ = read_file(d / n, 256 * 1024)
            try:
                data = load_json(text) if text else None
            except ValueError:
                data = None
            if not isinstance(data, dict):
                continue
            creds = data.get("Credentials") if isinstance(data.get("Credentials"), dict) else {}
            exp = _iso_time(data.get("expiresAt") or creds.get("Expiration"))
            if exp and exp > ctx.now:
                valid += 1
                latest = max(latest or exp, exp)
    if total:
        detail = f"{_count(total, 'cached session file')}, {valid} not yet expired"
        if latest:
            detail += f" (latest until {latest.astimezone(dt.timezone.utc):%Y-%m-%d %H:%M} UTC)"
        sec.add("medium" if valid else "info", "SSO and role cache", detail + "; contents not read",
                where=ctx.show(aws), reach=f"AWS: {_count(valid, 'cached SSO or role session')} still valid" if valid else "")
    return sec


# ---------------------------------------------------------------- Google Cloud
ADC_TYPES = {"authorized_user", "service_account", "external_account", "impersonated_service_account",
             "external_account_authorized_user", "gdch_service_account"}


def gcloud_dir(ctx: Context) -> Path:
    # gcloud: CLOUDSDK_CONFIG, else %APPDATA%\gcloud on Windows, else ~/.config/gcloud (it ignores XDG_CONFIG_HOME)
    if ctx.get("CLOUDSDK_CONFIG"):
        return Path(ctx.env["CLOUDSDK_CONFIG"])
    return ctx.appdata() / "gcloud" if ctx.windows else Path(ctx.home) / ".config" / "gcloud"


def _credential_json_type(text: str) -> str:
    try:
        data = load_json(text)
    except ValueError:
        return "unparseable"
    if not isinstance(data, dict):
        return "unparseable"
    t = data.get("type")
    return t if t in ADC_TYPES else "unrecognised type"


def scan_gcloud(ctx: Context) -> Section:
    sec = Section("gcloud", "Google Cloud (gcloud)")
    sec.store_note = ("gcloud auth login keeps its credentials in this configuration directory (Google Cloud docs), "
                      "not in macOS Keychain or Windows Credential Manager; the login databases are reported by "
                      "presence, not opened.")
    d = gcloud_dir(ctx)
    sec.paths.append(ctx.show(d))
    if exists(d):
        sec.found = True
        name = "default"
        text, _ = read_file(d / "active_config", 4096)
        if text and re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", text.strip()):
            name = text.strip()
        cfg = d / "configurations" / f"config_{name}"
        account = project = ""
        text, why = read_file(cfg)
        if text is not None:
            try:
                cp = ini(text)
                if cp.has_section("core"):
                    account = cp["core"].get("account", "").strip()
                    project = cp["core"].get("project", "").strip()
            except (configparser.Error, ValueError) as e:
                sec.error(ctx.show(cfg), f"could not parse ({type(e).__name__})")
        elif why != "missing":
            sec.error(ctx.show(cfg), why)
        logins = [n for n in ("credentials.db", "access_tokens.db") if is_regular(d / n)]
        legacy = d / "legacy_credentials"
        try:
            legacy_n = sum(1 for _ in os.scandir(legacy)) if legacy.is_dir() else 0
        except OSError:
            legacy_n = 0
        who = f"account {safe(account, 80)}" if account else "no active account"
        detail = f"configuration {safe(name, 64)}: {who}" + (f", project {safe(project, 64)}" if project else "")
        if logins or legacy_n:
            stored = ", ".join(logins + ([f"legacy_credentials ({legacy_n})"] if legacy_n else []))
            sec.add("medium", "gcloud login", f"{detail}; stored logins: {stored}", where=ctx.show(d),
                    reach=f"Google Cloud: gcloud is signed in ({who})" if account else
                    "Google Cloud: gcloud has stored logins")
        else:
            sec.add("info", "gcloud configuration", detail + "; no stored logins", where=ctx.show(d))
        adc = d / "application_default_credentials.json"
        text, why = read_file(adc)
        if text is not None:
            kind = _credential_json_type(text)
            sev = "high" if kind in ("authorized_user", "service_account") else "medium"
            sec.add(sev, "application-default credentials", f"type {kind}", where=ctx.show(adc),
                    reach=f"Google Cloud: application-default credentials ({kind}), used by every Google client "
                          "library on this machine")
        elif why != "missing":
            sec.error(ctx.show(adc), why)
    gac = ctx.get("GOOGLE_APPLICATION_CREDENTIALS")
    if gac:
        p = Path(os.path.expanduser(gac.strip()))
        text, why = read_file(p)
        sec.found = True
        if text is not None:
            kind = _credential_json_type(text)
            sec.add("high" if kind in ("authorized_user", "service_account") else "medium",
                    "GOOGLE_APPLICATION_CREDENTIALS", f"points to a credential file, type {kind}",
                    where=ctx.show(p),
                    reach=f"Google Cloud: GOOGLE_APPLICATION_CREDENTIALS points to a {kind} credential file")
        else:
            sec.add("info", "GOOGLE_APPLICATION_CREDENTIALS", f"set, but the file is {why}")
    return sec


# ---------------------------------------------------------------- Azure
def scan_azure(ctx: Context) -> Section:
    sec = Section("azure", "Azure CLI")
    sec.store_note = ("The Azure CLI saves its token cache and service principal entries as encrypted files on "
                      "Windows and as plaintext files on Linux and macOS (Microsoft docs); this tool reports which "
                      "files exist, not what they hold.")
    d = ctx.path_env("AZURE_CONFIG_DIR") or Path(ctx.home) / ".azure"
    sec.paths.append(ctx.show(d))
    if not exists(d):
        return sec
    prof = d / "azureProfile.json"
    text, why = read_file(prof)
    if text is not None:
        try:
            data = load_json(text)
        except ValueError:
            data = None
        if not isinstance(data, dict):
            sec.error(ctx.show(prof), "not a JSON object")
        else:
            raw = data.get("subscriptions")
            subs = [s for s in (raw if isinstance(raw, list) else []) if isinstance(s, dict)]
            users = {}
            for s in subs:
                u = s.get("user") if isinstance(s.get("user"), dict) else {}
                users[str(u.get("name"))] = str(u.get("type") or "unknown")
            kinds = sorted(set(users.values()))
            detail = (f"{_count(len(subs), 'subscription')}, {_count(len(users), 'account')}"
                      + (f" ({', '.join(safe(k, 30) for k in kinds)})" if kinds else ""))
            sec.add("medium" if subs else "info", "profile", detail, where=ctx.show(prof),
                    reach=f"Azure: the CLI is signed in to {_count(len(subs), 'subscription')}" if subs else "")
    elif why != "missing":
        sec.error(ctx.show(prof), why)
    for name, sev, what in (
            ("msal_token_cache.json", "medium", "token cache, plaintext"),
            ("msal_token_cache.bin", "medium", "token cache, encrypted"),
            ("service_principal_entries.json", "high", "service principal entries, plaintext"),
            ("service_principal_entries.bin", "medium", "service principal entries, encrypted"),
            ("accessTokens.json", "high", "tokens written by Azure CLI before 2.30.0, plaintext")):
        if is_regular(d / name):
            sec.add(sev, name, what, where=ctx.show(d / name),
                    reach=f"Azure: {what} in {ctx.show(d / name)}")
    sec.found = True
    return sec


# ---------------------------------------------------------------- a small YAML reader (kubeconfig, gh hosts.yml)
class YamlError(ValueError):
    pass


def _strip_comment(s: str) -> str:
    quote, i = None, 0
    while i < len(s):
        c = s[i]
        if quote:
            if quote == '"' and c == "\\":
                i += 2
                continue
            if c == quote:
                if quote == "'" and s[i + 1:i + 2] == "'":
                    i += 2
                    continue
                quote = None
        elif c in "'\"" and (not s[:i].strip() or s[:i].rstrip()[-1] in ":-[{,"):
            quote = c
        elif c == "#" and (i == 0 or s[i - 1] in " \t"):
            return s[:i]
        i += 1
    return s


def _quoted_end(s: str, i: int) -> int:
    """Index just past the quoted scalar that starts at s[i]."""
    q, j = s[i], i + 1
    while j < len(s):
        if q == '"' and s[j] == "\\":
            j += 2
            continue
        if s[j] == q:
            if q == "'" and s[j + 1:j + 2] == "'":
                j += 2
                continue
            return j + 1
        j += 1
    raise YamlError("unterminated quoted string")


def _unquote(s: str):
    if s[0] == '"':
        try:
            return json.loads(s)
        except ValueError:
            return s[1:-1]
    return s[1:-1].replace("''", "'")


def _scalar(v: str):
    v = v.strip()
    while v[:1] in ("!", "&"):  # tags and anchors mean nothing to the files read here
        parts = v.split(None, 1)
        v = parts[1] if len(parts) > 1 else ""
    if v in ("", "~", "null", "Null", "NULL"):
        return None
    if v[0] in "[{":
        value, end = _flow(v, 0)
        if v[end:].strip():
            raise YamlError("text after a flow collection")
        return value
    if v[0] in "'\"":
        end = _quoted_end(v, 0)
        if v[end:].strip():
            raise YamlError("text after a quoted string")
        return _unquote(v[:end])
    if v in ("true", "True", "TRUE"):
        return True
    if v in ("false", "False", "FALSE"):
        return False
    return v


def _flow(s: str, i: int):
    """A flow collection ([a, b] or {k: v}) starting at s[i] -> (value, index after it)."""
    opener = s[i]
    closer = "]" if opener == "[" else "}"
    out = [] if opener == "[" else {}
    i += 1
    while True:
        while i < len(s) and s[i] in " \t":
            i += 1
        if i >= len(s):
            raise YamlError("unterminated flow collection")
        if s[i] == closer:
            return out, i + 1
        if s[i] in "[{":
            item, i = _flow(s, i)
        elif s[i] in "'\"":
            end = _quoted_end(s, i)
            item, i = _unquote(s[i:end]), end
        else:
            m = re.compile(r"[^,\]\}]*?(?=\s*(?:,|\]|\}|:\s|:$))" if opener == "{" else r"[^,\]\}]*").match(s, i)
            if m is None:
                raise YamlError("unterminated flow mapping")
            item, i = _scalar(m.group(0)), m.end()
        while i < len(s) and s[i] in " \t":
            i += 1
        if opener == "{":
            if i < len(s) and s[i] == ":":
                i += 1
                while i < len(s) and s[i] in " \t":
                    i += 1
                if i < len(s) and s[i] in "[{":
                    val, i = _flow(s, i)
                elif i < len(s) and s[i] in "'\"":
                    end = _quoted_end(s, i)
                    val, i = _unquote(s[i:end]), end
                else:
                    m = re.compile(r"[^,\}]*").match(s, i)
                    val, i = _scalar(m.group(0)), m.end()
            else:
                val = None
            out[str(item)] = val
        else:
            out.append(item)
        while i < len(s) and s[i] in " \t":
            i += 1
        if i < len(s) and s[i] == ",":
            i += 1
        elif i < len(s) and s[i] != closer:
            raise YamlError("expected a comma")


_KEY = re.compile(r"([^\s#\[\]{},'\"][^#]*?)\s*:(?:[ \t]+|$)")


def _entry(text: str):
    """`key: value` -> (key, value text); None when the line is not a mapping entry."""
    if text == "-" or text.startswith(("- ", "? ")):
        return None
    if text[0] in "'\"":
        end = _quoted_end(text, 0)
        rest = text[end:].lstrip(" ")
        if not rest.startswith(":") or rest[1:2] not in ("", " ", "\t"):
            return None
        return str(_unquote(text[:end])), rest[1:].strip()
    m = _KEY.match(text)
    return (m.group(1), text[m.end():].strip()) if m else None


def yaml_load(text: str):
    """The block-style YAML that kubectl and gh write: mappings, sequences, scalars, flow collections.
    Anything else raises YamlError."""
    lines = []
    for n, raw in enumerate(text.replace("\r\n", "\n").replace("\r", "\n").split("\n"), 1):
        lead = raw[:len(raw) - len(raw.lstrip(" \t"))]
        body = _strip_comment(raw).rstrip()
        if not body.strip():
            continue
        if "\t" in lead:
            raise YamlError(f"tab indentation on line {n}")
        if body.startswith("%"):
            continue
        if body.strip() in ("---", "..."):
            if lines:
                break  # a second document: only the first one counts
            continue
        lines.append([len(body) - len(body.lstrip(" ")), body.strip(), n])
    if not lines:
        return None
    value, i = _block(lines, 0)
    if i != len(lines):
        raise YamlError(f"unexpected indentation on line {lines[i][2]}")
    return value


def _is_item(text: str) -> bool:
    return text == "-" or text.startswith("- ")


def _block(lines, i):
    return _seq(lines, i, lines[i][0]) if _is_item(lines[i][1]) else _map(lines, i, lines[i][0])


def _seq(lines, i, indent):
    out = []
    while i < len(lines) and lines[i][0] == indent and _is_item(lines[i][1]):
        _, text, n = lines[i]
        rest = text[1:].lstrip(" ")
        if not rest:
            if i + 1 < len(lines) and lines[i + 1][0] > indent:
                value, i = _block(lines, i + 1)
            else:
                value, i = None, i + 1
        elif _is_item(rest) or _entry(rest):
            lines[i] = [indent + len(text) - len(rest), rest, n]  # `- key: v` opens a mapping at the key's column
            value, i = _block(lines, i)
        else:
            value, i = _scalar(rest), i + 1
        out.append(value)
    return out, i


def _map(lines, i, indent):
    out: dict = {}
    while i < len(lines) and lines[i][0] == indent and not _is_item(lines[i][1]):
        _, text, n = lines[i]
        e = _entry(text)
        if e is None:
            raise YamlError(f"expected `key: value` on line {n}")
        key, value = e
        i += 1
        if value == "":
            if i < len(lines) and lines[i][0] > indent:
                out[key], i = _block(lines, i)
            elif i < len(lines) and lines[i][0] == indent and _is_item(lines[i][1]):
                out[key], i = _seq(lines, i, indent)  # kubectl writes `users:` then `- name:` at the same column
            else:
                out[key] = None
        elif re.fullmatch(r"[|>][0-9+-]*", value):
            parts = []
            while i < len(lines) and lines[i][0] > indent:
                parts.append(lines[i][1])
                i += 1
            out[key] = "\n".join(parts)
        else:
            parts = [value]
            while i < len(lines) and lines[i][0] > indent:  # a plain scalar folded over several lines
                if _entry(lines[i][1]) or _is_item(lines[i][1]):
                    raise YamlError(f"a mapping inside a scalar on line {lines[i][2]}")
                parts.append(lines[i][1])
                i += 1
            out[key] = _scalar(" ".join(parts))
    return out, i


# ---------------------------------------------------------------- Kubernetes
def kube_user_auth(user) -> tuple[str, str]:
    """(severity, what) for a kubeconfig user entry, without a single value."""
    u = user if isinstance(user, dict) else {}
    found = []
    if u.get("token"):
        found.append(("high", "stored token"))
    if u.get("tokenFile"):
        found.append(("high", "token file"))
    if u.get("client-key-data"):
        found.append(("high", "client certificate with inline key"))
    elif u.get("client-key"):
        found.append(("high", "client certificate with key file"))
    if u.get("password"):
        found.append(("high", "basic-auth password"))
    ap = u.get("auth-provider") if isinstance(u.get("auth-provider"), dict) else None
    if ap:
        cfg = ap.get("config") if isinstance(ap.get("config"), dict) else {}
        stored = [k for k in ("access-token", "refresh-token", "id-token", "client-secret") if cfg.get(k)]
        name = program_name(ap.get("name")).replace("a program", "?")
        found.append(("high" if stored else "medium",
                      f"auth-provider {name}" + (f" with stored {', '.join(stored)}" if stored else "")))
    ex = u.get("exec") if isinstance(u.get("exec"), dict) else None
    if ex:
        found.append(("medium", f"exec plugin {program_name(ex.get('command'))} (credentials from that program at "
                                "run time)"))
    if not found:
        return "info", "no credentials"
    sev = "high" if any(s == "high" for s, _ in found) else "medium"
    return sev, ", ".join(w for _, w in found)


def _named(items, key):
    out = {}
    for it in items if isinstance(items, list) else []:
        if isinstance(it, dict) and isinstance(it.get("name"), str):
            out[it["name"]] = it.get(key) if isinstance(it.get(key), dict) else {}
    return out


def scan_kube(ctx: Context) -> Section:
    sec = Section("kube", "Kubernetes (kubeconfig)")
    sec.store_note = ("Exec plugins and auth providers get credentials from another program at run time "
                      "(a cloud CLI, kubelogin), which may use macOS Keychain or Windows Credential Manager; "
                      "what they return is not visible here.")
    sep = ";" if ctx.windows else ":"
    if ctx.get("KUBECONFIG"):
        paths = [Path(os.path.expanduser(p)) for p in ctx.env["KUBECONFIG"].split(sep) if p.strip()]
        sec.notes.append(f"KUBECONFIG names {_count(len(paths), 'file')}.")
    else:
        paths = [Path(ctx.home) / ".kube" / "config"]
    for path in paths:
        sec.paths.append(ctx.show(path))
        text, why = read_file(path)
        if text is None:
            if why != "missing":
                sec.error(ctx.show(path), why)
            continue
        sec.found = True
        try:
            data = load_json(text) if text.lstrip().startswith("{") else yaml_load(text)
        except (ValueError, RecursionError) as e:
            sec.error(ctx.show(path), f"could not parse ({clean(e, 80)})")
            continue
        if data is None:
            sec.notes.append(f"{ctx.show(path)} is empty.")
            continue
        if not isinstance(data, dict):
            sec.error(ctx.show(path), "not a kubeconfig (top level is not a mapping)")
            continue
        clusters, users = _named(data.get("clusters"), "cluster"), _named(data.get("users"), "user")
        contexts = _named(data.get("contexts"), "context")
        current = data.get("current-context") if isinstance(data.get("current-context"), str) else ""
        used = set()
        where = ctx.show(path)
        for name, c in contexts.items():
            user, cluster = str(c.get("user") or ""), str(c.get("cluster") or "")
            used.add(user)
            sev, how = kube_user_auth(users.get(user))
            cl = clusters.get(cluster, {})
            server = host_of(str(cl.get("server"))) if cl.get("server") else "?"
            insecure = ", TLS verification off" if cl.get("insecure-skip-tls-verify") is True else ""
            item = f"context {safe(name, 60)}" + (" (current)" if name == current else "")
            detail = f"cluster {safe(cluster, 60)} ({server}{insecure}), user {safe(user, 60)}: {how}"
            reach = (f"Kubernetes: context {safe(name, 60)} reaches cluster {safe(cluster, 60)} ({server}) as "
                     f"{safe(user, 60)} with {how}") if sev != "info" else ""
            sec.add(sev, item, detail, reach=reach, where=where)
        for name, u in users.items():
            if name not in used:
                sev, how = kube_user_auth(u)
                sec.add(sev, f"user {safe(name, 60)}", f"{how}; no context uses it", where=where)
    return sec


# ---------------------------------------------------------------- Docker
DOCKER_STORES = {"osxkeychain": "macOS Keychain", "wincred": "Windows Credential Manager",
                 "pass": "pass", "secretservice": "Secret Service", "desktop": "Docker Desktop's credential helper"}


def _registry(key: str) -> str:
    name = host_of(key) if "://" in key else key.split("/")[0]
    return name if re.fullmatch(r"[A-Za-z0-9.\-_]{1,253}(?::[0-9]{1,5})?", name) else safe(name, 60)


def _helper(name) -> str:
    n = program_name(name)
    return (f"docker-credential-{n}" if n != "a program" else "a credential helper") + \
        (f" ({DOCKER_STORES[n]})" if n in DOCKER_STORES else "")


def scan_docker(ctx: Context) -> Section:
    sec = Section("docker", "Docker registries")
    d = ctx.path_env("DOCKER_CONFIG") or Path(ctx.home) / ".docker"
    f = d / "config.json"
    sec.paths.append(ctx.show(f))
    text, why = read_file(f)
    if text is None:
        if why != "missing":
            sec.error(ctx.show(f), why)
        return sec
    sec.found = True
    try:
        data = load_json(text)
    except ValueError:
        sec.error(ctx.show(f), "could not parse (not JSON)")
        return sec
    if not isinstance(data, dict):
        sec.error(ctx.show(f), "not a JSON object")
        return sec
    auths = data.get("auths") if isinstance(data.get("auths"), dict) else {}
    helpers = data.get("credHelpers") if isinstance(data.get("credHelpers"), dict) else {}
    store = data.get("credsStore") if isinstance(data.get("credsStore"), str) and data.get("credsStore") else None
    where = ctx.show(f)
    for key in sorted(set(auths) | set(helpers)):
        reg = _registry(str(key))
        entry = auths.get(key) if isinstance(auths.get(key), dict) else {}
        inline = [k for k in ("auth", "password", "identitytoken", "registrytoken") if entry.get(k)]
        if inline:
            sec.add("high", reg, "credentials stored in config.json (" + ", ".join(inline) + ")", where=where,
                    reach=f"Docker: push and pull as you on {reg}; credentials stored in {where}")
        elif key in helpers:
            sec.add("medium", reg, f"credentials via {_helper(helpers[key])}", where=where,
                    reach=f"Docker: {reg} through {_helper(helpers[key])}")
        elif store:
            sec.add("medium", reg, f"credentials via {_helper(store)}", where=where,
                    reach=f"Docker: {reg} through {_helper(store)}")
        else:
            sec.add("info", reg, "listed, no stored credentials", where=where)
    if store:
        sec.store_note = (f"credsStore is {_helper(store)}: registry passwords live there, not in config.json. "
                          "This tool sees the registries config.json lists, not what the store holds.")
    else:
        sec.store_note = ("No credsStore is set, so docker login writes credentials into config.json in base64 "
                          "(Docker docs); a credential helper named in credHelpers keeps its own.")
    return sec


# ---------------------------------------------------------------- npm
def parse_npmrc(text: str) -> list:
    out = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line[0] in "#;":
            continue
        k, sep, v = line.partition("=")
        if sep:
            out.append((k.strip(), v.strip().strip("\"'")))
    return out


def npm_auth(pairs) -> dict:
    """registry -> [(what, env var or '')] for every auth key, without a value."""
    found: dict = {}
    for key, value in pairs:
        m = re.fullmatch(r"(//.*?/?):(_authToken|_auth|_password|username|certfile|keyfile)", key)
        reg, what = (m.group(1), m.group(2)) if m else ("default registry", key)
        if what not in ("_authToken", "_auth", "_password", "username", "certfile", "keyfile"):
            continue
        ref = re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", value)
        found.setdefault(reg, []).append((what, ref.group(1) if ref else "", bool(value)))
    return found


def _npm_target(reg: str) -> str:
    return reg if reg == "default registry" else safe(mask_url("https:" + reg).split("://", 1)[-1].rstrip("/"), 100)


def scan_npm(ctx: Context) -> Section:
    sec = Section("npm", "npm")
    sec.store_note = ("npm reads tokens from .npmrc files and from the environment variables they name; "
                      "project .npmrc files are covered under Project.")
    p = ctx.path_env("NPM_CONFIG_USERCONFIG", "npm_config_userconfig") or Path(ctx.home) / ".npmrc"
    sec.paths.append(ctx.show(p))
    text, why = read_file(p)
    if text is None:
        if why != "missing":
            sec.error(ctx.show(p), why)
        return sec
    sec.found = True
    add_npm_findings(sec, parse_npmrc(text), ctx.show(p), "npm")
    if not sec.findings:
        sec.add("info", ".npmrc", "no registry credentials", where=ctx.show(p))
    return sec


def add_npm_findings(sec: Section, pairs, where: str, prefix: str) -> None:
    for reg, entries in npm_auth(pairs).items():
        target = _npm_target(reg)
        literal = [w for w, ref, has in entries if w in ("_authToken", "_auth", "_password") and has and not ref]
        refs = [ref for w, ref, has in entries if ref]
        if literal:
            sec.add("high", target, f"{', '.join(literal)} stored in the file", where=where,
                    reach=f"{prefix}: publish and install as you on {target}; token stored in {where}")
        elif refs:
            sec.add("info", target, "token taken from $" + ", $".join(safe(r, 40) for r in refs), where=where)
        else:
            sec.add("info", target, ", ".join(f"{w} {'set' if has else 'empty'}" for w, _, has in entries),
                    where=where)


# ---------------------------------------------------------------- PyPI (.pypirc)
def scan_pypirc(ctx: Context) -> Section:
    sec = Section("pypi", "PyPI uploads (.pypirc)")
    sec.store_note = ("twine can also take passwords from the system keyring (twine docs: keyring support), "
                      "which is macOS Keychain or Windows Credential Manager on those systems; not visible here.")
    p = Path(ctx.home) / ".pypirc"
    sec.paths.append(ctx.show(p))
    text, why = read_file(p)
    if text is None:
        if why != "missing":
            sec.error(ctx.show(p), why)
        return sec
    sec.found = True
    try:
        cp = ini(text)
    except (configparser.Error, ValueError) as e:
        sec.error(ctx.show(p), f"could not parse ({type(e).__name__})")
        return sec
    for name in cp.sections():
        if name == "distutils":
            continue
        s = cp[name]
        repo = s.get("repository", "").strip()
        host = host_of(repo) if repo else ("upload.pypi.org" if name == "pypi" else
                                           "test.pypi.org" if name == "testpypi" else "?")
        token = s.get("username", "").strip() == "__token__"
        if s.get("password", "").strip():
            sec.add("high", safe(name, 60), f"{host}: {'API token' if token else 'password'} stored in the file",
                    where=ctx.show(p), reach=f"PyPI: upload as you to {host} ({name} in {ctx.show(p)})")
        else:
            sec.add("info", safe(name, 60), f"{host}: no password stored", where=ctx.show(p))
    return sec


# ---------------------------------------------------------------- netrc
def parse_netrc(text: str) -> list:
    """[(machine or 'default', has login, has password, password)]; the password stays in memory only."""
    tokens, lines, i = [], text.splitlines(), 0
    while i < len(lines):
        words = lines[i].split()
        if words and words[0] == "macdef":  # a macro runs until the next empty line
            i += 1
            while i < len(lines) and lines[i].strip():
                i += 1
            continue
        if words and words[0].startswith("#"):
            i += 1
            continue
        tokens.extend(words)
        i += 1
    entries, cur, j = [], None, 0
    while j < len(tokens):
        t = tokens[j]
        if t in ("machine", "default"):
            if cur:
                entries.append(cur)
            name = tokens[j + 1] if t == "machine" and j + 1 < len(tokens) else "default"
            cur = [name, False, False, ""]
            j += 2 if t == "machine" else 1
            continue
        if cur and t in ("login", "password", "account") and j + 1 < len(tokens):
            if t == "login":
                cur[1] = True
            elif t == "password":
                cur[2], cur[3] = True, tokens[j + 1].strip("\"")
            j += 2
            continue
        j += 1
    if cur:
        entries.append(cur)
    return entries


def scan_netrc(ctx: Context) -> Section:
    sec = Section("netrc", "netrc")
    sec.store_note = "A plain file read by curl, git and others; credential helpers are covered under Git."
    candidates = ([ctx.path_env("NETRC")] if ctx.get("NETRC") else []) + \
        [Path(ctx.home) / ".netrc", Path(ctx.home) / "_netrc"]
    for p in dict.fromkeys(candidates):
        sec.paths.append(ctx.show(p))
        text, why = read_file(p)
        if text is None:
            if why != "missing":
                sec.error(ctx.show(p), why)
            continue
        sec.found = True
        entries = parse_netrc(text)
        for machine, login, has_pw, pw in entries:
            host = host_of(machine) if machine != "default" else "default (any other host)"
            if has_pw:
                sec.add("high", host, "login and password stored" if login else "password stored",
                        where=ctx.show(p), reach=f"netrc: a password for {host} in {ctx.show(p)}")
                if host in ("github.com", "api.github.com"):
                    ctx.add_token(pw, ctx.show(p), strict_github=False)
            else:
                sec.add("info", host, "no password" + (", login only" if login else ""), where=ctx.show(p))
        if not entries:
            sec.notes.append(f"{ctx.show(p)} has no machine entries.")
    return sec


# ---------------------------------------------------------------- git
GIT_HELPERS = {"store": "the plaintext file listed here", "cache": "memory, for a timeout",
               "osxkeychain": "macOS Keychain", "wincred": "Windows Credential Manager",
               "manager": "Git Credential Manager (Windows Credential Manager or macOS Keychain by default)",
               "manager-core": "Git Credential Manager (Windows Credential Manager or macOS Keychain by default)",
               "libsecret": "Secret Service", "gnome-keyring": "GNOME Keyring"}


def git_helpers(text: str) -> list:
    """credential.helper values in a git config file, first word only (the helper, not its options)."""
    out, in_cred = [], False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line[0] in "#;":
            continue
        m = re.match(r"\[\s*([A-Za-z0-9.-]+)(?:\s+\"[^\"]*\")?\s*\]", line)
        if m:
            in_cred = m.group(1).lower() == "credential"
            line = line[m.end():].strip()
            if not line:
                continue
        k, sep, v = line.partition("=")
        if in_cred and sep and k.strip().lower() == "helper":
            v = v.strip().strip("\"")
            if v:
                out.append("a shell command" if v.startswith("!") else
                           program_name(v).replace("git-credential-", "", 1))
    return out


def scan_git(ctx: Context) -> Section:
    sec = Section("git", "Git credentials")
    files = [Path(ctx.home) / ".git-credentials", ctx.config_home() / "git" / "credentials"]
    for p in files:
        sec.paths.append(ctx.show(p))
        text, why = read_file(p)
        if text is None:
            if why != "missing":
                sec.error(ctx.show(p), why)
            continue
        sec.found = True
        hosts: dict = {}
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                u = urllib.parse.urlsplit(line)
                pw, host = u.password, host_of(line)
            except ValueError:
                sec.notes.append(f"{ctx.show(p)}: a line that is not a URL was skipped.")
                continue
            h = hosts.setdefault(host, [0, 0])
            h[0] += 1
            if pw:
                h[1] += 1
                if host in ("github.com", "api.github.com"):
                    ctx.add_token(urllib.parse.unquote(pw), ctx.show(p), strict_github=False)
        for host, (n, with_pw) in sorted(hosts.items()):
            if with_pw:
                sec.add("high", host, f"{_count(with_pw, 'stored credential')}", where=ctx.show(p),
                        reach=f"Git: push and pull as you on {host}; credentials stored in {ctx.show(p)}")
            else:
                sec.add("info", host, f"{_count(n, 'entry', 'entries')} without a password", where=ctx.show(p))
    helpers = []
    for p in (Path(ctx.home) / ".gitconfig", ctx.config_home() / "git" / "config"):
        text, _ = read_file(p)
        if text:
            helpers += git_helpers(text)
    for h in dict.fromkeys(helpers):
        where = GIT_HELPERS.get(h, "a program this tool does not know")
        sev = "info" if h == "store" else "medium"
        sec.add(sev, f"credential.helper {safe(h, 40)}", f"credentials kept in {where}",
                reach=f"Git: credentials from credential.helper {safe(h, 40)} ({where}), used without a prompt"
                if sev == "medium" else "")
    if helpers:
        sec.store_note = ("What a credential helper holds is not visible here; git hands it out to any git "
                          "command without asking.")
    return sec


# ---------------------------------------------------------------- gh
def gh_dir(ctx: Context) -> Path:
    # gh: GH_CONFIG_DIR, else $XDG_CONFIG_HOME/gh, else %AppData%\GitHub CLI on Windows, else ~/.config/gh
    if ctx.get("GH_CONFIG_DIR"):
        return Path(ctx.env["GH_CONFIG_DIR"])
    if ctx.get("XDG_CONFIG_HOME"):
        return Path(ctx.env["XDG_CONFIG_HOME"]) / "gh"
    if ctx.windows:
        return ctx.appdata() / "GitHub CLI"
    return Path(ctx.home) / ".config" / "gh"


def scan_gh(ctx: Context) -> Section:
    sec = Section("gh", "GitHub CLI (gh)")
    sec.store_note = ("gh keeps its token in the system credential store (macOS Keychain, Windows Credential "
                      "Manager, Secret Service) unless it had to fall back to a plain text file (gh auth login "
                      "manual); a token in the store is not visible here, and gh uses it without a prompt.")
    p = gh_dir(ctx) / "hosts.yml"
    sec.paths.append(ctx.show(p))
    text, why = read_file(p)
    if text is None:
        if why != "missing":
            sec.error(ctx.show(p), why)
        return sec
    sec.found = True
    try:
        data = yaml_load(text)
    except (ValueError, RecursionError) as e:
        sec.error(ctx.show(p), f"could not parse ({clean(e, 80)})")
        return sec
    if data is None:
        sec.notes.append(f"{ctx.show(p)} is empty.")
        return sec
    if not isinstance(data, dict):
        sec.error(ctx.show(p), "not a mapping of hosts")
        return sec
    for host, entry in data.items():
        entry = entry if isinstance(entry, dict) else {}
        h = host_of(str(host))
        user = entry.get("user") if isinstance(entry.get("user"), str) else ""
        tokens = [entry.get("oauth_token")] if isinstance(entry.get("oauth_token"), str) else []
        users = entry.get("users") if isinstance(entry.get("users"), dict) else {}
        for u in users.values():
            if isinstance(u, dict) and isinstance(u.get("oauth_token"), str):
                tokens.append(u["oauth_token"])
        tokens = [t for t in tokens if t.strip()]
        who = f"user {safe(user, 40)}" if user else "no user recorded"
        if tokens:
            sec.add("high", h, f"{who}; token stored in plain text in hosts.yml", where=ctx.show(p),
                    reach=f"GitHub CLI: signed in to {h} as {safe(user, 40) or 'an unknown user'}; "
                          f"token in plain text in {ctx.show(p)}")
            if h == "github.com":
                for t in tokens:
                    ctx.add_token(t, ctx.show(p), strict_github=False)
        else:
            sec.add("medium", h, f"{who}; token in the system credential store (not visible)", where=ctx.show(p),
                    reach=f"GitHub CLI: signed in to {h} as {safe(user, 40) or 'an unknown user'}; token in the "
                          "system credential store")
    return sec


# ---------------------------------------------------------------- SSH keys
PEM_BEGIN = re.compile(r"-{5}BEGIN ((?:[A-Z0-9]+ )*)PRIVATE KEY-{5}")
PEM_END = re.compile(r"-{5}END (?:[A-Z0-9]+ )*PRIVATE KEY-{5}")
OPENSSH_MAGIC = b"openssh-key-v1\x00"
PKCS8_OIDS = {bytes.fromhex("2a864886f70d010101"): "rsa", bytes.fromhex("2a8648ce3d0201"): "ecdsa",
              bytes.fromhex("2b6570"): "ed25519", bytes.fromhex("2b6571"): "ed448",
              bytes.fromhex("2a8648ce380401"): "dsa"}
SSH_SKIP = {"authorized_keys", "authorized_keys2", "known_hosts", "known_hosts.old", "config", "environment", "rc"}


def _b64(body: str) -> bytes:
    data = "".join(ln.strip() for ln in body.splitlines() if ln.strip() and ":" not in ln)
    try:
        return base64.b64decode(data + "=" * (-len(data) % 4))
    except (binascii.Error, ValueError):
        return b""


def _openssh(blob: bytes) -> dict:
    """Read the unencrypted header of an openssh-key-v1 blob: cipher name and public key type (PROTOCOL.key)."""
    info = {"format": "OpenSSH", "type": None, "passphrase": None}
    if not blob.startswith(OPENSSH_MAGIC):
        return info
    pos = len(OPENSSH_MAGIC)

    def string() -> bytes:
        nonlocal pos
        if pos + 4 > len(blob):
            raise ValueError
        n = int.from_bytes(blob[pos:pos + 4], "big")
        if n > len(blob) - pos - 4:
            raise ValueError
        s = blob[pos + 4:pos + 4 + n]
        pos += 4 + n
        return s

    try:
        cipher = string()
        string()  # kdf name
        string()  # kdf options
        if pos + 4 > len(blob):
            raise ValueError
        pos += 4  # number of keys
        pub = string()
        n = int.from_bytes(pub[:4], "big") if len(pub) >= 4 else 0
        ktype = pub[4:4 + n].decode("ascii", "replace")
    except ValueError:
        return info
    info["passphrase"] = cipher != b"none"
    info["type"] = ktype if re.fullmatch(r"[a-z0-9@.-]{1,64}", ktype) else None
    return info


def private_key_info(text: str) -> dict | None:
    """Format, key type and whether a passphrase protects it, from the header alone. None if not a private key."""
    t = text.lstrip("\ufeff")
    if t.startswith("PuTTY-User-Key-File-"):
        m = re.match(r"PuTTY-User-Key-File-\d+:\s*([A-Za-z0-9@.-]{1,64})", t)
        enc = re.search(r"^Encryption:\s*(\S+)", t, re.M)
        return {"format": "PuTTY", "type": m.group(1) if m else None,
                "passphrase": (enc.group(1) != "none") if enc else None}
    m = PEM_BEGIN.search(t)
    if not m:
        return None
    label = m.group(1).strip()
    end = PEM_END.search(t, m.end())
    body = t[m.end():end.start() if end else len(t)]
    if label == "OPENSSH":
        return _openssh(_b64(body))
    if label == "ENCRYPTED":
        return {"format": "PKCS#8", "type": None, "passphrase": True}
    if label in ("RSA", "DSA", "EC"):
        enc = re.search(r"^Proc-Type:\s*4,\s*ENCRYPTED", body, re.M) is not None
        return {"format": "PEM", "type": "ecdsa" if label == "EC" else label.lower(), "passphrase": enc}
    if label == "":
        der = _b64(body)[:64]
        kind = next((n for oid, n in PKCS8_OIDS.items() if b"\x06" + bytes([len(oid)]) + oid in der), None)
        return {"format": "PKCS#8", "type": kind, "passphrase": False}
    return {"format": "PEM", "type": None, "passphrase": None}


def key_finding(info: dict) -> tuple[str, str]:
    kind = info.get("type") or "unknown type"
    hardware = "-sk" in kind or kind.startswith("sk-")
    if info.get("passphrase") is True:
        return "info", f"{info['format']} {kind}, passphrase-protected"
    if info.get("passphrase") is None:
        return "medium", f"{info['format']} {kind}, passphrase status unknown"
    if hardware:
        return "medium", f"{info['format']} {kind}, no passphrase, needs its hardware security key"
    return "high", f"{info['format']} {kind}, no passphrase"


def scan_ssh(ctx: Context) -> Section:
    sec = Section("ssh", "SSH keys")
    sec.store_note = ("macOS can keep a key's passphrase in the Keychain (UseKeychain), and a running ssh-agent "
                      "holds unlocked keys; neither is queried, so a passphrase-protected key may still be usable.")
    d = Path(ctx.home) / ".ssh"
    sec.paths.append(ctx.show(d))
    try:
        names = sorted(os.listdir(d))
    except OSError:
        names = []
    for n in names:
        p = d / n
        if n in SSH_SKIP or n.endswith(".pub") or not is_regular(p):
            continue
        text, why = read_file(p, 64 * 1024)
        if text is None:
            if why.startswith("unreadable"):
                sec.error(ctx.show(p), why)
            continue
        info = private_key_info(text)
        if info is None:
            continue
        sev, detail = key_finding(info)
        sec.add(sev, ctx.show(p), detail, where=ctx.show(p), key_type=info.get("type"),
                passphrase=info.get("passphrase"),
                reach=f"SSH: {ctx.show(p)} ({info.get('type') or 'unknown type'}) has no passphrase; it opens "
                      "every host and repository that trusts its public key" if sev == "high" else "")
    cfg, _ = read_file(d / "config", 256 * 1024)
    if cfg and re.search(r"(?im)^\s*UseKeychain\s+yes", cfg):
        sec.add("medium", "UseKeychain yes", "~/.ssh/config lets macOS supply key passphrases from the Keychain",
                reach="SSH: passphrases come from the macOS Keychain (UseKeychain yes)")
    if ctx.get("SSH_AUTH_SOCK"):
        sec.add("medium", "ssh-agent", "SSH_AUTH_SOCK is set: keys loaded into the agent work without their "
                "passphrase (the agent was not queried)",
                reach="SSH: an ssh-agent is reachable through SSH_AUTH_SOCK; its loaded keys work without "
                      "a passphrase")
    return sec


# ---------------------------------------------------------------- Terraform
def scan_terraform(ctx: Context) -> Section:
    sec = Section("terraform", "Terraform")
    sec.store_note = ("A credentials_helper in the CLI configuration may keep tokens in macOS Keychain or Windows "
                      "Credential Manager; what it holds is not visible here.")
    dirs = [Path(ctx.home) / ".terraform.d"] + ([ctx.appdata() / "terraform.d"] if ctx.windows else [])
    for d in dict.fromkeys(dirs):
        p = d / "credentials.tfrc.json"
        sec.paths.append(ctx.show(p))
        text, why = read_file(p)
        if text is None:
            if why != "missing":
                sec.error(ctx.show(p), why)
            continue
        sec.found = True
        try:
            data = load_json(text)
        except ValueError:
            sec.error(ctx.show(p), "could not parse (not JSON)")
            continue
        creds = data.get("credentials") if isinstance(data, dict) else None
        if not isinstance(creds, dict):
            sec.error(ctx.show(p), "no credentials object")
            continue
        for host, entry in sorted(creds.items()):
            h = host_of(str(host))
            if isinstance(entry, dict) and entry.get("token"):
                sec.add("high", h, "API token stored in plain text", where=ctx.show(p),
                        reach=f"Terraform: an API token for {h} in {ctx.show(p)}")
            else:
                sec.add("info", h, "no token", where=ctx.show(p))
    rc = [ctx.path_env("TF_CLI_CONFIG_FILE")] if ctx.get("TF_CLI_CONFIG_FILE") else []
    rc += [ctx.appdata() / "terraform.rc"] if ctx.windows else [Path(ctx.home) / ".terraformrc"]
    for p in rc:
        text, _ = read_file(p)
        if not text:
            continue
        sec.paths.append(ctx.show(p))
        sec.found = True
        for m in re.finditer(r'(?m)^\s*credentials\s+"([^"]+)"\s*\{([^}]*)\}', text):
            h = host_of(m.group(1))
            if re.search(r"\btoken\s*=", m.group(2)):
                sec.add("high", h, "API token in a credentials block", where=ctx.show(p),
                        reach=f"Terraform: an API token for {h} in {ctx.show(p)}")
        m = re.search(r'(?m)^\s*credentials_helper\s+"([^"]+)"', text)
        if m:
            sec.add("medium", "credentials_helper", f"tokens from terraform-credentials-{program_name(m.group(1))}",
                    where=ctx.show(p))
    return sec


# ---------------------------------------------------------------- the project
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".tox", ".nox", ".mypy_cache",
             ".pytest_cache", ".ruff_cache", ".terraform", ".next", ".gradle", "site-packages", ".cache"}
ENV_FILE = re.compile(r"(?i)\.env(?:\..*)?|.+\.env|\.envrc")
TEMPLATE_ENV = re.compile(r"(?i).*\.(?:example|sample|template|dist|defaults?)$")
SECRET_FILE_PATTERNS = ["*.pem", "*.key", "*.p12", "*.pfx", "*.p8", "*.jks", "*.keystore", "*.ppk", "id_rsa",
                        "id_dsa", "id_ecdsa", "id_ed25519", "credentials.json", "client_secret*.json",
                        "service-account*.json", "*serviceaccount*.json", "*.tfstate", "*.tfstate.backup",
                        "*.tfvars", "secrets.json", "secrets.yml", "secrets.yaml", ".npmrc", ".pypirc", ".netrc",
                        "_netrc", ".git-credentials", ".htpasswd", "kubeconfig", "*.kubeconfig", ".vault-token",
                        "master.key", ".dockercfg"]
ENV_LINE = re.compile(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_.-]*)\s*=\s?(.*)$")
MAX_WALK = 50_000


def parse_env_file(text: str) -> list:
    """[(name, value)] from a .env file: KEY=value, export KEY=value, quoted and multi-line quoted values."""
    out, lines, i = [], text.splitlines(), 0
    while i < len(lines):
        m = ENV_LINE.match(lines[i])
        i += 1
        if not m or lines[i - 1].lstrip().startswith("#"):
            continue
        name, value = m.group(1), m.group(2).strip()
        if value[:1] in ("'", '"'):
            q, body = value[0], value[1:]
            while q not in body and i < len(lines):  # a quoted value may run over several lines
                body += "\n" + lines[i]
                i += 1
            value = body.split(q, 1)[0]
        else:
            value = re.split(r"\s+#", value, 1)[0].strip()
        out.append((name, value))
    return out


def git_status(root: Path, rels: list) -> tuple[dict, str]:
    """rel path -> 'tracked', 'ignored' or 'not ignored'; ({}, why) when git cannot say.
    core.fsmonitor is off so that a repository's own config cannot make git start a program."""
    if not rels:
        return {}, ""
    base = ["git", "-c", "core.fsmonitor=false", "-C", str(root)]
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0")

    def run(args, data=b""):
        return subprocess.run(base + args, input=data, capture_output=True, timeout=20, env=env)

    try:
        top = run(["rev-parse", "--is-inside-work-tree"])
        if top.returncode != 0 or top.stdout.strip() != b"true":
            first = decode_bytes(top.stderr).strip().splitlines()[:1]
            return {}, ("not a git repository" if not first or "not a git repository" in first[0]
                        else clean(first[0], 100))
        tracked = {os.fsdecode(p) for p in run(["ls-files", "-z", "--cached"]).stdout.split(b"\0") if p}
        chk = run(["check-ignore", "--stdin", "-z"], b"".join(os.fsencode(r) + b"\0" for r in rels))
        if chk.returncode not in (0, 1):
            return {}, "git check-ignore failed"
        ignored = {os.fsdecode(p) for p in chk.stdout.split(b"\0") if p}
    except FileNotFoundError:
        return {}, "git is not installed"
    except (OSError, subprocess.SubprocessError) as e:
        return {}, f"git failed ({type(e).__name__})"
    return {r: "tracked" if r in tracked else "ignored" if r in ignored else "not ignored" for r in rels}, ""


def scan_project(ctx: Context) -> Section:
    sec = Section("project", "Project files")
    root = Path(ctx.project) if ctx.project else None
    if root is None:
        return sec
    sec.paths.append(ctx.show(root))
    try:
        r, h = root.resolve(), Path(ctx.home).resolve()
    except (OSError, RuntimeError):
        r, h = root, Path(ctx.home)
    if r == h or r in h.parents:
        sec.notes.append(f"{ctx.show(root)} is your home directory or above it; pass --project with a project "
                         "directory to check one.")
        sec.found = True
        return sec
    found, seen = [], 0
    for dirpath, dirnames, filenames in os.walk(root, onerror=lambda e: None):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS
                             and not is_regular(Path(dirpath) / d / "pyvenv.cfg"))
        seen += len(filenames) + len(dirnames)
        for n in sorted(filenames):
            low = n.lower()
            if ENV_FILE.fullmatch(n) or any(fnmatch.fnmatchcase(low, pat) for pat in SECRET_FILE_PATTERNS):
                found.append(Path(dirpath) / n)
        if seen > MAX_WALK:
            sec.notes.append(f"Stopped after {MAX_WALK} entries; files further down were not checked.")
            break
    if not found:
        sec.notes.append("No .env or secret-named files.")
    rels = [PurePath(os.path.relpath(p, root)).as_posix() for p in found]
    status, why = git_status(root, rels)
    if found and why:
        sec.notes.append(f"Git status unknown: {why}.")
    for p, rel in zip(found, rels):
        st = status.get(rel, "")
        where = safe(rel, 160)
        git_note = {"tracked": "tracked by git", "not ignored": "not git-ignored", "ignored": "git-ignored"}.get(st, "")
        text, why_r = read_file(p)
        if text is None and why_r != "missing":
            sec.error(where, why_r)
            continue
        if ENV_FILE.fullmatch(p.name):
            pairs = parse_env_file(text or "")
            creds = [n for n, v in pairs if env_kind(n, v) == "secret" and v.strip() and not is_placeholder(v)]
            names = ", ".join(safe(n, 40) for n, _ in pairs[:12]) + (", ..." if len(pairs) > 12 else "")
            detail = (f"{_count(len(pairs), 'variable')}" + (f" ({names})" if names else "")
                      + f"; {len(creds)} credential-like with a value" + (f"; {git_note}" if git_note else ""))
            template = TEMPLATE_ENV.fullmatch(p.name) is not None
            sev = "high" if creds else "info"
            reach = (f"Project: {where} holds {_count(len(creds), 'credential-like value')} "
                     f"({', '.join(safe(c, 40) for c in creds[:6])})" + (f", {git_note}" if git_note else "")
                     if creds else "")
            sec.add(sev, where, detail + ("; a template file, but with values" if template and creds else ""),
                    reach=reach, git=st or None, variables=[safe(n, 60) for n, _ in pairs],
                    credential_variables=[safe(c, 60) for c in creds])
            continue
        key = private_key_info(text) if text else None
        if p.suffix.lower() in (".pem", ".key") and key is None:
            continue  # certificates and public keys share these extensions
        if key:
            sev, detail = key_finding(key)
            detail = "private key: " + detail
        elif fnmatch.fnmatchcase(p.name.lower(), ".npmrc") and text:
            creds = [r for r, e in npm_auth(parse_npmrc(text)).items()
                     if any(w in ("_authToken", "_auth", "_password") and has and not ref for w, ref, has in e)]
            sev, detail = ("high", f"registry token stored for {', '.join(_npm_target(r) for r in creds)}") \
                if creds else ("info", "no registry token stored")
        else:
            sev, detail = "medium", "a file named like a credential file (not opened further)"
        sec.add(sev, where, detail + (f"; {git_note}" if git_note else ""), git=st or None,
                reach=f"Project: {where}: {detail}" + (f", {git_note}" if git_note else "") if sev != "info" else "")
    sec.found = True
    return sec


# ---------------------------------------------------------------- Claude Code transcripts
def transcript_files(ctx: Context) -> tuple[Path, list]:
    root = ctx.claude_dir() / "projects"
    out = []
    for dirpath, _, filenames in os.walk(root, onerror=lambda e: None):
        for n in filenames:
            # set-aside transcripts are named <session>.jsonl.superseded-<timestamp> (Claude Code docs)
            # a symlink is skipped: rewriting it would replace the link and leave its target as it was
            if (n.endswith(".jsonl") or ".jsonl.superseded-" in n) and not os.path.islink(os.path.join(dirpath, n)):
                out.append(Path(dirpath) / n)
    return root, sorted(out)


def _strings(obj):
    stack = [obj]
    while stack:
        o = stack.pop()
        if isinstance(o, str):
            yield o
        elif isinstance(o, dict):
            for k, v in o.items():
                stack.append(k)
                stack.append(v)
        elif isinstance(o, list):
            stack.extend(o)


def _redact_obj(obj):
    counts: dict = {}

    def walk(o):
        if isinstance(o, str):
            new, c = redact_text(o)
            for k, n in c.items():
                counts[k] = counts.get(k, 0) + n
            return new
        if isinstance(o, dict):
            return {walk(k): walk(v) for k, v in o.items()}
        if isinstance(o, list):
            return [walk(v) for v in o]
        return o

    return walk(obj), counts


def _split_ending(raw: bytes) -> tuple[bytes, bytes]:
    if raw.endswith(b"\r\n"):
        return raw[:-2], b"\r\n"
    if raw.endswith(b"\n"):
        return raw[:-1], b"\n"
    return raw, b""


def line_counts(body: bytes) -> dict:
    """Secret-shaped strings in one transcript line, counted inside its decoded JSON strings when it parses."""
    if not triggered(body):
        return {}
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return redact_text(body.decode("utf-8", "surrogateescape"))[1]
    try:
        obj = json.loads(text)
    except ValueError:
        return redact_text(text)[1]
    counts: dict = {}
    for s in _strings(obj):
        for k, n in redact_text(s)[1].items():
            counts[k] = counts.get(k, 0) + n
    return counts


def redact_line(body: bytes) -> tuple[bytes, dict]:
    """The line with every secret-shaped string replaced. A line that was valid JSON stays valid JSON:
    the in-place text replacement is kept only when it decodes to exactly the JSON-level replacement;
    otherwise the line is re-serialised from that."""
    if not triggered(body):
        return body, {}
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:  # not UTF-8, so not JSON either: replace in the text, keep every other byte
        new, counts = redact_text(body.decode("utf-8", "surrogateescape"))
        return new.encode("utf-8", "surrogateescape"), counts
    try:
        obj = json.loads(text)
    except ValueError:
        new, counts = redact_text(text)
        return new.encode("utf-8"), counts
    new_obj, counts = _redact_obj(obj)
    if not counts:
        return body, {}
    raw = redact_text(text)[0]
    try:
        if json.loads(raw) == new_obj:
            return raw.encode("utf-8"), counts
    except ValueError:
        pass
    return json.dumps(new_obj, ensure_ascii=True, separators=(",", ":")).encode("ascii"), counts


def scan_transcript_file(p: Path) -> tuple[dict, dict, str]:
    """(count per type, lines per type, error)."""
    counts: dict = {}
    lines: dict = {}
    try:
        with open(p, "rb") as f:
            for raw in f:
                body, _ = _split_ending(raw)
                c = line_counts(body)
                for k, n in c.items():
                    counts[k] = counts.get(k, 0) + n
                    lines[k] = lines.get(k, 0) + 1
    except OSError as e:
        return counts, lines, f"unreadable ({type(e).__name__})"
    return counts, lines, ""


def scan_transcripts(ctx: Context) -> tuple[Section, list]:
    sec = Section("transcripts", "Claude Code transcripts")
    root, files = transcript_files(ctx)
    sec.paths.append(ctx.show(root))
    hits = []
    totals: dict = {}
    for p in files:
        counts, lines, err = scan_transcript_file(p)
        if err:
            sec.error(ctx.show(p), err)
        if counts:
            hits.append((p, counts, lines))
            for k, n in counts.items():
                totals[k] = totals.get(k, 0) + n
    if files:
        sec.found = True
    for p, counts, lines in hits:
        detail = ", ".join(f"{k} {counts[k]} in {_count(lines[k], 'line')}" for k in sorted(counts))
        sec.add("high", ctx.show(p), detail, where=ctx.show(p),
                types={k: {"count": counts[k], "lines": lines[k]} for k in sorted(counts)})
    if hits:
        n = sum(totals.values())
        kinds = ", ".join(f"{k} {totals[k]}" for k in sorted(totals, key=lambda k: -totals[k]))
        sec.notes.append(f"{_count(n, 'secret-shaped string')} in {len(hits)} of {_count(len(files), 'file')} "
                         f"({kinds}). They are plaintext copies of what passed through a tool; "
                         "`credential-reach --redact` replaces them after a confirmation and a backup.")
        sec.findings[0]["reach"] = (f"Claude Code transcripts: {_count(n, 'secret-shaped string')} ({kinds}) in "
                                    f"{_count(len(hits), 'file')} under {ctx.show(root)}, readable by any process "
                                    "running as you")
    elif files:
        sec.notes.append(f"No secret-shaped strings in {_count(len(files), 'file')}.")
    return sec, hits


# ---------------------------------------------------------------- --redact
def redact_file(p: Path, backup: Path) -> tuple[dict, str]:
    """Rewrite one transcript with its secret-shaped strings replaced, after copying it to `backup`.
    (count per type, "") on success, ({}, why) when the file was left as it was."""
    try:
        before = os.stat(p)
    except OSError as e:
        return {}, f"unreadable ({type(e).__name__})"
    fd, tmp = tempfile.mkstemp(prefix=f".{p.name}.", suffix=".credential-reach.tmp", dir=str(p.parent))
    counts: dict = {}
    valid_before = 0
    try:
        with os.fdopen(fd, "wb") as out, open(p, "rb") as src:
            for raw in src:
                body, end = _split_ending(raw)
                valid_before += _valid_json(body)
                new, c = redact_line(body)
                for k, n in c.items():
                    counts[k] = counts.get(k, 0) + n
                out.write(new + end)
        if not counts:
            os.unlink(tmp)
            return {}, ""
        valid_after, left = 0, 0
        with open(tmp, "rb") as f:
            for raw in f:
                body, _ = _split_ending(raw)
                valid_after += _valid_json(body)
                left += sum(line_counts(body).values())
        if valid_after != valid_before or left:
            os.unlink(tmp)
            return {}, "the rewritten file did not check out; left unchanged"
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, backup)
        now = os.stat(p)
        if (now.st_size, now.st_mtime_ns) != (before.st_size, before.st_mtime_ns):
            os.unlink(tmp)
            backup.unlink()
            return {}, "changed while being redacted (a session is writing to it); left unchanged"
        shutil.copymode(p, tmp)
        os.replace(tmp, p)
    except OSError as e:
        if os.path.exists(tmp):
            os.unlink(tmp)
        return {}, f"could not rewrite ({type(e).__name__})"
    return counts, ""


def _valid_json(body: bytes) -> int:
    if not body.strip():
        return 0
    try:
        json.loads(body.decode("utf-8"))
        return 1
    except (UnicodeDecodeError, ValueError):
        return 0


def _private_dir(d: Path) -> None:
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass


def run_redact(ctx: Context, as_json: bool) -> int:
    sec, hits = scan_transcripts(ctx)
    root = ctx.claude_dir() / "projects"
    if not hits:
        msg = f"No secret-shaped strings in the transcripts under {ctx.show(root)}; nothing to redact."
        print(json.dumps({"redacted": [], "message": msg}, indent=1) if as_json else msg)
        return 0 if not sec.errors else 2
    n = sum(sum(c.values()) for _, c, _ in hits)
    stamp = ctx.now.strftime("%Y%m%dT%H%M%SZ")
    backup_root = ctx.claude_dir() / "credential-reach-backups" / stamp
    err = sys.stderr
    print(f"{_count(n, 'secret-shaped string')} in {_count(len(hits), 'transcript file')} under {ctx.show(root)}:",
          file=err)
    for p, counts, _ in hits:
        print(f"  {ctx.show(p)}: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())), file=err)
    print(f"Each file is copied to {ctx.show(backup_root)} first. That copy still holds the secrets: delete it once "
          "you have checked the result.\nClose Claude Code sessions first; a file written to during the rewrite is "
          "left unchanged.", file=err)
    if not (hasattr(sys.stdin, "isatty") and sys.stdin.isatty()):
        print("credential-reach: --redact asks for confirmation at a terminal, and stdin is not one; "
              "nothing changed.", file=err)
        return 2
    err.write('Type "redact" to replace them: ')
    err.flush()
    answer = sys.stdin.readline().strip()
    if answer != "redact":
        print("Not confirmed; nothing changed.", file=err)
        return 1
    _private_dir(backup_root)
    done, failed = [], []
    for p, _, _ in hits:
        rel = p.relative_to(root)
        dest = backup_root / "projects" / rel
        _private_dir(dest.parent)
        counts, why = redact_file(p, dest)
        (failed if why else done).append({"file": ctx.show(p), **({"error": why} if why else {"replaced": counts})})
    result = {"redacted": done, "failed": failed, "backup": ctx.show(backup_root)}
    if as_json:
        print(json.dumps(result, indent=1))
    else:
        for d in done:
            print(f"redacted {d['file']}: " + ", ".join(f"{k} {v}" for k, v in sorted(d["replaced"].items())))
        for f in failed:
            print(f"left unchanged {f['file']}: {f['error']}")
        print(f"backup: {ctx.show(backup_root)}")
    return 2 if failed else 0


# ---------------------------------------------------------------- --probe
GITHUB_TOKEN_SHAPE = re.compile(r"gh[pousr]_[A-Za-z0-9]{36,251}|github_pat_[A-Za-z0-9_]{22,251}"
                                r"|ghs_[0-9]{1,20}_[A-Za-z0-9_-]{1,2000}\.[A-Za-z0-9_-]{1,2000}\.[A-Za-z0-9_-]{1,2000}")
LEGACY_GITHUB_TOKEN = re.compile(r"[0-9a-f]{40}")  # unprefixed, from before 2021; only from a github.com entry
SCOPE_NOTES = {  # GitHub docs, "Scopes for OAuth apps", checked 2026-09-24
    "repo": "full access to public and private repositories",
    "delete_repo": "delete repositories the account administers",
    "admin:org": "fully manage organizations, teams and memberships",
    "workflow": "add and update GitHub Actions workflow files",
    "admin:repo_hook": "manage repository webhooks",
    "admin:org_hook": "manage organization webhooks",
    "admin:public_key": "manage the account's public keys",
    "admin:gpg_key": "manage the account's GPG keys",
    "write:packages": "publish packages",
    "delete:packages": "delete packages",
    "codespace": "create and manage codespaces",
}
TOKEN_TYPES = {"ghp_": "personal access token (classic)", "github_pat_": "fine-grained personal access token",
               "gho_": "OAuth token", "ghu_": "GitHub App user token", "ghs_": "GitHub App installation token",
               "ghr_": "GitHub App refresh token"}


def token_type(token: str) -> str:
    return next((v for k, v in TOKEN_TYPES.items() if token.startswith(k)), "unprefixed token")


def _header(headers, name: str):
    if headers is None:
        return None
    try:
        v = headers.get(name)
    except AttributeError:
        return None
    if v is None and isinstance(headers, dict):
        v = next((val for k, val in headers.items() if str(k).lower() == name.lower()), None)
    return v


def probe_one(token: str, sources: list, timeout: float) -> dict:
    r = {"sources": sources, "token_type": token_type(token)}
    req = urllib.request.Request(GITHUB_USER_API, headers={
        "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": UA})
    body, headers = b"", None
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, "status", None) or 200
            headers = resp.headers
            body = resp.read(65536) or b""
    except urllib.error.HTTPError as e:
        status, headers = e.code, e.headers
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as e:
        r.update(result=f"could not reach api.github.com ({type(e).__name__})", checked=False)
        return r
    r["status"] = status
    if status == 401:
        r.update(result="rejected (401): revoked, expired or not a valid token", checked=True, valid=False)
        return r
    if status != 200:
        limited = _header(headers, "X-RateLimit-Remaining") == "0"
        r.update(result=f"GitHub answered {status}" + (" (rate limit)" if limited else ""), checked=False)
        return r
    r.update(checked=True, valid=True, result="valid")
    try:
        data = json.loads(body.decode("utf-8")) if body else None
    except (UnicodeDecodeError, ValueError):
        data = None
    login = data.get("login") if isinstance(data, dict) else None
    if isinstance(login, str) and re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})(?:\[bot\])?", login):
        r["login"] = login
    raw = _header(headers, "X-OAuth-Scopes")
    if raw is None:
        r["scopes"] = None
        r["scopes_note"] = ("scopes are not exposed for this token type; a fine-grained token's repositories and "
                            "permissions are set on github.com") if token.startswith("github_pat_") else \
            "GitHub sent no X-OAuth-Scopes header for this token"
    else:
        scopes = [s.strip() for s in str(raw).split(",") if s.strip()]
        r["scopes"] = [s for s in scopes if re.fullmatch(r"[a-z0-9_:]{1,40}", s)][:50]
        r["powerful"] = {s: SCOPE_NOTES[s] for s in r["scopes"] if s in SCOPE_NOTES}
    exp = _header(headers, "GitHub-Authentication-Token-Expiration")
    if isinstance(exp, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} [A-Z+0-9:-]{1,6}", exp.strip()):
        r["expires"] = exp.strip()
    return r


def probe_github(ctx: Context, timeout: float = 10.0) -> dict:
    tokens = dict(ctx.github_tokens)
    out = {"endpoint": GITHUB_USER_API, "results": []}
    if urllib.request.getproxies().get("https"):
        # seen in a hosted sandbox: its proxy replaced the Authorization header with the session's own credential
        out["note"] = ("Sent through the HTTPS proxy set in the environment. A proxy that adds its own GitHub "
                       "credentials changes what GitHub answers, and the scopes shown would then be the proxy's.")
    if not tokens:
        print("credential-reach --probe: no GitHub token for github.com found; nothing sent.", file=sys.stderr)
        return out
    print(f"credential-reach --probe: sending {_count(len(tokens), 'GitHub token')} to GET {GITHUB_USER_API}, "
          "one request each, to read the scopes GitHub reports. This uses each token once; nothing else is sent.",
          file=sys.stderr)
    for token, sources in tokens.items():
        out["results"].append(probe_one(token, sources, timeout))
    return out


def probe_detail(r: dict) -> str:
    """One line per probed token, for the probe section: what GitHub said, without the token."""
    head = r["token_type"] + (f" for {r['login']}" if r.get("login") else "")
    if not r.get("valid"):
        return f"{head}: {r['result']}"
    if r.get("scopes") is None:
        return f"{head}: valid; {r['scopes_note']}"
    scopes = ", ".join(r["scopes"]) or "none (public read only)"
    return f"{head}: valid; scopes {scopes}" + (f"; expires {r['expires']}" if r.get("expires") else "")


def probe_reach(r: dict) -> tuple[str, str]:
    src = ", ".join(r["sources"])
    who = f" for {r['login']}" if r.get("login") else ""
    if not r.get("checked"):
        return "info", f"GitHub probe: token in {src}: {r['result']}"
    if not r.get("valid"):
        return "info", f"GitHub probe: token in {src}: {r['result']}"
    if r.get("scopes") is None:
        return "medium", f"GitHub probe: {r['token_type']}{who} in {src} is valid; {r['scopes_note']}"
    if not r["scopes"]:
        return "medium", f"GitHub probe: {r['token_type']}{who} in {src} is valid, with no scopes (public read)"
    power = r.get("powerful") or {}
    text = f"GitHub probe: {r['token_type']}{who} in {src} is valid, scopes {', '.join(r['scopes'])}"
    if power:
        text += "; " + "; ".join(f"{s}: {n}" for s, n in power.items())
    if r["token_type"].endswith("(classic)"):
        text += "; account-wide"
    return ("high" if power else "medium"), text


# ---------------------------------------------------------------- the whole audit
SCANNERS = (scan_env, scan_aws, scan_gcloud, scan_azure, scan_kube, scan_docker, scan_npm, scan_pypirc, scan_netrc,
            scan_git, scan_gh, scan_ssh, scan_terraform, scan_project)


def scan_transcript_section(ctx: Context) -> Section:
    return scan_transcripts(ctx)[0]


def _guarded(scan, ctx: Context) -> Section:
    """One scanner's section; a bug in it becomes a reported error, never a traceback or a lost report."""
    try:
        return scan(ctx)
    except Exception as e:  # noqa: BLE001 - the other sections still have to be reported
        sec = Section(scan.__name__.replace("scan_", ""), scan.__name__.replace("scan_", "").capitalize())
        sec.error("credential-reach", f"internal error ({type(e).__name__}); this part was not checked")
        return sec


def audit(ctx: Context, transcripts: bool = True) -> dict:
    sections = [_guarded(scan, ctx) for scan in SCANNERS]
    if transcripts:
        sections.append(_guarded(scan_transcript_section, ctx))
    probe = probe_github(ctx) if ctx.probe else None
    blast = []
    order = {s: i for i, s in enumerate(SEVERITIES)}
    for sec in sections:
        for f in sec.findings:
            if f.get("reach") and f["severity"] in ("high", "medium"):
                blast.append({"severity": f["severity"], "source": sec.id, "text": f["reach"]})
    if probe:
        for r in probe["results"]:
            sev, text = probe_reach(r)
            r["severity"] = sev
            if sev != "info":
                blast.append({"severity": sev, "source": "probe", "text": text})
    blast.sort(key=lambda b: order[b["severity"]])
    totals = {s: sum(1 for sec in sections for f in sec.findings if f["severity"] == s) for s in SEVERITIES}
    incomplete = any(sec.errors for sec in sections) or bool(
        probe and any(not r.get("checked") for r in probe["results"]))
    report = {
        "tool": "credential-reach", "version": VERSION,
        "checked": ctx.now.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "platform": ctx.system, "home": safe(str(ctx.home), 200),
        "project": ctx.show(ctx.project) if ctx.project else None,
        "values_shown": False,
        "blast_radius": blast,
        "sections": [sec.as_dict() for sec in sections if sec.found],
        "not_found": [{"id": sec.id, "title": sec.title, "paths": sec.paths} for sec in sections if not sec.found],
        "totals": totals, "incomplete": incomplete,
    }
    if probe is not None:
        report["probe"] = probe
    return _scrub(report)


def _scrub(o):
    """Last guard on everything printed: any secret shape left in any string is replaced."""
    if isinstance(o, str):
        return redact_text(o)[0] if triggered(o.encode("utf-8", "surrogatepass")) else o
    if isinstance(o, dict):
        return {k: _scrub(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_scrub(v) for v in o]
    return o


# ---------------------------------------------------------------- output
TAG = {"high": "high  ", "medium": "medium", "info": "info  "}
FOOTER = ("Not read: macOS Keychain, Windows Credential Manager, browser sessions, and MCP server settings; "
          "programs the agent can run may still use what they hold.")


def render_text(rep: dict) -> str:
    out = [f"credential-reach {rep['version']}: what an agent running as you here can reach",
           f"checked {rep['checked']} on {rep['platform']} · home {rep['home']}"
           + (f" · project {rep['project']}" if rep.get("project") else ""),
           "No secret values are shown: names, locations, hosts, profiles, lengths and presence only.", "",
           "Blast radius"]
    if not rep["blast_radius"]:
        out.append("  nothing found that an agent could use")
    for b in rep["blast_radius"][:25]:
        out.append(f"  {TAG[b['severity']]}  {b['text']}")
    if len(rep["blast_radius"]) > 25:
        out.append(f"  ... and {len(rep['blast_radius']) - 25} more below")
    for sec in rep["sections"]:
        out += ["", sec["title"] + (f"  ({', '.join(sec['paths'])})" if sec["paths"] else "")]
        width = min(max([len(f["item"]) for f in sec["findings"]] + [4]), 40)
        for f in sec["findings"]:
            out.append(f"  {TAG[f['severity']]}  {f['item'].ljust(width)}  {f['detail']}")
        out += [f"  note: {n}" for n in sec["notes"]]
        out += [f"  could not check: {e}" for e in sec["errors"]]
        if sec["not_visible"]:
            out.append(f"  not visible here: {sec['not_visible']}")
    if rep.get("probe") is not None:
        out += ["", f"GitHub probe  (GET {rep['probe']['endpoint']}, one request per token)"]
        if not rep["probe"]["results"]:
            out.append("  no GitHub token for github.com was found; nothing was sent")
        if rep["probe"].get("note") and rep["probe"]["results"]:
            out.append(f"  note: {rep['probe']['note']}")
        for r in rep["probe"]["results"]:
            out.append(f"  {TAG[r['severity']]}  {', '.join(r['sources'])}: {probe_detail(r)}")
    if rep["not_found"]:
        out += ["", "Nothing found in: " + "; ".join(f"{s['title']} ({', '.join(s['paths'])})" if s["paths"]
                                              else s["title"] for s in rep["not_found"])]
    t = rep["totals"]
    out += ["", f"{t['high']} high · {t['medium']} medium · {t['info']} info"
            + (" · some checks could not complete" if rep["incomplete"] else ""), FOOTER]
    return "\n".join(out) + "\n"


def _md(t) -> str:
    return str(t).replace("|", "\\|").replace("`", "'").replace("<", "&lt;").replace(">", "&gt;")


def render_markdown(rep: dict) -> str:
    out = [f"## credential-reach report, {rep['checked'][:10]}", "",
           f"Checked on {rep['platform']}, home `{_md(rep['home'])}`"
           + (f", project `{_md(rep['project'])}`" if rep.get("project") else "")
           + ". No secret values: names, locations, hosts, profiles, lengths and presence only.", "",
           "### Blast radius", ""]
    out += [f"- **{b['severity']}** {_md(b['text'])}" for b in rep["blast_radius"]] or ["- nothing found"]
    for sec in rep["sections"]:
        out += ["", f"### {_md(sec['title'])}", ""]
        if sec["paths"]:
            out += ["Read: " + ", ".join(f"`{_md(p)}`" for p in sec["paths"]), ""]
        if sec["findings"]:
            out += ["| Severity | Item | Detail |", "| --- | --- | --- |"]
            out += [f"| {f['severity']} | {_md(f['item'])} | {_md(f['detail'])} |" for f in sec["findings"]]
            out.append("")
        out += [f"- Note: {_md(n)}" for n in sec["notes"]]
        out += [f"- Could not check: {_md(e)}" for e in sec["errors"]]
        if sec["not_visible"]:
            out.append(f"- Not visible here: {_md(sec['not_visible'])}")
    if rep.get("probe") is not None:
        out += ["", "### GitHub probe", "", f"`GET {rep['probe']['endpoint']}`, one request per token.", ""]
        out += [f"- **{r['severity']}** {_md(', '.join(r['sources']))}: {_md(probe_detail(r))}"
                for r in rep["probe"]["results"]] or ["- No GitHub token for github.com was found; nothing was sent."]
        if rep["probe"].get("note") and rep["probe"]["results"]:
            out.append(f"- Note: {_md(rep['probe']['note'])}")
    if rep["not_found"]:
        out += ["", "Nothing found in: " + "; ".join(_md(s["title"]) for s in rep["not_found"])]
    t = rep["totals"]
    out += ["", f"{t['high']} high · {t['medium']} medium · {t['info']} info", "", f"_{_md(FOOTER)}_",
            "", "_Made with [credential-reach](https://github.com/Keremozdemirra/credential-reach)._"]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- command line
def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="credential-reach",
        description="List the credentials an AI agent running as you on this machine could use: environment "
                    "variables, cloud CLI profiles, kubeconfig, registry tokens, SSH keys, the project's .env files "
                    "and Claude Code transcripts. Never prints a secret value.",
        epilog="Exit codes: 0 without --strict (2 for a --project that is not a directory). With --strict: 1 when "
               "a finding is high, else 2 when a check could not complete, else 0. With --redact: 0 done or "
               "nothing to do, 1 not confirmed, 2 not a terminal or a file could not be rewritten.")
    fmt = ap.add_mutually_exclusive_group()
    fmt.add_argument("--json", action="store_true", help="print JSON")
    fmt.add_argument("--markdown", action="store_true", help="print Markdown, for an issue or a note")
    ap.add_argument("--project", type=Path, metavar="DIR",
                    help="the project to check for .env and secret-named files (default: the current directory)")
    ap.add_argument("--no-transcripts", action="store_true", help="skip the Claude Code transcript scan")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 on any high finding, else 2 if a check could not complete")
    ap.add_argument("--probe", action="store_true",
                    help="send each GitHub token found for github.com, once, to GET https://api.github.com/user "
                         "to read its scopes. This uses the token. Off by default; nothing else is ever sent.")
    ap.add_argument("--redact", action="store_true",
                    help="replace secret-shaped strings in Claude Code transcripts with [REDACTED:<type>], after "
                         "a confirmation typed at the terminal and a backup copy of each changed file")
    ap.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):  # a Windows console that cannot print a character must not crash
        sys.stdout.reconfigure(errors="replace")
    if a.project is not None and not a.project.is_dir():
        print(f"credential-reach: --project {safe(a.project, 200)}: not a directory", file=sys.stderr)
        return 2
    try:
        project = Path(os.path.abspath(a.project if a.project is not None else Path.cwd()))
    except OSError:  # the current directory was deleted
        project = None
    ctx = Context(Path.home(), os.environ, platform.system(), project, probe=a.probe)
    if a.redact:
        return run_redact(ctx, a.json)
    rep = audit(ctx, transcripts=not a.no_transcripts)
    if a.json:
        print(json.dumps(rep, indent=1, ensure_ascii=False))
    elif a.markdown:
        sys.stdout.write(render_markdown(rep))
    else:
        sys.stdout.write(render_text(rep))
    if a.strict:
        if rep["totals"]["high"]:
            return 1
        if rep["incomplete"]:
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
