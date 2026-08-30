"""Promote a lore entry to an ancestor project (ADR-0078 slice 2, #1494).

Promotion moves an **owned** node's file up into a declared ancestor project,
keeping its front-matter `id` — every inbound reference resolves by id, so
backlinks survive untouched (ADR-0078 §1). Content travels by default; the
parts that would leak origin-local structure upward (a reference to an
origin-local node, a tag the destination does not know, ADR-0078 §4) stay
behind as a sparse layer override on the origin, through the same #314 path
(`services/project/overrides.py`) `_save_lore_override` uses.

`_partition_lore_promotion` is the single partition both the dry-run preview
and the commit share (ADR-0078 §9) — what the author approved in the plan is
exactly what runs.
"""

from __future__ import annotations

from typing import Any

from app.models import LoreEntry, PromotionPlan, PromotionStayItem, PromotionTarget
from app.services.project.errors import ProjectServiceError
from app.services.project.node_index import IndexLayer, NodeIndex
from app.services.project.node_index_gate import node_index_gate


class PromotionMixin:
    def promotion_targets(self) -> list[PromotionTarget]:
        """The declared ancestor projects a node here may be promoted into —
        `_project_layer_folders` minus the trailing open project (ADR-0078 §2)."""
        root = self._require_project()
        folders = self._project_layer_folders(root)[:-1]
        targets: list[PromotionTarget] = []
        for folder in folders:
            layer = self.layer_by_id(root, self._metadata_schema_layer_id(folder))
            if layer is not None:
                targets.append(PromotionTarget(layer_id=layer.id, label=layer.label))
        return targets

    def _target_visible_from_destination(
        self, index: NodeIndex, root, target_id: str, dest_rank: int
    ) -> bool:
        """Whether some copy of `target_id` would still resolve once resolution
        starts at a layer of rank `dest_rank` (ADR-0078 §4 / "to verify" note).

        Rank is **ascending**: the Library/machine floor is low, and the open
        project — the most local layer — is the *highest* rank. A destination
        is an ancestor, so it has a LOWER rank than the origin. A candidate is
        reachable from that destination iff it lives at the destination itself
        or further OUT (an even lower rank, i.e. `<= dest_rank`) — a candidate
        at a HIGHER rank than the destination is more local than the
        destination and would not be seen once resolution starts there. Get
        this backwards and every partition silently inverts.
        """
        for candidate in index.candidates.get(target_id, []):
            layer = self.layer_by_id(root, candidate.source_layer_id)
            if layer is not None and layer.rank <= dest_rank:
                return True
        return False

    # --- per-field-type partition (ADR-0078 §3/§4) --------------------------
    #
    # Each returns `(travel_value, stay_value, stay_item)`: `travel_value` is
    # `None` when nothing of the field travels (omit the key from `travels`
    # entirely — an entity_ref that stays wholly behind); `stay_value`, when
    # not `None`, is the value the origin should still see for the field —
    # the FULL original value for a collection, since the override diff
    # (`promote_lore_entry`) needs `submitted` to carry the whole thing back,
    # not just the part that stayed.

    def _partition_entity_ref(
        self, index: NodeIndex, root, dest: IndexLayer, field: str, value: Any
    ) -> tuple[Any, Any, PromotionStayItem | None]:
        target = value if isinstance(value, str) else ""
        if not target or self._target_visible_from_destination(index, root, target, dest.rank):
            return value, None, None
        target_entry = index.by_id.get(target)
        title = target_entry.title if target_entry is not None else target
        item = PromotionStayItem(field=field, reason=f"points at {title}, which is not visible at {dest.label}")
        return None, value, item

    def _partition_entity_ref_list(
        self, index: NodeIndex, root, dest: IndexLayer, field: str, value: Any
    ) -> tuple[Any, Any, PromotionStayItem | None]:
        ids = [i for i in value if isinstance(i, str) and i] if isinstance(value, list) else []
        visible_ids = [i for i in ids if self._target_visible_from_destination(index, root, i, dest.rank)]
        hidden_ids = [i for i in ids if i not in visible_ids]
        if not hidden_ids:
            return visible_ids, None, None
        names = ", ".join(index.by_id[i].title if i in index.by_id else i for i in hidden_ids)
        item = PromotionStayItem(field=field, reason=f"references {names}, not visible at {dest.label}")
        # The full original list re-appears at the origin via the override
        # (§4's `base`/`submitted` merge in `promote_lore_entry`).
        return visible_ids, ids, item

    def _partition_tags(
        self, dest: IndexLayer, known_at_dest: set[str], field: str, value: Any
    ) -> tuple[Any, Any, PromotionStayItem | None]:
        tag_list = [t for t in value if isinstance(t, str) and t] if isinstance(value, list) else []
        travel_tags = [t for t in tag_list if t.lower() in known_at_dest]
        unknown_tags = [t for t in tag_list if t.lower() not in known_at_dest]
        if not unknown_tags:
            return travel_tags, None, None
        item = PromotionStayItem(field=field, reason=f"tagged {', '.join(unknown_tags)}, not known at {dest.label}")
        return travel_tags, tag_list, item

    def _partition_field(
        self,
        index: NodeIndex,
        root,
        dest: IndexLayer,
        known_at_dest: set[str],
        field_type: str,
        field: str,
        value: Any,
    ) -> tuple[Any, Any, PromotionStayItem | None]:
        """One field's `(travel_value, stay_value, stay_item)` — dispatched by
        declared type (ADR-0078 §3/§4). Any type not named here travels whole."""
        if field_type == "entity_ref":
            return self._partition_entity_ref(index, root, dest, field, value)
        if field_type == "entity_ref_list":
            return self._partition_entity_ref_list(index, root, dest, field, value)
        if field_type == "tags":
            return self._partition_tags(dest, known_at_dest, field, value)
        return value, None, None

    def _partition_lore_promotion(
        self, entry_id: str, target_layer_id: str
    ) -> tuple[LoreEntry, IndexLayer, dict[str, Any], dict[str, Any], PromotionPlan]:
        """The one partition backing both preview and commit (ADR-0078 §9).

        Returns `(full, dest, travels_metadata, stays_metadata, plan)`. Writes
        nothing — a pure read over the current index and schema.
        """
        root = self._require_project()
        index = self._build_node_index()
        entry = index.by_id.get(entry_id)
        if entry is None or entry.kind != "lore":
            raise ProjectServiceError(f"Lore Entry {entry_id} not found.", 404)

        # Owned-here only — the INVERSE of `fork_lore_entry`'s guard, which
        # refuses when the node already lives here. Promotion refuses when it
        # does not (ADR-0078 §2): an already-inherited node has nothing local
        # to lift.
        open_layer_id = self._metadata_schema_layer_id(root)
        if entry.source_layer_id != open_layer_id:
            raise ProjectServiceError(
                f"Lore Entry {entry_id} is inherited, not owned here; promote it from the "
                "project that owns it.",
                409,
            )

        dest = self.layer_by_id(root, target_layer_id)
        valid_destinations = set(self._project_layer_folders(root)[:-1])
        if dest is None or dest.folder not in valid_destinations:
            raise ProjectServiceError("Not a declared ancestor project.", 400)

        # An owned node folds to its own authored values — no override to fold.
        full = self.read_lore_entry(entry_id)
        origin_types = self._schema_field_types(self.read_metadata_schema())
        dest_schema = self.read_metadata_schema(up_to_layer_id=target_layer_id)
        dest_types = self._schema_field_types(dest_schema)
        known_at_dest = {tag.name.lower() for tag in self.read_known_tags(up_to_layer_id=target_layer_id).tags}

        travels: dict[str, Any] = {}
        stays: dict[str, Any] = {}
        stay_items: list[PromotionStayItem] = []
        invisible: list[str] = []

        for field, value in full.metadata.items():
            field_type = origin_types.get(field, "text")
            travel_value, stay_value, item = self._partition_field(
                index, root, dest, known_at_dest, field_type, field, value
            )
            if travel_value is not None:
                travels[field] = travel_value
            if stay_value is not None:
                stays[field] = stay_value
            if item is not None:
                stay_items.append(item)
            if field not in dest_types:
                # Book-only field definition (ADR-0078 §3/§8): still travels on
                # the file, just invisible at the destination until the
                # definition itself is promoted.
                invisible.append(field)

        plan = PromotionPlan(
            destination=PromotionTarget(layer_id=dest.id, label=dest.label),
            travels=sorted(travels),
            stays_in_origin=stay_items,
            invisible_at_destination=sorted(invisible),
        )
        return full, dest, travels, stays, plan

    def preview_lore_promotion(self, entry_id: str, target_layer_id: str) -> PromotionPlan:
        """The dry-run promotion plan (ADR-0078 §9). Writes nothing."""
        _full, _dest, _travels, _stays, plan = self._partition_lore_promotion(entry_id, target_layer_id)
        return plan

    def promote_lore_entry(self, entry_id: str, target_layer_id: str) -> LoreEntry:
        """Commit the promotion computed by `_partition_lore_promotion`.

        Order is load-bearing (ADR-0078 §10): write the destination file, then
        delete the origin's, THEN invalidate the index so `entry_id` resolves
        as inherited — only then is it safe to write the stay-behind override,
        because `read_lore_entry`'s fold applies only to an inherited winner.
        Writing the override first would silently drop it.
        """
        root = self._require_project()
        full, dest, travels_metadata, stays_metadata, _plan = self._partition_lore_promotion(
            entry_id, target_layer_id
        )

        promoted = LoreEntry(
            id=full.id,
            title=full.title,
            body=full.body,
            revision="",
            entry_type=full.entry_type,
            metadata=travels_metadata,
            forked_from=None,
        )
        self._write_lore_entry_file(self._filepath_for_new_node(dest.folder / "lore", full.title), promoted)
        self._delete_node_file(self._path_for_node_id(entry_id, "lore"))
        # The write funnel patches the memo incrementally per call; a promotion
        # spans two layers in one gesture, which the incremental patch was
        # never built to model. Force a cold rebuild rather than trust it, so
        # the very next read already resolves `entry_id` as inherited from
        # `dest` — the precondition the override write below depends on.
        node_index_gate.invalidate()

        if stays_metadata:
            rows = self._diff_metadata_to_override_rows(
                base=travels_metadata,
                submitted={**travels_metadata, **stays_metadata},
                field_types=self._schema_field_types(self.read_metadata_schema()),
            )
            self._write_override_file(root, entry_id, full.title, rows)
            # `_write_override_file` writes under `<root>/overrides/`, which
            # `_maintain_index_after_write` already routes to a full
            # `node_index_gate.invalidate()` (an override fans out like a
            # schema edit) — this second call is a harmless no-op belt-and-
            # braces, kept explicit so the ordering here does not depend on
            # reading that unrelated module's internals to trust.
            node_index_gate.invalidate()

        return self.read_lore_entry(entry_id)
