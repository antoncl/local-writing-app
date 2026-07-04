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
- `sort` includes a **manual/stored-order** option — load-bearing for Assistants (ADR-0024).
