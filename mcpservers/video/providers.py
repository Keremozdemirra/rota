"""Video generation providers behind one interface.

Design rules that are not negotiable here:

- API keys are read from the process environment at call time. They are never
  accepted as tool arguments, never returned in a result, never logged, and
  never written to the job store. A tool argument would put the key into a
  model context; an environment read does not.
- Only stdlib. This server runs as a subprocess of Claude Code and adding a
  dependency to it means adding it to every machine that mounts the server.
- Submit and poll are separate calls. Video generation runs 30s-6min; a
  blocking tool call would burn the model's turn budget waiting.

Model slugs and input field names change on the provider side without notice.
Verify against provider docs before trusting any default in MODELS.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

TIMEOUT_S = 60


class ProviderError(RuntimeError):
    """Raised with a message safe to show a model — never contains the key."""


def _request(url: str, *, method: str = "GET", headers: dict[str, str],
             body: dict[str, Any] | None = None) -> dict[str, Any]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Content-Type": "application/json", "Accept": "application/json", **headers,
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        raise ProviderError(f"HTTP {exc.code} from {_host(url)}: {detail}") from None
    except urllib.error.URLError as exc:
        raise ProviderError(f"cannot reach {_host(url)}: {exc.reason}") from None
    return json.loads(raw) if raw.strip() else {}


def _host(url: str) -> str:
    return url.split("/", 3)[2] if "//" in url else url


def _env_key(var: str, provider: str) -> str:
    key = os.environ.get(var, "").strip()
    if not key:
        raise ProviderError(
            f"{provider} is not configured: {var} is unset in this server's "
            f"environment. Set it in .mcp.json env or the shell that launches "
            f"Claude, then restart the MCP server."
        )
    return key


@dataclass
class Job:
    """Provider-agnostic handle. Never holds a key."""
    provider: str
    remote_id: str
    status: str                      # queued | running | succeeded | failed
    poll_url: str
    result_url: str = ""
    video_url: str = ""
    error: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v not in ("", None)}


class Provider:
    name = "abstract"

    def submit(self, model: str, payload: dict[str, Any]) -> Job:
        raise NotImplementedError

    def poll(self, job: Job) -> Job:
        raise NotImplementedError


class Replicate(Provider):
    """https://replicate.com/docs — prediction create/get.

    Endpoint shape (stable since 2023): POST /v1/models/{owner}/{name}/predictions
    with {"input": {...}}, GET /v1/predictions/{id} to poll. `output` is either a
    URL string or a list whose last element is the video URL, depending on model.
    """

    name = "replicate"
    base = "https://api.replicate.com/v1"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {_env_key('REPLICATE_API_TOKEN', 'replicate')}"}

    def submit(self, model: str, payload: dict[str, Any]) -> Job:
        if "/" not in model:
            raise ProviderError(f"replicate model must be 'owner/name', got {model!r}")
        url = f"{self.base}/models/{model}/predictions"
        data = _request(url, method="POST", headers=self._headers(), body={"input": payload})
        return Job(
            provider=self.name,
            remote_id=str(data.get("id", "")),
            status=_norm(data.get("status")),
            poll_url=(data.get("urls") or {}).get("get") or f"{self.base}/predictions/{data.get('id')}",
            meta={"model": model},
        )

    def poll(self, job: Job) -> Job:
        data = _request(job.poll_url, headers=self._headers())
        job.status = _norm(data.get("status"))
        job.error = str(data.get("error") or "")[:400]
        job.video_url = _first_url(data.get("output"))
        return job


class Fal(Provider):
    """https://fal.ai/docs — queue API.

    POST https://queue.fal.run/{model_id} returns request_id plus status_url and
    response_url. Always follow the returned URLs rather than rebuilding them:
    fal routes some models through per-app subdomains.
    """

    name = "fal"
    base = "https://queue.fal.run"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Key {_env_key('FAL_KEY', 'fal')}"}

    def submit(self, model: str, payload: dict[str, Any]) -> Job:
        data = _request(f"{self.base}/{model}", method="POST",
                        headers=self._headers(), body=payload)
        return Job(
            provider=self.name,
            remote_id=str(data.get("request_id", "")),
            status=_norm(data.get("status")),
            poll_url=str(data.get("status_url", "")),
            result_url=str(data.get("response_url", "")),
            meta={"model": model},
        )

    def poll(self, job: Job) -> Job:
        data = _request(job.poll_url, headers=self._headers())
        job.status = _norm(data.get("status"))
        if job.status == "succeeded" and job.result_url:
            result = _request(job.result_url, headers=self._headers())
            job.video_url = _first_url(result.get("video") or result.get("videos") or result)
        return job


def _norm(status: Any) -> str:
    """Collapse provider vocabularies onto four states."""
    s = str(status or "").lower()
    if s in ("succeeded", "completed", "success", "ok"):
        return "succeeded"
    if s in ("failed", "error", "canceled", "cancelled"):
        return "failed"
    if s in ("processing", "in_progress", "running", "started"):
        return "running"
    return "queued"


def _first_url(output: Any) -> str:
    """Dig a video URL out of the several shapes providers return."""
    if isinstance(output, str):
        return output if output.startswith("http") else ""
    if isinstance(output, list):
        for item in reversed(output):
            found = _first_url(item)
            if found:
                return found
        return ""
    if isinstance(output, dict):
        for key in ("url", "video_url", "output", "video", "videos"):
            if key in output:
                found = _first_url(output[key])
                if found:
                    return found
    return ""


PROVIDERS: dict[str, Provider] = {p.name: p for p in (Replicate(), Fal())}

# Defaults only. VERIFY these slugs against the provider catalogue before use —
# generation model names rotate faster than any file in this repo.
MODELS = {
    "replicate": os.environ.get("VIDEO_MCP_REPLICATE_MODEL", "minimax/video-01"),
    "fal": os.environ.get("VIDEO_MCP_FAL_MODEL", "fal-ai/ltx-video"),
}


def get(provider: str) -> Provider:
    try:
        return PROVIDERS[provider]
    except KeyError:
        raise ProviderError(
            f"unknown provider {provider!r}; available: {', '.join(PROVIDERS)}"
        ) from None
