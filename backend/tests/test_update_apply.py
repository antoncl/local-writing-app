"""ADR-0072 slice S6 — the in-app update *apply* (#2083).

The check half is `test_updates.py`; this covers the download + swap-on-restart
installer: platform gating, the download/verify/apply state machine (with the
network and the real installer/subprocess stubbed), the channel asset URL, and
the routes. Nothing here spawns a real process or stops a real server.
"""
from __future__ import annotations

import hashlib
import threading

import httpx
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
    assert url.endswith(ua._platform_asset())


def test_asset_url_nightly_uses_nightly_tag() -> None:
    url = ua._asset_url("nightly")
    assert "/releases/download/nightly/" in url
    assert url.endswith(ua._platform_asset())


def test_platform_asset_windows(monkeypatch) -> None:
    monkeypatch.setattr(ua.sys, "platform", "win32")
    assert ua._platform_asset() == ua._WINDOWS_SETUP_ASSET


def test_platform_asset_linux(monkeypatch) -> None:
    monkeypatch.setattr(ua.sys, "platform", "linux")
    assert ua._platform_asset() == ua._LINUX_APPIMAGE_ASSET


def test_platform_asset_macos(monkeypatch) -> None:
    monkeypatch.setattr(ua.sys, "platform", "darwin")
    assert ua._platform_asset() == ua._MACOS_DMG_ASSET


def test_macos_app_path_finds_enclosing_bundle(monkeypatch) -> None:
    monkeypatch.setattr(
        ua.sys, "executable", "/Applications/Local Writing App.app/Contents/MacOS/local-writing-app"
    )
    assert ua._macos_app_path() == "/Applications/Local Writing App.app"


def test_macos_app_path_none_when_not_in_bundle(monkeypatch) -> None:
    monkeypatch.setattr(ua.sys, "executable", "/opt/local-writing-app/local-writing-app")
    assert ua._macos_app_path() is None


# --- platform gating (frozen only; Linux needs $APPIMAGE) ------------------


def test_apply_supported_frozen_windows(monkeypatch) -> None:
    monkeypatch.setattr(ua.sys, "frozen", True, raising=False)
    monkeypatch.setattr(ua.sys, "platform", "win32")
    assert ua.apply_supported() is True


def test_apply_supported_frozen_linux_appimage(monkeypatch) -> None:
    monkeypatch.setattr(ua.sys, "frozen", True, raising=False)
    monkeypatch.setattr(ua.sys, "platform", "linux")
    monkeypatch.setenv("APPIMAGE", "/home/u/Apps/local-writing-app.AppImage")
    assert ua.apply_supported() is True


def test_apply_unsupported_frozen_linux_without_appimage(monkeypatch) -> None:
    # A frozen Linux run that isn't an AppImage (portable zip / headless tarball)
    # has no in-app apply path — update-server.sh handles the tarball.
    monkeypatch.setattr(ua.sys, "frozen", True, raising=False)
    monkeypatch.setattr(ua.sys, "platform", "linux")
    monkeypatch.delenv("APPIMAGE", raising=False)
    assert ua.apply_supported() is False


def test_apply_supported_frozen_macos_in_bundle(monkeypatch) -> None:
    monkeypatch.setattr(ua.sys, "frozen", True, raising=False)
    monkeypatch.setattr(ua.sys, "platform", "darwin")
    monkeypatch.setattr(ua, "_macos_app_path", lambda: "/Applications/Local Writing App.app")
    assert ua.apply_supported() is True


def test_apply_unsupported_frozen_macos_not_in_bundle(monkeypatch) -> None:
    # A raw onedir/zip run on macOS has no `.app` to swap.
    monkeypatch.setattr(ua.sys, "frozen", True, raising=False)
    monkeypatch.setattr(ua.sys, "platform", "darwin")
    monkeypatch.setattr(ua, "_macos_app_path", lambda: None)
    assert ua.apply_supported() is False


# --- the download -> verify -> apply state machine -------------------------


