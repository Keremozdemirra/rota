"""Workflow definitions — the multi-agent shapes the platform can run.

A workflow is a list of phases. Each phase runs one agent with one model, one
tool set and one budget, and receives the previous phases' outputs as context.
Phases marked `fan_out` expand into N parallel agents, one per work package the
planning phase produced.

This is deliberately declarative rather than a graph engine. Everything the
platform ships today is plan → build → integrate → verify with a variable
middle, and a data structure that describes exactly that is easier to reason
about than a general DAG that mostly encodes the same four nodes.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Phase:
    id: str
    label: str
    model: str                      # haiku | sonnet | opus
    tools: tuple[str, ...]
    prompt: str                     # {brief} and {prior} are filled at run time
    max_turns: int = 8
    fan_out: bool = False           # expand over the plan's work packages
    budget_share: float = 0.25      # fraction of the session cap this phase may use


@dataclass(frozen=True)
class Workflow:
    id: str
    label: str
    description: str
    phases: tuple[Phase, ...]
    needs_video_mcp: bool = False
    tags: tuple[str, ...] = field(default_factory=tuple)

    def public(self) -> dict:
        return {
            "id": self.id, "label": self.label, "description": self.description,
            "phases": [{"id": p.id, "label": p.label, "model": p.model,
                        "fan_out": p.fan_out} for p in self.phases],
            "needs_video_mcp": self.needs_video_mcp,
        }


_PLAN_CONTRACT = """You are the architect. Produce a plan, not an implementation.

Output exactly this structure and nothing else:

## Scope
One paragraph: what is being built, and one sentence on what is explicitly out.

## Decisions
Three to six lines, each `decision — because reason`. Stack, storage, hosting.

## Work packages
A numbered list, 2 to 5 items, each a single line:
`N. <name> | deliverable: <file or artefact> | depends on: <N or none>`
Packages must be independently buildable. If two need the same file, merge them.

## Risks
Up to three lines, each a real failure mode with the check that would catch it.
"""

_BUILD_CONTRACT = """You are an implementer. You own exactly one work package.

Build it end to end and write real files — no scaffolding comments, no TODOs,
no placeholder functions. Stay inside your package: if you need something
another package owns, code against the interface stated in the plan and note
the assumption in one line at the end.

Finish with a `## Delivered` section listing each file you wrote and one line
on what it does.
"""

_INTEGRATE_CONTRACT = """You are the integrator. The packages were built in
parallel and have never met.

Find and fix the seams: mismatched interfaces, duplicated definitions, imports
of things nobody wrote, config keys referenced but never set. Run whatever the
project can be run with and make it actually execute.

Report as `## Fixed` (what you changed and why) and `## Still broken` (anything
you could not close, with the reason). An empty `Still broken` must be honest.
"""

_VERIFY_CONTRACT = """You are the adversarial reviewer. Assume the work is wrong
and try to prove it.

Check, in this order: does it run; does it do what the brief asked; are there
correctness bugs; are there secrets, credentials or personal data in any file;
are the claims in the delivery report actually true of the files on disk.

Report findings ranked by severity, each as `severity | file:line | what breaks
and when`. If you find nothing at a severity, say so in one line. Do not fix
anything and do not pad the list — a short honest review beats a long one.
"""

_VIDEO_CONTRACT = """You are the media producer. You have the video-mcp tools.

Sequence, and do not skip steps: video_generate → poll video_status until it
reports succeeded or failed → video_fetch → video_encode_web → video_poster →
video_embed. Raw provider output never goes on a page.

Generate at most the number of clips the plan asks for. Each generation costs
real money on the operator's provider account, so a retry needs a reason.

