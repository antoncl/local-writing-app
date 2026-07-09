# ADR-0031: Parameterized views — free variables, a bindings environment, and the field-extraction node

- Status: Proposed — 0.7.0, **revised 2026-07-09** (design agreed; implementation pending). The
  2026-07-09 revision corrects a flattening in the original §C/§D: parameters are **two families on
  two wire pipes** (entity → node-set; value → `{field,value}`), and **referenced-by is not a field
  predicate** — it is the **Match** node (ADR-0033). See
  `memory/decisions_184_entity_vs_value_parameters.md`.
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
*Which* field or tag a view filters on, and the `nest`/`match` rule, are **authoring** decisions
frozen into the spec. A free variable **never selects the field or match rule** — it only supplies
a **value** (a value parameter → the `{field,value}` slot, §C) or a **node** (an entity parameter →
a node-set input, §C). Choosing to filter on `pov` rather than `status`, or which reference field
Match traverses, is the author building that predicate; nothing at runtime re-decides it. `$self` (the node the
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

**C. Two parameter families, two pipes — the entity/value split is the spine.**
*(Revised 2026-07-09. The original §C flattened both families into "a variable in the predicate
value slot"; that lost the node-set nature of entities and mis-modelled referenced-by. Corrected
below.)* A parameter is one of two families (the same split ADR-0032 §A declares), and each rides
its own wire type:

- An **entity parameter** — `$self` (reserved, surface-supplied) or `$character` (author-declared)
  — ranges over **nodes**, so it is a **node-set source** on the **node-set pipe** (the existing
  set-algebra flow). It feeds any node-set input: a Filter's set-input, a `field_of` source, a
  **Match**/**Nest** Parents or Children handle. It is **not** a value operand.
- A **value parameter** — `$status` → e.g. `status: draft` — is a coupled **`{field, value}`** (the
  field it ranges over plus a chosen value). It rides a **second wire type**, the **`{field,value}`
  pipe**, into a **Filter's RHS**, supplying both the predicate's field and its value.

So the field-predicate `value` slot is fed only by the **`{field,value}` pipe** — a value parameter,
or a `field_of` extraction (§D) — **never by an entity**. The two pipes carry different payloads and
**cannot cross-connect**: a `{field,value}` can't feed `union`/`intersect`/a Match input; a node-set
can't land on a Filter's RHS. **The type is the connection rule, made visible** — value/binding
handles sit at the **top** of a node (visually distinct), node-set handles on the sides.

**referenced-by is not a field predicate** (the original §C's `field(<ref>, includes, $self)` was
the flatten). "Nodes that reference `$self`" is a **relational match**, expressed with the **Match**
node (ADR-0033): `$self` (an entity, node-set pipe) into Match's Parents, the universe into
Children, matched on the reference field; Match returns the referrers, flat. Only genuine **value**
comparisons — "scenes whose `status` is `draft`", "scenes sharing `$self`'s scalar `pov`" — live on
the `{field,value}` pipe into a Filter (the **POV/Status** shape).

**D. The field-extraction node (`field_of`) — same-field matching, always on the `{field,value}`
pipe.** Given a **node-set** source and a chosen field `F`, `field_of` emits a coupled
**`{field: F, value}`** on the `{field,value}` pipe: `flatMap(inputSet, n → valuesOf(n, F))`,
**deduplicated**. `field_of($self, "pov")` is the N=1 case (`$self` a singleton); a multi-node
input (e.g. `All`, §E) yields `F`'s distinct values across the set. Wired into a Filter it
**overrides both** the field (via `F`) and the value — which is exactly a **same-field match**
("scenes sharing `$self`'s `pov`"): the extracted field and the filtered field are the *same* field,
so coupling them is correct.

**`field_of` always emits `{field,value}` — never a node-set — including for reference fields.**
*(Revised 2026-07-09; the original §D wrongly gave it a value-only mode and implied entities could
be values.)* Same-field matching compares the **stored representation**, and a reference's stored
representation is its **id**, so "sharing `$self`'s `pov_ref`" is `candidate.pov_ref == <$self's
stored pov_ref>` — id equality on the `{field,value}` pipe, no entity reified. *Cross-field /
identity traversal* — a candidate's reference field pointing at a **different** entity — is **not**
`field_of`; it is **Match** (ADR-0033). `field_of` never produces the node-set an entity target
would need, which is precisely why coupling `{field,value}` is always the right rule for it (and why
the original "value-only wire, dropdown names a different LHS" escape hatch — the LHS-override
problem — is unnecessary: that case is Match).

The **field dropdown** selects `F`, listing the source entity's fields **including intrinsics**
(`id`/`title`/`entry_type` — the honest choice, matching the field-definition window). Because
entity types are **subtype-polymorphic** (ADR-0032 §A), the dropdown offers the **declared (base)
type's** fields — every specialization carries at least those. `long_text` stays excluded (§F);
enum/select project the stored **key** (§F).

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
- **Splitting `name` and `value` into independent wires — rejected (§D).** The motivating case for
  a split (a value for a *different* LHS field than the one it came from) is **referenced-by**, and
  that is now **Match** (ADR-0033), not a field predicate — so `field_of` stays cleanly coupled and
  never needs a value-only mode. A field *is* a `(name, value)` unit; coupling matches the writer's
  mental model.
- **Overloading the field predicate for reference traversal — rejected (2026-07-09).** A
  *polymorphic Filter RHS* (accept a green entity, identity-match when the LHS is a reference field)
  was considered; it mixes value comparison and identity traversal in one node and reintroduces the
  **LHS-override problem** (an extracted `(name,value)` hijacks the filter's field). Likewise a
  *mode flag on Nest* (flat-vs-nested output) is the mode-parameter smell. Reference traversal gets
  its **own node, Match** (ADR-0033) — flat semi-join, green in/out — so Filter stays value-only and
  Nest stays tree-only.
- **A dedicated reverse-link / "backlinks" operator — RESOLVED as Match (ADR-0033), not deferred.**
  Referenced-by, "which nodes reference `$self`", is the Match node (`$self` → Parents, universe →
  Children, match on the reference field, flat output). `MutationTimeline`'s non-roster data source
  is still separate work layered on top.
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
- **The graph gains a second wire type** (§C): node-set edges (set-algebra flow) vs
  **`{field,value}`** edges (value parameter / `field_of` → a Filter RHS), visually distinct and
  non-cross-connectable. Value/binding handles sit at the **top** of a node; node-set handles on the
  sides. The type is the connection rule.
- **The designer grows** (§C/§D): an **entity Parameter** node (node-set source: `$self` reserved,
  `$character` declared) and a **value Parameter** node (`{field,value}` source); the
  **field-extraction** node `field_of` (node-set → `{field,value}`); and the **Match** node
  (ADR-0033) for reference traversal. A `{field,value}` wire into a Filter **overrides its field/op/
  value editors and locks them** until disconnected (it is the single source); a wired field the
  target kind lacks is a **validation warning**.
- **Referenced-by / reference traversal is Match, not a predicate** (§C, ADR-0033): the Filter RHS
  stays **`{field,value}`-only**; Nest stays tree-only; Match owns the flat semi-join. Entity
  parameters (node-set pipe) feed Filter set-inputs, `field_of` sources, and Match/Nest handles.
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
