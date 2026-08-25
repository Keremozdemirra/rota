"""Local media work: probe, web renditions, poster frames, HLS, embed markup.

Everything here shells out to ffmpeg/ffprobe. The point of doing it locally
rather than through a provider is cost and determinism: a generated clip comes
back as one 8-second MP4 at whatever bitrate the provider chose, and a website
needs a poster frame, an H.264 baseline for Safari, a VP9/AV1 fallback, and a
file small enough to autoplay on a phone. That is an ffmpeg job, not an API job.

Paths are confined to WORKSPACE. A tool that let a model write anywhere on the
filesystem via a relative path is a tool that will eventually do it.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

WORKSPACE = Path(os.environ.get(
    "VIDEO_MCP_WORKSPACE", Path.home() / "agents" / "media")).resolve()
FFMPEG_TIMEOUT_S = int(os.environ.get("VIDEO_MCP_FFMPEG_TIMEOUT", "900"))


class MediaError(RuntimeError):
    pass


def require_ffmpeg() -> None:
    missing = [b for b in ("ffmpeg", "ffprobe") if shutil.which(b) is None]
    if missing:
        raise MediaError(
            f"{' and '.join(missing)} not found on PATH. Install with: brew install ffmpeg"
        )


def resolve(name: str, *, must_exist: bool = True) -> Path:
    """Map a caller-supplied name into WORKSPACE, rejecting escapes."""
    candidate = (WORKSPACE / name).resolve()
    if not str(candidate).startswith(str(WORKSPACE) + os.sep) and candidate != WORKSPACE:
        raise MediaError(f"path escapes the media workspace: {name}")
    if must_exist and not candidate.exists():
        raise MediaError(f"no such file in workspace: {name}")
    return candidate


def _run(args: list[str]) -> str:
    proc = subprocess.run(args, capture_output=True, text=True, timeout=FFMPEG_TIMEOUT_S)
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-6:]
        raise MediaError(f"{args[0]} failed: " + " / ".join(tail))
    return proc.stdout


def probe(path: Path) -> dict:
    out = _run(["ffprobe", "-v", "error", "-print_format", "json",
                "-show_format", "-show_streams", str(path)])
    data = json.loads(out)
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    fmt = data.get("format", {})
    return {
        "file": path.name,
        "duration_s": round(float(fmt.get("duration", 0) or 0), 3),
        "size_mb": round(int(fmt.get("size", 0) or 0) / 1_048_576, 2),
        "container": fmt.get("format_name", ""),
        "video_codec": video.get("codec_name", ""),
        "width": video.get("width"),
        "height": video.get("height"),
        "fps": _fps(video.get("avg_frame_rate", "")),
        "has_audio": audio is not None,
    }


def _fps(rate: str) -> float | None:
    try:
        num, den = rate.split("/")
        return round(int(num) / int(den), 2) if int(den) else None
    except (ValueError, ZeroDivisionError):
        return None


@dataclass(frozen=True)
class Preset:
    """One web rendition. crf/cq are quality-targeted, not bitrate-targeted:
    a hero loop of a still-ish scene should not pay for a bitrate it cannot use."""
    label: str
    height: int
    crf: int


LADDER = (Preset("1080p", 1080, 24), Preset("720p", 720, 25), Preset("480p", 480, 27))


def encode_web(src: Path, stem: str, *, heights: list[int], mute: bool,
               formats: list[str]) -> list[dict]:
    """H.264/MP4 for universal playback, VP9/WebM for bandwidth. AV1 is not in
    the default ladder: encode time is minutes per second of footage and Safari
    support still depends on hardware."""
    require_ffmpeg()
    outputs = []
    for preset in LADDER:
        if preset.height not in heights:
            continue
        for fmt in formats:
            out = WORKSPACE / f"{stem}-{preset.label}.{fmt}"
            scale = f"scale=-2:{preset.height}:flags=lanczos"
            args = ["ffmpeg", "-y", "-i", str(src), "-vf", scale, "-movflags", "+faststart"]
            if fmt == "mp4":
                args += ["-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p",
                         "-preset", "slow", "-crf", str(preset.crf)]
            elif fmt == "webm":
                args = [a for a in args if a != "+faststart" and a != "-movflags"]
                args += ["-c:v", "libvpx-vp9", "-crf", str(preset.crf + 6), "-b:v", "0",
                         "-row-mt", "1", "-deadline", "good", "-cpu-used", "2"]
            else:
                raise MediaError(f"unsupported format {fmt!r}; use mp4 or webm")
            args += ["-an"] if mute else ["-c:a", "aac", "-b:a", "128k"]
            args.append(str(out))
            _run(args)
            outputs.append({"label": preset.label, "format": fmt, "file": out.name,
                            "size_mb": round(out.stat().st_size / 1_048_576, 2)})
    if not outputs:
        raise MediaError("no rendition produced — check heights and formats")
    return outputs


def poster(src: Path, stem: str, at_s: float) -> dict:
    require_ffmpeg()
    jpg = WORKSPACE / f"{stem}-poster.jpg"
    webp = WORKSPACE / f"{stem}-poster.webp"
    for out, extra in ((jpg, ["-q:v", "3"]), (webp, ["-quality", "80"])):
        _run(["ffmpeg", "-y", "-ss", str(at_s), "-i", str(src),
              "-frames:v", "1", "-vf", "scale=-2:1080", *extra, str(out)])
    return {"jpg": jpg.name, "webp": webp.name,
            "size_kb": round(jpg.stat().st_size / 1024, 1)}


def hls(src: Path, stem: str) -> dict:
    """Adaptive packaging. Worth it above ~30s or when the clip is above the
    fold on a page people open on mobile data; below that a plain MP4 wins."""
    require_ffmpeg()
    outdir = WORKSPACE / f"{stem}-hls"
    outdir.mkdir(parents=True, exist_ok=True)
    _run(["ffmpeg", "-y", "-i", str(src),
          "-filter_complex",
          "[0:v]split=3[v1][v2][v3];[v1]scale=-2:1080[v1o];[v2]scale=-2:720[v2o];[v3]scale=-2:480[v3o]",
          "-map", "[v1o]", "-c:v:0", "libx264", "-b:v:0", "5000k",
          "-map", "[v2o]", "-c:v:1", "libx264", "-b:v:1", "2800k",
          "-map", "[v3o]", "-c:v:2", "libx264", "-b:v:2", "1200k",
          "-f", "hls", "-hls_time", "4", "-hls_playlist_type", "vod",
          "-hls_segment_filename", str(outdir / "v%v-s%03d.ts"),
          "-master_pl_name", "master.m3u8",
          "-var_stream_map", "v:0 v:1 v:2",
          str(outdir / "v%v.m3u8")])
    return {"dir": outdir.name, "master": f"{outdir.name}/master.m3u8"}


def embed_snippet(stem: str, *, renditions: list[dict], poster_name: str,
                  autoplay: bool, base_url: str) -> str:
    """The markup a generated site should actually ship.

    autoplay implies muted+playsinline or iOS silently refuses to start, and
    preload=metadata rather than auto so a hero video does not cost every
    visitor the whole file before they scroll."""
    base = base_url.rstrip("/") + "/" if base_url else ""
    order = {"webm": 0, "mp4": 1}                       # smallest acceptable first
    sources = sorted(renditions, key=lambda r: (order.get(r["format"], 9), -_h(r["label"])))
    lines = [
        "<video",
        f'  class="{stem}-video"',
        f'  poster="{base}{poster_name}"',
        '  preload="metadata"',
        '  playsinline',
    ]
    if autoplay:
        lines += ["  autoplay", "  muted", "  loop"]
    else:
        lines.append("  controls")
    lines.append(">")
    for rendition in sources:
        mime = "video/webm" if rendition["format"] == "webm" else "video/mp4"
        lines.append(f'  <source src="{base}{rendition["file"]}" type="{mime}">')
    lines += [
        f'  <p>Your browser cannot play this video. '
        f'<a href="{base}{sources[-1]["file"]}">Download it instead.</a></p>',
        "</video>",
    ]
    return "\n".join(lines)


def _h(label: str) -> int:
    return int("".join(c for c in label if c.isdigit()) or 0)


def download(url: str, name: str) -> Path:
    """Fetch a finished generation into the workspace. http(s) only — a file://
    or data: URL arriving from a provider response is not something to honour."""
    import urllib.request

    if not url.startswith(("http://", "https://")):
        raise MediaError("refusing to download a non-http URL")
    dest = resolve(name, must_exist=False)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=300) as resp, dest.open("wb") as fh:
        shutil.copyfileobj(resp, fh)
    return dest
