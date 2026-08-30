"""Promote a node to an ancestor project (ADR-0078 slices 2/3, #1494/#1663).

Promotion moves an **owned** node's file up into a declared ancestor project,
keeping its front-matter `id` — every inbound reference resolves by id, so
backlinks survive untouched (ADR-0078 §1). Content travels by default; the
parts that would leak origin-local structure upward (a reference to an
origin-local node, a tag the destination does not know, ADR-0078 §4) stay
behind as a sparse layer override on the origin, through the same #314 path
(`services/project/overrides.py`) `_save_lore_override` uses.

`_partition_node_metadata` is the kind-agnostic §4 metadata partition shared
by every promotable kind. `_partition_lore_promotion` / `_partition_prompt_
promotion` layer their own owned-here/destination guards and kind-specific
extras (a prompt's §5 dynamic-reference list and §6 include cascade) on top
of it, each backing both its dry-run preview and its commit (ADR-0078 §9) —
what the author approved in the plan is exactly what runs.
"""

from __future__ import annotations

from typing import Any

from app.models import (
    LoreEntry,
    PromotionPlan,
    PromotionStayItem,
    PromotionTarget,
    PromptEntry,
)
from app.services.project.errors import ProjectServiceError
from app.services.project.node_index import IndexLayer, NodeIndex
from app.services.project.node_index_gate import node_index_gate
from app.services.project.references import INCLUDE_FIELD_ID


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
        # (§4's `base`/`submitted` merge in `promote_lore_entry`). When *every*
        # target is hidden, drop the field from the destination entirely (None)
        # rather than leave an empty list — matching the single-`entity_ref`
        # path, so a wholly-origin-local list and a wholly-origin-local ref
        # behave the same at the destination.
        travel_value = visible_ids if visible_ids else None
        return travel_value, ids, item

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

    def _partition_node_metadata(
        self, metadata: dict[str, Any], dest: IndexLayer, index: NodeIndex, root
    ) -> tuple[dict[str, Any], dict[str, Any], list[PromotionStayItem], list[str]]:
        """The kind-agnostic §4 metadata partition, shared by every promotable
        kind. Reads the origin's own field types (how the ORIGIN defines each
        field), the destination's schema (`up_to_layer_id=dest.id`, to spot a
        book-only field definition, §3/§8) and known tags (§4), then dispatches
        each field through `_partition_field`.

        Returns `(travels, stays, stay_items, invisible)` — the same four
        pieces `_partition_lore_promotion` used to compute inline; a kind's own
        partition wraps this with its owned-here/destination guards and any
        kind-specific extras (a prompt's §5/§6) and folds the result into its
        `PromotionPlan`.
        """
        origin_types = self._schema_field_types(self.read_metadata_schema())
        dest_schema = self.read_metadata_schema(up_to_layer_id=dest.id)
        dest_types = self._schema_field_types(dest_schema)
        known_at_dest = {tag.name.lower() for tag in self.read_known_tags(up_to_layer_id=dest.id).tags}

        travels: dict[str, Any] = {}
        stays: dict[str, Any] = {}
        stay_items: list[PromotionStayItem] = []
        invisible: list[str] = []

        for field, value in metadata.items():
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

        return travels, stays, stay_items, invisible

    def _promotion_guard(
        self, entry_id: str, target_layer_id: str, kind: str, noun: str
    ) -> tuple[Any, IndexLayer, NodeIndex, Any]:
        """The owned-here / declared-ancestor guard shared by every kind's
        partition (ADR-0078 §2) — the INVERSE of `fork_lore_entry`'s guard,
        which refuses when the node already lives here; promotion refuses when
        it does not (an already-inherited node has nothing local to lift).

        Returns `(entry, dest, index, root)` for the caller to continue from.
        """
        root = self._require_project()
        index = self._build_node_index()
        entry = index.by_id.get(entry_id)
        if entry is None or entry.kind != kind:
            raise ProjectServiceError(f"{noun} {entry_id} not found.", 404)

        open_layer_id = self._metadata_schema_layer_id(root)
        if entry.source_layer_id != open_layer_id:
            raise ProjectServiceError(
                f"{noun} {entry_id} is inherited, not owned here; promote it from the "
                "project that owns it.",
                409,
            )

        dest = self.layer_by_id(root, target_layer_id)
        valid_destinations = set(self._project_layer_folders(root)[:-1])
        if dest is None or dest.folder not in valid_destinations:
            raise ProjectServiceError("Not a declared ancestor project.", 400)

        return entry, dest, index, root

    def _partition_lore_promotion(
        self, entry_id: str, target_layer_id: str
    ) -> tuple[LoreEntry, IndexLayer, dict[str, Any], dict[str, Any], PromotionPlan]:
        """The one partition backing both preview and commit (ADR-0078 §9).

        Returns `(full, dest, travels_metadata, stays_metadata, plan)`. Writes
        nothing — a pure read over the current index and schema.
        """
        _entry, dest, index, root = self._promotion_guard(entry_id, target_layer_id, "lore", "Lore Entry")

        # An owned node folds to its own authored values — no override to fold.
        full = self.read_lore_entry(entry_id)
        travels, stays, stay_items, invisible = self._partition_node_metadata(full.metadata, dest, index, root)

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

    # --- prompt promotion (ADR-0078 slice 3, #1663) --------------------------

    def _prompt_include_closure(self, index: NodeIndex, prompt_id: str) -> set[str]:
        """The transitive forward closure of `prompt_id`'s literal
        `{% include %}`s (ADR-0078 §6) — the hard dependencies that must be
        satisfiable at the destination. Mirrors the reverse helper
        `prompts_including_snippet` (references.py:1328) but walks
        `edges_by_src` forward from the prompt being promoted; the `closure`
        set doubles as the cycle guard, same as that helper's `seen`. Only
        `@include` edges count — a prompt's own `entity_ref` edges (if any)
        are not a hard dependency (§4 handles those)."""
        closure: set[str] = set()
        frontier = [prompt_id]
        while frontier:
            current = frontier.pop()
            for edge in index.edges_by_src.get(current, []):
                if edge.field_id != INCLUDE_FIELD_ID or edge.dst in closure:
                    continue
                closure.add(edge.dst)
                frontier.append(edge.dst)
        return closure

    def _prompt_dynamic_include_reason(
        self, full: PromptEntry, closure_ids: list[str], index: NodeIndex
    ) -> str | None:
        """§6 ★: a dynamically-named `{% include %}` anywhere in the prompt or
        its static closure means the closure computed above is incomplete —
        literal-only discovery (`literal_include_names`) cannot see it, and an
        unresolved dynamic include would raise under `StrictUndefined` at the
        destination. The prompt itself is checked FIRST: a dynamic include
        there means the closure it seeded is not trustworthy at all, so there
        is no point classifying members computed from it."""
        from app.services.ai.effective_inputs import has_dynamic_include
        from app.services.ai.templates import create_environment

        env = create_environment()
        if has_dynamic_include(full.body, env):
            return (
                f"{full.title} has a dynamically-named {{% include %}} the promotion can't follow; "
                "make it a literal include first"
            )
        for member_id in closure_ids:
            candidate = index.by_id.get(member_id)
            if candidate is None:
                continue
            try:
                _, body = self._read_markdown_with_front_matter(candidate.path)
            except (OSError, ProjectServiceError):
                continue
            if has_dynamic_include(body, env):
                return (
                    f"{candidate.title} has a dynamically-named {{% include %}} the promotion can't "
                    "follow; make it a literal include first"
                )
        return None

    def _partition_prompt_promotion(
        self, entry_id: str, target_layer_id: str
    ) -> tuple[PromptEntry, IndexLayer, dict[str, Any], dict[str, Any], list[str], PromotionPlan]:
        """The one partition backing both prompt preview and commit (ADR-0078
        §9), layering §5's dynamic-reference list and §6's include cascade /
        dynamic-include refusal on top of the shared §4 metadata partition.

        Returns `(full, dest, travels_metadata, stays_metadata, to_promote,
        plan)` — `to_promote` is the cascaded closure members' ids (id order,
        empty when nothing needs to cascade or the plan is blocked). Writes
        nothing.
        """
        _entry, dest, index, root = self._promotion_guard(entry_id, target_layer_id, "prompt", "Prompt")

        full = self.read_prompt_entry(entry_id)
        travels_metadata, stays_metadata, stay_items, invisible = self._partition_node_metadata(
            full.metadata, dest, index, root
        )
        resolves_differently = [i.name for i in full.inputs if i.type in ("context_pick", "scene_ref")]

        open_layer_id = self._metadata_schema_layer_id(root)
        closure_ids = sorted(self._prompt_include_closure(index, entry_id))
        to_promote: list[str] = []
        blocked_reason = self._prompt_dynamic_include_reason(full, closure_ids, index)
        if blocked_reason is None:
            for member_id in closure_ids:
                if self._target_visible_from_destination(index, root, member_id, dest.rank):
                    continue  # already inherited at/above the destination
                candidate = index.by_id.get(member_id)
                if candidate is None:
                    continue
                if candidate.source_layer_id == open_layer_id:
                    to_promote.append(member_id)
                    continue
                member_layer = self.layer_by_id(root, candidate.source_layer_id)
                layer_label = member_layer.label if member_layer is not None else candidate.source_layer_id
                blocked_reason = f"{candidate.title} is owned by {layer_label} and can't be lifted from here"
                break

        plan = PromotionPlan(
            destination=PromotionTarget(layer_id=dest.id, label=dest.label),
            travels=sorted(travels_metadata),
            stays_in_origin=stay_items,
            invisible_at_destination=sorted(invisible),
            also_promoted=[index.by_id[member_id].title for member_id in to_promote],
            resolves_differently=resolves_differently,
            blocked_reason=blocked_reason,
        )
        return full, dest, travels_metadata, stays_metadata, to_promote, plan

    def preview_prompt_promotion(self, entry_id: str, target_layer_id: str) -> PromotionPlan:
        """The dry-run promotion plan (ADR-0078 §9), including the §6 cascade
        and any §6 ★ dynamic-include refusal. Writes nothing."""
        _full, _dest, _travels, _stays, _to_promote, plan = self._partition_prompt_promotion(
            entry_id, target_layer_id
        )
        return plan

    def _write_promoted_prompt(self, entry_id: str, dest: IndexLayer, root) -> None:
        """Move one owned prompt node's file into `dest.folder` (ADR-0078 §1),
        mirroring `promote_lore_entry`'s single-node write/delete/override
        order. Shared by the cascaded closure members and the promoted prompt
        itself (`promote_prompt_entry`), each partitioned fresh against the
        index as it stands after any prior member in the same commit already
        moved — so a member that itself references an earlier-cascaded member
        sees it as already at the destination."""
        index = self._build_node_index()
        full = self.read_prompt_entry(entry_id)
        travels_metadata, stays_metadata, _stay_items, _invisible = self._partition_node_metadata(
            full.metadata, dest, index, root
        )
        self._write_node_entry_file(
            self._filepath_for_new_node(dest.folder / "prompts", full.title),
            full.id,
            full.title,
            full.entry_type,
            travels_metadata,
            full.body,
            extra=self._prompt_front_matter_extra(full.inputs, full.offer_on, full.context_strategy),
            omit_empty_metadata=True,
        )
        self._delete_node_file(self._path_for_node_id(entry_id, "prompt"))
        # See `promote_lore_entry`: force a cold rebuild so the next read (the
        # next cascade member, or the final `read_prompt_entry`) already
        # resolves this id as inherited from `dest`.
        node_index_gate.invalidate()

        if stays_metadata:
            rows = self._diff_metadata_to_override_rows(
                base=travels_metadata,
                submitted={**travels_metadata, **stays_metadata},
                field_types=self._schema_field_types(self.read_metadata_schema()),
            )
            self._write_override_file(root, entry_id, full.title, rows)
            node_index_gate.invalidate()

    def promote_prompt_entry(self, entry_id: str, target_layer_id: str) -> PromptEntry:
        """Commit the promotion computed by `_partition_prompt_promotion`
        (ADR-0078 §6/§9): a blocked plan (an un-followable dynamic include, or
        a closure member owned by an intermediate ancestor) raises rather than
        promoting anything; otherwise every cascaded closure member is moved
        first, then the prompt itself. Order among the cascaded members
        doesn't matter — nothing renders mid-transaction, and the end state is
        everything at the destination regardless of the order they moved in.
        """
        _full, dest, _travels, _stays, to_promote, plan = self._partition_prompt_promotion(
            entry_id, target_layer_id
        )
        if plan.blocked_reason is not None:
            raise ProjectServiceError(plan.blocked_reason, 422)

        root = self._require_project()
        for member_id in to_promote:
            self._write_promoted_prompt(member_id, dest, root)
        self._write_promoted_prompt(entry_id, dest, root)
        return self.read_prompt_entry(entry_id)
