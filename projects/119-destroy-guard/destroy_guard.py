#!/usr/bin/env python3
"""destroy-guard: destructive infrastructure commands wait for a fresh, verified backup.

Two halves that never share work:

  the hook   destroy_guard_hook.py reads a Bash or PowerShell command line before
             Claude Code runs it. For `terraform destroy`, `kubectl delete`,
             `helm uninstall`, `git push --force` and the like it looks for the
             manifest of a fresh, verified backup of exactly that target. If
             there is none it asks the person and names the command that makes
             one; if there is one it says nothing. It runs no command and
             writes no file.
  the CLI    `destroy-guard backup -- <command>` works out the read-only export
             for that command (terraform state pull, kubectl get -o json,
             helm get all, git ls-remote + fetch), checks what came back, and
             stores it under .destroy-guard/backups/ with a manifest.

Standard library only; Python 3.9+.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import shlex
import stat
import sys
import urllib.parse
from pathlib import Path

VERSION = "0.1.0"
# How long a backup counts as fresh. destroy-guard's own choice, not a standard:
# long enough to make a backup and then run the command, short enough that the
# target has probably not changed in between. DESTROY_GUARD_MAX_AGE_MINUTES overrides it.
DEFAULT_MAX_AGE_MINUTES = 30
MAX_AGE_ENV = "DESTROY_GUARD_MAX_AGE_MINUTES"
STORE_ENV = "DESTROY_GUARD_DIR"
# A manifest dated a little in the future is a clock difference; more is not a backup of now.
CLOCK_SKEW = dt.timedelta(seconds=60)
MAX_MANIFESTS = 500  # newest first: a hook must not read an unbounded directory
MAX_MANIFEST_BYTES = 1 << 20
MAX_SMALL_FILE = 4 << 20  # kubeconfig, git config and HEAD, .terraform/environment
FINGERPRINT_LIMIT = (2000, 64 << 20)  # files, bytes hashed for `kubectl delete -f <dir>`
EXPORT_TIMEOUT = 600
MAX_DEPTH = 4  # bash -c "sh -c '...'" nesting followed
MAX_REASON = 1800

# ---------------------------------------------------------------- masking

# Words that make an option's value, or an assignment, worth hiding.
SECRET_WORD = re.compile(r"(?i)key|token|secret|passw|pwd|auth|credential|cookie|session|bearer|signature|"
                         r"private|access|(?:^|[_-])pw(?:$|[_-])")
# The shapes of common API keys, found anywhere in a value.
TOKEN_SHAPE = re.compile(r"(?:sk|pk|rk)[-_][A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{20,}"
                         r"|glpat-[A-Za-z0-9_-]{8,}|xox[abeprs]-[A-Za-z0-9-]{10,}|AKIA[A-Z0-9]{16}"
                         r"|AIza[A-Za-z0-9_-]{30,}|eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")
URL_IN_TEXT = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s\"'<>`]+")
ASSIGN = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=(.*)", re.S)
ENV_NAME = re.compile(r"[A-Z_][A-Z0-9_]*")
FLAG = re.compile(r"-{1,2}[A-Za-z][A-Za-z0-9_.-]*")
FLAG_VALUE = re.compile(r"(-{1,2}[A-Za-z][A-Za-z0-9_.-]*)=(.*)", re.S)
# Variables that name a target, not a credential. Every other environment
# assignment in front of a command is printed as NAME=***.
SHOWN_ENV = {"TF_WORKSPACE", "TF_DATA_DIR", "KUBECONFIG", "HELM_NAMESPACE", "HELM_KUBECONTEXT",
             "AWS_PROFILE", "AWS_REGION", "AWS_DEFAULT_REGION"}
MYSQL_TOOLS = {"mysql", "mariadb", "mysqladmin"}
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f\u200b-\u200f\u2028\u2029\u202a-\u202e\u2066-\u2069\ufeff]")


def clean(text, limit: int = 300) -> str:
    """Text made safe to print on one line: no control or bidi characters, bounded."""
    t = re.sub(r"\s+", " ", CONTROL.sub(" ", str(text))).strip()
    return t if len(t) <= limit else t[:limit - 3].rstrip() + "..."


def mask_url(u: str) -> str:
    """`https://user:pw@host/p?token=x` -> `https://***@host/p?***`."""
    try:
        p = urllib.parse.urlsplit(u)
    except ValueError:
        return "***"
    if not p.scheme or not p.netloc:
        return u
    netloc = ("***@" + p.netloc.rsplit("@", 1)[1]) if "@" in p.netloc else p.netloc
    return f"{p.scheme}://{netloc}{p.path}" + ("?***" if p.query else "") + ("#***" if p.fragment else "")


def mask_text(text: str) -> str:
    """URLs and key-shaped strings inside free text, masked."""
    return TOKEN_SHAPE.sub("***", URL_IN_TEXT.sub(lambda m: mask_url(m.group(0)), str(text)))


def mask_word(w: str, env_prefix: bool = False) -> str:
    m = FLAG_VALUE.fullmatch(w)
    if m:  # --flag=value, -var=name=value
        flag, val = m.groups()
        key = val.split("=", 1)[0] if "=" in val else ""
        if SECRET_WORD.search(flag) or (key and SECRET_WORD.search(key)) or TOKEN_SHAPE.search(val):
            return flag + "=***"
        return flag + "=" + mask_text(val)
    m = ASSIGN.fullmatch(w)
    if m:
        name = m.group(1)
        # In front of a command it is an environment variable, where credentials live. As an
        # argument (`-l app=web`, `-var region=eu`) only upper-case or secret-looking names are hidden.
        hide = (name not in SHOWN_ENV) if env_prefix else (
            (ENV_NAME.fullmatch(name) is not None and name not in SHOWN_ENV) or SECRET_WORD.search(name) is not None)
        return f"{name}=***" if hide or TOKEN_SHAPE.search(m.group(2)) else f"{name}={mask_text(m.group(2))}"
    return mask_text(w)


def mask_words(words, tool: str = "", n_assign: int = 0) -> list[str]:
    """Words as they may be printed: credentials in URLs, flags and assignments replaced by ***."""
    out, hide_next = [], False
    for k, w in enumerate(str(x) for x in words):
        if hide_next and not w.startswith("-"):
            out.append("***")
            hide_next = False
            continue
        if tool in MYSQL_TOOLS and re.fullmatch(r"-p.+", w):  # mysql -pSECRET
            out.append("-p***")
            hide_next = False
            continue
        out.append(mask_word(w, env_prefix=k < n_assign))
        hide_next = bool(FLAG.fullmatch(w) and SECRET_WORD.search(w))  # `--token VALUE`
    return out


# ---------------------------------------------------------------- reading the command line

PUNCTUATION = "();<>|&\n"
OPERATORS = re.compile(r"&>>|<<<|\|\||&&|;;|\|&|<<|>>|<&|>&|&>|<>|>\||[|&;\n()<>]")
REDIRECTS = {"<", ">", ">>", "<<", "<<<", "<&", ">&", "&>", "&>>", "<>", ">|"}
WINDOWS_PATH = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:\\")
HEREDOC_OP = re.compile(r"<<(-?)[ \t]*(?:'([^'\n]*)'|\"([^\"\n]*)\"|((?:\\.|[^\s;&|()<>'\"])+))")
DYNAMIC = re.compile(r"[$`*?]")


def _prepass(text: str, shell: str = "bash", body: bool = False):
    """Heredoc bodies and comments out of a command line; substitutions noted.

    Returns (line, bodies, spans): the line with each heredoc body removed and
    its delimiter replaced by a placeholder, a map placeholder -> (body, expands),
    and the outermost `$(...)` and backtick spans, which run as command lines
    of their own even inside double quotes. With `body`, `text` is a heredoc
    body: quotes are literal, only substitutions count.
    """
    posix, ps = shell == "bash", shell == "powershell"
    out, bodies, spans, pending = [], {}, [], []
    stack = [["hd", 0]] if body else []  # [kind, start]: sq, dq, hd, sub, par, bt
    i, n = 0, len(text)

    def close(i):
        kind, start = stack.pop()
        if kind in ("sub", "bt") and not any(k in ("sub", "bt") for k, _ in stack):
            spans.append(text[start:i])

    while i < n:
        c = text[i]
        top = stack[-1][0] if stack else "top"
        if top == "sq":
            out.append(c)
            i += 1
            if c == "'":
                stack.pop()
            continue
        if c == "\\" and posix and i + 1 < n:
            out.append(text[i:i + 2])
            i += 2
            continue
        if c == "`" and ps and i + 1 < n:  # PowerShell's escape character
            out.append(text[i:i + 2])
            i += 2
            continue
        if top in ("dq", "hd"):
            if c == '"' and top == "dq":
                stack.pop()
            elif text.startswith("$(", i):
                stack.append(["sub", i + 2])
                out.append("$(")
                i += 2
                continue
            elif c == "`" and posix:
                stack.append(["bt", i + 1])
            out.append(c)
            i += 1
            continue
        if c == "'":
            stack.append(["sq", i])
        elif c == '"':
            stack.append(["dq", i])
        elif c == "`" and posix:
            if top == "bt":
                close(i)
            else:
                stack.append(["bt", i + 1])
        elif text.startswith("$(", i):
            stack.append(["sub", i + 2])
            out.append("$(")
            i += 2
            continue
        elif c == "(" and top in ("sub", "par"):
            stack.append(["par", i])
        elif c == ")" and top in ("sub", "par"):
            close(i)
        elif c == "#" and (i == 0 or text[i - 1] in " \t\n;&|()"):
            j = text.find("\n", i)  # a comment runs to the end of its line
            i = n if j < 0 else j
            continue
        elif posix and text.startswith("<<", i) and not text.startswith("<<<", i) and (i == 0 or text[i - 1] != "<"):
            m = HEREDOC_OP.match(text, i)
            if m:
                ph = f"__destroy_guard_heredoc_{len(bodies) + len(pending)}__"
                word = m.group(4)
                delim = m.group(2) if m.group(2) is not None else m.group(3) if m.group(3) is not None \
                    else word.replace("\\", "")
                # an unquoted delimiter means the body is expanded, so $(...) inside it runs
                expands = word is not None and "\\" not in word
                pending.append((ph, delim, bool(m.group(1)), expands))
                out.append(f"<< {ph} ")
                i = m.end()
                continue
        elif c == "\n" and pending:
            out.append("\n")
            i += 1
            for ph, delim, strip_tabs, expands in pending:
                lines = []
                while i < n:
                    j = text.find("\n", i)
                    line = text[i:] if j < 0 else text[i:j]
                    i = n if j < 0 else j + 1
                    if (line.lstrip("\t") if strip_tabs else line) == delim:
                        break
                    lines.append(line)
                bodies[ph] = ("\n".join(lines), expands)
            pending = []
            continue
        out.append(c)
        i += 1
    while stack:  # unterminated: what is open still runs
        kind, start = stack[-1]
        if kind in ("sub", "bt") and not any(k in ("sub", "bt") for k, _ in stack[:-1]):
            spans.append(text[start:])
        stack.pop()
    return "".join(out), bodies, spans


def split_commands(line: str, shell: str = "bash"):
    """The simple commands in a shell line, and `(` / `)` markers for subshells.

    `a; b`, `a&&b`, `a | b` and newlines separate. Each command is a dict with
    its words, its redirects [(operator, target)], and whether its standard
    input is a pipe. Returns None when the quotes do not balance.
    """
    lx = shlex.shlex(line, posix=True, punctuation_chars=PUNCTUATION)
    lx.whitespace_split = True
    lx.whitespace = " \t\r"  # a newline separates commands; it is not just a space
    lx.commenters = ""  # comments were removed by _prepass, which knows where a word starts
    if shell != "bash" or WINDOWS_PATH.search(line):
        lx.escape = ""  # PowerShell escapes with a backtick, and C:\Users\x is a path
    try:
        tokens = list(lx)
    except ValueError:
        return None
    items, cur, redirs, piped = [], [], [], False

    def flush(next_piped: bool):
        nonlocal cur, redirs, piped
        if cur or redirs:
            items.append({"words": cur, "redirects": redirs, "piped": piped})
        cur, redirs, piped = [], [], next_piped

    i = 0
    while i < len(tokens):
        t = tokens[i]
        if not t or not all(ch in PUNCTUATION for ch in t):
            cur.append(t)
            i += 1
            continue
        ops = OPERATORS.findall(t)
        for j, o in enumerate(ops):
            if o in ("<", ">") and ops[j + 1:j + 2] == ["("]:
                continue  # process substitution: the `(` that follows opens it
            if o in REDIRECTS:
                target = ""
                if j == len(ops) - 1 and i + 1 < len(tokens) and not all(ch in PUNCTUATION for ch in tokens[i + 1]):
                    target = tokens[i + 1]
                    i += 1
                if cur and cur[-1].isdigit():  # the 2 in 2>&1
                    cur.pop()
                redirs.append((o, target))
            elif o == "(":
                flush(False)
                items.append("(")
            elif o == ")":
                flush(False)
                items.append(")")
            else:
                flush(o in ("|", "|&"))
        i += 1
    flush(False)
    return items


def _basename(word: str) -> str:
    """`C:\\tools\\terraform.exe` -> `terraform`."""
    b = re.split(r"[\\/]", str(word).strip())[-1].lower()
    for suffix in (".exe", ".cmd", ".bat", ".ps1"):
        if b.endswith(suffix):
            b = b[:-len(suffix)]
    return b


def _join(cwd, rel):
    """A directory relative to cwd, or None when either cannot be known."""
    if rel is None:
        return cwd
    if not rel or DYNAMIC.search(rel):
        return None
    rel = os.path.expanduser(rel)
    if os.path.isabs(rel) or WINDOWS_PATH.match(rel):
        return os.path.normpath(rel)
    return os.path.normpath(os.path.join(cwd, rel)) if cwd else None


def _read_small(path, limit: int = MAX_SMALL_FILE) -> str:
    try:
        with open(path, "rb") as f:
            return f.read(limit).decode("utf-8", "replace")
    except (OSError, ValueError):
        return ""


# Commands that run the command after them, and their options that take a value.
WRAPPERS = {
    "sudo": {"-u", "-g", "-C", "-D", "-h", "-p", "-r", "-t", "-U", "-T", "--user", "--group", "--chdir",
             "--host", "--prompt", "--role", "--type", "--other-user", "--close-from", "--command-timeout"},
    "doas": {"-u", "-C"}, "env": {"-u", "--unset", "-C", "--chdir", "-S", "--split-string"},
    "timeout": {"-s", "--signal", "-k", "--kill-after"}, "time": {"-f", "--format", "-o", "--output"},
    "nohup": set(), "nice": {"-n", "--adjustment"}, "ionice": {"-c", "-n", "-p", "--class", "--classdata"},
    "stdbuf": {"-i", "-o", "-e", "--input", "--output", "--error"}, "command": set(), "exec": {"-a"},
    "builtin": set(),
    "xargs": {"-I", "-L", "-n", "-P", "-s", "-d", "-E", "-a", "--max-args", "--max-procs", "--delimiter",
              "--arg-file", "--max-lines", "--max-chars", "--eof"},
}
KEYWORDS = {"if", "then", "else", "elif", "fi", "do", "done", "while", "until", "!", "{", "}"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh", "mksh", "ash"}
PWSH = {"powershell", "pwsh"}
CD = {"cd", "pushd", "chdir", "set-location", "sl", "push-location"}
EVAL = {"eval", "iex", "invoke-expression"}


class _Line:
    """What earlier commands on the same line changed: directory, exported variables, Terraform workspace."""

    def __init__(self, cwd, env=None, moved=None):
        self.cwd = cwd
        self.env = dict(env or {})  # exported on this line; None = unset
        self.vars = {}  # assigned without export: a child process does not see them
        self.tf_ws = {}  # directory -> workspace selected on this line
        self.plans = set()  # plan files written by `plan -destroy -out=...` on this line
        # Shared by every copy, subshells included: after any `cd` on the line, where a
        # substitution runs is not certain.
        self.moved = moved if moved is not None else [False]

    def copy(self) -> "_Line":
        c = _Line(self.cwd, self.env, self.moved)
        c.vars, c.tf_ws, c.plans = dict(self.vars), dict(self.tf_ws), set(self.plans)
        return c


class _Ctx:
    """One simple command that runs a tool."""

    def __init__(self, line, cwd, env_local, cleared, stdin_args, exe, words, shell):
        self.line, self.cwd, self.env_local, self.cleared = line, cwd, env_local, cleared
        self.stdin_args, self.exe, self.words, self.shell = stdin_args, exe, words, shell

    def env(self) -> dict:
        env = {} if self.cleared else dict(os.environ)
        for k, v in list(self.line.env.items()) + list(self.env_local.items()):
            if v is None:
                env.pop(k, None)
            else:
                env[k] = v
        return env

    def assign_words(self) -> list[str]:
        merged = {k: v for k, v in self.line.env.items() if v is not None}
        merged.update({k: v for k, v in self.env_local.items() if v is not None})
        return [f"{k}={v}" for k, v in merged.items()]


def analyse(command: str, shell: str = "bash", cwd=None, _line=None, _depth: int = 0) -> list[dict]:
    """Every destructive operation a command line would run, with the target each one hits."""
    if not isinstance(command, str) or not command.strip() or _depth > MAX_DEPTH:
        return []
    line = _line or _Line(cwd)
    start = line.copy()
    text, bodies, spans = _prepass(command, shell)
    items = split_commands(text, shell)
    if items is None:
        return []  # unbalanced quotes: the shell would not run it either
    ops, saved, prev = [], [], None
    for it in items:
        if it == "(":
            saved.append(line.copy())
            prev = None
        elif it == ")":
            if saved:
                line = saved.pop()
            prev = None
        else:
            ops += _command(it, prev, line, bodies, shell, _depth)
            prev = it
    body_spans = [sp for body, expands in bodies.values() if expands for sp in _prepass(body, shell, body=True)[2]]
    for span in spans + body_spans:
        sub = start.copy()
        if line.moved[0]:
            sub.cwd = None
        ops += analyse(span, shell, None, sub, _depth + 1)
    seen, out = set(), []
    for op in ops:
        key = (op["label"], json.dumps(op["targets"], sort_keys=True), op["problem"], op["cwd"])
        if key not in seen:
            seen.add(key)
            out.append(op)
    return out


def _cd_target(tool: str, args: list[str]):
    """The directory a cd-like command goes to: a path, '' for home, None when unknown."""
    rest = list(args)
    while rest:
        a = rest[0]
        if a.lower() in ("-path", "-literalpath") and len(rest) > 1:
            return rest[1]
        if a == "--":
            rest = rest[1:]
            break
        if a.startswith("-") and a != "-" or a.lower() == "/d":
            rest = rest[1:]
            continue
        break
    if not rest:
        return ""
    if rest[0] == "-" or re.fullmatch(r"[+-]\d+", rest[0]):
        return None  # the previous directory, or a place on the directory stack
    return rest[0]


def _command(it, prev, line: _Line, bodies, shell: str, depth: int) -> list[dict]:
    words = list(it["words"])
    while words and words[0] in KEYWORDS:
        words.pop(0)
    if not words:
        return []
    m = re.fullmatch(r"\$env:([A-Za-z_][A-Za-z0-9_]*)(?:=(.*))?", words[0], re.S | re.I)
    if m:  # PowerShell: $env:NAME = value
        value = m.group(2) if m.group(2) is not None else (words[2] if len(words) > 2 and words[1] == "=" else None)
        if value is not None:
            line.env[m.group(1)] = value
        return []
    env_local, cwd, cleared, stdin_args, i = {}, line.cwd, False, False, 0
    while i < len(words):
        w = words[i]
        m = ASSIGN.fullmatch(w)
        if m:
            env_local[m.group(1)] = m.group(2)
            i += 1
            continue
        name = _basename(w)
        if name not in WRAPPERS:
            break
        i += 1
        takes = WRAPPERS[name]
        while i < len(words) and words[i].startswith("-") and len(words[i]) > 1:
            key, eq, val = words[i].partition("=")
            if key in takes and not eq:
                val = words[i + 1] if i + 1 < len(words) else ""
                i += 1
            if (name == "env" and key in ("-C", "--chdir")) or (name == "sudo" and key in ("-D", "--chdir")):
                cwd = _join(cwd, val)
            elif name == "env" and key in ("-i", "--ignore-environment"):
                cleared = True
            elif name == "env" and key in ("-u", "--unset"):
                env_local[val] = None
            i += 1
        if name == "timeout" and i < len(words) and re.fullmatch(r"[0-9.]+[smhd]?", words[i]):
            i += 1  # the duration
        if name == "xargs":
            stdin_args = True
    if i >= len(words):
        for k, v in env_local.items():  # `NAME=value` alone: exported only if it already was
            if v is None:
                continue
            if k in line.env or k in os.environ:
                line.env[k] = v
            else:
                line.vars[k] = v
        return []
    exe, args = words[i], words[i + 1:]
    tool = _basename(exe)
    ctx = _Ctx(line, cwd, env_local, cleared, stdin_args, exe, words[i:], shell)

    if tool in CD:
        target = _cd_target(tool, args)
        line.cwd = None if target is None else _join(line.cwd, target or "~")
        line.moved[0] = True
        return []
    if tool in ("export", "unset") or (tool == "set" and shell == "cmd"):  # cmd.exe's `set NAME=value` exports
        for a in args:
            m = ASSIGN.fullmatch(a)
            if tool == "unset" and not a.startswith("-"):
                line.env[a] = None
            elif m and tool != "unset":
                line.env[m.group(1)] = m.group(2)
            elif tool == "export" and a in line.vars:
                line.env[a] = line.vars[a]
        return []

    stdin = _stdin_texts(it, prev, bodies)
    nested = _nested_scripts(tool, args, stdin, shell)
    if nested is not None:
        ops = []
        child = line.copy()
        child.cwd = cwd
        child.env.update(env_local)
        for script, sh in nested:
            ops += analyse(script, sh, None, child.copy(), depth + 1)
        return ops
    parser = PARSERS.get(tool)
    if parser is None:
        return []
    return parser(ctx, tool, args, stdin)


def _stdin_texts(it, prev, bodies) -> list[str]:
    """What a command reads on standard input, when the line itself spells it out."""
    texts = []
    for op, target in it["redirects"]:
        if op == "<<" and target in bodies:
            texts.append(bodies[target][0])
        elif op == "<<<":
            texts.append(target)
    if it["piped"] and isinstance(prev, dict) and prev["words"]:
        first, rest = _basename(prev["words"][0]), prev["words"][1:]
        if first == "echo":
            texts.append(" ".join(a for a in rest if not re.fullmatch(r"-[neE]+", a)))
        elif first == "printf" and rest:
            texts.append(rest[0].replace("\\n", "\n"))
    return texts


def _nested_scripts(tool: str, args: list[str], stdin: list[str], shell: str):
    """Command lines a shell, eval or cmd /c will run: [(script, shell)], or None if `tool` runs none."""
    if tool in SHELLS:
        j = 0
        while j < len(args) and args[j].startswith(("-", "+")) and args[j] not in ("-", "--"):
            a = args[j]
            if a in ("-o", "+o", "-O", "+O", "--rcfile", "--init-file"):
                j += 2
                continue
            if not a.startswith("--") and "c" in a[1:]:
                return [(args[j + 1], "bash")] if j + 1 < len(args) else []
            j += 1
        if j < len(args) and args[j] not in ("-", "--"):
            return []  # a script file: not read
        return [(t, "bash") for t in stdin]
    if tool in PWSH:
        for j, a in enumerate(args):
            low = a.lower()
            if low in ("-c", "-command", "/c", "/command", "-com", "-comm", "-comma", "-comman"):
                rest = args[j + 1:]
                return [(rest[0] if len(rest) == 1 else shlex.join(rest), "powershell")] if rest else []
            if low in ("-f", "-file", "-encodedcommand", "-enc", "-e", "-ec"):
                return []  # a script file, or base64 destroy-guard does not decode
        return [(t, "powershell") for t in stdin]
    if tool == "cmd":
        j = 0
        while j < len(args) and args[j].startswith("/") and args[j].lower() not in ("/c", "/k"):
            j += 1
        if j < len(args) and args[j].lower() in ("/c", "/k"):
            rest = args[j + 1:]
            return [(rest[0] if len(rest) == 1 else shlex.join(rest), "cmd")] if rest else []
        return []
    if tool in EVAL:
        return [(" ".join(args), shell)] if args else []  # eval joins its words with spaces and parses again
    return None


# ---------------------------------------------------------------- flags

def _pflags(args: list[str], value_flags: set):
    """GNU/pflag-style options: --flag=v, --flag v, -f v, -fv, bundled -Ai. Returns ({flag: [values]}, positionals).

    A value of None marks a flag given without one.
    """
    flags, pos, i = {}, [], 0
    while i < len(args):
        a = args[i]
        if a == "--":
            pos += args[i + 1:]
            break
        if a.startswith("--") and len(a) > 2:
            name, eq, val = a.partition("=")
            if not eq and name in value_flags:
                val, eq = (args[i + 1] if i + 1 < len(args) else ""), "="
                i += 1
            flags.setdefault(name, []).append(val if eq else None)
        elif a.startswith("-") and len(a) > 1:
            short = a[:2]
            if short in value_flags:
                if len(a) > 2:
                    val = a[3:] if a[2] == "=" else a[2:]
                else:
                    val = args[i + 1] if i + 1 < len(args) else ""
                    i += 1
                flags.setdefault(short, []).append(val)
            else:
                for ch in a[1:]:
                    flags.setdefault("-" + ch, []).append(None)
        else:
            pos.append(a)
        i += 1
    return flags, pos


def _go_flags(args: list[str], value_flags: set):
    """Go `flag` package options, as Terraform takes them: -flag, --flag, -flag=v, -flag v."""
    flags, pos, i = {}, [], 0
    while i < len(args):
        a = args[i]
        if a == "--":
            pos += args[i + 1:]
            break
        if a.startswith("-") and len(a) > 1:
            name, eq, val = a.lstrip("-").partition("=")
            if not eq and "-" + name in value_flags and i + 1 < len(args):
                val, eq = args[i + 1], "="
                i += 1
            flags.setdefault(name, []).append(val if eq else None)
        else:
            pos.append(a)
        i += 1
    return flags, pos


def _last(flags: dict, *names):
    vals = [v for n in names for v in flags.get(n, [])]
    return vals[-1] if vals else None


def _all(flags: dict, *names) -> list:
    return [v for n in names for v in flags.get(n, []) if v is not None]


def _has(flags: dict, *names) -> bool:
    return any(n in flags for n in names)


def _true(flags: dict, name: str) -> bool:
    vals = flags.get(name)
    return bool(vals) and (vals[-1] is None or vals[-1].lower() in ("true", "1", "t"))


def _op(ctx: _Ctx, tool: str, label: str, what: str, targets=(), problem=None, auto=True, plan=None,
        extra_assign=()) -> dict:
    return {"tool": tool, "label": label, "what": what, "targets": [] if problem else list(targets),
            "problem": problem, "auto": bool(auto and not problem and targets), "manual": not auto,
            "cwd": ctx.cwd, "exe": ctx.exe,
            "words": list(ctx.words), "assign": ctx.assign_words() + list(extra_assign), "plan": plan or {},
            "shell": ctx.shell}


def _q(s) -> str:
    return json.dumps(str(s), ensure_ascii=False)


# ---------------------------------------------------------------- Terraform and OpenTofu

TF_VALUE = {"-target", "-replace", "-var", "-var-file", "-lock-timeout", "-parallelism", "-state", "-state-out",
            "-backup", "-out", "-exclude", "-generate-config-out"}
TF_NAMES = {"terraform": "Terraform", "tofu": "OpenTofu"}


def _terraform(ctx: _Ctx, tool: str, args: list[str], stdin) -> list[dict]:
    chdir, i = None, 0
    while i < len(args) and args[i].startswith("-"):
        name, eq, val = args[i].lstrip("-").partition("=")
        if name == "chdir":
            if not eq:
                val = args[i + 1] if i + 1 < len(args) else ""
                i += 1
            chdir = val
        elif name in ("help", "h", "version", "v"):
            return []
        i += 1
    if i >= len(args):
        return []
    sub, rest = args[i], args[i + 1:]
    d = _join(ctx.cwd, chdir)
    if sub == "workspace":
        if rest[:1] and rest[0] in ("select", "new"):
            _, pos = _go_flags(rest[1:], set())
            if pos and d:
                ctx.line.tf_ws[d] = pos[0]
        return []
    if sub == "state":
        if rest[:1] != ["rm"]:
            return []
        flags, _ = _go_flags(rest[1:], TF_VALUE)
        if _true(flags, "dry-run"):
            return []
        action = "state rm"
    else:
        flags, pos = _go_flags(rest, TF_VALUE)
        if sub == "plan":
            if _true(flags, "destroy") and flags.get("out") and flags["out"][-1] and d:
                ctx.line.plans.add(os.path.normpath(os.path.join(d, flags["out"][-1])))
            return []
        if sub == "destroy":
            action = "destroy"
        elif sub == "apply" and _true(flags, "destroy"):
            action = "apply -destroy"
        elif sub == "apply" and pos and d and os.path.normpath(os.path.join(d, pos[0])) in ctx.line.plans:
            action = "apply"  # of a plan this line made with `plan -destroy`
        else:
            return []
    if _has(flags, "help", "h"):
        return []
    label, product = f"{tool} {action}", TF_NAMES[tool]
    problem, ws, from_line = None, None, False
    if chdir is not None and d is None:
        problem = "its -chdir directory comes from a shell expression, so destroy-guard cannot match a backup to it."
    elif d is None:
        problem = "destroy-guard cannot tell which directory it runs in (after a cd it cannot follow)."
    elif _has(flags, "state"):
        problem = ("it names a state file with -state; destroy-guard backs up the state of the configured"
                   " backend only.")
    else:
        env = ctx.env()
        ws = env.get("TF_WORKSPACE")
        if not ws and d in ctx.line.tf_ws:
            ws, from_line = ctx.line.tf_ws[d], True
        if not ws:
            data_dir = env.get("TF_DATA_DIR") or ".terraform"
            ws = _read_small(Path(d) / data_dir / "environment", 4096).strip() or "default"
        if DYNAMIC.search(ws):
            problem = "its workspace comes from a shell expression, so destroy-guard cannot match a backup to it."
    real = os.path.realpath(d) if d else ""
    scope = f"the {product} state of {real} (workspace {_q(ws)})" if not problem else f"what the {product} state tracks"
    what = f"removes entries from {scope}; the resources themselves stay" if action == "state rm" \
        else f"destroys everything in {scope}"
    target = {"tool": tool, "dir": real, "workspace": ws}
    extra = [f"TF_WORKSPACE={ws}"] if from_line else []
    return [_op(ctx, tool, label, what, [target], problem, plan={"dir": real, "workspace": ws}, extra_assign=extra)]


# ---------------------------------------------------------------- Kubernetes

KUBE_CONN = {"--context", "--cluster", "--kubeconfig", "--user", "-s", "--server", "--token", "--as", "--as-group",
             "--as-uid", "--certificate-authority", "--client-certificate", "--client-key", "--request-timeout",
             "--tls-server-name", "--cache-dir", "--username", "--password"}
KUBE_VALUE = KUBE_CONN | {"-n", "--namespace", "-v", "--v", "--vmodule", "--log-file", "--log-dir", "--profile",
                          "--profile-output", "-f", "--filename", "-k", "--kustomize", "-l", "--selector",
                          "--field-selector", "--grace-period", "--timeout", "-o", "--output", "--raw",
                          "--template", "--chunk-size"}
# canonical resource -> (Kind, cluster-scoped, other names kubectl accepts)
KINDS = {
    "pods": ("Pod", False, "po pod"), "deployments": ("Deployment", False, "deploy deployment"),
    "services": ("Service", False, "svc service"), "namespaces": ("Namespace", True, "ns namespace"),
    "configmaps": ("ConfigMap", False, "cm configmap"), "secrets": ("Secret", False, "secret"),
    "statefulsets": ("StatefulSet", False, "sts statefulset"), "daemonsets": ("DaemonSet", False, "ds daemonset"),
    "replicasets": ("ReplicaSet", False, "rs replicaset"), "jobs": ("Job", False, "job"),
    "cronjobs": ("CronJob", False, "cj cronjob"), "ingresses": ("Ingress", False, "ing ingress"),
    "persistentvolumeclaims": ("PersistentVolumeClaim", False, "pvc persistentvolumeclaim"),
    "persistentvolumes": ("PersistentVolume", True, "pv persistentvolume"),
    "serviceaccounts": ("ServiceAccount", False, "sa serviceaccount"),
    "customresourcedefinitions": ("CustomResourceDefinition", True, "crd crds customresourcedefinition"),
    "horizontalpodautoscalers": ("HorizontalPodAutoscaler", False, "hpa horizontalpodautoscaler"),
    "poddisruptionbudgets": ("PodDisruptionBudget", False, "pdb poddisruptionbudget"),
    "networkpolicies": ("NetworkPolicy", False, "netpol networkpolicy"), "roles": ("Role", False, "role"),
    "rolebindings": ("RoleBinding", False, "rolebinding"), "clusterroles": ("ClusterRole", True, "clusterrole"),
    "clusterrolebindings": ("ClusterRoleBinding", True, "clusterrolebinding"),
    "storageclasses": ("StorageClass", True, "sc storageclass"), "nodes": ("Node", True, "no node"),
    "endpoints": ("Endpoints", False, "ep"),
}
KIND_ALIASES = {a: k for k, (_, _, names) in KINDS.items() for a in names.split() + [k]}
BUILTIN_GROUPS = {"", "core", "apps", "batch", "networking.k8s.io", "policy", "rbac.authorization.k8s.io",
                  "storage.k8s.io", "autoscaling", "apiextensions.k8s.io"}


def kind_of(resource: str) -> str:
    """`deploy`, `deployment.apps`, `Deployments` -> `deployments`; anything else, lower-cased as given."""
    r = resource.lower()
    head, _, group = r.partition(".")
    group = re.sub(r"^v\d+(?:(?:alpha|beta)\d+)?\.?", "", group)
    if head in KIND_ALIASES and group in BUILTIN_GROUPS:
        return KIND_ALIASES[head]
    return r


def kube_context(ctx: _Ctx, context_flag, kubeconfig_flag, env_context: str = ""):
    """(context, kubeconfig paths, problem). Of a kubeconfig only `current-context` is read."""
    env = ctx.env()
    if kubeconfig_flag is not None:
        files = [kubeconfig_flag]
    elif env.get("KUBECONFIG"):
        files = [f for f in env["KUBECONFIG"].split(os.pathsep) if f]
    else:
        files = [os.path.join(os.path.expanduser("~"), ".kube", "config")]
    paths = [_join(ctx.cwd, f) for f in files]
    if any(p is None for p in paths):
        return "", "", "its kubeconfig path comes from a shell expression or an unknown directory."
    kubeconfig = os.pathsep.join(os.path.realpath(p) for p in paths)
    context = context_flag if context_flag is not None else env.get(env_context) if env_context else None
    if context is not None:
        if not context or DYNAMIC.search(context):
            return "", kubeconfig, "its context comes from a shell expression, so destroy-guard cannot match a backup."
        return context, kubeconfig, None
    for p in paths:
        text = _read_small(p)
        m = re.search(r"(?m)^current-context:[ \t]*(.*?)[ \t]*$", text) or \
            re.search(r'"current-context"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
        if m and m.group(1).strip("'\""):
            return m.group(1).strip("'\""), kubeconfig, None
    return "", kubeconfig, None


def _where(ns_id: str, context: str) -> str:
    ns = {"*": "in every namespace", "-": "", "": "in the context's default namespace"}.get(ns_id, f"in namespace {ns_id}")
    return (f" {ns}" if ns else "") + (f", context {context}" if context else ", no kubeconfig context found")


def _kubectl(ctx: _Ctx, tool: str, args: list[str], stdin) -> list[dict]:
    flags, pos = _pflags(args, KUBE_VALUE)
    if not pos or pos[0] != "delete" or _has(flags, "-h", "--help"):
        return []
    dry = flags.get("--dry-run")
    if dry is not None and (dry[-1] is None or dry[-1].lower() in ("client", "server", "true", "unchanged")):
        return []
    label = "kubectl delete"
    context, kubeconfig, problem = kube_context(ctx, _last(flags, "--context"), _last(flags, "--kubeconfig"))
    conn = [f"{k}={v}" for k in sorted(KUBE_CONN - {"--context", "--kubeconfig"}) for v in _all(flags, k)]
    base = {"tool": "kubectl", "context": context, "kubeconfig": kubeconfig}
    for k in ("--server", "-s", "--cluster", "--user", "--as"):
        if _last(flags, k) is not None:
            base[k.lstrip("-")] = mask_text(_last(flags, k))
    ns = _last(flags, "-n", "--namespace")
    all_ns = _has(flags, "-A", "--all-namespaces")
    ns_id = "*" if all_ns else (ns or "")
    if ns and DYNAMIC.search(ns):
        problem = problem or "its namespace comes from a shell expression, so destroy-guard cannot match a backup."
    plan = {"context": context, "kubeconfig": _last(flags, "--kubeconfig"), "conn": conn,
            "namespace": ns, "all_namespaces": all_ns}
    res = pos[1:]
    files, kust = _all(flags, "-f", "--filename"), _last(flags, "-k", "--kustomize")
    selector, fsel, every = _last(flags, "-l", "--selector"), _last(flags, "--field-selector"), _has(flags, "--all")
    if _last(flags, "--raw") is not None:
        return [_op(ctx, tool, label, "deletes a raw API path", problem="it deletes a raw API path (--raw); destroy-guard"
                    " makes backups of named objects, selectors and manifest files only.")]
    if ctx.stdin_args:
        return [_op(ctx, tool, label, "deletes objects named on standard input", problem="it takes the names from standard"
                    " input (xargs), so destroy-guard cannot tell which objects it deletes.")]
    if files or kust:
        if "-" in files:
            return [_op(ctx, tool, label, "deletes objects read from standard input", problem="it reads the objects to delete"
                        " from standard input, so destroy-guard cannot tell which objects they are.")]
        entries = []
        for f in files + ([kust] if kust else []):
            if re.match(r"https?://", f):
                entries.append({"url": mask_url(f)})
                continue
            p = _join(ctx.cwd, f)
            if p is None:
                problem = problem or "a manifest path comes from a shell expression or an unknown directory."
                break
            entries.append({"path": os.path.realpath(p), "sha256": fingerprint(p, manifests_only=f != kust)})
        target = dict(base, namespace=ns_id, files=entries, kustomize=bool(kust),
                      recursive=_has(flags, "-R", "--recursive"))
        shown = ", ".join(e.get("path") or e.get("url", "") for e in entries)
        plan.update(mode="files", files=files, kustomize=kust, recursive=_has(flags, "-R", "--recursive"))
        return [_op(ctx, tool, label, f"deletes the objects defined in {shown}{_where(ns_id, context)}", [target], problem,
                    plan=plan)]
    if not res:
        return []  # kubectl refuses a delete that names nothing
    if any("/" in r for r in res):
        if not all("/" in r for r in res):
            return []  # kubectl refuses TYPE/NAME mixed with other arguments
        pairs = [tuple(r.split("/", 1)) for r in res]
    else:
        types, names = res[0].split(","), res[1:]
        if not names:
            if not (selector or fsel or every):
                return []  # kubectl refuses: no name, selector or --all
            if any(DYNAMIC.search(x) for x in [selector or "", fsel or ""] + types):
                problem = problem or "its selector comes from a shell expression, so destroy-guard cannot match a backup."
            kinds = ",".join(sorted(kind_of(t) for t in types))
            target = dict(base, namespace=ns_id, kinds=kinds, selector=(selector or "").replace(" ", ""),
                          field_selector=(fsel or "").replace(" ", ""), all=bool(every))
            how = f"-l {selector}" if selector else f"--field-selector {fsel}" if fsel else "--all"
            plan.update(mode="group", resources=res[0], selector=selector, field_selector=fsel)
            return [_op(ctx, tool, label, f"deletes every {kinds} matching {how}{_where(ns_id, context)}", [target],
                        problem, plan=plan)]
        if selector or fsel:
            return []  # kubectl refuses names together with a selector
        pairs = [(t, n) for t in types for n in names]
    targets, objects, shown = [], [], []
    for resource, name in pairs:
        if DYNAMIC.search(resource + name) or not name:
            problem = problem or "an object name comes from a shell expression, so destroy-guard cannot match a backup."
            break
        kind = kind_of(resource)
        scoped = KINDS.get(kind, ("", False, ""))[1]
        obj_ns = "-" if scoped else ns_id
        t = dict(base, kind=kind, name=name, namespace=obj_ns)
        if t not in targets:
            targets.append(t)
            objects.append({"resource": resource, "kind": kind, "name": name, "cluster_scoped": scoped})
            if kind == "namespaces":
                shown.append(f"namespace {name} and everything in it")
            elif kind == "customresourcedefinitions":
                shown.append(f"the resource type {name} and every object of that type")
            else:
                shown.append(f"{kind}/{name}")
    where = _where(ns_id if any(not o["cluster_scoped"] for o in objects) else "-", context)
    plan.update(mode="objects", objects=objects)
    return [_op(ctx, tool, label, "deletes " + ", ".join(shown) + where, targets, problem, plan=plan)]


def fingerprint(path, manifests_only: bool = False) -> str:
    """SHA-256 over a manifest file, or over the files under a directory (names and contents), bounded.

    For `kubectl delete -f <dir>` only .json, .yaml and .yml files count, the ones kubectl reads;
    a kustomization (-k) can pull in any file, so there every file counts.
    """
    p = Path(path)
    h = hashlib.sha256()
    try:
        if p.is_file():
            if p.stat().st_size > FINGERPRINT_LIMIT[1]:
                return "too-large"
            h.update(p.read_bytes())
            return h.hexdigest()
        if not p.is_dir():
            return "missing"
        files, total = 0, 0
        for root, dirs, names in os.walk(p):
            dirs[:] = sorted(d for d in dirs if not d.startswith("."))
            for n in sorted(names):
                f = Path(root) / n
                if not f.is_file() or (manifests_only and not n.lower().endswith((".json", ".yaml", ".yml"))):
                    continue
                files += 1
                total += f.stat().st_size
                if files > FINGERPRINT_LIMIT[0] or total > FINGERPRINT_LIMIT[1]:
                    return "too-large"
                h.update(f.relative_to(p).as_posix().encode("utf-8") + b"\0" + f.read_bytes() + b"\0")
        return h.hexdigest()
    except OSError:
        return "unreadable"


# ---------------------------------------------------------------- Helm

HELM_CONN = {"--kube-context", "--kubeconfig", "--kube-apiserver", "--kube-as-user", "--kube-as-group",
             "--kube-ca-file", "--kube-token", "--kube-tls-server-name", "--registry-config",
             "--repository-cache", "--repository-config", "--burst-limit", "--qps", "--content-cache"}
HELM_VALUE = HELM_CONN | {"-n", "--namespace", "--cascade", "--description", "--timeout"}


def _helm(ctx: _Ctx, tool: str, args: list[str], stdin) -> list[dict]:
    flags, pos = _pflags(args, HELM_VALUE)
    if not pos or pos[0] not in ("uninstall", "delete", "del", "un") or _has(flags, "-h", "--help"):
        return []
    dry = flags.get("--dry-run")
    if dry is not None and (dry[-1] is None or dry[-1].lower() != "false"):
        return []
    releases = pos[1:]
    if not releases:
        return []
    env = ctx.env()
    context, kubeconfig, problem = kube_context(ctx, _last(flags, "--kube-context"), _last(flags, "--kubeconfig"),
                                                "HELM_KUBECONTEXT")
    ns = _last(flags, "-n", "--namespace") or env.get("HELM_NAMESPACE") or ""
    if ns and DYNAMIC.search(ns) or any(DYNAMIC.search(r) for r in releases):
        problem = problem or "its release or namespace comes from a shell expression, so destroy-guard cannot match a backup."
    base = {"tool": "helm", "context": context, "kubeconfig": kubeconfig, "namespace": ns}
    if _last(flags, "--kube-apiserver") is not None:
        base["server"] = mask_text(_last(flags, "--kube-apiserver"))
    targets = []
    for r in releases:
        if dict(base, release=r) not in targets:
            targets.append(dict(base, release=r))
    conn = [f"{k}={v}" for k in sorted(HELM_CONN - {"--kube-context", "--kubeconfig"}) for v in _all(flags, k)]
    plan = {"context": context, "kubeconfig": _last(flags, "--kubeconfig"), "namespace": ns, "conn": conn,
            "releases": [t["release"] for t in targets]}
    label = f"helm {pos[0]}"
    names = ", ".join(t["release"] for t in targets)
    return [_op(ctx, tool, label, f"uninstalls release {names}{_where(ns, context)}", targets, problem, plan=plan)]


# ---------------------------------------------------------------- git

GIT_GLOBAL_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env",
                    "--super-prefix"}
GIT_PUSH_VALUE = {"--repo", "--receive-pack", "--exec", "-o", "--push-option"}
SHA = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")


def work_tree(start) -> Path | None:
    """The nearest directory at or above `start` that holds a .git entry."""
    if not start:
        return None
    p = Path(os.path.abspath(start))
    for d in [p, *p.parents]:
        if os.path.lexists(d / ".git"):
            return d
    return None


def git_dirs(top: Path):
    """(git dir, common dir) of a work tree; .git is a file in worktrees and submodules."""
    dotgit = top / ".git"
    if dotgit.is_dir():
        gitdir = dotgit
    else:
        m = re.match(r"gitdir:\s*(.+)", _read_small(dotgit, 4096).strip())
        if not m:
            return None, None
        gitdir = Path(m.group(1).strip())
        if not gitdir.is_absolute():
            gitdir = top / gitdir
    common = gitdir
    c = _read_small(gitdir / "commondir", 4096).strip()
    if c:
        common = Path(c) if os.path.isabs(c) else gitdir / c
    return Path(os.path.normpath(gitdir)), Path(os.path.normpath(common))


def git_config(common: Path) -> dict:
    """The keys destroy-guard needs from a repository's own config (branch remotes, push defaults); nothing else is kept."""
    keep, section = {}, ""
    for raw in _read_small(common / "config").splitlines():
        s = raw.strip()
        if not s or s[0] in "#;":
            continue
        m = re.fullmatch(r'\[\s*([A-Za-z0-9.-]+)(?:\s+"((?:[^"\\]|\\.)*)")?\s*\]', s)
        if m:
            section = m.group(1).lower() + ("." + m.group(2) if m.group(2) is not None else "")
            continue
        m = re.fullmatch(r"([A-Za-z][A-Za-z0-9-]*)\s*(?:=\s*(.*))?", s)
        if not m or not section:
            continue
        key = f"{section}.{m.group(1).lower()}"
        wanted = key in ("remote.pushdefault", "push.default") or (
            key.startswith("branch.") and key.rsplit(".", 1)[1] in ("remote", "pushremote", "merge"))
        if wanted:
            val = re.sub(r"\s+[#;].*$", "", (m.group(2) or "").strip())
            keep[key] = val[1:-1] if len(val) > 1 and val[0] == val[-1] == '"' else val
    return keep


