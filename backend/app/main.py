"""FastAPI application: CORS middleware + router registration (#170).

The ~115 HTTP routes live in `app/routers/*.py`, one APIRouter per area, and
delegate to the service layer (`app/services/`). Business logic does not live
here. The shared `ProjectService` singleton + error translation live in
`app/runtime.py` so every router shares the same process-wide state.
"""

from __future__ import annotations

import atexit
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import (
    ai,
    entries,
    lore,
    machine_settings,
    metadata,
    project,
    scenes,
    snapshots,
)
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


app = FastAPI(title="Local Writing Service", version="0.5.4", lifespan=lifespan)
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

# Registration order mirrors the original single-file route order.
app.include_router(project.router)
app.include_router(metadata.router)
app.include_router(scenes.router)
app.include_router(snapshots.router)
app.include_router(lore.router)
app.include_router(entries.router)
app.include_router(machine_settings.router)
app.include_router(ai.router)
