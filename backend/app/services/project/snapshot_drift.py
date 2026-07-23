"""Comparing two witnesses (ADR-0043, #439 slice 3).

The half the feature is named for. ADR-0043: *if the report is the only
protection, the report is the feature* — it must name what actually changed, the
entity, the field, the value then versus now, in the author's vocabulary. A
report that can only say "context has changed since this snapshot was taken" has
not implemented the design, however correct the storage is.

Pure and IO-free: both witnesses were produced by `build_witness`, so both sides
of every comparison already came off the same pipeline. Everything here is set
arithmetic and value equality.

**Five axes** (`docs/design/snapshots-and-the-witness.md` §2, plus §3's gap):

1. **mutation / value** — `state` compared field by field, attributed to a marker
   through `overrides`;
2. **inheritance** — `revision` as an **opaque** token, never inspected;
3. **reinterpretation** — the type and constraints of *only the recorded fields*;
4. **membership** — set difference, in **both** directions;
5. **visibility** — the resolved source layer, which no hash over file bytes can
   see, including the composite `revision` #314 introduces.

**Advisory, always.** Nothing here gates a restore, asks for an acknowledgement
or refuses to perform anything.
"""

from __future__ import annotations

from app.models import (
    WITNESS_VERSION,
    EntityDrift,
    FieldReinterpretation,
    SnapshotDrift,
    Witness,
    WitnessEntity,
    WitnessFieldDrift,
    WitnessFieldType,
)
from app.services.project.field_values import same_rendered_value


def compare_witnesses(was: Witness | None, now: Witness) -> SnapshotDrift:
    """What has changed between the world at capture and the world now.

    Three outcomes, kept distinguishable because the surface cannot honour a
    distinction the payload has collapsed:

    - `available=False` — the snapshot predates the witness. There is nothing to
      compare, which is neither "unchanged" nor "unknown".
    - `comparable=False` — the witness was recorded under a shape this build
      cannot read. Degrade coarsely; never guess.
    - a real comparison, whose `entities` may legitimately be empty.
    """
    if was is None:
        return SnapshotDrift(available=False)
    if was.version != WITNESS_VERSION:
        return SnapshotDrift(available=True, comparable=False, truncated=was.truncated)

    was_by_id = {entity.id: entity for entity in was.entities}
    now_by_id = {entity.id: entity for entity in now.entities}

    # Membership is only a claim about the sources **both** sides observed. A
    # witness captured without a prose editor behind it has no dynamic set, and
    # differencing that against one that does would report every
    # implicitly-detected entity as removed on a scene nobody touched.
    common_sources = set(was.sources_recorded) & set(now.sources_recorded)

    entities: list[EntityDrift] = []
    # Sorted so the report is stable across requests; the surface orders for
    # reading, not the wire.
    for entity_id in sorted(set(was_by_id) | set(now_by_id)):
        drift = _entity_drift(
            was_by_id.get(entity_id), now_by_id.get(entity_id), common_sources
        )
        if drift is not None:
            entities.append(drift)

    return SnapshotDrift(
        available=True,
        comparable=True,
        truncated=was.truncated or now.truncated,
        entities=entities,
    )


def _entity_drift(
    was: WitnessEntity | None, now: WitnessEntity | None, common_sources: set[str]
) -> EntityDrift | None:
    """One entity across the axes, or `None` when it has nothing to report.

    An entity present in both versions with nothing to say about it is omitted.
    Under an advisory model a report that lists the unchanged trains the
    dismissal that makes it worthless on the one occasion it mattered — detector
    precision is part of the report-quality obligation, not separate from it.

    An entity that participated in **neither** version never reaches here: the
    union is over what the two witnesses recorded, so absence is never
    manufactured into a claim.
    """
    if was is None and now is None:  # pragma: no cover - not reachable from the union
        return None
    if now is None:
        # Removed. A character who played a primary role in one version and is
        # absent or deleted in the other is exactly the information the author
        # needs, and it is not obtainable from any per-entity comparison.
        if not common_sources.intersection(was.sources):
            return None
        return EntityDrift(
            entity_id=was.id,
            title=was.title or was.id,
            membership="removed",
            sources=list(was.sources),
        )
    if was is None:
        if not common_sources.intersection(now.sources):
            return None
        return EntityDrift(
            entity_id=now.id,
            title=now.title or now.id,
            membership="added",
            sources=list(now.sources),
        )

    fields = _field_drifts(was, now)
    reinterpreted = _reinterpretations(was, now)
    entry_changed = _entry_changed(was, now)
    layer_moved = was.source_layer_id != now.source_layer_id

    if not fields and not reinterpreted and entry_changed == "no" and not layer_moved:
        return None

    return EntityDrift(
        entity_id=now.id,
        # The current name, so the author recognises what they are looking at;
        # the captured one only survives for an entity that no longer exists.
        title=now.title or was.title or now.id,
        membership="present",
        sources=list(now.sources),
        entry_changed=entry_changed,
        fields=fields,
        reinterpreted=reinterpreted,
        layer_was=was.source_layer_label if layer_moved else "",
        layer_now=now.source_layer_label if layer_moved else "",
    )


