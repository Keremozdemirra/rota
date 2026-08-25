# video-mcp — giving Claude real video

An MCP server that lets a Claude session generate a clip, encode it for the
web, and write the markup that embeds it. Nine tools over stdio, standard
library only, no dependency beyond the `mcp` package itself.

## Why a server and not a script

Claude can already shell out to `ffmpeg` with Bash. The reason to wrap it is
narrower than it looks: a tool with a typed signature is a tool the model
cannot get subtly wrong, and a tool that reads its API keys from its own
environment is a tool that cannot leak them into a transcript. `Bash("curl -H
'Authorization: Bearer sk-…'")` puts the key in the context window. A tool call
does not.

## 1. Prerequisites

```bash
brew install ffmpeg
```

```bash
python3 -c "import mcp; print('mcp ok')"
```

`ffmpeg` is required for everything under *process*; the *generate* tools work
without it, but a raw provider MP4 is not something to put on a page.

## 2. Provider credentials

Keys go in the shell that launches Claude, never in a file in this repo.

```bash
echo 'export REPLICATE_API_TOKEN="…"' >> ~/.zshrc
echo 'export FAL_KEY="…"' >> ~/.zshrc
```

The server reads them at call time and fails with a readable message when one
is missing. Nothing here writes a key anywhere, and no tool accepts one as an
argument — if you find yourself wanting to pass a key to a tool, the design has
gone wrong.

## 3. Register the server

`.mcp.json` at the repo root already declares it:

```json
{
  "mcpServers": {
    "video": {
      "type": "stdio",
      "command": "python3",
      "args": ["-m", "mcpservers.video.server"],
      "env": {
        "PYTHONPATH": "${HOME}/agents/rota",
        "VIDEO_MCP_WORKSPACE": "${HOME}/agents/media",
        "REPLICATE_API_TOKEN": "${REPLICATE_API_TOKEN}",
        "FAL_KEY": "${FAL_KEY}"
      }
    }
  }
}
```

Project scope means the server exists when you work in `~/agents/rota` and
nowhere else. To make it available everywhere:

```bash
claude mcp add video --scope user -- python3 -m mcpservers.video.server
```

Restart the session, then confirm with `/mcp` — the server should list as
connected with nine tools.

## 4. Check it before trusting it

```bash
cd ~/agents/rota && python3 -c "
import asyncio, mcpservers.video.server as s
print([t.name for t in asyncio.run(s.mcp.list_tools())])
print(s.video_manifest())"
```

## 5. The tools

| Tool | What it does |
|---|---|
| `video_generate` | Submits a generation. Returns a `job_id` in under a second. |
| `video_status` | Polls it. `queued` → `running` → `succeeded` \| `failed`. |
| `video_fetch` | Downloads the finished clip into the media workspace. |
| `video_probe` | Duration, codec, resolution, fps, size, audio present. |
| `video_encode_web` | MP4 (H.264) + WebM (VP9) renditions at chosen heights. |
| `video_poster` | Poster frame as JPEG and WebP. |
| `video_hls` | Multi-bitrate HLS packaging. |
| `video_embed` | The `<video>` markup: source order, poster, iOS attributes. |
| `video_manifest` | Everything in the workspace, with sizes. |

Generation is split from polling deliberately. A blocking call that waits four
minutes for a render spends the model's turn budget doing nothing; submit-then-
poll costs two cheap calls and leaves the session free in between.

## 6. The shape of a real run

> Generate a six-second looping shot of coffee beans pouring into a hopper,
> shallow depth of field, and give me the markup for a hero section.

```
video_generate(prompt="…", provider="replicate", duration_s=6, aspect_ratio="16:9")
  → {"job_id": "replicate-xyz…", "status": "queued"}
video_status(job_id="replicate-xyz…")
  → {"status": "running"}          # poll again in ~20s
video_status(job_id="replicate-xyz…")
  → {"status": "succeeded", "video_url": "https://…"}
video_fetch(job_id="replicate-xyz…", name="hero-loop")
  → {"file": "hero-loop-source.mp4", "duration_s": 6.0, "size_mb": 4.8, …}
video_encode_web(file="hero-loop-source.mp4", heights=[1080, 720], mute=true)
  → 4 renditions, 0.9-3.1 MB each
video_poster(file="hero-loop-source.mp4", at_s=1.2)
video_embed(stem="hero-loop", renditions=[…], base_url="/media")
```

The last call returns markup that is correct rather than plausible — WebM
before MP4 so a browser that can take the smaller file does, `preload=
"metadata"` so a hero video does not cost every visitor 3 MB before they
scroll, and `muted` + `playsinline` alongside `autoplay` because iOS silently
refuses to start a clip without them.

## 7. What to verify before relying on it

Two things in this server go stale on the provider's schedule, not yours:

- **Model slugs.** `MODELS` in `providers.py` holds one default per provider.
  Video model names rotate every few months. Check the provider catalogue and
  pass `model=` explicitly for anything that matters.
- **Input field names.** `prompt`, `duration`, `aspect_ratio` and `image_url`
  are common but not universal — some models want `num_frames`, some want
  `image` rather than `image_url`. `extra_input` passes a raw dict straight
  through for exactly this reason.

Adding a third provider is one class: subclass `Provider`, implement `submit`
and `poll`, add it to `PROVIDERS`. `_norm` and `_first_url` already absorb most
of the shape differences between providers.

## 8. Cost discipline

Generation is the expensive call in this whole system — cents to low dollars
per clip, against fractions of a cent for the model turn that requested it. Two
guards worth keeping: generate at the lowest resolution that will survive the
final encode, and never let a workflow retry a generation without a stated
reason. The `video-site` workflow in the platform enforces the second one in
its media-phase contract.
