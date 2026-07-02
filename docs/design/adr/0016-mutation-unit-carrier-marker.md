# ADR-0016: The mutation unit — one carrier marker, one pill; rows keep their own lifetimes

- Status: Proposed — 0.4.0 authoring rework, 2026-07-02
- Feature: #33 mid-scene lore mutations · Doc: `mutation-unit-authoring.md` §2 · Issues: #69, #70
- Amends: ADR-0001 (marker grammar) · Extends: ADR-0010 (close ref) · Subsumes: ADR-0015 `group=`
- Guards: ADR-0002 (independent intervals)

## Decision
One authored change (one entity, N field changes) is a **mutation unit**, stored as **one
multi-line carrier comment** — a head (`entity`, optional `name`, unit `id`) plus one `field=` row
per line, each row with its **own `id`**:

```
<!-- mutate:entity=<lore-id>[;name=<n>];id=<unit-id>
field=<key>[;op=<op>];value=<v>;id=<row-id>
…
-->
```

The v1.1 single-line marker is the **degenerate form** (head + sole row folded); the writer emits
it for one-row units, so all existing markers parse unchanged and canonicalization is
deterministic. The unit renders as **one pill**; the pill dialog edits the whole unit.

**The unit is authoring/presentation granularity, not lifetime granularity.** Each row resolves as
an independent record (ADR-0002/0009 verbatim). `close;ref=<row-id>` closes one row;
`close;ref=<unit-id>` is sugar that ends every live row of the unit at that point — index-time
expansion into per-row ends that merely coincide. `name=` moves to the head (once, not per
member); `group=` is subsumed — legacy `group=` markers parse forever and map to a unit tie in the
index. `MutationMarker` stays per-row and gains `unit_id`/`unit_name`; timeline, scrubber, and
close picker group by unit.

## Why / rejected alternative
Rejected **unit-level ids only** (rows unaddressable): a whole-unit-only close binds the members'
lifetimes — exactly the co-occurring-≠-shared-lifetime conflation ADR-0002 and ADR-0015 reject
(the werewolf's mid-transform clue must outlive the transform). Rows keep ids, so nothing that is
expressible today becomes inexpressible.

Rejected **keeping N markers + purely visual grouping** (#70 alone, `group=` glue): Model A's
files are the human-readable source of truth, and three comments for one authored change is the
same clutter in the file that the pills are in the prose; `name=` duplicated per member is a
maintenance split ADR-0015 tolerated, not endorsed. Rejected a **pointer/registry** for the unit
for the same split-brain reasons as ADR-0001/0015.

## Consequences
- Grammar is additive; no migration (pre-1.0). New authoring never emits `group=`.
- The index resolves `close;ref=` against row ids *and* unit ids; deleting a unit drops its rows
  and dangling closes (ADR-0010 reconcile extends to units).
- One TipTap atom per unit; serialization must round-trip the multi-line comment byte-stably.
- #70's inline "frame" dissolves: the single pill (with a `·N` count) *is* the frame; no
  adjacent-pill grouping is built for legacy `group=` siblings.
