# ADR-0009: Collection mutations use add/remove; effective_state returns typed lists

- Status: Accepted (v1.1) — 0.4.0, 2026-07-01
- Feature: #33 mid-scene lore mutations · Doc: `mid-scene-lore-mutations-v1.1.md` §1 · Issue: #58
- Refines: ADR-0002 (combine rule), ADR-0006 (contract), ADR-0007 (validation)

## Decision
Collection fields (`multi_select`, `tags`, `entity_ref_list` — the only three) get **two**
value-carrying interval operators, gated by field type; every other type stays replace-only:

- `op=add` — union an item into the collection;
- `op=remove` — drop an item from the collection, **including a value provided by base** (which has
  no record to close, so remove is not redundant with close/ADR-0010).

Each add/remove marker carries **one** element. Effective collection at `(scene, pos)`:
```
(base_set ∪ {live add records}) ∖ {live remove records}
```
set semantics, deduped; **remove wins** when a value is concurrently added and removed (redaction
bias). Scalars keep "latest-started live replace wins."

`effective_state()`'s contract widens from `dict[str, str]` to **`dict[str, str | list[str]]`** —
a resolved collection is a real list, so the datatype matches the field rather than a stringified
encoding.

## Why / rejected alternative
Rejected keeping `dict[str, str]` and JSON-string-encoding collections: it re-imports the
string-typing ambiguity the v1.0 review fought (values that *look* scalar but aren't). Typing the
value correctly **at the source** is cleaner and keeps the `Boolean("false")` bug fixed for free
(booleans remain scalars/strings, coerced at the boundary). Both consumers already type-normalize
(`_coerce_mutation_value`; `FieldValueEditor.normaliseFieldValue`), so the ripple is small.

Rejected "add only": can't retract a base-provided collection value; remove is its sibling, not a
duplicate of interval-close.

## Consequences
- The `/mutate` form shows an op selector only for the three collection types.
- Add/remove markers are ordinary intervals — closeable (ADR-0010) and validated per-element
  (ADR-0007).
- Callers reading `effective_state` must handle `list` values for collection fields.
