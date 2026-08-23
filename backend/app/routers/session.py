"""Browser-presence WebSocket (#1378).

A desktop launch quits when its last tab closes; the frontend holds this socket
open for the tab's lifetime, and the endpoint counts it in the presence tracker.
No project scope — an app-lifecycle concern, like the version and update routes.

On a LAN/systemd server the tracker is never consulted (`server.py` only arms
auto-shutdown on a loopback desktop launch), so this is just a harmless open
socket there.
"""

from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.session_presence import presence

router = APIRouter()


@router.websocket("/api/session/live")
async def session_live(ws: WebSocket) -> None:
    await ws.accept()
    presence.connect()
    try:
        # The connection's mere existence is the signal — we never send or expect
        # a message. This loop simply blocks until the browser closes the socket
        # (tab close or reload), which raises WebSocketDisconnect.
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        presence.disconnect()
