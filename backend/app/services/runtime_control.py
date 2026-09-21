"""A tiny handle onto the running server so in-process code can stop it.

`server.py` (the entrypoint) registers the live uvicorn server here; the update
installer (`update_apply`, ADR-0072 S6 #2083) asks for a graceful stop through
this module rather than importing the web layer (ADR-0056). Setting
`should_exit` is uvicorn's supported programmatic stop — the same one the
last-tab-closed auto-shutdown watcher uses — and it still runs the node-index
flush on the way out.
"""
from __future__ import annotations

from typing import Protocol


class _Stoppable(Protocol):
    should_exit: bool


_server: _Stoppable | None = None


def register_server(server: _Stoppable) -> None:
    """Called once by the entrypoint with the running uvicorn server."""
    global _server
    _server = server


def request_shutdown() -> bool:
    """Ask the running server to stop gracefully; False if none is registered
    (a source/dev run, or before serving) so the caller can react."""
    if _server is None:
        return False
    _server.should_exit = True
    return True