def current_branch(gitdir: Path):
    m = re.fullmatch(r"ref:\s*refs/heads/(.+)", _read_small(gitdir / "HEAD", 4096).strip())
    return m.group(1) if m else None


def _full_ref(name: str) -> str:
    return name if name.startswith("refs/") else f"refs/heads/{name}"


def _remote_id(remote: str, git_cwd: str) -> str:
    """A remote as it goes into a target: a name as is, a URL masked, a local path made absolute."""
    if re.match(r"[A-Za-z][A-Za-z0-9+.-]*://", remote):
        return mask_url(remote)
    if re.fullmatch(r"[^/\\:]+@[^/\\:]+:.*", remote) or re.fullmatch(r"[A-Za-z0-9._-]+", remote):
        return remote  # scp-like git@host:path, or a configured remote's name
    return os.path.realpath(os.path.join(git_cwd, os.path.expanduser(remote)))


def _git(ctx: _Ctx, tool: str, args: list[str], stdin) -> list[dict]:
    git_cwd, i, other_repo = ctx.cwd, 0, False
    while i < len(args) and args[i].startswith("-"):
        key, eq, val = args[i].partition("=")
        if key in GIT_GLOBAL_VALUE and not eq:
            val = args[i + 1] if i + 1 < len(args) else ""
            i += 1
        if key == "-C":
            git_cwd = _join(git_cwd, val)
        elif key in ("--git-dir", "--work-tree"):
            other_repo = True
        i += 1
    if i >= len(args) or args[i] != "push":
        return []
    rest = args[i + 1:]
    force = delete = dry = False
    many, repo_flag, pos, j = [], None, [], 0
    while j < len(rest):
        a = rest[j]
        key, eq, val = a.partition("=")
        if a == "--":
            pos += rest[j + 1:]
            break
        if key in ("--force", "--force-with-lease"):
            force = True
        elif key == "--delete":
            delete = True
        elif key in ("--dry-run", "--help"):
            dry = True
        elif key in ("--mirror", "--prune", "--all", "--branches", "--tags"):
            many.append(key)
            force |= key == "--mirror"  # a mirror push force-updates and deletes to match
            delete |= key == "--prune"
        elif key == "--repo":
            repo_flag = val if eq else (rest[j + 1] if j + 1 < len(rest) else "")
            j += 0 if eq else 1
        elif key in GIT_PUSH_VALUE:
            j += 0 if eq else 1
        elif a.startswith("--"):
            pass
        elif a.startswith("-") and len(a) > 1:
            letters = a[1:]
            force |= "f" in letters
            delete |= "d" in letters
            dry |= "n" in letters or "h" in letters
            if letters.endswith("o"):
                j += 1  # -o takes the next word as its value
        else:
            pos.append(a)
        j += 1
    if dry:
        return []
    remote = repo_flag or (pos[0] if pos else None)
    specs = pos[1:] if pos else []
    marked = [s for s in specs if s.startswith("+") or (s.startswith(":") and len(s) > 1)]
    if not (force or delete or marked):
        return []
    deleting = (delete or any(s.startswith(":") for s in marked)) and not force
    label = "git push --delete" if deleting else "git push --force"
    if many:
        return [_op(ctx, tool, label, "rewrites many refs at once", problem=f"it uses {', '.join(many)}, which can overwrite or"
                    " delete many refs; destroy-guard makes backups of single branches only.", auto=False)]
    top = work_tree(git_cwd)
    if git_cwd is None or top is None or other_repo:
        return [_op(ctx, tool, label, "rewrites a branch on a remote", problem="destroy-guard cannot tell which repository it"
                    " pushes from (a cd, -C or --git-dir it cannot follow).")]
    gitdir, common = git_dirs(top)
    cfg = git_config(common) if common else {}
    branch = current_branch(gitdir) if gitdir else None
    detached = _op(ctx, tool, label, "rewrites the current branch on its remote", problem="HEAD is detached, so destroy-guard cannot tell"
                   " which branch it pushes.")
    if remote is None:
        if branch is None:
            return [detached]
        remote = (cfg.get(f"branch.{branch}.pushremote") or cfg.get("remote.pushdefault")
                  or cfg.get(f"branch.{branch}.remote") or "origin")
    if DYNAMIC.search(remote) or any(DYNAMIC.search(s) for s in specs):
        return [_op(ctx, tool, label, "rewrites a branch on a remote", problem="its remote or branch comes from a shell"
                    " expression, so destroy-guard cannot match a backup.")]
    if delete and not specs:
        return []  # git refuses --delete without a ref
    refs = []
    for s in (specs if (force or delete) else marked) or [None]:
        if s is None:  # no refspec: the current branch, the way push.default says
            if branch is None:
                return [detached]
            mode = cfg.get("push.default", "simple").lower()
            if mode == "nothing":
                return []
            if mode == "matching":
                return [_op(ctx, tool, label, "rewrites every matching branch", problem="push.default is `matching`, so it"
                            " pushes every branch that exists on both sides; destroy-guard makes backups of single"
                            " branches only.", auto=False)]
            merge = cfg.get(f"branch.{branch}.merge")
            dst = merge if mode in ("upstream", "tracking") and merge else f"refs/heads/{branch}"
        else:
            src, colon, dst = s.lstrip("+").partition(":")
            if not colon:
                dst = src
            if dst == "HEAD":
                if branch is None:
                    return [detached]
                dst = branch
            if not dst or "*" in dst or SHA.fullmatch(dst):
                return [_op(ctx, tool, label, "rewrites refs on a remote", problem="its refspec names no single branch, so"
                            " destroy-guard cannot match a backup.")]
            dst = _full_ref(dst)
        if dst not in refs:
            refs.append(dst)
    rid = _remote_id(remote, git_cwd)
    real_top = os.path.realpath(top)
    targets = [{"tool": "git", "repo": real_top, "remote": rid, "ref": r} for r in refs]
    shown = ", ".join(refs)
    plan = {"git_cwd": git_cwd, "remote": remote, "refs": refs, "repo": real_top}
    verb = "deletes" if deleting else "overwrites"
    return [_op(ctx, tool, label, f"{verb} {shown} on {mask_text(remote)} (repository {real_top})", targets, None,
                plan=plan)]


