"""HTTP surface for the platform. Six endpoints, one page, no database.

    POST   /api/session      key in, opaque token out (key never comes back)
    DELETE /api/session      wipe the key from memory now
    GET    /api/session      remaining budget, run count
    GET    /api/workflows    what can be run
    POST   /api/run          execute a workflow, streamed as SSE
    GET    /api/run/{id}/file/{path}   download one artefact

The token travels in the Authorization header, not a cookie. There is no
cross-origin form posting to protect against because there is no cookie to
ride on, and it keeps the key out of anything a browser persists by default.
"""

from __future__ import annotations

import json
import os
import secrets
import time
from collections import defaultdict, deque
from pathlib import Path

from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

from . import runner, workflows
from .keyvault import VAULT, SessionError

STATIC = Path(__file__).resolve().parent / "static"
RATE_LIMIT_PER_MIN = int(os.environ.get("ROTA_RATE_LIMIT", "6"))

@asynccontextmanager
async def lifespan(_: FastAPI):
    runner.sweep_workspaces()          # yesterday's client artefacts are not ours to keep
    yield


app = FastAPI(title="rota platform", version="0.1.0", docs_url=None,
              redoc_url=None, lifespan=lifespan)

_hits: dict[str, deque[float]] = defaultdict(deque)


def _rate_limit(key: str) -> None:
    """Per-token, in-memory, fixed window. Not a defence against a determined
    attacker — a guard against one user's runaway loop eating the box."""
    now = time.time()
    window = _hits[key]
    while window and window[0] < now - 60:
        window.popleft()
    if len(window) >= RATE_LIMIT_PER_MIN:
        raise HTTPException(429, "too many runs — wait a minute")
    window.append(now)


def _session(authorization: str | None):
    token = (authorization or "").removeprefix("Bearer ").strip()
    try:
        return VAULT.get(token)
    except SessionError as exc:
        raise HTTPException(401, str(exc)) from None


class SessionIn(BaseModel):
    api_key: str = Field(min_length=20, max_length=200)
    spend_cap_usd: float | None = Field(default=None, ge=0.10, le=50.0)


class RunIn(BaseModel):
    brief: str = Field(min_length=8, max_length=8000)
    workflow: str = "single"


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (STATIC / "index.html").read_text(encoding="utf-8")


@app.post("/api/session")
def open_session(body: SessionIn) -> dict:
    try:
        session = VAULT.open(body.api_key, body.spend_cap_usd)
    except SessionError as exc:
        raise HTTPException(400, str(exc)) from None
    return session.public()


@app.get("/api/session")
def read_session(authorization: str | None = Header(default=None)) -> dict:
    return _session(authorization).public()


@app.delete("/api/session")
def close_session(authorization: str | None = Header(default=None)) -> dict:
    token = (authorization or "").removeprefix("Bearer ").strip()
    return {"closed": VAULT.close(token)}


@app.get("/api/workflows")
def list_workflows() -> dict:
    return {"workflows": [w.public() for w in workflows.WORKFLOWS.values()]}


@app.post("/api/run")
async def run(body: RunIn, request: Request,
              authorization: str | None = Header(default=None)) -> StreamingResponse:
    session = _session(authorization)
    _rate_limit(session.token)
    try:
        workflows.get(body.workflow)
    except KeyError as exc:
        raise HTTPException(400, str(exc)) from None

    run_id = f"{int(time.time())}-{secrets.token_hex(4)}"

    async def stream():
        yield ": stream open\n\n"
        async for event in runner.run_workflow(body.brief, body.workflow,
                                               session, run_id=run_id):
            if await request.is_disconnected():
                break
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream", headers={
        "Cache-Control": "no-store",
        "X-Accel-Buffering": "no",          # nginx would otherwise hold the stream
    })


@app.get("/api/run/{run_id}/file/{path:path}")
def download(run_id: str, path: str,
             authorization: str | None = Header(default=None)) -> FileResponse:
    _session(authorization)
    root = runner.RUNS_DIR / run_id
    target = (root / path).resolve()
    if not str(target).startswith(str(root.resolve())) or not target.is_file():
        raise HTTPException(404, "no such artefact")
    return FileResponse(target, filename=target.name)
