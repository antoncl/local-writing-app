# ADR-0023: NodePickerConfig = sources (ViewSpecs/refs) + mechanics

- Status: Accepted (v1) — 0.5.0, 2026-07-02
- Feature: #35 Views & Filters · Doc: `views-and-filters.md` §6 · Issue: #35
- Governed by: `memory/decisions_inputs_fields_uniformity.md`

## Decision
`NodePickerConfig` splits into **membership** and **mechanics**. Membership becomes
`sources: [ViewSpec-or-view-ref]` — **one source per kind**, unioned across sources. Mechanics
(`multiple`, `allow_target_marking`, `presets`) stay picker-local. Today's `{kinds, entry_types}`
is exactly the degenerate one-leaf inline ViewSpec; the format flips wholesale, pre-1.0, no
migration, across all three storage sites: schema field `picker_config`, prompt input `target`,
`tags.yaml` scopes.

**Not unified in v1:**
- **Tag scopes** keep the degenerate type-leaf subset (same ViewSpec format, restricted `expr`).
- **Editor UI**: `NodePickerConfigEditor` keeps its simple checkbox-tree form (emitting a
  degenerate ViewSpec) plus one addition — "…or use a saved view" (a `view-ref`). The full
  Venn-graph canvas ships once, for the designer.

## Why / rejected alternative
`NodePickerConfig` today conflates *which nodes are pickable* (membership — an impoverished view
language: kinds + entry_types only, no tags, no predicates) with *how the picker behaves*
(mechanics). Separating them lets the **same ViewSpec language** drive panes and pickers, so a
saved view is reusable as a picker constraint (`view-ref`) — Anton called this "elegant". The
per-kind `sources` list reconciles the tension that views are kind-anchored (ADR-0020) while
pickers legitimately span kinds (context_pick offers scenes *and* lore): one source per kind,
union, dropdown still groups by kind. It also matches the existing `entry_types: Record<kind, …>`
shape, which was already per-kind.

Rejected **growing NodePickerConfig's flat fields** (add a `tags` list, etc.) — it perpetuates a
second, overlapping filter vocabulary; the inversion (config *delegates to* a ViewSpec) removes
the duplication. Rejected **full-expression tag scopes in v1** — scope enforcement is backend-side
(`metadata_values.py` auto-broadening), so arbitrary expressions would force a backend evaluator
into v1, and tag-dependent tag scopes are self-referential. Rejected **unifying the editor UI** —
unify the *language and evaluator*, not the authoring surface; that keeps 0.5.0 tractable.

## Consequences
- A format change rippling three storage sites → land the ViewSpec schema **early** (build step 1)
  so nothing downstream serializes the dead shape.
- Assistant picker scoping (ADR-0024) rides `sources` with no bespoke mechanism.
- Tag scopes are "unified on paper" (ViewSpec format) without the evaluator machinery.
