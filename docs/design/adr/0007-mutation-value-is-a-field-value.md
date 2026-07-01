# ADR-0007: A mutation value is a field value — validated

- Status: Accepted — 0.4.0 planning, 2026-07-01
- Feature: #33 mid-scene lore mutations · Doc: `docs/design/mid-scene-lore-mutations.md` §3.4

## Decision
A mutation's value is validated exactly as a base field value is, through
`_validate_metadata_field_value()` (`services/project/metadata_values.py`): a `select` value must
be in options, an `entity_ref` must point to a real entity, a number must parse, and so on.
Wire it in at:
- **`save_scene()`** (`services/project/manuscript.py`) — the marker scan that builds the index
  validates each value before persisting; a bad value is rejected/flagged like any invalid metadata.
- **`validate_project()`** (`services/project/lifecycle.py`) — a scene-mutation scan loop so
  project-wide validation covers markers.

## Why
A `/mutate rank = "Captain"` *sets a field value*. An unvalidated mutation could inject an invalid
value into AI context and break resolution silently (e.g. a `select` value not in the option set, a
dangling `entity_ref`). Validation already exists for base values; mutation values are the same
kind of thing and must pass the same check.

## Consequences
- The index-building scan does double duty: build + validate (one walk).
- No new validator — reuse the existing field-type validation path.
