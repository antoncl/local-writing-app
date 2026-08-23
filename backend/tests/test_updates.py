"""ADR-0072 slice S6 — the auto-update check (#1362).

Three seams, each isolated from the network and the developer's real config:
  - `build_info.build_stamp()` — the frozen commit stamp (source run -> None).
  - `updates.check_for_update()` — the channel comparison, over a mocked GitHub.
  - `machine_settings.update_channel()` — the direct-read channel accessor.
"""

from __future__ import annotations

import httpx
import yaml
from fastapi.testclient import TestClient

from app.services import machine_settings as ms
from app.services import updates as updates_service

# --- build stamp -----------------------------------------------------------


def test_build_stamp_none_in_source_run() -> None:
    from app.services.build_info import build_stamp

    # Not frozen: no bundle to read a stamp from.
    assert build_stamp() is None


def test_build_stamp_reads_frozen_file(tmp_path, monkeypatch) -> None:
    import app.services.build_info as bi

    (tmp_path / bi.BUILD_STAMP_FILENAME).write_text("abc123def456\n", encoding="utf-8")
    monkeypatch.setattr(bi.sys, "frozen", True, raising=False)
    monkeypatch.setattr(bi.sys, "_MEIPASS", str(tmp_path), raising=False)
    assert bi.build_stamp() == "abc123def456"


def test_build_stamp_frozen_but_empty_is_none(tmp_path, monkeypatch) -> None:
    import app.services.build_info as bi

    # A local freeze bakes GITHUB_SHA="" -> an empty file -> unknown, not "".
    (tmp_path / bi.BUILD_STAMP_FILENAME).write_text("", encoding="utf-8")
    monkeypatch.setattr(bi.sys, "frozen", True, raising=False)
    monkeypatch.setattr(bi.sys, "_MEIPASS", str(tmp_path), raising=False)
    assert bi.build_stamp() is None


def test_build_stamp_frozen_missing_file_is_none(tmp_path, monkeypatch) -> None:
    import app.services.build_info as bi

    # Unlike the node-index identity, a missing stamp must NOT crash — it only
    # means "can't compare", which the update check degrades on.
    monkeypatch.setattr(bi.sys, "frozen", True, raising=False)
    monkeypatch.setattr(bi.sys, "_MEIPASS", str(tmp_path), raising=False)  # no file
    assert bi.build_stamp() is None


# --- update check: mocked GitHub -------------------------------------------


def _mock_github(monkeypatch, handler) -> None:
    """Force every httpx.Client the updates service opens onto a MockTransport,
    so a request is answered by `handler` instead of the network. Timeout and
    headers still flow through the real Client — only the transport is swapped."""
    real_client = httpx.Client

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(updates_service.httpx, "Client", factory)


def _stable_release(tag: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={"tag_name": tag, "html_url": f"https://example.test/releases/{tag}"},
    )


def test_stable_update_available(monkeypatch) -> None:
    _mock_github(monkeypatch, lambda req: _stable_release("v0.9.5"))
    result = updates_service.check_for_update("stable", "0.9.0", None)
    assert result.reachable is True
    assert result.update_available is True
    assert result.latest == "v0.9.5"
    assert result.latest_url == "https://example.test/releases/v0.9.5"


def test_stable_up_to_date(monkeypatch) -> None:
    _mock_github(monkeypatch, lambda req: _stable_release("v0.9.0"))
    result = updates_service.check_for_update("stable", "0.9.0", None)
    assert result.update_available is False
    assert result.latest == "v0.9.0"


def test_stable_running_ahead_is_not_an_update(monkeypatch) -> None:
    # A dev running 0.9.1 against a 0.9.0 latest must not be told to "update".
    _mock_github(monkeypatch, lambda req: _stable_release("v0.9.0"))
    result = updates_service.check_for_update("stable", "0.9.1", None)
    assert result.update_available is False


