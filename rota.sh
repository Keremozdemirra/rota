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
#   rota drift                           installed-vs-recorded check (also runs weekly)
#   rota diagram                         re-render docs/diagrams/*.json → .html
#   rota tokens                          where context goes, trend vs last run
#   rota stage-skill <name>              safe editable copy (symlinks dereferenced)
#   rota vitals <repo>|--gaps <term>     verdict from the local ecosystem census
#   rota lessons                         what the observation backlog is waiting on
#   rota daily                           pull the census, file arrivals that pass vetting.yaml
#   rota mcp-health                      do the configured MCP endpoints still answer?
#   rota auto-off                        remove the weekly autorun
#
# Everything setup does is persistent across reboots. Nothing here needs to be
# repeated when the Mac restarts. Bash 3.2 compatible (macOS default shell).

ROTA_DIR="$(cd "$(dirname "$0")" && pwd)"
AGENTS_DIR="$(dirname "$ROTA_DIR")"
PLIST="$HOME/Library/LaunchAgents/com.rota.weekly.plist"
DPLIST="$HOME/Library/LaunchAgents/com.rota.daily.plist"
ARRIVALS="$ROTA_DIR/ledger/arrivals.md"
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
    cat > "$DPLIST" <<DPLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.rota.daily</string>
  <key>ProgramArguments</key>
  <array><string>/bin/bash</string><string>$ROTA_DIR/rota.sh</string><string>daily</string></array>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>10</integer><key>Minute</key><integer>15</integer></dict>
  <key>StandardOutPath</key><string>$ROTA_DIR/ledger/daily.log</string>
  <key>StandardErrorPath</key><string>$ROTA_DIR/ledger/daily.log</string>
