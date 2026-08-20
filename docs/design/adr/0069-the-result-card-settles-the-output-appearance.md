# ADR-0069: The result card settles the output's appearance

- Status: **Accepted** — 2026-08-20 (Anton). Design for #1190.
- Concern: letting a **view** decide how its output is rendered — the ADR-0066
  layout axes (`mode` = card/tree, `density` = comfortable/compact/dense) —
  instead of the layout being fixed by whichever pane happens to render it.
- Follows: ADR-0066 (a NodeList sets its density; the NodeRow adapts — the
  `mode`/`density` axes this ADR feeds), ADR-0035 (a view's output is one
  `ViewResult`, and that is `ViewNodeList`'s input), ADR-0037 / ADR-0038 (the
  view designer; per-node config is edited **inline in the node card**),
  ADR-0041 / #277 (the `ViewExpr` IDL — the semantic `ViewSpec` panes receive).
- Relates: #1190 (this is its design).
- **Verified against `98b1cb55` (2026-08-20).**

## Context

ADR-0066 gave `NodeList` two orthogonal presentation axes — **`mode`**
(`card` | `tree`) and **`density`** (`comfortable` | `compact` | `dense`) — read
by every row through context. But **the consumer pane sets them today, not the
view.** So every view shown in a given pane looks the same, and a writer can't
say "render *this* view as dense cards" while another stays a comfortable tree.
The rendering machinery already exists; what's missing is a way for the view to
select it and carry that choice wherever it's shown.

The relevant shape of the view system, verified against `98b1cb55`:

