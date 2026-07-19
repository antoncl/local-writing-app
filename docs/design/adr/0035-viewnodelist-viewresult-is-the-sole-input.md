# ADR-0035: `ViewNodeList` — a view's output is one `ViewResult<T>`, and that is its sole input

> **⚠ Amended 2026-07-19 (#199): `$self` was removed entirely** — `ViewNodeList` no longer takes an `anchorId` and binds no `$self`. Every `$self` reference below is **superseded**; the param strip + bindings env remain, minus `$self`. See [ADR-0032](0032-parameter-declaration-and-binding-provenance.md) Amendment 2.

- Status: Accepted — 0.7.0, 2026-07-11
- Feature: #182 canonical list-render wrapper (named **`ViewNodeList`**) · relates #112 (Draft
  presentation), #181 (unified evaluator normalizers), #184 (parameterized views)
- Follows: ADR-0021 (saved views are nodes; `ViewSpec` is the core), ADR-0022 (every NodeList is
  backed by a view), ADR-0025 (views evaluate frontend-side over an in-memory roster), **ADR-0027
  §D/§E (the *intra-result* mechanism — named handles + `(node,path)` normalization organize
  grouping/nesting *within a single* `ViewResult`; the precedent that concatenation lands inside one
  result — NOT the inter-result "vertical edges" composition, which is Views 2.0)**, ADR-0034 (the
  Draft pane hands the wrapper **one** enriched roster → one `ViewResult`)
- Consistent with: ADR-0019 / ADR-0028 (multi-membership — a node may appear under several
  groups/paths), ADR-0031 §D (node-set vs value-set edge payloads — scoped in Decision below)
- Governed by: `memory/decisions_view_render_pipeline_ownership.md`

> **Terminology — "wrapper" = `ViewNodeList`.** Throughout this ADR (and its
> siblings, ADR-0032 §D in particular) "the wrapper" / "the list-render wrapper"
> denotes exactly **`ViewNodeList`** — the component named in the Feature line and
> the subject of the Decision. There is no separate or additional wrapper layer:
> the param strip, the bindings env (incl. `$self`), and re-evaluation all live
> **inside `ViewNodeList`** (its `view` mode), not in a per-pane shim. When a
> passage says "the pane hands the wrapper one `ViewResult`," read "the pane hands
> `ViewNodeList` one `ViewResult`."

## Context
#181 unified the evaluator's normalizers so `evaluateView` returns **one tree-uniform
`ViewResult<T>`** (`nodes` membership · `annotations` per-node color · `groups` tree-or-`null` ·
`diagnostics`). #182 introduces the consumer half: a component — **`ViewNodeList`** — that renders a
`ViewResult` as a NodeList, absorbing today's per-pane `ViewGroupedList` + `GroupTree` glue and the
duplicated `viewGroups`/`displayGroups`/`collapsedGroups` boilerplate the call-site census found
copied across Lore, Assistants, and the Draft path.

`ViewNodeList` **composes** `NodeList`; it does **not** extend it. `NodeList` stays view-blind naive
chrome (search slot, empty slot, `card`/`tree` mode); all `ViewResult → row` logic lives in
`ViewNodeList`. This is the ownership inversion of #182 — see
`decisions_view_render_pipeline_ownership.md`.

The census surfaced sites that never evaluate a view (Chats, Mutations, MutationTimeline,
BacklinksPanel — pre-computed arrays; ReferencePicker — a cross-kind union node set, ADR-0023). The
open question was the input **type**: should `ViewNodeList` accept `ViewResult<T> | T[]`, or
`ViewResult<T>` alone with non-view sites lifting their arrays? Underneath sits a second, larger
question the Views 2.0 flow model raises: a view whose output is several result nodes joined by
**vertical edges** — a **concatenation** of outputs. Does that produce *many* results, or one?

## Decision
**A view's output is exactly one `ViewResult<T>` — always — and `ViewResult<T>` is `ViewNodeList`'s
sole input.** This is a hard boundary, not a default. Nothing downstream of the evaluator ever sees
a `ViewResult[]`, a `ViewResult | T[]` union, or any other shape.

**Scope — `T` is always a node** (`ViewResult<T extends EvalNode>`). The **value-set** edge payload
(ADR-0031 §D — a scalar `field_of` yields a set of *values*) is an **evaluation-internal operand**
feeding a Filter's value slot; it is never a view's rendered output and **never reaches
`ViewNodeList`**. So "one `ViewResult<T>`" and 0031's two edge payloads do not contend — the two
payloads live *inside* evaluation; the *output* is always one node-typed `ViewResult`.

