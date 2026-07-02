# ADR-0001: Mutations stored as self-contained scene-body markers (Model A)

- Status: Accepted — 0.4.0 planning, 2026-07-01 · **Amended 2026-07-02: multi-row carrier (ADR-0016)**
- Feature: #33 mid-scene lore mutations · Doc: `docs/design/mid-scene-lore-mutations.md` §3

> **Amendment (2026-07-02, ADR-0016)** — the grammar gains a **multi-line carrier form** for a
> multi-field authored change (one comment: head + one `field=` row per line, each row with its
> own id). The single-line marker below is the degenerate one-row form and parses unchanged.

## Decision
Store each mutation as a **self-contained HTML-comment marker in the scene body**, at the prose
position where the change happens, carrying `entity` (lore id) + `field` (key) + url-encoded
`value` + a **client-minted `id`**:

```
<!-- mutate:entity=<lore-id>;field=<field-key>;value=<url-encoded>;id=<marker-id> -->
```

Lore files hold **base state only**; the `mutations_by_entity` index is derived (`.cache/`,
rebuildable). Insertion is an ordinary scene save — no create route.

## Why / rejected alternative
The rejected model (B) makes the marker a *pointer* to a central store of `(entity, field,
value)`. That creates a **second source of truth**, splits the mutation's *position* (in prose)
from its *data* (in a file) — which fights position-granular resolution (ADR-0003) — and needs
orphan sync when scenes move or delete. Model A keeps scenes self-contained and authoritative:
markers travel with the prose, so moving a scene moves its mutations and deleting a scene deletes
them. Position is semantically meaningful and lives with the prose, so the data must too. This
also mirrors the shipped embedded-todo marker pattern.

Recurring-state DRY (a werewolf transforming many times) is handled as an **authoring
convenience** (a saved transformation set re-applied), not by pointers. True single-point-edit of
a recurring state is a deferred opt-in "linked mutation," and does not justify a pointer model for
*all* mutations.

## Consequences
- Lore-card display and the time-slider read the derived index (a pre-ordered per-entity slice);
  a full all-scenes scan happens only on a cold cache rebuild.
- The client mints the marker id (embedded-todos do the same — the backend scan expects the id
  present; `PATCH`/`DELETE` rewrite in place).
- The grammar is **forward-compatible**: `op=add` (additive), a close-marker referencing an id
  (interval close), and a `knower=<id>` scope (per-knower) are all additive, leaving v1.0 markers
  untouched.