- **A designed view persists two parallel forms.** The semantic, portable
  **`ViewSpec`** (`types.ts:592` — `{ kind, expr? | groups?, sort?, params?,
  group_by? }`, the ADR-0041 IDL) and a canvas **`ViewLayout`** snapshot
  (positions + per-node `cfg`, `ViewNode.layout`, `types.ts:657` — "absent for
  designer-less views"). Both hang off the `ViewNode` (`spec` at `types.ts:656`).
- **Only the `ViewSpec` reaches a pane.** A pane assembles `{ spec, universe,
  schema, referenceIndex }` and hands it to `ViewNodeList`, which owns evaluation
  (`ViewNodeList.svelte` — `evaluateView` → `ViewResult` → render). The canvas
  `ViewLayout` never travels to the pane.
- **The designer flow has a terminal "result" node.** Kind `output` — the single
  sink of the DAG (`viewGraph.ts:46`), labelled **"View result"** in the
  designer. It already carries **settable per-node config** (its group input
  handles + per-handle `group_by`), edited **inline in the card** (the ADR-0038
  pattern), and `graphToSpec` lowers that config into `spec.groups` /
  `spec.group_by`. It is the natural home for "how the output looks."
- **`ViewNodeList` forwards only `mode`.** It accepts a `mode` prop
  (`ViewNodeList.svelte:130,160`) and passes `{mode}` to `NodeList`
  (`:471`) — it has **no `density` passthrough yet**.
- **Not every view has a result card.** Default/implicit views
  (`defaultView(kind)`), built-in views, and `result`-driven (non-designed)
  lists are synthesized `ViewSpec`s / plain node-sets with **no flow and no
  output node**.

## Decision

**Appearance is a property the writer sets on the "View result" card; it is
stored as a spec-level field and read by `ViewNodeList` to drive the ADR-0066
axes. A view with no result card falls back to the pane default.**

1. **The result card is the editing home.** The `output` ("View result") node
   grows an inline control for `mode` + `density`, exactly mirroring how its
   group handles are edited today (ADR-0038 inline per-node config). This is the
   card that "settles the appearance of the output."

2. **Appearance is stored on the `ViewSpec`, not the canvas layout.** A new
   optional field — `spec.layout = { mode?, density? }` — is **lowered by
   `graphToSpec`** from the output node's `cfg`, sitting **beside `sort` /
   `group_by`**, i.e. on the `ViewSpec` wrapper and **not inside the `ViewExpr`
   query tree**. It is stored on the spec because **the spec is the only thing a
   pane receives** — a property living only in the canvas `ViewLayout.cfg` would
   never reach rendering. (The canvas layout still snapshots the node `cfg`
   verbatim for author-arrangement restore; the semantic source that *travels*
   is `spec.layout`.)

3. **`ViewNodeList` reads `spec.layout` and feeds `NodeList`.** It maps
   `spec.layout.mode` / `spec.layout.density` onto `NodeList`'s existing axes.
   **Prerequisite:** `ViewNodeList` gains a `density` passthrough (it forwards
   only `mode` today, `:471`).

4. **A cardless view keeps the pane default.** Default / built-in /
   `result`-driven views have no output node, so `spec.layout` is absent →
   `ViewNodeList` falls back to the consumer-supplied `mode`/`density` (today's
   behaviour). Optionally `defaultView(kind)` may seed a sensible per-kind
   default. So: **the result card settles a *designed* view's appearance; a
   cardless view stays on the pane default.**

## Why / rejected alternatives

**Put the layout inside the `ViewExpr` grammar / IDL.** Rejected — layout is
*presentation* (how the result is drawn), not *query semantics* (which nodes are
in it). Keeping it out of `ViewExpr` keeps the IDL and both runtimes pure. It
rides the `ViewSpec` wrapper beside `sort` / `group_by`, which are already
spec-level knobs, not part of the expression tree.

**Store it only on the canvas `ViewLayout.cfg`.** Rejected — panes never receive
`ViewLayout`, only `ViewSpec` (`types.ts:656-657`). A layout property that lived
only on the canvas snapshot would be invisible to every pane that renders the
view. It must be lowered into the spec to have any effect.

**Leave it a pane prop (status quo).** Rejected — that is precisely what #1190
asks to change. The layout should travel *with the view*, so the same view reads
the same in any pane.

**A separate per-view "display settings" panel, divorced from the flow.**
Rejected — the `output` node is the discoverable, already-present home for
"what the result is and how it reads," and reusing the inline per-node-config
pattern (ADR-0038) avoids a second settings surface. This is the user's own
model: that card settles the output's appearance.

## Anti-goals

- **Not a `ViewExpr` grammar or evaluator change.** Presentation only; the
  `ViewResult` and the two runtimes are untouched. `spec.layout` is inert to
  `evaluateView`.
- **Not a new `NodeRow` prop.** NodeRow already adapts via context (ADR-0066);
  this only feeds `NodeList`'s existing `mode`/`density` axes.
- **Not forcing a layout on cardless views.** Absent `spec.layout` ⇒ the pane
  default, exactly as today.
- **No pre-1.0 migration.** A stored view without `spec.layout` renders on the
  default — absent means "as before", so nothing to migrate.

## User journey (definition of done)

A writer designs a view, expands its **View result** card, and picks how the
output reads — **cards or tree**, and **comfortable / compact / dense**. The
choice saves with the view and travels wherever the view is shown, so the same
view looks the same in every pane that renders it. A default (undesigned) view,
or a plain node list, keeps its pane's default look — nothing about those
surfaces changes. `svelte-check` stays clean and the existing view tests pass.

## Consequences

- `ViewSpec` gains an optional `layout` field; `graphToSpec` lowers it from the
  `output` node `cfg`; the canvas `ViewLayout` round-trips the same `cfg`.
- `ViewNodeList` gains a `density` passthrough and reads `spec.layout`.
- `ViewFlowNode`'s `output` block gains the `mode` / `density` controls.
- Cardless views are unaffected (absent ⇒ pane default).
- Future appearance knobs (beyond the two axes) have a defined home: the result
  card → `spec.layout`.

## Slice plan

- **S1 — `density` passthrough on `ViewNodeList`.** The prerequisite one-liner
  (`:471` gains `{density}`, a prop defaulting to the consumer value). Ships
  alone, unlocks the rest, no behaviour change on its own.
- **S2 — `spec.layout` on `ViewSpec` + `graphToSpec` lowering.** The field, its
  round-trip through the canvas `cfg`, and `ViewNodeList` reading it to set
  `mode`/`density`. No UI yet — a hand-set field already takes effect.
- **S3 — the output-card controls.** The `mode`/`density` picker inside
  `ViewFlowNode`'s `output` block (the editing surface, ADR-0038 inline pattern).
- **S4 (optional) — per-kind defaults.** Seed a sensible `mode`/`density` in
  `defaultView(kind)` so even undesigned views can lead with a good look.