# ---------------------------------------------------------------- SQL

SQL_NOISE = re.compile(r"--[^\n]*|/\*.*?\*/|'(?:[^']|'')*'|\$([A-Za-z_][A-Za-z0-9_]*|)\$.*?\$\1\$|\"(?:[^\"]|\"\")*\"|`[^`]*`",
                       re.S)
SQL_DESTRUCTIVE = re.compile(r"(?i)\b(?:DROP\s+(?:(?:MATERIALIZED|FOREIGN)\s+)?(TABLE|DATABASE|SCHEMA|VIEW|INDEX|"
                             r"SEQUENCE|COLUMN|PARTITION|USER|ROLE|OWNED|TYPE|FUNCTION|PROCEDURE|TRIGGER|EXTENSION)"
                             r"|(TRUNCATE))\b")
PSQL_VALUE = {"-c", "--command", "-d", "--dbname", "-f", "--file", "-h", "--host", "-p", "--port", "-U",
              "--username", "-v", "--set", "--variable", "-P", "--pset", "-o", "--output", "-L", "--log-file",
              "-T", "--table-attr", "-F", "--field-separator", "-R", "--record-separator"}
MYSQL_VALUE = {"-e", "--execute", "-u", "--user", "-h", "--host", "-P", "--port", "-D", "--database", "-S", "--socket"}
SQL_MANUAL = ("destroy-guard has no automatic backup for databases in v1; a dump made with the database's own tool"
              " (pg_dump, mysqldump) before approving is the manual equivalent.")


