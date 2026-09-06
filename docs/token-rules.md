# Token rules — the systemic standard

Every rule here exists because context is billed twice: once as money,
once as attention — a model reasoning over irrelevant context produces
worse answers, not just pricier ones. These rules bind every session,
skill, and agent in this ecosystem.

## 1. Resident bytes are rent

Anything always loaded — CLAUDE.md, skill descriptions, MCP tool schemas —
is paid on every single request. Budget them like rent:

- CLAUDE.md ≤ 100 lines. Overflow moves to `memory/` and is retrieved.
- Skill `description` ≤ ~40 words, written to fire on real phrasing
  (agent-kit standard). The body is pay-per-use; the description is not.
- MCP servers with unused tool schemas get disconnected. Deferred loading
  (ToolSearch-style) where the platform offers it.

## 2. Route before you load

One request → one route → one capability's context. The three tiers:

| Tier | Mechanism | Cost |
| --- | --- | --- |
| 0 | trigger regex over the registry, Turkish-suffix tolerant, phrase beats word | 0 tokens |
| 1 | haiku classifier, route table only | ~300 tokens |
| 2 | one worker, route-scoped tools | the job itself |

Loading two skills for one job means the routing failed — fix the
triggers, do not widen the load. Trigger edits are held to
`tools/eval_routes.py`, which measures what fraction of real requests
Tier-0 resolves for free — the number that decides what routing costs.

## 3. Model tiering — CONTESTED (2026-09-06)

> **This rule and current practice disagree, and the disagreement is Kerem's to
> settle, not this document's.** The rule says cheapest model that survives the
> job. On 2026-09-06 Kerem set every lead to Opus 5 / high and verification to
> max. Both positions are defensible — the rule optimises per-call cost, the
> decision optimises for not shipping a wrong answer that costs a day to undo —
> and this file will not quietly resolve it in favour of the older text.
> Until Kerem says otherwise, the standing instruction wins and the rule below
> describes intent, not practice.

**Mechanism, whichever way it settles:** `CLAUDE_CODE_SUBAGENT_MODEL_FORCE`
enforces the choice rather than leaving it a preference. A rule with no
enforcement drifts back to habit, which is how this rule and practice came to
disagree without anyone noticing.

Cheapest model that survives the job: haiku for triage, recall and
mechanical transforms; sonnet as the working default; opus/deep only for
planning and adversarial verification (mimar/doğrulayıcı roles). The
tier lives in the registry, not in habit.

## 4. Context carries conclusions, not evidence

Subagents read the files, run the greps, hold the dumps — and return
structured findings. Raw file contents never cross an agent boundary.
Corollary for replies: tables for data, prose for reasoning, no restating
the request, no recap of steps.

## 5. Memory beats history

Re-reading old conversations is the most expensive way to remember.
The vault replaces it: hot tier (CLAUDE.md + DEVAM.md, ~2 files, always),
warm tier (FTS5 search, ≤ ~800 tokens injected), cold tier (full file
only when a citation demands it). New chats are ~16x the marginal cost of
continuing one — one conversation per topic.

## 6. Writes are distilled and gated

A durable fact is one sentence, verifiable, source-stamped
(`MEMORY+ … → _inbox → review`). Never paragraphs, never inferred, never
straight into canonical files. A wrong memory is worse than no memory —
it gets injected into every future request that matches it.

## 7. Cache-shaped prompts

Stable prefix, volatile tail. System prompts and route tables change
rarely and in whole; timestamps, request text, and memory blocks go last.
This keeps prompt-cache hit rates high on every platform that caches.

## 8. Budgets are contracts, not vibes

Every route declares S/M/L: max turns and a target output size injected
into the worker's prompt. Exceeding budget is a defect to fix in the
registry, not a mood of the model.

## 9. Measure, then cut

The ledger (`ledger/usage.jsonl`, `python -m router report`) says which
route actually burns tokens. Optimize the top line of the report, not the
rule you most recently read about. Anything uninstrumented is assumed
expensive.

## 10. Zero-token paths are the best paths

If a regex, a SQL query, or 30 lines of Python answers deterministically,
no model call happens at all. Tier-0 routing, FTS5 recall, the scout's
scoring — all deliberately model-free. The best prompt is the one never
sent.


---

# Added 2026-09-06

The network rebuilt three of the rules above from scratch in a single day
without knowing this file existed. That is the archive failure this document is
supposed to prevent, so what follows is folded in here rather than left on the
board: **one authority, cited from elsewhere, never restated.**

## 11. A report is a fixed receipt, not prose

Measured 2026-09-06: inter-session messages were **39% of the hub's context**,
1.6 MB across 582 records in one day. Rule 4 said "conclusions, not evidence";
it was not concrete enough to be obeyed. The concrete form:

```
[ORK] RESULT <role> → <role> | <subject, max 8 words>
DID: <one line, what changed>
CHECK: <command → result, or verdict → source> [~<k> tokens]
PATH: <absolute path(s)>
NEEDS: nothing | hub: <one line> | Kerem: <one line>
```

The `[~<k> tokens]` suffix is the task's spend in thousands. **Measure it, do
not estimate it**, and measure a task rather than a window:
`spend.py --mark` before, `spend.py --from-call N` after. `--since-calls` is a
rolling window whose successive readings overlap; every figure reported on
2026-09-06 was taken that way and is cumulative, not per-task. The
first figure this network reported was typed rather than read and was wrong by
roughly an order of magnitude; a number typed into a receipt reads as measured
because it is written down, which is the failure the receipt was added to avoid.

