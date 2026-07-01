# ADR-0010: Interval close is a separate close-marker

- Status: Accepted (v1.1) — 0.4.0, 2026-07-01
- Feature: #33 mid-scene lore mutations · Doc: `mid-scene-lore-mutations-v1.1.md` §2 · Issue: #59
- Implements: the "optional end" of ADR-0002's independent-interval model

## Decision
An interval is closed by a **separate marker at the close position**, referencing the start
record's id:
```
<!-- mutate:close;ref=<start-marker-id>;id=<close-marker-id> -->
```
The end of an interval is a different point in the prose than its start, so the close must live where
it happens — it cannot be an attribute on the start marker. `close` is **op-agnostic** (closes a
replace, add, or remove record alike) and carries its own id (editable/deletable like any marker).

A record with start `S` closed at `C` is **live at `P` iff `S ≤ P < C`** (close exclusive); absent a
close, live to end-of-book. Revert carries **no stored prior value**: when a closed replace record
expires the field recomputes to the next-latest-started still-live replace record (ultimately base);
a closed add/remove simply leaves the live set (ADR-0002 consequence).

Authoring: `/mutate close` at the cursor lists records **live there**; picking one — or a co-authored
group (v1.0 §5.2) — inserts the close-marker(s). Base records aren't closeable (no id).

## Why / rejected alternative
Rejected encoding end as `end=<pos>` on the start marker: positions shift as prose is edited, and it
puts the close information away from where the close happens (breaking the Model-A "value lives at
the point of change" invariant, ADR-0001). A referencing marker at the close site is stable and
mirrors the existing single-marker edit machinery.

## Consequences
- Out-of-order retraction (red-herring: close one add while siblings stand) needs no special
  handling — liveness is per-record (ADR-0002).
- The mutations index must resolve `close` markers against their `ref` when computing liveness.
- Deleting a start record should also drop dangling closes that reference it (index-time reconcile).
