#!/usr/bin/env bash
# Tests for the PreToolUse secret guard.
#
# The live hook is wired to Bash only, so a credential written through the Write
# or Edit tool reaches disk unscanned. The proposed replacement handles those
# tools. These tests decide whether it earns installation, and they exist because
# the "16/16 passing" that justified it was ad hoc and left nothing on disk.
#
# Usage: bash test_secret_hook.sh [path-to-hook]   (default: the .proposed one)
set -u
HOOK="${1:-$HOME/.claude/hooks/commit-secret-scan.sh.proposed}"
pass=0; fail=0

# A credential-shaped string built at runtime, so this test file never contains
# one and never trips the very guard it is testing.
FAKE_GH="ghp_$(printf 'a%.0s' {1..36})"
FAKE_ANT="sk-ant-$(printf 'b%.0s' {1..24})"

run() { printf '%s' "$2" | bash "$HOOK" >/dev/null 2>&1; echo "$?"; }

check() { # name expected_blocked json
  local name="$1" want="$2" json="$3" rc
  rc=$(run "$name" "$json")
  local got=0; [ "$rc" -ne 0 ] && got=1
  if [ "$got" = "$want" ]; then
    pass=$((pass+1)); printf 'ok    %s\n' "$name"
  else
    fail=$((fail+1)); printf 'FAIL  %s (blocked=%s, wanted=%s, rc=%s)\n' "$name" "$got" "$want" "$rc"
  fi
}

j() { python3 -c 'import json,sys; print(json.dumps({"tool_name":sys.argv[1],"tool_input":json.loads(sys.argv[2])}))' "$1" "$2"; }

# The gap this hook exists to close.
check "Write with a GitHub token is blocked" 1 \
  "$(j Write "$(python3 -c 'import json,sys; print(json.dumps({"file_path":"/tmp/x.txt","content":"token = \""+sys.argv[1]+"\""}))' "$FAKE_GH")")"
check "Edit introducing an Anthropic key is blocked" 1 \
  "$(j Edit "$(python3 -c 'import json,sys; print(json.dumps({"file_path":"/tmp/x.py","old_string":"k=1","new_string":"KEY=\""+sys.argv[1]+"\""}))' "$FAKE_ANT")")"
check "MultiEdit with a token in one edit is blocked" 1 \
  "$(j MultiEdit "$(python3 -c 'import json,sys; print(json.dumps({"file_path":"/tmp/x.py","edits":[{"new_string":"clean"},{"new_string":sys.argv[1]}]}))' "$FAKE_GH")")"

# It must not block ordinary work, or it gets disabled within a day.
check "Write of ordinary prose passes" 0 \
  "$(j Write '{"file_path":"/tmp/x.md","content":"Rotate the token in settings, then delete the file."}')"
check "Write mentioning the word token passes" 0 \
  "$(j Write '{"file_path":"/tmp/x.md","content":"ghp_ is the classic token prefix"}')"
check "Read is not scanned" 0 "$(j Read '{"file_path":"/tmp/x.md"}')"
check "Bash without git passes" 0 "$(j Bash '{"command":"ls -la"}')"

# Failing open on a credential gate is the one unacceptable outcome.
check "malformed input does not crash into an allow" 0 "not json at all"
check "empty input does not crash" 0 ""

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
