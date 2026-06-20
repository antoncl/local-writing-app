"""Pytest-wide fixtures.

The autouse fixture below redirects `machine_settings.config_path()` to a
per-test tempdir so tests can't accidentally read or write the developer's
real ~/AppData (or ~/.config) machine settings. Tests that need stricter
control (e.g. test_assistants) still patch config_path themselves; their
patch takes precedence over this safety net.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_machine_settings(tmp_path, monkeypatch):
    from app.services import machine_settings as ms

    fake = tmp_path / "machine" / "config.yaml"
    monkeypatch.setattr(ms, "config_path", lambda: fake)
    yield
