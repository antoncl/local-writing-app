"""Pytest-wide fixtures.

`_isolate_machine_settings` redirects `machine_settings.config_path()` to a
per-test tempdir so tests can't accidentally read or write the developer's
real ~/AppData (or ~/.config) machine settings. Tests that need stricter
control (e.g. test_assistants) still patch config_path themselves; their
patch takes precedence over this safety net.

`_inject_wire_scope` plays the browser (#413): since the resolution scope now
rides the wire (`X-Project-Root`), it injects the current test's scope header on
every `TestClient` request, so routes resolve their project from the request
exactly as in production. It also resets the scope per-test so one test's open
project never leaks into the next.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_machine_settings(tmp_path, monkeypatch):
    from app.services import machine_settings as ms

    fake = tmp_path / "machine" / "config.yaml"
    monkeypatch.setattr(ms, "config_path", lambda: fake)
    yield


@pytest.fixture(autouse=True)
def _inject_wire_scope(monkeypatch):
    import project_fixtures
    from starlette.testclient import TestClient

    project_fixtures.clear_test_scope()
    original_request = TestClient.request

    def request_with_scope(self, method, url, *args, headers=None, **kwargs):
        merged = dict(headers) if headers else {}
        for key, value in project_fixtures.test_scope_header().items():
            merged.setdefault(key, value)  # an explicit header still wins
        return original_request(self, method, url, *args, headers=merged, **kwargs)

    monkeypatch.setattr(TestClient, "request", request_with_scope)
    yield
    project_fixtures.clear_test_scope()
