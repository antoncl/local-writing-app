"""Shared test helper (ADR-0095 §12/S1): move a legacy-grammar scene body into
sets + anchors, the way the migration will. Existing tests keep authoring
mutation markers in the old inline grammar — it stays the readable shorthand
for "this scene has these changes at these points" — but the mutations index
no longer reads that grammar (ADR-0095 §5), so every fixture must go through
`convert_legacy_mutations` before it can resolve.

`save_scenes_with_mutations` is the ONE place that conversion happens. A test:

    self.s2 = self._new_scene("Scene Two", "")  # create the scene, no body yet
    ids = save_scenes_with_mutations(self.service, {
        self.s2: f"Before. <!-- mutate:entity={self.honor};field=rank;value=Captain;id=m1 --> After.",
    })

writes the converted `mutation_set` node(s) through the unvalidated writer
(`_write_converted_mutation_set` — the same one the migration will use, §12)
and the converted scene bodies through the ordinary `save_scene`, then returns
`unit_id -> (set_id, anchor_id)` for tests that need to address a specific
record or write a close anchor of their own.
"""

from __future__ import annotations

from app.models import SaveSceneRequest
from app.services.project.legacy_mutation_markers import convert_legacy_mutations
from app.services.project_service import ProjectService


def save_scenes_with_mutations(
    service: ProjectService,
    bodies: dict[str, str] | list[tuple[str, str]],
) -> dict[str, tuple[str, str]]:
    """Convert and save every scene in `bodies` (legacy-grammar bodies, keyed
    or ordered by scene id — both already CREATED, e.g. via `create_scene`).

    Manuscript order: a `list[(scene_id, body)]` is taken in the order given;
    a `dict` is ordered by the service's own manuscript tree position
    (`_scene_order`), falling back to dict insertion order for any scene not
    in the tree (a fixture that leaves a scene unlinked on purpose).

    Returns `unit_id -> (set_id, anchor_id)` — the legacy marker/unit id each
    converted record came from, for tests that need to name a specific
    record or write their own close anchor against it.
    """
    ordered_ids = _manuscript_order(service, bodies)
    scenes = [(scene_id, bodies[scene_id] if isinstance(bodies, dict) else dict(bodies)[scene_id]) for scene_id in ordered_ids]
    index = service._build_node_index()

    def entity_type(entity_id: str) -> str | None:
        entry = index.by_id.get(entity_id)
        return entry.entry_type if entry is not None and entry.kind == "lore" else None

    result = convert_legacy_mutations(scenes, entity_type)
    for converted in result.sets:
        service._write_converted_mutation_set(converted)
    for scene_id, original_body in scenes:
        new_body = result.bodies.get(scene_id, original_body)
        current = service.read_scene(scene_id)
        service.save_scene(
            scene_id,
            SaveSceneRequest(
                title=current.title,
                body=new_body,
                status=current.status,
                entry_type=current.entry_type,
                metadata=current.metadata,
            ),
        )
    return {
        converted.unit_id: (converted.set_id, converted.anchor_id) for converted in result.sets
    }


def _manuscript_order(
    service: ProjectService, bodies: dict[str, str] | list[tuple[str, str]]
) -> list[str]:
    if isinstance(bodies, list):
        return [scene_id for scene_id, _ in bodies]
    order = service._scene_order()
    ordered = sorted(bodies, key=lambda sid: order.get(sid, len(order)))
    return ordered
