# ADR-0036: Views are explicit or implicit; the empty view evaluates to the empty set

> **⚠ Amended 2026-07-19 (#199): `$self` was removed entirely** — the `$self` mention below (the anchored entity a backlinks list is relative to) is **superseded**; the backlinks panel never routed through `$self`/the evaluator (it's a reverse-index bypass) and is unaffected. See [ADR-0032](0032-parameter-declaration-and-binding-provenance.md) Amendment 2.

- Status: Accepted — 0.7.0, 2026-07-11 · shipped (#112, PR #214)
- Feature: #112 Draft migration (phase 2 of #182) is the vehicle. Removes the null-view-evaluation
  hack, introduces the explicit/implicit split, and settles where `ViewNodeList` fold state persists.
- Follows: ADR-0020 (views are kind-anchored — the universe is the kind's roster), ADR-0021 (saved
  views are nodes; `ViewSpec` is the core), ADR-0022 (**every NodeList is backed by a view** —
  "implicit view" = node-less-view *provenance*, not the absence of a view; this ADR gives that clause
  its persistence model), ADR-0025 (**views evaluate frontend-side**; the backend never evaluates —
  load-bearing below), ADR-0031/0032 §neutral-reset / #198 / #206 (an *unset combinator operand* is
  ∩-identity pass-through — distinct from an empty *view*, see below), ADR-0035 (`ViewNodeList`;
  `collapsed` is a `$bindable SvelteSet<string>` keyed by `ViewGroup.key`)
- Governed by: `memory/decisions_182_view_node_list.md` (the PENDING collapse decision), 
  `memory/decisions_view_render_pipeline_ownership.md`, `memory/decisions_184_entity_vs_value_parameters.md`

## Context

Two loose ends converge in the #112 Draft migration, and resolving one forces the other.

**1. The null-view hack.** A view whose `expr` is `null` (or a stray `{}`) evaluates to the **whole
roster** — `evaluateView` falls through to `new Set(state.order.keys())` at
`frontend/src/lib/views/evaluateView.ts:329` (mirror paths: the stray-`{}` leaf `:668`, the groupless
`view_ref` `:686`). `defaultView(kind)` (`:192`) is literally `{ kind, expr: null }` and leans on this:
every pane's *default* view means "show everything" only because an **unspecified** view silently
means "everything." That is a hack — an absent specification should not smuggle in the maximal one —
and eliminating it was the point of the last stretch of view work; the cut was deferred until #112
landed the render substrate (#181/#182). The ViewEditor still shows the full roster for an empty view.

This is **not** the neutral-reset (`:1033`): an *inactive field predicate inside a combinator* returns
the universe for ∩-identity so an intersect passes its input through (#198/#206). That is a **combinator
operand** being unset, not a **view** being empty — a different level, and correct. It stays.

**2. Where fold state persists.** `ViewNodeList` owns per-group collapse as a `$bindable collapsed`
set (ADR-0035). Phase 1 shipped it *ephemeral*. The Draft tree — #112 — cannot: it already persists
collapse (today via `treeActions.collapsedStructureNodes` → `localStorage`, keyed by raw node id;
`treeActions.svelte.ts:248-303`). So #112 must answer "where does fold state live?", and the answer
depends on whether a list *is* a customizable view or not — the same distinction that decides what
replaces the null default.

## Decision

### 1. The empty/null view evaluates to the **empty set**
Top-level `expr: null` / `{}` yields `{}`, not the roster (cut `:329`, `:668`, `:686` to the empty
set). **An unspecified view shows nothing; "everything" must be stated explicitly.** The neutral-reset
for unset *operands inside combinators* (`:1033`) is untouched — different level (§Context).

### 2. Views are **explicit** or **implicit** — the split governs backing *and* persistence
- **Explicit view** — the pane offers view customization (Draft, entities/Lore, Assistants, …). It is
  **always backed by a real view node on disk**, and that includes a **system-provided default view**
  the user can **copy but not modify** — the starting point for authoring their own. Its fold/ui state
  persists **on the view node** (the selected one, or the system default).
- **Implicit view** — no customization is offered (the References list, and similar derived/embedded
  lists). It is **not backed by a view node on disk** — it is an in-memory result, usually
  `nodeSet(...)` (the degenerate `ViewResult`, ADR-0035) or a synthesized explicit spec, and it
  **never relies on null-means-everything**. Its fold/ui state, if any, persists on the **host
  node/entity being displayed** (the entity that owns the embedded list; `$self` for backlinks).
  *(Host-node fold wiring is out of scope for #112 — Draft is explicit — and lands with the first
  implicit consumer that needs persisted fold. Stated here as the other half of the settled model.)*

### 3. Each system default view's spec is chosen by an **equivalence audit**, per site — no new grammar
The replacement for a given `defaultView(kind)` is an **explicit** spec that presents the **same data,
in the same grouping, in the same sort** as that pane's old null view — verified site by site (the
audit question: *"does this explicit view reproduce the old null view here?"*). The data-selector is
`{ descendants_of: "<kind-root>" }`, where **`<kind-root>` is the kind's parentless root type** looked
up from the schema — `lore:base`/`scene:base`/`research:base` for kinds with an abstract base, but
`assistant:assistant`/`chat:chat_session`/`project:project` for **single-concrete-type kinds that have
no `:base`** (a real gap — there is *no* `assistant:base`; `default_schema.py:267`). This works
uniformly because `descendantFqns` seeds the family with the FQN itself (`evaluateView.ts:951`
`new Set([fqn])`), so `descendants_of:<kind-root>` = the whole roster for *every* kind, single-concrete
included. **No `all`/`universe` grammar leaf is added** — an earlier proposal, withdrawn once the
seed-inclusive `descendants_of` was found to cover the kind-agnostic case with existing grammar. The
designer's "All" injector (`viewGraph.ts` — today lowering to `expr:null`) is re-pointed to lower to
`descendants_of:<kind-root>` instead; an *empty/unwired* graph lowers to `null` → empty.

Selector paired with the kind's intrinsic presentation + manual sort. **Scene/Draft is more involved**
and its exact default spec is deferred to build time: `descendants_of:scene:base` + `presentation:"tree"`
reproduces today's tree via the `ancestry` side-channel on `EvalNode`, but expressing the manuscript
hierarchy via the `nest` op (ADR-0028) would make the tree first-class *in the spec* rather than riding
that side-channel — a fork settled when the scene view is built, not here.

The audit is a **gating deliverable of the cut**, not an afterthought: every `evaluateView` caller and
`defaultView` consumer is inspected before `:329` flips, so no surface silently empties. (Audit done
2026-07-11: only Lore + Assistants are load-bearing on null-means-everything; Draft's current sites
read only `.annotations`/are guarded; **no implicit site** feeds the evaluator a null spec — they use
`nodeSet(...)`.)

### 4. `ui.collapsed` on the view node (explicit path)
A new optional `ui: ViewUiState { collapsed: list[str] }` on the view node — a presentation sibling of
`spec`, beside `presentation`/`layout`, the evaluator ignores it. `collapsed` is the set of collapsed
`ViewGroup.key`s (`node:<id>` / `group:<seg>`, stable — `evaluateView.ts:519`; absent ⇒ expanded).
Persisted as a front-matter `ui:` blob (follow the `layout` optional-blob pattern in `views.py`;
write-when-present). **The backend stores the list verbatim — never parses a key, never evaluates,
never prunes** (ADR-0025 preserved). Added to `ViewNode`, `ViewNodeSummary` (ships with `list_views`,
so saved-view fold seeds with no extra fetch), and the ui-patch request model.

### 5. The system default view — real, listed, **read-only**, disk-materialized-on-fold
Reserved ids `view_default_<kind>`, flagged `system: true` (⇒ read-only). Spec = §3's audited whole-kind
spec; presentation = the kind's intrinsic default. It is a **first-class switcher entry** — the default
selection *and* the visible thing users **Duplicate** (the existing create-view flow, seeded from its
spec) to author their own; the designer offers **Duplicate, not Edit** on a `system` view; `save_view`
rejects a `system` id. It is **always present in `list_views`** (synthesized from the kind's spec when
no file exists); its file is written **lazily, on the first `ui` write** — visible-always, file-on-intent.

**Selection stays as-is at the store level:** `paneViews.selected[kind] === null` still means "default
selected" and the switcher's Default row still picks `null`; the frontend's `defaultView(kind)` now
returns §3's explicit whole-kind spec (not `{expr:null}`), and the *collapse layer alone* resolves the
default's persistence address to `view_default_<kind>`. Evaluation of the default is **no longer**
`{expr:null}` — it is the explicit spec, which by §3 reproduces the old data.

### 6. Persistence lifecycle + pruning
A reusable `collapseState` controller (`lib/stores/collapseState.svelte.ts`): seeds a `SvelteSet` from
`ui.collapsed`, binds into `ViewNodeList`'s `collapsed`, **debounces** the `PUT` ~600ms after the last
mutation, **flushes on unmount** (teardown + `beforeunload`). A dedicated **lock-free**
`PUT /api/views/{id}/ui` (body `{collapsed}`) writes only `ui` — it does **not** touch `spec`, does not
consult/bump the spec `revision`, and cannot 409 against a concurrent designer edit (the "two
independent lifecycles"). Stale keys (a `node:<id>` whose node vanished) are **inert** — they match no
group — so the controller prunes them **frontend-side at flush**, intersecting the persisted set with
the live `ViewGroup.key` set it already holds (backend can't prune — no evaluation).

### 7. Fold is **per-view**, not per-structure-node
Because fold hangs off the *view* node, collapsing Act 1 in the default manuscript view does not
collapse it in a filtered scene view — each view (default included) owns its fold. A view is a lens;
its fold is the lens's.

## Why / rejected alternatives
- **Rejected: keep null-means-everything.** An unspecified view returning the entire universe is the
  hack this ADR exists to remove — it hides "show everything" behind the *absence* of a spec, so the
  designer can't distinguish "I haven't defined this" from "I want all of it", and every default is
  implicitly maximal. Empty-means-empty makes "everything" an explicit, inspectable spec (§3).
- **Rejected: fold state on the structure node** (`manuscript.structure.yaml` / scene front-matter). It
  writes UI state into the authoritative, un-rebuildable structure file, and forces fold to be shared
  across every scene view — contra §7. Structure yaml is semantic truth; fold is per-lens presentation.
- **Rejected: keep `localStorage` (status quo).** Not portable, not part of the project, and it
  re-entrenches the "Draft pane is special" bypass #182/#112 remove. Fold belongs with the view.
- **Rejected: hide the default node.** The system default is a read-only, **copyable** view the user is
  meant to *see and Duplicate*; hiding it strands the starting point. A `system`/read-only flag gives
  Duplicate-not-Edit without removing it from the roster.
- **Rejected: back implicit views with a disk node too.** An implicit list offers no customization, so
  a stored view node is pure ceremony; its state (if any) belongs on the host entity it renders
  (Anton: "implicit views do not need to be backed by a real view stored on disk").
- **Rejected: fold the `ui` write into `save_view` / the spec revision-lock.** A fold toggle would then
  409 against a concurrent designer edit and bump the spec revision — coupling the two lifecycles §6
  keeps independent.
- **Rejected: the backend prunes stale keys / evaluates the equivalence.** The backend cannot evaluate
  a view (ADR-0025). Keys are inert until pruned; the frontend has the live key set (§6). The
  equivalence audit (§3) is likewise a frontend/design activity.

## Consequences
- **The null-cut has a real blast radius → the per-site equivalence audit (§3) is a gating
  deliverable.** Every `evaluateView` caller / `defaultView` consumer is inspected before `:329` flips;
  implicit consumers that leaned on null-means-everything are given an explicit in-memory spec.
- **New backend surface:** `ViewUiState` + `system: bool` on `ViewNode`/`ViewNodeSummary`; a `ui:`
  front-matter blob + `_parse_view_ui` (mind `_write_node_entry_file`'s falsy-skip); the
  `view_default_<kind>` reserved-id scheme, **always-listed synthesis**, materialize-file-on-`ui`-write,
  and `save_view` rejecting `system` ids; `GET`/`PUT /api/views/{id}/ui`. Tests: system view always
  listed + read-only, materialization idempotency, `ui` round-trip, lock-free vs spec-revision
  independence, empty-view-is-empty.
- **New frontend surface:** `defaultView(kind)` → explicit whole-kind spec; `collapseState` controller;
  `api.getViewUi`/`putViewUi`; `ViewNode`/summary/`system` type mirrors; the ViewSwitcher renders a
  `system` view read-only (**Duplicate**, not Edit). `treeActions.collapsedStructureNodes` + its
  `localStorage` load/save are **deleted** — a straight cut (pre-1.0: no migration; test projects are
  recreated, `feedback_no_pre_1_0_migrations`). Lore/Assistants keep ephemeral collapse until they
  adopt the controller (no regression).
- **`ViewNodeList`'s _collapse contract_ is unchanged by this ADR** — it already exposes
  `bind:collapsed`; this ADR only decides what *backs* that binding and what a default spec *is*, so it
  adds no collapse API. This is **not** a claim that #112 leaves `ViewNodeList` untouched: the Draft
  migration is the first consumer to **wire the escape hatches** (`onRename`/`onReorder`/`onDblClick`,
  present-but-unwired since phase 1 — ADR-0035) and may adjust the wrapper as that surface is
  exercised. Scope such changes under #112, not this ADR.
- **`ui` is the extension point** for future per-view presentation state (scroll, density) — a
  structured sibling, never a widening of `spec`.
