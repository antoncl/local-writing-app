#!/usr/bin/env python3
"""The ASGI app `scripts/dev_backend.py` actually serves: `app.main:app` plus proof.

This exists because of #364, where a dev server started from a worktree served
the *primary* tree's code and said nothing. Two distinct things can go wrong,
and neither is visible from outside:

1. **Wrong import.** `import app` resolves to another checkout (the venv's
   editable install points at the primary tree). `--app-dir` and `PYTHONPATH`
   already prevent this — measured, not assumed — but nothing proved it.
2. **Wrong server.** Our uvicorn starts, logs "Application startup complete",
   and never owns the port, because a server from another tree already held it.
   On Windows `uvicorn --reload` binds with `SO_REUSEADDR`, which permits
   binding an address that is already in LISTEN, so the second start succeeds
   silently and the *first* server keeps answering. This is what actually
   happened in #364; the import was correct the whole time.

A check inside the server can only catch (1) — it is by definition running in
the process that answers. So this wrapper does both halves: it asserts its own
provenance at import time (fails the process, loudly, rather than serving the
wrong tree), and it exposes that provenance plus a per-launch nonce over HTTP so
the *launcher* can confirm the server answering the port is the one it started.

The probe route lives here rather than in `app.main` on purpose: it is a
property of the dev launcher, not of the product, and `backend/app` should not
grow a diagnostic surface that ships.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

CHECKOUT = Path(os.environ["DEV_BACKEND_CHECKOUT"]).resolve()
NONCE = os.environ.get("DEV_BACKEND_NONCE", "")
PROBE_PATH = "/__dev_backend_provenance"


def _fail(message: str) -> None:
    """Refuse to serve. A wrong-tree preview is worse than no preview."""
    sys.stderr.write(f"\ndev_backend: REFUSING TO SERVE\n{message}\n\n")
    sys.stderr.flush()
    raise SystemExit(1)


def _load_app():
    """Import the backend and prove it came from the checkout we were told to serve."""
    try:
        import app as app_package
        from app.main import app as asgi_app
    except Exception as exc:  # noqa: BLE001 - re-raised as a fatal launcher error
        _fail(f"could not import `app` from {CHECKOUT / 'backend'}: {exc!r}")

    resolved = Path(app_package.__file__).resolve().parent
    expected = (CHECKOUT / "backend" / "app").resolve()
    if resolved != expected:
        _fail(
            f"`app` imported from {resolved}\n"
            f"but this server was started from {CHECKOUT}\n"
            f"(expected {expected}).\n"
            "The venv's editable install points at the primary worktree; "
            "PYTHONPATH must put this checkout's backend/ first."
        )

    print(f"dev_backend: serving app from {resolved}", file=sys.stderr, flush=True)
    return asgi_app


_APP = _load_app()

_PROVENANCE = json.dumps(
    {
        "checkout": str(CHECKOUT),
        "app_file": str((CHECKOUT / "backend" / "app" / "__init__.py").resolve()),
        "nonce": NONCE,
        "pid": os.getpid(),
    }
).encode("utf-8")


async def app(scope, receive, send):
    """`app.main:app`, with one extra route the launcher uses to identify us."""
    if scope["type"] == "http" and scope["path"] == PROBE_PATH:
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"cache-control", b"no-store"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": _PROVENANCE})
        return
    await _APP(scope, receive, send)