</dict></plist>
DPLIST_EOF
    launchctl unload "$DPLIST" 2>/dev/null
    launchctl load "$DPLIST" 2>/dev/null && ok "daily census pull installed (10:15, after the 07:00 UTC run)" \
      || warn "launchd load failed for the daily job"
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
    launchctl list 2>/dev/null | grep -q com.rota.daily && ok "daily census pull loaded (10:15)" || note "daily pull off"
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
# Diagrams are derived artifacts: the .json in docs/diagrams/ is the source,
# the .html is output. Re-render is cheap; what it cannot fix is a source whose
# *content* went stale, which is why the weekly prints the source dates next to
# the drift result and lets a human join the two.
do_diagram() {
  ARCHIFY="$HOME/.claude/skills/archify/bin/archify.mjs"
  [ -f "$ARCHIFY" ] || { warn "archify not installed — skipping diagrams"; return 0; }
  found=0
  for src in "$ROTA_DIR"/docs/diagrams/*.*.json; do
    [ -e "$src" ] || continue
    found=1
    base=$(basename "$src"); kind=$(echo "$base" | rev | cut -d. -f2 | rev)
    out="${src%.*.json}.html"
    if node "$ARCHIFY" render "$kind" "$src" "$out" >/dev/null 2>&1; then
      ok "$base → $(basename "$out")"
    else
      warn "$base failed to render — run: node $ARCHIFY validate $kind $src"
    fi
  done
  [ "$found" = 1 ] || note "no diagram sources in docs/diagrams/"
}

# Stage a skill for editing without touching the live one.
#
# 28 of 36 skills here are symlinks into per-agent repositories. `cp -R` copies
# a symlink AS a symlink, so the "staged copy" points back at the live file and
# every edit lands in production — silently, with a successful exit code, and a
# diff that reports no difference because it is comparing a file to itself.
# Dereference, then assert the boundary exists before trusting it.
do_stage_skill() {
  name="${1:?usage: rota stage-skill <skill-name>}"
  src="$HOME/.claude/skills/$name"
  [ -e "$src" ] || { warn "no such skill: $name"; return 1; }
  real=$(cd "$src" && pwd -P)
  dest="$HOME/.claude/projects/-Users-keremozdemir-agents/skill-updates/$(date +%F)/$name"
  rm -rf "$dest"; mkdir -p "$dest"
  cp -RL "$real/." "$dest/"
  chmod -R u+w "$dest"
  links=$(find "$dest" -type l | wc -l | tr -d ' ')
  [ "$links" = 0 ] || { warn "$links symlink(s) survived the copy — do not edit"; return 1; }
  [ "$(cd "$dest" && pwd -P)" != "$real" ] || { warn "staged path resolves to the live one"; return 1; }
  ok "staged $name → $dest"
  note "live source: $real"
  note "install with: cp \"$dest/SKILL.md\" \"$real/SKILL.md\""
}

# The census is produced in CI every morning; a local copy nobody refreshes is
# a stale answer that looks current. This pulls it and files the arrivals that
# pass vetting.yaml — quietly, into the ledger. Nothing interrupts: the weekly
# brief is where they get read, so there is one place to look, not two.
do_daily() {
  mkdir -p "$ROTA_DIR/ledger"
  out=$(python3 tools/vitals.py --sync --days 1 2>&1)
  {
    echo "## $(date +%F)"
    echo '```'
    echo "$out"
    echo '```'
    echo
  } >> "$ARRIVALS"
  echo "$out"
}

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
    echo "## Drift — recorded vs actual"
    echo '```'
    python3 tools/drift.py --emit 2>&1
    echo '```'
    echo
    echo "## Context cost — is CLAUDE.md §8 holding?"
    echo '```'
    python3 tools/tokens.py 2>&1
    echo '```'
    echo
    echo "## Diagrams — re-rendered from source"
    echo '```'
    do_diagram 2>&1
    echo '```'
    echo
    echo "## MCP endpoints — does the record still describe reality?"
    echo '```'
    python3 tools/mcp_health.py 2>&1
    echo '```'
    echo
    echo "## Ecosystem census — what the ground looks like"
    echo '```'
    python3 tools/vitals.py --summary 2>&1
    echo '```'
    echo
    echo "## Census candidates — possible products, components or contributions"
    echo '```'
    python3 tools/vitals.py --candidates 2>&1
    echo '```'
    echo "Full list: ledger/census-candidates.md"
    echo
    echo "## Arrivals — what the daily census brought, after vetting.yaml"
    echo '```'
    if [ -f "$ARRIVALS" ]; then tail -28 "$ARRIVALS"; else echo "(no daily run yet — rota setup installs it)"; fi
    echo '```'
    echo
    echo "## Lessons — captured, waiting to be acted on"
    echo '```'
    python3 tools/lessons.py 2>&1
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
  drift)    exec python3 tools/drift.py "${@:2}" ;;
  diagram)  do_diagram ;;
  stage-skill) shift; do_stage_skill "$@" ;;
  tokens)   exec python3 tools/tokens.py "${@:2}" ;;
  vitals)   exec python3 tools/vitals.py "${@:2}" ;;
  lessons)  exec python3 tools/lessons.py "${@:2}" ;;
  mcp-health) exec python3 tools/mcp_health.py "${@:2}" ;;
  daily)    do_daily ;;
  run|routes|report) exec python3 -m router "$@" ;;
  serve)
    py_has fastapi || { echo "install first: pip install -r service/requirements.txt" >&2; exit 1; }
    exec python3 -m uvicorn service.app:app --host 127.0.0.1 --port "${2:-8787}" ;;
  build)    shift; exec python3 -m pipeline.weekly "$@" ;;
  auto-off) launchctl unload "$PLIST" 2>/dev/null; rm -f "$PLIST"; launchctl unload "$DPLIST" 2>/dev/null; rm -f "$DPLIST"; ok "weekly and daily autoruns removed" ;;
  *)        echo "usage: rota {setup|status|weekly|daily|drift|diagram|tokens|vitals|lessons|mcp-health|stage-skill|run \"...\"|serve|build|routes|report|auto-off}"; exit 2 ;;
esac
