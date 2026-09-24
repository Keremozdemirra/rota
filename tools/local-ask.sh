#!/usr/bin/env bash
# One question to a local Ollama model, no agent loop, thinking off. The fast path for
# footwork on text you already have: pipe the text in, ask one thing, get one answer.
#   local-ask.sh [-m fast|careful|code|small|<model>] "<instruction>" < file   or   cmd | local-ask.sh "<instruction>"
# Roles and the measurements behind them are in local-models.sh; default fast. Nothing leaves the machine.
set -euo pipefail
source "$(dirname "$0")/local-models.sh"
MODEL=fast
while getopts "m:" o; do case $o in m) MODEL=$OPTARG;; *) exit 2;; esac; done
shift $((OPTIND-1))
INSTR="${1:?instruction}"; INPUT="$(cat)"
MODEL=$(use_model "$MODEL")
python3 - "$MODEL" "$INSTR" "$INPUT" <<'PY'
import json, sys, urllib.request
model, instr, text = sys.argv[1], sys.argv[2], sys.argv[3]
body = {"model": model, "stream": False, "think": False,
        "messages": [{"role": "user", "content": f"{instr}\n\n<text>\n{text}\n</text>"}],
        "options": {"temperature": 0.2, "num_ctx": 16384}}
req = urllib.request.Request("http://127.0.0.1:11434/api/chat", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=600) as r:
    d = json.load(r)
print(d["message"]["content"].strip())
print(f"[{model}: {d.get('prompt_eval_count',0)} in, {d.get('eval_count',0)} out, {d.get('total_duration',0)/1e9:.1f}s]", file=sys.stderr)
PY
