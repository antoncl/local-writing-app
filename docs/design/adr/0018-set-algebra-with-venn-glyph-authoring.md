# ADR-0018: Views are set algebra, authored as a Venn-glyph composition graph

- Status: Accepted (v1) — 0.5.0, 2026-07-02
- Feature: #35 Views & Filters · Doc: `views-and-filters.md` §0–1 · Issue: #35
- Governed by: `memory/decisions_ui_widget_taxonomy.md`

## Decision
A view's membership is expressed as **set algebra** — union, intersection, difference,
complement — over sets of nodes, **not** as boolean predicate expressions (AND/OR/NOT).
The two are isomorphic (∪=OR, ∩=AND, ∖=AND-NOT, complement=NOT), so nothing is lost.

Views are authored in a **drag-and-drop composition graph** (a DAG with one output node),
where each combinator node carries a **Venn-diagram glyph** with the result region filled
(the Figma/Illustrator boolean-ops pattern). Library: **Svelte Flow (`@xyflow/svelte` 1.0)**,
verified as a native Svelte-5/runes rewrite. There is **no text DSL** in v1 — the graph is
the authoring surface.

## Why / rejected alternative
Every filtering UI Anton has built or seen ends up power-user-only. The diagnosis is
**boolean predicate logic gets tricky fast** and **the UIs are lousy** — not that
expressiveness was lacking. So the fix targets *representation*, not *power*: people have a
working intuition for sets-of-things they lack for predicate logic, and non-designers use
Venn-glyph boolean ops (Figma) daily without knowing the word "boolean".

Rejected **boolean operators** (the industry default) — the thing being replaced. Rejected a
**literal interactive Venn canvas** — famously breaks past 2–3 sets; the glyph is an *icon on
a graph node*, not the geometry itself. Rejected a **text DSL for v1** — it recreates exactly
the power-user cliff; #35's "GUI vs DSL" question dissolves in favor of the graph.

## Consequences
- **Difference is not commutative** and is the op most likely to confuse the target user:
  its ports carry explicit *keep* / *remove* roles and the glyph shows which lobe survives —
  a hard requirement, not polish.
- **Complement requires a universe** — see ADR-0020 (kind-anchored).
- Most real views are 2–3 nodes deep; the graph serializes to the `expr` tree in ViewSpec
  (ADR-0021).
- Svelte Flow is a new frontend dependency, likely reused by the 0.6.0 workspace overhaul.
