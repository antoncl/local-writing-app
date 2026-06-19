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


class Assistant(BaseModel):
    """A user-defined model configuration: 'who you hire' under a subscription.

    `id` is a stable slug (kebab-case typical). `name` is the user-facing label.
    `provider` + `model` resolve which subscription and which model the call
    goes to. `temperature` and `max_tokens` are the only knobs surfaced today;
    additional params (top_p, persona, etc.) are out of scope for Phase 1.
    """

    id: str
    name: str
    provider: str
    model: str
    temperature: float = 0.7
    max_tokens: int = 4096


PROVIDER_DISPLAY_NAMES = {
    "anthropic": "Anthropic",
    "openai": "OpenAI",
    "openrouter": "OpenRouter",
    "ollama": "Ollama",
}


def _slugify(text: str) -> str:
    import re

    cleaned = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return cleaned or "assistant"


class MachineSettings(BaseModel):
    version: int = 1
    providers: ProviderCredentials = Field(default_factory=ProviderCredentials)
    default_provider: str = "ollama"
    default_models: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_MODELS))
    assistants: list[Assistant] = Field(default_factory=list)
    default_assistant_id: str = ""


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
        return _backfill_assistants(MachineSettings())
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return _backfill_assistants(MachineSettings())
    if not isinstance(data, dict):
        return _backfill_assistants(MachineSettings())
    try:
        settings = MachineSettings.model_validate(data)
    except Exception:
        settings = MachineSettings()
    return _backfill_assistants(settings)


def _backfill_assistants(settings: MachineSettings) -> MachineSettings:
    """Generate one assistant per non-empty (provider, model) pair if the
    roster is empty. Pre-existing rosters are left alone — the user owns the
    list once any entry exists."""
    if settings.assistants:
        if not settings.default_assistant_id or not any(
            a.id == settings.default_assistant_id for a in settings.assistants
        ):
            settings = settings.model_copy(
                update={"default_assistant_id": settings.assistants[0].id}
            )
        return settings

    assistants: list[Assistant] = []
    seen_ids: set[str] = set()
    for provider, model in settings.default_models.items():
        if not model:
            continue
        provider_label = PROVIDER_DISPLAY_NAMES.get(provider, provider)
        name = f"{provider_label}: {model}"
        base_id = _slugify(name)
        assistant_id = base_id
        suffix = 2
        while assistant_id in seen_ids:
            assistant_id = f"{base_id}-{suffix}"
            suffix += 1
        seen_ids.add(assistant_id)
        assistants.append(
            Assistant(
                id=assistant_id,
                name=name,
                provider=provider,
                model=model,
            )
        )

    default_id = ""
    if settings.default_provider:
        match = next(
            (a for a in assistants if a.provider == settings.default_provider),
            None,
        )
        default_id = match.id if match else (assistants[0].id if assistants else "")
    elif assistants:
        default_id = assistants[0].id

    return settings.model_copy(
        update={"assistants": assistants, "default_assistant_id": default_id}
    )


def resolve_assistant(
    settings: MachineSettings, assistant_id: str | None
) -> Assistant | None:
    """Look up an assistant by id; falls back to the default. Returns None
    when the roster is empty or the requested id is unknown and there is no
    default to fall back to."""
    candidate_id = assistant_id or settings.default_assistant_id
    if not candidate_id:
        return None
    for assistant in settings.assistants:
        if assistant.id == candidate_id:
            return assistant
    return None


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
    if "assistants" in patch and isinstance(patch["assistants"], list):
        base["assistants"] = patch["assistants"]
    if "default_assistant_id" in patch and patch["default_assistant_id"] is not None:
        base["default_assistant_id"] = patch["default_assistant_id"]
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
