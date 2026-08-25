#!/usr/bin/env python3
"""video-mcp — an MCP server that gives Claude the ability to put real video
on a generated website.

Nine tools, split three ways:

  generate   submit / status / fetch      talk to a generation provider
  process    probe / renditions / poster / hls    ffmpeg, locally
  publish    embed / manifest             the markup and the inventory

The split matters. Generation is slow and costs money per call; processing is
fast and free; publishing is pure text. Keeping them apart means a model can
retry an encode without re-paying for the clip, and can write the page markup
without touching either.

Run:  python -m mcpservers.video.server        (stdio; how Claude launches it)
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from mcpservers.video import media, providers  # noqa: E402

try:                                     # mcp >= 2.0
    from mcp.server import MCPServer
except ImportError:                      # mcp 1.x
    from mcp.server.fastmcp import FastMCP as MCPServer  # type: ignore

mcp = MCPServer(
    name="video-mcp",
    version="0.1.0",
    instructions=(
        "Video generation and web-delivery tools. Generation is asynchronous: "
        "call video_generate, then poll video_status, then video_fetch. Always "
        "run video_encode_web before putting a generated clip on a page — raw "
        "provider output is not web-deliverable. Never pass API keys as "
        "arguments; this server reads them from its own environment."
    ),
)

JOBS_PATH = media.WORKSPACE / ".video-jobs.json"


def _jobs() -> dict[str, dict]:
    if not JOBS_PATH.exists():
        return {}
    try:
        return json.loads(JOBS_PATH.read_text())
    except json.JSONDecodeError:
        return {}


def _save(job_id: str, record: dict) -> None:
    media.WORKSPACE.mkdir(parents=True, exist_ok=True)
    store = _jobs()
    store[job_id] = record
    JOBS_PATH.write_text(json.dumps(store, indent=2))


def _err(exc: Exception) -> dict[str, Any]:
    """Errors go back as data, not exceptions: a model can act on a message
    like 'FAL_KEY is unset', but a stack trace just ends the turn."""
    return {"ok": False, "error": str(exc)}


# --------------------------------------------------------------------------
# generate
# --------------------------------------------------------------------------

@mcp.tool(
    description="Submit a text-to-video or image-to-video generation. Returns a "
                "job_id immediately; generation takes 30s-6min. Poll video_status."
)
def video_generate(
    prompt: str,
    provider: str = "replicate",
    model: str = "",
    duration_s: int = 6,
    aspect_ratio: str = "16:9",
    image_url: str = "",
    extra_input: dict | None = None,
) -> dict:
    try:
        driver = providers.get(provider)
        model = model or providers.MODELS.get(provider, "")
        if not model:
            return {"ok": False, "error": f"no default model for {provider}; pass model="}
        payload: dict[str, Any] = {"prompt": prompt, "aspect_ratio": aspect_ratio}
        if duration_s:
            payload["duration"] = duration_s
        if image_url:
            payload["image_url"] = image_url          # i2v; field name varies by model
        payload.update(extra_input or {})

        job = driver.submit(model, payload)
        job_id = f"{provider}-{job.remote_id}"
        _save(job_id, {**job.as_dict(), "job_id": job_id,
                       "prompt": prompt[:200], "submitted_at": time.time()})
        return {"ok": True, "job_id": job_id, "status": job.status,
                "model": model, "hint": "poll video_status in ~20s"}
    except Exception as exc:                                   # noqa: BLE001
        return _err(exc)


@mcp.tool(description="Check a generation job. Returns status and, when finished, the source URL.")
def video_status(job_id: str) -> dict:
    try:
        record = _jobs().get(job_id)
        if not record:
            return {"ok": False, "error": f"unknown job_id {job_id!r}"}
        if record.get("status") in ("succeeded", "failed"):
            return {"ok": True, **record}
        job = providers.Job(**{k: v for k, v in record.items()
                               if k in providers.Job.__dataclass_fields__})
        job = providers.get(job.provider).poll(job)
        merged = {**record, **job.as_dict()}
        _save(job_id, merged)
        return {"ok": True, **merged}
    except Exception as exc:                                   # noqa: BLE001
        return _err(exc)


@mcp.tool(description="Download a finished generation into the media workspace. "
                      "Give it a slug like 'hero-loop'; extension is added.")
def video_fetch(job_id: str, name: str) -> dict:
    try:
        record = _jobs().get(job_id) or {}
        url = record.get("video_url", "")
        if not url:
            return {"ok": False, "error": "job has no video_url yet — poll video_status first"}
        stem = name.removesuffix(".mp4")
        path = media.download(url, f"{stem}-source.mp4")
        return {"ok": True, "file": path.name, **media.probe(path)}
    except Exception as exc:                                   # noqa: BLE001
        return _err(exc)


# --------------------------------------------------------------------------
# process
# --------------------------------------------------------------------------

@mcp.tool(description="Inspect a video in the workspace: duration, codec, size, fps, audio.")
def video_probe(file: str) -> dict:
    try:
        return {"ok": True, **media.probe(media.resolve(file))}
    except Exception as exc:                                   # noqa: BLE001
        return _err(exc)


@mcp.tool(
    description="Produce web renditions from a source video. Defaults to a muted "
                "720p MP4+WebM pair, which is what a hero loop should ship."
)
def video_encode_web(
    file: str,
    stem: str = "",
    heights: list[int] | None = None,
    formats: list[str] | None = None,
    mute: bool = True,
) -> dict:
    try:
        src = media.resolve(file)
        stem = stem or src.stem.removesuffix("-source")
        outputs = media.encode_web(src, stem,
                                   heights=heights or [720],
                                   formats=formats or ["mp4", "webm"],
                                   mute=mute)
        return {"ok": True, "stem": stem, "renditions": outputs}
    except Exception as exc:                                   # noqa: BLE001
        return _err(exc)


@mcp.tool(description="Extract a poster frame (JPEG + WebP) at the given second.")
def video_poster(file: str, at_s: float = 0.5, stem: str = "") -> dict:
    try:
        src = media.resolve(file)
        return {"ok": True, **media.poster(src, stem or src.stem.removesuffix("-source"), at_s)}
    except Exception as exc:                                   # noqa: BLE001
        return _err(exc)


@mcp.tool(description="Package a video as multi-bitrate HLS. Use above ~30s or for "
                      "above-the-fold video on mobile; a plain MP4 is better below that.")
def video_hls(file: str, stem: str = "") -> dict:
    try:
        src = media.resolve(file)
        return {"ok": True, **media.hls(src, stem or src.stem.removesuffix("-source"))}
    except Exception as exc:                                   # noqa: BLE001
        return _err(exc)


# --------------------------------------------------------------------------
# publish
# --------------------------------------------------------------------------

@mcp.tool(description="Return the <video> markup for a set of renditions: correct "
                      "source order, poster, and the autoplay attributes iOS requires.")
def video_embed(
    stem: str,
    renditions: list[dict],
    poster_file: str = "",
    autoplay: bool = True,
    base_url: str = "/media",
) -> dict:
    try:
        html = media.embed_snippet(
            stem,
            renditions=renditions,
            poster_name=poster_file or f"{stem}-poster.jpg",
            autoplay=autoplay,
            base_url=base_url,
        )
        return {"ok": True, "html": html}
    except Exception as exc:                                   # noqa: BLE001
        return _err(exc)


@mcp.tool(description="List every media file in the workspace with its size.")
def video_manifest() -> dict:
    try:
        media.WORKSPACE.mkdir(parents=True, exist_ok=True)
        files = [
            {"file": p.name, "size_mb": round(p.stat().st_size / 1_048_576, 2)}
            for p in sorted(media.WORKSPACE.iterdir())
            if p.is_file() and not p.name.startswith(".")
        ]
        return {"ok": True, "workspace": str(media.WORKSPACE), "files": files}
    except Exception as exc:                                   # noqa: BLE001
        return _err(exc)


if __name__ == "__main__":
    mcp.run("stdio")