def sql_destructive(text: str) -> set:
    """`DROP TABLE`, `TRUNCATE`, ... in SQL, outside string literals, quoted names and comments."""
    found = set()
    for m in SQL_DESTRUCTIVE.finditer(SQL_NOISE.sub(" ", text or "")):
        found.add("TRUNCATE" if m.group(2) else "DROP " + m.group(1).upper())
    return found


def _sql(ctx: _Ctx, tool: str, args: list[str], stdin) -> list[dict]:
    if tool == "dropdb":
        flags, pos = _pflags(args, {"-h", "--host", "-p", "--port", "-U", "--username", "--maintenance-db"})
        if not pos or _has(flags, "--help", "-?", "-V", "--version"):
            return []
        return [_op(ctx, "sql", "dropdb", f"drops the PostgreSQL database {pos[-1]}", problem=SQL_MANUAL, auto=False)]
    if tool == "mysqladmin":
        flags, pos = _pflags(args, MYSQL_VALUE)
        if "drop" not in [p.lower() for p in pos]:
            return []
        return [_op(ctx, "sql", "mysqladmin drop", "drops a MySQL database", problem=SQL_MANUAL, auto=False)]
    flags, _ = _pflags(args, PSQL_VALUE if tool == "psql" else MYSQL_VALUE)
    texts = _all(flags, "-c", "--command") if tool == "psql" else _all(flags, "-e", "--execute")
    found = set()
    for t in texts + list(stdin):
        found |= sql_destructive(t)
    if not found:
        return []
    what = ", ".join(sorted(found))
    return [_op(ctx, "sql", f"{tool} {what}", f"runs {what} on the database it connects to", problem=SQL_MANUAL,
                auto=False)]


