# ADR-0031: Parameterized views — free variables, forward projection/predication, and field-set-typed selectors

- Status: Accepted — 0.7.0, **rewritten 2026-07-09 (forward model)**; accepted 2026-07-10 (5 context-blind gates). This supersedes the
  two-pipe/Match revision made earlier the same day. What died is the **symmetric two-parameter-
  family** framing and **id-in-`field_of` matching** — *not* the existence of two edge payloads:
  edges still carry **node-sets** (the general flow) and **value-sets** (from scalar `field_of`),
  because a field's value is a node or a scalar. `field_of` is a **forward projection** whose output
  follows the field (reference → nodes, scalar → values); reference matching is ordinary **forward
  `Filter` predication** or **`field_of` projection**; and **Match (ADR-0033) is withdrawn** as
  unnecessary. See `memory/decisions_184_entity_vs_value_parameters.md`.
- Feature: #184 Parameterized views · Doc: `views-and-filters.md` (parameterization)
- Part of the render-pipeline trio: ADR-0027/#181 (producer — canonical `ViewResult`) ·
  **this / #184** (membership-side — parameterization) · #182 (consumer — canonical render wrapper)
- Amends: ADR-0025 (the evaluator gains a **bindings environment** injected at eval time),
  ADR-0018/0027 (the grammar gains a **variable operand** in a Filter's value slot and a
  **`field_of` projection** operator), **ADR-0020** (kind-anchoring generalized: a node's field
  selector derives from **its input set**, not one view-level anchor), builds on ADR-0023
- Depends on: **ADR-0034** (full-field roster) — the forward model presupposes every node's complete
  field set is present in the evaluated roster
- Withdraws: **ADR-0033** (Match) — see §C and "Why"
- Governed by: `memory/decisions_author_vs_runtime_authority.md`,
  `memory/decisions_view_render_pipeline_ownership.md`, `memory/decisions_metadata_revision.md`

## Context
Every ViewExpr predicate today takes a **literal** operand baked into the stored spec
(`views-and-filters.md` §1.4). So *"scenes where character X is the POV"* or *"nodes that reference **this** node"* cannot
be a static saved view — the identity (`X`, `this node`) lives in the **environment around the
list**, not the spec. Lacking a channel to inject that identity, these lists are hand-rolled
*outside* the view system (`BacklinksPanel`, `MutationTimeline`, ad-hoc POV filters). That is the
reason **"derived lists"** exist as an escape hatch.

