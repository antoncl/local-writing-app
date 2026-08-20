# ADR-0069: A view's appearance is ui state, set at the view selector

- Status: **Accepted** (re-review — supersedes the first draft's "on the spec"
  design) — 2026-08-20 (Anton). Design for #1190.
- Concern: letting the user choose **how a view's output is rendered** — the
  ADR-0066 `mode` (card/tree) + `density` axes — **per view**, without touching
  the semantic spec.
- Follows: ADR-0066 (a NodeList sets its density; the NodeRow adapts — the
  `mode`/`density` axes this feeds), ADR-0036 (per-view **non-semantic ui
  state** — the collapsed-groups set, persisted lock-free via `/ui`), ADR-0037
  §3 (grouping is view algebra; `ViewPresentation` eradicated — **the spec
  carries no presentation hint**, honoured here), ADR-0035 (a view's output is
  one `ViewResult`, `ViewNodeList`'s input).
- Relates: #1190 (this is its design).
- **Verified against `98b1cb55` (2026-08-20).**

## Context

ADR-0066 gave `NodeList` two orthogonal presentation axes — **`mode`**
(`card`/`tree`) and **`density`** (`comfortable`/`compact`/`dense`), read by
every row via context. Today the **consumer pane** sets them, not the view, and
`ViewNodeList` forwards only `mode` (`ViewNodeList.svelte:130,160,471`) — it has
**no `density` prop**. A writer can't say "show *this* view as dense cards."

Two prior decisions bound where such a choice may live:

- **ADR-0037 §3 keeps the spec presentation-free.** §3 *eradicated*
  `ViewPresentation` because the old `"tree" | "grouped" | "flat"` blob
  **conflated a genuine layout choice with a grouping decision that belongs to
  the view**; the surviving `mode` "survives *only* as `NodeList
  mode="card"|"tree"` — presentation-only" (pane-side). The backend guards it:
  the `ViewSpec` is *"never a presentation hint"* (`models_views.py:283-285`).
  So appearance **must not go on the spec** — and it needn't, because it has zero
  effect on membership or grouping.
- **ADR-0036 gives a view an orthogonal ui channel.** `ViewUiState`
  (`types.ts:649`, today `{ collapsed: string[] }`) is exactly the home for
  *non-semantic per-view UI state*. It is persisted **lock-free** via
  `api.updateViewUi(viewId, ui)` → `PUT /views/{id}/ui` (`api.ts:1225`),
  independent of the spec revision-lock, and rides `ViewNode.ui` /
  `ViewNodeSummary.ui` (`types.ts:660,681`). **But it is only *written*
  implicitly** today — by folding groups, via `CollapseState.#write`
  (`collapseState.svelte.ts:78`, the sole writer). There is no affordance for the
  user to configure it deliberately. **This is the gap #1190 fills: appearance is
  the same kind of orthogonal ui state, but user-set.**

Where the user would set it, and how it reaches render:

- **The view selector is `ViewSwitcher`**, rendered centrally by the region
  chrome in **`RegionActions.svelte:22-25`** (gated on `entry.view.switcher`,
  with `entry.view.kind` + schema already in scope) — the pane's actions rail. An
  adjacent affordance is a **sibling of `<ViewSwitcher>` there**.
- **The pane body only receives the `ViewSpec`** — `RegionBody.svelte:19` calls
  `paneViews.specFor(kind, schema)` (`paneViews.svelte.ts:145`), which returns
  only a spec; `paneViews.reload()` keeps `v.spec` and **discards `v.ui`**
  (`:102-104`), even though the roster summary carries it. So surfacing
  appearance needs `paneViews` to retain and expose `ui.appearance`.

## Decision

**Appearance is per-view ui state, set by a control beside the view selector and
persisted in `ViewUiState` — orthogonal to the spec.**

1. **`ViewUiState` gains `appearance`.** `appearance?: { mode?: "card"|"tree";
   density?: "comfortable"|"compact"|"dense" }`, beside `collapsed` — in the
   frontend type (`types.ts:649`) and the backend model (`models_views.py`). The
   `ViewSpec` is untouched; **ADR-0037 §3 stands.**

2. **A control sits next to `ViewSwitcher`.** A compact segmented control
   (card/tree, and density) in `RegionActions` (`:22-25`). Changing it writes
   `appearance` onto the resolved view's ui and persists via `updateViewUi`.

3. **`paneViews` surfaces it, symmetric with the spec.** A new accessor —
   `appearanceFor(kind)` — reads `.ui.appearance` for the resolved view
   (`resolvedViewId(kind)`, `paneViews.svelte.ts:131`), retaining `v.ui` in
   `reload()` alongside `specs`, and returns the per-kind default when the view
   is the unmaterialized `view_default_<kind>` (no summary). `RegionActions`
   (writer) and `RegionBody` (reader) both key off `entry.view.kind`, so writer
   and reader can't drift — the same symmetry the spec path already relies on.

4. **`ViewNodeList` gains a `density` passthrough; the pane feeds both axes.**
   `ViewNodeList` accepts `density` and forwards it to `NodeList` beside `mode`
   (`:471`). A pane sources `mode`/`density` from `appearanceFor(kind)` and passes
   them. **Absent `appearance` ⇒ the pane's current default** (Lore `card`,
   StructureTree `tree`, …) — a view that never set one renders exactly as today.