1. **A view never emits multiple results — concatenation always lands inside one `ViewResult`, and
   it does so at two *distinct* levels:**
   - **Intra-result (today — ADR-0027 §D/§E):** *within* a single View result node, N named input
     handles concatenate and group, and `evaluateView` normalizes the `(node, path)` rows into that
     one result's `groups` (the tree-uniform form, post-#181). §D/§E specify how grouping/nesting is
     managed **inside a single `ViewResult`** — they are **not** about composing several of them.
   - **Inter-result (the flow model's "vertical edges" — Views 2.0):** *multiple* View result nodes
     joined vertically, a concatenation of their outputs. This is a **higher** composition than §D,
     but it too **reduces to a single `ViewResult`** — the containment this ADR turns on. So whether
     concatenation is intra-result (handles) or inter-result (vertical edges), the value that crosses
     into `ViewNodeList` is **always one `ViewResult`**; the closure is realized **upstream**, never
     asked of the consumer.

2. **`ViewResult<T>` is closed under concatenation**, which lets the *non-view* constructors express
   it without a new type:
   - `nodeSet(nodes: T[]) → ViewResult<T>` = `{ nodes, annotations: new Map(), groups: null }` — the
     **degenerate, one-stream** `ViewResult`. The base case; not a peer input shape.
   - `concat(...rs: ViewResult<T>[]) → ViewResult<T>` (**only if** a hand-assembled site needs it) —
     the inter-result stacking (above) expressed as a `ViewResult` *constructor* for non-view
     results, using the append-and-dedupe semantics of ADR-0027 §D's across-handle rule: each input
     becomes a top-level `groups` segment; `nodes` is the deduped union. It is **not** a view-grammar
     / palette op (those stay ADR-0018/0027), and it is **same-kind** (uniform `T`) — cross-kind
     stacking is flow composition, **Views 2.0** ([[decisions-views-2-0-flow-model]]; consistent with
     ADR-0031's heterogeneous-out-of-scope).

3. **Non-view sites lift, at the call site, via `nodeSet()`.** `<ViewNodeList result={nodeSet(chats)}
   />`. One visible word; the promotion is legible — even Chats hands over a rendered result. No
   union, no `Array.isArray` discriminant inside the component, one internal code path.

4. **Membership vs. presentation** — the *established* rule (ADR-0027 §E dedupe-on-`(node,path)`;
   ADR-0019 / ADR-0028 multi-membership), restated here as an invariant every constructor and
   `ViewNodeList` must honor:
   - `nodes` = **membership → deduped.** A node is "in the view" once.
   - `groups` = **presentation → may repeat.** The same node may appear under two segments/paths, as
     it does under two annotate labels (ADR-0019) or two Nest parents (ADR-0028) today — path
     denormalization ([[decisions-view-trees-are-path-denormalization]]). `ViewNodeList` renders
     `groups` faithfully and never collapses repeats.

Richness grows in the **`ViewResult` constructor family** (`nodeSet`, optionally `concat`) and in the
view grammar **upstream** — not in `ViewNodeList`'s input signature, which stays one node-typed
`ViewResult`.

## Why / rejected alternatives
- **Rejected: `ViewResult<T> | T[]` union input.** It is only sugar over `nodeSet()` — the same lift,
  moved *inside* the component behind a runtime discriminant and a messier generic prop type. It
  presents a bare `T[]` as a *co-equal* input shape when a `T[]` is conceptually the *least*
  expressive `ViewResult` (no annotations, no segments). And it does not generalize: a 2-way union
  cannot express N stacked streams, so it would have to be revisited the moment concatenation ships.
  Starting strict and loosening later (a non-breaking overload) is cheap; starting loose and
  tightening is not.
- **Rejected: a view outputs many results (`ViewResult[]` / vertical edges as a collection).** This
  is the asymmetry the whole #182 project exists to kill. **ADR-0027 §E already establishes the
  precedent** for the intra-result case — `evaluateView` normalizes a View's handle output into
  **one** result — and the inter-result "vertical edges" composition (Views 2.0) follows the **same
  principle**: it reduces to one `ViewResult`, never a surfaced collection. Surfacing a collection
  instead would make every consumer re-implement the stitch, drifting site-to-site — precisely the
  per-pane divergence the census documented. **The single-`ViewResult` output is a clean boundary;
  anything else reintroduces asymmetry downstream.**
- **Consistency with ADR-0034.** The Draft pane was already decided to hand the wrapper **one**
  enriched-roster `ViewResult` (membership + presentation), rejecting the two-roster split. This ADR
  generalizes that grain to *every* input to `ViewNodeList`.

## Consequences
- **`ViewNodeList` has one input type and one internal path**, and its signature **does not change**
  when the inter-result "vertical edges" flow model matures — that composition reduces to one
  `ViewResult`, exactly as ADR-0027 §E's intra-result normalize does today, and `ViewNodeList`
  already renders it. Forward-compatible with the Views 2.0 substrate (ADR-0031/0032; north star in
  `decisions_views_2_0_flow_model`).
- **`ViewGroupedList` + `GroupTree` are absorbed into `ViewNodeList`**; the per-pane
  `viewGroups`/`displayGroups`/`collapsedGroups` derivation is centralized.
- **Non-view sites become first-class** through `nodeSet()` — the census's Classes C/D/E route
  through the same component as the view-driven Classes A/F, which is the asymmetry fix.
- **`nodeSet` (and `concat` if a site needs it) live beside `evaluateView`** (`lib/views/`) as
  `ViewResult` *constructors* — **not** grammar; membership-dedup / presentation-repeat (§4) is their
  shared invariant.
- **Out of *this ADR* (input contract only), but IN scope for the 0.7.0 *release*.**
  `ViewNodeList`'s **consumer-side API** — the `row` snippet + intent surface, including the
  **escape-hatch** handlers (drag-reorder, inline rename, dblclick-open) — is designed on **#182**,
  shaped by the **full census (Draft included) now**, so the signature is **settled up front and does
  not widen** when Draft is plugged in. Release phasing (both 0.7.0): **phase 1** = Lore + Assistants
  + the ViewBodyView preview (core + pluggable; escape-hatch props present-but-unwired); **phase 2 =
  #112, the Draft migration**, which first *exercises* those escape-hatch handlers. Neither is
  deferred past this release. **Genuinely out (Views 2.0):** cross-kind / inter-result composition
  (§2). Naming of `nodeSet`/`concat` is bikeable.
