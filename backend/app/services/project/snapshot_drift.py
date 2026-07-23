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


def compare_witnesses(was: Witness | None, now: Witness | None) -> SnapshotDrift:
    """What has changed between the world at capture and the world now.

    Three outcomes, kept distinguishable because the surface cannot honour a
    distinction the payload has collapsed:

    - `available=False` — the snapshot predates the witness. There is nothing to
      compare, which is neither "unchanged" nor "unknown".
    - `comparable=False` — one side cannot be read. Either the stored witness was
      recorded under a shape this build does not understand, or the *current*
      side could not be built at all. Degrade coarsely; never guess.
    - a real comparison, whose `entities` may legitimately be empty.
    """
    if was is None:
        return SnapshotDrift(available=False)
    # A live side that would not build is not evidence of an unchanged world.
    # Reporting an empty comparison here was an affirmative all-clear drawn from
    # having seen nothing.
    if now is None or was.version != WITNESS_VERSION:
        return SnapshotDrift(available=True, comparable=False, truncated=was.truncated)

    was_by_id = {entity.id: entity for entity in was.entities}
    now_by_id = {entity.id: entity for entity in now.entities}

    # Membership is only a claim about the sources **both** sides observed. A
    # witness captured without a prose editor behind it has no dynamic set, and
    # differencing that against one that does would report every
    # implicitly-detected entity as removed on a scene nobody touched.
    common_sources = set(was.sources_recorded) & set(now.sources_recorded)

    # …and it is not a claim either side is in a position to make once the entity
    # cap has fired. The cap keeps the lowest-sorting ids and is applied
    # independently on each side, so a single new low-sorting entity shifts the
    # retained window and drops a different tail — which the set difference then
    # reported as an entity "no longer part of this scene" while it sat, present
    # and unchanged, in both worlds. Field, revision, schema and layer drift on
    # the entities both sides did retain are unaffected and still reported.
    membership_is_claimable = not (was.truncated or now.truncated)

    entities: list[EntityDrift] = []
    # Sorted so the report is stable across requests; the surface orders for
    # reading, not the wire.
    for entity_id in sorted(set(was_by_id) | set(now_by_id)):
        drift = _entity_drift(
            was_by_id.get(entity_id),
            now_by_id.get(entity_id),
            common_sources,
            membership_is_claimable=membership_is_claimable,
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
    was: WitnessEntity | None,
    now: WitnessEntity | None,
    common_sources: set[str],
    *,
    membership_is_claimable: bool,
) -> EntityDrift | None:
    """One entity across the axes, or `None` when it has nothing to report.

    An entity present in both versions with nothing to say about it is omitted.
    Under an advisory model a report that lists the unchanged trains the
    dismissal that makes it worthless on the one occasion it mattered — detector
    precision is part of the report-quality obligation, not separate from it.

    An entity that participated in **neither** version never reaches here: the
    union is over what the two witnesses recorded, so absence is never
    manufactured into a claim.

    **Membership keys on `sources`, not on presence.** A witness may carry an
    entity with no sources — recorded so its values can still be compared, but
    not a member of that version's context. That is what lets the mutation case
    report properly: an entity whose only source was a marker interval, and whose
    interval has since been deleted, is no longer a member *and* has values worth
    naming. Keying on presence returned a bare "no longer part of this scene" and
    discarded both values — on ADR-0043's own motivating example.
    """
    if was is None and now is None:  # pragma: no cover - not reachable from the union
        return None

    was_member = bool(was and common_sources.intersection(was.sources))
    now_member = bool(now and common_sources.intersection(now.sources))
    membership = "present"
    if was_member and not now_member:
        # A character who played a primary role in one version and is absent or
        # deleted in the other is exactly the information the author needs, and
        # it is not obtainable from any per-entity comparison.
        membership = "removed"
    elif now_member and not was_member:
        membership = "added"
    elif not was_member and not now_member:
        # Neither side counts it as context — nothing to say about the set, and
        # nothing to say about a version that never had it.
        return None
    if membership != "present" and not membership_is_claimable:
        membership = "present"

    # Only one side has a record: there is no comparison to make, so the
    # membership claim is all there is.
    if was is None or now is None:
        recorded = was or now
        if membership == "present":
            return None
        return EntityDrift(
            entity_id=recorded.id,
            title=recorded.title or recorded.id,
            membership=membership,
            sources=list(recorded.sources),
        )

    fields = _field_drifts(was, now)
    reinterpreted = _reinterpretations(was, now)
    entry_changed = _entry_changed(was, now)
    # The **label**, never the layer id: that id is a hash of the resolved folder
    # path, and comparing one across a project move would fire this axis on every
    # witnessed entity of every existing snapshot.
    layer_moved = was.source_layer_label != now.source_layer_label

    if (
        membership == "present"
        and not fields
        and not reinterpreted
        and entry_changed == "no"
        and not layer_moved
    ):
        return None

    return EntityDrift(
        entity_id=now.id,
        # The current name, so the author recognises what they are looking at;
        # the captured one only survives for an entity that no longer exists.
        title=now.title or was.title or now.id,
        membership=membership,
        sources=list(now.sources or was.sources),
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
