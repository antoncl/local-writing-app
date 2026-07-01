"""Mid-scene lore mutations slice of ProjectService (GH #33, #50).

A mutation is a self-contained HTML-comment marker living inline in scene
markdown, carrying the new value at the point of change:

    <!-- mutate:entity=<lore-id>;field=<field-key>;value=<url-encoded>;id=<marker-id> -->

Unlike embedded todos this marker wraps **no prose** — it is a point marker
whose position within the scene body is semantically load-bearing (prose before
it sees the old value, prose after it the new; ADR-0003). The scene is
authoritative and the marker travels with the prose, so moving/deleting a scene
moves/deletes its mutations with it — no orphan management (ADR-0001).

This mixin owns the marker pattern, the per-scene scan, and the intentful
single-marker mutators (rewrite/remove without a full body save). The
project-wide index and the effective-state resolver that read these markers
live in a separate slice (#51). `ProjectService` composes it; shared helpers
(`read_scene`, `_path_for_node_id`, `_write_scene_file`) resolve via MRO.

`MUTATION_MARKER_PATTERN` lives here (its single home, alongside the code that
rewrites markers with it), mirroring `EMBEDDED_TODO_PATTERN`.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from dataclasses import dataclass
from dataclasses import field as dc_field
from urllib.parse import quote, unquote

from app.models import (
    MutationMarker,
    Scene,
    UpdateMutationRequest,
)
from app.services.project.errors import ProjectServiceError

MUTATION_MARKER_PATTERN = re.compile(
    r"<!--\s*mutate:entity=([A-Za-z0-9_-]+);field=([A-Za-z0-9_.-]+);"
    r"value=([^;\s]*);id=([A-Za-z0-9_-]+)\s*-->",
)

# Sentinel position: resolve at end of scene (every in-scene marker counts as
# live). Only `replace_selection` passes a real cursor offset; every other
# surface resolves at end-of-scene (ADR-0003).
END_OF_SCENE: int | None = None


@dataclass
class MutationsIndex:
    """Project-wide mutation index (#51). Rebuildable from scene files; each
    entity's list is pre-ordered by manuscript position then prose offset, so
    the resolver slices O(applicable) rather than re-scanning. `version` changes
    whenever any marker changes, letting the AI cache layer key volatile lore on
    it instead of the (now-insufficient) lore file revision (ADR-0006)."""

    version: str = ""
    by_entity: dict[str, list[MutationMarker]] = dc_field(default_factory=dict)
    scene_order: dict[str, int] = dc_field(default_factory=dict)


class LoreMutationsMixin:
    def _scan_scene_mutations(self, scene: Scene) -> Iterator[MutationMarker]:
        """Yield every mutation marker in one scene body, in prose order,
        carrying each marker's char offset (needed for position-granular
        resolution). The single per-scene scan the index (#51) walks."""
        body = scene.body
        for match in MUTATION_MARKER_PATTERN.finditer(body):
            yield MutationMarker(
                marker_id=match.group(4),
                entity_id=match.group(1),
                field=match.group(2),
                value=unquote(match.group(3)),
                scene_id=scene.id,
                offset=match.start(),
                line=body[: match.start()].count("\n") + 1,
            )

    # ----- index + resolver (#51) ----------------------------------------

    def _scene_order(self) -> dict[str, int]:
        """Map each scene id to its manuscript position (depth-first document
        order: act → chapter → scene). Scenes not linked into the manuscript
        tree have no manuscript position and are absent."""
        try:
            structure = self.read_structure()
        except ProjectServiceError:
            return {}
        order: dict[str, int] = {}

        def walk(node: Scene) -> None:
            scene_id = getattr(node, "scene_id", None)
            if scene_id and scene_id not in order:
                order[scene_id] = len(order)
            for child in getattr(node, "children", None) or []:
                walk(child)

        walk(structure.root)
        return order

    def build_mutations_index(self) -> MutationsIndex:
        """Walk every manuscript scene in order, scanning its markers into a
        per-entity list ordered by (manuscript position, prose offset).
        Rebuildable cache over scene files — mirrors `_build_node_index`
        (compute-on-demand); persist to `.cache/` only if it ever gets slow
        (§3.3)."""
        scene_order = self._scene_order()
        scene_paths = self._scene_display_paths()
        by_entity: dict[str, list[MutationMarker]] = {}
        for scene_id in scene_order:
            try:
                scene = self.read_scene(scene_id)
            except ProjectServiceError:
                continue
            for marker in self._scan_scene_mutations(scene):
                marker.scene_path = scene_paths.get(scene_id, marker.scene_path)
                by_entity.setdefault(marker.entity_id, []).append(marker)
        for records in by_entity.values():
            records.sort(key=lambda m: (scene_order.get(m.scene_id, 0), m.offset))
        return MutationsIndex(
            version=self._mutations_version(by_entity),
            by_entity=by_entity,
            scene_order=scene_order,
        )

    def effective_state(
        self,
        entity_id: str,
        scene_id: str,
        position: int | None = END_OF_SCENE,
        index: MutationsIndex | None = None,
    ) -> dict[str, str]:
        """Effective mutation overrides for `entity_id` as of (scene, position).

        Returns only the fields carrying a **live** mutation, each mapped to its
        winning value; the caller overlays these onto the entry's base field
        values (ADR-0003, ADR-0006). v1.0 is replace-only, open-ended: among the
        records live at (scene, position), the latest-started per field wins.

        A record is live iff its start is at or before the resolution point in
        manuscript order — earlier scene always, same scene only if its marker
        sits at/before `position` (so prose before a marker sees the old value,
        prose after it the new). `position=END_OF_SCENE` counts every in-scene
        marker as live. Pass a prebuilt `index` to resolve many entries without
        re-scanning."""
        idx = index or self.build_mutations_index()
        records = idx.by_entity.get(entity_id)
        if not records:
            return {}
        target_pos = idx.scene_order.get(scene_id)
        if target_pos is None:
            # Scene not in the manuscript → no manuscript position → base only.
            return {}
        effective: dict[str, str] = {}
        for marker in records:  # pre-sorted ascending, so the last live wins
            if self._marker_is_live(marker, idx.scene_order, target_pos, position):
                effective[marker.field] = marker.value
        return effective

    def _marker_is_live(
        self,
        marker: MutationMarker,
        scene_order: dict[str, int],
        target_pos: int,
        position: int | None,
    ) -> bool:
        marker_pos = scene_order.get(marker.scene_id)
        if marker_pos is None or marker_pos > target_pos:
            return False
        if marker_pos < target_pos:
            return True
        return position is END_OF_SCENE or marker.offset <= position

    def _mutations_version(self, by_entity: dict[str, list[MutationMarker]]) -> str:
        digest = hashlib.sha1()  # noqa: S324 - cache key, not security
        for entity_id in sorted(by_entity):
            for marker in by_entity[entity_id]:
                digest.update(
                    f"{entity_id}\x1f{marker.scene_id}\x1f{marker.offset}"
                    f"\x1f{marker.field}\x1f{marker.value}\x1f{marker.marker_id}\x1e".encode()
                )
        return digest.hexdigest()[:16]

    # ----- intentful single-marker mutators (#50) ------------------------

    def update_mutation(
        self, scene_id: str, marker_id: str, request: UpdateMutationRequest
    ) -> Scene:
        """Rewrite a single mutation marker's entity/field/value in place, without
        a full body save. Returns the updated scene so an open editor pane can
        reconcile."""
        scene = self.read_scene(scene_id)
        new_body, found = self._rewrite_mutation(scene.body, marker_id, request)
        if not found:
            raise ProjectServiceError(
                f"Mutation {marker_id} does not exist in scene {scene.id}.", 404
            )
        path = self._path_for_node_id(scene.id, "scene")
        self._write_scene_file(path, scene.model_copy(update={"body": new_body}))
        return self.read_scene(scene.id)

    def delete_mutation(self, scene_id: str, marker_id: str) -> Scene:
        """Remove a single mutation marker. The marker wraps no prose, so removal
        just drops the comment. Returns the updated scene."""
        scene = self.read_scene(scene_id)
        found = False

        def replace(match: re.Match[str]) -> str:
            nonlocal found
            if match.group(4) != marker_id:
                return match.group(0)
            found = True
            return ""

        new_body = MUTATION_MARKER_PATTERN.sub(replace, scene.body)
        if not found:
            raise ProjectServiceError(
                f"Mutation {marker_id} does not exist in scene {scene.id}.", 404
            )
        path = self._path_for_node_id(scene.id, "scene")
        self._write_scene_file(path, scene.model_copy(update={"body": new_body}))
        return self.read_scene(scene.id)

    def _rewrite_mutation(
        self, body: str, marker_id: str, request: UpdateMutationRequest
    ) -> tuple[str, bool]:
        found = False

        def replace(match: re.Match[str]) -> str:
            nonlocal found
            if match.group(4) != marker_id:
                return match.group(0)
            found = True
            entity = request.entity_id or match.group(1)
            field = request.field or match.group(2)
            # Re-encode only when a new value is supplied; otherwise keep the
            # existing encoded value verbatim to avoid gratuitous diffs.
            value = quote(request.value, safe="") if request.value is not None else match.group(3)
            return f"<!-- mutate:entity={entity};field={field};value={value};id={marker_id} -->"

        return MUTATION_MARKER_PATTERN.sub(replace, body), found
