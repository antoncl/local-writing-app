"""Machine-settings and assistant-tag routes (#170 main.py split)."""
from __future__ import annotations

import ipaddress
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from app.models import (
    AssistantTagList,
    AssistantTagsOverview,
    MachineSettingsUpdate,
    MachineSettingsView,
    MergeAssistantTagsRequest,
    SetAssistantTagColorRequest,
)
from app.runtime import CurrentProject, translate_errors
from app.services import machine_settings as machine_settings_service

router = APIRouter()


def _build_settings_view(masked: dict[str, Any]) -> MachineSettingsView:
    # A recent that now points outside the machine projects root is marked
    # unavailable — equivalent to a deleted folder (#441). Computed here, never
    # stored; a pure path test, so it never mis-flags an unmounted drive. Read
    # the root once and reuse it across every recent (one traversal, not N).
    root = machine_settings_service.projects_root()
    recents = [
        {**r, "within_root": machine_settings_service.is_within_root(Path(r["path"]), root)}
        for r in masked.get("recent_projects", [])
    ]
    return MachineSettingsView(
        version=masked["version"],
        providers=masked["providers"],
        default_provider=masked["default_provider"],
        default_models=masked["default_models"],
        default_projects_folder=masked.get("default_projects_folder", ""),
        recent_projects=recents,
        palette=masked.get("palette", []),
        display=masked.get("display", {}),
        ai_policy=masked.get("ai_policy", "off"),
        update_channel=masked.get("update_channel", "stable"),
        config_path=str(machine_settings_service.config_path()),
        config_dir=str(machine_settings_service.config_dir()),
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


def _is_loopback_client(host: str | None) -> bool:
    """Whether the request's peer is on this machine (a loopback IP).

    ``request.client.host`` is a numeric peer address, so this is an IP test, not
    a hostname one — ``ipaddress.is_loopback`` (as ``server.py`` uses) classifies
    every loopback form (127.0.0.0/8, ``::1``, IPv4-mapped) rather than matching a
    couple of literals.
    """
    if not host:
        return False
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@router.post("/api/settings/machine/reveal-logs")
def reveal_logs(request: Request) -> dict[str, str]:
    """Open the app-data (logs) folder in the OS file manager (#1749).

    Loopback-only: the folder lives on the *server* machine, so this only helps a
    caller on that machine (a desktop launch). A remote (LAN/Pi) caller is refused
    rather than spawning a file manager on the server's desktop. The frontend also
    hides the button off-loopback; this is the matching backend guard.
    """
    if not _is_loopback_client(request.client.host if request.client else None):
        raise HTTPException(
            status_code=403,
            detail="Opening the logs folder is only available on the local machine.",
        )
    machine_settings_service.reveal_config_dir()
    return {"config_dir": str(machine_settings_service.config_dir())}


@router.get("/api/assistant-tags", response_model=AssistantTagList)
def get_assistant_tags() -> AssistantTagList:
    # Machine-global (assistants live machine-globally), so this is not scoped
    # to the open project (#88).
    return AssistantTagList(tags=machine_settings_service.load_assistant_tags())


@router.get("/api/assistant-tags/overview", response_model=AssistantTagsOverview)
def get_assistant_tags_overview(project: CurrentProject) -> AssistantTagsOverview:
    # Machine-global vocabulary, but the use-counts read the open project's
    # prompt docs, so this rides the project scope like the governance ops (#247).
    # With no project open it degrades to the machine roster alone.
    with translate_errors():
        return project.read_assistant_tags_overview()


@router.post("/api/assistant-tags/merge", response_model=AssistantTagList)
def merge_assistant_tags(project: CurrentProject, request: MergeAssistantTagsRequest) -> AssistantTagList:
    # Rename is a single-source merge. Rewrites reachable references then the
    # flat store; the survivor keeps its own colour (#247).
    with translate_errors():
        return project.merge_assistant_tags(request)


@router.put("/api/assistant-tags/{name}", response_model=AssistantTagList)
def set_assistant_tag_color(name: str, request: SetAssistantTagColorRequest) -> AssistantTagList:
    return AssistantTagList(tags=machine_settings_service.set_assistant_tag_color(name, request.color))


