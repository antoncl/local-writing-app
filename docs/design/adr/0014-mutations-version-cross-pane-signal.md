# ADR-0014: `mutationsVersion` cross-pane freshness signal

- Status: Accepted (v1.1) — 0.4.0, 2026-07-01
- Feature: #33 mid-scene lore mutations · Doc: `time-sensitive-lore-entry.md` §5 · Issue: #63
- Related: `memory/decisions_todo_as_node_index.md` (index-over-nodes precedent)

## Decision
Introduce a rebuildable **`mutationsVersion`** counter in a store, **bumped on a scene save whose
mutation markers changed**. The lore card's fetch effect keys on **`(entityId, mutationsVersion)`**,
so a mutation authored/edited/deleted in a *scene* pane invalidates an open lore card in another
pane. The signal **owns no mutation state** — mutations live in scene bodies; the index is derived;
this counter is just an invalidation tick, consistent with the index-over-nodes model.

**Fallback:** if change-detection proves fiddly, bump on **every** scene save — the card refetch is
one cheap index read, so over-invalidation is acceptable.

## Why / rejected alternative
Today `MutationTimeline` keys its refetch on `entityId` only, so a lore card open in one pane goes
stale when its mutations are authored in a scene pane (the data resolves correctly on *next* fetch —
purely a staleness-of-open-view bug). Rejected making the card own or subscribe to mutation records
directly: that would give a derived view ownership of source-of-truth state, violating the
scene-authoritative model (ADR-0001). A derived version tick is the minimal, correct fix and is
exactly what the time-travel card (ADR-0013) also needs.

## Consequences
- One store signal, watched by the card; nothing else changes ownership.
- Both #63 (staleness) and #64 (time-travel) consume it; ship the store first as a low-risk
  standalone step.
