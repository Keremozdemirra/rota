#!/usr/bin/env bash
# rota.sh — the one command.
#
#   bash ~/agents/rota/rota.sh setup     idempotent install/repair of everything
#                                        (deps, index, links, git, weekly autorun,
#                                        `rota` alias). Run once per Mac; rerun
#                                        any time — it only fixes what's missing.
#   rota status                          health check, one line per component
#   rota weekly                          ledger report + scout + inbox brief
#                                        (also runs automatically Mondays 09:30)
#   rota run "..." [--dry-run]           one-shot dispatch through the router
#   rota serve [port]                    BYO-key platform on localhost (docs/platform.md)
#   rota build [--item NNN] [--dry-run]  weekly autonomous project (docs/weekly-pipeline.md)
#   rota routes | rota report            routing table / token ledger
#   rota auto-off                        remove the weekly autorun
#
# Everything setup does is persistent across reboots. Nothing here needs to be
# repeated when the Mac restarts. Bash 3.2 compatible (macOS default shell).

ROTA_DIR="$(cd "$(dirname "$0")" && pwd)"
AGENTS_DIR="$(dirname "$ROTA_DIR")"
PLIST="$HOME/Library/LaunchAgents/com.rota.weekly.plist"
BRIEF="$ROTA_DIR/ledger/weekly-brief.md"
cd "$ROTA_DIR" || exit 1

have()   { command -v "$1" >/dev/null 2>&1; }
py_has() { python3 -c "import $1" >/dev/null 2>&1; }
ok()     { printf '[ok] %s\n' "$1"; }
warn()   { printf '[!!] %s\n' "$1"; }
note()   { printf '[--] %s\n' "$1"; }

pip_install() {  # try the three sane modes in order, quietly
  pip3 install -q "$1" 2>/dev/null \
    || pip3 install -q --user "$1" 2>/dev/null \
    || pip3 install -q --break-system-packages "$1" 2>/dev/null
}

