# ADR-0026: Type-aware Jinja helpers on a shared entry_type-ancestry primitive

- Status: Accepted (v1) — 0.5.0, 2026-07-03
- Feature: #35 Views & Filters · Doc: `views-and-filters.md` §8, §8.1 · Issue: #35
- Governed by: `memory/decisions_prompt_model.md`, `docs/metadata-strategy.md`, `memory/reference_roadmap.md` (1.0 template-surface freeze)

## Decision
Add an **inheritance-aware type predicate** to the Jinja template surface so a prompt's
logic can branch on an entry's type family:

- **`is_a(node, "lore:character")`** → bool, true when the node's entry_type **equals or
  descends from** the given FQN. Registered in `register_helpers()` (the
  `env.globals["…"] = …` pattern, `helpers.py:390–407`).
- (Optional) `kind_of(node)` → entry_type FQN string, shipped only if a call site needs it
  (`entry.entry_type` largely covers it once FQN-qualified).

Both the view **`descendants-of` leaf** (frontend evaluator) and this helper (backend) use
**one shared `entry_type_ancestry` primitive** in the schema service — given an FQN, its
ancestor/descendant chain via `parent:` (schema inheritance resolution, `schema.py:832`).
Built once; exposed in the schema payload for the frontend, called directly backend-side.

## Why / rejected alternative
Today templates can only test `entry.entry_type == "character"` — exact match, no
inheritance, no FQN. A `deity` (which `parent:`-inherits `character`) fails that test, so a
prompt written "for characters" silently skips deities. An inheritance-aware `is_a` makes
prompt logic track the type hierarchy the schema already models, and is exactly the
membership question the view `descendants-of` leaf answers — so the ancestry computation is
built once and shared, not duplicated across the frontend evaluator and the backend
template engine.

Rejected **exact-match-only** (status quo) — breaks the moment sub-types exist, which is the
whole point of the inheritance model. Rejected **duplicating** ancestry logic in templates
vs. the evaluator — one canonical primitive avoids drift. Rejected a **string-prefix hack**
on FQNs (`entry_type.startswith("lore:")`) — that tests *kind*, not the `parent:` chain, and
misses cross-branch inheritance.

## Consequences
- Depends on **#77** (FQN) for the qualified argument form, and on the shared ancestry
  primitive (build step 1 / #78). Sequenced as build step 6 — backend-only, independent of
  the view UI steps.
- **Additive to the template surface**, so pre-1.0 is the right time (the surface freezes at
  1.0; additions stay allowed after, existing shapes don't change).
- The primitive is the single source of truth for "is X a kind-of Y" across the app.
