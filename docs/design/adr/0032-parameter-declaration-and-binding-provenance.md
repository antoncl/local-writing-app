# ADR-0032: Parameter declaration and binding provenance

- Status: Proposed — 0.7.0, **revised 2026-07-09** (design agreed; implementation pending). The
  revision makes each parameter family's **output wire pipe** explicit and points reference
  traversal at the new **Match** node (ADR-0033). See
  `memory/decisions_184_entity_vs_value_parameters.md`.
- Feature: #184 Parameterized views — the **configurator slice** ADR-0031 deferred · Doc:
  `views-and-filters.md` (parameterization)
- Follows: **ADR-0031** (free variables + a bindings environment; this ADR specifies *how a
  parameter is declared by the author* and *how its value reaches the evaluator at runtime*, both
  of which ADR-0031 explicitly deferred)
- Builds on: ADR-0023 (NodePickerConfig = `sources` + mechanics — a parameter's type reuses it),
  ADR-0022 (every NodeList is backed by a view), the #182 render-wrapper contract
- Governed by: `memory/decisions_author_vs_runtime_authority.md`,
  `memory/decisions_view_render_pipeline_ownership.md`

## Context
ADR-0031 gave the evaluator **free variables** and a **bindings environment** (`EvalContext.
bindings`), but deliberately stopped at the evaluator boundary: it consumes bindings and says
nothing about where they come from. `$self` is the trivial case — the embedding pane supplies it,
it is *ambient*. But the moment a view **author declares an input the surface doesn't already
know about** — "this view takes a `status`" or "…a `character`" — nothing is ambient. That value
is **not conjured**; it has to be **collected**. This ADR specifies the two open halves:
**(a)** how the author declares a parameter, and **(b)** how a runtime user supplies its value —
plus who owns the UI that does the collecting.

## Decision

**A. Declaration = a Parameter node, typed by *reference*.**
In the designer the author drops a **Parameter** node (the same family as `$self`, but
**not reserved**) and gives it a **name** and a **type**. The type is declared by pointing at
**what the parameter ranges over**, which reuses machinery already in the app (ADR-0023) rather
than inventing a widget-config surface:
- **Entity parameter** (`$character`) — ranges over **nodes**, so its type **is a view** (the
  universe of `lore:character`). The runtime control is the picker that view drives (ADR-0023
  `sources`). **Its output rides the node-set pipe (green)** — an entity parameter is a *node-set
  source*, feeding a Filter set-input, a `field_of` source, or a **Match**/**Nest** Parents/Children
  handle (ADR-0031 §C). It is never a value.
- **Value parameter** (`$status`) — ranges over a **field's value domain**, so the author points
  at a **field** (`status`); the parameter inherits that field's options in **key-space**
  (ADR-0031 §F). The runtime control is a select of those options. **Its output is a coupled
  `{field, value}` on the `{field,value}` pipe (orange)**, feeding a **Filter RHS** (ADR-0031 §C).

These two families are the same split as ADR-0031 §C–§F (entity node-sets vs `{field,value}`)
surfacing in the authoring layer — a sign the model is coherent, not accreting. The output-pipe
distinction *is* the wire-type discipline of ADR-0031 §C: entities ride the node-set pipe,
values ride the `{field,value}` pipe, and they cannot cross-connect. **Reference traversal
("scenes where `$character` is POV", referenced-by) is the Match node (ADR-0033), fed by the entity
parameter's green output — not a field predicate.** The control is **derived
from the type, never hand-built** — exactly as an `entity_ref` field's picker is derived from its
config today. The declaration (name + type-reference) is stored in the view spec's **parameter
list**.

**Entity-parameter types are subtype-polymorphic.** A parameter typed `lore:character` accepts the
declared entry_type **and every specialization below it** on the `parent:` chain — a `protagonist`
(which `is_a` character) satisfies a `character` slot. This is the exact `is_a`/entry_type-ancestry
relation ADR-0026 defines and the `descendants_of` grammar leaf already evaluates (#77 FQN); the
parameter layer **reuses** it rather than inventing an equality check. Consequently the runtime
picker for a `character` param offers the **whole family** (character + protagonist + …), and this
`is_a`-awareness holds anywhere an entry_type constraint appears, not just parameters. (Value
parameters — a select field's option domain — are not entry_types and carry no such subtyping.)

**B. Binding provenance — a priority ladder, mostly *not* the parent.**
For each declared parameter, a value is resolved down a short, explicit ladder:
1. **Surface-supplied (reserved)** — `$self`, and anything else the embedding pane chooses to
   bind. No user action. This is the **only** "conjured" tier, and it is reserved names only.
2. **Author-fixed default** — the author pins a constant at design time. This **closes** the
   parameter into a literal (it is no longer free); an edge case, not the interesting path.
3. **Runtime user control** — the real path for `$status`/`$character`. When the view renders,
   every declared parameter that tiers 1–2 did not bind gets an **input control rendered
   alongside the list** (a parameter strip above the rows). The user picks → the binding updates →
   the view re-evaluates. This is a search box's relationship to a filtered list, generalized.
4. *(later)* **Wired from enclosing context** — bound to a selection in a sibling pane. Real, but
   v2.

**C. Runtime bindings are ephemeral by default.**
A value picked through a tier-3 control is **pane/session state, not baked into the shared view
node**. A declared free parameter that gets *saved as a value* stops being a parameter — so
persisting the pick would quietly **collapse the abstraction**. The saved view stays a reusable
**template** ("a function awaiting arguments"); the current binding is remembered as **pane
state** (alongside the #182 wrapper's `collapsed`/`search`/`activeId` behaviour props), never
written back into the spec. Author-fixed defaults (§B tier 2) are the deliberate opposite — an
explicit *closing* of a parameter, which is why they persist.

**D. Ownership — the #182 render wrapper, not the evaluator and not each pane.**
The evaluator only **consumes** `bindings` (ADR-0031). **Populating** them from the user is the
render wrapper's job: its contract `(viewSpec, bindings)` extends to *"for each declared parameter
the incoming bindings don't cover, render its control, collect the value, feed it back into
bindings, re-evaluate."* So the parameter UI lives **with the wrapper** — centralized, reused
everywhere a parameterized list appears — not hand-rolled per pane. This is precisely why
ADR-0031 deferred the configurator to the #182 slice: the evaluator half shipped first; the
collection half is the wrapper's.

## Why / rejected alternatives
- **Baking runtime picks into the saved spec — rejected (§C).** It closes the parameter: the
  template becomes one concrete view, and expressing "the same view for a different character"
  needs a *new saved view per value*. Ephemeral binding keeps a single reusable view — the whole
  point of parameterizing.
- **Per-pane bespoke parameter UI — rejected (§D).** That is the derived-list escape hatch
  reappearing one layer up ([[decisions-view-render-pipeline-ownership]]). Centralize the control
  in the wrapper so "list = rendered view" stays enforced, not remembered.
- **Hand-configured parameter widgets — rejected (§A).** Type-by-reference derives the control
  from the schema (a field's domain) or a view (a kind's universe), reusing ADR-0023; a separate
  widget-config surface would duplicate the picker machinery entity_ref fields already use.
- **A standalone persisted "parameter bindings" store — rejected for v1 (§C).** Pane state
  suffices; a shared or named binding set (e.g. "pin this view to Alice everywhere") is a later
  concern, not v1 scope.

## Consequences
- **The view spec grows a parameter-declaration list** (`name`, type-reference — a view for entity
  params, a field key for value params). This is **the first thing the backend must persist** for
  parameterized views: ADR-0031 kept `models_views.py` untouched for *synthetic* (frontend-only)
  views, but a **saved** parameterized view needs its parameter list in `models_views.py`. Runtime
  binding *values* are **not** persisted (§C).
- **The #182 render wrapper gains a parameter strip** — it reads the spec's declared params,
  resolves each down the §B ladder, renders a derived control for the unbound ones, holds their
  bindings as pane state, and re-evaluates on change.
- **Reserved names (`$self`) never render a control**; user-declared params render one unless the
  surface binds them.
- **The two parameter families reuse existing pickers** (ADR-0023): entity → view-sourced node
  picker; value → field-domain select. No new widget surface.
- **Out of scope**: context-wiring (§B tier 4); named/shared/persisted binding sets; anything the
  ADR-0031 cardinality model (§E) doesn't already give for multi-valued parameters.
