"""One field's descriptor for the `fields()` Jinja global (ADR-0060 §3).

`helpers._fields` walks an entry type's fields; this builds each one's
`{id, label, type, options, option_labels, description, group, proposable}`
descriptor (plus `tag_vocabulary` and list `items`), and ranks a tag field's
vocabulary. Split out of `helpers.py` for the file-size cap (#2515).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.services.ai.entry_patch import is_proposable_field, tag_vocabulary_target

if TYPE_CHECKING:
    from app.services.project_service import ProjectService


def option_labels(options: Any) -> dict[str, str]:
    """Each option value's display text (#2513), so a template that READS a
    select shows what the author sees ("Rebel"), not the stored key ("reb"). A
    label defaults to its value, like the rail's. `{}` without options."""
    return {opt.value: opt.label or opt.value for opt in options} if options else {}


# The vocabulary line is meant to fit in one field-contract row, not become
# its own budget line — capped well below what a large project's tag roster
# could otherwise dump into every revise-entry render (#1799).
_TAG_VOCABULARY_CAP = 60


def tag_vocabulary_titles(
    project: ProjectService, entry_type: str, *, cap: int = _TAG_VOCABULARY_CAP
) -> tuple[list[str], int]:
    """Every `entry_type` tag's title in the merged layer chain, ranked by
    USAGE — backlink count, `index.edges_by_dst` — descending, then title
    alphabetically (case-insensitive) for ties (round 2, Y2): the "prefer
    tags that already exist" guidance is most actionable when the tags shown
    are the ones actually in play, not just the alphabetically-first 60.
    `edges_by_dst` is already folded through `canonical_id` (ADR-0082 §5), so
    a merged tag's backlinks count toward its survivor with no extra work
    here, and it holds only real `ReferenceEdge`s — a `merged_into` redirect
    is metadata, not an edge, so it can never inflate a usage count on its
    own ("redirect edges excluded" is a byproduct of the shape, not a filter
    this function applies).

    Capped at `cap`; returns `(titles, total)` so a caller can tell the model
    the list is partial (`_describe_field`, `field_contract.py`) rather than
    silently reading as the whole vocabulary. A merged-away tag itself
    (`merged_into` set) is excluded from the candidates: its title is a stale
    redirect, not something to propose. A duplicate title (a rare hand-edited
    collision) keeps its highest usage count, so the list has no repeats."""
    index = project._build_assistant_index()
    usage_by_title: dict[str, int] = {}
    for entry in index.by_id.values():
        if entry.kind != "tag" or entry.entry_type != entry_type or entry.merged_into:
            continue
        usage = len(index.edges_by_dst.get(entry.id, []))
        usage_by_title[entry.title] = max(usage, usage_by_title.get(entry.title, 0))
    ranked = sorted(usage_by_title, key=lambda title: (-usage_by_title[title], title.lower()))
    return ranked[:cap], len(ranked)


def field_descriptor(
    project: ProjectService, schema: Any, definition: Any, field_id: str
) -> dict[str, Any]:
    """The descriptor for `field_id` on the resolved entry type `definition`."""
    field = schema.fields.get(field_id)
    # `options` is always present (empty when the field has none) so the
    # create template can test `f.options` without hitting StrictUndefined.
    # For `list` fields the top-level options are SUPPRESSED: the select
    # sugar stores its choices on the field, but "one of: …" at field
    # level reads as a constraint on the field's own (non-array) value —
    # the choices belong to the item descriptor below.
    # Resolve the field's per-type label (#1009): a `field_overrides[id].label`
    # on the resolved type wins over the shared field def's name — the same
    # resolution the rail UI (`effectiveFieldLabel`) uses, so the model sees a
    # field by the name the author sees (e.g. `title` = "Name" on lore,
    # "Title" on scene) instead of always the global "Title". The description
    # resolves the same way: a per-type `description` wins over the shared one.
    override = definition.field_overrides.get(field_id)
    descriptor: dict[str, Any] = {
        "id": field_id,
        "label": override.label if override and override.label else field.name,
        "type": field.type,
        "options": [opt.value for opt in field.options] if field.options and field.type != "list" else [],
        # The display text for each option value (#2513), so a template that
        # READS a select shows what the author sees ("Rebel"), not the stored
        # key ("reb"). A label defaults to its value, like the rail's.
        "option_labels": option_labels(field.options) if field.type != "list" else {},
        # Author help text (#1004): what the field is FOR, so the model
        # proposes on-target values. Always present (None when unset) so the
        # template can test `f.description` without hitting StrictUndefined.
        "description": override.description if override and override.description else field.description,
        # The field's section label (#784), so a template can reason about
        # fields BY their group — `{% for f in fields(e) if f.group == "GMO" %}`
        # renders an applied struct (Goal/Motivation/Obstacle) as one block.
        # It is the same `group` an L2 group application stamps on its members
        # and a manual section header uses; None when ungrouped. Always present
        # so the template can test `f.group` without hitting StrictUndefined.
        "group": field.group,
        # Advisory (ADR-0060 §3): whether it makes sense to ask the AI to
        # compute a value — `false` for computed / reference / hidden fields.
        # The template decides what to do with it; the roster is never
        # pre-filtered on it (retires the old `is_proposable_field` gate).
        "proposable": is_proposable_field(field_id, field, schema),
    }
    # ADR-0082 §2 / #1799: a proposable tag-vocabulary field carries its
    # live vocabulary titles alongside the descriptor, so `field_contract`'s
    # "prefer tags that already exist" guidance (`_describe_field`) is
    # actionable rather than abstract. Ranked by usage + capped (round 2,
    # Y2) — an unbounded list would blow the prompt's token budget on a
    # large project; `tag_vocabulary_total` is the uncapped count, so a
    # truncated render can say how many more exist.
    tag_target = tag_vocabulary_target(field, schema)
    if tag_target is not None:
        titles, total = tag_vocabulary_titles(project, tag_target)
        descriptor["tag_vocabulary"] = titles
        descriptor["tag_vocabulary_total"] = total
    # List fields (#698): describe the item shape so the model emits
    # legal items — flat scalars for item_type sugar, member-keyed maps
    # for a group shape. `items` mirrors the top-level descriptor shape
    # per member; templates test `f['items']` the way they test options.
    if field.type == "list" and field.item_members:
        # The resolver's tie-break verdict, never the raw declaration —
        # a cross-layer both-keys conflict would otherwise make this
        # describe a record list as a flat scalar array.
        descriptor["item_scalar"] = bool(field.item_scalar)
        descriptor["items"] = [
            {
                "key": member.key,
                "label": member.name or member.key,
                "type": member.type,
                "options": [opt.value for opt in member.options] if member.options else [],
                # As on the field (#2515): each option value's display text.
                "option_labels": option_labels(member.options),
            }
            for member in field.item_members
        ]
    return descriptor
