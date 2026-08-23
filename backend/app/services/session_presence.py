"""Track live browser connections so a desktop launch can quit when its last tab closes (#1378).

A WebSocket stays open for a tab's whole lifetime and closes promptly when the
tab is closed or reloaded — a far more reliable "is a tab still open?" signal
than a heartbeat poll, which background-tab timer throttling (and outright tab
freezing) would make lie. A TTL short enough to make "close -> quit" feel prompt
would be short enough to false-quit a server whose tab was merely backgrounded;
an open socket survives that, because the browser keeps the connection. So this
just counts open connections and decides when none remain.

Consulted only on a loopback desktop launch (`server.py` arms the watcher under
the same condition that opens the browser). A LAN/Pi/systemd server never asks —
a service outliving its browser is the point, not a bug — so the socket is a
harmless no-op there.

Pure and layering-clean (no FastAPI import): the router feeds it connect/
disconnect, the entrypoint polls `should_shutdown`, and tests drive it with an
injected clock.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

# After the last tab disconnects, wait this long before quitting. A reload drops
# the socket and immediately opens a new one; this grace spans that gap so a
# refresh never takes the server down. Comfortably longer than a local reload's
# reconnect (~1-2s), short enough that a real close still feels prompt — with the
# watcher's 1s poll the worst-case close-to-quit is ~4-5s ("a few seconds").
DEFAULT_EMPTY_GRACE = 4.0


class SessionPresence:
    """Count open browser presence sockets and decide when the last one is gone."""

    def __init__(
        self,
        *,
        empty_grace: float = DEFAULT_EMPTY_GRACE,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._empty_grace = empty_grace
        self._clock = clock
        self._lock = threading.Lock()
        self._count = 0
        # True once any tab has ever connected — the watcher must not quit before
        # the auto-opened browser has had a chance to connect (an empty count at
        # startup is "not open yet", not "closed").
        self._seen_any = False
        # Monotonic time the count last fell to zero; None while a tab is open.
        self._empty_since: float | None = None

    def connect(self) -> None:
        with self._lock:
            self._count += 1
            self._seen_any = True
            self._empty_since = None

    def disconnect(self) -> None:
        with self._lock:
            if self._count == 0:
                return  # defensive: never let a stray close reset the empty clock
            self._count -= 1
            if self._count == 0:
                self._empty_since = self._clock()

    @property
    def active(self) -> int:
        with self._lock:
            return self._count

    def should_shutdown(self) -> bool:
        """True once every tab has closed and the grace window has elapsed."""
        with self._lock:
            if not self._seen_any or self._count > 0 or self._empty_since is None:
                return False
            return (self._clock() - self._empty_since) >= self._empty_grace


# Process-wide singleton shared by the router (writes) and the entrypoint watcher
# (reads), the same pattern as `node_index_gate`.
presence = SessionPresence()
