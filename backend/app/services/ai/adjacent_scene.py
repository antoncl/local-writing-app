"""`previous_scene(x)` / `next_scene(x)` — the scene beside a scene or a plot card
in manuscript reading order (#2355).

Split out of `helpers.py` (which is near the file-size guard); the Jinja globals
are registered there. Reading order is the plot board's leaf-scene rank — the
exact order `plot_context`'s reveal gate uses, so `plot_context(as_of=next_scene(e))`
reveals precisely one scene more — and it crosses chapter and act boundaries.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.services.ai.entry_ref import EntryRef

if TYPE_CHECKING:
    from app.services.project_service import ProjectService

# A plot card names the scene it is attached to in this field (ADR-0048 §1).
_CARD_SCENE_FIELD = "scene"


def adjacent_scene(
    project: ProjectService, schema: Any, ref: EntryRef | None, step: int
) -> EntryRef | None:
    """The scene `step` places from `ref` in reading order, or None.

    `ref` is a scene or a plot card; a card stands for the scene it is attached
    to. None at either end of the manuscript, for a card attached to no scene,
    and for anything that is neither — so a template can fall back with `or`:
    `plot_context(as_of=next_scene(e) or e.id)`.
    """
    if ref is None:
        return None
    try:
        _containers, _scene_to_container, scene_to_order = project._board_container_map()
    except Exception:  # noqa: BLE001 — a missing/malformed tree must not 500 a render
        return None
    order = sorted(scene_to_order, key=scene_to_order.__getitem__)
    scene_id = ref.id if ref.id in order else _card_scene_id(ref)
    if scene_id not in order:
        return None
    position = order.index(scene_id) + step
    if not 0 <= position < len(order):
        return None
    return EntryRef(project, schema, order[position])


def _card_scene_id(ref: EntryRef) -> str | None:
    """The id of the scene a plot card is attached to, or None. The metadata
    view wraps an `entity_ref` value as an EntryRef, so read its id back."""
    value = ref.metadata.get(_CARD_SCENE_FIELD)
    value = getattr(value, "id", value)
    return value if isinstance(value, str) and value else None
