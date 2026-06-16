from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


APP_NAME = "local-writing-app"
CONFIG_FILENAME = "config.yaml"
MASK = "********"

DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-haiku-4-5-20251001",
    "openai": "gpt-4o-mini",
    "openrouter": "anthropic/claude-haiku-4.5",
    "ollama": "llama3.2",
}


class ProviderCredentials(BaseModel):
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    openrouter_api_key: str = ""
    ollama_host: str = "http://127.0.0.1:11434"


class MachineSettings(BaseModel):
    version: int = 1
    providers: ProviderCredentials = Field(default_factory=ProviderCredentials)
    default_provider: str = "ollama"
    default_models: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_MODELS))


def config_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        if base:
            return Path(base) / APP_NAME
        return Path.home() / "AppData" / "Roaming" / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        return Path(base) / APP_NAME
    return Path.home() / ".config" / APP_NAME


def config_path() -> Path:
    return config_dir() / CONFIG_FILENAME


def load_settings() -> MachineSettings:
    path = config_path()
    if not path.exists():
        return MachineSettings()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return MachineSettings()
    if not isinstance(data, dict):
        return MachineSettings()
    try:
        return MachineSettings.model_validate(data)
    except Exception:
        return MachineSettings()


def save_settings(settings: MachineSettings) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = settings.model_dump(mode="json")
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def mask_credentials(settings: MachineSettings) -> dict[str, Any]:
    payload = settings.model_dump(mode="json")
    providers = payload.get("providers", {})
    for key in ("anthropic_api_key", "openai_api_key", "openrouter_api_key"):
        if providers.get(key):
            providers[key] = MASK
    payload["providers"] = providers
    return payload


def merge_update(current: MachineSettings, patch: dict[str, Any]) -> MachineSettings:
    """Apply a partial update; MASK sentinels mean 'keep current value'."""
    base = current.model_dump(mode="json")
    if "default_provider" in patch and patch["default_provider"] is not None:
        base["default_provider"] = patch["default_provider"]
    if "default_models" in patch and isinstance(patch["default_models"], dict):
        base.setdefault("default_models", {}).update(patch["default_models"])
    providers_patch = patch.get("providers")
    if isinstance(providers_patch, dict):
        providers = base.setdefault("providers", {})
        for key, value in providers_patch.items():
            if value is None:
                continue
            if value == MASK:
                continue  # keep current
            providers[key] = value
    return MachineSettings.model_validate(base)