def test_run_success_applies_and_requests_shutdown(monkeypatch) -> None:
    # Stub the platform apply step so this is deterministic on any OS.
    calls: dict[str, object] = {}

    def fake_download(url, dest, on_progress):
        on_progress(0.5)
        dest.write_bytes(b"x" * 2048)
        calls["url"] = url
        return 2048

    monkeypatch.setattr(ua, "_download", fake_download)
    # No manifest -> install unverified; the checksum path has its own tests below.
    monkeypatch.setattr(ua, "_expected_sha256", lambda channel, asset: None)
    monkeypatch.setattr(ua, "_apply", lambda path: calls.__setitem__("applied", path))
    monkeypatch.setattr(
        ua.runtime_control, "request_shutdown", lambda: calls.__setitem__("shutdown", True) or True
    )

    ua._run("nightly")

    assert "/releases/download/nightly/" in calls["url"]
    assert calls.get("applied") is not None
    assert calls.get("shutdown") is True
    assert ua.current_status().state == "applying"


def test_run_error_on_empty_download(monkeypatch) -> None:
    # An empty file must be refused and must NOT hand off to the apply step.
    def empty_download(url, dest, on_progress):
        dest.write_bytes(b"")
        return 0

    applied = {"count": 0}
    monkeypatch.setattr(ua, "_download", empty_download)
    monkeypatch.setattr(ua, "_apply", lambda path: applied.__setitem__("count", applied["count"] + 1))
    monkeypatch.setattr(ua.runtime_control, "request_shutdown", lambda: True)

    ua._run("stable")

    status = ua.current_status()
    assert status.state == "error"
    assert status.detail
    assert applied["count"] == 0


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


# --- checksum verification (SHA256SUMS) ------------------------------------


class _FakeResponse:
    """Stands in for `httpx.get(...)` returning the SHA256SUMS manifest."""

    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code


def test_sha256_file_hashes_in_blocks(tmp_path) -> None:
    payload = b"the quick brown fox" * 100_000  # spans several 1 MiB blocks
    f = tmp_path / "blob"
    f.write_bytes(payload)
    assert ua._sha256_file(f) == hashlib.sha256(payload).hexdigest()


def test_expected_sha256_parses_the_matching_line(monkeypatch) -> None:
    asset = ua._platform_asset()
    manifest = (
        "aaaa  local-writing-app-linux-x64.zip\n"
        f"{'b' * 64}  {asset}\n"
        "cccc  local-writing-app-macos-arm64.dmg\n"
    )
    monkeypatch.setattr(ua.httpx, "get", lambda *a, **k: _FakeResponse(manifest))
    assert ua._expected_sha256("nightly", asset) == "b" * 64


def test_expected_sha256_strips_binary_mode_asterisk(monkeypatch) -> None:
    asset = ua._platform_asset()
    monkeypatch.setattr(ua.httpx, "get", lambda *a, **k: _FakeResponse(f"{'d' * 64} *{asset}\n"))
    assert ua._expected_sha256("stable", asset) == "d" * 64


def test_expected_sha256_none_on_absent_manifest(monkeypatch) -> None:
    # A release predating the manifest returns 404 -> None (install unverified).
    monkeypatch.setattr(ua.httpx, "get", lambda *a, **k: _FakeResponse("", status_code=404))
    assert ua._expected_sha256("stable", ua._platform_asset()) is None


def test_expected_sha256_none_on_network_error(monkeypatch) -> None:
    def boom(*a, **k):
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(ua.httpx, "get", boom)
    assert ua._expected_sha256("nightly", ua._platform_asset()) is None


def test_expected_sha256_none_on_server_error(monkeypatch) -> None:
    # A transient 5xx/403 for the manifest must degrade to unverified (like a
    # network failure), NOT hard-fail an update whose asset already downloaded.
    monkeypatch.setattr(ua.httpx, "get", lambda *a, **k: _FakeResponse("", status_code=503))
    assert ua._expected_sha256("nightly", ua._platform_asset()) is None


def test_expected_sha256_raises_when_manifest_omits_asset(monkeypatch) -> None:
    # Manifest present but missing our asset is a packaging bug -> fail closed.
    monkeypatch.setattr(
        ua.httpx, "get", lambda *a, **k: _FakeResponse("aaaa  some-other-asset.zip\n")
    )
    with pytest.raises(RuntimeError):
        ua._expected_sha256("nightly", ua._platform_asset())


