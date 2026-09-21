"""Auto-update routes (ADR-0072 S6, #1362/#2083).

Thin translators, like every router (ADR-0056): read the running version + build
stamp + configured channel, hand them to the updates service, return its verdict.
`/apply` and `/apply/status` drive the download + swap-on-restart install.
No project scope — updates are a machine/app concern, not a per-project one.
"""
from __future__ import annotations

from importlib.metadata import version as _pkg_version

from fastapi import APIRouter

from app.models import UpdateApplyStatus, UpdateCheck
from app.services import machine_settings as machine_settings_service
from app.services import update_apply as update_apply_service
from app.services import updates as updates_service
from app.services.build_info import build_stamp

router = APIRouter()


@router.get("/api/updates/check", response_model=UpdateCheck)
def check_for_update() -> UpdateCheck:
    # `update_channel()` is a direct config read (no settings side effects), the
    # same discipline `bind_address()`/`default_ai_policy()` follow.
    result = updates_service.check_for_update(
        channel=machine_settings_service.update_channel(),
        current_version=_pkg_version("local-writing-service"),
        current_build=build_stamp(),
    )
    # Whether the UI should offer "Install and restart" vs only the release link.
    result.can_apply = update_apply_service.apply_supported()
    return result


@router.post("/api/updates/apply", response_model=UpdateApplyStatus)
def apply_update() -> UpdateApplyStatus:
    # Install the configured channel's latest — the same channel the check used.
    return update_apply_service.start_apply(machine_settings_service.update_channel())


@router.get("/api/updates/apply/status", response_model=UpdateApplyStatus)
def apply_status() -> UpdateApplyStatus:
    return update_apply_service.current_status()
