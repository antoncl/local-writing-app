# ADR-0020: Views are kind-anchored; the universe is all nodes of that kind

- Status: Accepted (v1) — 0.5.0, 2026-07-02
- Feature: #35 Views & Filters · Doc: `views-and-filters.md` §1.1, §1.4 · Issue: #35, #77
- Governed by: `memory/architecture_class_instance_model.md`

## Decision
A view is anchored to exactly **one kind**. Its **universe** — the set complement is taken
relative to — is *all nodes of that kind in the project* (all lore entries, or all scenes, or
all assistants). Cross-kind views / smart folders are out of scope.

Entry_type references inside a view expression use the **kind-qualified FQN** form
(e.g. `lore:character`), per #77.

## Why / rejected alternative
Complement ("NOT tagged gotham") is meaningless without a universe to subtract from. Anton
pinned the answer: when generating a view on lore, the universe is all lore; same for scenes,
same for assistants. Anchoring to the pane's kind makes complement total and well-defined,
matches the already-kind-scoped panes, and keeps the algebra closed.

Rejected an **unbounded / cross-kind universe** — complement would be ill-defined or explode
to "every node in the project", and #35 explicitly scopes smart folders out. Pickers that
legitimately span kinds are handled by holding **one source per kind and unioning**
(ADR-0023), not by widening any single view's universe.

Entry_type identity **must** be unambiguous before views serialize it: today entry_type keys
are global dict keys with no per-kind namespacing and no uniqueness check — a silent
last-layer-wins clobber at schema merge. That is #77, a **prerequisite that lands first**.

## Consequences
- A view file records its `kind`; the designer and evaluator both key off it.
- `descendants-of(lore:character)` and every FQN leaf is unambiguous only once #77 ships.
- Cross-pane narrowing (a Draft filter auto-narrowing Lore) stays out of v1 (doc §7).
