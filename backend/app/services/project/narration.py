"""Narration-specific reads over the generic cascade fold (ADR-0079).

`_CascadeResolver` (computed_metadata.py) folds `cascade_fields` down the
manuscript structure generically and disclaims narration semantics. The one
narration-specific rule — a `third_omniscient` / `third_objective` scene has no
viewpoint character, so `pov` is not consulted — lives here, a pure function
applied ONCE for every consumer (the AI template path today; any read that wants
effective POV later). Dict in, dict out: no service dependency, so it imports
cleanly from both the project and AI layers.
"""

from __future__ import annotations

from typing import Any

# pov_mode values that carry no viewpoint character (default_schema.py roster).
_NO_CHARACTER_MODES = frozenset({"third_omniscient", "third_objective"})


def resolved_narration(resolved_cascade: dict[str, Any] | None) -> dict[str, Any]:
    """A scene's effective narration from its `resolved_cascade` (ADR-0079):
    `{"mode": <pov_mode value | None>, "character": <pov character id | None>}`.

    Applies the mode-gates-character rule once: an omniscient / objective mode has
    no viewpoint character, so `character` is None regardless of what the cascade
    resolved for `pov`. `mode` / `character` are None when unset all the way to the
    book default."""
    cascade = resolved_cascade or {}
    mode = (cascade.get("pov_mode") or {}).get("value")
    character = (cascade.get("pov") or {}).get("value")
    if mode in _NO_CHARACTER_MODES:
        character = None
    return {"mode": mode, "character": character}
