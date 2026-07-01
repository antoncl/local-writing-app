# ADR-0004: Every field is mutable — no `mutable` flag

- Status: Accepted — 0.4.0 planning, 2026-07-01
- Feature: #33 mid-scene lore mutations · Doc: `docs/design/mid-scene-lore-mutations.md` §3.1

## Decision
Drop the v1 draft's `mutable: bool` on `MetadataFieldDefinition`. **Every field is mutable.** The
`/mutate` autocomplete listing all of an entity's fields is the discovery surface — no schema
declaration step. Base state = open-ended records at book-start.

## Why / rejected alternative
The rejected design gated mutations behind a per-field `mutable: true` flag set in the schema.
Requiring a schema edit *before* you can record a change is a context-switch out of creative flow
into project admin — friction at exactly the moment of writing, so it would not get used. Almost
no field ever gets a mutation; making them all *capable* costs nothing and keeps the model uniform
(no special declaration), consistent with the node model.

## Consequences
- Because *any* field can carry mutations, the resolver must cover **every** lore-field injection
  site — including the **implicit-context** path (auto-injected entities), not just explicit lore.
  Handled by the single formatter seam (ADR-0006).
- Additive combine is **field-type-gated with a per-mutation toggle**: where accumulation is
  meaningless (e.g. boolean) it's replace-only; where it makes sense the writer toggles replace vs.
  add per mutation.
- No schema migration and no `mutable`-flag validation to build.