5. **The `/ui` blob is written whole; writers must not clobber each other.**
   `updateViewUi` rewrites the entire `ViewUiState`. Invariant: **every writer of
   the blob preserves the field it doesn't own** — the appearance writer keeps
   `collapsed`, and `CollapseState` keeps `appearance`. Concretely, `paneViews`
   owns the appearance write and merges the last-known `collapsed`;
   `CollapseState.#write` is extended to carry through the current `appearance`.
   (Lock-free, last-write-wins — acceptable for ui state; both fields change
   rarely relative to the round-trip.)

## Why / rejected alternatives

**On the spec (via `graphToSpec` / the result card)** — the first draft's design.
Rejected: it violates ADR-0037 §3 (the spec is presentation-free) and the backend
guard. Appearance has no effect on membership or grouping, so it does not belong
in the semantic, portable core. (This is the reversal that review caught before
any code.)

**In `ViewUiState` but with no user affordance.** Rejected — the user must be
able to *configure* it (the #1190 requirement). Ui state today is only written
implicitly by folding; without a control, appearance would be un-settable.

**On the canvas `ViewLayout.cfg`** (the designer result-card's config). Rejected —
the canvas layout never travels to a pane (panes get only the spec); a value
authored there could never drive rendering.

**A per-viewer / global default instead of per-view.** Rejected — the choice
should stick to *the view* (#1190), the way its fold state does, and show the
same in any pane that renders it.

## Anti-goals

- **Not a spec / grammar / evaluator change.** ADR-0037 §3 preserved; `ViewSpec`,
  `graphToSpec`, and both view runtimes are untouched. Appearance is inert to
  `evaluateView`.
- **Not a new `NodeRow` prop.** It feeds `NodeList`'s existing `mode`/`density`
  axes (ADR-0066).
- **Not a per-viewer / global setting.** Per view, through the same ui channel as
  collapse.
- **Not forced onto untouched views.** Absent `appearance` ⇒ pane default.
- **No pre-1.0 migration.** A stored view with no `ui.appearance` renders on the
  default — absent means "as today".

## User journey (definition of done)

A writer opens a pane, picks a view from the switcher, and — right beside it —
flips the layout between **cards** and a **tree** and chooses the **density**. The
choice sticks to that view (persisted like its fold state) and shows the same
next time, in any pane that renders the view. A view that's never been touched
keeps its pane's default look. `svelte-check` stays clean; existing view/ui tests
pass; a new test asserts a view with `ui.appearance` renders at that mode/density
and that an appearance write preserves `collapsed`.

## Consequences

- `ViewUiState` gains `appearance` (frontend type + backend model + its
  round-trip).
- A segmented control lands in `RegionActions` beside `ViewSwitcher`.
- `paneViews` retains `v.ui` and exposes `appearanceFor(kind)` + an appearance
  writer; `CollapseState` is made appearance-preserving.
- `ViewNodeList` gains `density`; panes pass `mode`/`density` from the accessor.
- The two ui-state concerns (collapse, appearance) share one lock-free blob under
  a preserve-the-other-field invariant.

## Slice plan

- **S1 — `density` passthrough on `ViewNodeList`.** The prerequisite one-liner
  (`:471` gains `{density}`, a prop defaulting to the consumer value). Ships
  alone, no behaviour change.
- **S2 — `ViewUiState.appearance` end to end (no control yet).** The field
  (front + back), `paneViews` retaining `ui` + `appearanceFor`, the merge-safe
  write, and `ViewNodeList`/pane reading it. A hand-set `ui.appearance` already
  takes effect and round-trips without clobbering `collapsed`.
- **S3 — the control.** The segmented card/tree + density control beside
  `ViewSwitcher` in `RegionActions` — the user affordance.
- **S4 (optional) — per-kind defaults** in `appearanceFor` when unset, so even an
  untouched view can lead with a sensible look.
