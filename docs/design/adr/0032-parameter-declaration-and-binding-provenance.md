# ADR-0032: Parameter declaration and binding provenance

- Status: Accepted — 0.7.0, **amended 2026-07-09 (forward model)**; accepted 2026-07-10. Declaration is now **promote-in-
  place**: a runtime formal is a *promoted Filter value slot*, its type **derived from the field**;
  the declared *Parameter-node-typed-by-reference* is **deferred** to node-set-source params (no
  current use case). `$self` is a **reserved wired source node**, not a formal. Reference traversal
  is forward `Filter`/`field_of` (ADR-0031) — Match (ADR-0033) is withdrawn. **Amended 2026-07-15
  (§D Amendment 1: ONE central reused component owns the whole runtime view surface — selection +
  binding — because selection fixes which params instantiate).** **Amended 2026-07-19
  (Amendment 2, #199: `$self` is REMOVED — no surface binds it; reintroduce with the anchored render
  surface. Every §A/§B/§D reference to `$self` below is superseded by Amendment 2).**
  See `memory/decisions_184_entity_vs_value_parameters.md`.
- Feature: #184 Parameterized views — the **configurator slice** ADR-0031 deferred · Doc:
  `views-and-filters.md` (parameterization)
- Follows: **ADR-0031** (free variables + bindings env; forward `field_of`/`Filter`). This ADR
  specifies *how a formal is authored* and *how its actual reaches the evaluator at runtime*.
- Builds on: ADR-0023 (a param's control reuses picker mechanics), ADR-0022 (every NodeList is a
  view), the #182 render-wrapper contract, ADR-0026 (`is_a` for type intersection)
- Governed by: `memory/decisions_author_vs_runtime_authority.md`,
  `memory/decisions_view_render_pipeline_ownership.md`

## Context
ADR-0031 gives the evaluator **free variables** and a **bindings environment**, but stops at the
evaluator boundary: it consumes bindings and says nothing about where they come from. `$self` is
ambient — the pane supplies it. But the moment a view **takes an input the surface doesn't already
know** — "…a `POV`", "…a `status`" — that value must be **collected**. This ADR specifies
**(a)** how the author declares a formal, **(b)** how a runtime user supplies its actual, and who
owns the collecting UI.

The authoring convention is load-bearing because **it fixes where a formal's *type* comes from**,
which fixes its runtime control.

## Decision

**A. Declaration = promote-in-place; the type is derived from the field.**
A runtime formal is created by **promoting a Filter's value slot** (the "promoted port" convention:
Houdini *promote parameter*, Blender *group inputs*, Unreal *promoted variables*). The inline value
editor **collapses into a socket** wired to the parameter strip. Consequences:
- The formal's **type is derived from the promoted field** — an `entity_ref` slot yields an entity
  formal whose picker is the field's `ReferencePicker`; a `select` slot yields a value formal over
  the field's key-space. **No separate type declaration, and it cannot mismatch the slot** — it came
  from it.
- Promoting binds the slot to a **named formal** stored in the view spec's **parameter list**
  (`name`, `label`). Multiple slots may promote to the **same name** (fan-out — filter *and* colour
  by one `$POV`); a shared formal's **type is the intersection of its slots' fields** (ADR-0031 §F).
  Sharing a name across an empty intersection is a validation **warning**.

**`$self` is a reserved *wired source node*, not a promoted formal.** It has no slot to promote —
ADR-0031's canonical use is `field_of($self, 'References')`, where `$self` is the **input** to
`field_of`. So `$self` is a node on the canvas (sibling to `All`) emitting the anchored node as a
singleton set, **wired** wherever a node-set is wanted (a `field_of` input; a Filter's entity
operand for "scenes where **this** character is POV"). Its type is the **pane's anchor kind**
(ambient); in a **roster pane** with no anchor it emits empty, so a `$self` view only functions where
there is an anchor.