# ---------------------------------------------------------------- setup ----
do_setup() {
  echo "rota setup — idempotent, safe to rerun"

  have python3 || { warn "python3 not found — install Xcode CLT or Homebrew python first"; exit 1; }

  # 1. dependencies
  if py_has yaml; then ok "pyyaml"; else
    pip_install pyyaml && ok "pyyaml installed" || warn "pyyaml install failed — router/registry needs it"
  fi
  if py_has claude_agent_sdk; then ok "claude-agent-sdk"; else
    pip_install claude-agent-sdk && ok "claude-agent-sdk installed" \
      || note "claude-agent-sdk not installed — live dispatch off (dry-run, ltm, scout all fine)"
  fi

  # 2. memory index + generated agents
  python3 tools/ltm.py index >/dev/null 2>&1 && ok "memory index refreshed" || warn "ltm index failed"
  py_has yaml && { python3 tools/gen_agents.py >/dev/null 2>&1 && ok "agents/*.md regenerated"; }

  # 3. native links (Claude Code / Cowork sees rota + hafiza-ara everywhere)
  mkdir -p "$HOME/.claude/agents" "$HOME/.claude/skills"
  ln -sf "$ROTA_DIR"/agents/*.md "$HOME/.claude/agents/" 2>/dev/null
  ln -sfn "$ROTA_DIR/skills/rota"       "$HOME/.claude/skills/rota"
  ln -sfn "$ROTA_DIR/skills/hafiza-ara" "$HOME/.claude/skills/hafiza-ara"
  ok "linked into ~/.claude (agents + skills)"

  # 4. git — init once, never auto-commit existing work
  if [ -d .git ]; then ok "git repo present"; else
    git init -q -b main && git add -A && git commit -q -m "rota v0.1" && ok "git initialized"
  fi

  # 5. weekly autorun (launchd) — Mondays 09:30, local, zero tokens
  if have launchctl; then
    mkdir -p "$HOME/Library/LaunchAgents" "$ROTA_DIR/ledger"
    cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.rota.weekly</string>
  <key>ProgramArguments</key>
  <array><string>/bin/bash</string><string>$ROTA_DIR/rota.sh</string><string>weekly</string></array>
  <key>StartCalendarInterval</key>
  <dict><key>Weekday</key><integer>1</integer><key>Hour</key><integer>9</integer><key>Minute</key><integer>30</integer></dict>
  <key>StandardOutPath</key><string>$ROTA_DIR/ledger/weekly.log</string>
  <key>StandardErrorPath</key><string>$ROTA_DIR/ledger/weekly.log</string>
</dict></plist>
PLIST_EOF
    launchctl unload "$PLIST" 2>/dev/null
    launchctl load "$PLIST" 2>/dev/null && ok "weekly autorun installed (Mondays 09:30)" \
      || warn "launchd load failed — run 'rota weekly' manually"
  else
    note "launchctl not found (not macOS?) — weekly autorun skipped"
  fi

  # 6. `rota` alias — one word from any terminal
  [ -f "$HOME/.zshrc" ] || touch "$HOME/.zshrc"
  if ! grep -q "alias rota=" "$HOME/.zshrc"; then
    printf '\n# rota orchestrator (added by rota.sh setup)\nalias rota='\''bash %s/rota.sh'\''\n' "$ROTA_DIR" >> "$HOME/.zshrc"
    ok "alias added to ~/.zshrc — open a new terminal, then just: rota status"
  else
    ok "alias present"
  fi

  # 7. clean up the delivery leftovers this system shipped in with
  [ -d "$AGENTS_DIR/_to_delete-rota-delivery" ] && rm -rf "$AGENTS_DIR/_to_delete-rota-delivery" && ok "removed _to_delete-rota-delivery"
  [ -d "$AGENTS_DIR/_to_delete-claude-yanlis-hafiza" ] && note "_to_delete-claude-yanlis-hafiza still there — yours to delete when ready"

  echo
  do_status
}

# --------------------------------------------------------------- status ----
do_status() {
  echo "rota status — $ROTA_DIR"
  have python3 && ok "python3 $(python3 -V 2>&1 | cut -d' ' -f2)" || warn "python3 missing"
  py_has yaml  && ok "pyyaml" || warn "pyyaml missing → bash rota.sh setup"
  py_has claude_agent_sdk && ok "claude-agent-sdk (live dispatch on)" || note "claude-agent-sdk off — dry-run/ltm/scout still work"
  python3 tools/ltm.py stats 2>/dev/null | sed -n '3p' | sed 's/^/[ok] index: /' || warn "index unreadable"
  [ -L "$HOME/.claude/skills/rota" ] && ok "skills linked" || warn "skills not linked → setup"
  agents_n=$(ls "$HOME/.claude/agents/"*.md 2>/dev/null | wc -l | tr -d ' ')
  [ "$agents_n" -gt 0 ] && ok "agents linked ($agents_n)" || warn "agents not linked → setup"
  [ -d .git ] && ok "git ($(git log --oneline 2>/dev/null | wc -l | tr -d ' ') commits)" || note "no git repo"
  if have launchctl; then
    launchctl list 2>/dev/null | grep -q com.rota.weekly && ok "weekly autorun loaded (Mon 09:30)" || note "weekly autorun off → setup (or rota auto-off was used)"
  fi
  pending=$(cat "$AGENTS_DIR"/memory/_inbox/*.md 2>/dev/null | grep -c '^- \[ \]')
  props=$(ls proposals/*.md 2>/dev/null | wc -l | tr -d ' ')
  runs=$(cat ledger/usage.jsonl 2>/dev/null | wc -l | tr -d ' ')
  note "inbox pending: ${pending:-0} · proposals: $props · dispatches logged: ${runs:-0}"
  [ -f "$BRIEF" ] && note "last weekly brief: $(sed -n '1p' "$BRIEF")"
  return 0
}

# --------------------------------------------------------------- weekly ----
do_weekly() {
  today=$(date +%F)
  {
    echo "# rota weekly brief — $today"
    echo
    echo "## Tokens by route"
    echo '```'
    if py_has yaml; then python3 -m router report 2>&1; else echo "pyyaml missing — run setup"; fi
    echo '```'
    echo
    echo "## Scout"
    echo '```'
    python3 tools/scout.py --limit 3 2>&1
    echo '```'
    echo
    echo "## Memory inbox — pending review"
    if cat "$AGENTS_DIR"/memory/_inbox/*.md 2>/dev/null | grep '^- \[ \]'; then :; else echo "(empty — nothing to review)"; fi
    echo
    echo "## Proposals awaiting a decision"
    props_list=$(ls proposals/*.md 2>/dev/null | sed 's|proposals/|- |')
    [ -n "$props_list" ] && echo "$props_list" || echo "(none)"
    echo
    echo "Ritual: promote checked inbox facts → CLAUDE.md / memory/*.md; approve or delete proposals; tune the most expensive route."
  } > "$BRIEF"
  cat "$BRIEF"
  if have osascript; then
    pending=$(grep -c '^- \[ \]' "$BRIEF" 2>/dev/null)
    osascript -e "display notification \"Brief ready — ${pending:-0} item(s) pending. See ledger/weekly-brief.md\" with title \"rota weekly\"" 2>/dev/null
  fi
}

# -------------------------------------------------------------- dispatch ---
case "${1:-status}" in
  setup)    do_setup ;;
  status)   do_status ;;
  weekly)   do_weekly ;;
  run|routes|report) exec python3 -m router "$@" ;;
  serve)
    py_has fastapi || { echo "install first: pip install -r service/requirements.txt" >&2; exit 1; }
    exec python3 -m uvicorn service.app:app --host 127.0.0.1 --port "${2:-8787}" ;;
  build)    shift; exec python3 -m pipeline.weekly "$@" ;;
  auto-off) launchctl unload "$PLIST" 2>/dev/null; rm -f "$PLIST"; ok "weekly autorun removed" ;;
  *)        echo "usage: rota {setup|status|weekly|run \"...\"|serve|build|routes|report|auto-off}"; exit 2 ;;
esac
