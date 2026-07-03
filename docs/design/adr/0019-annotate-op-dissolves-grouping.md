# ADR-0019: The annotate op — grouping and coloring dissolve into the expression graph

- Status: Accepted (v1) — 0.5.0, 2026-07-02
- Feature: #35 Views & Filters · Doc: `views-and-filters.md` §1.3 · Issue: #35
- Governed by: `memory/decisions_ui_widget_taxonomy.md`

## Decision
Grouping is **not** a separate view primitive. A view carries a fifth node type, **annotate**,
a *pass-through* that stamps the members of its input set with a payload and forwards the set
unchanged (it never filters). Two payloads:

- **Label** → *hard grouping*. Output nodes carry zero or more labels; the list groups by
  label. A node with two labels appears in **both** groups. Unlabeled nodes fall into an
  implicit **"everything else"** bucket, last. Each annotate node carries an explicit **rank**
  that orders the groups.
- **Color** → *soft grouping*. Tints matching rows in place without re-partitioning, supplying
  the **existing NodeRow color-part slot** (the same slot entry_type colors feed). A view
  color overrides the type color for the rows it covers.

## Why / rejected alternative
The epic listed Group as a primitive alongside Predicate/Sort. But Anton's own grouping
problem — roll `character`+`deity`+… into one "Characters" group in some views, keep "Deities"
separate in others — is just *a user-composed list of named sets*, which the set algebra
already expresses. Making grouping a graph annotation means there is **no parallel grouping
structure** in the view file: the `expr` tree *is* the grouping. Multi-membership (node in
several groups) and the implicit remainder bucket fall out for free.

Coloring came from Anton's "coloring or labeling operation" idea. Keeping it the *same op*
with a different payload gives a **soft** grouping (findable-at-a-glance without re-partition)
for free — e.g. tint the Gotham entries while keeping the type grouping.

Rejected a **standalone Group primitive** (parallel named-set list) — redundant with the
algebra, and it would need its own multi-membership + ordering rules that annotate already has.
Rejected a **new color treatment** — violates the widget-taxonomy decision; color rides the
existing NodeRow color part.

## Consequences
- Group order lives on the annotate node's **rank** (alphabetical is wrong often enough that
  order needs an explicit home).
- Color precedence: view color overrides entry_type color for covered rows.
- The Draft tree can't re-group (structure owns its shape) but **accepts color annotations** —
  "tint Honor's scenes" over the hierarchy (ADR-0022).
- Grouping applies only to `grouped`/`flat` presentation, not `tree` (ADR-0022).
- **User-facing naming:** "annotate" is internal only. The designer palette surfaces **two
  nodes — "Group" (name → restructuring bucket) and "Highlight" (color → in-place emphasis)**
  — both compiling to the one annotate op, because the two payloads are two distinct user
  intents. A single umbrella verb ("Mark") misdescribes one of the two and collides with the
  mutation-"marker" vocabulary. A Group may also carry a color.
- **Tinting for depth:** where color and grouping combine (a Highlight within a Group, or —
  later — nested groups), each level's color is a **programmatic tint of the base color**
  (computed shade of the existing NodeRow color part, not a new treatment). v1 ships flat
  rank-ordered groups + optional color; true nested grouping is deferred but inherits the tint
  rule when it lands.