**The declared Parameter-node-typed-by-reference is deferred.** A formal declared *independently* of
any slot — a user-typed **entity seed set** fed into `field_of`/set-algebra — is the only case
promote-in-place cannot express (no slot to derive a type from). It has **no current use case**, so
it is documented but **not built for 0.7.0**. When it arrives it is the non-reserved sibling of the
`$self` source node, typed by reference (a kind/view; entity types subtype-polymorphic via ADR-0026,
picker offers the whole `is_a` family) and runtime-bound.

**B. Binding provenance — the authored value is an overridable default.**
Promoting a value slot does **not** discard its authored constant — it **converts the constant into
a default**, shown pre-filled in the strip and **overridable** at runtime. So a promoted formal is
always a strip control *seeded by its default*; there is no separate "author-default closes the
formal" tier. The ladder, per formal:
1. **Surface / reserved** — `$self` (wired source node), and anything the pane binds. No user action,
   **no strip control**; reserved names only.
2. **Un-promoted literal** — a **fixed constant** internal to the Filter, **not exposed** in the
   strip and not overridable. The author's choice to hardcode a value.
3. **Promoted formal** — the real runtime path (`$POV`/`$status`). A strip control **seeded by the
   authored default** (which may be empty); the user may **override** it → the binding updates → the
   view re-evaluates. A formal with **no default** starts unbound → its predicate is inactive until
   picked (ADR-0031 §B). A search box's relationship to a filtered list, generalized.
4. *(later)* **Wired from enclosing context** — bound to a sibling pane's selection. Real, but v2.

**C. Defaults persist; overrides are ephemeral.**
An authored **default** (§B tier 3) persists in the spec — it is part of the template. A runtime
**override** of that default is **pane/session state, not baked into the shared view node**;
persisting it would collapse the template into one concrete view. So the saved view carries its
defaults ("a function with default arguments"); the current pane carries the overrides. Un-promoted
literals (§B tier 2) persist as ordinary fixed constants.

**D. Ownership — the #182 render wrapper.**
The evaluator only **consumes** `bindings`. **Populating** them is the wrapper's job: its contract
`(viewSpec, bindings)` extends to *"for each formal the incoming bindings don't cover, render its
control (derived from its type), collect the value, feed it back, re-evaluate."* So the parameter
strip lives **with the wrapper** — centralized, reused wherever a parameterized list appears — and
its controls are the same `FieldValueEditor` widgets promoted from the fields.

