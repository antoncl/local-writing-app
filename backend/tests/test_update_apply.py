"""ADR-0072 slice S6 — the in-app update *apply* (#2083).

The check half is `test_updates.py`; this covers the download + swap-on-restart
installer: platform gating, the download/verify/apply state machine (with the
network and the real installer/subprocess stubbed), the channel asset URL, and
the routes. Nothing here spawns a real process or stops a real server.
"""
from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient

from app.services import runtime_control
from app.services import update_apply as ua


@pytest.fixture(autouse=True)
def _reset_state():
    # The apply state and the server handle are module singletons — reset around
    # every test so ordering can't leak one test's status into the next.
    ua._state.set(state="idle", progress=0.0, detail=None)
    runtime_control._server = None
    yield
    ua._state.set(state="idle", progress=0.0, detail=None)
    runtime_control._server = None


# --- platform gating -------------------------------------------------------


def test_apply_unsupported_in_source_run() -> None:
    # The test process isn't frozen, so there's nothing to replace regardless of OS.
    assert ua.apply_supported() is False


def test_start_apply_reports_unsupported_when_gated(monkeypatch) -> None:
    monkeypatch.setattr(ua, "apply_supported", lambda: False)
    status = ua.start_apply("stable")
    assert status.state == "unsupported"
    assert status.detail


# --- asset URL per channel -------------------------------------------------


def test_asset_url_stable_uses_latest() -> None:
    url = ua._asset_url("stable")
    assert "/releases/latest/download/" in url
    assert url.endswith(ua._WINDOWS_SETUP_ASSET)


def test_asset_url_nightly_uses_nightly_tag() -> None:
    url = ua._asset_url("nightly")
    assert "/releases/download/nightly/" in url
    assert url.endswith(ua._WINDOWS_SETUP_ASSET)


# --- the download -> verify -> apply state machine -------------------------


def test_run_success_spawns_installer_and_requests_shutdown(monkeypatch) -> None:
    calls: dict[str, object] = {}

    def fake_download(url, dest, on_progress):
        on_progress(0.5)
        dest.write_bytes(b"x" * 2048)
        calls["url"] = url
        return 2048

    monkeypatch.setattr(ua, "_download", fake_download)
    monkeypatch.setattr(ua, "_spawn_installer", lambda path: calls.__setitem__("spawned", path))
    monkeypatch.setattr(
        ua.runtime_control, "request_shutdown", lambda: calls.__setitem__("shutdown", True) or True
    )

    ua._run("nightly")

    assert "/releases/download/nightly/" in calls["url"]
    assert calls.get("spawned") is not None
    assert calls.get("shutdown") is True
    assert ua.current_status().state == "applying"


def test_run_error_on_empty_download(monkeypatch) -> None:
    # An empty file must be refused and must NOT hand off to the installer.
    def empty_download(url, dest, on_progress):
        dest.write_bytes(b"")
        return 0

    spawned = {"count": 0}
    monkeypatch.setattr(ua, "_download", empty_download)
    monkeypatch.setattr(ua, "_spawn_installer", lambda path: spawned.__setitem__("count", spawned["count"] + 1))
    monkeypatch.setattr(ua.runtime_control, "request_shutdown", lambda: True)

    ua._run("stable")

    status = ua.current_status()
    assert status.state == "error"
    assert status.detail
    assert spawned["count"] == 0


class _FakeStream:
    """Stands in for `httpx.stream(...)` — a context manager that is also the
    response, yielding fixed chunks under a declared Content-Length."""

    def __init__(self, chunks, content_length):
        self._chunks = chunks
        self.headers = {"Content-Length": str(content_length)}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        pass

    def iter_bytes(self):
        yield from self._chunks


def test_download_raises_on_short_read(monkeypatch, tmp_path) -> None:
    # Body ends at 10 bytes but Content-Length said 20 — a real completeness
    # check, not the tautology of comparing a file to its own byte count.
    monkeypatch.setattr(ua.httpx, "stream", lambda *a, **k: _FakeStream([b"x" * 10], 20))
    with pytest.raises(RuntimeError):
        ua._download("http://x", tmp_path / "f", lambda frac: None)


def test_download_returns_written_when_complete(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(ua.httpx, "stream", lambda *a, **k: _FakeStream([b"x" * 8, b"y" * 12], 20))
    dest = tmp_path / "f"
    assert ua._download("http://x", dest, lambda frac: None) == 20
    assert dest.stat().st_size == 20


def test_run_download_failure_becomes_error_not_crash(monkeypatch) -> None:
    def boom(url, dest, on_progress):
        raise RuntimeError("network went away")

    monkeypatch.setattr(ua, "_download", boom)
    monkeypatch.setattr(ua, "_spawn_installer", lambda path: pytest.fail("must not spawn"))

    ua._run("stable")  # must not raise

    assert ua.current_status().state == "error"


def test_start_apply_is_idempotent_while_busy(monkeypatch) -> None:
    monkeypatch.setattr(ua, "apply_supported", lambda: True)
    ua._state.set(state="downloading", progress=0.3)
    started = {"count": 0}
    monkeypatch.setattr(ua, "_run", lambda channel: started.__setitem__("count", started["count"] + 1))

    status = ua.start_apply("stable")

    assert status.state == "downloading"
    assert started["count"] == 0  # no new run kicked off


def test_start_apply_launches_worker_when_idle(monkeypatch) -> None:
    monkeypatch.setattr(ua, "apply_supported", lambda: True)
    ran = threading.Event()
    monkeypatch.setattr(ua, "_run", lambda channel: ran.set())

    status = ua.start_apply("stable")

    assert status.state == "downloading"
    assert ran.wait(timeout=2.0)


# --- runtime_control -------------------------------------------------------


def test_request_shutdown_false_without_a_server() -> None:
    assert runtime_control.request_shutdown() is False


def test_request_shutdown_sets_should_exit() -> None:
    class FakeServer:
        should_exit = False

    server = FakeServer()
    runtime_control.register_server(server)
    assert runtime_control.request_shutdown() is True
    assert server.should_exit is True


# --- routes ----------------------------------------------------------------


def test_check_endpoint_reports_can_apply() -> None:
    from app.main import app

    body = TestClient(app).get("/api/updates/check").json()
    # Not frozen in tests, so in-app apply is unavailable — the UI shows the link.
    assert body["can_apply"] is False


def test_apply_route_returns_status_and_status_route_reads_it(monkeypatch) -> None:
    from app.main import app

    # Gate on so the route reaches the worker path; stub the worker so nothing
    # actually downloads or stops the server.
    monkeypatch.setattr(ua, "apply_supported", lambda: True)
    monkeypatch.setattr(ua, "_run", lambda channel: None)
    client = TestClient(app)

    started = client.post("/api/updates/apply")
    assert started.status_code == 200
    assert started.json()["state"] == "downloading"

    status = client.get("/api/updates/apply/status")
    assert status.status_code == 200
    assert status.json()["state"] in ("downloading", "idle")


def test_apply_route_unsupported_off_platform(monkeypatch) -> None:
    from app.main import app

    monkeypatch.setattr(ua, "apply_supported", lambda: False)
    body = TestClient(app).post("/api/updates/apply").json()
    assert body["state"] == "unsupported"
