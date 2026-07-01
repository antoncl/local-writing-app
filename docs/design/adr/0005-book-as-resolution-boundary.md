# ADR-0005: Book as the resolution boundary

- Status: Accepted — 0.4.0 planning, 2026-07-01
- Feature: #33 mid-scene lore mutations · Doc: `docs/design/mid-scene-lore-mutations.md` §2, §8

## Decision
The **book** is the resolution boundary. Cumulative resolution starts from the lore file's
base state at book-start. `project.md starting_state` (book_start_overrides) is **deferred**;
**cross-book** mutation walking is **out of scope**.

## Why / rejected alternative
The rejected option resolves across the nested project hierarchy (universe → series → book) in v1,
walking mutations and start-state overrides from ancestors. A standalone book with no ancestors
needs no `starting_state`, and cross-book walking adds a resolution layer and test surface with no
v1 payoff. Keeping the boundary at the book keeps v1 focused on the common case.

## Consequences
- Base state for resolution = the lore file at book-start.
- When nested-project `starting_state` lands later, it slots in as an additional resolution layer
  *below* mutations (base → book_start_overrides → mutations), not a rework of the resolver.
