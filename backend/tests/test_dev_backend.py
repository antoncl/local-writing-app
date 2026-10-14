"""`scripts/dev_backend.py` isolates the Claude worktree app's machine config (#1998).

The worktree dev server runs the REAL app; without `LWA_CONFIG_DIR` it reads and
writes the developer's real `%APPDATA%/config.yaml` — recents,
`default_projects_folder`, palette, and the provider API keys — so a
create/settings action in the dev instance silently clobbers real machine
settings. This pins that `env_for_server` redirects the config seam to a
per-worktree throwaway dir, the isolation pytest (`conftest`) and the Playwright
webServer already have. The runtime guard in `machine_settings.config_dir()`
(covered in `test_machine_settings.TestConfigDirIsolationGuard`) is the second
line of defence if this ever regresses.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _load_script(name: str):
    """Import a module from `scripts/`, which is not a package (the gate-test idiom,
    shared with test_clean_worktrees / test_gate_invariants)."""
    path = Path(__file__).resolve().parents[2] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_script_{name}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Register before exec: a spec-loaded module resolves `__module__` via
    # sys.modules (Python 3.14), None for an unregistered spec.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_env_for_server_isolates_the_machine_config(monkeypatch: pytest.MonkeyPatch) -> None:
    dev_backend = _load_script("dev_backend")
    # A clean environment (conftest's LWA_CONFIG_DIR removed) so `setdefault`
    # fills in the per-worktree throwaway dir rather than inheriting one.
    monkeypatch.delenv("LWA_CONFIG_DIR", raising=False)
    env = dev_backend.env_for_server("nonce")
    assert env["LWA_CONFIG_DIR"] == str(dev_backend.REPO / "tmp" / "claude-config")


def test_explicit_config_dir_override_is_respected(monkeypatch: pytest.MonkeyPatch) -> None:
    # An explicit LWA_CONFIG_DIR in the environment still wins (setdefault) — a
    # caller that deliberately isolated elsewhere is not overridden.
    dev_backend = _load_script("dev_backend")
    monkeypatch.setenv("LWA_CONFIG_DIR", str(Path("deliberate") / "override"))
    env = dev_backend.env_for_server("nonce")
    assert env["LWA_CONFIG_DIR"] == str(Path("deliberate") / "override")


class _FakeProcess:
    def __init__(self, log: list[str], name: str) -> None:
        self.log, self.name = log, name

    def terminate(self) -> None:
        self.log.append(f"terminate {self.name}")

    def join(self) -> None:
        self.log.append(f"join {self.name}")

    def start(self) -> None:
        self.log.append(f"start {self.name}")


def test_reload_restart_terminates_the_old_server_and_starts_a_new_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # #2471: uvicorn's Windows restart sent a console Ctrl+C that never arrived,
    # so `join()` hung and the old server kept serving stale code. The wrapper's
    # restart terminates instead — it must stop the old child before starting
    # the new one, and hand uvicorn's own config/target/sockets to the new one.
    from uvicorn.supervisors.basereload import BaseReload

    # Loading the wrapper patches BaseReload on Windows; undo it after the test.
    monkeypatch.setattr(BaseReload, "restart", BaseReload.restart)
    dev_uvicorn = _load_script("dev_uvicorn")
    log: list[str] = []
    calls: list[dict] = []

    def fake_get_subprocess(**kwargs):
        calls.append(kwargs)
        return _FakeProcess(log, "new")

    monkeypatch.setattr(dev_uvicorn, "get_subprocess", fake_get_subprocess)
    reloader = type("Reloader", (), {})()
    reloader.process = _FakeProcess(log, "old")
    reloader.config, reloader.target, reloader.sockets = "cfg", "tgt", ["sock"]

    dev_uvicorn.restart_by_terminate(reloader)

    assert log == ["terminate old", "join old", "start new"]
    assert calls == [{"config": "cfg", "target": "tgt", "sockets": ["sock"]}]
    assert reloader.process.name == "new"


def test_the_uvicorn_internals_the_restart_relies_on_are_still_there() -> None:
    # The wrapper reaches into uvicorn (pinned in requirements.lock); an upgrade
    # that moves these must fail here, not hang a dev server again.
    import inspect

    from uvicorn._subprocess import get_subprocess
    from uvicorn.supervisors.basereload import BaseReload

    assert {"config", "target", "sockets"} <= set(inspect.signature(get_subprocess).parameters)
    assert callable(BaseReload.restart)


def test_the_wrapper_replaces_the_restart_on_windows_only(monkeypatch: pytest.MonkeyPatch) -> None:
    # POSIX keeps uvicorn's own restart (SIGTERM via terminate() already works).
    from uvicorn.supervisors.basereload import BaseReload

    monkeypatch.setattr(BaseReload, "restart", BaseReload.restart)
    dev_uvicorn = _load_script("dev_uvicorn")
    patched = BaseReload.restart is dev_uvicorn.restart_by_terminate
    assert patched == (sys.platform == "win32")


def test_the_launcher_runs_uvicorn_through_the_wrapper() -> None:
    source = (Path(__file__).resolve().parents[2] / "scripts" / "dev_backend.py").read_text(
        encoding="utf-8"
    )
    assert '"dev_uvicorn.py"' in source
    assert '"-m", "uvicorn"' not in source
