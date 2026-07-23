"""Building a snapshot's witness (ADR-0043, #439 slice 3).

A witness is the scene's **immediate context** — the entities whose state the
prose depends on — recorded at capture, never restored, and compared later so the
app can tell the author what has changed underneath an old version.
`docs/design/snapshots-and-the-witness.md` carries the reasoning; §1 is the
definition this module implements.

**Three sources, unioned:**

1. **Mutations** — `{e : effective_state(e, scene) != {}}`. Defined by
   *resolution*, not by syntax, which is what makes it cover intervals opened in
   an earlier scene. The narrower "markers in this scene's body" is refuted by
   ADR-0043's own motivating example: a scene inside an open interval carries no
   markers at all, yet what the world *is* there is decided entirely by its
   neighbours, and a body-markers witness for it would be empty.
2. **`entity_ref`s** — the scene's own explicit references, off the edges the
   node index already carries.
3. **The dynamic context** — supplied by the caller, because the frontend owns
   the alias matcher (§4). Nothing here rescans prose.

**No transitive expansion.** `_textual_one_hop` is prompt-assembly machinery; a
witness that followed references out of the entities it found would stop being a
record of this scene's context and become a record of the project.

**One builder, both sides.** `build_witness` is called at capture *and* at
comparison. Slice 2's single largest defect class was reading the snapshot side
raw while the live side had been through `read_scene`, which flipped fields on
scenes nobody had touched; the fix is structural, not a normalisation step.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.models import Witness, WitnessEntity, WitnessFieldType
from app.services.project.errors import ProjectServiceError
from app.services.project.lore_mutations import MutationsIndex

# The structural cost bound the drift path needs (#409's lesson: an unbounded
# cost on the synchronous route is a hung pane with nothing on screen explaining
# why). A witness stops at this many entities and says so — `truncated` is
# reported rather than hidden, because a silently truncated witness reads as
# "nothing else changed", which is the one claim it cannot make.
#
# 200 is far above any plausible scene: the measured sweep is 0.7 ms at 150
# entities, flat at every manuscript size (#440 / PR #443), so this bounds the
# pathological case rather than the normal one.
MAX_WITNESS_ENTITIES = 200

# The dynamic set is a client payload, so it is capped at the boundary rather
# than trusted. Typical is 2–3 ids.
MAX_DYNAMIC_CONTEXT_IDS = 200

# Never recorded in `state`: unbounded, and a body edit still reports at the
# floor through `revision`. The witness stores what a report can *name*.
UNWITNESSED_FIELDS = frozenset({"body"})

# Membership provenance, in the order sources are unioned. Ordering is fixed so
# a witness rebuilt from the same world is byte-identical.
SOURCE_MUTATION = "mutation"
SOURCE_ENTITY_REF = "entity_ref"
SOURCE_DYNAMIC = "dynamic"


@dataclass(frozen=True)
class _WitnessScope:
    """Everything one witness build resolves against, gathered once.

    A parameter object rather than eight arguments threaded through three
    methods: the contents are read-only for the duration of the build, and every
    one of them is a shared traversal that must not be re-derived per entity —
    which is exactly the thing a long parameter list stops making obvious.
    """

    scene_id: str
    node_index: Any
    mutations: MutationsIndex
    field_types: dict[str, str]
    labels: dict[str, str]
    options: dict[str, list[str]]


class SnapshotWitnessMixin:
    """Composed onto `ProjectService`. Reaches `_build_node_index`,
    `build_mutations_index`, `effective_state`, `_mutation_field_types`,
    `read_metadata_schema`, `_read_front_matter_only`, `_normalise_metadata` and
    `_revision` via MRO."""

    def build_witness(
        self,
        scene_id: str,
        dynamic_context: list[str] | None = None,
        *,
        index: MutationsIndex | None = None,
    ) -> Witness:
        """The scene's immediate context, resolved as of that scene.

        `dynamic_context` distinguishes **not observed** (`None`) from
        **observed and empty** (`[]`). Only a caller with a prose editor behind
        it can supply the set; one that cannot records two sources instead of
        three, and the comparison narrows accordingly rather than reporting every
        implicitly-detected entity as removed.

        `index` is threaded rather than rebuilt: `build_mutations_index` is the
        expensive part of this request (1.16 s at 600 scenes), and a comparison
        that also resolves names would otherwise build it twice. Count the
        re-derivations of a shared traversal before adding a consumer.

        A capture is never the reason a save fails, so this degrades to an empty
        witness rather than raising: an absent witness reports as *no witness
        recorded*, which is honest, while a failed save loses words.
        """
        try:
            return self._build_witness(scene_id, dynamic_context, index=index)
        except (ProjectServiceError, OSError):
            return Witness()

    def _build_witness(
        self,
        scene_id: str,
        dynamic_context: list[str] | None,
        *,
        index: MutationsIndex | None,
    ) -> Witness:
        # One schema read, three derivations. `_mutation_field_types` reads it
        # again internally and the display maps would be a third — at ~10 ms a
        # read, that is most of the fixed cost of a witness on a typical scene.
        # Count the re-derivations of a shared traversal before adding a
        # consumer.
        schema = self._witness_schema()
        labels, options = _field_display_from(schema)
        scope = _WitnessScope(
            scene_id=scene_id,
            node_index=self._build_node_index(),
            mutations=index if index is not None else self.build_mutations_index(),
            field_types=_field_types_from(schema),
            labels=labels,
            options=options,
        )

        ordered, truncated = self._witness_membership(scope, dynamic_context or [])
        entities = [self._witness_entity(scope, entity_id, sources) for entity_id, sources in ordered]
        recorded = [SOURCE_MUTATION, SOURCE_ENTITY_REF]
        if dynamic_context is not None:
            recorded.append(SOURCE_DYNAMIC)
        return Witness(
            truncated=truncated,
            sources_recorded=recorded,
            entities=[e for e in entities if e is not None],
        )

    # ----- membership (drift axis 4's raw material) -------------------------

    def _witness_membership(
        self, scope: _WitnessScope, dynamic_context: list[str]
    ) -> tuple[list[tuple[str, list[str]]], bool]:
        """The witnessed ids with their provenance, and whether the cap fired.

        Only ids that resolve to a **lore** entry in this scope are kept. An id
        that resolves to nothing is dropped rather than recorded as an absent
        entity: an entity that never participated must not be manufactured into
        the report (#409, narrowed).
        """
        sources: dict[str, list[str]] = {}

        def add(entity_id: str, source: str) -> None:
            entry = scope.node_index.by_id.get(entity_id)
            if entry is None or entry.kind != "lore":
                return
            bucket = sources.setdefault(entity_id, [])
            if source not in bucket:
                bucket.append(source)

        for entity_id in scope.mutations.by_entity:
            if self.effective_state(
                entity_id, scope.scene_id, index=scope.mutations, field_types=scope.field_types
            ):
                add(entity_id, SOURCE_MUTATION)
        for edge in scope.node_index.edges_by_src.get(scope.scene_id, []):
            add(edge.dst, SOURCE_ENTITY_REF)
        for entity_id in dynamic_context[:MAX_DYNAMIC_CONTEXT_IDS]:
            add(entity_id, SOURCE_DYNAMIC)

        # Sorted by id, not by discovery order: the witness is compared against
        # a later rebuild, and a list whose order depends on dict iteration
        # would make the cap drop a different tail each time.
        ordered = sorted(sources.items())
        truncated = len(ordered) > MAX_WITNESS_ENTITIES or len(dynamic_context) > MAX_DYNAMIC_CONTEXT_IDS
        return ordered[:MAX_WITNESS_ENTITIES], truncated

    # ----- one entity -------------------------------------------------------

    def _witness_entity(
        self, scope: _WitnessScope, entity_id: str, sources: list[str]
    ) -> WitnessEntity | None:
        entry = scope.node_index.by_id.get(entity_id)
        if entry is None:
            return None
        overrides = self.effective_state(
            entity_id, scope.scene_id, index=scope.mutations, field_types=scope.field_types
        )
        base_title, base_metadata = self._witness_base_values(entry.path)

        # The resolved view: what this entity *was* at this scene. Stored values
        # with the live mutation overrides applied — not one or the other, since
        # a report that named only the stored value would be wrong inside an
        # interval, and one that named only the override would be empty outside.
        state: dict[str, Any] = {
            key: value
            for key, value in base_metadata.items()
            if key not in UNWITNESSED_FIELDS
        }
        state["title"] = base_title
        for key, value in overrides.items():
            if key not in UNWITNESSED_FIELDS:
                state[key] = value

        return WitnessEntity(
            id=entity_id,
            # A live title mutation wins even when it blanks the name (an
            # intentional rename to empty), so the default is only consulted
            # when no title mutation is in play — `or` would swallow "".
            title=str(overrides.get("title", base_title or "")),
            sources=list(sources),
            revision=self._witness_revision(entry.path),
            source_layer_id=entry.source_layer_id,
            source_layer_label=entry.source_layer_label,
            state=state,
            overrides=sorted(key for key in overrides if key not in UNWITNESSED_FIELDS),
            field_types={
                key: WitnessFieldType(
                    label=scope.labels.get(key, key),
                    type=scope.field_types.get(key, ""),
                    options=scope.options.get(key, []),
                )
                for key in state
            },
        )

    def _witness_revision(self, path: Path) -> str | None:
        """The opaque change token. `None` where it cannot be read, which the
        report shows as **unknown** — never folded into "unchanged"."""
        try:
            return self._revision(path)
        except OSError:
            return None

    def _witness_base_values(self, path: Path) -> tuple[str, dict[str, Any]]:
        """The entry's stored title and metadata, read **without validation**.

        Deliberately not `read_lore_entry`: a witness is a historical record and
        one side of the comparison may not satisfy today's schema. Validating
        here would drop exactly the entity whose value became illegal — the case
        the drift report exists to announce.
        """
        try:
            front_matter = self._read_front_matter_only(path)
        except (ProjectServiceError, OSError):
            return "", {}
        metadata = front_matter.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        return str(front_matter.get("title") or ""), dict(metadata)

    def _witness_schema(self) -> Any | None:
        """The merged schema, or `None` when it cannot be read.

        A capture is never the reason a save fails, so an unreadable schema
        costs the witness its labels and types, not its existence.
        """
        try:
            return self.read_metadata_schema()
        except ProjectServiceError:
            return None


def _field_types_from(schema: Any | None) -> dict[str, str]:
    """field id → type, plus the intrinsic title/body.

    Mirrors `_mutation_field_types` deliberately — same contract, but reading a
    schema the caller already has instead of fetching its own.
    """
    types = {"title": "text", "body": "long_text"}
    for field_id, field in (getattr(schema, "fields", None) or {}).items():
        types[field_id] = getattr(field, "type", "text")
    return types


def _field_display_from(schema: Any | None) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Field id → author-facing label, and field id → allowed option values.

    The label travels *into* the witness so the report can still speak the
    author's vocabulary about a field the schema has since dropped — which is
    precisely the case axis 3 fires on.
    """
    labels = {"title": "Title"}
    options: dict[str, list[str]] = {}
    for field_id, field in (getattr(schema, "fields", None) or {}).items():
        labels[field_id] = getattr(field, "name", "") or field_id
        options[field_id] = [
            str(getattr(option, "value", "") or "")
            for option in (getattr(field, "options", None) or [])
        ]
    return labels, options
