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

import re
from collections.abc import Iterator
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
