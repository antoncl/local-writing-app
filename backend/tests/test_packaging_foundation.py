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

    def bind(argv: list[str]) -> tuple[str, int]:
        return resolve_bind(server._build_parser().parse_args(argv))

    monkeypatch.delenv("LWA_HOST", raising=False)
    monkeypatch.delenv("LWA_PORT", raising=False)
    monkeypatch.setattr(server, "bind_address", lambda: ("192.168.1.5", 9000))

    # CLI flag wins over everything.
    assert bind(["--host", "10.0.0.1", "--port", "1234"]) == ("10.0.0.1", 1234)

    # Env wins over settings when no CLI flag.
    monkeypatch.setenv("LWA_HOST", "10.0.0.2")
    monkeypatch.setenv("LWA_PORT", "4321")
    assert bind([]) == ("10.0.0.2", 4321)

    # Settings used when no flag/env.
    monkeypatch.delenv("LWA_HOST", raising=False)
    monkeypatch.delenv("LWA_PORT", raising=False)
    assert bind([]) == ("192.168.1.5", 9000)

    # Default loopback when everything is unset.
    monkeypatch.setattr(server, "bind_address", lambda: (None, None))
    assert bind([]) == ("127.0.0.1", 8787)


def test_is_loopback() -> None:
    assert _is_loopback("127.0.0.1") is True
    assert _is_loopback("localhost") is True
    assert _is_loopback("0.0.0.0") is False
    assert _is_loopback("192.168.1.5") is False


def test_should_open_browser_matrix(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.server as server

    monkeypatch.delenv("LWA_NO_BROWSER", raising=False)

    def args(argv: list[str]):
        return server._build_parser().parse_args(argv)

    # A loopback desktop launch with no opt-out → open the browser (#1365).
    assert server._should_open_browser(args([]), "127.0.0.1") is True
    assert server._should_open_browser(args([]), "localhost") is True
    # A non-loopback bind is the LAN/Pi server — headless, never open a browser.
    assert server._should_open_browser(args([]), "0.0.0.0") is False
    assert server._should_open_browser(args([]), "192.168.1.5") is False
    # Explicit opt-outs win even on loopback (the systemd unit passes the flag).
    assert server._should_open_browser(args(["--no-browser"]), "127.0.0.1") is False
    monkeypatch.setenv("LWA_NO_BROWSER", "1")
    assert server._should_open_browser(args([]), "127.0.0.1") is False
    # An explicit "off" spelling of the env var is not a suppression.
    monkeypatch.setenv("LWA_NO_BROWSER", "0")
    assert server._should_open_browser(args([]), "127.0.0.1") is True


def test_open_browser_when_ready_opens_once_listening(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    import app.server as server

    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen()
    port = srv.getsockname()[1]
    try:
        server._open_browser_when_ready("127.0.0.1", port, timeout=3.0)
    finally:
        srv.close()
    assert opened == [f"http://127.0.0.1:{port}"]


def test_open_browser_when_ready_gives_up_if_never_listening(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    import app.server as server

    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))
    # Nothing ever binds → the poll must time out and never open a dead URL.
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: (_ for _ in ()).throw(OSError("refused")))
    server._open_browser_when_ready("127.0.0.1", 59999, timeout=0.3)
    assert opened == []


def test_self_check_opens_a_project() -> None:
    # The self-check drives the real service layer (create a temp project, read
    # structure/lore/prompts), so a green run here means the runtime paths the
    # frozen --self-check exercises are sound. In a source run this is not a
    # frozen test, but it locks the self-check itself against regressions.
    from app.server import self_check

    assert self_check() == 0


def test_self_check_probes_the_lazy_preview_chain() -> None:
    # The probe must actually load the preview modules that are only imported
    # lazily at request time — that's the whole point (a frozen build with a bad
    # PYZ entry among them would raise here). Loading them locks the names against
    # drift: rename one and this fails, signalling the probe needs updating.
    import sys

    from app.server import _preview_import_probe

    _preview_import_probe()
    for name in (
        "app.services.ai.context_expander",
        "app.services.ai.lore_block",
        "app.services.ai.lore_selection",
    ):
        assert name in sys.modules


def test_probe_covers_the_lazy_preview_imports() -> None:
    # Drift guard: if a new lazy import is added to _preview_lore_tiers, the probe
    # must import it too — otherwise a bad PYZ entry for that new module ships
    # silently again, the exact blind spot this guard exists to close. Derive both
    # sets from source so they can't quietly diverge. `sessions` is excluded: it is
    # also imported at preview.py's module top, so self-check already loads it.
    import ast
    import inspect

    from app import server
    from app.services.ai import preview

    tree = ast.parse(inspect.getsource(preview))
    eager = {n.module for n in tree.body if isinstance(n, ast.ImportFrom) and n.module}
    lazy: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_preview_lore_tiers":
            lazy = {
                s.module
                for s in ast.walk(node)
                if isinstance(s, ast.ImportFrom) and s.module
            }
    lazy_only = {m for m in lazy if m.startswith("app.services.ai.") and m not in eager}
    assert lazy_only, "expected _preview_lore_tiers to have lazy-only preview imports"

    probe = ast.parse(inspect.getsource(server._preview_import_probe))
    probed = {a.name for n in ast.walk(probe) if isinstance(n, ast.Import) for a in n.names}
    missing = lazy_only - probed
    assert not missing, f"_preview_import_probe must import {missing} (see _preview_lore_tiers)"


def test_self_check_fails_when_a_preview_module_cannot_load(monkeypatch) -> None:
    # A frozen build whose lazy preview chain can't import (the arm64 `zlib:
    # incorrect header check`) must make --self-check FAIL, so CI catches it
    # instead of a user's first chat. Simulate that by making the probe raise.
    from app import server

    def boom() -> None:
        raise RuntimeError("simulated undecompressable preview module")

    monkeypatch.setattr(server, "_preview_import_probe", boom)
    assert server.self_check() == 1


def test_version_endpoint_reports_running_version() -> None:
    from importlib.metadata import version as _pkg_version

    from app.main import app

    client = TestClient(app)
    response = client.get("/api/version")
    assert response.status_code == 200
    body = response.json()
    # `build` is None in a source run (no baked stamp); the version is the
    # running package version. (The nightly update check compares `build`, S6.)
    assert body == {"version": _pkg_version("local-writing-service"), "build": None}
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
