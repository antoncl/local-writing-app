from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from app.models import RecentProject, Swatch

APP_NAME = "local-writing-app"
CONFIG_FILENAME = "config.yaml"
MASK = "********"
RECENT_PROJECTS_MAX = 10

DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-haiku-4-5-20251001",
    "openai": "gpt-4o-mini",
    "openrouter": "anthropic/claude-haiku-4.5",
    "ollama": "llama3.2",
}


# The seed palette. Exactly 30 swatches so the SwatchPicker grid fills
# its default 5×6 layout with no empty cells. The first four ids
# (forest, slate-blue, warm-brown, graphite) preserve the historical
# `--ctx-k-*` values from ContextPicker.svelte so the picker's chips
# and monograms keep their look once the hardcoded vars are removed.
# The rest is a writer-friendly spread across hues, picked to read on
# both light and dark backgrounds.
DEFAULT_PALETTE: list[dict[str, str]] = [
    {"id": "forest", "label": "Forest", "hex": "#3f7d68"},
    {"id": "slate-blue", "label": "Slate Blue", "hex": "#4f7390"},
    {"id": "warm-brown", "label": "Warm Brown", "hex": "#976b46"},
    {"id": "graphite", "label": "Graphite", "hex": "#5f6f67"},
    {"id": "sage", "label": "Sage", "hex": "#7a9b7e"},
    {"id": "moss", "label": "Moss", "hex": "#5b7a3a"},
    {"id": "olive", "label": "Olive", "hex": "#8a8a3a"},
    {"id": "mint", "label": "Mint", "hex": "#5fae8c"},
    {"id": "teal", "label": "Teal", "hex": "#3f7d80"},
    {"id": "ocean", "label": "Ocean", "hex": "#2f6680"},
    {"id": "sky", "label": "Sky", "hex": "#6f9fc4"},
    {"id": "navy", "label": "Navy", "hex": "#2d3f5e"},
    {"id": "indigo", "label": "Indigo", "hex": "#4a5896"},
    {"id": "lavender", "label": "Lavender", "hex": "#8c84bf"},
    {"id": "violet", "label": "Violet", "hex": "#6b4d8a"},
    {"id": "mauve", "label": "Mauve", "hex": "#8e6a7e"},
    {"id": "plum", "label": "Plum", "hex": "#8a3f6a"},
    {"id": "fuchsia", "label": "Fuchsia", "hex": "#b04590"},
    {"id": "rose", "label": "Rose", "hex": "#b0567a"},
    {"id": "crimson", "label": "Crimson", "hex": "#a8423f"},
    {"id": "brick", "label": "Brick", "hex": "#8a3f2a"},
    {"id": "coral", "label": "Coral", "hex": "#c46a52"},
    {"id": "rust", "label": "Rust", "hex": "#9a5a36"},
    {"id": "chocolate", "label": "Chocolate", "hex": "#704a2e"},
    {"id": "amber", "label": "Amber", "hex": "#c08a3a"},
    {"id": "ochre", "label": "Ochre", "hex": "#a08236"},
    {"id": "sand", "label": "Sand", "hex": "#c0a874"},
    {"id": "stone", "label": "Stone", "hex": "#7d7768"},
    {"id": "silver", "label": "Silver", "hex": "#94a09a"},
    {"id": "charcoal", "label": "Charcoal", "hex": "#3a423f"},
    # Standard signaling primaries — recognizable RAG + blue/orange + a
    # neutral. Picked to read as the literal color name (vs. the curated
    # tones above) and to tint well under color-mix(... 12%, white 88%).
    {"id": "red", "label": "Red", "hex": "#d44a4a"},
    {"id": "green", "label": "Green", "hex": "#3eaa5a"},
    {"id": "yellow", "label": "Yellow", "hex": "#d8b22a"},
    {"id": "blue", "label": "Blue", "hex": "#3a76d8"},
    {"id": "orange", "label": "Orange", "hex": "#e07a26"},
    {"id": "gray", "label": "Gray", "hex": "#8a948f"},
]


class ProviderCredentials(BaseModel):
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    openrouter_api_key: str = ""
    ollama_host: str = "http://127.0.0.1:11434"


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


def _seed_palette() -> list[Swatch]:
    return [Swatch(**entry) for entry in DEFAULT_PALETTE]


class MachineSettings(BaseModel):
    version: int = 1
    providers: ProviderCredentials = Field(default_factory=ProviderCredentials)
    default_provider: str = "ollama"
    default_models: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_MODELS))
    default_projects_folder: str = ""
    recent_projects: list[RecentProject] = Field(default_factory=list)
    palette: list[Swatch] = Field(default_factory=_seed_palette)


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


def assistants_dir() -> Path:
    """Folder holding assistant entry files. Derived from `config_path()` so
    test fixtures that patch the config path automatically isolate this too."""
    return config_path().parent / "assistants"


