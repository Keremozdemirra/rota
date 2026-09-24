#!/usr/bin/env python3
"""Compare hook-harness's idea of which hook handlers run with what an installed Claude Code actually starts.

  python3 tools/crosscheck_claude_code.py probes [--corpus fitted|heldout]
      Runs a corpus of `if` rules against tool calls and reports, rule by rule, where hook-harness and Claude Code
      agree. "fitted" is the corpus the matching model was built from. "heldout" was written afterwards and scored
      991 of 1045 before the model was revised on it; "heldout2" was written after that revision.

  python3 tools/crosscheck_claude_code.py hooks HOOKS.json CASES.json
      Replaces every command in a real hooks file with a recorder, sends each case's tool call through Claude Code,
      and compares the number of handler processes per case with `hook-harness run --dry-run`.

How: a local stand-in for the Messages API answers each model request with the next scripted tool call. Claude Code
runs with an empty temporary HOME, a stripped environment and a placeholder API key that only the local stand-in
ever sees, so no account, no credential and no network are involved. A catch-all PreToolUse handler denies every
call, so no probed command runs; file tools touch only a temporary project directory. Needs `claude` on PATH.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import hook_harness as hh  # noqa: E402

RECORDER = r'''import json, os, sys
d = json.load(sys.stdin)
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "log.jsonl"), "a") as f:
    f.write(json.dumps({"id": sys.argv[1], "event": d.get("hook_event_name"), "tool": d.get("tool_name"),
                        "tool_use_id": d.get("tool_use_id"), "input": d.get("tool_input")}) + "\n")
if sys.argv[2:] == ["deny"]:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                             "permissionDecisionReason": "crosscheck"}}))
'''
FILE_TOOLS = ("Write", "Edit", "Read")


# ---------------------------------------------------------------- corpus

BASH_FITTED_RULES = [
    "Bash(git *)", "Bash(git push *)", "Bash(rm *)", "Bash(cat *)", "Bash(npm run *)", "Bash(npm run build)",
    "Bash(ls *)", "Bash(ls*)", "Bash(* --version)", "Bash(* --help *)", "Bash(git log * main)", "Bash(npm test)",
    "Bash(ls:*)", "Bash(echo *)", "Bash(date)", "Bash(git:* push)", "Bash", "Bash(*)", "Bash(run_in_background:true)",
    "Bash(grep *)", "Bash(npm test *)", "Bash(sudo *)", "Bash(bash *)", "Bash(git)", "Bash(true)", "Bash(sleep *)",
    "Bash(npm *)", "Bash(git*)", "Bash([[ *)", "Bash([ *)", "Bash(test *)", "Bash(./run.sh *)", "Bash(a.b *)",
    "Bash(/usr/bin/git *)", "Bash(g*t *)", "Bash(git  *)", "Bash(git *x)", "Bash(@scope/x *)", "Bash(x *)",
    "Bash(ls)", "Bash(echo)", "Bash(git push)", "Bash(* main)", "Bash(cd *)", "Bash(nohup *)", "Bash(timeout *)",
    "Bash(nice *)", "Bash(command *)", "Bash(env *)", "Bash(xargs *)", "Bash(git commit *)", "Bash(git push )",
    "Bash(echo a b)", "Bash(git commit -m fix bug)", "Bash(export *)", "Bash(pip install *)"]
BASH_FITTED_COMMANDS = [
    "git push origin main", "FOO=bar git push", "npm test && git push", "echo $(rm -f /nonexistent-hh-probe)",
    "echo $(date)", "echo before $(date) after", "$TOOL git push", "git 'push' origin main", "\\git push origin main",
    "git  push  origin main", "timeout 30 npm test", "nice -n 5 npm test", "xargs grep pattern", "xargs -n1 grep x",
    "npm test > /dev/null", "npm test 2>&1 | tee /dev/null", "lsof", "ls", "ls -la", "node --version", "npm --help x",
    "npm --help", "git log --oneline main", "git log main", "npm run build --watch", "npm run", "echo '$HOME'",
    "echo \"$HOME\"", "echo ${HOME}", "if true; then git push; fi", "for f in a b; do rm -f /nonexistent-$f; done",
    "(cd /tmp && git status)", "npm test &&", "echo \"unbalanced", "cat <<EOF\ngit push\nEOF", "sudo git push",
    "bash -c 'git push'", "command -v git", "command git push", "git status # git push", "echo `git log`",
    "NODE_ENV=test npm test", "echo hi; ls", "true | git push", "git push &", "'git' push origin main",
    "git \"push\" origin main", "rm *.tmp", "cat ~/x", "echo $'a'", "echo $((1+2))", "{ git push; }", "time git push",
    "! git push", "git push\nls", "case x in x) git push;; esac", "f() { git push; }", "diff <(ls) <(ls)",
    "echo hi > out.txt", "exec git push", "npm install left-pad esbuild && echo \"$HOME\"", "echo $HOME", "ls $DIR",
    "echo $1", "echo \"$@\"", "x=$(date)", "FOO=$(date) git push", "while true; do git push; done",
    "if [ -f x ]; then git push; else ls; fi", "nohup git push", "echo hi && echo \"$(git log)\"",
    "git push; echo $HOME", "[[ -f x ]] && git push", "git push \"origin", "ls && $X foo", "git \\\npush origin main",
    "env A=1 git push", "git push origin\\ main", "echo x | xargs git push", "echo $HOME/x", "cat file.txt | grep x",
    "git -C . push origin main", "ls \"$DIR\"", "echo $(( 2 + 3 ))", "a=1; git push", "echo $PWD", "echo \"$PWD\"",
    "echo \"a $DIR b\"", "echo a\\ b", "echo \\$HOME", "for f in a b; do echo x; done", "echo \"$(date)\" && ls",
    "echo \"$((1+2))\"", "echo $$", "echo '$(date)'", "echo ${#x}", "echo $HOME$USER", "echo \"$(ls)\" x",
    "git commit -m \"fix bug\"", "echo 'a b'", "echo $(date) | cat", "echo $(date) &", "echo $DIR && ls",
    "X=1 echo $X", "export X=$(date)", "echo $(echo $(date))", "$(which git) push", "echo $()", "echo a\\;b",
    "npm install left-pad && npm test", "git add -A && git commit -m \"msg with spaces\"", "git\tpush origin",
    "git push  ", "ls |", "echo hi &&  ", "echo $/x", "grep \"a$\" f", "grep a$ f", "echo $DIR/x", "echo x$1y",
    "[ -f x ] && ls", "echo $", "ls > $OUT", "echo <<< x", "awk '{print $1}' f", "echo $@"]
BASH_HELDOUT_RULES = [
    "Bash(npm install *)", "Bash(npm i *)", "Bash(pip install *)", "Bash(python -m pytest *)", "Bash(git commit *)",
    "Bash(git checkout *)", "Bash(docker *)", "Bash(docker run *)", "Bash(curl *)", "Bash(rm -rf *)", "Bash(make)",
    "Bash(make *)", "Bash(cargo test*)", "Bash(npx *)", "Bash(uv run *)", "Bash(jq *)", "Bash(sed -i *)",
    "Bash(find * -delete)", "Bash(chmod +x *)", "Bash(kubectl apply *)"]
BASH_HELDOUT_COMMANDS = [
    "npm install --save-dev typescript @types/node", "npm i -D vitest && npm test -- --run",
    "pip install -r requirements.txt && python -m pytest -q tests/", "python -m pytest -x -k \"not slow\"",
    "git checkout -b feature/login && git commit -am 'wip'", "git commit -m \"$(date +%F) release\"",
    "docker run --rm -v \"$PWD\":/src -w /src node:22 npm ci", "curl -fsSL https://example.com/install.sh | sh",
    "rm -rf node_modules dist && npm ci", "make -j4", "make", "cargo test --workspace 2>&1 | tail -20",
    "npx prettier --write 'src/**/*.ts'", "uv run --with httpx python script.py", "cat package.json | jq -r .version",
    "sed -i 's/foo/bar/g' src/*.py", "find . -name '*.pyc' -delete", "chmod +x scripts/*.sh && ./scripts/build.sh",
    "kubectl apply -f k8s/ --dry-run=client", "cd frontend && npm run build && cd ..",
    "for f in src/*.ts; do npx tsc --noEmit \"$f\"; done", "export NODE_OPTIONS=--max-old-space-size=4096; npm run build",
    "test -d .venv || python3 -m venv .venv", "git log --oneline -n 5 | cat", "ls -la ~/.config",
    "echo \"Build finished at $(date)\" >> build.log", "npm run lint -- --fix", "git diff --stat HEAD~1",
    "tar -czf dist.tgz dist/ && ls -lh dist.tgz", "grep -rn \"TODO\" src/ | head -20",
    "python3 - <<'PY'\nprint(1)\nPY", "go test ./... -run TestLogin", "docker compose up -d && docker compose ps",
    "npm install left-pad; npm install", "pip3 install --upgrade pip", "yarn add lodash", "PYTHONPATH=. pytest",
    "sudo apt-get install -y jq", "cd /tmp && curl -O https://example.com/f.tgz", "bash scripts/setup.sh $ENV"]
# Written after the model was revised on the first held-out set, and run only after that revision.
BASH_HELDOUT2_RULES = [
    "Bash(npm run build*)", "Bash(npm ci)", "Bash(git diff *)", "Bash(git stash *)", "Bash(python *)", "Bash(node *)",
    "Bash(rm -f *)", "Bash(cp *)", "Bash(pytest *)", "Bash(npm install)", "Bash(docker build *)", "Bash(jq *)",
    "Bash(sudo *)", "Bash(perl *)", "Bash(npx tsc *)", "Bash(wc *)", "Bash(bundle exec *)", "Bash(make test*)",
    "Bash(open *)", "Bash(uv sync)"]
BASH_HELDOUT2_COMMANDS = [
    "npm ci && npm run build 2>&1 | tail -50", "git status && git diff --cached --stat",
    "python -c \"import sys; print(sys.version)\"", "cd \"$(dirname \"$0\")\" && ./run.sh", "ls -1 src | wc -l",
    "git log -1 --format=%H", "node -e \"console.log(process.version)\"", "rm -f /tmp/hh-$$.lock",
    "mkdir -p build && cp -r assets build/", "grep -q \"version\" package.json && echo found",
    "pytest tests/test_x.py::test_y -vv", "if [ -f package.json ]; then npm install; fi",
    "for d in */; do echo \"$d\"; done", "cat <<'EOF' | python3 -\nprint(2)\nEOF",
    "git stash && git pull --rebase && git stash pop", "export PATH=\"$HOME/.local/bin:$PATH\" && uv sync",
    "docker build -t app:$(git rev-parse --short HEAD) .", "curl -s https://api.github.com/repos/o/r | jq .stargazers_count",
    "sudo systemctl restart nginx", "ruby -v", "perl -pi -e 's/a/b/' file.txt", "npx tsc --noEmit -p tsconfig.json",
    "echo \"$(git branch --show-current)\"", "wc -l $(git ls-files '*.py')", "git diff > changes.patch",
    "python manage.py migrate --noinput", "bundle exec rspec spec/models", "make test 2>&1 | tee test.log", "true",
    "npm test -- --coverage && open coverage/index.html"]
PATH_HELDOUT2 = {
    "Write": ["src/**/*.test.*", "**/__init__.py", "/.env", ".env", "**/*.lock", "*.min.js", "/docs/**", "migrations/**"],
    "Read": ["**/.env*", ".aws/**", "~/.aws/**", "*.key"],
}
PATH_HELDOUT2_CALLS = {
    "Write": ["@@P@@/src/a/b.test.ts", "@@P@@/pkg/__init__.py", "@@P@@/.env", "@@P@@/sub/.env", "@@P@@/yarn.lock",
              "@@P@@/web/app.min.js", "@@P@@/docs/x/y.md", "@@P@@/app/migrations/0001.py", "@@P@@/migrations/0002.py"],
    "Read": ["@@P@@/.env.production", "@@H@@/.aws/credentials", "@@P@@/.aws/config", "@@P@@/tls/server.key"],
}
PATH_FITTED = {
    "Write": ["*.ts", "src/**", "**/src/**", "/src/**", "//**/*mcp*.json", "docs", "src/*.ts", "./src/app.ts", "src",
              "docs/", "~/notes.txt", "**/*.ts", "*", None, "app.ts", "/src", "s?c/**", "[st]rc/**", "src/**/*.ts",
              "**", "*.TS", "Finance (2024)/**", "/proj/src/**", "proj/src/**", "//**/src/app.ts", "../proj/src/app.ts",
              "~/*"],
    "Read": [".env", "**/.env", "./.env", "secrets/**", "~/notes.txt", "//**/.env", "*.env", "secrets", None,
             "/proj/.env"],
}
PATH_FITTED_CALLS = {
    "Write": ["@@P@@/src/app.ts", "@@P@@/vendor/pkg/src/lib.js", "@@P@@/docs/a.md", "@@P@@/.mcp.json",
              "@@P@@/src/deep/x.ts", "@@P@@/app.ts", "@@H@@/notes.txt", "@@P@@/Finance (2024)/r.txt",
              "@@P@@/SRC/APP.TS", "src/rel.ts", "~/notes2.txt", "@@P@@/new/src/n.ts"],
    "Read": ["@@P@@/.env", "@@P@@/sub/.env", "@@P@@/secrets/x", "@@P@@/a/secrets/y", "@@H@@/notes.txt", "@@P@@/x.env",
             "@@P@@/src/app.ts", ".env"],
}
PATH_HELDOUT = {
    "Write": ["*.py", "tests/**", "**/*.test.ts", "/package.json", "package.json", "//**/node_modules/**", ".github/**",
              "**/.env*", "*.md", "src/components/*.tsx", "~/.config/**", "build/", "*.{js,ts}", "Dockerfile*"],
    "Read": [".git/**", "**/.git/**", "**/*.pem", "id_rsa*", "~/.ssh/**", "/.claude/**", "**/secrets*/**"],
}
PATH_HELDOUT_CALLS = {
    "Write": ["@@P@@/app/main.py", "@@P@@/tests/test_api.py", "@@P@@/web/src/button.test.ts", "@@P@@/package.json",
              "@@P@@/web/package.json", "@@P@@/web/node_modules/x/index.js", "@@P@@/.github/workflows/ci.yml",
              "@@P@@/.env.local", "@@P@@/docs/README.md", "@@P@@/src/components/Nav.tsx", "@@H@@/.config/tool/cfg.json",
              "@@P@@/build/out.js", "@@P@@/lib/x.js", "@@P@@/Dockerfile.prod"],
    "Read": ["@@P@@/.git/config", "@@P@@/sub/.git/HEAD", "@@P@@/certs/server.pem", "@@P@@/id_rsa.pub",
             "@@H@@/.ssh/config", "@@P@@/.claude/settings.json", "@@P@@/app/secrets-prod/db.txt"],
}


# ---------------------------------------------------------------- the stand-in API

def _mock(plan: list, log: list):
    state = {"n": 0}
    lock = threading.Lock()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            self.send_response(404)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(b"{}")

        def do_HEAD(self):
            self.send_response(200)
            self.end_headers()

        def do_POST(self):
            n = int(self.headers.get("content-length") or 0)
            body = self.rfile.read(n) if n else b""
            if not self.path.startswith("/v1/messages") or "count_tokens" in self.path:
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"input_tokens": 10}')
                return
            try:
                req = json.loads(body)
            except ValueError:
                req = {}
            with lock:
                i = state["n"]
                if req.get("tools"):
                    state["n"] += 1
            step = plan[i] if req.get("tools") and i < len(plan) else None
            log.append(i if step else None)
            msg = {"id": f"msg_{i}", "type": "message", "role": "assistant", "model": "claude-sonnet-4-5", "content": [],
                   "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 5, "output_tokens": 1}}
            if step:
                block = {"type": "tool_use", "id": f"toolu_{i:05d}", "name": step["name"], "input": {}}
                events = [{"type": "content_block_start", "index": 0, "content_block": block},
                          {"type": "content_block_delta", "index": 0,
                           "delta": {"type": "input_json_delta", "partial_json": json.dumps(step["input"])}},
                          {"type": "content_block_stop", "index": 0},
                          {"type": "message_delta", "delta": {"stop_reason": "tool_use", "stop_sequence": None},
                           "usage": {"output_tokens": 10}}]
                final = dict(msg, content=[dict(block, input=step["input"])], stop_reason="tool_use")
            else:
                events = [{"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
                          {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "done"}},
                          {"type": "content_block_stop", "index": 0},
                          {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                           "usage": {"output_tokens": 1}}]
                final = dict(msg, content=[{"type": "text", "text": "done"}], stop_reason="end_turn")
            self.send_response(200)
            if req.get("stream"):
                self.send_header("content-type", "text/event-stream")
                self.end_headers()
                events = [{"type": "message_start", "message": msg}] + events + [{"type": "message_stop"}]
                self.wfile.write("".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode())
            else:
                self.send_header("content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(final).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def run_claude(work: Path, plan: list, settings: dict, plugin_dir: Path | None, claude: str,
               project: Path) -> list:
    """Send PLAN through Claude Code; return the recorder rows."""
    home = work / "home"
    home.mkdir(exist_ok=True)
    (work / "settings.json").write_text(json.dumps(settings, indent=1), encoding="utf-8")
    log_path = work / "log.jsonl"
    if log_path.exists():
        log_path.unlink()
    api_log = []
    server = _mock(plan, api_log)
    env = {"PATH": os.pathsep.join(p for p in (os.path.dirname(claude), os.path.dirname(sys.executable),
                                              "/usr/local/bin", "/usr/bin", "/bin") if p),
           "HOME": str(home), "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{server.server_address[1]}",
           # read only by the local stand-in above; not a credential
           "ANTHROPIC_API_KEY": "placeholder-for-local-stand-in", "DISABLE_TELEMETRY": "1",
           "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "DISABLE_AUTOUPDATER": "1", "IS_SANDBOX": "1"}
    argv = [claude, "-p", "go", "--settings", str(work / "settings.json"), "--permission-mode", "dontAsk",
            "--output-format", "stream-json", "--verbose"]
    if plugin_dir:
        argv += ["--plugin-dir", str(plugin_dir)]
    try:
        subprocess.run(argv, cwd=project, env=env, stdin=subprocess.DEVNULL, stdout=open(work / "claude.out", "w"),
                       stderr=open(work / "claude.err", "w"), timeout=900)
    finally:
        server.shutdown()
    return [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()] if log_path.exists() else []


def _recorder(work: Path, rid: str, deny: bool = False) -> dict:
    return {"type": "command", "command": sys.executable, "args": [str(work / "rec.py"), rid] + (["deny"] if deny else [])}


def _deny_all(work: Path, except_files: bool = False) -> dict:
    matcher = "^(?!(Write|Edit|Read)$).*" if except_files else "*"
    return {"matcher": matcher, "hooks": [_recorder(work, "__deny__", True)]}


# ---------------------------------------------------------------- probes

def probes(corpus: str, claude: str, keep: Path | None) -> int:
    work = Path(keep or tempfile.mkdtemp(prefix="hh-crosscheck-"))
    work.mkdir(parents=True, exist_ok=True)
    (work / "rec.py").write_text(RECORDER, encoding="utf-8")
    proj, home = work / "proj", work / "home"
    for d in (proj, home):
        d.mkdir(exist_ok=True)
    b_rules, b_cmds, paths, calls = {
        "fitted": (BASH_FITTED_RULES, BASH_FITTED_COMMANDS, PATH_FITTED, PATH_FITTED_CALLS),
        "heldout": (BASH_HELDOUT_RULES, BASH_HELDOUT_COMMANDS, PATH_HELDOUT, PATH_HELDOUT_CALLS),
        "heldout2": (BASH_HELDOUT2_RULES, BASH_HELDOUT2_COMMANDS, PATH_HELDOUT2, PATH_HELDOUT2_CALLS)}[corpus]
    groups = [{"matcher": "Bash", "hooks": [_recorder(work, f"B{i}") | {"if": r} for i, r in enumerate(b_rules)]}]
    for tool, pats in paths.items():
        groups.append({"matcher": tool, "hooks": [_recorder(work, f"{tool[0]}{i}") | {"if": tool if p is None else
                                                                                       f"{tool}({p})"}
                                                  for i, p in enumerate(pats)]})
    groups.append(_deny_all(work))
    plan = [{"name": "Bash", "input": {"command": c, "description": "crosscheck"}} for c in b_cmds]
    sub = {"@@P@@": str(proj), "@@H@@": str(home)}
    for tool, targets in calls.items():
        for t in targets:
            for k, v in sub.items():
                t = t.replace(k, v)
            plan.append({"name": tool, "input": {"file_path": t, "content": "x\n"} if tool == "Write" else
                         {"file_path": t}})
            if tool == "Read" and not t.startswith("~"):
                target = Path(t if os.path.isabs(t) else proj / t)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("x\n", encoding="utf-8")
    rows = run_claude(work, plan, {"hooks": {"PreToolUse": groups}}, None, claude, proj)
    fired, seen_input = {}, {}
    for row in rows:
        fired.setdefault(row["tool_use_id"], set()).add(row["id"])
        seen_input.setdefault(row["tool_use_id"], row["input"])
    ctx = hh.Context(cwd=str(proj), project_dir=str(proj), home=str(home))
    total = agree = 0
    misses, rejected = [], []
    for i, step in enumerate(plan):
        tid = f"toolu_{i:05d}"
        if tid not in fired:
            rejected.append(step)  # Claude Code refused the call before any hook ran
            continue
        tool = step["name"]
        rules = b_rules if tool == "Bash" else [tool if p is None else f"{tool}({p})" for p in paths[tool]]
        prefix = "B" if tool == "Bash" else tool[0]
        inp = seen_input.get(tid, step["input"])
        for j, rule in enumerate(rules):
            observed = f"{prefix}{j}" in fired[tid]
            predicted = hh.rule_fires(rule, tool, inp, ctx).fires
            total += 1
            if observed == predicted:
                agree += 1
            else:
                misses.append((step, rule, observed, predicted))
    version = subprocess.run([claude, "--version"], capture_output=True, text=True).stdout.strip()
    print(f"corpus {corpus}: {agree} of {total} rule/call pairs agree with {version} "
          f"({len(b_rules)} Bash rules x {len(b_cmds)} commands, "
          f"{sum(len(v) for v in paths.values())} path rules x {sum(len(v) for v in calls.values())} paths)")
    for step, rule, observed, predicted in misses:
        what = step["input"].get("command") or step["input"].get("file_path")
        print(f"  differs: {step['name']} {json.dumps(what)[:70]} {rule}: Claude Code "
              f"{'ran' if observed else 'did not run'} it, hook-harness predicts "
              f"{'it runs' if predicted else 'it does not'}")
    for step in rejected:
        what = step["input"].get("command") or step["input"].get("file_path")
        print(f"  not counted: Claude Code rejected {step['name']} {json.dumps(what)[:80]} before hooks ran")
    print(f"work directory: {work}")
    return 0 if agree == total else 1


# ---------------------------------------------------------------- real hooks files

def hooks(hooks_path: Path, cases_path: Path, claude: str, keep: Path | None) -> int:
    src = hh.load_source(hooks_path)
    if src.data is None:
        print(f"cannot read {hooks_path}", file=sys.stderr)
        return 2
    suite = hh.load_suite(cases_path)
    work = Path(keep or tempfile.mkdtemp(prefix="hh-crosscheck-"))
    work.mkdir(parents=True, exist_ok=True)
    (work / "rec.py").write_text(RECORDER, encoding="utf-8")
    proj = work / "proj"
    if suite.project_dir and suite.project_dir.is_dir():
        shutil.copytree(suite.project_dir, proj, dirs_exist_ok=True)
    proj.mkdir(exist_ok=True)
    ids = {}
    data = json.loads(json.dumps(src.data))
    for h in hh.handlers_of(data):
        if h.type != "command":
            continue
        key = (h.spec.get("command"), json.dumps(h.spec.get("args")), h.spec.get("shell"))
        rid = ids.setdefault(key, f"C{len(ids)}")
        spec = data["hooks"][h.event][h.gi]["hooks"][h.hi]
        rec = _recorder(work, rid)
        spec.pop("shell", None)
        spec["command"], spec["args"] = rec["command"], rec["args"]
    plan, index = [], []
    for case in suite.cases:
        event, tool = case["event"], case.get("tool_name")
        if event not in ("PreToolUse", "PostToolUse") or not tool:
            index.append(None)
            continue
        if event == "PostToolUse" and tool not in FILE_TOOLS:
            index.append(None)  # the tool would really run
            continue
        inp = dict(case.get("tool_input") or {})
        if tool == "Edit":
            plan.append({"name": "Read", "input": {"file_path": inp.get("file_path")}})
        index.append(len(plan))
        plan.append({"name": tool, "input": inp})
    settings = {"hooks": {}, "permissions": {"allow": [f"Edit(/{proj}/**)", f"Read(/{proj}/**)"]}}
    plugin_dir = None
    if src.kind == "plugin":
        plugin_dir = work / "plugin"
        (plugin_dir / ".claude-plugin").mkdir(parents=True, exist_ok=True)
        (plugin_dir / "hooks").mkdir(exist_ok=True)
        (plugin_dir / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "crosscheck", "version": "0.0.0",
                                                                               "description": "crosscheck"}))
        (plugin_dir / "hooks" / "hooks.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
    else:
        settings["hooks"] = data["hooks"]
    settings["hooks"].setdefault("PreToolUse", []).append(_deny_all(work, except_files=True))
    rows = run_claude(work, plan, settings, plugin_dir, claude, proj)
    runs = {}
    for row in rows:
        if row["id"] != "__deny__":
            runs.setdefault((row["tool_use_id"], row["event"]), []).append(row["id"])
    opts = hh.Options(dry_run=True, project_dir=proj)
    predicted = hh.run_suite(src, suite, opts)
    version = subprocess.run([claude, "--version"], capture_output=True, text=True).stdout.strip()
    agree = total = 0
    print(f"{hooks_path} against {version}:")
    for case, pos, pred in zip(suite.cases, index, predicted):
        if pos is None:
            print(f"  skipped  {case['name']} (only PreToolUse calls and PostToolUse file calls are sent)")
            continue
        observed = len(runs.get((f"toolu_{pos:05d}", case["event"]), []))
        total += 1
        agree += observed == pred.processes
        print(f"  {'agree' if observed == pred.processes else 'DIFFER':7}  {case['name']}: Claude Code started "
              f"{observed}, hook-harness predicts {pred.processes}")
    print(f"{agree} of {total} cases agree. work directory: {work}")
    return 0 if agree == total else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="crosscheck_claude_code.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--claude", default=shutil.which("claude"), help="the Claude Code executable")
    ap.add_argument("--keep", type=Path, help="work directory to keep (default: a new temporary one)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("probes")
    p.add_argument("--corpus", choices=("fitted", "heldout", "heldout2"), default="fitted")
    h = sub.add_parser("hooks")
    h.add_argument("hooks", type=Path)
    h.add_argument("cases", type=Path)
    a = ap.parse_args(argv)
    if not a.claude:
        print("claude is not on PATH", file=sys.stderr)
        return 2
    if a.cmd == "probes":
        return probes(a.corpus, a.claude, a.keep)
    return hooks(a.hooks, a.cases, a.claude, a.keep)


if __name__ == "__main__":
    raise SystemExit(main())
