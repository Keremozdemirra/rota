#!/usr/bin/env bash
# One command for the optimisation loop: every living document the hub owns or
# every session reads, through every mechanical check we have. Prints one line
# per file with hard failures, then a total. Exit 1 when any hard failure remains.
# Living documents only: reviews/, audit/, dated proposals and log entries are
# records and are cleaned by their authors, by hand.
set -u
T=~/agents/rota/tools
M=~/.claude/projects/-Users-keremozdemir-Library-Application-Support-Claude-scratch-workspaces-a559a02a-fb00-42c6-8497-a2ddb0df2ccc-3f5347f2-0958-44f9-a5e0-a9522eb15945-scratch-2026-09-05-639b4c/memory
FILES=(
  ~/.claude/orkestra/board.md ~/.claude/orkestra/tasks.md ~/.claude/orkestra/facts.md
  ~/.claude/orkestra/allocation.md ~/.claude/orkestra/log.md ~/.claude/orkestra/audit-2026-09.md
  ~/.claude/orkestra/reviews/README.md
  ~/.claude/orkestra/leads/*.md
  ~/agents/rota/skills/orkestra/SKILL.md ~/agents/rota/skills/craft/SKILL.md ~/agents/rota/skills/rota/SKILL.md
  "$M"/*.md
  ~/agents/kariyer/applications/*.md
  ~/agents/projects/zemin360/basvuru-metinleri.md ~/agents/projects/zemin360/sunum.html ~/agents/projects/zemin360/mvp/README.md
)
total=0; bad=0; n=0
for f in "${FILES[@]}"; do
  [ -f "$f" ] || continue
  n=$((n+1))
  if ! python3 -c "import sys;open(sys.argv[1],encoding='utf-8').read()" "$f" 2>/dev/null; then
    echo "UTF8   $f"; bad=$((bad+1)); continue
  fi
  line=$(python3 "$T/slopcheck.py" "$f" | head -1)
  hard=$(printf '%s' "$line" | sed -E 's/.*hard failures ([0-9]+).*/\1/')
  soft=$(printf '%s' "$line" | sed -E 's/.*soft flags ([0-9]+).*/\1/')
  total=$((total+hard))
  [ "$hard" -gt 0 ] && bad=$((bad+1))
  printf '%-5s %-4s %s\n' "$hard" "$soft" "${f/#$HOME/~}"
done | sort -rn
echo "---"
echo "path citations in charters:"
for f in ~/.claude/orkestra/leads/*.md; do
  c=$(python3 "$T/pathcheck.py" "$f" 2>/dev/null | grep -cE "does not exist|glob parent missing" || true)
  [ "$c" -gt 0 ] && echo "  $c stale in ${f/#$HOME/~}"
done
echo "---"
# recompute totals (the pipe above ran in a subshell)
th=0; tb=0
for f in "${FILES[@]}"; do
  [ -f "$f" ] || continue
  h=$(python3 "$T/slopcheck.py" "$f" 2>/dev/null | head -1 | sed -E 's/.*hard failures ([0-9]+).*/\1/')
  th=$((th+${h:-0})); [ "${h:-0}" -gt 0 ] && tb=$((tb+1))
done
echo "hard failures: $th in $tb files"
[ "$th" -eq 0 ]
