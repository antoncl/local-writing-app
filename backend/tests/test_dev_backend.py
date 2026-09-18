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
