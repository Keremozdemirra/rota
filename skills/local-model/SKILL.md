---
name: local-model
description: Runs footwork on a local Ollama model (Qwen3 30B) instead of the Max subscription, nothing leaves the machine. Use for bulk or mechanical text jobs: summarising many files, classifying, tagging, translation drafts, data generation, first-pass rewrites, census notes. "yerel modelle yap", "qwen ile", "kotayi harcama", "run this locally", "offload to the local model". Not for decisions, anything touching money, credentials or legal text, or a final answer Kerem will publish; those stay on Claude.
---

# Local model

Two tools under `~/agents/rota/tools/`, both on Ollama at 127.0.0.1:11434.
Nothing leaves the machine, nothing counts against the subscription.

## local-ask.sh, the fast path

One question about text you already have. No agent loop, thinking off.

```bash
cat file.md | ~/agents/rota/tools/local-ask.sh "Summarise in three lines."
tail -200 log.md | ~/agents/rota/tools/local-ask.sh -m qwen3:8b "List the dates mentioned."
```

Stdin is the text, the argument is the instruction, stdout is the answer, stderr
prints model, token counts and seconds. Batch over files with a shell loop; the
model stays loaded between calls.

## local-claude.sh, the agent path

A Claude Code run whose model is local. Same tools as a sub-agent (Read, Grep,
Glob by default; add Write or Bash with `-t`), so it can find and read files on
its own. Measured 2026-09-22: on qwen3:8b it hit its turn limit after four
minutes, and on qwen3:30b it had not finished after twenty while another job
held the GPU. Treat it as experimental; reach for it only when the GPU is idle
and the job truly needs to look things up. local-ask.sh is the default.

```bash
~/agents/rota/tools/local-claude.sh -n 8 "Read every SKILL.md under ~/.claude/skills and list the ones that mention Make.com."
~/agents/rota/tools/local-claude.sh -m qwen3-coder:30b -t Read,Grep,Glob,Write "Write tests for rota/tools/scout.py into rota/tests/test_scout.py."
```

## Which model

`qwen3:30b` for prose and classification, `qwen3-coder:30b` for code, `qwen3:8b`
when speed matters more than quality. `ollama list` shows what is pulled; a
model that is not pulled falls back to qwen3:8b.

## Rules

- Read the output before using it; a local model invents less when the text is
  in front of it, and still invents.
- Prompts and files stay on this machine, so client material may go through it;
  credentials still never go into a prompt.
- Measure: stderr gives tokens and seconds; a job slower than doing it on Claude
  is not footwork.
