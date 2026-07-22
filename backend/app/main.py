"""FastAPI application: CORS middleware + router registration (#170).

The ~115 HTTP routes live in `app/routers/*.py`, one APIRouter per area, and
delegate to the service layer (`app/services/`). Business logic does not live
here. The shared `ProjectService` singleton + error translation live in
`app/runtime.py` so every router shares the same process-wide state.
"""

from __future__ import annotations

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

app = FastAPI(title="Local Writing Service", version="0.5.4")
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