PARSERS = {"terraform": _terraform, "tofu": _terraform, "kubectl": _kubectl, "helm": _helm, "git": _git,
           "psql": _sql, "mysql": _sql, "mariadb": _sql, "dropdb": _sql, "mysqladmin": _sql}
QUICK = re.compile(r"(?i)terraform|tofu|kubectl|helm|git|psql|mysql|mariadb|dropdb")


# ---------------------------------------------------------------- store and manifests

STAMP = re.compile(r"(\d{8}T\d{6}Z)-[0-9a-f]{12}(?:-\d+)?")
SAFE_FILE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,150}")


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def max_age() -> dt.timedelta:
    raw = os.environ.get(MAX_AGE_ENV, "")
    try:
        minutes = float(raw) if raw else DEFAULT_MAX_AGE_MINUTES
    except ValueError:
        minutes = DEFAULT_MAX_AGE_MINUTES
    if not 0 < minutes <= 7 * 24 * 60:
        minutes = DEFAULT_MAX_AGE_MINUTES
    return dt.timedelta(minutes=minutes)


def store_dir(start) -> Path:
    """.destroy-guard at the top of the git work tree holding `start`, else in `start`; DESTROY_GUARD_DIR overrides."""
    env = os.environ.get(STORE_ENV)
    if env:
        return Path(os.path.abspath(os.path.expanduser(env)))
    start = os.path.realpath(start or os.getcwd())
    return (work_tree(start) or Path(start)) / ".destroy-guard"