Parameterized views make **"every list is governed by a view"** (the #182 premise) true. The
evaluator already injects runtime capability through `EvalContext` (`schema`, `resolveView` —
ADR-0025); a **bindings environment** is the same seam, one member further.

An earlier revision routed this through a *symmetric two-parameter-family* scheme (an entity-param
pipe and a value-param pipe, plus id-in-`field_of`) and a dedicated reverse-join node (Match,
ADR-0033). That *symmetric* machinery dissolves once one observation is taken seriously: **you always
operate from the side of a relationship that carries the linking field.** Everything below follows
from that. (Two edge *payloads* — node-sets and value-sets — do remain, because a field's value is a
node or a scalar; that is not the rejected symmetry. See §D.)

## Decision

**A. Authoring vs runtime — the field is authored, only the value is free.**
*Which* field a view filters or projects on, and the `nest` rule, are **authoring** decisions frozen
into the spec. A free variable **never selects the field** — it supplies only a **value** (or a
**node**, via a wired source). `$self` (the node a pane is anchored to) is a **reserved** parameter
the surface supplies; other parameters are user-declared. This is
[[decisions-author-vs-runtime-authority]].

**B. Free variables + a bindings environment.**
A `ViewSpec` may carry **parameter declarations** and evaluation takes a **bindings environment**
(`EvalContext.bindings`: name → value), injected exactly as `resolveView` is. A view with **no**
free variables is the **degenerate closed case** (empty bindings) — existing views are unchanged.
An **unbound** variable degrades gracefully **by role**: an unbound **filter operand** makes its
predicate **inactive** (no constraint), while an **unresolved source** (`$self` in a pane with no
anchor) contributes the **empty set**. A promoted formal is normally **seeded by its authored default**
(ADR-0032), so "unbound" arises only when no default is set.

An inactive predicate is the **identity element of its immediately enclosing combinator**, not a fixed
value — so "no constraint" means *show everything* in every position, uniformly across keep, drop,
complement, and union. The evaluator resets a per-position flag for each combinator to its own identity
(`∩` → universe, `∪` → ∅, `difference.keep` → universe / `remove` → ∅, `complement` → ∅), rather than
propagating a keep/subtract sign from the root — a global sign is wrong for an inactive predicate nested
inside a combinator that itself sits in a subtractive position (`A − (X ∩ inactive)` must give `A − X`,
not `A`). This is the structural realization of "unset = show everything." (See `views-and-filters.md`
§14.2.)

**C. The forward model — predicate or project, always from the field-carrying side.**
Given a field `F` linking node-sets X and Y, you start from the side that **carries `F`** and do one
of two things:
- **Predicate it — `Filter`** — keep the subset of that same side whose `F` matches an operand.
  The subject never leaves. (`Filter(scenes, pov ∈ {Alice, Bob})` → scenes.)
- **Project it — `field_of`** — cross to the other side / to the values.
  (`field_of(scenes, pov)` → the POV characters.)

This is the whole reference-query surface. The apparent need for a reverse **join** (Match) came
from *projecting first* (`field_of(scenes, pov)` → characters) and then trying to recover the
scenes — which forces a join. **Predication never projects, so it never needs to recover the
subject.** A genuinely reverse query ("which characters are the POV of some draft scene") is *still
forward* — you start from the scenes (which carry `pov`) and **project** to characters. You are
forced to a reverse join only when you hold one entity and cannot enumerate the candidate side; with
a full-field roster (ADR-0034) you always can, so **Match is unnecessary** (see §G for the one
residual, any-field referenced-by).

**D. `field_of` — forward projection; output kind follows the projected field.**
`field_of(nodeSet, F)` = `flatMap(nodeSet, n → valuesOf(n, F))`, **deduplicated**. Its **output type
is statically known** from `F`:
- `F` a **reference** field → the **referenced nodes** (a node-set). `field_of(scenes, pov)` →
  characters. This output feeds set algebra, the render wrapper, or a Filter operand.
- `F` a **value** field → the **values** (e.g. the set of statuses in use). This feeds a Filter
  operand for a same-field comparison ("scenes with the same status as this one").

`field_of($self, pov)` is the N=1 case; `field_of(All, pov)` yields `pov`'s distinct **projections**
across the roster — for a reference field the distinct referenced **nodes**, for a scalar field the
distinct **values** — deduped, so the output is bounded by the field's distinct projections, not
roster size (no fan-out to guard).

The **two outputs are two edge payloads**, but they never contend for one port (§E): a Filter's
single value slot accepts *whichever payload its authored field's type calls for*. A reference
projection is a **node-set** and joins the general flow — set algebra, the value slot of a Filter
**authored on an `entity_ref` field**, or (in a later increment) another `field_of` (**multi-hop** —
the 0.7.0 cut is **single-hop**; see Consequences). A scalar projection is a **value-set**
and joins **only** the value slot of a Filter **authored on a scalar field**, for same-field /
same-value comparison. This is what expresses *"nodes sharing `$self`'s tags"* and *"a reference
tree built by shared tag"* (the value-matching Nest already ships as `by: title`, generalized). Two
payloads are inherent to the field-value duality — not the rejected symmetric ceremony.

**E. `Filter` — forward predication; ONE value slot, typed by the authored field.**
A Filter has **exactly one value slot** — never an entity slot *and* a value slot. Which payload that
slot accepts is **fixed by the authored field's type** (monomorphic per field), and the slot renders
the field's own editor (this ships today — `FieldValueEditor`: `ReferencePicker` for `entity_ref`, an
option list for `select`, …):

| Authored field type | The one value slot accepts | Compared by |
|---|---|---|
| `entity_ref` / `entity_ref_list` | a **node-set** | id overlap |
| scalar (`select` / `text` / `number` / `tags` / …) | a **value-set** | value overlap |

So a Filter authored on `pov_ref` exposes a node-set slot; one authored on `status` exposes a
value-set slot; the slot is never *both*, and its payload type is known statically at authoring time.
An `entity_ref` field is thus compared by its **stored id** against the operand's id(s) — forward and
correct: the field is on the candidate, node identity *is* id equality, and no id is extracted or
reified (the subject stays a scene).

That one slot may be filled three **mutually-exclusive** ways (ADR-0032): an **inline literal**, a
**promoted formal** (a runtime strip control), or a **wired source** (`$self`, a `field_of` output,
set-algebra). A wired source occupies the slot as a graph edge into the port; a literal or a formal
is an in-slot **tagged operand**; the three cannot co-occupy one slot. The serialized operand tag +
new-node grammar live in the parameterization spec (`views-and-filters.md`).

**Cardinality — both sides are sets; the predicate is overlap.** Because edges carry sets and
projection emits value-*sets*, the honest semantics is **coerce both sides to sets and test
overlap**:

| LHS \ RHS | scalar | set |
|---|---|---|
| **single** (e.g. `status`, `pov`) | `==` | **`∈`** — `status ∈ {draft, revised}`, `pov ∈ {Alice, Bob}` |
| **list** (e.g. `tags`) | `includes` | **intersection ≠ ∅** |

One rule, not four. A **single-valued field filters against a *set* of allowed values** with **no
storage change** (a scene still holds one `status`; only the set of *acceptable* values grows) — this
is what expresses "Bob **or** Alice" and "draft **or** revised". Consequently the `op` enum
**collapses 6→4**: `eq`+`includes` → **`overlap`**, `neq`+`not_includes` → **`disjoint`**,
`set`/`unset` kept. This edits the `op` enum in `models_views.py` and the frontend
`ViewFieldPredicate.op` type. Per the project **no-pre-1.0-migrations** rule, stored views carrying
old `eq`/`neq`/`includes`/`not_includes` values are **not migrated** — test projects are recreated
([[feedback-no-pre-1-0-migrations]]).

**F. Field selectors = the intersection of fields over the input set.**
A node's field dropdown (on `Filter` and `field_of`) offers **the fields present on every member of
its actual input set** — not a single view-level anchor kind (generalizing ADR-0020). The common
cases:
- a **subtype family** (`character` + `protagonist`, ADR-0026 `is_a`) → the base type's fields (every
  specialization carries at least those) — the specialization of the intersection rule;
- **shared field-groups across unrelated kinds** → whatever fields they genuinely share (sharing is
  not only vertical);
- a **cross-kind** set with nothing in common → down to intrinsics (`id`/`title`/`entry_type`), with
  an authoring **warning** when the offered set is thin.

The input set's type is derivable statically (leaf kind → `Filter` preserves it → `field_of` remaps
to `F`'s target). The **runtime evaluator is unchanged** — it still reads fields structurally; this
is authoring-time type inference for populating dropdowns and validating.

