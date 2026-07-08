# ADR-0031: Parameterized views — free variables, a bindings environment, and the field-extraction node

- Status: Proposed — 0.7.0, 2026-07-08 (design agreed; implementation pending)
- Feature: #184 Parameterized views · Doc: `views-and-filters.md` (parameterization)
- Part of the render-pipeline trio: ADR-0027/#181 (producer — canonical `ViewResult`) ·
  **this / #184** (membership-side — parameterization) · #182 (consumer — canonical render wrapper)
- Amends: ADR-0025 (the frontend evaluator gains a **bindings environment** injected at eval
  time, alongside `schema`/`resolveView`), ADR-0018/0027 (the grammar gains a **variable operand
  form** in the predicate value slot and a **field-extraction operator**), builds on ADR-0023
  (typed param declarations feed the picker)
- Governed by: `memory/decisions_author_vs_runtime_authority.md`,
  `memory/decisions_view_render_pipeline_ownership.md`,
  `memory/decisions_metadata_revision.md` (stable-key-vs-display-name)

## Context
Every ViewExpr leaf/predicate today takes **literal** operands baked into the stored spec — a
field predicate's right-hand side is a value the designer picks from a dropdown (ADR-0018 §1.4).
So a view like *"scenes where character X is the POV"* or *"nodes that reference **this** node"*
**cannot be a static saved spec**: the identity (`X`, `this node`) lives in the **environment
around the list**, not the stored view. The evaluator has no channel to inject that identity, so
these lists are hand-rolled *outside* the view system today — `BacklinksPanel`,
`MutationTimeline`, ad-hoc POV filters. That is the reason **"derived lists"** exist as an escape
hatch.

Parameterized views are what make **"every list is governed by a view"** — the premise of #182 —
true instead of a slogan: `BacklinksPanel = references(target=$self)`,
`MutationTimeline = mutations(target=$self)`, POV `= pov == $povCharacter`. The evaluator already
injects runtime capabilities through `EvalContext` (`schema` for `descendants_of`, `resolveView`
for `view_ref` — ADR-0025); a **bindings environment** is the same seam, one member further.

## Decision

**A. Authoring vs runtime — the field is authored, only the value is free.**
*Which* field or tag a view filters on is an **authoring** decision, frozen into the spec (the
predicate `key`, the `nest` match rule). A free variable **never selects the field** — it only
fills a **value** slot. Choosing to filter on `pov` rather than `status`, or which tag to match,
is the author building that predicate; nothing at runtime re-decides it. `$self` (the node the
pane/editor is anchored to) is a **reserved implicit parameter** the surface supplies; other
parameters are **user-declared** with a type. This is [[decisions-author-vs-runtime-authority]]:
capability on the author, per-use value on the runtime user.

**B. Free variables + a bindings environment.**
A `ViewSpec` may carry **parameter declarations** `{ name, type, label }`, where `type` is an
`entity_ref` constraint so a configurator/picker can offer the right values (ADR-0023).
Evaluation takes a **bindings environment** (`EvalContext.bindings`: param name → value),
injected at eval time exactly as `resolveView` is. A saved view with **no** free variables is the
**degenerate closed case** (empty bindings) — nothing changes for existing views. An
**unresolved** variable degrades gracefully (its predicate contributes no match), mirroring an
unresolved `view_ref` contributing the empty set.

**C. A variable supplies the predicate RHS — no new grammar position.**
The field-predicate `value` slot — today a literal from a dropdown — may instead be a **bound
variable**. Same slot, variable source. In the designer this is a **parameter handle at the top
of each filter node** (a visually distinct color/shape); an edge from a **Parameter** node into
that handle **overrides/replaces the dropdown**. This one move expresses both motivating cases:
- **referenced-by** = `field(<ref field>, includes, $self)` with no groups — the view degenerates
  to the **unfiltered universe of nodes that reference `$self`**;
- **POV filter** = `field(pov, eq, $povCharacter)`.

The graph now carries **two wire types**: the existing **node-set** edges (set-algebra flow) and
**value/binding** edges (Parameter → handle, and extraction → RHS, §D). They carry different
payloads and **cannot cross-connect** — a value-set can't feed `union`/`intersect`. So value edges
**render visually distinct** from node-set edges (as the Parameter node itself is distinct), and
that distinction *is* the type discipline made visible. A value-set may not land on a node-set
input, and a node-set may not land on a value handle — the type is the connection rule.