def _parse_utc(s):
    try:
        return dt.datetime.strptime(str(s), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def target_key(t: dict) -> str:
    return json.dumps(t, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def load_manifest(d: Path):
    """(manifest, created) for a backup directory that passes every check, else (None, why)."""
    try:
        st = os.lstat(d)
        if not stat.S_ISDIR(st.st_mode):
            return None, "not a directory"
        # git does not keep directory modes and another user cannot give us a 0700 directory,
        # so a checked-in or planted backup fails here.
        if os.name == "posix" and (st.st_mode & 0o077 or (hasattr(os, "getuid") and st.st_uid != os.getuid())):
            return None, "not private to this user"
        with open(d / "manifest.json", "rb") as f:
            raw = f.read(MAX_MANIFEST_BYTES + 1)
        if len(raw) > MAX_MANIFEST_BYTES:
            return None, "manifest too large"
        m = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError):
        return None, "no readable manifest"
    if not isinstance(m, dict) or m.get("format") != 1 or m.get("verified") is not True:
        return None, "not a verified manifest"
    created = _parse_utc(m.get("created_utc"))
    targets, exports = m.get("targets"), m.get("exports")
    if created is None or not isinstance(targets, list) or not isinstance(exports, list) or not exports:
        return None, "incomplete manifest"
    for e in exports:
        name = e.get("file") if isinstance(e, dict) else None
        if not isinstance(name, str) or not SAFE_FILE.fullmatch(name) or not isinstance(e.get("bytes"), int):
            return None, "bad export entry"
        try:
            if os.lstat(d / name).st_size != e["bytes"]:
                return None, f"{name} changed since the backup"
        except OSError:
            return None, f"{name} is missing"
    return m, created


def backups(store: Path):
    """Backup directories in a store, newest first, bounded."""
    root = store / "backups"
    try:
        names = [n for n in os.listdir(root) if STAMP.fullmatch(n)]
    except OSError:
        return []
    return [root / n for n in sorted(names, reverse=True)[:MAX_MANIFESTS]]


def _stores(op: dict) -> list[Path]:
    starts = [op["cwd"], op["plan"].get("dir"), op["plan"].get("repo")]
    out = []
    for s in starts:
        if s:
            p = store_dir(s)
            if p not in out:
                out.append(p)
    return out


def find_backup(op: dict, now=None, window=None) -> dict:
    """Whether fresh, verified backups cover every target of `op`: status covered or missing, and ages."""
    now = now or now_utc()
    window = window or max_age()
    wanted = {target_key(t) for t in op["targets"]}
    covered, newest, used = set(), None, []
    for store in _stores(op):
        for d in backups(store):
            m, created = load_manifest(d)
            if m is None:
                continue
            keys = {target_key(t) for t in m["targets"] if isinstance(t, dict)} & wanted
            if not keys:
                continue
            age = now - created
            newest = age if newest is None or age < newest else newest
            if -CLOCK_SKEW <= age <= window and not keys <= covered:
                covered |= keys
                used.append((d, age))
    ok = bool(wanted) and covered >= wanted
    return {"status": "covered" if ok else "missing", "backups": used if ok else [], "newest_age": newest}


def evaluate(command: str, shell: str = "bash", cwd=None, now=None) -> list[dict]:
    """Each destructive operation in `command`, with status covered, missing, unresolved or manual."""
    results = []
    for op in analyse(command, shell, cwd):
        if op["problem"]:
            results.append({"op": op, "status": "manual" if op["manual"] else "unresolved"})
        else:
            results.append(dict(find_backup(op, now), op=op))
    return results


def fmt_age(age: dt.timedelta) -> str:
    s = max(0, int(age.total_seconds()))
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min"
    if s < 86400:
        return f"{s // 3600} h {s % 3600 // 60} min"
    return f"{s // 86400} d {s % 86400 // 3600} h"


def _runner() -> str:
    import shutil
    if shutil.which("destroy-guard"):
        return "destroy-guard"
    return "python3 " + shlex.quote(str(Path(__file__).resolve()))


def _ps_quote(w: str) -> str:
    return w if re.fullmatch(r"[A-Za-z0-9_./:=@%+,\\-]+", w) else "'" + w.replace("'", "''") + "'"


def backup_command(op: dict, session_cwd=None, runner=None) -> str:
    """The one command that makes the backup `op` needs, masked for printing."""
    words = list(op["assign"]) + list(op["words"])
    shown = mask_words(words, _basename(op["exe"]), len(op["assign"]))
    quote = _ps_quote if op["shell"] == "powershell" else shlex.quote
    cwd = []
    if op["cwd"] and (not session_cwd or os.path.realpath(op["cwd"]) != os.path.realpath(session_cwd)):
        cwd = ["--cwd", op["cwd"]]
    return " ".join([runner or _runner(), "backup"] + [quote(w) for w in cwd] + ["--"]
                    + [w if "***" in w else quote(w) for w in shown])


def reason(results: list[dict], session_cwd=None, window=None) -> str | None:
    """The text for the permission prompt, or None when every operation is covered."""
    window = window or max_age()
    w = fmt_age(window)
    parts, data_note, missing = [], False, False
    for r in results:
        op = r["op"]
        if r["status"] == "covered":
            continue
        head = f"`{op['label']}` {op['what']}."
        if r["status"] == "missing":
            missing = True
            data_note |= op["tool"] != "git"
            age = r.get("newest_age")
            have = f"No backup of it from the last {w}." if age is None else (
                f"The newest backup of it is {fmt_age(age)} old.")
            parts.append(f"{head} {have} To make one, run `{backup_command(op, session_cwd)}` on its own first.")
        else:
            parts.append(f"{head} {op['problem']}")
    if not parts:
        return None
    text = "destroy-guard: " + " | ".join(parts)
    if data_note:
        text += " A backup holds state and object definitions, not the data inside databases or volumes."
    if missing:
        text += f" The {w} window is destroy-guard's own choice ({MAX_AGE_ENV} changes it)."
    return clean(mask_text(text + " Approving runs the command as it is."), MAX_REASON)


# ---------------------------------------------------------------- the backup CLI

class ExportError(Exception):
    def __init__(self, message: str, code: int = 1):
        super().__init__(message)
        self.code = code


def _private_dir(p: Path) -> bool:
    """Create `p` with mode 0700, or tighten it to 0700. True when it had to be tightened."""
    if os.path.islink(p):
        raise ExportError(f"{p} is a symbolic link; destroy-guard does not write backups through one", 2)
    p.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name != "posix":
        return False
    if stat.S_IMODE(os.stat(p).st_mode) != 0o700:
        os.chmod(p, 0o700)
        return True
    return False


def _write_private(path: Path, data: bytes):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return hashlib.sha256(data).hexdigest(), len(data)


def exclude_store(store: Path):
    """Add the store to .git/info/exclude of the work tree it sits in. Returns the exclude file, or None."""
    top = work_tree(store.parent)
    if top is None:
        return None
    _, common = git_dirs(top)
    if common is None:
        return None
    try:
        rel = store.resolve().relative_to(top.resolve()).as_posix()
    except ValueError:
        return None
    entry = f"/{rel}/"
    exclude = common / "info" / "exclude"
    existing = _read_small(exclude)
    if entry in (s.strip() for s in existing.splitlines()):
        return exclude
    exclude.parent.mkdir(parents=True, exist_ok=True)
    with open(exclude, "a", encoding="utf-8") as f:
        if existing and not existing.endswith("\n"):
            f.write("\n")
        f.write(f"# destroy-guard backups can contain secrets\n{entry}\n")
    return exclude


def prepare_store(store: Path) -> list[str]:
    """Create the store private and ignored by git. Returns notes for the person."""
    notes = []
    if _private_dir(store):
        notes.append(f"tightened {store} to mode 0700")
    _private_dir(store / "backups")
    ignore = store / ".gitignore"
    if not ignore.exists():
        ignore.write_text("# destroy-guard backups can contain secrets; nothing here belongs in git\n*\n",
                          encoding="utf-8")
    exclude = exclude_store(store)
    if exclude:
        notes.append(f"{store.name}/ is listed in {exclude}")
    return notes


def _run(argv: list[str], cwd, env, timeout=None):
    import subprocess
    timeout = timeout or EXPORT_TIMEOUT
    shown = " ".join(mask_words([_basename(argv[0])] + argv[1:]))
    try:
        p = subprocess.run(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout)
    except FileNotFoundError:
        raise ExportError(f"{argv[0]} was not found", 2) from None
    except subprocess.TimeoutExpired:
        raise ExportError(f"`{shown}` did not finish within {timeout} s") from None
    except OSError as e:
        raise ExportError(f"could not run `{shown}`: {e.strerror}", 2) from None
    return p.returncode, p.stdout, p.stderr.decode("utf-8", "replace"), shown


def _ok(argv, cwd, env, timeout=None) -> bytes:
    rc, out, err, shown = _run(argv, cwd, env, timeout)
    if rc != 0:
        tail = clean(mask_text(" ".join(err.strip().splitlines()[-3:])), 240)
        raise ExportError(f"`{shown}` exited with {rc}" + (f": {tail}" if tail else ""))
    return out


def _json(out: bytes, shown: str):
    if not out.strip():
        raise ExportError(f"`{shown}` printed nothing")
    try:
        return json.loads(out.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ExportError(f"`{shown}` did not print JSON ({len(out)} bytes)") from None


def _version(argv, cwd, env, pick) -> str:
    try:
        rc, out, _, _ = _run(argv, cwd, env, 60)
        return clean(pick(out.decode("utf-8", "replace")), 80) if rc == 0 else "unknown"
    except (ExportError, ValueError, KeyError, TypeError, AttributeError):
        return "unknown"


def _safe_name(*parts) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", "-".join(str(p) for p in parts))[:150].lstrip("._-") or "export"


def _export_terraform(op, exe, env, d: Path):
    plan, tool = op["plan"], op["tool"]
    env = dict(env, TF_WORKSPACE=plan["workspace"], CHECKPOINT_DISABLE="1", TF_INPUT="0", TF_IN_AUTOMATION="1")
    shown = f"{tool} state pull"
    out = _ok([exe, "state", "pull"], plan["dir"], env)
    if not out.strip():
        raise ExportError(f"`{shown}` printed nothing: workspace {plan['workspace']} has no state")
    state = _json(out, shown)
    if not isinstance(state, dict):
        raise ExportError(f"`{shown}` did not print a state object")
    serial, lineage, resources = state.get("serial"), state.get("lineage"), state.get("resources")
    if not isinstance(serial, int) or isinstance(serial, bool) or not isinstance(lineage, str) or not lineage:
        raise ExportError(f"`{shown}` printed JSON without a serial and lineage, so it is not a state file")
    if not isinstance(resources, list):
        raise ExportError(f"`{shown}` printed a state without a resources list")
    if not resources:
        raise ExportError(f"the state of workspace {plan['workspace']} lists no resources, so there is nothing to back up")
    managed = [r for r in resources if isinstance(r, dict) and r.get("mode") == "managed"]
    types = {}
    for r in managed:
        if isinstance(r.get("type"), str):
            types[r["type"]] = types.get(r["type"], 0) + 1
    name = f"{tool}.tfstate"
    sha, size = _write_private(d / name, out)
    facts = {"serial": serial, "lineage": clean(lineage, 80), "resources": len(resources), "managed": len(managed),
             "types": dict(sorted(types.items(), key=lambda kv: (-kv[1], kv[0]))[:20])}
    version = _version([exe, "version", "-json"], plan["dir"], env, lambda s: json.loads(s)["terraform_version"])
    summary = (f"state serial {serial}, lineage {facts['lineage']}, {len(resources)} resources"
               + (" (" + ", ".join(f"{k} {v}" for k, v in list(facts["types"].items())[:6]) + ")" if types else ""))
    return [dict(file=name, command=shown, bytes=size, sha256=sha, facts=facts)], {tool: version}, [summary]


def _kube_argv(op, exe) -> list[str]:
    plan = op["plan"]
    argv = [exe] + list(plan.get("conn", []))
    if plan.get("kubeconfig"):
        argv.append(f"--kubeconfig={plan['kubeconfig']}")
    if plan.get("context"):
        argv.append(f"--context={plan['context']}")  # pinned to the context the target names
    return argv


def _items(doc, shown: str) -> list:
    if not isinstance(doc, dict) or not isinstance(doc.get("items"), list):
        raise ExportError(f"`{shown}` did not print a list of objects")
    return [x for x in doc["items"] if isinstance(x, dict)]


def _count_kinds(items) -> str:
    counts = {}
    for x in items:
        counts[str(x.get("kind"))] = counts.get(str(x.get("kind")), 0) + 1
    return ", ".join(f"{k} {v}" for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:8])


def _export_kubectl(op, exe, env, d: Path):
    plan = op["plan"]
    base = _kube_argv(op, exe)
    ns_args = ["--all-namespaces"] if plan.get("all_namespaces") else (
        [f"--namespace={plan['namespace']}"] if plan.get("namespace") else [])
    exports, notes = [], []

    def save(fname, data, command, facts):
        sha, size = _write_private(d / fname, data)
        exports.append(dict(file=fname, command=command, bytes=size, sha256=sha, facts=facts))

    mode = plan.get("mode")
    if mode == "objects":
        for o in plan["objects"]:
            argv = base + ["get", o["resource"], o["name"], "-o", "json"] + ([] if o["cluster_scoped"] else ns_args)
            shown = " ".join(mask_words(["kubectl"] + argv[1:]))
            out = _ok(argv, op["cwd"], env)
            doc = _json(out, shown)
            meta = doc.get("metadata") if isinstance(doc, dict) else None
            kind = doc.get("kind") if isinstance(doc, dict) else None
            if not isinstance(meta, dict) or meta.get("name") != o["name"] or not isinstance(kind, str):
                raise ExportError(f"`{shown}` did not return an object named {o['name']}")
            expected = KINDS.get(o["kind"], (None,))[0]
            if expected and kind != expected:
                raise ExportError(f"`{shown}` returned a {clean(kind, 60)}, expected a {expected}")
            ns = meta.get("namespace") or ""
            save(_safe_name("kubectl", o["kind"], ns, o["name"]) + ".json", out, shown,
                 {"kind": kind, "name": o["name"], "namespace": ns})
            notes.append(f"{kind} {o['name']}" + (f" in namespace {ns}" if ns else ""))
            if o["kind"] == "namespaces":
                types_out = _ok(base + ["api-resources", "--namespaced=true", "--verbs=list,delete", "-o", "name"],
                                op["cwd"], env)
                types = [t for t in types_out.decode("utf-8", "replace").split()
                         if t and not t.startswith("events")]
                if not types:
                    raise ExportError("`kubectl api-resources` listed no namespaced resource types")
                argv = base + ["get", ",".join(types), f"--namespace={o['name']}", "-o", "json"]
                shown = f"kubectl get <{len(types)} resource types> --namespace={o['name']} -o json"
                out = _ok(argv, op["cwd"], env)
                items = _items(_json(out, shown), shown)
                save(_safe_name("kubectl-namespace", o["name"], "contents") + ".json", out, shown,
                     {"items": len(items), "resource_types": len(types)})
                notes.append(f"{len(items)} objects in namespace {o['name']} ({_count_kinds(items) or 'none'})")
            elif o["kind"] == "customresourcedefinitions":
                argv = base + ["get", o["name"], "--all-namespaces", "-o", "json"]
                shown = " ".join(mask_words(["kubectl"] + argv[1:]))
                out = _ok(argv, op["cwd"], env)
                items = _items(_json(out, shown), shown)
                save(_safe_name("kubectl-crd", o["name"], "objects") + ".json", out, shown, {"items": len(items)})
                notes.append(f"{len(items)} objects of type {o['name']}")
    elif mode == "group":
        argv = base + ["get", plan["resources"]] + ns_args + ["-o", "json"]
        if plan.get("selector"):
            argv.append(f"--selector={plan['selector']}")
        if plan.get("field_selector"):
            argv.append(f"--field-selector={plan['field_selector']}")
        shown = " ".join(mask_words(["kubectl"] + argv[1:]))
        out = _ok(argv, op["cwd"], env)
        items = _items(_json(out, shown), shown)
        if not items:
            raise ExportError(f"`{shown}` matched no objects, so there is nothing to back up")
        save(_safe_name("kubectl", plan["resources"], "selection") + ".json", out, shown, {"items": len(items)})
        notes.append(f"{len(items)} objects ({_count_kinds(items)})")
    elif mode == "files":
        argv = base + ["get"]
        for f in plan["files"]:
            argv += ["-f", f]
        if plan.get("kustomize"):
            argv += ["-k", plan["kustomize"]]
        if plan.get("recursive"):
            argv.append("--recursive")
        argv += ns_args + ["-o", "json"]
        shown = " ".join(mask_words(["kubectl"] + argv[1:]))
        out = _ok(argv, op["cwd"], env)
        doc = _json(out, shown)
        items = _items(doc, shown) if isinstance(doc, dict) and "items" in doc else [doc]
        if not items or not all(isinstance(x, dict) and x.get("kind") and isinstance(x.get("metadata"), dict)
                                for x in items):
            raise ExportError(f"`{shown}` returned no objects")
        save("kubectl-manifest-objects.json", out, shown, {"items": len(items)})
        notes.append(f"{len(items)} objects ({_count_kinds(items)})")
    else:
        raise ExportError("nothing to export", 2)
    version = _version([exe, "version", "--client", "-o", "json"], op["cwd"], env,
                       lambda s: json.loads(s)["clientVersion"]["gitVersion"])
    return exports, {"kubectl": version}, notes


def _export_helm(op, exe, env, d: Path):
    plan = op["plan"]
    base = [exe] + list(plan.get("conn", []))
    if plan.get("kubeconfig"):
        base.append(f"--kubeconfig={plan['kubeconfig']}")
    if plan.get("context"):
        base.append(f"--kube-context={plan['context']}")
    if plan.get("namespace"):
        base.append(f"--namespace={plan['namespace']}")
    exports, notes = [], []
    for rel in plan["releases"]:
        argv = [base[0], "get", "all", rel] + base[1:]
        shown = " ".join(mask_words(["helm"] + argv[1:]))
        out = _ok(argv, op["cwd"], env)
        text = out.decode("utf-8", "replace")
        if not text.strip():
            raise ExportError(f"`{shown}` printed nothing")
        if rel not in text:
            raise ExportError(f"`{shown}` printed {len(out)} bytes that do not name release {rel}")
        sha, size = _write_private(d / (_safe_name("helm", rel) + ".txt"), out)
        exports.append(dict(file=_safe_name("helm", rel) + ".txt", command=shown, bytes=size, sha256=sha,
                            facts={"release": rel}))
        notes.append(f"release {rel}: {size} bytes of manifest, values, hooks and notes")
    version = _version([exe, "version", "--short"], op["cwd"], env, lambda s: s.strip())
    return exports, {"helm": version}, notes


def _export_git(op, exe, env, d: Path, now=None):
    plan = op["plan"]
    env = dict(env, GIT_TERMINAL_PROMPT="0")
    cwd, remote = plan["git_cwd"], plan["remote"]
    stamp = (now or now_utc()).strftime("%Y%m%dT%H%M%SZ")
    exports, notes = [], []
    for ref in plan["refs"]:
        shown_remote = mask_text(remote)
        out = _ok([exe, "ls-remote", remote, ref], cwd, env).decode("utf-8", "replace")
        sha = next((ln.split()[0] for ln in out.splitlines() if len(ln.split()) == 2 and ln.split()[1] == ref
                    and SHA.fullmatch(ln.split()[0])), None)
        if sha is None:
            raise ExportError(f"{shown_remote} has no {ref}: a force push would create it and overwrite nothing,"
                              " so there is nothing to back up")
        # --refmap= keeps origin/* where it is: moving it would defeat a later --force-with-lease
        _ok([exe, "fetch", "--no-tags", "--refmap=", remote, ref], cwd, env)
        rc, _, _, _ = _run([exe, "cat-file", "-e", sha + "^{commit}"], cwd, env)
        if rc != 0:
            raise ExportError(f"after the fetch, commit {sha[:12]} is not in the local repository")
        short = ref[len("refs/heads/"):] if ref.startswith("refs/heads/") else ref[len("refs/"):]
        backup_ref = f"refs/destroy-guard/{short}-{stamp}"
        _ok([exe, "update-ref", backup_ref, sha, ""], cwd, env)
        got = _ok([exe, "rev-parse", "--verify", backup_ref + "^{commit}"], cwd, env).decode().strip()
        if got != sha:
            raise ExportError(f"{backup_ref} points at {got[:12]}, not {sha[:12]}")
        record = f"{sha} {ref} {shown_remote}\nbackup ref: {backup_ref}\n".encode("utf-8")
        fname = _safe_name("git", short) + ".txt"
        fsha, size = _write_private(d / fname, record)
        exports.append(dict(file=fname, command=f"git ls-remote {shown_remote} {ref}; git fetch; git update-ref",
                            bytes=size, sha256=fsha, facts={"ref": ref, "remote_tip": sha, "backup_ref": backup_ref}))
        notes.append(f"{ref} on {shown_remote} was {sha}; kept as {backup_ref}")
    version = _version([exe, "--version"], cwd, env, lambda s: s.strip().split()[-1])
    return exports, {"git": version}, notes


EXPORTERS = {"terraform": _export_terraform, "tofu": _export_terraform, "kubectl": _export_kubectl,
             "helm": _export_helm, "git": _export_git}
SECRETS_NOTE = ("Backups can hold secrets: Terraform state often contains passwords and keys, Kubernetes Secrets are"
                " only base64-encoded, Helm values often carry credentials. They stay on this machine, in a directory"
                " only you can read; destroy-guard never uploads or prints them.")


def _which(op: dict, env: dict):
    import shutil
    exe = op["exe"]
    if os.path.dirname(exe) and not os.path.isabs(exe) and op["cwd"]:
        exe = os.path.join(op["cwd"], exe)
    return shutil.which(exe, path=env.get("PATH"))


def backup_one(op: dict, out=sys.stdout, err=sys.stderr, now=None) -> int:
    env = dict(os.environ)
    for k, v in _assign_pairs(op["assign"]):
        env[k] = v
    exe = _which(op, env)
    if not exe:
        print(f"{op['label']}: {_basename(op['exe'])} was not found on PATH; no backup written.", file=err)
        return 2
    now = now or now_utc()
    store = store_dir(op["cwd"])
    try:
        notes = prepare_store(store)
    except (OSError, ExportError) as e:
        print(f"{op['label']}: cannot create {store}: {getattr(e, 'strerror', None) or e}", file=err)
        return 2
    import shutil
    key = hashlib.sha256("\n".join(target_key(t) for t in op["targets"]).encode("utf-8")).hexdigest()[:12]
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    d = None
    for n in range(100):
        cand = store / "backups" / (f"{stamp}-{key}" + (f"-{n}" if n else ""))
        try:
            os.mkdir(cand, 0o700)
            d = cand
            break
        except FileExistsError:
            continue
    if d is None:
        print(f"{op['label']}: could not create a backup directory in {store}", file=err)
        return 2
    if os.name == "posix":
        os.chmod(d, 0o700)
    print(f"{op['label']} {op['what']}; backing it up", file=out)
    try:
        exporter = EXPORTERS[op["tool"]]
        if op["tool"] == "git":
            exports, versions, facts = exporter(op, exe, env, d, now)
        else:
            exports, versions, facts = exporter(op, exe, env, d)
    except ExportError as e:
        shutil.rmtree(d, ignore_errors=True)
        print(f"{op['label']}: no backup written: {e}", file=err)
        return e.code
    except BaseException:
        shutil.rmtree(d, ignore_errors=True)  # a half-written backup may hold secrets
        raise
    manifest = {
        "destroy_guard": VERSION, "format": 1, "created_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "command": " ".join(mask_words(list(op["assign"]) + list(op["words"]), _basename(op["exe"]),
                                       len(op["assign"]))),
        "label": op["label"], "what": op["what"], "targets": op["targets"], "exports": exports,
        "tool_versions": versions, "verified": True,
    }
    _write_private(d / "manifest.json.tmp", json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8"))
    os.replace(d / "manifest.json.tmp", d / "manifest.json")
    until = (now + max_age()).strftime("%H:%M:%S UTC")
    for f in facts:
        print(f"  {f}", file=out)
    for e in exports:
        print(f"  {e['file']}: {e['bytes']} bytes, sha256 {e['sha256'][:16]}...", file=out)
    print(f"verified backup: {d}", file=out)
    print(f"  counts for this exact target until {until} ({fmt_age(max_age())}, destroy-guard's own window)", file=out)
    for note in notes:
        print(f"  {note}", file=out)
    print(SECRETS_NOTE, file=err)
    return 0


def _assign_pairs(words):
    for w in words:
        m = ASSIGN.fullmatch(w)
        if m:
            yield m.group(1), m.group(2)


# ---------------------------------------------------------------- CLI

USAGE = """usage: destroy-guard backup [--cwd DIR] -- <command>   make a verified backup of what <command> removes
       destroy-guard check  [--cwd DIR] [--json] -- <command>   what the hook would say about <command>
       destroy-guard list   [--cwd DIR] [--json]                backups in this project's store
       destroy-guard --version

Exit codes: backup 0 verified backup written, 1 an export failed its checks, 2 nothing to back up
(not a destructive command, no automatic backup for it, tool missing, bad arguments);
check 0 nothing destructive or every target covered, 1 a target has no fresh backup, 2 bad arguments;
list 0 all backups intact, 1 a backup file is missing or changed."""


def _parse_cli(rest: list[str]):
    opts, words, i = {"cwd": None, "json": False}, [], 0
    while i < len(rest):
        a = rest[i]
        if a == "--":
            words = rest[i + 1:]
            break
        if a == "--cwd" and i + 1 < len(rest):
            opts["cwd"] = rest[i + 1]
            i += 2
            continue
        if a.startswith("--cwd="):
            opts["cwd"] = a[len("--cwd="):]
        elif a == "--json":
            opts["json"] = True
        elif a.startswith("-"):
            raise ValueError(f"unknown option {a}")
        else:
            words = rest[i:]
            break
        i += 1
    cwd = opts["cwd"] or os.getcwd()
    if not os.path.isdir(cwd):
        raise ValueError(f"--cwd {cwd}: no such directory")
    opts["cwd"] = os.path.realpath(cwd)
    command = words[0] if len(words) == 1 else shlex.join(words) if words else ""
    return opts, command


def cmd_backup(opts, command, out, err) -> int:
    if not command:
        print("destroy-guard backup: give the destructive command after --", file=err)
        return 2
    ops = analyse(command, "bash", opts["cwd"])
    if not ops:
        print("destroy-guard: this is not a command destroy-guard knows as destructive; nothing to back up.", file=err)
        return 2
    codes = []
    for op in ops:
        if not op["auto"]:
            print(f"{op['label']}: {op['problem']}", file=err)
            codes.append(2)
            continue
        codes.append(backup_one(op, out, err))
    return 0 if all(c == 0 for c in codes) else 1 if 1 in codes else 2


def cmd_check(opts, command, out, err) -> int:
    if not command:
        print("destroy-guard check: give the command after --", file=err)
        return 2
    results = evaluate(command, "bash", opts["cwd"])
    window = max_age()
    rows = []
    for r in results:
        op = r["op"]
        row = {"label": op["label"], "effect": op["what"], "status": r["status"], "problem": op["problem"],
               "backup_command": backup_command(op, opts["cwd"]) if op["auto"] else None,
               "backups": [str(d) for d, _ in r.get("backups", [])],
               "newest_backup_age_seconds": int(r["newest_age"].total_seconds()) if r.get("newest_age") else None}
        rows.append(row)
    if opts["json"]:
        print(json.dumps({"window_minutes": window.total_seconds() / 60, "operations": rows}, indent=2,
                         ensure_ascii=False), file=out)
    elif not rows:
        print("nothing destructive that destroy-guard knows of", file=out)
    for row in [] if opts["json"] else rows:
        print(f"{row['label']}: {row['effect']}", file=out)
        if row["status"] == "covered":
            print(f"  covered by {', '.join(row['backups'])}", file=out)
        elif row["status"] == "missing":
            age = row["newest_backup_age_seconds"]
            print("  no backup from the last " + fmt_age(window) + (
                f" (newest: {fmt_age(dt.timedelta(seconds=age))} old)" if age is not None else ""), file=out)
            print(f"  make one: {row['backup_command']}", file=out)
        else:
            print(f"  {row['problem']}", file=out)
    return 1 if any(r["status"] != "covered" for r in results) else 0


def cmd_list(opts, out, err) -> int:
    store = store_dir(opts["cwd"])
    now, rows, bad = now_utc(), [], 0
    for d in backups(store):
        m, created = load_manifest(d)
        status = "ok"
        if m is None:
            status, bad = created, bad + 1
        else:
            for e in m["exports"]:
                data = (d / e["file"]).read_bytes()
                if hashlib.sha256(data).hexdigest() != e.get("sha256"):
                    status, bad = f"{e['file']}: checksum differs", bad + 1
                    break
        rows.append({"dir": str(d), "created_utc": m["created_utc"] if m else None,
                     "age_seconds": int((now - created).total_seconds()) if m else None,
                     "label": m.get("label") if m else None, "what": m.get("what") if m else None,
                     "files": [e["file"] for e in m["exports"]] if m else [], "status": status})
    if opts["json"]:
        print(json.dumps({"store": str(store), "backups": rows}, indent=2, ensure_ascii=False), file=out)
    elif not rows:
        print(f"no backups in {store}", file=out)
    else:
        print(f"{store}", file=out)
        for r in rows:
            age = fmt_age(dt.timedelta(seconds=r["age_seconds"])) + " old" if r["age_seconds"] is not None else "?"
            print(f"  {Path(r['dir']).name}  {age:>14}  {r['status']}  {clean(r['label'] or '', 60)}: "
                  f"{clean(r['what'] or '', 120)}", file=out)
    return 1 if bad else 0


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    out, err = sys.stdout, sys.stderr
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(USAGE, file=out if argv else err)
        return 0 if argv else 2
    if argv[0] in ("--version", "-V"):
        print(f"destroy-guard {VERSION}", file=out)
        return 0
    cmd = argv[0]
    if cmd not in ("backup", "check", "list"):
        print(f"destroy-guard: unknown command {clean(cmd, 40)}\n{USAGE}", file=err)
        return 2
    try:
        opts, command = _parse_cli(argv[1:])
    except ValueError as e:
        print(f"destroy-guard {cmd}: {e}", file=err)
        return 2
    if cmd == "backup":
        return cmd_backup(opts, command, out, err)
    if cmd == "check":
        return cmd_check(opts, command, out, err)
    return cmd_list(opts, out, err)


if __name__ == "__main__":
    raise SystemExit(main())
