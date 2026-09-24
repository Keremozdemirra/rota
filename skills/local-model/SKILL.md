---
name: local-model
description: Sends mechanical text work to local Ollama models (Qwen3.6 fast, Qwen3.8 careful, Qwen3-Coder) so it never reaches the Max plan; nothing leaves the machine. Use without being asked whenever the job is footwork over material not yet in context: summarising three or more files, classifying or tagging a list, pulling fields from many records, a translation draft, a boilerplate or test-scaffold draft, census notes. Also on "yerel modelle yap", "qwen ile", "kotayi harcama", "run this locally". Not for decisions, money, credentials, legal text, anything published, or work needing tools or the web; those stay on Claude. Model policy: ~/agents/MODELS.md.
---

# Local model

Two tools under `~/agents/rota/tools/`, both on Ollama at 127.0.0.1:11434.
Nothing leaves the machine, nothing counts against the subscription.

## local-ask.sh, the fast path

One question about text you already have. No agent loop, thinking off.

```bash
cat file.md | ~/agents/rota/tools/local-ask.sh "Summarise in three lines."
tail -200 log.md | ~/agents/rota/tools/local-ask.sh -m careful "List the dates mentioned."
```

Stdin is the text, the argument is the instruction, stdout is the answer, stderr
prints model, token counts and seconds. Batch over files with a shell loop; the
model stays loaded between calls.

## local-claude.sh, the agent path

A Claude Code run whose model is local. Same tools as a sub-agent (Read, Grep,
Glob by default; add Write or Bash with `-t`), so it can find and read files on
its own. Measured 2026-09-24 on the fast role, idle GPU: a one-file lookup
answered correctly in 5 min 50 s, because every turn re-reads Claude Code's own
system prompt. Treat it as experimental; reach for it only when the job truly
needs to look things up. local-ask.sh is the default.

```bash
~/agents/rota/tools/local-claude.sh -n 8 "Read every SKILL.md under ~/.claude/skills and list the ones that mention Make.com."
~/agents/rota/tools/local-claude.sh -m code -t Read,Grep,Glob,Write "Write tests for rota/tools/scout.py into rota/tests/test_scout.py."
```

## Which model

Pass a role with `-m`; the scripts resolve it through `tools/local-models.sh`,
which also holds the measurements (2026-09-24, idle M5 Pro 64 GB):

| Role | Model | Use for | Inbound class /60 | All fields /60 | Code /11 | tok/s |
|---|---|---|---|---|---|---|
| `fast` (default) | qwen3.6:35b-a3b-nvfp4 | summaries, classification, extraction, bulk | 60 | 59 | 10 | 47.6 |
| `careful` | qwen3.8:27b-nvfp4 | small batches where every field must be right | 60 | 60 | 10 | 18.2 |
| `code` | qwen3-coder:30b | code and tests | | | 11 | |
| `small` | qwen3:8b | reproducing the studio kits' published figures | 58 | 53 | 7 | 35.1 |

A full model name also works. A model that is not pulled falls back to qwen3:8b.
Embeddings stay on bge-m3 (`ltm.py`).

## Rules

- Read the output before using it; a local model invents less when the text is
  in front of it, and still invents.
- Prompts and files stay on this machine, so client material may go through it;
  credentials still never go into a prompt.
- Measure: stderr gives tokens and seconds; a job slower than doing it on Claude
  is not footwork.
