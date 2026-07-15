# ADR-0022: Every NodeList is backed by a view; presentation ∈ {tree, grouped, flat}

- Status: Accepted (v1) — 0.5.0, 2026-07-02; **amended 2026-07-15 (runtime view surface = ONE central reused component owning selection + binding; ADR-0032 §D Amdt 1)**
- Feature: #35 Views & Filters · Doc: `views-and-filters.md` §3, §5 · Issue: #35
- Governed by: `memory/decisions_ui_widget_taxonomy.md`, `memory/decisions_todo_as_node_index.md`

## Decision
**Every NodeList renders through a view** — most implicit and fixed, some user-switchable. A
view's **presentation** is one of `tree-from-structure` / `grouped` / `flat`. The set machinery
handles *membership and annotation* in all three; label-grouping (ADR-0019) applies only to
`grouped`/`flat`, never `tree`.

v1 exposes a **switcher** on **Lore, Draft, Assistants** only. All other NodeList sites (Prompts,
Chats, Mutations panes; pickers, add-menus, BacklinksPanel, MutationTimeline, SchemaTreePane,
ReferencePicker) render **fixed** views expressing their current shape.

## Why / rejected alternative
The inventory (2026-07-02: 12 NodeList sites + 3 hand-rolled lists) showed every list already
*is* a view over nodes — grouped-by-type, tree-by-structure, flat — just hardcoded. Naming that
invariant unifies the surfaces and makes "switchable views" an incremental exposure, not a new
subsystem. Anton pinned the v1 switcher set to Lore/Draft/Assistants (the three where grouping/
ordering pay off first).

**Tree is a shape, not a grouping.** Draft (manuscript structure) and Prompts (subtype nesting)
render *hierarchies*; the annotate model gives one grouping level, not recursion. Rather than
stretch set algebra to express trees, presentation names the shape and grouping composition
applies only to the flat/grouped shapes. Filtering a tree drags in **ancestor visibility** (a
matching scene needs its non-matching act/chapter kept visible) — deferred; the Draft tree gets
**color annotations only** in v1, which still delivers metadata-driven visual filtering there.

Rejected **membership-filtering the Draft tree in v1** (ancestor-visibility complexity).
Rejected folding **Search/Todo/cost-breakdown** into views now: Search is a natural later
adoption (a search *is* an ad-hoc view), Todo is an index over markers (todo-as-node-index — it
stays out), the cost breakdown isn't a node list.

## Consequences
- A behavior-identical refactor step: express current Lore/Draft/Assistants shapes as implicit
  default views and route their NodeLists through `evaluateView` (verifiable — output unchanged).
- The pane persists its **last-selected view** in UI state, not in the project (the *views* are
  project data; the *selection* is not).
- Prompts/Chats/Mutations get fixed views now, switchers later.

## Amendment (2026-07-15) — the runtime view surface is ONE central reused component
Superseding the v1 framing where App positions a standalone `<ViewSwitcher>` in each pane's handle
bar: **view selection *and* actual→formal parameter binding are owned by one central, reused
component** (the render surface — ADR-0032 §D Amendment 1), because they are **inseparable** — the
selected lens fixes the formals, hence *whether and which* parameter controls instantiate, so the
selector is part of parameter instantiation, not a component that can be owned apart from it. The
selector is **positioned** as pane-handle-bar chrome but is **part of that one component**, not a
per-pane widget a caller wires in. "v1 switcher on Lore/Draft/Assistants only" becomes a prop/config
on the one component (an **exposure** decision), never a licence to fork or re-place it. Chosen for
the stronger guard against per-caller divergence (one component, no seams for functionality to drift
across panes) and because the two concerns don't cleanly separate.

**Code follow-up (tracked, not yet done):** the current per-pane `<ViewSwitcher>` wiring in
`App.svelte` (`loreActions` / `outlineActions` / `assistantsActions`) folds into the central
component; App stops hand-placing the selector per pane.
