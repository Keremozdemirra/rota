# Backlog item {{ID}}

## What to build

{{TASK}}

## Where

Everything you write goes under `{{DIR}}`. Do not modify files outside it.
The repository root is read-only context: read it to match conventions, never
edit it.

## Standards this repository already holds itself to

- Python 3.9+, standard library only unless the plan justifies a dependency
  and names it explicitly. PyYAML is already present; nothing else is.
- Comments explain why, never what. A comment restating the line above it
  gets deleted in review.
- No README, no example script, no test scaffold unless the work genuinely
  needs one. Unrequested files are noise.
- Every published coefficient, threshold or rate needs a primary source and
  a date next to it. No source, no number.
- No credential, token or key in any file, ever — including in a test fixture,
  including commented out.
- English for everything written down.

## Definition of done

- It runs. State the exact command that proves it.
- A `unittest` suite covering the failure modes that would actually occur,
  not the happy path restated three times.
- A short `README.md` inside `{{DIR}}` whose last section is
  "What this is not" — the boundary is the useful half.
- The verification phase found nothing above `medium` severity, or the
  findings are written down with the reason they were accepted.

## Out of scope

Anything that changes the router, the registry, the memory protocol, or the
platform service. If the item appears to need one of those, say so in the
plan and build up to that boundary instead of crossing it.
