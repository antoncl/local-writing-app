"""Presence tracking that lets a desktop launch quit when its last tab closes (#1378).

Two seams:
  - `SessionPresence` — the pure connect/disconnect counter + grace decision,
    driven here by an injected clock so timing is deterministic.
  - `/api/session/live` — the WebSocket that feeds the shared tracker, exercised
    through the real app so a connect increments and a close decrements.
"""

from __future__ import annotations

from app.services.session_presence import SessionPresence


class FakeClock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


# --- the counter + grace decision -----------------------------------------


def test_never_shuts_down_before_any_tab_connects() -> None:
    clock = FakeClock()
    presence = SessionPresence(empty_grace=5.0, clock=clock)
    # Startup: no tab has connected yet (the auto-opened browser may still be
    # loading). An empty count here is "not open yet", not "closed".
    clock.now = 1000.0
    assert presence.should_shutdown() is False


def test_open_tab_never_shuts_down() -> None:
    clock = FakeClock()
    presence = SessionPresence(empty_grace=5.0, clock=clock)
    presence.connect()
    clock.now = 10_000.0  # arbitrarily far in the future
    assert presence.active == 1
    assert presence.should_shutdown() is False


def test_shuts_down_only_after_grace_elapses() -> None:
    clock = FakeClock()
    presence = SessionPresence(empty_grace=5.0, clock=clock)
    presence.connect()
    clock.now = 100.0
    presence.disconnect()
    assert presence.should_shutdown() is False   # grace not yet elapsed
    clock.now = 104.9
    assert presence.should_shutdown() is False   # still within grace
    clock.now = 105.0
    assert presence.should_shutdown() is True     # grace elapsed


def test_reload_within_grace_does_not_shut_down() -> None:
    clock = FakeClock()
    presence = SessionPresence(empty_grace=5.0, clock=clock)
    presence.connect()
    clock.now = 100.0
    presence.disconnect()          # reload drops the old socket...
    clock.now = 102.0
    presence.connect()             # ...and the new page connects within grace
    clock.now = 200.0
    assert presence.active == 1
    assert presence.should_shutdown() is False


def test_last_of_several_tabs_arms_shutdown() -> None:
    clock = FakeClock()
    presence = SessionPresence(empty_grace=5.0, clock=clock)
    presence.connect()
    presence.connect()
    clock.now = 50.0
    presence.disconnect()
    assert presence.active == 1
    assert presence.should_shutdown() is False    # one tab still open
    presence.disconnect()
    clock.now = 56.0
    assert presence.should_shutdown() is True      # last tab gone + grace


def test_stray_disconnect_does_not_reset_empty_clock() -> None:
    clock = FakeClock()
    presence = SessionPresence(empty_grace=5.0, clock=clock)
    presence.connect()
    clock.now = 100.0
    presence.disconnect()          # empty clock starts at t=100
    clock.now = 103.0
    presence.disconnect()          # a spurious extra close must not push it out
    clock.now = 105.0
    assert presence.active == 0
    assert presence.should_shutdown() is True      # still armed off the t=100 mark


# --- the WebSocket wiring ---------------------------------------------------


def test_live_socket_counts_connect_and_disconnect() -> None:
    import time

    from fastapi.testclient import TestClient

    import app.services.session_presence as sp
    from app.main import app

    client = TestClient(app)
    before = sp.presence.active  # relative: the singleton persists across tests
    with client.websocket_connect("/api/session/live"):
        assert sp.presence.active == before + 1
    # The server-side disconnect runs on the app's thread; poll briefly so the
    # assertion doesn't race the close propagation.
    deadline = time.monotonic() + 2.0
    while sp.presence.active != before and time.monotonic() < deadline:
        time.sleep(0.01)
    assert sp.presence.active == before


# --- the entrypoint watcher wiring -----------------------------------------


class _StubServer:
    def __init__(self) -> None:
        self.should_exit = False


def test_watcher_stops_server_when_the_last_tab_closes(monkeypatch) -> None:
    import time

    import app.server as server_module

    monkeypatch.setattr(server_module.presence, "should_shutdown", lambda: True)
    server = _StubServer()
    server_module._arm_auto_shutdown(server, poll_interval=0.01)

    deadline = time.monotonic() + 2.0
    while not server.should_exit and time.monotonic() < deadline:
        time.sleep(0.01)
    assert server.should_exit is True


def test_watcher_leaves_server_running_while_a_tab_is_open(monkeypatch) -> None:
    import time

    import app.server as server_module

    monkeypatch.setattr(server_module.presence, "should_shutdown", lambda: False)
    server = _StubServer()
    server_module._arm_auto_shutdown(server, poll_interval=0.01)

    time.sleep(0.1)  # give the daemon several poll cycles
    assert server.should_exit is False
