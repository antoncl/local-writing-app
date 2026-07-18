# ADR-0021: Saved views are frontmatter-only nodes; ViewSpec is the portable core

- Status: Accepted (v1) — 0.5.0, 2026-07-02
- Feature: #35 Views & Filters · Doc: `views-and-filters.md` §1.4, §2 · Issue: #35
- Governed by: `memory/architecture_class_instance_model.md`, `memory/feedback_chat_as_node_validation.md`

## Decision
**ViewSpec** = `(kind, expr, sort)` is the portable membership+ordering core, with two carriers:

1. **A saved view** = a **frontmatter-only Node** of new kind `view` (folder `views/`, no body):
   name + ViewSpec + presentation hints.
2. **An inline anonymous ViewSpec** — the same schema embedded where a membership constraint
   lives (picker configs, ADR-0023) — no node.

The **leaf vocabulary** (`expr` terminals): `type` (exact FQN), `descendants-of` (inheritance-
aware), `tag`, `field predicate` (authored with the field's own widget), `hand-picked` (the one
**static** leaf, chosen via NodePicker), `view-ref` (embed a saved view; cycle-checked at save).

## Why / rejected alternative
Making a saved view a Node gets CRUD, listing, naming, and project-versioned persistence for
free, and makes the view *designer* just another NodeEditor body view — the chat-as-node lesson
(resist bespoke subsystems). It answers #35's persistence question: views are project-scoped
(a single-user local app needs no per-user views).

Rejected a bespoke **`views.yaml`** store — exactly the "model a first-class thing as an ad-hoc
list" trap; it would forgo the node surfaces and layered behavior.

The **static/live split** is deliberate: `type`/`descendants-of`/`tag`/`field` leaves are live
queries (membership tracks project changes); `hand-picked` is a snapshot enumeration ("my
problem scenes") that no predicate offers. Mixing them in one view is useful; the designer
shows which is which. `view-ref` is where views-as-nodes pays off — define "Gotham cast" once,
reuse it in a pane, a picker constraint, and a prompt source.

## Consequences
- `view` joins the kind whitelist — re-read `docs/metadata-strategy.md` class-instance
  invariants first.
- Field-predicate leaves need their fields present in the frontend node summaries — a
  **payload-width** concern to verify at build (ADR-0025), not an evaluator concern.
- `view-ref` needs **cycle detection at save** (views are nodes; ref cycles are real).
  *(Retired by Amendment 1 — the `view-ref` leaf is gone.)*
- `sort` includes a **manual/stored-order** option — load-bearing for Assistants (ADR-0024).

## Amendment 1 — Drop the `view-ref` leaf (stored-view inclusion) (0.7.0)

- Status: Accepted — 0.7.0, 2026-07-18
- Amends: §Decision (the leaf vocabulary — removes `view-ref`) and the §Consequences
  "cycle detection at save" line (retired with the leaf).
- Closes: #276.

### Context
The `view-ref` leaf let one view's `expr` **embed another saved view** — the "define 'Gotham
cast' once, reuse it inside other views" idea in §Why. In practice this reuse-inside-a-view
never earned its keep: across the 0.5–0.7 view work no shipped view used it, and it carried a
disproportionate tail of machinery — a frontend `resolveView` resolver threaded through every
pane, a runtime `viewStack` cycle guard, `evalViewRef`/`evalViewRefRows`/`isBareViewRef` in the
evaluator, and a whole backend save-time cycle checker (`_check_view_ref_cycles` +
`_collect_view_refs`). The #275 max review also found that walker had already drifted (it walked
`nest.parents/children` but not the new `orphans_nest`), so a `view-ref` buried in an
orphans-only Nest escaped cycle detection — a latent bug the leaf was still accruing.

### Decision
Remove the `view-ref` leaf. The `expr` leaf vocabulary is now **`type` / `descendants-of` /
`tag` / `field predicate` / `hand-picked`** — no view embeds another view.

**Scope — what this does NOT cut** (the naming invites confusion):
- **Saved views as nodes** (carrier 1) stay entirely: CRUD, the roster, pane selection, the
  ViewSwitcher, per-pane default views. This amendment touches the *leaf that references one
  view from inside another*, nothing about views-as-nodes.
- **The NodePicker "…or use a saved view" source** (ADR-0023, the `{view: <id>}` picker source)
  is a **separate live feature** and is untouched. A picker sourcing its candidates from a
  saved view evaluates that view's own spec directly — it never went through the `view-ref`
  leaf. ADR-0023's incidental "(a `view-ref`)" phrasing predates this split; read it as "a
  reference to a saved view *as a picker source*," not this leaf.

### Consequences
- The §Consequences "cycle detection at save" line is retired: with no `view-ref`, **cross-view
  cycles cannot exist**. The only cycles left are intra-view wiring, held acyclic at authoring
  time by `isValidConnection` and repaired on load by `cycleCheck.ts` (both designer-graph and
  stored-spec surfaces, #275). No save-time backend guard is needed, and the drifted
  `orphans_nest` walker gap is mooted rather than patched.
- The designer palette loses its **"Saved view"** source; `specToGraph`/`graphToSpec`, the
  `ViewGlyph`/`nodeSummary`/`ViewFlowNode` leaf surfaces, and `paneViews.resolveView` all drop.
- Other ADRs that mention `view-ref` in passing (0027 injector list + sub-flow depth-≤1 note;
  0028 §1.4 leaf list; 0031/0036/0037 evaluator plumbing; 0038 structural-selector list) are
  left as **point-in-time records** — their `view-ref` references now read as historical, not
  as live grammar.