def _entry_changed(was: WitnessEntity, now: WitnessEntity) -> str:
    """Axis 2, as a tristate.

    The token is **opaque** — never inspected, only compared — which is what
    makes this independent of #314 rather than blocked on it: when `revision`
    becomes a composite hash, snapshots get the better detector with no edit
    here.

    `unknown` where the tokens cannot be compared meaningfully: a token that
    could not be read, or one computed under a different definition. ADR-0043's
    degrade-coarsely rule — those snapshots must report the axis as **unknown**
    rather than as **unchanged**, because "unchanged" is a claim and this is not
    in a position to make it.
    """
    if was.revision is None or now.revision is None:
        return "unknown"
    if was.revision_kind != now.revision_kind:
        return "unknown"
    return "yes" if was.revision != now.revision else "no"


def _field_drifts(was: WitnessEntity, now: WitnessEntity) -> list[WitnessFieldDrift]:
    """Axis 1 and the field-level detail for a direct edit.

    `state` is the resolved view on both sides, so one comparison covers both a
    marker in another scene and an edit to the entry itself. `from_mutation`
    attributes it: the author needs to know whether to look for a marker or for
    an edit, and the two are fixed in different places.

    Absence is compared the way the rail renders it (`same_rendered_value`) — a
    missing key and an empty one read identically, so flipping between them would
    show two values the author cannot tell apart.
    """
    mutated = set(was.overrides) | set(now.overrides)
    drifts: list[WitnessFieldDrift] = []
    for field_id in sorted(set(was.state) | set(now.state)):
        was_value = was.state.get(field_id)
        now_value = now.state.get(field_id)
        if same_rendered_value(was_value, now_value):
            continue
        drifts.append(
            WitnessFieldDrift(
                field_id=field_id,
                label=_label(field_id, now.field_types, was.field_types),
                was=was_value,
                now=now_value,
                from_mutation=field_id in mutated,
            )
        )
    return drifts


def _reinterpretations(was: WitnessEntity, now: WitnessEntity) -> list[FieldReinterpretation]:
    """Axis 3 — the *meaning* of a recorded value moved under it.

    Scoped to the fields present in **both** witnesses' `field_types`, which is
    to say the fields the witness actually recorded. Not a whole-schema hash:
    that fires on every schema edit, including the additions and deletions the
    sparse storage model already absorbs harmlessly, so most reports would
    announce a change with no consequence.

    A field that appeared or disappeared is not a reinterpretation — it is a
    membership change *within* the entity, and `_field_drifts` already carries it
    with both values.
    """
    reinterpreted: list[FieldReinterpretation] = []
    for field_id in sorted(set(was.field_types) & set(now.field_types)):
        was_type = was.field_types[field_id]
        now_type = now.field_types[field_id]
        if was_type.type == now_type.type and was_type.options == now_type.options:
            continue
        reinterpreted.append(
            FieldReinterpretation(
                field_id=field_id,
                label=_label(field_id, now.field_types, was.field_types),
                type_was=was_type.type,
                type_now=now_type.type,
                options_was=list(was_type.options),
                options_now=list(now_type.options),
            )
        )
    return reinterpreted


def _label(field_id: str, *sources: dict[str, WitnessFieldType]) -> str:
    """The field's author-facing name, preferring the current one.

    Falls back through the captured witness and then to the raw id: a field the
    schema has since dropped still has a name the author will recognise, and that
    is exactly the field axis 3 fires on.
    """
    for source in sources:
        label = source.get(field_id)
        if label is not None and label.label:
            return label.label
    return field_id
