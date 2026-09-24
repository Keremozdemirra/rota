#!/usr/bin/env bash
# Run a Claude Code job on a local Ollama model instead of the Max subscription.
# For footwork: bulk summaries, classification, translation drafts, data generation,
# anything mechanical that would burn quota. Nothing leaves the machine.
#   local-claude.sh [-m fast|careful|code|small|<model>] [-t tools] [-n max_turns] "<prompt>"     (or prompt on stdin)
# Defaults: role fast (local-models.sh; qwen3:8b if not pulled), tools Read,Grep,Glob, 6 turns.
set -euo pipefail
source "$(dirname "$0")/local-models.sh"
MODEL=fast; TOOLS="Read,Grep,Glob"; TURNS=6
while getopts "m:t:n:" o; do case $o in m) MODEL=$OPTARG;; t) TOOLS=$OPTARG;; n) TURNS=$OPTARG;; *) exit 2;; esac; done
shift $((OPTIND-1))
PROMPT="${1:-$(cat)}"
MODEL=$(use_model "$MODEL")
export ANTHROPIC_BASE_URL="${OLLAMA_HOST:-http://127.0.0.1:11434}" ANTHROPIC_AUTH_TOKEN=ollama ANTHROPIC_API_KEY=""
exec claude -p "$PROMPT" --model "$MODEL" --max-turns "$TURNS" --allowedTools "$TOOLS" 2>/dev/null
