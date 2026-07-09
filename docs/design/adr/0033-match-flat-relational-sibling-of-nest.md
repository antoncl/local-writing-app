# ADR-0033: Match — the flat relational sibling of Nest

- Status: Proposed — 0.7.0, 2026-07-09 (design agreed; implementation pending)
- Feature: #184 Parameterized views — the **reference-traversal** half (what ADR-0031's original §C
  wrongly tried to do inside the field predicate)
- Follows: **ADR-0028** (Nest — relational denormalization from lore links) and **ADR-0031** (the
  two-pipe parameter model; entity parameters ride the node-set pipe)
- Governed by: `memory/decisions_184_entity_vs_value_parameters.md`,
  `memory/decisions_nest_relational_trees.md`

## Context
Nest (ADR-0028) takes a join over a link/reference field between two node-sets and renders it as a
**denormalized hierarchy** — a recursive tree. But a large class of queries wants the *same* join
rendered **flat**, as a set rather than a tree:
- **referenced-by** — "which nodes reference `$self`";
- "scenes where `$character` is POV";
- "characters who are some scene's POV".

ADR-0031's original §C tried to route referenced-by through the **field predicate**
(`field(<ref>, includes, $self)`), which flattened entities into values and hit the
**LHS-override problem**: an extracted `(name, value)` hijacks the filter's field, so it can only
ever express *same-field* matches, not "candidate's `mentions` field points at `$self`". Two
shortcuts were considered and rejected (ADR-0031 rejected-alternatives): a **polymorphic Filter
RHS** (accept a green entity, identity-match) — which mixes value comparison with identity
traversal in one node — and a **mode flag on Nest** (flat-vs-nested output) — the mode-parameter
smell. The honest factoring: the relational match is **one operation with two output shapes**, so
the flat shape gets its **own node**.

## Decision
**Match is Nest's flat sibling.** It shares Nest's configuration and its `by: ref | title`
link-matching core (ADR-0028 §B), and differs only in what it emits:

- **Config (identical to Nest):** a **Parents** node-set input, a **Children** node-set input, and a
  **match rule** — the link `field`, `direction` (`child_to_parent` | `parent_to_children`), `by`
  (`ref` | `title`). Green node-set in, green node-set out.
- **No recursion.** Match has no self-loop; it is a single-level join (there is no hierarchy to
  walk).
- **Flat, deduplicated output.** Run the one-level join exactly as Nest does, then **strip the
  parent/header level and emit the deduplicated leaves** — the matched children. Dedup because a
  child matching several parents would otherwise repeat.

**Which nodes come out is governed by the Parent/Child role assignment + direction** — there is no
separate output selector. The output is *always* the leaf (children) level, so the author chooses
what lands there by assigning it to the **Children** input:
- **referenced-by** — `Parents = $self`, `Children = universe`, `match = {mentions, child_to_parent}`
  → strip `$self`, emit the **referrers**, deduped. *Only the nodes referencing `$self` come out.*
- **"scenes where `$character` is POV"** — `Parents = $character`, `Children = scenes`,
  `match = {pov_ref, child_to_parent}` → the matching **scenes**.
- **"characters who are some scene's POV"** — `Parents = scenes`, `Children = characters`,
  `match = {pov_ref, parent_to_children}` → the referenced **characters**.

**Input-aware match field.** Match — and, as a shared refinement, Nest — gains an **input-aware
match-field dropdown**: it offers the reference/link fields that can actually link the Parents'
kind to the Children's kind, instead of today's flat joinable-fields list.

## Why / rejected alternatives
- **A mode flag on Nest (flat vs nested) — rejected.** One node whose output shape is a hidden
  toggle is the mode-parameter smell. Two named nodes — **Nest** (tree) and **Match** (flat), each a
  single purpose — is the honest refactor; they share the match core in implementation without a
  runtime flag.
- **A polymorphic Filter RHS (an entity into the value slot) — rejected (ADR-0031 §C).** Mixes value
  comparison with identity traversal and reintroduces the LHS-override problem. Keeping Match
  separate lets **Filter stay value-only** and **Nest stay tree-only**.
- **A backend reverse-link endpoint — rejected.** Evaluation is frontend-side (ADR-0025), and
  backend-computed derived lists were already rejected (ADR-0031). Match is a frontend graph
  operator.
- **Emitting both sides, or the nested tree — rejected.** The nested tree *is* Nest. Match exists
  precisely for the flat, header-stripped, deduped set.

## Consequences
- **A new designer node, "Match"** (verb, alongside Filter/Nest), reusing Nest's match-rule UI and
  its `buildNestAdjacency` link core (ADR-0028 §B). Output is a flat green node-set.
- **Filter stays value-only (`{field,value}` RHS); Nest stays tree-only.** Reference-traversal-flat
  lives in Match — which is what lets ADR-0031 keep the Filter RHS unpolymorphic and drop the
  value-only `field_of` mode.
- **Nest's match-field dropdown becomes input-aware** (shared refinement).
- **referenced-by, POV-by-entity, and reverse membership fold into the view system** as Match nodes
  fed by entity parameters (ADR-0031/0032) — collapsing another derived-list escape hatch, the same
  way parameterization does for value filters.
- **The clean partition** the two pipes enforce: *scalar value comparison → Filter + `field_of`
  (`{field,value}` pipe); reference / identity traversal → Match, flat / Nest, nested (node-set
  pipe).* The wire type tells you which mechanism you're in.
- **Guards** (cf. ADR-0028 §D): with no recursion there is no unbounded walk; output is bounded by
  `|Children|` after dedup, so Nest's cycle/termination/fan-out guards mostly fall away.
- **Out of scope:** `MutationTimeline`'s non-roster data source; any deeper unification of the
  flat/nested pair beyond "two sibling nodes."
