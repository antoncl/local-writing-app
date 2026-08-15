"""Assistant temperature validation (#178 slice 1).

The (provider, model, temperature) compatibility check that guards the
assistants-save path lives here as a free function, not in the HTTP layer.
It used to be reached by a router→router import (`routers/entries.py` →
`routers/ai.py`) — the coupling this extraction removes. Capability queries
run through the registry's credential-less `capability_profile_for`, retiring
the router's duplicate profile factory (#178 item 7).
"""

from __future__ import annotations

from typing import Any

from app.services.ai.profiles.registry import capability_profile_for


def coerce_optional_temperature(raw: Any) -> float | None:
    """Parse a temperature value from assistant metadata. None / empty /
    unparseable all collapse to None so the call site omits the param.

    Shared with call-parameter resolution (#178 slice 2): "the assistant set
    a temperature" must mean the same thing when we validate a save and when
    we build the provider call, or the two would disagree.
    """
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def validate_assistant_temperature(metadata: dict[str, Any] | None) -> str | None:
    """Check that the assistant's (provider, model, temperature) combo is
    valid. Returns an error message to surface as 400, or None when OK.

    - Model requires temperature but none set → reject (no current model
      hits this; the check is here for forward-compat).
    - Model rejects temperature but one is set → reject so the user fixes
      it at save time instead of seeing a runtime 400 on first use.

    When provider or model are missing, defer to other validation — we
    only check the temperature combo when there's enough info to judge.
    """
    if not metadata:
        return None
    provider_name = metadata.get("ai_provider")
    model_id = metadata.get("ai_model")
    if not isinstance(provider_name, str) or not isinstance(model_id, str):
        return None
    if not provider_name or not model_id:
        return None
    profile = capability_profile_for(provider_name)
    if profile is None:
        return None
    has_temp = coerce_optional_temperature(metadata.get("ai_temperature")) is not None
    if profile.requires_temperature(model_id) and not has_temp:
        return (
            f"Model '{model_id}' requires a temperature setting — "
            "fill in the Temperature field."
        )
    if not profile.supports_temperature(model_id) and has_temp:
        return (
            f"Model '{model_id}' does not accept a temperature setting — "
            "clear the Temperature field."
        )
    return None
