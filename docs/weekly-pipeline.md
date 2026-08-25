# The weekly pipeline — one autonomous project a week

There used to be a second cadence: `daily-loop` moved an existing repository
forward by one PR a day. Kerem retired it on 2026 08 25 and asked for nothing
daily anywhere, so this is the only cadence left. Once a week, take one line
from a backlog and turn it into a finished project directory with a plan, an
implementation, an integration pass, an adversarial review and a pull
request.

## The loop

```
BACKLOG.md ── first unchecked Queue item
     │
     ▼
templates/BRIEF.md ── one line becomes a real brief with standards and a
     │                definition of done
     ▼
project workflow ── architect → implementers (parallel) → integrator → reviewer
     │              writing into projects/NNN-slug/
     ▼
ship.sh ── secret scan → branch → commit → push → gh pr create
     │
     ▼
BACKLOG.md ── item checked off, but only after ship.sh returns 0
```

## Run it

```bash
cd ~/agents/rota && python3 -m pipeline.weekly --dry-run
```

Prints the item it would take and the full brief it would hand the architect.
Costs nothing. Read the brief before the first real run — most bad autonomous
builds are bad briefs.

```bash
cd ~/agents/rota && python3 -m pipeline.weekly --cap 10
```

```bash
cd ~/agents/rota && python3 -m pipeline.weekly --item 003 --no-ship
```

`--no-ship` builds into `projects/` and stops before git, which is how to try
a change to the brief template without opening a PR.

## Why the model does not run git

`ship.sh` is the only thing in the pipeline that touches the repository, and it
is deterministic shell you can read in two minutes. An agent with `git push` is
an agent that can rewrite history on one bad turn, and unlike a bad commit that
is not recoverable from the local clone. The script does not force-push, does
not delete branches, and does not commit to the default branch — every weekly
build arrives as a PR a human merges.

It also refuses to commit at all if a credential pattern appears anywhere under
the project directory. The scan is deliberately noisy: a false positive costs
one manual look, a false negative costs a key rotation and a public repository
with a live token in it.

## Scheduling

**GitHub Actions** — `.github/workflows/weekly.yml`, Mondays 05:00 UTC. Needs
one repository secret, `ANTHROPIC_API_KEY`, and installs the Claude Code CLI in
the runner. The job has `contents: write` and `pull-requests: write` and
nothing else. Phase transcripts upload as an artefact for 14 days, which is
where to look when a build comes out wrong.

**launchd**, if you would rather it ran on the Mac against the Max subscription
instead of an API key — the same place `rota.sh setup` installs the weekly
brief job. Owner mode passes no key at all and inherits whatever credentials
the Claude Code CLI already has.

## The brief template is the real interface

`pipeline/templates/BRIEF.md` is where the quality comes from, not the
workflow. It carries the repository's standards (stdlib only, comments explain
why, no unrequested files, no number without a source), the definition of done
(it runs, there is a test suite for real failure modes, the README ends with
"what this is not"), and an explicit out-of-scope list that keeps a project
from wandering into the router or the memory protocol.

When a weekly build comes out wrong, edit this file first. Changing the model
or the workflow is almost never the fix.

## Reading the output

Each phase writes `projects/NNN-slug/.rota-<phase>.md`. `ship.sh` deletes them
before committing — they are for the reviewer, not the repository — so read
them before you ship, or use `--no-ship` when you want to keep them.

`.rota-verify.md` is the one that matters. The reviewer is instructed to assume
the work is wrong and to report an honest short list rather than a padded long
one. If it says "nothing above medium", that is a claim to spot-check, not a
result to trust.

`ledger/weekly.jsonl` accumulates one row per run: item, duration, cost per
phase. After a few weeks it answers the only question that decides whether this
cadence is worth keeping — what a finished project actually costs.

## Backlog discipline

The Queue in `BACKLOG.md` is the priority order. The pipeline takes the top
unchecked item; if that is not what should be built this week, reorder the file
rather than reaching for `--item`. Items should be one line, and small enough
that four parallel implementers can finish them — an item that needs eight work
packages is two items.

## What this is not

Not unattended shipping: it opens a PR, it does not merge. Not a way of moving
existing repositories forward either: this creates new ones, and the loop that
moved existing ones is retired rather than replaced. Not deterministic — the same backlog line will produce a different project on
a different week, and that is the cost of the cadence, not a bug in it.
