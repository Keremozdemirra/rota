# The platform — rota as a service

A web front end where someone enters their own Anthropic key and runs the
orchestrator, the workflows and the sub-agents on it. Their key, their spend,
their artefacts.

## Read this part first

Executing agents server-side means this server holds the caller's API key in
plaintext memory for the length of their session. No amount of engineering
removes that: the process that calls `api.anthropic.com` needs the key. Every
hosted BYO-key agent platform has this property, whether or not it says so.

What the design does instead is shrink the window and bound the damage:

| Risk | What stops it |
|---|---|
| Key written to disk or a log | Held in one in-memory dict; `Secret.__repr__` is redacted; nothing serialises it |
| Key echoed back to the client | Only an opaque token leaves the server; the UI clears the input on submit |
| Stolen token runs up a bill | Per-session USD cap enforced by the SDK's `max_budget_usd`, per phase |
| Key outlives the session | 30-minute sliding TTL, plus an explicit wipe button |
| Guest run reads the operator's data | `setting_sources=[]`, per-run temp `cwd`, memory recall forced off |
| Guest run billed to the operator | Ambient Claude credentials blanked in the child env |

That last row is the one that is easy to miss. The SDK merges `options.env`
over `os.environ` rather than replacing it, so a guest run would otherwise
inherit the operator's `CLAUDE_CODE_OAUTH_TOKEN` — and a subscription token
that outranks the supplied key means the operator quietly pays for a stranger's
work. `runner.AMBIENT_CREDENTIALS` blanks them.

**If you would rather not hold anyone's key at all**, the alternative is a
browser-only client calling Anthropic directly with the
`anthropic-dangerous-direct-browser-access` header. You then cannot run the
orchestrator, because there is no server in the loop to run it. That is the
whole trade: server-side agents require key custody. Pick knowingly.

## Install and run

```bash
cd ~/agents/rota && pip install -r service/requirements.txt
```

FastAPI, uvicorn and pydantic are new dependencies and they live in
`service/requirements.txt`, not the root one — the router stays on PyYAML.

```bash
cd ~/agents/rota && python3 -m uvicorn service.app:app --port 8787
```

Open <http://127.0.0.1:8787>.

If the key check fails with `CERTIFICATE_VERIFY_FAILED` on a fresh macOS
Python, run `/Applications/Python\ 3.x/Install\ Certificates.command` once.

## Shape

```
browser  ──POST /api/session──▶  keyvault   verify against /v1/models, mint token
         ◀──token, no key─────

browser  ──POST /api/run─────▶  runner     phase 1 ─┐
         ◀──SSE phase events──             phase 2 ─┼─ each an SDK query()
                                            phase 3 ─┤   with env={key}
                                            phase 4 ─┘   and max_budget_usd

                                 workspace  /tmp/rota-runs/<run_id>/
                                 swept daily; artefacts served back by token
```

Streaming is server-sent events over `fetch`, not `EventSource` — the token
travels in an `Authorization` header, and `EventSource` cannot set headers.
There is no cookie anywhere, which is also why there is no CSRF surface.

## Endpoints

| Method | Path | Notes |
|---|---|---|
| `POST` | `/api/session` | `{api_key, spend_cap_usd}` → token. Validates the key first. |
| `GET` | `/api/session` | Budget left, runs so far, minutes to expiry. |
| `DELETE` | `/api/session` | Drops the key from memory immediately. |
| `GET` | `/api/workflows` | What can be run, and the phases each one has. |
| `POST` | `/api/run` | `{brief, workflow}` → SSE stream. Rate limited per token. |
| `GET` | `/api/run/{id}/file/{path}` | One artefact. Path traversal is rejected. |

## Workflows

Defined declaratively in `service/workflows.py`. A workflow is phases; a phase
is one agent with one model, one tool set, one turn limit and a share of the
session cap.

**`single`** — one agent, all the usual tools. The cheap path, and the right
one for anything that is a job rather than a project.

**`project`** — architect (opus) → implementers (sonnet, parallel, one per
work package) → integrator (sonnet) → reviewer (opus). The fan-out is driven
by the plan: the architect writes work-package lines in a fixed format,
`runner.parse_packages` matches exactly that format, and up to four agents run
in parallel. The strictness is load-bearing — a looser parser spawns an agent
per bullet in the Risks section.

**`video-site`** — architect → media producer (holds the video-mcp tools) →
site builders (parallel) → reviewer. The media phase produces the clips and the
exact `<video>` markup; the build phase is told to embed that markup verbatim
rather than inventing filenames, which is the failure this split exists to
prevent.

Adding one is a `Workflow` literal. Nothing else changes.

## Budget arithmetic

Each phase gets `spend_cap_usd × budget_share`, and the shares sum to 1.0 per
workflow. `max_budget_usd` makes the SDK stop the phase rather than discovering
the overrun in the invoice. Before each phase the runner re-checks the session's
remaining budget, so a phase that ran long cannot leave the next one unfunded
without an explicit error the caller sees.

## Deployment

One process. `keyvault.Vault` is in-memory, so two workers do not share
sessions. Scale by running isolated instances behind a router that keys on the
session token, not by adding workers to this one — and if that starts to look
like real infrastructure, the honest move is to stop holding keys and let
clients bring their own runner instead.

Terminate TLS in front of it. A BYO-key form over plain HTTP is a credential
harvester with extra steps.

Set before exposing it anywhere:

```bash
export ROTA_SPEND_CAP_USD=2.00     # hard ceiling; a client may ask for less
export ROTA_SESSION_TTL=1800
export ROTA_MAX_SESSIONS=50
export ROTA_RATE_LIMIT=6           # runs per minute per token
export ROTA_MAX_FANOUT=4
export ROTA_RUNS_DIR=/var/tmp      # workspaces live under <dir>/rota-runs
```

## What this is not

Not multi-tenant infrastructure: no database, no auth beyond the key itself,
no quota that survives a restart. Not a sandbox — agents run as the server
user with `acceptEdits` inside their run directory, which is fine for a
demo on your own machine and not fine for the open internet without a
container per run. Not audited. If a client's work is genuinely sensitive,
the right answer is to run this on their machine, not yours.
