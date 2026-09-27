"""Provider API keys live in the OS secret store, not config.yaml (#2287).

Every test here runs against conftest's per-test in-memory keyring
(`_isolate_keyring`), and config.yaml is redirected to a per-test tmp dir
(`_isolate_machine_settings`) — so nothing reaches the developer's real
Credential Manager / Keychain or real config.
"""

from __future__ import annotations

from pathlib import Path

import keyring
import pytest
import yaml
from fastapi.testclient import TestClient
from keyring.backends import null
from keyring.errors import KeyringError

from app.main import app
from app.services import machine_settings as ms
from app.services import secret_store

_KEY = "sk-test-not-a-real-key"


def _service() -> str:
    return secret_store.service_name(ms.config_path().parent)


def _file_providers() -> dict:
    return yaml.safe_load(ms.config_path().read_text(encoding="utf-8"))["providers"]


def _settings_with_key() -> ms.MachineSettings:
    settings = ms.load_settings()
    settings.providers.anthropic_api_key = _KEY
    return settings


def test_a_saved_key_goes_to_the_store_not_the_file(_isolate_keyring) -> None:
    ms.save_settings(_settings_with_key())

    assert _file_providers()["anthropic_api_key"] == ""
    assert _isolate_keyring.entries[(_service(), "anthropic_api_key")] == _KEY
    assert ms.load_settings().providers.anthropic_api_key == _KEY


def test_a_plaintext_key_in_the_file_moves_to_the_store_on_load(_isolate_keyring) -> None:
    # A config written before #2287: the key sits in plaintext.
    ms.config_path().parent.mkdir(parents=True, exist_ok=True)
    ms.config_path().write_text(
        yaml.safe_dump({"version": 2, "providers": {"openrouter_api_key": _KEY}}), encoding="utf-8"
    )

    assert ms.load_settings().providers.openrouter_api_key == _KEY
    assert _file_providers()["openrouter_api_key"] == "", "the plaintext key is scrubbed from the file"
    assert _isolate_keyring.entries[(_service(), "openrouter_api_key")] == _KEY


def test_clearing_a_key_deletes_it_from_the_store(_isolate_keyring) -> None:
    ms.save_settings(_settings_with_key())
    settings = ms.load_settings()
    settings.providers.anthropic_api_key = ""
    ms.save_settings(settings)

    assert (_service(), "anthropic_api_key") not in _isolate_keyring.entries
    assert ms.load_settings().providers.anthropic_api_key == ""


def test_with_no_store_the_key_stays_in_the_file() -> None:
    keyring.set_keyring(null.Keyring())  # conftest's fixture restores the previous backend

    assert not ms.keys_in_os_store()
    ms.save_settings(_settings_with_key())
    assert _file_providers()["anthropic_api_key"] == _KEY
    assert ms.load_settings().providers.anthropic_api_key == _KEY


def test_a_key_the_store_refuses_stays_in_the_file_rather_than_be_lost(_isolate_keyring, monkeypatch) -> None:
    def refuse(*_args) -> None:
        raise KeyringError("locked")

    monkeypatch.setattr(_isolate_keyring, "set_password", refuse)
    ms.save_settings(_settings_with_key())

    assert _file_providers()["anthropic_api_key"] == _KEY


def test_each_config_dir_gets_its_own_entry_however_it_was_isolated() -> None:
    # The real %APPDATA% config, a worktree's LWA_CONFIG_DIR and an E2E run's
    # overridden APPDATA all resolve to different dirs, so different entries.
    real = secret_store.service_name(Path("C:/Users/someone/AppData/Roaming/local-writing-app"))
    e2e = secret_store.service_name(Path("C:/Temp/lwa-e2e-home/local-writing-app"))
    assert real != e2e
    assert real.startswith("local-writing-app/")
    assert real == secret_store.service_name(Path("C:/Users/someone/AppData/Roaming/local-writing-app"))


def test_an_isolated_config_neither_sees_nor_clobbers_the_real_keys(tmp_path, monkeypatch) -> None:
    # "Real" config: a key is saved.
    ms.save_settings(_settings_with_key())
    # An E2E-style run isolates the config some other way (here: a different
    # dir, as an overridden APPDATA would give) and clears the key.
    real_config_path = ms.config_path
    isolated = tmp_path / "e2e-home" / "config.yaml"
    monkeypatch.setattr(ms, "config_path", lambda: isolated)
    assert ms.load_settings().providers.anthropic_api_key == ""
    cleared = ms.load_settings()
    cleared.providers.anthropic_api_key = ""
    ms.save_settings(cleared)
    # Back on the real config, its key is untouched.
    monkeypatch.setattr(ms, "config_path", real_config_path)
    assert ms.load_settings().providers.anthropic_api_key == _KEY


def test_a_real_os_keyring_is_refused_in_a_test_process() -> None:
    real_looking = type("Keyring", (null.Keyring,), {"__module__": "keyring.backends.Windows", "priority": 5})
    keyring.set_keyring(real_looking())

    with pytest.raises(RuntimeError, match="2287"):
        secret_store.available()


def test_the_settings_api_masks_the_key_and_reports_the_store() -> None:
    ms.save_settings(_settings_with_key())

    view = TestClient(app).get("/api/settings/machine").json()

    assert view["providers"]["anthropic_api_key"] == ms.MASK
    assert view["keys_in_os_store"] is True