def test_stable_no_release_yet(monkeypatch) -> None:
    _mock_github(monkeypatch, lambda req: httpx.Response(404, json={"message": "Not Found"}))
    result = updates_service.check_for_update("stable", "0.9.0", None)
    assert result.reachable is True
    assert result.update_available is False
    assert result.detail == "no stable release yet"


def test_offline_is_reachable_false_not_an_error(monkeypatch) -> None:
    def boom(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=req)

    _mock_github(monkeypatch, boom)
    result = updates_service.check_for_update("stable", "0.9.0", None)
    assert result.reachable is False
    assert result.update_available is False
    assert result.detail  # carries a note


def _nightly_ref(sha: str) -> httpx.Response:
    return httpx.Response(200, json={"object": {"sha": sha, "type": "commit"}})


def test_nightly_update_available_on_differing_commit(monkeypatch) -> None:
    _mock_github(monkeypatch, lambda req: _nightly_ref("f" * 40))
    result = updates_service.check_for_update("nightly", "0.9.0", "a" * 40)
    assert result.update_available is True
    assert result.latest == "f" * 12
    assert result.latest_url.endswith("/releases/tag/nightly")


def test_nightly_up_to_date_on_same_commit(monkeypatch) -> None:
    sha = "a" * 40
    _mock_github(monkeypatch, lambda req: _nightly_ref(sha))
    result = updates_service.check_for_update("nightly", "0.9.0", sha)
    assert result.update_available is False


def test_nightly_without_build_stamp_cannot_compare(monkeypatch) -> None:
    _mock_github(monkeypatch, lambda req: _nightly_ref("f" * 40))
    result = updates_service.check_for_update("nightly", "0.9.0", None)
    assert result.reachable is True
    assert result.update_available is False
    assert result.detail == "no build stamp to compare"


def test_nightly_no_build_yet(monkeypatch) -> None:
    _mock_github(monkeypatch, lambda req: httpx.Response(404, json={"message": "Not Found"}))
    result = updates_service.check_for_update("nightly", "0.9.0", "a" * 40)
    assert result.reachable is True
    assert result.update_available is False
    assert result.detail == "no nightly build yet"
    # No link to a page that doesn't exist yet.
    assert result.latest_url is None


# --- channel accessor + endpoint -------------------------------------------


def _write_config(channel: str) -> None:
    path = ms.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"update_channel": channel}), encoding="utf-8")


def test_update_channel_defaults_stable_when_unset() -> None:
    assert ms.update_channel() == "stable"


def test_update_channel_reads_config() -> None:
    _write_config("nightly")
    assert ms.update_channel() == "nightly"


def test_update_channel_bad_value_falls_back_to_stable() -> None:
    _write_config("bleeding-edge")  # not a valid channel
    assert ms.update_channel() == "stable"


def test_check_endpoint_uses_configured_channel(monkeypatch) -> None:
    from app.main import app

    _write_config("nightly")
    seen = {}

    def fake_check(channel, current_version, current_build):
        seen["channel"] = channel
        from app.models import UpdateCheck

        return UpdateCheck(channel=channel, current_version=current_version)

    monkeypatch.setattr("app.routers.updates.updates_service.check_for_update", fake_check)
    response = TestClient(app).get("/api/updates/check")
    assert response.status_code == 200
    assert seen["channel"] == "nightly"
    assert response.json()["channel"] == "nightly"


def test_settings_round_trip_update_channel() -> None:
    from app.main import app

    client = TestClient(app)
    put = client.put("/api/settings/machine", json={"update_channel": "nightly"})
    assert put.status_code == 200
    assert put.json()["update_channel"] == "nightly"
    # Persisted: a fresh GET reflects it, and the direct accessor agrees.
    assert client.get("/api/settings/machine").json()["update_channel"] == "nightly"
    assert ms.update_channel() == "nightly"


def test_settings_rejects_bad_channel() -> None:
    from app.main import app

    client = TestClient(app)
    bad = client.put("/api/settings/machine", json={"update_channel": "hourly"})
    assert bad.status_code == 422
