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

from collections.abc import Iterable
from dataclasses import dataclass
from dataclasses import field as dc_field
from pathlib import Path
from typing import Any

from app.models import Witness, WitnessEntity, WitnessFieldType
from app.services.project.errors import ProjectServiceError
from app.services.project.field_values import display_value as _display_value
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

# Field **types** never recorded in `state`: unbounded, and an edit to one still
# reports at the floor through `revision`. The witness stores what a report can
# *name*, and no report names a page of prose.
#
# By type, not by field id. Excluding `"body"` alone read as if the rule were
# about the intrinsic body, when the justification — "unbounded" — is a
# statement about the type: a schema `long_text` (a character's Notes, or the
# `summary` and `dynamics` fields the default schema already ships) is exactly
# as unbounded, and was being copied verbatim into every entity of every
# sidecar. Measured at ~40x the size of the prose the snapshot exists to hold.
UNWITNESSED_FIELD_TYPES = frozenset({"long_text"})

# Membership provenance, in the order sources are unioned. Ordering is fixed so
# a witness rebuilt from the same world is byte-identical.
SOURCE_MUTATION = "mutation"
SOURCE_ENTITY_REF = "entity_ref"
SOURCE_DYNAMIC = "dynamic"


@dataclass
class _Member:
    """One candidate entity while the membership pass runs.

    `overrides` is carried from the pass that already resolved it, so
    `effective_state` is computed once per entity rather than once to test
    membership and again to record state.
    """

    overrides: dict[str, Any]
    sources: list[str] = dc_field(default_factory=list)


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
        also_resolve: Iterable[str] = (),
    ) -> Witness | None:
        """The scene's immediate context, resolved as of that scene.

        `dynamic_context` distinguishes **not observed** (`None`) from
        **observed and empty** (`[]`). Only a caller with a prose editor behind
        it can supply the set; one that cannot records two sources instead of
        three, and the comparison narrows accordingly rather than reporting every
        implicitly-detected entity as removed.

        `also_resolve` names entities to record the state of **without making
        them members** (`sources` stays empty). The comparison passes the stored
        witness's ids, so an entity that has since dropped out of the context can
        still have its values named — see `_entity_drift`.

        `index` is threaded rather than rebuilt: `build_mutations_index` is the
        expensive part of this request (1.16 s at 600 scenes). Count the
        re-derivations of a shared traversal before adding a consumer.

        **Returns `None` when the witness could not be built**, and a capture
        then writes no witness at all. It used to return an empty `Witness()`,
        which is a different and much worse thing: the comparison accepted it as
        a real one and reported *nothing changed* — an affirmative all-clear from
        a build that saw nothing, which is the exact claim ADR-0043's
        degrade-coarsely rule says a witness must never make.

        The exception net matches `_build_node_index`'s for the same schema read:
        a bad schema shape arrives as a pydantic `ValidationError`, which is a
        `ValueError`. Catching only `ProjectServiceError`/`OSError` let it escape
        and 500 the save — breaking this method's own contract that a capture is
        never the reason a save fails.
        """
        try:
            return self._build_witness(
                scene_id, dynamic_context, index=index, also_resolve=also_resolve
            )
        except (ProjectServiceError, ValueError, OSError):
            return None

    def _build_witness(
        self,
        scene_id: str,
        dynamic_context: list[str] | None,
        *,
        index: MutationsIndex | None,
        also_resolve: Iterable[str],
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

        ordered, truncated = self._witness_membership(
            scope, dynamic_context or [], also_resolve
        )
        recorded = [SOURCE_MUTATION, SOURCE_ENTITY_REF]
        if dynamic_context is not None:
            recorded.append(SOURCE_DYNAMIC)
        return Witness(
            truncated=truncated,
            sources_recorded=recorded,
            entities=[
                self._witness_entity(scope, entity_id, member.sources, member.overrides)
                for entity_id, member in ordered
            ],
        )

    # ----- membership (drift axis 4's raw material) -------------------------

    def _witness_membership(
        self,
        scope: _WitnessScope,
        dynamic_context: list[str],
        also_resolve: Iterable[str],
    ) -> tuple[list[tuple[str, _Member]], bool]:
        """The witnessed ids with their provenance, and whether the cap fired.

        Only ids that resolve to a **lore** entry in this scope are kept. An id
        that resolves to nothing is dropped rather than recorded as an absent
        entity: an entity that never participated must not be manufactured into
        the report (#409, narrowed).

        The resolved overrides are **carried, not discarded**. This pass already
        computes `effective_state` for every candidate and used to keep only its
        truthiness, leaving `_witness_entity` to resolve each survivor a second
        time — which, whenever an `add`/`remove` op is live, means a second
        `read_lore_entry` per entity (a file read plus a schema merge).
        """
        members: dict[str, _Member] = {}

        def add(entity_id: str, source: str, overrides: dict[str, Any] | None = None) -> None:
            entry = scope.node_index.by_id.get(entity_id)
            if entry is None or entry.kind != "lore":
                return
            member = members.get(entity_id)
            if member is None:
                member = _Member(
                    overrides=self._resolve_overrides(scope, entity_id)
                    if overrides is None
                    else overrides
                )
                members[entity_id] = member
            if source and source not in member.sources:
                member.sources.append(source)

        for entity_id in scope.mutations.by_entity:
            overrides = self._resolve_overrides(scope, entity_id)
            if overrides:
                add(entity_id, SOURCE_MUTATION, overrides)
        for edge in scope.node_index.edges_by_src.get(scope.scene_id, []):
            add(edge.dst, SOURCE_ENTITY_REF)
        for entity_id in dynamic_context[:MAX_DYNAMIC_CONTEXT_IDS]:
            add(entity_id, SOURCE_DYNAMIC)
        # Non-members: recorded so their values can still be compared, never
        # counted as part of this scene's context. `add("")` adds no source.
        for entity_id in also_resolve:
            add(entity_id, "")

        # Sorted by id, not by discovery order: the witness is compared against
        # a later rebuild, and a list whose order depends on dict iteration
        # would make the cap drop a different tail each time.
        ordered = sorted(members.items())
        truncated = len(ordered) > MAX_WITNESS_ENTITIES or len(dynamic_context) > MAX_DYNAMIC_CONTEXT_IDS
        return ordered[:MAX_WITNESS_ENTITIES], truncated

    def _resolve_overrides(self, scope: _WitnessScope, entity_id: str) -> dict[str, Any]:
        return self.effective_state(
            entity_id, scope.scene_id, index=scope.mutations, field_types=scope.field_types
        )

    # ----- one entity -------------------------------------------------------

    def _witness_entity(
        self,
        scope: _WitnessScope,
        entity_id: str,
        sources: list[str],
        overrides: dict[str, Any],
    ) -> WitnessEntity:
        # Total, not optional: `_witness_membership.add()` already resolved this
        # id against this same `node_index` and dropped anything that did not,
        # so a `None` guard here would be a defence with no invariant behind it
        # — and one no test could ever reach.
        entry = scope.node_index.by_id[entity_id]
        base_title, base_metadata = self._witness_base_values(entry.path)

        # The resolved view: what this entity *was* at this scene. Stored values
        # with the live mutation overrides applied — not one or the other, since
        # a report that named only the stored value would be wrong inside an
        # interval, and one that named only the override would be empty outside.
        def witnessed(key: str) -> bool:
            return scope.field_types.get(key, "text") not in UNWITNESSED_FIELD_TYPES

        state: dict[str, Any] = {
            key: value for key, value in base_metadata.items() if witnessed(key)
        }
        state["title"] = base_title
        for key, value in overrides.items():
            if witnessed(key):
                state[key] = value

        return WitnessEntity(
            id=entity_id,
            # Read off `state`, never recomputed. The effective-title rule was
            # written twice — once building `state["title"]`, once as
            # `str(overrides.get(...))` — and the `str()` in the second silently
            # stringified what the first kept structured: retyping the intrinsic
            # `title` to a collection made this the Python repr of a list, which
            # the report then rendered as the entity's name.
            title=_display_value(state.get("title")),
            sources=list(sources),
            revision=self._witness_revision(entry.path),
            source_layer_label=entry.source_layer_label,
            state=state,
            overrides=sorted(key for key in overrides if witnessed(key)),
            field_types={
                key: WitnessFieldType(
                    # Empty, not the field id, when the schema has no entry for
                    # this key. The id looked like a harmless fallback but it
                    # made every label truthy, so the comparison's own fallback
                    # to the *captured* label became unreachable — and a field
                    # the schema has since dropped, which is exactly what axis 3
                    # fires on, was reported by its raw id.
                    label=scope.labels.get(key, ""),
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
        """The entry's stored title and metadata, **normalised but not validated**.

        Deliberately not `read_lore_entry`: a witness is a historical record and
        one side of the comparison may not satisfy today's schema. Validating
        here would drop exactly the entity whose value became illegal — the case
        the drift report exists to announce.

        **`_normalise_metadata` is not optional, though**, and skipping it was
        two bugs at once. It is the same `str()` coercion `_snapshot_state` uses
        one module over, for the same reason its docstring gives: an unquoted
        YAML date loads as `datetime.date`, and since the *stored* side of the
        witness goes through `model_dump(mode="json")` on the way to the sidecar
        while the *live* side did not, the two rendered identically and compared
        unequal — a drift row reading `Born: 1985-04-12 → 1985-04-12`, on every
        park, forever, on a scene nobody had touched. It also coerces keys to
        `str`, without which a hand-authored `metadata: {2019: …}` reached a
        `str`-typed pydantic field and 500'd the author's save.

        Both sides of a comparison must come off the same pipeline; this is that
        pipeline for the witness.
        """
        try:
            front_matter = self._read_front_matter_only(path)
            metadata = self._normalise_metadata(front_matter.get("metadata"), path)
        except (ProjectServiceError, OSError):
            return "", {}
        return str(front_matter.get("title") or ""), metadata

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
