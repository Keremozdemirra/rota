# Sourced by local-ask.sh and local-claude.sh: maps a job to the local model that won it.
# Measured 2026-09-24 on the M5 Pro 64 GB, idle machine, Ollama 0.34.0, think off, temperature 0:
#   model                   inbound class /60  visibility all fields /60  code /11  gen tok/s
#   qwen3.6:35b-a3b-nvfp4   60                 59                         10        47.6
#   qwen3.8:27b-nvfp4       60                 60                         10        18.2
#   qwen3-coder:30b         -                  -                          11        -
#   qwen3:8b                58                 53                          7        35.1
# Dropped the same day: qwen3:30b (60, 40 with 13 invalid JSON, 53.1) and gemma4:26b (60, 56, 48.3).
# Sets: venture-studio kits inbound-capture and visibility-watch; code is twelve spec-only tasks, one ambiguous task not scored.
resolve_model() {
  case "$1" in
    fast|"")  echo "qwen3.6:35b-a3b-nvfp4" ;;  # default: summaries, classification, extraction, bulk
    careful)  echo "qwen3.8:27b-nvfp4" ;;      # every field must be right and volume is small; 2.6x slower
    code)     echo "qwen3-coder:30b" ;;
    small)    echo "qwen3:8b" ;;               # the model the studio kits' published figures were taken on
    *)        echo "$1" ;;                     # any pulled model name passes through
  esac
}
use_model() { local m; m=$(resolve_model "$1"); ollama show "$m" >/dev/null 2>&1 && echo "$m" || echo "qwen3:8b"; }