**Amendment 1 (2026-07-15) — one central reused component owns the whole runtime view surface.**
§D generalizes: **runtime view-configuration is ONE central, reused component** — not a set of parts
a caller (App/pane) wires together. This is the #182 / ADR-0022 principle (the failure mode being
callers driving the naive `NodeList` / handle-bar differently, so surfaces drift). The two runtime
concerns — **view selection** (which saved lens is active) and **actual→formal binding** (arguments
to that lens's formals) — are **inseparable**, so they are **not** two independently-owned components:

- **Selecting the lens *fixes the formals*, which fixes whether a parameter strip instantiates at all
  and which controls it shows.** The selector is therefore intrinsically part of parameter
  instantiation — the decision "show parameter controls? which?" is downstream of the selection and
  cannot be owned by a different component than the selection itself.

So one component owns the whole runtime surface: it renders the **view selector** (positioned as
pane-handle-bar chrome — a coarse, persistent, tab-like choice), the **param strip** (fine-grained,
ephemeral, §C), and the list. It is **dropped in once per pane**; the selector is **not** a separate
widget a caller hand-places per pane. *Which* panes expose selection is a prop/config on the one
component (ADR-0022 v1: Lore/Draft/Assistants), never a per-pane reimplementation.

This **supersedes** any reading of §D as "selection is pane-owned, binding is wrapper-owned" (two
owners): the single component owns both. Chosen (over a two-component split) for two reasons — it is
the **stronger guard against per-caller divergence** (one component, no seams for functionality to
fork across panes), and the two concerns are **not cleanly separable** (above). The rule holds until
a pane needs something the one component cannot express (falsifiable, not proven).

**Amendment 2 (2026-07-19) — `$self` is removed (#199).**
The reserved `$self` source described in §A (and referenced in §B tier 1, §D consequences) is
**deleted from the codebase**, not merely dormant. Rationale:

- **Nothing binds it.** §A ties `$self`'s value to "the pane's anchor kind", but **every view-list /
  tree pane is a roster pane with no anchor** (Lore, Draft, Research, Assistants). No surface ever
  supplied an `anchorId`, so a `$self` view resolved to the empty set *everywhere*, including the pane
  the reader might assume it worked in. The mechanism was fully inert.
- **It was an over-exposed footgun.** The designer palette offered "This entry" (`$self`) as a source
  in *every* view, on *every* pane — so a user could author a view that could never produce a row,
  with no signal. Offering a source that can't bind is worse than not offering it.
- **Its one real consumer never used it.** The backlinks panel — the only entry-relative feature that
  actually works — is a reverse-index bypass (`backlinksFor(anchorId)`), never routed through the
  evaluator or `$self`. It is unaffected.

**What was removed:** the `SELF_VAR` constant + its evaluator branches (an unbound var is now uniformly
`OPERAND_INACTIVE`, ADR-0031 §B — there is no `$self`-empty-set case); the `self` designer graph-node
kind, its palette chip, lowering, glyph and render; and the `anchorId → $self` binding on the
`ViewNodeList` `view` input. The `{var}` operand mechanism (promoted formals / params) is **untouched**.
The view-grammar IDL (#277/ADR-0041) never reserved `$self` — `var` is an ordinary string field — so
no grammar change was needed.

**Reintroduction path.** `$self` was invented for the surface §A anticipated but that was never built:
a **reference / entity_ref field rendered as a view on a node's editor rail**, which legitimately needs
"filter relative to *this* node." When that anchored render surface ships (Views 2.0 flow model), a
`$self`-equivalent anchor binding comes back **with it**, defined against a surface that actually binds —
not as free-floating forward-compat ABI. Until then, `$self` does not exist.

## Why / rejected alternatives
- **A declared Parameter node as the *primary* declaration — rejected/deferred.** Promote-in-place
  derives the type from the field (no independent declaration, no mismatch) and gives fan-out via
  shared names, matching the "the inline picker becomes a socket" model. A declared node earns its
  keep only for **node-set-source** params, which have no current use case — so it is deferred, not
  built.
- **Baking runtime picks into the saved spec — rejected (§C).** Closes the parameter; "the same view
  for a different character" would need a new saved view per value.
- **Per-pane bespoke parameter UI — rejected (§D).** That is the derived-list escape hatch one layer
  up. Centralize in the wrapper.
- **Hand-configured parameter widgets — rejected (§A).** The control derives from the field
  (promote-in-place) or, for the deferred declared param, from a type-reference (ADR-0023) — never a
  bespoke widget surface.

## Consequences
- **The view spec grows a parameter list** (`name`, `label`, **default**; type **derived** from the
  promoted slot's field, intersected across shared slots). This is the **first thing the backend
  persists** for a **saved** parameterized view (`models_views.py`). Authored **defaults persist**;
  runtime **overrides** do not (§C).
- **The #182 wrapper gains a parameter strip** — reads the formals, resolves each down the ladder,
  renders a `FieldValueEditor`-derived control for the unbound ones, holds bindings as pane state,
  re-evaluates on change.
- **`$self` ships as a reserved wired source node** (ambient, no control, type = anchor kind, empty
  in roster panes). The **declared source node is deferred**.
- **Reserved names never render a control**; promoted formals render one unless the surface binds
  them.
- **Out of scope**: context-wiring (§B tier 4); the declared source Parameter node; named/shared/
  persisted binding sets.
