#!/usr/bin/env bash
# Link every skill that any agent repository holds into ~/.claude/skills, so a
# skill one chat adds is loaded by the next chat without anyone running kayit.
# Adds only; never removes or replaces a link that points elsewhere. Idempotent,
# silent when nothing changed. Runs at SessionStart (settings.json) and by hand.
set -u
DEST="$HOME/.claude/skills"; mkdir -p "$DEST"; n=0
for d in "$HOME"/agents/*-agent/skills/* "$HOME"/agents/agent-kit/skills/* "$HOME"/agents/rota/skills/*; do
  [ -f "$d/SKILL.md" ] || continue
  name=$(basename "$d"); t="$DEST/$name"
  if [ -e "$t" ] || [ -L "$t" ]; then continue; fi
  ln -sfn "$d" "$t" && n=$((n+1)) && echo "linked $name <- ${d#$HOME/agents/}"
done
[ "$n" -gt 0 ] && echo "link-skills: $n new skill(s) linked"
exit 0
