# ADR-0027: The approachable flow — injectors, filters, and named-handle grouping

- Status: Accepted (v1) — 0.5.0, 2026-07-04
- Feature: #35 Views & Filters · #91 (UX / paradigm overhaul) · Doc: `views-and-filters.md` §1–4, §12
- Amends: ADR-0018 (adds injector/filter roles), ADR-0019 (grouping mechanism: named
  handles supersede annotate label+rank), ADR-0021 (per-segment sort), ADR-0025
  (denormalized evaluator output)
- Governed by: `memory/decisions_ui_widget_taxonomy.md`

## Context
The Venn-glyph composition graph (ADR-0018) is the right *foundation* — set algebra
composes cross-source cleanly — but exposing the bare algebra is unintuitive for the
single-source 90% case: a lone leaf "means the whole universe," and the simplest narrowing
("characters with rank ≥ 3") needs an explicit Intersect node. #91 is the reconciliation.
It keeps set-injection as the semantic foundation and makes the **authoring surface**
approachable — without reverting to boolean predicate logic.

## Decision
The designer palette gains **roles**, so the common case reads as a pipeline and the algebra
surfaces only when the graph actually branches.

**A. Injector** — a source (no input) that emits a set: today's leaves (type,
descendants-of, tag, field, hand-picked, view-ref) **plus a universal `All`** (the whole
kind universe). Semantics unchanged from ADR-0018 §1.4.

**B. Filter** — a *transform*: set in → narrowed set out, on the same predicates
(type/tag/field). AND/OR are expressed by **topology, not keywords** — filters **in series**
narrow successively (AND); parallel branches reconverging combine (OR, see D). A filter is
**authoring sugar that lowers to the shipped algebra**: `keep: p` → `intersect(input,
inject(p))`, `drop: p` → `difference(input, inject(p))`. The evaluator and `expr` grammar do
not change; filters live in the designer `layout` and compile down on save.

**C. Operation** — the explicit set combinators (∪ ∩ ∖ ¬, ADR-0018). Retained but **demoted
to the power tier**: the beginner pipeline (`All → Filter → Filter → View`) needs none.

**D. Named handles on the View = grouping.** A View (output) has **N named input handles**,
ordered top-to-bottom. This one mechanism carries grouping and makes dedupe a *visible wiring
choice*:
- **Same handle → union + dedupe.** Everything wired to one handle merges into that handle's
  single group; duplicates collapse. A flat OR is "wire both branches into one handle."
- **Across handles → ordered concatenation.** Each handle is a group; **handle order = group
  order** (drag the wire to reorder — there is no rank number). A node may appear under
  several handles (multi-membership across groups).
- The handle's **name is the group label**. A **named sub-flow / view-ref** wired to a handle
  contributes one deeper level (see E).

This **supersedes ADR-0019's label+rank grouping**: grouping is no longer an
`annotate(label, rank)` node but the View's handle structure. The standalone **Group palette
node is retired** (subsumed by handle naming + sub-flows), as is the implicit "everything
else" remainder bucket (make it explicit with a handle if wanted). **Highlight (color)
survives** as a pass-through soft overlay; a handle/group may carry an optional color; the
tinting-for-depth rule (ADR-0019) still governs nesting.

**E. Denormalized output — grouping and trees are one mechanism.** `evaluateView` returns
**rows `(node, path)`**, where `path` is the handle / sub-flow names from the outer View
inward:
- **dedupe on identical `(node, path)`** — D's same-handle rule stated precisely;
- **normalize by `path`** — 0–1 segments render flat / grouped, deeper segments render as
  nesting (the RPG-II level-break: a denormalized list carrying control keys, normalized back
  into a hierarchy);
- **handle / sub-flow order = sibling order** at each level.

Trees fall **out of** named handles + named sub-flows — they are not a separate subsystem.
**v1 emits depth ≤ 1**: a sub-flow / view-ref feeding a handle contributes its *result set*
(flat, deduped into that handle's group — exactly today's view-ref behavior). A sub-flow
contributing its *own group structure* (real nesting) is the later increment, unlocked by
teaching the renderer to walk paths deeper than one. **Nothing in the grammar or the stored
spec caps depth — only the renderer does, for now.**

**Rendering rules:** a **1-handle View renders flat** (the handle name is the list's own
title, no group header — the pipeline case); **2+ handles render as groups**.

**Sort is per-segment.** A **Sorter node sits in a branch**, before a handle, sorting *that
segment*; this is the grouping story's default. A single global `sort` on the ViewSpec
(ADR-0021) remains the fallback when no per-branch Sorter is present. Mid-graph sorting before
a union is meaningless and is not offered.

## Why / rejected alternative
The friction #91 names is real, but the obvious fix is a trap. **Rejected: a nested All/Any
boolean filter builder** (Notion/Airtable style — "match [all/any] of: predicate, predicate,
…" with per-row negation). It expresses the whole algebra in a linear list with no canvas, but
it is **predicate logic in a costume** — exactly the power-user-only surface ADR-0018 set out
to avoid. Anton's standing observation: *every* filter UI built on boolean predicates ends up
used only by programmers.

The chosen model keeps the intuitive part (spatial flow over sets) and makes it *approachable*
rather than *collapsing* it: a beginner learns one verb — drop an `All`, chain a couple of
`Filter`s — and grows into injectors + operations when a single pipe stops being enough. AND/OR
never appear as keywords; they are series vs. parallel. Dedupe is never hidden set-theory; it is
"same handle or not."

**Named handles were the unlock** (Anton): they make dedupe an explicit wiring decision *and*
turn grouping — and, by composition with sub-flows, nesting/trees — into the same mechanism,
which is why "trees" can stay a deferred feature with no separate design.

## Consequences
- **Foundation unchanged.** Filters, sorters, and named-handle grouping are an **authoring +
  serialization layer**; `evaluateView`'s membership algebra and the `expr` grammar (ADR-0021)
  don't move. The designer `layout` (already split from `expr`, commit `27cbeeb`) carries the
  friendly nodes; `graphToExpr` lowers them.
- **Evaluator output shape changes** (amends ADR-0025): `{nodes, annotations, groups}` → **rows
  `(node, path)`** + a normalize pass. Depth-1 now; deeper is a renderer increment on the same
  contract.
- **Resolves the parked n-ary-output question** (step-3 follow-up): a View handle is n-ary;
  multi-input = union+dedupe within a handle, ordered concat across handles. Operations stay
  explicit for intersect / difference / complement.
- **Closes the #91 polish items structurally**, not one by one: comparator-adapts-to-datatype
  (the op menu lives *inside* a Filter, derived from the field); single-type kinds hide Type
  (offered only when the kind has >1 entry_type); "Views over" hidden when the anchor kind comes
  from pane context; group order is handle order (the `rank` field and its hint are gone).
- **Amends ADR-0019**: annotate label+rank grouping and the standalone Group node retire;
  Highlight/color and the tint-for-depth rule survive.
- **Out of scope for 0.5.0** (restates §9): true nested rendering / trees (the depth > 1
  renderer), even though the model now expresses them.
