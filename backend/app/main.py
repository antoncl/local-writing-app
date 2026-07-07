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
)

app = FastAPI(title="Local Writing Service", version="0.5.4")
app.add_middleware(
    CORSMiddleware,
    # 5173 = the default Vite dev server; 5174 = the isolated "claude" frontend
    # (`--mode claude`, backend on :8788) so that parallel stack can actually
    # reach its backend — see memory/feedback_isolated_claude_instance.md.
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:5174",
        "http://localhost:5174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Registration order mirrors the original single-file route order.
app.include_router(project.router)
app.include_router(metadata.router)
app.include_router(scenes.router)
app.include_router(lore.router)
app.include_router(entries.router)
app.include_router(machine_settings.router)
app.include_router(ai.router)
