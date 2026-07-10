# ADR-0033: Match — the flat relational sibling of Nest — WITHDRAWN

- Status: **Withdrawn 2026-07-09** — superseded by ADR-0031's forward model. Match is not needed and
  will not be built. This record is kept because *why an operator was rejected* is the load-bearing
  part of an ADR. See `memory/decisions_184_entity_vs_value_parameters.md`.
- Feature: #184 Parameterized views — the reference-traversal half (originally)
- Superseded by: **ADR-0031** (forward `Filter` predication + `field_of` projection)

## What it proposed
Match was to be Nest's **flat** sibling: the same `by: ref | title` link core (ADR-0028), a
**Parents** and **Children** node-set input and a match rule, but **no recursion** and a **flat,
header-stripped, deduplicated** output — a semi-join returning the matched children. It was meant to
own referenced-by, "scenes where `$character` is POV", and "characters who are some scene's POV",
so that Filter could stay value-only and Nest tree-only.

## Why it is withdrawn
Match existed to give reference traversal a **flat output**. Under the forward model (ADR-0031) that
need never arises:

- **Reverse queries are still forward.** "Characters who are the POV of some draft scene" starts
  from the scenes (which carry `pov`) and **projects** — `field_of(draftScenes, pov)` → characters.
  No join.
- **Forward predication keeps the subject.** "Scenes where `$character` is POV" is
  `Filter(scenes, pov ∈ {$character})` — the scenes never leave, so there is nothing to *recover*
  with a join. Match looked mandatory only because one first *projected* (`field_of(scenes, pov)` →
  characters) and then needed the scenes back.
- **Any-field referenced-by is a computed field, not an operator** — the `'References'` node-set
  field (ADR-0031 §G), backed by the reverse index.
- **Flat-vs-tree is presentation, not grammar.** ADR-0027/#181 made this a `treePresentation`
  concern in the normalizer. A distinct grammar node whose only difference from Nest is flat-vs-tree
  output re-litigates a decision the render pipeline already settled, and re-introduces a near-clone
  of Nest.

So reference matching needs **no dedicated operator**: forward `Filter` (predicate), `field_of`
(project), the `'References'` computed field (any-field referenced-by), and Nest (still the *only*
recursive/tree denormalizer). The "clean partition" Match was meant to enforce holds without it.

## What survived into ADR-0031
- The **input-aware match-field dropdown** (offer only fields that can link the input's kind) —
  generalized as ADR-0031 §F, *field selectors = intersection of fields over the input set*.
- The recognition that **Filter stays value/field-typed and Nest stays tree-only** — achieved by the
  forward model, without a third node.
