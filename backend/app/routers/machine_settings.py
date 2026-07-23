"""Machine-settings and assistant-tag routes (#170 main.py split)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.models import (
    AssistantTagList,
    MachineSettingsUpdate,
    MachineSettingsView,
    SetAssistantTagColorRequest,
)
from app.runtime import translate_errors
from app.services import machine_settings as machine_settings_service

router = APIRouter()


def _build_settings_view(masked: dict[str, Any]) -> MachineSettingsView:
    return MachineSettingsView(
        version=masked["version"],
        providers=masked["providers"],
        default_provider=masked["default_provider"],
        default_models=masked["default_models"],
        default_projects_folder=masked.get("default_projects_folder", ""),
        recent_projects=masked.get("recent_projects", []),
        palette=masked.get("palette", []),
        config_path=str(machine_settings_service.config_path()),
    )


@router.get("/api/settings/machine", response_model=MachineSettingsView)
def get_machine_settings() -> MachineSettingsView:
    current = machine_settings_service.load_settings()
    masked = machine_settings_service.mask_credentials(current)
    return _build_settings_view(masked)


@router.put("/api/settings/machine", response_model=MachineSettingsView)
def update_machine_settings(request: MachineSettingsUpdate) -> MachineSettingsView:
    # Guarded since #429: `default_projects_folder` is the layer walk's bound
    # for every project on the machine, so a bad value here is not a local
    # mistake — it silently flattens every chain at once.
    with translate_errors():
        current = machine_settings_service.load_settings()
        patch = request.model_dump(exclude_unset=True)
        updated = machine_settings_service.merge_update(current, patch)
        machine_settings_service.save_settings(updated)
        masked = machine_settings_service.mask_credentials(updated)
        return _build_settings_view(masked)


@router.get("/api/assistant-tags", response_model=AssistantTagList)
def get_assistant_tags() -> AssistantTagList:
    # Machine-global (assistants live machine-globally), so this is not scoped
    # to the open project (#88).
    return AssistantTagList(tags=machine_settings_service.load_assistant_tags())


@router.put("/api/assistant-tags/{name}", response_model=AssistantTagList)
def set_assistant_tag_color(name: str, request: SetAssistantTagColorRequest) -> AssistantTagList:
    return AssistantTagList(tags=machine_settings_service.set_assistant_tag_color(name, request.color))


