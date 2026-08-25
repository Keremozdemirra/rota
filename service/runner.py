"""Execution: run a workflow on the caller's key, in a workspace of its own.

Two things here are load-bearing.

First, the key never becomes process state. `ClaudeAgentOptions.env` is passed
per call and the SDK hands it to the CLI subprocess it spawns; nothing mutates
os.environ, so two concurrent runs on two different keys cannot bleed into each
other. `max_budget_usd` is set from what is left of the caller's cap, so the
SDK stops the run rather than the invoice discovering it later.

Second, a guest run gets none of the operator's context. `setting_sources=[]`
means no user or project settings, no local skills, no CLAUDE.md. `cwd` is a
fresh per-run directory, not the vault. rota's own routes carry `memory: true`
because they serve their owner; serving that to a stranger would hand them the
owner's private memory files, so guest mode forces it off. Owner mode is a
separate switch, not a default that someone forgets to flip.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator

from . import workflows
from .keyvault import VAULT, Secret, Session, SessionError
from .workflows import Phase, Workflow

MAX_FANOUT = int(os.environ.get("ROTA_MAX_FANOUT", "4"))
RUNS_DIR = Path(os.environ.get("ROTA_RUNS_DIR", tempfile.gettempdir())) / "rota-runs"
REPO_ROOT = Path(__file__).resolve().parent.parent

# Matches the architect's work-package line. Anything the architect writes that
# does not match is not a package — that strictness is what stops the fan-out
# from spawning an agent per bullet point in the Risks section.
PACKAGE_RE = re.compile(
    r"^\s*(\d+)\.\s*(?P<name>[^|]{3,80}?)\s*\|\s*deliverable:\s*(?P<deliverable>[^|]{1,120})",
    re.MULTILINE | re.IGNORECASE,
)


@dataclass
class PhaseResult:
    phase_id: str
    label: str
    text: str
    cost_usd: float
    duration_s: float
    model: str
    packages: list[str] = field(default_factory=list)


def video_mcp_config() -> dict:
    """The MCP server declaration handed to a run that needs video.

    Provider keys come from this server's environment, not the caller's session:
    the video provider account is the operator's, and metering it is the
    operator's problem. That is a deliberate asymmetry with the Anthropic key.
    """
    env = {k: v for k, v in os.environ.items()
           if k in ("REPLICATE_API_TOKEN", "FAL_KEY", "VIDEO_MCP_WORKSPACE",
                    "VIDEO_MCP_REPLICATE_MODEL", "VIDEO_MCP_FAL_MODEL")}
    return {
        "video": {
            "type": "stdio",
            "command": "python3",
            "args": ["-m", "mcpservers.video.server"],
            "env": {"PYTHONPATH": str(REPO_ROOT), **env},
        }
    }


def workspace_for(run_id: str) -> Path:
    path = RUNS_DIR / run_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def parse_packages(plan_text: str) -> list[str]:
    packages = [
        f"{m.group('name').strip()} — deliverable: {m.group('deliverable').strip()}"
        for m in PACKAGE_RE.finditer(plan_text or "")
    ]
    return packages[:MAX_FANOUT]


# The SDK merges options.env over os.environ rather than replacing it, so a
# guest run would otherwise inherit whatever Claude credentials the operator
# has in their shell — and a subscription token that outranks the caller's key
# means the operator quietly pays for the stranger's run. Blank them.
AMBIENT_CREDENTIALS = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_AUTH_TOKEN",
                       "ANTHROPIC_BASE_URL", "AWS_BEARER_TOKEN_BEDROCK",
                       "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX")


def _env_for(key: Secret | None) -> dict[str, str]:
    if key is None:
        return {}                              # owner mode: ambient credentials
    return {"ANTHROPIC_API_KEY": key.reveal(),
            **{name: "" for name in AMBIENT_CREDENTIALS}}


async def _one_agent(prompt: str, phase: Phase, *, key: Secret | None, cwd: Path,
                     budget_usd: float, workflow: Workflow) -> tuple[str, float]:
    from claude_agent_sdk import ClaudeAgentOptions, query

    options = ClaudeAgentOptions(
        model=phase.model,
        allowed_tools=list(phase.tools),
        max_turns=phase.max_turns,
        cwd=str(cwd),
        env=_env_for(key),
        max_budget_usd=max(0.05, budget_usd),
        setting_sources=[],                     # no operator settings, skills or CLAUDE.md
        permission_mode="acceptEdits",          # writes confined to cwd by the sandbox
        mcp_servers=video_mcp_config() if workflow.needs_video_mcp else {},
        system_prompt=(
            "You are one phase of an automated multi-agent build. Do your phase "
            "and stop. No preamble, no recap of the brief, no offers to continue. "
            "Write files rather than pasting file contents into your reply.\n"
            "Never write an API key, token or credential into any file."
        ),
    )

    text, cost = "", 0.0
    async for message in query(prompt=prompt, options=options):
        result = getattr(message, "result", None)
        if isinstance(result, str):
            text = result
            cost = float(getattr(message, "total_cost_usd", 0.0) or 0.0)
    return text, cost


async def run_workflow(brief: str, workflow_id: str, session: Session,
                       *, run_id: str, cwd: Path | None = None) -> AsyncIterator[dict]:
    """Async event stream: one dict per phase boundary. The caller turns these
    into SSE frames; nothing here knows about HTTP."""
    workflow = workflows.get(workflow_id)
    cwd = cwd or workspace_for(run_id)
    prior_parts: list[str] = []
    results: list[PhaseResult] = []
    total_cost = 0.0

    yield {"event": "run_start", "run_id": run_id, "workflow": workflow.id,
           "phases": [p.id for p in workflow.phases], "workspace": str(cwd)}

    try:
        for phase in workflow.phases:
            VAULT.assert_budget(session, 0.05)
            allowance = min(session.remaining_usd(),
                            session.spend_cap_usd * phase.budget_share)
            prior = "\n\n".join(prior_parts)[-12000:]
            started = time.monotonic()

            yield {"event": "phase_start", "phase": phase.id, "label": phase.label,
                   "model": phase.model, "budget_usd": round(allowance, 3)}

            if phase.fan_out:
                packages = parse_packages(prior_parts[0] if prior_parts else "")
                if not packages:
                    packages = ["the whole brief, as a single package"]
                per_agent = max(0.05, allowance / len(packages))
                prompts = [
                    phase.prompt.format(brief=brief, prior=prior, package=pkg)
                    for pkg in packages
                ]
                yield {"event": "fan_out", "phase": phase.id, "packages": packages}
                outcomes = await asyncio.gather(*[
                    _one_agent(p, phase, key=session.key, cwd=cwd,
                               budget_usd=per_agent, workflow=workflow)
                    for p in prompts
                ], return_exceptions=True)
                texts, cost = [], 0.0
                for pkg, outcome in zip(packages, outcomes):
                    if isinstance(outcome, Exception):
                        texts.append(f"### {pkg}\nFAILED: {outcome}")
                        continue
                    body, spent = outcome
                    texts.append(f"### {pkg}\n{body}")
                    cost += spent
                text = "\n\n".join(texts)
            else:
                prompt = phase.prompt.format(brief=brief, prior=prior, package="")
                text, cost = await _one_agent(prompt, phase, key=session.key, cwd=cwd,
                                              budget_usd=allowance, workflow=workflow)

            duration = time.monotonic() - started
            total_cost += cost
            VAULT.charge(session, cost,
                         {"run_id": run_id, "phase": phase.id, "usd": round(cost, 4)})
            result = PhaseResult(phase.id, phase.label, text, cost, duration, phase.model)
            results.append(result)
            prior_parts.append(f"--- {phase.label} ---\n{text}")

            yield {"event": "phase_done", "phase": phase.id, "label": phase.label,
                   "text": text, "cost_usd": round(cost, 4),
                   "duration_s": round(duration, 1),
                   "spent_usd": round(session.spent_usd, 4),
                   "remaining_usd": round(session.remaining_usd(), 4)}

        yield {"event": "run_done", "run_id": run_id,
               "cost_usd": round(total_cost, 4),
               "files": [str(p.relative_to(cwd)) for p in sorted(cwd.rglob("*"))
                         if p.is_file()][:200]}

    except SessionError as exc:
        yield {"event": "error", "kind": "budget", "message": str(exc)}
    except Exception as exc:                                   # noqa: BLE001
        yield {"event": "error", "kind": "run", "message": f"{type(exc).__name__}: {exc}"}


def sweep_workspaces(max_age_s: int = 86_400) -> int:
    """Client artefacts are not the operator's to keep. Delete run directories
    once they are a day old; the client downloaded them or they did not matter."""
    if not RUNS_DIR.exists():
        return 0
    cutoff = time.time() - max_age_s
    removed = 0
    for path in RUNS_DIR.iterdir():
        if path.is_dir() and path.stat().st_mtime < cutoff:
            shutil.rmtree(path, ignore_errors=True)
            removed += 1
    return removed
