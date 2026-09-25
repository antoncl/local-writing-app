"""The retired inline mutation grammar (ADR-0001/ADR-0016), kept only for the
migration and for restoring a pre-ADR-0095 snapshot (§11, §12). This module is
the grammar's only home now — `lore_mutations.py` imports it from here so its
own (still-legacy-reading) behaviour is unchanged, and the ADR-0095 migration
imports it to convert a project's scenes to sets + anchors.

The legacy grammar, unchanged from `lore_mutations.py`'s original docstring:

    <!-- mutate:entity=<lore-id>;field=<field-key>;value=<url-encoded>;id=<marker-id> -->

v1.1 optional attributes (absent on v1.0 markers, so old markers parse
unchanged): `op=<add|remove|replace>` (default `replace`), `name=<url-encoded>`
and `group=<group-id>` (a legacy co-authored-set tie). Canonical order is
`entity;field;op?;value;name?;group?;id`.

The **carrier** form (#69, ADR-0016) is one authored change touching N fields
as one multi-line comment — a head (entity, optional name, unit id) plus one
`field=` row per line, each row keeping its own id:

    <!-- mutate:entity=<lore-id>[;name=<url-encoded>];id=<unit-id>
    field=<key>[;op=<op>];value=<url-encoded>;id=<row-id>
    -->

The single-line marker is the degenerate one-row form of the same grammar.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import unquote

from app.services.project.mutation_anchors import (
    derive_anchor_id,
    derive_set_id,
    render_anchor,
    render_close,
)

MUTATION_MARKER_PATTERN = re.compile(
    r"<!--\s*mutate:entity=(?P<entity>[A-Za-z0-9_-]+);field=(?P<field>[A-Za-z0-9_.-]+);"
    r"(?:op=(?P<op>add|remove|replace);)?"
    r"value=(?P<value>[^;\s]*)"
    r"(?:;name=(?P<name>[^;\s]*))?"
    r"(?:;group=(?P<group>[A-Za-z0-9_-]+))?"
    r";id=(?P<id>[A-Za-z0-9_-]+)\s*-->",
)

# Carrier marker (#69, ADR-0016): head line + one field row per line. The rows
# capture is deliberately loose (whole lines) — each line is re-matched against
# MUTATION_CARRIER_ROW_PATTERN, and a carrier with ANY malformed row does not
# parse as a unit at all (stays an inert comment), so a rewrite can never
# silently drop a hand-authored line it failed to understand.
MUTATION_CARRIER_PATTERN = re.compile(
    r"<!--[ \t]*mutate:entity=(?P<entity>[A-Za-z0-9_-]+)"
    r"(?:;name=(?P<name>[^;\s]*))?"
    r";id=(?P<id>[A-Za-z0-9_-]+)[ \t]*\r?\n"
    r"(?P<rows>(?:[ \t]*field=[^\r\n]*\r?\n)+)"
    r"[ \t]*-->",
)

MUTATION_CARRIER_ROW_PATTERN = re.compile(
    r"field=(?P<field>[A-Za-z0-9_.-]+);"
    r"(?:op=(?P<op>add|remove|replace);)?"
    r"value=(?P<value>[^;\s]*)"
    r";id=(?P<id>[A-Za-z0-9_-]+)",
)

# The legacy close marker (ADR-0010): a separate point marker ending the start
# record `ref`. Byte-identical to a new no-`row=` close (ADR-0095 §1), which is
# what lets the converter recognise its own output as already-converted on a
# second pass (see `convert_legacy_mutations`).
_LEGACY_CLOSE_PATTERN = re.compile(
    r"<!--\s*mutate:close;ref=(?P<ref>[A-Za-z0-9_-]+);id=(?P<id>[A-Za-z0-9_-]+)\s*-->",
)


@dataclass
class CarrierRow:
    """One `field=` row of a carrier marker (#69), value kept url-encoded
    verbatim so untouched rows round-trip byte-stable through a rewrite."""

    field: str
    op: str  # "replace" when the marker omits op=
    raw_value: str
    row_id: str


def _parse_carrier_rows(match: re.Match[str]) -> list[CarrierRow] | None:
    """Parse a carrier match's row block. `None` when any row is malformed —
    the whole comment then stays an inert (never-rewritten) comment."""
    rows: list[CarrierRow] = []
    for line in match.group("rows").splitlines():
        text = line.strip()
        if not text:
            continue
        row = MUTATION_CARRIER_ROW_PATTERN.fullmatch(text)
        if row is None:
            return None
        rows.append(
            CarrierRow(
                field=row.group("field"),
                op=row.group("op") or "replace",
                raw_value=row.group("value"),
                row_id=row.group("id"),
            )
        )
    return rows or None


# ----- ADR-0095 §12: legacy → sets + anchors converter -----------------------


@dataclass
class ConvertedRow:
    id: str
    field: str
    op: str
    value: str  # url-DECODED


@dataclass
class ConvertedSet:
    set_id: str
    anchor_id: str
    scene_id: str
    entity_id: str
    title: str  # "" when the unit/marker had no name
    target_entry_type: str  # "" when entity_type() returned None
    rows: list[ConvertedRow]
    unit_id: str  # the legacy unit id it came from


@dataclass
class ConversionResult:
    bodies: dict[str, str]  # scene_id -> converted body, ONLY for scenes that changed
    sets: list[ConvertedSet]  # in manuscript order


@dataclass
class _Occurrence:
    scene_id: str
    scene_index: int
    offset: int
    anchor_id: str


@dataclass
class _Unit:
    unit_id: str
    entity_id: str
    title: str
    rows: list[ConvertedRow]
    span: tuple[int, int]
    group_id: str = ""


def _scan_units(body: str) -> list[_Unit]:
    """Every legacy unit (single-line marker or carrier) in `body`, in prose
    order. A single-line marker WITH `group=` is still its own one-row unit
    (§12 step 4/ADR §3 rule 3) — the group id is recorded separately, for
    close expansion."""
    units: list[_Unit] = []
    for match in MUTATION_MARKER_PATTERN.finditer(body):
        unit_id = match.group("id")
        name = unquote(match.group("name") or "")
        row = ConvertedRow(
            id=unit_id,
            field=match.group("field"),
            op=match.group("op") or "replace",
            value=unquote(match.group("value")),
        )
        units.append(
            _Unit(
                unit_id=unit_id,
                entity_id=match.group("entity"),
                title=name,
                rows=[row],
                span=match.span(),
                group_id=match.group("group") or "",
            )
        )
    for match in MUTATION_CARRIER_PATTERN.finditer(body):
        parsed = _parse_carrier_rows(match)
        if parsed is None:
            continue  # malformed carrier — left untouched
        unit_id = match.group("id")
        rows = [
            ConvertedRow(id=r.row_id, field=r.field, op=r.op, value=unquote(r.raw_value))
            for r in parsed
        ]
        units.append(
            _Unit(
                unit_id=unit_id,
                entity_id=match.group("entity"),
                title=unquote(match.group("name") or ""),
                rows=rows,
                span=match.span(),
            )
        )
    units.sort(key=lambda u: u.span[0])
    return units


def _emit_closes(
    ref: str,
    close_id: str,
    close_pos: tuple[int, int],
    unit_occurrences: dict[str, list[_Occurrence]],
    group_members: dict[str, list[_Occurrence]],
    row_to_unit: dict[str, str],
) -> str | None:
    """The replacement text for one legacy close, or `None` when `ref`
    resolves to nothing in this input (left unchanged) — §12 step 5 / ADR §7
    rule 7."""
    row = ""
    if ref in unit_occurrences:
        occurrences = unit_occurrences[ref]
    elif ref in group_members:
        occurrences = group_members[ref]
    elif ref in row_to_unit:
        occurrences = unit_occurrences.get(row_to_unit[ref], [])
        row = ref
    else:
        return None
    due = [occ for occ in occurrences if (occ.scene_index, occ.offset) <= close_pos]
    if not due:
        return None
    rendered = []
    for n, occ in enumerate(due, start=1):
        variant = close_id if n == 1 else f"{close_id}_{n}"
        rendered.append(render_close(occ.anchor_id, variant, row=row))
    return "\n".join(rendered)


@dataclass
class _Registry:
    """Working state of the unit pass: every occurrence found, keyed for the
    close pass to resolve refs against (§12 step 5)."""

    unit_occurrences: dict[str, list[_Occurrence]]
    group_members: dict[str, list[_Occurrence]]
    row_to_unit: dict[str, str]
    sets: list[ConvertedSet]
    replacements: dict[str, list[tuple[int, int, str]]]
    repeats_in_scene: dict[tuple[str, str], int]


def _register_unit(
    registry: _Registry, scene_id: str, scene_index: int, unit: _Unit, entity_type: Callable[[str], str | None]
) -> None:
    """Assign `unit`'s anchor/set id (first occurrence keeps its legacy id, a
    later one is derived, §12 step 3), record it in `registry` and queue its
    body-span replacement.

    A unit id repeated more than once within the *same* scene would otherwise
    derive the same id twice (`derive_anchor_id`/`derive_set_id` key only on
    scene + unit id) — `repeats_in_scene` counts same-scene repeats so the
    2nd+ repeat in one scene gets its own disambiguated key."""
    first = unit.unit_id not in registry.unit_occurrences
    if first:
        anchor_id = unit.unit_id
        set_id = derive_set_id(unit.unit_id)
    else:
        key = (scene_id, unit.unit_id)
        k = registry.repeats_in_scene.get(key, 0) + 1
        registry.repeats_in_scene[key] = k
        anchor_id = derive_anchor_id(scene_id, unit.unit_id, k)
        set_id = derive_set_id(
            f"{scene_id}:{unit.unit_id}" if k <= 1 else f"{scene_id}:{unit.unit_id}:{k}"
        )
    occurrence = _Occurrence(
        scene_id=scene_id, scene_index=scene_index, offset=unit.span[0], anchor_id=anchor_id
    )
    registry.unit_occurrences.setdefault(unit.unit_id, []).append(occurrence)
    if unit.group_id:
        registry.group_members.setdefault(unit.group_id, []).append(occurrence)
    if len(unit.rows) > 1:
        for row in unit.rows:
            registry.row_to_unit[row.id] = unit.unit_id
    registry.sets.append(
        ConvertedSet(
            set_id=set_id,
            anchor_id=anchor_id,
            scene_id=scene_id,
            entity_id=unit.entity_id,
            title=unit.title,
            target_entry_type=entity_type(unit.entity_id) or "",
            rows=unit.rows,
            unit_id=unit.unit_id,
        )
    )
    registry.replacements[scene_id].append(
        (unit.span[0], unit.span[1], render_anchor(set_id, anchor_id))
    )


def _scan_units_pass(
    scenes: list[tuple[str, str]], entity_type: Callable[[str], str | None]
) -> _Registry:
    registry = _Registry({}, {}, {}, [], {sid: [] for sid, _ in scenes}, {})
    for scene_index, (scene_id, body) in enumerate(scenes):
        for unit in _scan_units(body):
            _register_unit(registry, scene_id, scene_index, unit, entity_type)
    return registry


def _scan_closes_pass(
    scenes: list[tuple[str, str]], registry: _Registry
) -> dict[str, list[tuple[int, int, str]]]:
    close_replacements: dict[str, list[tuple[int, int, str]]] = {sid: [] for sid, _ in scenes}
    for scene_index, (scene_id, body) in enumerate(scenes):
        for match in _LEGACY_CLOSE_PATTERN.finditer(body):
            replacement = _emit_closes(
                match.group("ref"),
                match.group("id"),
                (scene_index, match.start()),
                registry.unit_occurrences,
                registry.group_members,
                registry.row_to_unit,
            )
            if replacement is not None:
                close_replacements[scene_id].append((match.start(), match.end(), replacement))
    return close_replacements


def _apply_edits(
    scenes: list[tuple[str, str]],
    unit_replacements: dict[str, list[tuple[int, int, str]]],
    close_replacements: dict[str, list[tuple[int, int, str]]],
) -> dict[str, str]:
    bodies: dict[str, str] = {}
    for scene_id, body in scenes:
        edits = sorted(
            [*unit_replacements[scene_id], *close_replacements[scene_id]],
            key=lambda e: e[0],
            reverse=True,
        )
        if not edits:
            continue
        new_body = body
        for start, end, text in edits:
            new_body = new_body[:start] + text + new_body[end:]
        bodies[scene_id] = new_body
    return bodies


def convert_legacy_mutations(
    scenes: list[tuple[str, str]],
    entity_type: Callable[[str], str | None],
) -> ConversionResult:
    """Convert every legacy inline marker across `scenes` (manuscript order)
    into `mutation_set`s + anchors (ADR-0095 §12 steps 2–5). Pure: no
    filesystem, no `ProjectService`. `entity_type(lore_id) -> type | None`
    supplies each set's `target_entry_type`; a dead pin (`None`) is kept, not
    dropped (§2)."""
    registry = _scan_units_pass(scenes, entity_type)
    close_replacements = _scan_closes_pass(scenes, registry)
    bodies = _apply_edits(scenes, registry.replacements, close_replacements)
    return ConversionResult(bodies=bodies, sets=registry.sets)