**D. The field-extraction node — the one genuinely new operator.**
Given a source of nodes, project one of their fields. Because an edge carries a **node-set**, not
one entity (§E), extraction is a **map**, not a projection: `flatMap(inputSet, n → valuesOf(n, F))`,
**deduplicated**, emitting a **coupled `(name, valueSet)`** — `name` is the chosen field (singular),
the values are a set. `field_of($self, "pov_ref")` is the N=1 case (`$self` a singleton); a
multi-node input (e.g. `All`, §E) yields the field's distinct values across the set. A
**dropdown on the node selects the field** `F`. Wiring a coupled `(name, value)` into a filter
**overrides both** the filter's field dropdown (via `name`) *and* its value handle (via `value`) —
symmetric with §C, no redundancy — which is exactly a **same-field match** ("scenes sharing
`$self`'s `pov_ref`"). A value-only wire (a bare Parameter, §C) overrides only the value; the
filter's own field dropdown then names the LHS — which the **referenced-by** case genuinely needs,
because that LHS is a field of the *target* nodes that no upstream node provides. So the dropdown is
the **inline default, overridden by a wired `name`** — never the sole path. (A wired `name` is only
meaningful when the target kind *has* that field — a validation **warning**, not a hard block.)
Name and value stay **coupled** (see rejected: split).

**E. Cardinality — both sides are sets; predicate semantics is overlap.**
Because every edge carries a node-set, and extraction (§D) emits a value-*set*, the predicate RHS
is **generally a set**, and the honest semantics is **coerce both sides to sets and test overlap**:

| LHS \ RHS | scalar | set |
|---|---|---|
| **single** (e.g. `status`) | `==` | **`∈`** — `status ∈ {draft, todo}` |
| **list** (e.g. `tags`) | `includes` | **intersection ≠ ∅** — "tagged like `$self`" |

This is one rule, not four. It has two immediate payoffs:
- **A single-select filters against a *set* of allowed values** — "status is draft **or** todo" is a
  multi-pick on the value dropdown yielding `{draft, todo}`, tested by `∈`. No union-of-`eq`
  boilerplate, and **no storage change** — a scene still holds one `status`; only the set of
  *acceptable* values grows.
- **Extraction of a multi-valued field just flows in as a set** — no special-casing. `matchesField`
  already `asArray`s the LHS; the change is to `asArray` the RHS too and test intersection.
- **Connecting `All` to extraction is safe and well-defined** — `flatMap` + dedup means the output
  is bounded by the field's *distinct values* (e.g. the set of statuses in use), not by universe
  size, so there is no Nest-style fan-out to guard.

Since cardinality now drives the match, the op vocabulary **collapses** (decided 2026-07-08):
`eq`+`includes` become one positive **overlap** op, `neq`+`not_includes` its negation **disjoint**,
`set`/`unset` kept — the six-value `op` enum ([`types.ts`] `ViewFieldPredicate.op`) shrinks to four.
The scalar-vs-list distinction those pairs encoded is now handled by set-coercion, not op choice, so
keeping them apart is a distinction without a difference. (Op *names* `overlap`/`disjoint` are a
trivial follow-up; the decision is the merge.)

**F. Field-type applicability — not every type is joinable.**
- **text · number · single-ref · single-select** — scalar, extractable, `∈`/`==`. The easy case,
  covers most `$self`-style derived lists on day one.
- **tags · multi-ref · multi-select** — multi-valued → value-sets, intersection semantics (§E).
- **select / enum (key/label duality).** A select **stores a key** but **shows a label**. Extraction
  must project the **stored key** — projecting the display string would compare a label against
  another node's key and never match. The extraction node is **schema-aware for enum fields**
  (yields the key); the override handle is already key-based, so it round-trips. This is
  [[decisions-metadata-revision]]'s stable-key-vs-display-name rule resurfacing.
- **`long_text` — excluded, presence-only.** Freeform prose with no stable identity; equality/
  membership on a paragraph is meaningless and extraction yields an uncomparable blob. Only
  `set`/`unset` applies — the same exclusion `context_pick` got from Nest (ADR-0028: per-prompt
  runtime, not authored structure), which stays excluded here too.
- **computed numerics** (`word_count`, `cost` — ADR-0029) are comparable *in principle* but want
  **ordering ops** (`>`/`<`) the grammar lacks; a **noted gap**, not part of this cut.

## Why / rejected alternatives
- **Sigil string `"$self"` as the operand form — rejected.** Stringly-typed and collides with any
  literal value that legitimately begins with `$`. The grammar discriminates by **tagged slots**
  everywhere else (`ViewExpr`, `ViewSource = ViewSpec | ViewRef`); a tagged variable operand is
  the house style.
- **Keeping derived lists backend-computed (the current `/references/backlinks` endpoint) as
  their permanent home — rejected.** It leaves "derived lists" a hand-rolled escape hatch and
  contradicts ADR-0025 (eval is frontend-side). The synthetic parameterized views are
  **frontend-constructed and never persisted**, so **no backend round-trip is needed** until a
  user *saves* a parameterized view — which is the configurator slice (out of scope here).
- **Splitting `name` and `value` into independent wires — rejected (§D).** Strictly more powerful
  (filter on the field named by entity A with a value from entity B) but **no writer workflow
  wants it**; the reachable split-only combination — an extracted field-name with a *literal*
  value — is near-meaningless (typing a value for a field you didn't consciously choose). A field
  *is* a `(name, value)` unit: coupling matches the writer's mental model; splitting adds
  cognitive load for the 95% case. Coupled is a **strict subset** — a second output handle is an
  additive, non-breaking increment if a real need ever appears (`feedback_flag_duplication…`
  logic in reverse: don't pre-pay generality nobody asked for).
- **A dedicated reverse-link / "backlinks" operator in this ADR — deferred.** Referenced-by is
  already expressible as `field(<ref field>, includes, $self)` (§C); a first-class reverse-link
  operator, and `MutationTimeline`'s non-roster data source, are **separate work layered on this
  mechanism**, not part of it.
- **Keeping `eq`/`includes` (and `neq`/`not_includes`) as distinct ops — rejected (§E, decided).**
  Under set-coerced overlap they are the same test at different cardinalities; the difference was
  only scalar-vs-list-field, now handled by coercion. They **merge** into `overlap`/`disjoint`
  (+ `set`/`unset`). This is a backend `models_views.py` op-set change touching stored views' `op`
  values — **cheap pre-1.0** (test projects recreated, `feedback_no_pre_1_0_migrations`).

## Consequences
- **The grammar grows two things**: a **variable-operand form** in the field-predicate `value`
  slot, and a **field-extraction operator** (`field_of` — a node-set → coupled `(name, valueSet)`
  via `flatMap` + dedup). The evaluator gains a **bindings environment** in `EvalContext`/`RunState`
  (amends ADR-0025, mirroring `resolveView`) and **set-coerced overlap** in `matchesField` (both
  sides → sets; §E). `$self` is reserved.
- **Predicate semantics becomes cardinality-driven** (§E): the `op` enum shrinks 6→4 — one
  `overlap` test + its `disjoint` negation replace `eq`/`neq`/`includes`/`not_includes` (**decided**
  op collapse), `set`/`unset` retained. A single-select filters against a multi-pick value **set**
  (`status ∈ {draft, todo}`) with no storage change.
- **The graph gains a second wire type** (§C): node-set edges vs value/binding edges, visually
  distinct and non-cross-connectable — the type is the connection rule.
- **The designer grows** a parameter handle on filter nodes, a **Parameter** node, and the
  **field-extraction** node; a wired coupled `(name, value)` overrides both the field and value
  dropdowns; a wired `name` on a kind lacking that field is a **validation warning**.
- **Field-type applicability is bounded** (§F): `long_text` and `context_pick` excluded (presence-
  only); enum extraction is key-space; computed-numeric ordering ops are a noted gap.
- **Existing closed views are byte-identical** (empty bindings, no variables) — the closed case is
  the degenerate case.
- **The backend (`models_views.py`) is untouched** in this cut: synthetic parameterized views live
  and die in the frontend. Backend persistence of **typed param declarations** arrives only with
  the **configurator/picker** for user-authored parameterized views (a later slice, likely with
  #182's derived-list phase).
- **Derived lists fold into the view system.** `BacklinksPanel`, `MutationTimeline`, and POV
  become **synthetic parameterized views bound with `$self`** (#182's derived-list slice),
  collapsing the escape hatch into the core and making "every list is governed by a view" true.
- **Out of scope**: the configurator/picker for user-declared params and its backend persistence;
  a dedicated reverse-link operator; `MutationTimeline`'s non-roster data source; splitting
  `name`/`value`.
