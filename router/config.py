"""Registry loading and path resolution. PyYAML is the only dependency."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "rota needs PyYAML for registry.yaml — install with: pip install pyyaml"
    ) from exc

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = REPO_ROOT / "registry.yaml"
LEDGER_PATH = REPO_ROOT / "ledger" / "usage.jsonl"


@dataclasses.dataclass(frozen=True)
class Route:
    id: str
    desc: str
    triggers: tuple[str, ...]
    tools: tuple[str, ...]
    model: str          # alias after resolution (haiku/sonnet/opus/…)
    budget: str         # S | M | L
    memory: bool
    repo: str = ""
    skill: str = ""     # optional file loaded into the worker prompt at dispatch


@dataclasses.dataclass(frozen=True)
class Registry:
    models: dict[str, str]
    budgets: dict[str, dict[str, int]]
    memory: dict[str, Any]
    scout: dict[str, Any]
    routes: tuple[Route, ...]

    def route(self, route_id: str) -> Route:
        for r in self.routes:
            if r.id == route_id:
                return r
        raise KeyError(f"unknown route: {route_id}")

    @property
    def fallback(self) -> Route:
        return self.routes[0]  # by convention: first route is the fallback

    def vault_path(self) -> Path:
        return (REPO_ROOT / str(self.memory.get("vault", ".."))).resolve()

    def inbox_path(self) -> Path:
        return (REPO_ROOT / str(self.memory.get("inbox", "../memory/_inbox"))).resolve()


def load(path: Path = REGISTRY_PATH) -> Registry:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    models = dict(raw.get("models", {}))
    routes = []
    for r in raw.get("routes", []):
        model = str(r.get("model", "default"))
        routes.append(
            Route(
                id=str(r["id"]),
                desc=str(r.get("desc", "")),
                triggers=tuple(str(t).lower() for t in r.get("triggers", [])),
                tools=tuple(r.get("tools", [])),
                model=models.get(model, model),  # resolve tier name → alias
                budget=str(r.get("budget", "M")),
                memory=bool(r.get("memory", False)),
                repo=str(r.get("repo", "")),
                skill=str(r.get("skill", "")),
            )
        )
    if not routes:
        raise SystemExit("registry.yaml defines no routes")
    return Registry(
        models=models,
        budgets={k: dict(v) for k, v in raw.get("budgets", {}).items()},
        memory=dict(raw.get("memory", {})),
        scout=dict(raw.get("scout", {})),
        routes=tuple(routes),
    )
