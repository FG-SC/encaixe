"""FastAPI app factory. Serves the API under /api and the production front build at /."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from app import __version__
from app.config import REPO_ROOT, get_settings
from app.db import init_db

log = logging.getLogger(__name__)

FRONT_DIST = REPO_ROOT / "front" / "dist"


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    settings.ensure_var_dirs()
    init_db()
    if settings.is_prod:  # load the model now: in production a missing model stops the server at boot
        from app.embeddings import get_embedder

        get_embedder()
    for hook in app.state.startup_hooks:
        await hook()
    yield
    for hook in app.state.shutdown_hooks:
        await hook()


def _mount_front(app: FastAPI, dist: Path) -> None:
    """Serve front/dist with an SPA fallback, only when the build exists."""
    if not (dist / "index.html").is_file():
        log.info("front build not found at %s; serving the API only", dist)
        return
    index = dist / "index.html"
    root = dist.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path.startswith("api/"):
            raise HTTPException(status_code=404)
        target = (dist / path).resolve()
        if path and target.is_file() and root in target.parents:
            return FileResponse(target)
        return FileResponse(index)


def create_app(front_dist: Path | None = FRONT_DIST) -> FastAPI:
    settings = get_settings()
    if settings.is_prod and (problems := settings.prod_problems()):
        raise RuntimeError("ENCAIXE_ENV=prod, but: " + "; ".join(problems))
    docs = {} if not settings.is_prod else {"docs_url": None, "redoc_url": None, "openapi_url": None}
    app = FastAPI(title="Encaixe", version=__version__, lifespan=_lifespan, **docs)
    app.state.startup_hooks = []
    app.state.shutdown_hooks = []
    if settings.llm_enabled:  # background LLM upgrades of market jobs (never blocks a request)
        from app.llm import queue

        app.state.startup_hooks.append(queue.start_worker)
        app.state.shutdown_hooks.append(queue.stop_worker)

    from app.api import routes_meta

    app.include_router(routes_meta.router)
    for module in _optional_routers(include_dev=not settings.is_prod):
        app.include_router(module.router)

    if front_dist is not None:
        _mount_front(app, front_dist)
    return app


def _optional_routers(include_dev: bool = True) -> list:
    """Routers added by later phases; each module exposes ``router``. The dev panel's routes only outside prod."""
    import importlib

    modules = []
    names = [
        "app.api.routes_rules",
        "app.api.routes_candidates",
        "app.api.routes_recruiters",
        "app.api.routes_events",
        "app.api.routes_market",
    ]
    if include_dev:
        names.append("app.api.routes_dev")
    for name in names:
        try:
            modules.append(importlib.import_module(name))
        except ModuleNotFoundError as exc:
            if exc.name != name:
                raise
    return modules
