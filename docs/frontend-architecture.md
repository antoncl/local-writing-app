# Frontend Architecture & Refactoring Criteria

This document records the design criteria the frontend refactoring (issue #14)
is steered by, and the architecture those criteria point to. It **supersedes the
line-count framing** that originally drove the work.

## Why this exists

The decomposition of `App.svelte` and `project_service.py` was originally driven
by a "split before any file passes ~1500 LOC" rule. That rule was a useful
*forcing function* but the wrong *goal*: it says what to move away from, not what
to move toward. The result was motion without a destination.

The correction: **derive refactoring goals from design criteria, and treat line
count as a smell, not a target.** A cohesive large component can be fine; a small
file doing three jobs is not. When a file is too big it is almost always because
it violates one of the criteria below — and the fix is "extract the
responsibility / reduce to a canonical widget / move state out," not "cut lines
to hit a number."

## The diagnosis (2026-06-29 audit)

Three read-only audits of the frontend (App.svelte state ownership, the
component-event system, the existing state layer) produced one coherent picture:
a **god-component + prop-drilling** architecture.

- **App.svelte** (~3.8k LOC) holds **~13 domain server-state vars** plus ~95
  top-level `let` and 21 `$:` derivations. It fetches everything on project
  open, prop-drills it into ~20 children, and keeps derived lists coherent **by
  hand** through a `refresh*()` fan-out (≈30% of mutations re-fetch a related
  list rather than trusting the mutation's return value).
- **Events are mostly noise to the state question.** Of ~44 distinct component
  events, ~38 are trivial one-shot child→parent **signals** (mechanical to
  convert to callback props). Only **6 are real state-sync**, in two clusters:
  the **editor draft** (`change` / `metadataChange` / `inputsChange`) and
  **cross-pane derived state** (`cost-changed` / `renamed` / `embeddedTodos`).
  All six pay a **3-level re-dispatch tax through `NodeEditor`, which acts as a
  pure pass-through hub.**
- **The fix's foundation already exists.** `api.ts` is a clean, stateless fetch
  wrapper whose **mutations return the canonical next-state** (the full updated
  document or list) — so a write-through cache needs no new endpoints.
  `colors.ts` already proves the pattern: it is a `writable` store holding
  *server data* (the machine palette), read by 13 files. `theme.ts` and
  `focusTargetStore.ts` are two more working store/service precedents. There are
  **zero `.svelte.ts` rune modules** and exactly **one** trivial `setContext`
  use today — the reactive state layer is greenfield.
- **Worst offenders (and they coincide):** `SchemaTypeEditor` takes **53 props,
  20 of them two-way `bind:`** (the ~50-var schema-authoring draft block drilled
  wholesale and mutated back up — prop-drilling acting as a poor-man's form
  store). `SchemaTypeEditor` / `SchemaFieldInlineEditor` are *simultaneously* the
  worst prop-drilling and the worst CSS entanglement (the deferred composition
  cluster). The schema-authoring surface is the single highest-value target.
- **Legacy reactivity is an active tax.** `Tree.svelte` is built around a
  live-getter workaround (`getStructure`/`applyStructure` injected because the
  `structure` prop goes stale mid-turn); `NodeEditor` carries a side-effecting
  `$:` with a manual `lastSeededSceneId` guard and an inlined derivation to dodge
  a chained-`$:` race. See `memory/feedback_svelte5_reactivity_traps.md`.

Note: the project runs **Svelte 5** (`^5.16.0`) but in **legacy mode** — 45 files
use `export let`, 21 use `createEventDispatcher` (deprecated in Svelte 5), 42 use
`on:` directives, 0 use runes. "Adopt Svelte 5" therefore means "migrate to the
runes component model," and that migration is the *vehicle* for the state fix
below, not a separate effort.

## Design criteria

1. **One component, one responsibility.** Split on "more than one reason to
   change," not on LOC. Extract a sub-component when it is reused, independently
   testable, or owns its own state/lifecycle; use a snippet for inline-only
   repetition. Line count stays a *smell*.

2. **Reduce to the canonical shapes.** Every surface is one of:
   a **NodeRow**(+**NodeList**) for lists/trees; a **NodeEditor** (shell + body
   view) for editing one node; a **Configurator** for a widget that authors the
   *config object* driving another widget's behavior (ContextPicker, the
   select-options editor, the eventual 0.5.0 filter/view builder); or **named
   framework residue** (Modal, Pane, TopBar, the pickers, the metadata field
   grid). Don't fork a parallel `.foo-row`/bespoke editor — extend the canonical
   widget. (See `memory/decisions_ui_widget_taxonomy.md` and
   `memory/strategy_app_reduces_to_noderow_or_nodeeditor.md`. "Configurator" is
   the newly-named third pattern.) The CSS co-location sweep empirically
   validated this: surfaces that already reduce to NodeList+NodeRow carry ~0
   unique CSS; the ones that don't carry bespoke list/row CSS *precisely because
   they haven't been reduced.*

3. **Domain state lives in a reactive layer, not a god-component.** Server-mirrored
   data lives in a query-cache-shaped reactive store; components **read** it
   reactively; mutations go through intentful `api.ts` calls and **write the
   returned canonical next-state back into the store**. This retires
   prop-drilling, the manual `refresh*()` fan-out, and the state-sync events
   alike. **Explicitly not an event bus** (see below).

4. **Migrate to runes as each component is touched.** Callback props replace
   `createEventDispatcher`; `$props` replaces `export let`; `$state`/`$derived`
   replace `let`/`$:` (and fix the reactivity traps). Legacy and runes coexist
   per-component, so this is incremental, done *as* a component is decomposed —
   never a big-bang rewrite.

5. **Keep the framework residue small and named.** Modal, Pane, TopBar, the
   pickers, and the metadata field grid are deliberately *not* node widgets.
   That residue is the real "framework" layer; everything else collapses into a
   canonical widget.

## State architecture: a reactive layer, not an event bus

A global message dispatcher / pub-sub bus was considered (the classic desktop-UI
approach: one queue, components subscribe, everyone re-renders on a signal). It
is **rejected.** A bus buys decoupling at the cost of *action-at-a-distance* — you
cannot statically see who reacts to a signal, ordering bugs creep in, and it is
hard to type. The modern realization of the same goal (one source of truth,
components stay in sync, no manual wiring) is **reactive shared state**, which
gives decoupling *and* traceability.

The chosen model is three tiers — not one global blob:

- **Server-mirrored domain store** — a query-cache shape in `.svelte.ts` modules
  using `$state`, built on `api.ts` write-through (a mutation returns the
  canonical next-state, which is written straight into the store). Holds the ~13
  domain vars + their derivations. Generalizes the existing `colors.ts`
  precedent. This is what erases the `metadataSchema` 6-way drill, the
  `focusedDocument`/`pinnedKeys` 5-way drill, the `refresh*()` fan-out, and the 6
  state-sync events + `NodeEditor`'s pass-through tax.
- **Per-pane `$state`** — the hybrid `editorPanes` draft set (server copy + draft
  fields + pane flags). Scoped per pane, **never** global.
- **Scoped component `$state`** — the schema-authoring draft block, dialog form
  drafts. Genuinely-UI-local state (pane geometry/drag, open/closed flags) stays
  in App or a tiny UI store.

There is a narrow, legitimate place for an *imperative command* channel ("open
node X in a pane", "focus pane Y") — a handful of typed callbacks/commands, not a
global bus for all UI synchronization.

## Migration sequence (high level)

Each step is independently shippable; the detailed step-by-step plan is tracked
separately (plan mode / issue #14 task breakdown).

1. **Stand up the domain store** (`.svelte.ts`, write-through on `api.ts`) and
   move load-the-world + `refresh*()` into it; App reads from the store.
2. **Delete the worst drills** — `metadataSchema` and `focusedDocument`/
   `pinnedKeys` — by reading from the store/context in the leaf components.
3. **Collapse the editor-draft + cross-pane (B) events** into store reads,
   dissolving `NodeEditor`'s pass-through hub.
4. **The schema-authoring surface** — scoped `$state` inside `SchemaTypeEditor`
   (kills the 20 `bind:`) *together with* the CSS composition extraction
   (`SchemaFieldInline` owner). The #1 target: worst prop-drilling and worst CSS
   entanglement, fixed in one pass.
5. **Bulk-mechanical runes migration** — `export let`→`$props`,
   `createEventDispatcher`→callback props, `on:`→attribute handlers — done
   per-component as each is touched.

## Done-condition for #14 (revised)

Not "files under N lines." Instead: **every surface reduces to a canonical widget
(NodeRow/NodeList, NodeEditor, Configurator) or named framework residue; domain
state lives in the reactive layer; touched components are on runes.** Line count
is a derived smell, not the acceptance test.

## References

- `memory/decisions_ui_widget_taxonomy.md` — the three core widgets + color parts.
- `memory/strategy_app_reduces_to_noderow_or_nodeeditor.md` — the reduction lens.
- `memory/feedback_svelte5_reactivity_traps.md` — the legacy-`$:` tax runes fixes.
- `memory/project_app_styles_decomposition.md` — the CSS co-location work that
  surfaced which surfaces already reduce to the canonical widgets.
- Existing store precedents: `frontend/src/colors.ts` (server data),
  `frontend/src/theme.ts`, `frontend/src/focusTargetStore.ts`.
