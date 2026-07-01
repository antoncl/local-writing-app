# ADR-0011: Transformation sets are a first-class Node kind

- Status: Accepted (v1.1) — 0.4.0, 2026-07-01
- Feature: #33 mid-scene lore mutations · Doc: `mid-scene-lore-mutations-v1.1.md` §5 · Issue: #62
- Governed by: `memory/architecture_class_instance_model.md`, `docs/metadata-strategy.md`

## Decision
A **transformation set** — a reusable, named bundle of field mutations re-applied to a chosen entity
in one gesture (the recurring werewolf transform) — is modeled as a **new top-level Node kind**
(`transformation`, working slug), not a sub-type of an existing kind and not an ad-hoc list in
`project.yaml`.

Shape: an **ordered list of `(field, op, value)` rows** + a target lore **entry-type**; no prose
body. The **entity is bound at apply time** (not stored), so one set applies to any entity of its
target type. Applying **expands the set into N independent inline Model-A markers** at the cursor
(co-authored group label so they can close together) — after expansion they are ordinary,
individually-editable markers. It is a **stamp, not a linked mutation** (single-point-edit stays out
of scope).

## Why / rejected alternative
Checked against the snippet lesson (a kind introduced for a mere affordance difference, later ripped
out): a new kind is justified only when **storage shape genuinely differs** *and* a **new routing
surface** is needed. A transformation set clears both — its `(field, op, value)`-rows shape matches
no existing kind's storage, and it needs its own list pane + editor. It is not an AI invocation
(≠ `prompt`) nor a world fact (≠ `lore`), so no sub-type fits.

Rejected a `project.yaml` list: exactly the "don't model a first-class thing as an ad-hoc store"
trap; it wouldn't get the NodeList/NodeEditor surfaces or layered-schema behavior for free.

## Consequences
- Adding the slug touches the kind whitelist in `_validate_metadata_schema_definition` — **re-read
  `docs/metadata-strategy.md` § Class–instance model & § Invariants first** (per the memo).
- The set reduces to standard widgets: NodeList + NodeEditor; rows reuse the `/mutate` field picker
  and `FieldValueEditor`. It gets its own list pane (the browse/curate home) for free by being a kind.
- Two authoring paths: a **"reusable?" checkbox** promotes an in-flow `/mutate` authoring into a set,
  or author directly in the pane. Application is a **type-scoped picker** in `/mutate` (sets filtered
  to the chosen entity's entry-type); expansion reuses the plural-marker insertion path and defaults
  the group name to the set title (ADR-0015). See doc §5.3.
- **Stamp, three edit surfaces:** the inline pill edits an applied *occurrence*; the lore-card list is
  read-only/navigate; the Transformations pane edits the *template* (future applications only).
  Edit-once-propagate-to-all is the deferred v2 linked mutation (#66) — it would break scene
  self-authority (ADR-0001), so it is not admitted through these paths.
