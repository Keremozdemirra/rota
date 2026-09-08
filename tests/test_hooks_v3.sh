#!/usr/bin/env bash
# Tests for the three v3 hooks: Şef anchor v2, one-line reply, slop gate.
# Usage: bash test_hooks_v3.sh [hooks-dir]   (default: ~/.claude/hooks, *.proposed files)
set -u
H="${1:-$HOME/.claude/hooks}"
SEF="$H/sef-anchor.sh.proposed"; ONE="$H/one-line-reply.sh.proposed"; GATE="$H/slop-gate.sh.proposed"
[ -f "$SEF" ] || SEF="$H/sef-anchor.sh"; [ -f "$ONE" ] || ONE="$H/one-line-reply.sh"; [ -f "$GATE" ] || GATE="$H/slop-gate.sh"
HUB="local_d745dbde-a33b-4a0e-8f8a-f18bd95be1fb"; OTHER="local_f3a16218-2ddc-400e-9350-5d1f9807a2a3"
pass=0; fail=0
check() { # name want_blocked hook json
  local rc got; printf '%s' "$4" | bash "$3" >/dev/null 2>&1; rc=$?; got=0; [ "$rc" -ne 0 ] && got=1
  if [ "$got" = "$2" ]; then pass=$((pass+1)); printf 'ok    %s\n' "$1"; else fail=$((fail+1)); printf 'FAIL  %s (blocked=%s wanted=%s rc=%s)\n' "$1" "$got" "$2" "$rc"; fi
}
j() { python3 -c 'import json,sys; print(json.dumps(json.loads(sys.argv[1])))' "$1"; }
msg() { python3 -c 'import json,sys; print(json.dumps({"tool_name":"mcp__ccd_session_mgmt__send_message","tool_input":{"session_id":sys.argv[1],"message":sys.argv[2]}}))' "$1" "$2"; }

echo "== sef-anchor v2"
check "no Şef → blocked" 1 "$SEF" "$(msg "$HUB" "[ORK] RESULT a → hub | x")"
check "Şef: ok" 0 "$SEF" "$(msg "$HUB" "Şef: [ORK] RESULT a → hub | x
DID: y")"
check "Şef — em dash → blocked" 1 "$SEF" "$(msg "$HUB" "Şef — [ORK] RESULT a → hub | x")"
LONG=$(python3 -c 'print("Şef: [ORK] RESULT a → hub | x\n" + "\n".join(f"line {i}" for i in range(20)))')
check "20 lines → blocked" 1 "$SEF" "$(msg "$HUB" "$LONG")"
BIG=$(python3 -c 'print("Şef: [ORK] RESULT a → hub | x\n" + "w" * 2000)')
check "2,000 chars → blocked" 1 "$SEF" "$(msg "$HUB" "$BIG")"
check "lane to lane, no Şef → passes" 0 "$SEF" "$(msg "$OTHER" "[ORK] FYI a → b | x")"
check "other tool → passes" 0 "$SEF" "$(j '{"tool_name":"Bash","tool_input":{"command":"ls"}}')"

echo "== one-line-reply"
T=$(mktemp -d)
mk() { python3 -c 'import json,sys
print(json.dumps({"type":"user","message":{"role":"user","content":"hi"}}))
print(json.dumps({"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":sys.argv[1]}]}}))' "$1"; }
mk "Sent to hub: T-044 done" > "$T/one.jsonl"
mk "Line one.
Line two with narration for Kerem.
Line three." > "$T/many.jsonl"
stop() { python3 -c 'import json,sys; print(json.dumps({"hook_event_name":"Stop","stop_hook_active":sys.argv[3]=="1","cwd":sys.argv[1],"transcript_path":sys.argv[2]}))' "$1" "$2" "$3"; }
check "lane, one line → passes" 0 "$ONE" "$(stop "$HOME/agents" "$T/one.jsonl" 0)"
check "lane, three lines → blocked" 1 "$ONE" "$(stop "$HOME/agents" "$T/many.jsonl" 0)"
check "lane subfolder, three lines → blocked" 1 "$ONE" "$(stop "$HOME/agents/plsfix" "$T/many.jsonl" 0)"
check "hub cwd, three lines → passes" 0 "$ONE" "$(stop "/tmp/hub-scratch" "$T/many.jsonl" 0)"
check "stop_hook_active → passes (no loop)" 0 "$ONE" "$(stop "$HOME/agents" "$T/many.jsonl" 1)"
check "missing transcript → passes" 0 "$ONE" "$(stop "$HOME/agents" "$T/none.jsonl" 0)"

echo "== slop-gate"
W() { python3 -c 'import json,sys; print(json.dumps({"tool_name":"Write","tool_input":{"file_path":sys.argv[1],"content":sys.argv[2]}}))' "$1" "$2"; }
check "md with em dash under ~/agents → blocked" 1 "$GATE" "$(W "$HOME/agents/projects/x/y.md" "A — B.")"
check "md with contrast → blocked" 1 "$GATE" "$(W "$HOME/agents/projects/x/y.md" "It is a receipt, not a report.")"
check "clean md → passes" 0 "$GATE" "$(W "$HOME/agents/projects/x/y.md" "It is a receipt.")"
check "blockquoted dash → passes" 0 "$GATE" "$(W "$HOME/agents/projects/x/y.md" "> quoted — verbatim
Own prose.")"
check "py file with dash → passes" 0 "$GATE" "$(W "$HOME/agents/projects/x/y.py" "# A — B")"
check "md outside roots → passes" 0 "$GATE" "$(W "/tmp/elsewhere/y.md" "A — B.")"
printf 'Old line, not a good one.\n' > "$T/e.md"
E() { python3 -c 'import json,sys; print(json.dumps({"tool_name":"Edit","tool_input":{"file_path":sys.argv[1],"old_string":sys.argv[2],"new_string":sys.argv[3]}}))' "$1" "$2" "$3"; }
mkdir -p "$HOME/agents/projects/_hooktest" && cp "$T/e.md" "$HOME/agents/projects/_hooktest/e.md"
check "edit that removes the contrast → passes" 0 "$GATE" "$(E "$HOME/agents/projects/_hooktest/e.md" "Old line, not a good one." "Old line.")"
check "edit that keeps the contrast → blocked" 1 "$GATE" "$(E "$HOME/agents/projects/_hooktest/e.md" "Old line" "New line")"
rm -rf "$HOME/agents/projects/_hooktest" "$T"

echo "== read-budget"
RB="$H/read-budget.sh.proposed"; [ -f "$RB" ] || RB="$H/read-budget.sh"
T2=$(mktemp -d); python3 -c 'print("\n".join("line %d" % i for i in range(1000)))' > "$T2/long.md"; printf 'short\n' > "$T2/short.md"
R() { python3 -c 'import json,sys; ti={"file_path":sys.argv[1]}
if len(sys.argv)>2: ti["limit"]=int(sys.argv[2])
print(json.dumps({"tool_name":"Read","tool_input":ti}))' "$@"; }
check "1000-line file, no limit → blocked" 1 "$RB" "$(R "$T2/long.md")"
check "1000-line file with limit → passes" 0 "$RB" "$(R "$T2/long.md" 120)"
check "short file → passes" 0 "$RB" "$(R "$T2/short.md")"
check "missing file → passes" 0 "$RB" "$(R "$T2/none.md")"
check "other tool → passes" 0 "$RB" "$(j '{"tool_name":"Bash","tool_input":{"command":"ls"}}')"
rm -rf "$T2"

echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
