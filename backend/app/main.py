"""FastAPI application: CORS middleware + router registration (#170).

The ~115 HTTP routes live in `app/routers/*.py`, one APIRouter per area, and
delegate to the service layer (`app/services/`). Business logic does not live
here. The shared `ProjectService` singleton + error translation live in
`app/runtime.py` so every router shares the same process-wide state.

Layering runs one way — routes import services, never the reverse. That is no
longer prose you have to remember: `scripts/check_layer_imports.py` fails CI if
a `services/` module imports FastAPI, starlette, or a router (ADR-0056, #977).
"""

from __future__ import annotations

import atexit
import traceback
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from importlib.metadata import version as _pkg_version
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.routers import (
    ai,
    entries,
    lore,
    machine_settings,
    metadata,
    plot,
    project,
    scenes,
    snapshots,
    updates,
)
from app.runtime import root_from_header
from app.services.error_log import append_error_line
from app.services.frontend_assets import frontend_dist_dir
from app.services.machine_settings import error_log_dir
from app.services.project.node_index_gate import node_index_gate

# The node-index snapshot is flushed lazily behind a dirty flag (#476); write any
# pending one out on a clean shutdown so the next open serves it rather than
# rebuilding. Safe by construction either way — a kill that fires neither hook
# loses only rebuildable cache, which the next open's manifest diff recovers.
# `atexit` is the catch-all (covers uvicorn's graceful stop and any non-server
# entrypoint); the lifespan shutdown is the server's first-class hook.
atexit.register(node_index_gate.flush)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield
    node_index_gate.flush()


# Version is derived from the installed package metadata (backend/pyproject.toml),
# never hand-copied here — one backend literal, so a release bump can't leave the
# OpenAPI docs reporting a stale version. `scripts/check_version_sync.py` holds
# that literal equal to frontend/package.json (#1299).
app = FastAPI(
    title="Local Writing Service",
    version=_pkg_version("local-writing-service"),
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    # Local-first: the backend only ever binds 127.0.0.1 (never network-exposed),
    # and any number of parallel dev stacks must reach it — Anton's :5173, the
    # isolated "claude" frontend on :5174, plus a worktree thread on any other
    # port. Pinning specific frontend ports (was 5173/5174 only) CORS-rejected
    # every stack outside that pair — a hardcode that blocked parallel work. Match
    # any loopback origin by regex instead; Starlette echoes the matched origin
    # (not `*`), so this stays compatible with allow_credentials.
    allow_origin_regex=r"https?://(127\.0\.0\.1|localhost)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def record_unhandled_errors(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Give a genuine `500` a durable line before it vanishes into the console (#386).

    This middleware is a *choke point*, and deliberately so (ADR-0056 §2/§4): every
    unhandled backend error is logged here because it flows through this one path,
    not because each call site remembered to log it. Do not "simplify" it into
    per-handler try/except — the single funnel is the mechanism. Its frontend twin
    is the `run()` funnel in App.svelte, feeding `lib/errorLog.ts`.


    Domain failures (`ProjectServiceError`) are already turned into HTTP responses
    upstream, so only *unexpected* exceptions — the ones the UI sees as a bare
    "Internal Server Error" with nothing behind it — reach this `except`. We record
    one line, then re-raise unchanged so the 500 is produced exactly as before.
    Recording never alters the outcome, and the writer swallows its own failures.

    The line lands in the scope the request carries: the project's own log when
    `X-Project-Root` is present, else the machine-scope log (#741) — a 500 raised
    resolving `/api/project/open` has no project yet, and that is exactly the class
    that used to vanish here.
    """
    try:
        response = await call_next(request)
    except Exception as exc:
        header_root = root_from_header(request.headers.get("X-Project-Root"))
        append_error_line(
            header_root if header_root is not None else error_log_dir(),
            origin="backend",
            message=f"{type(exc).__name__}: {exc}",
            detail="".join(traceback.format_exception(exc)),
            context=f"{request.method} {request.url.path}",
            ensure_dir=header_root is None,
        )
        raise
    return response


# Registration order mirrors the original single-file route order.
app.include_router(project.router)
app.include_router(metadata.router)
app.include_router(scenes.router)
app.include_router(snapshots.router)
app.include_router(lore.router)
app.include_router(plot.router)
app.include_router(entries.router)
app.include_router(machine_settings.router)
app.include_router(ai.router)
app.include_router(updates.router)


def mount_frontend(app: FastAPI, dist_dir: Path | None) -> None:
    """Serve the built frontend from the app's own origin (ADR-0072 §1).

    Mounted at "/" AFTER every router, so the exact `/api/...` routes and the
    built-in `/docs`/`/openapi.json` win their paths and this catch-all serves
    the bundle (index.html + assets) for everything else. `html=True` returns
    index.html for "/". Skipped when no build is present (a dev run), leaving
    the API-only behaviour the Vite dev server expects.
    """
    if dist_dir is not None:
        app.mount("/", StaticFiles(directory=dist_dir, html=True), name="frontend")


mount_frontend(app, frontend_dist_dir())
