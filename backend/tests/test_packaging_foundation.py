"""ADR-0072 slice S1 — "one process, one origin" (#1340).

Covers the frontend-mount seam (`mount_frontend`) and the product entrypoint's
bind-address resolution (`app/server.py`), independently of any real built
frontend or real machine config.yaml.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import mount_frontend
from app.server import _is_loopback, resolve_bind


def test_mount_frontend_serves_index_and_leaves_api(tmp_path: Path) -> None:
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    (dist_dir / "index.html").write_text("<h1>hi</h1>", encoding="utf-8")

    app = FastAPI()

    @app.get("/api/ping")
    def ping() -> dict[str, bool]:
        return {"ok": True}

    mount_frontend(app, dist_dir)
    client = TestClient(app)

    index_response = client.get("/")
    assert index_response.status_code == 200
    assert "hi" in index_response.text

    api_response = client.get("/api/ping")
    assert api_response.status_code == 200
    assert api_response.json() == {"ok": True}

    missing_response = client.get("/assets-that-dont-exist")
    assert missing_response.status_code == 404


def test_mount_frontend_none_is_noop() -> None:
    app = FastAPI()
    mount_frontend(app, None)
    client = TestClient(app)
    # No frontend mounted and no routes registered -> a plain 404, not a crash.
    assert client.get("/").status_code == 404


def test_resolve_bind_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.server as server

    monkeypatch.delenv("LWA_HOST", raising=False)
    monkeypatch.delenv("LWA_PORT", raising=False)
    monkeypatch.setattr(server, "bind_address", lambda: ("192.168.1.5", 9000))

    # CLI flag wins over everything.
    assert resolve_bind(["--host", "10.0.0.1", "--port", "1234"]) == ("10.0.0.1", 1234)

    # Env wins over settings when no CLI flag.
    monkeypatch.setenv("LWA_HOST", "10.0.0.2")
    monkeypatch.setenv("LWA_PORT", "4321")
    assert resolve_bind([]) == ("10.0.0.2", 4321)

    # Settings used when no flag/env.
    monkeypatch.delenv("LWA_HOST", raising=False)
    monkeypatch.delenv("LWA_PORT", raising=False)
    assert resolve_bind([]) == ("192.168.1.5", 9000)

    # Default loopback when everything is unset.
    monkeypatch.setattr(server, "bind_address", lambda: (None, None))
    assert resolve_bind([]) == ("127.0.0.1", 8787)


def test_is_loopback() -> None:
    assert _is_loopback("127.0.0.1") is True
    assert _is_loopback("localhost") is True
    assert _is_loopback("0.0.0.0") is False
    assert _is_loopback("192.168.1.5") is False


def test_version_endpoint_reports_running_version() -> None:
    from importlib.metadata import version as _pkg_version

    from app.main import app

    client = TestClient(app)
    response = client.get("/api/version")
    assert response.status_code == 200
    body = response.json()
    assert body == {"version": _pkg_version("local-writing-service")}
    assert body["version"]  # non-empty


def test_frontend_dist_dir_uses_frozen_meipass(tmp_path, monkeypatch) -> None:
    import app.services.frontend_assets as fa

    frozen = tmp_path / "frontend_dist"
    frozen.mkdir()
    monkeypatch.setattr(fa.sys, "frozen", True, raising=False)
    monkeypatch.setattr(fa.sys, "_MEIPASS", str(tmp_path), raising=False)
    assert fa.frontend_dist_dir() == frozen


def test_frontend_dist_dir_frozen_but_missing_is_none(tmp_path, monkeypatch) -> None:
    import app.services.frontend_assets as fa

    monkeypatch.setattr(fa.sys, "frozen", True, raising=False)
    monkeypatch.setattr(fa.sys, "_MEIPASS", str(tmp_path), raising=False)  # no frontend_dist subdir
    assert fa.frontend_dist_dir() is None


def test_build_identity_reads_frozen_stamp(tmp_path, monkeypatch) -> None:
    import app.services.project.node_index_snapshot as nis

    (tmp_path / nis.FROZEN_IDENTITY_FILENAME).write_text("deadbeefcafe0001", encoding="utf-8")
    monkeypatch.setattr(nis.sys, "frozen", True, raising=False)
    monkeypatch.setattr(nis.sys, "_MEIPASS", str(tmp_path), raising=False)
    # lru_cache: clear so the frozen branch runs, not a cached live digest.
    nis.build_identity.cache_clear()
    try:
        assert nis.build_identity() == "deadbeefcafe0001"
    finally:
        nis.build_identity.cache_clear()  # don't leak the frozen value into other tests


def test_build_identity_frozen_missing_stamp_raises(tmp_path, monkeypatch) -> None:
    import app.services.project.node_index_snapshot as nis

    monkeypatch.setattr(nis.sys, "frozen", True, raising=False)
    monkeypatch.setattr(nis.sys, "_MEIPASS", str(tmp_path), raising=False)  # no stamp file
    nis.build_identity.cache_clear()
    try:
        with pytest.raises(RuntimeError, match=nis.FROZEN_IDENTITY_FILENAME):
            nis.build_identity()
    finally:
        nis.build_identity.cache_clear()