Finish with `## Media` — each clip's stem, its rendition filenames, and the
exact <video> markup the site should embed.
"""

SINGLE = Workflow(
    id="single",
    label="Single agent",
    description="One routed specialist. Cheapest path; use it for anything that "
                "is one job rather than one project.",
    phases=(
        Phase("run", "Execute", "sonnet",
              ("Read", "Write", "Edit", "Bash", "Grep", "Glob", "WebSearch", "WebFetch"),
              "{brief}", max_turns=12, budget_share=1.0),
    ),
    tags=("default",),
)

PROJECT = Workflow(
    id="project",
    label="Project team",
    description="Architect plans, implementers build the packages in parallel, "
                "an integrator closes the seams, a reviewer tries to break it.",
    phases=(
        Phase("plan", "Architect", "opus", ("Read", "Grep", "Glob", "WebSearch"),
              _PLAN_CONTRACT + "\n\nBrief:\n{brief}", max_turns=6, budget_share=0.20),
        Phase("build", "Implementers", "sonnet",
              ("Read", "Write", "Edit", "Bash", "Grep", "Glob", "WebSearch", "WebFetch"),
              _BUILD_CONTRACT + "\n\nPlan:\n{prior}\n\nYour package:\n{package}",
              max_turns=20, fan_out=True, budget_share=0.45),
        Phase("integrate", "Integrator", "sonnet",
              ("Read", "Write", "Edit", "Bash", "Grep", "Glob"),
              _INTEGRATE_CONTRACT + "\n\nPlan and package reports:\n{prior}",
              max_turns=14, budget_share=0.20),
        Phase("verify", "Reviewer", "opus", ("Read", "Grep", "Glob", "Bash"),
              _VERIFY_CONTRACT + "\n\nBrief:\n{brief}\n\nWhat was built:\n{prior}",
              max_turns=10, budget_share=0.15),
    ),
    tags=("flagship",),
)

VIDEO_SITE = Workflow(
    id="video-site",
    label="Video website",
    description="Plans a site, generates and web-encodes the video through the "
                "video-mcp server, builds the pages around it, then reviews it.",
    needs_video_mcp=True,
    phases=(
        Phase("plan", "Architect", "opus", ("Read", "Grep", "Glob", "WebSearch"),
              _PLAN_CONTRACT +
              "\n\nThis site uses video. State in Decisions how many clips, what "
              "each one shows, and where it sits on the page.\n\nBrief:\n{brief}",
              max_turns=6, budget_share=0.15),
        Phase("media", "Media producer", "sonnet",
              ("mcp__video__video_generate", "mcp__video__video_status",
               "mcp__video__video_fetch", "mcp__video__video_encode_web",
               "mcp__video__video_poster", "mcp__video__video_embed",
               "mcp__video__video_manifest", "Read", "Write"),
              _VIDEO_CONTRACT + "\n\nPlan:\n{prior}", max_turns=30, budget_share=0.30),
        Phase("build", "Site builders", "sonnet",
              ("Read", "Write", "Edit", "Bash", "Grep", "Glob"),
              _BUILD_CONTRACT +
              "\n\nThe media phase already produced the clips and the exact "
              "<video> markup. Embed that markup verbatim; do not invent "
              "filenames.\n\nPlan and media report:\n{prior}\n\nYour package:\n{package}",
              max_turns=20, fan_out=True, budget_share=0.35),
        Phase("verify", "Reviewer", "opus", ("Read", "Grep", "Glob", "Bash"),
              _VERIFY_CONTRACT +
              "\n\nAlso check: every <source> points at a file that exists, every "
              "video has a poster, and autoplay clips are muted and playsinline."
              "\n\nBrief:\n{brief}\n\nWhat was built:\n{prior}",
              max_turns=10, budget_share=0.20),
    ),
    tags=("video",),
)

WORKFLOWS = {w.id: w for w in (SINGLE, PROJECT, VIDEO_SITE)}


def get(workflow_id: str) -> Workflow:
    try:
        return WORKFLOWS[workflow_id]
    except KeyError:
        raise KeyError(f"unknown workflow {workflow_id!r}; "
                       f"available: {', '.join(WORKFLOWS)}") from None