def load_settings() -> MachineSettings:
    """Read config.yaml. Side-effect: on first load after upgrade, when no
    assistant files exist but the legacy `default_models` matrix does, write
    one assistant file per (provider, model) pair so the file-backed roster
    is non-empty going forward. The Slice A inline `assistants` list has been
    removed — files are canonical."""
    path = config_path()
    if not path.exists():
        settings = MachineSettings()
    else:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            settings = MachineSettings()
        else:
            if not isinstance(data, dict):
                settings = MachineSettings()
            else:
                # Drop legacy inline fields if a config from Slice A/B/C is
                # encountered — they're now ignored.
                data.pop("assistants", None)
                data.pop("default_assistant_id", None)
                try:
                    settings = MachineSettings.model_validate(data)
                except Exception:
                    settings = MachineSettings()
    _migrate_default_models_to_files_if_empty(settings)
    _top_up_palette(settings)
    return settings


def _top_up_palette(settings: MachineSettings) -> None:
    """Append any seed swatches the user's stored palette is missing.

    Purely additive — never reorders, renames, or removes user swatches.
    Handles the seed growing over time without forcing existing users to
    manually re-add new colors. If the user *deleted* a seed swatch on
    purpose, it'll come back here; reset is a known limitation."""
    existing_ids = {s.id for s in settings.palette}
    appended: list[Swatch] = []
    for entry in DEFAULT_PALETTE:
        if entry["id"] not in existing_ids:
            appended.append(Swatch(**entry))
    if appended:
        settings.palette = list(settings.palette) + appended


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
    if "default_projects_folder" in patch and patch["default_projects_folder"] is not None:
        base["default_projects_folder"] = patch["default_projects_folder"]
    if "recent_projects" in patch and patch["recent_projects"] is not None:
        # An explicit list rewrites the recents — used when the user removes
        # a stale entry from the UI.
        base["recent_projects"] = patch["recent_projects"]
    if "palette" in patch and patch["palette"] is not None:
        # The palette is edited as a whole list in the settings UI — reorder,
        # add, rename, delete all yield a new list. Validate via Pydantic so
        # malformed swatches (bad hex, empty id) raise before save.
        base["palette"] = [
            Swatch.model_validate(s).model_dump(mode="json")
            for s in patch["palette"]
        ]
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


def touch_recent_project(root_path: Path, title: str) -> None:
    """Move-to-top a project on the recents list. Cap at RECENT_PROJECTS_MAX.

    Best-effort: any failure (read-only config dir, malformed yaml) is
    swallowed — recents is UX polish, not a correctness path. The create /
    open flows must not break because of a recents-write hiccup.
    """
    try:
        path_str = str(root_path.expanduser().resolve())
        now_iso = datetime.now(UTC).isoformat(timespec="seconds")
        settings = load_settings()
        kept = [r for r in settings.recent_projects if r.path != path_str]
        kept.insert(0, RecentProject(path=path_str, title=title, opened_at=now_iso))
        settings.recent_projects = kept[:RECENT_PROJECTS_MAX]
        save_settings(settings)
    except Exception:  # noqa: BLE001
        # Don't let recents tracking break project open/create.
        pass


# ----- File-based assistant migration (one-shot) ---------------------------


def _migrate_default_models_to_files_if_empty(settings: MachineSettings) -> None:
    """When no assistant files exist but `default_models` does, materialize
    the matrix as files (one per non-empty pair). Subsequent runs see the
    files and skip. The pair matching `default_provider` is flagged
    is_default."""
    folder = assistants_dir()
    if folder.exists() and any(folder.glob("*.md")):
        return
    pairs: list[tuple[str, str]] = [
        (provider, model)
        for provider, model in settings.default_models.items()
        if model
    ]
    if not pairs:
        return
    folder.mkdir(parents=True, exist_ok=True)
    seen_slugs: set[str] = set()
    for provider, model in pairs:
        label = PROVIDER_DISPLAY_NAMES.get(provider, provider)
        title = f"{label}: {model}"
        base_id = _slugify(title)
        assistant_id = base_id
        suffix = 2
        while assistant_id in seen_slugs:
            assistant_id = f"{base_id}-{suffix}"
            suffix += 1
        seen_slugs.add(assistant_id)
        metadata: dict[str, Any] = {
            "ai_provider": provider,
            "ai_model": model,
            # Intentionally no `ai_temperature` — let the provider apply its
            # own default unless the user sets one explicitly. Some newer
            # models (e.g. claude-opus-4-7) reject an explicit temperature.
            "ai_max_tokens": 4096,
        }
        if provider == settings.default_provider:
            metadata["is_default"] = True
        front: dict[str, Any] = {
            "id": assistant_id,
            "title": title,
            "entry_type": "assistant",
            "metadata": metadata,
        }
        front_text = yaml.safe_dump(front, sort_keys=False, allow_unicode=True).strip()
        (folder / f"{assistant_id}.md").write_text(
            f"---\n{front_text}\n---\n\n", encoding="utf-8"
        )