**G. Referenced-by = the `references` computed field (ADR-0029), not an operator.**
"Nodes referencing `$self` via *any* field" is a disjunction over an unknown set of reference fields
— awkward to author as one Filter. It is served by the **backlinks computed field ADR-0029 already
catalogs** — *"backlinks **when surfaced**"* ([[decisions-intrinsic-fields-and-overrides]], ADR-0029)
— which **#184 is what surfaces** (stable key `references`, label "References"; spec'd in
`views-and-filters.md` §14.4). As a catalog computed field it is added/removed per type,
**reorderable and hideable via `field_overrides` like any field** (this realizes #118 pt 3 "References
editable-or-removable in the schema editor"; the broader bidirectional-display design is GH #15), its
definition built-in. The one aspect ADR-0029 left implicit — its **value is a node-set**, not a
scalar like `word_count`/`cost` — is made explicit here: `field_of($self, references)` → the
referrers (a node-set). Materialized by inverting the forward reference adjacency the **backend
supplies at load** (`views-and-filters.md` §14.4; the same in-memory inversion Nest does) — a
**data-model convenience backed by a reverse index, not a graph operator.** Field-*specific* referenced-by ("scenes where Bob is POV") is just
forward `Filter(scenes, pov ∈ {Bob})`.

**H. Field-type applicability.**
- **text · number · single-ref · single-select** — scalar, projectable, `∈`/`==`.
- **tags · multi-ref · multi-select** — multi-valued → value-sets, intersection semantics.
- **select / enum** — projects the **stored key**, never the label (else a label compares against
  another node's key and never matches) — [[decisions-metadata-revision]] stable-key rule.
- **`long_text`** — excluded, presence-only (`set`/`unset`): freeform prose has no stable identity.
- **computed numerics** (`word_count`, `cost`) want ordering ops (`>`/`<`) the grammar lacks — a
  **noted gap**.

**I. Universe & complement — kind-relative, against the roster.**
`All` is the **view's roster** (the `EvalNode[]` the pane supplies, ADR-0034) — *not* "all nodes of
one kind." **Complement** (the only universe-dependent op) is **kind-relative**:
`complement(S) = { n ∈ All : kind(n) ∈ kinds(S) } − S`. ADR-0020's "all nodes of that kind" is this in
the single-kind special case. It is well-defined only when `S` is **kind-homogeneous** — e.g.
*"characters who are the POV of no scene"* = `All(characters) − field_of(scenes, pov)` (both sides
characters). **Complementing a heterogeneous (cross-kind) set has no coherent universe → out of scope
for 0.7.0** (a validation error), on the same typed-pipe frontier as multi-hop. This makes the
**roster-completeness** requirement load-bearing: the roster must be **complete within every kind the
view references** (ADR-0034) — otherwise a kind-relative complement silently under-counts.

## Why / rejected alternatives
- **Match / a dedicated reverse-join operator (ADR-0033) — withdrawn.** It was introduced to give
  reference traversal a *flat* output. Forward **predication** keeps the subject (no join to recover
  it) and forward **projection** (`field_of`) yields the other side directly; the only residual —
  any-field referenced-by — is the `'References'` computed field (§G). Match adds no expressive
  power. Keeping it would re-introduce a near-clone of Nest and re-litigate flat-vs-tree, which
  ADR-0027/#181 already made a **presentation** concern (`treePresentation`), not a grammar one.
- **The symmetric two-parameter-family framing (entity-param pipe vs value-param pipe, both feeding
  filters) — rejected.** The Filter's value operand is **one** slot, field-typed (`ReferencePicker`
  for `entity_ref`, select for `select`), fed by a literal, a promoted formal, or a wired payload of
  the matching type. There is no "entity pipe vs value pipe" to reconcile *at the Filter*; the
  "polymorphic RHS" objection dissolves because the slot's type is fixed by the **authored** field
  (monomorphic per field), not chosen at runtime. (This is distinct from the two *edge payloads*,
  §D — those are real and inherent; what is rejected is the symmetric *parameter-family* ceremony.)
- **`field_of` always emits `{field,value}`, and id-in-`field_of` matching — rejected.** That
  demoted a reference to its id and forced hand-rolled identity matching. `field_of` **projects**;
  on a reference field it yields **nodes**. Forward predication never extracts an id to match.
- **A `direction` parameter on `field_of` — rejected.** Forward-only over a full-field roster
  (ADR-0034) removes the need to traverse a forward field in reverse; reverse membership is either a
  forward `Filter` on the candidate side or the `'References'` field.
- **Sigil string `"$self"` as the operand — rejected.** Stringly-typed; the grammar discriminates by
  tagged slots everywhere else. A tagged variable operand is the house style.
- **Backend-computed derived lists as their permanent home — rejected.** Contradicts ADR-0025
  (frontend eval). Synthetic parameterized views are frontend-constructed and never persisted until
  a user *saves* one (the configurator slice, ADR-0032).

## Consequences
- **The grammar grows two things**: a **variable operand** in a Filter's value slot, and the
  **`field_of` projection** operator (node-set → nodes or values, `flatMap` + dedup). The evaluator
  gains a **bindings environment** (amends ADR-0025) and **set-coerced overlap** in `matchesField`;
  the `op` enum shrinks **6→4**. Runtime remains field-structural.
- **Field selectors become input-set-derived** (§F, generalizing ADR-0020): authoring-time type
  inference offers the **intersection of fields over the input set**; cross-kind degrades gracefully
  with a warning.
- **Requires a full-field roster (ADR-0034).** The forward model can only predicate/project on
  fields present in the evaluated roster; the thin manuscript-structure projection is insufficient.
- **`'References'` is a computed node-set field** (§G) backed by a frontend reverse index — not an
  operator.
- **Match, the *symmetric two-parameter-family* ceremony, `field_of` direction, and id-matching are
  removed.** Edges still carry **two honest payloads** — node-sets (general flow) and value-sets
  (scalar `field_of` → a Filter's value operand) — an inherent consequence of the field-value
  duality, not the rejected ceremony.
- **Derived lists fold in**: `BacklinksPanel` = `field_of($self, 'References')`; POV/status = forward
  Filters bound via the parameter strip — synthetic views, collapsing the escape hatch.
- **Multi-hop** (`field_of → field_of`, e.g. House→characters→scenes) works under §F applied to
  `field_of`'s **inferred** output, via per-node type inference. **0.7.0 cut = single-hop**
  (`field_of` output → a terminal / set algebra / a Filter operand — not into another type-aware
  node's primary input); multi-hop (per-node inference) is the first forward-compatible increment;
  **heterogeneous self-render / flow composition = Views 2.0**
  ([[decisions-views-2-0-flow-model]]).
- **Existing closed views are byte-identical** (empty bindings). **`models_views.py`** gains no
  *parameter-list* fields for *synthetic* (frontend-only) views; the `op`-enum edit above is the one
  separate backend change. A **saved** parameterized view persists its parameter list (ADR-0032).
- **Out of scope**: the configurator/persistence (ADR-0032); multi-hop inference; `MutationTimeline`'s
  non-roster source.