def test_run_error_on_checksum_mismatch(monkeypatch) -> None:
    # A complete download whose hash doesn't match the manifest must NOT install.
    def fake_download(url, dest, on_progress):
        dest.write_bytes(b"corrupt bytes")
        return 13

    applied = {"count": 0}
    monkeypatch.setattr(ua, "_download", fake_download)
    monkeypatch.setattr(ua, "_expected_sha256", lambda channel, asset: "f" * 64)
    monkeypatch.setattr(ua, "_apply", lambda path: applied.__setitem__("count", 1))
    monkeypatch.setattr(ua.runtime_control, "request_shutdown", lambda: True)

    ua._run("nightly")

    status = ua.current_status()
    assert status.state == "error"
    assert "checksum" in (status.detail or "").lower()
    assert applied["count"] == 0


def test_run_installs_when_checksum_matches(monkeypatch) -> None:
    payload = b"the real asset bytes"

    def fake_download(url, dest, on_progress):
        dest.write_bytes(payload)
        return len(payload)

    applied = {"count": 0}
    monkeypatch.setattr(ua, "_download", fake_download)
    monkeypatch.setattr(
        ua, "_expected_sha256", lambda channel, asset: hashlib.sha256(payload).hexdigest()
    )
    monkeypatch.setattr(ua, "_apply", lambda path: applied.__setitem__("count", 1))
    monkeypatch.setattr(ua.runtime_control, "request_shutdown", lambda: True)

    ua._run("stable")

    assert ua.current_status().state == "applying"
    assert applied["count"] == 1


def test_run_download_failure_becomes_error_not_crash(monkeypatch) -> None:
    def boom(url, dest, on_progress):
        raise RuntimeError("network went away")

    monkeypatch.setattr(ua, "_download", boom)
    monkeypatch.setattr(ua, "_apply", lambda path: pytest.fail("must not apply"))

    ua._run("stable")  # must not raise

    assert ua.current_status().state == "error"


# --- the AppImage swap helper (Linux) --------------------------------------


def test_spawn_appimage_swap_raises_without_appimage_env(monkeypatch) -> None:
    monkeypatch.delenv("APPIMAGE", raising=False)
    with pytest.raises(RuntimeError):
        ua._spawn_appimage_swap("/tmp/new.AppImage")


def test_spawn_appimage_swap_launches_detached_helper(monkeypatch) -> None:
    monkeypatch.setenv("APPIMAGE", "/home/u/Apps/local-writing-app.AppImage")
    seen: dict[str, object] = {}

    def fake_popen(argv, **kwargs):
        seen["argv"] = argv
        seen["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(ua.subprocess, "Popen", fake_popen)
    ua._spawn_appimage_swap("/tmp/new.AppImage")

    argv = seen["argv"]
    assert argv[0] == "/bin/sh" and argv[1] == "-c"
    # positional args to the helper: pid, new path, current AppImage path
    assert argv[-1] == "/home/u/Apps/local-writing-app.AppImage"
    assert argv[-2] == "/tmp/new.AppImage"
    assert seen["kwargs"].get("start_new_session") is True


# --- the dmg swap helper (macOS) -------------------------------------------


def test_spawn_macos_swap_raises_when_not_in_a_bundle(monkeypatch) -> None:
    monkeypatch.setattr(ua, "_macos_app_path", lambda: None)
    with pytest.raises(RuntimeError):
        ua._spawn_macos_swap("/tmp/new.dmg")


def test_spawn_macos_swap_launches_detached_helper(monkeypatch) -> None:
    monkeypatch.setattr(ua, "_macos_app_path", lambda: "/Applications/Local Writing App.app")
    monkeypatch.setattr(ua.tempfile, "mkdtemp", lambda **k: "/tmp/lwa-update-mnt-X")
    seen: dict[str, object] = {}

    def fake_popen(argv, **kwargs):
        seen["argv"] = argv
        seen["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(ua.subprocess, "Popen", fake_popen)
    ua._spawn_macos_swap("/tmp/new.dmg")

    argv = seen["argv"]
    assert argv[0] == "/bin/sh" and argv[1] == "-c"
    # positional args to the helper: pid, dmg, target .app, mountpoint
    assert argv[-1] == "/tmp/lwa-update-mnt-X"
    assert argv[-2] == "/Applications/Local Writing App.app"
    assert argv[-3] == "/tmp/new.dmg"
    assert seen["kwargs"].get("start_new_session") is True


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