The honest limit: the transcript records usage per API call, not per task, so
`--since-calls` is the closest scope available without marking task boundaries.
Say which scope you used. Note also that cache reads dwarf everything else —
41M against 824k of new input over 150 calls in one measured window — so a
receipt figure counts new input plus output and is not the whole bill. It was added
2026-09-06 in place of a four-session single-agent baseline: the same ratio
arrives from real work instead of a reconstruction, and costs nothing per
message. Anthropic measures multi-agent systems at roughly 15× single-chat
tokens and advises proving the need against a single-agent baseline; this is how
this network is proving it. Design of the baseline that was declined, and what it
would not have settled: `~/.claude/orkestra/proposals/2026-09-06-single-agent-baseline.md`.

ACK one line or nothing — silence is acceptance. FYI two lines. QUESTION is the
decision in one sentence, then the options. One message per work session, not per
item.

Never send reasoning, method, corrections to your own method, lessons learned, or
what you rejected. None of it is discarded; it goes in the file `PATH` names, in
your charter, or in the observation log. It does not go into someone else's
context.

### Two findings that bear on why this network exists

Recorded beside rule 11 because they qualify what the receipt measures, and both
are uncomfortable enough that paraphrasing them would soften them.

**Anthropic's stated mechanism:** *"multi-agent systems work mainly because they
help spend enough tokens"* — token usage alone explained **80% of the variance**
in their eval. If that holds here, most of what this network buys is spending,
not structure.

It is not established that it holds. Their 15× figure measures an orchestrator
fanning out parallel workers against a chat baseline; this network is neither.
Its findings come from cross-lane **review**, a different mechanism that their
sources do not speak to. **We are outside the measured region, not safely inside
it.** The ledger at `~/.claude/orkestra/baseline/ledger.md` is twenty real tasks
recorded as they happen — the cheapest thing that would begin to tell.

**One judge, not a jury.** Anthropic tried multiple judges per component and
found a single call with a single prompt, scoring 0.0–1.0 plus pass/fail, "the
most consistent and aligned with human judgements". The one-verifier design here
matches their practice.

*Correction kept visible:* research reported earlier the same day, from outside
literature, that juries of cheaper models correlate better with human judgement
and that the one-verifier rule ran against the evidence. Anthropic's own
experiment found the opposite. The evidence is mixed; the earlier note was
one-sided. Both stay on the record rather than the losing one being deleted —
a rule whose contrary evidence has been erased is a rule nobody can re-examine.

## 12. Done means a check passed, and the check is named

`CHECK` carries a command and its result, a verdict and whose it is, or a diff.
Your own assessment is not a check. A report that says "verified" without naming
what was run is prose wearing a receipt's clothes.

## 13. The lead contract replaces asking per item

Board §0 states what each lane may do alone, what it queues for Kerem, and what
wakes him. Read it once and work from it. A message asking permission for
something the contract already permits costs the same as the work.

## 14. A defect found once is a class, not a fact

Run the same test over every artefact in the same decision before the note goes
out. Google Fonts was found on colaunch.app and then missed on six tools in the
same session — the second sweep was never run, because the first finding felt
like the answer.

The cost argument: re-opening a decision costs more than testing the other six
artefacts while the test is already written.

## 15. A sweep that cannot see is worse than no sweep

`grep` on this machine is **ugrep 7.8.4** and skips `.git/` in recursive mode.
`--hidden` does not help, and naming the directory explicitly still returns
nothing. Every recursive secret sweep was therefore blind to tokens embedded in
remote URLs — eleven of them, missed by three leads.

Use `find … -type f -print0 | xargs -0 grep -l`, `rg --hidden`, or `gitleaks` for
any sweep that must see `.git/`. **A clean grep sweep over `.git/` proves
nothing.** Likewise, a static count of assertions is not a test result:
`grep -c 'check('` misses assertions inside loops and conditionals, in both
directions. Run the suite.

---

# Correctness rules kept here, 2026-09-06

Not about tokens. They live here because two documents drift and one does not,
and because every one of them was learned by getting it wrong.

- **Decimal comma.** Numbers from EU or German official text use it —
  `3,251` is three point two five one; `75,99` is a price. Every parsed figure
  gets a magnitude test before use: a thousands-separator misread lands on a
  plausible-looking value, not an obvious break.
- **Retrieval date and data vintage are two fields, never one.** A figure read
  yesterday can be superseded today — the ETS price moved 74.66 → 75.99 within a
  day.
- **Counts carry a measured-at or they are folklore.** Against a live system a
  count is stale the moment it is written. Either date it or publish the command
  that produces it. Established twice on 2026-09-06, the second time by
  publishing stale numbers in the document that recorded the first.
- **A tool named in a charter is described from at least one real call.** A
  description written from the installed surface rather than from use is how
  `context7` sat in a charter for two weeks without the lane ever needing it.

---

## Keeping this file the authority

The receipt shape diverged **once, within one exchange** of the board and the
orkestra skill being pointed here: the skill gained the token suffix and this
file did not. Citing an authority does not make it one. Any change to a rule
lands here first, and the copy is updated from it — never the reverse. If you are
editing a rule in `board.md` or a skill, you are editing the wrong file.

## Superseded by this section

- **Rule 4's corollary** ("tables for data, prose for reasoning") is superseded
  by rule 11 for inter-session messages. It still holds for replies to Kerem.
- **The three-line summary** in `rota/skills/orkestra/SKILL.md` is superseded by
  rule 11's five-line receipt.

## Not superseded, and worth saying so

Rules 1, 2, 5, 6, 7, 8, 9 and 10 were re-derived or re-confirmed by this week's
work and stand unchanged. Rule 10 in particular: the census, the lexical index
and the scout's scoring all still run without a model call.
