# ADR-0002: Independent-interval model — no stack, no frames

- Status: Accepted — 0.4.0 planning, 2026-07-01
- Feature: #33 mid-scene lore mutations · Doc: `docs/design/mid-scene-lore-mutations.md` §2
- Supersedes: the v1 draft's "reversal by re-set; no `unset`."

## Decision
Each mutation is an **independent record** with its own lifetime: a **start** (marker position in
manuscript+prose order), an **optional end** (a marker closing *that specific* record), a
**combine rule** (replace a scalar field / add to a collection), and an **identity**. Closing ends
one record by id. There is **no stack, no frame, no nesting discipline.**

The resolver at `(scene, position)` collects every record whose interval is live there; per field
the latest-started live record wins; live additive records union in.

## Why / rejected alternative
A stack/frame conflates *co-occurring in time* with *sharing a lifetime*. Killer counterexample: a
detective who is also a werewolf **learns a clue while transformed**. The transformation ends at
dawn; the clue is permanent. Any model where lifetime belongs to a *group* (a frame, a stack
level) would pop the clue when it pops the transformation. Lifetime belongs to each individual
change, so the primitive is one independent record — *smaller* than a stack, not bigger.

We considered and rejected: (a) a stack with push/pop — fails the clue case; (b) "reversal by
re-set only, no close" (the v1 draft) — forces re-typing the restored state on every werewolf
revert and cannot express a scoped/temporary change.

## Consequences
- **Out-of-order retraction** (a red herring dropped while other beliefs stand) requires per-record
  identity (ADR-0001).
- Werewolf revert is "latest live record wins" as a closed interval expires — no stored prior
  value, no explicit restore.
- **Base state unifies** into the model: the lore file's values are open-ended replace records at
  book-start, shadowed by later ones.
- A multi-field transform is N independent, co-authored records plus a soft UI group label
  (create-together, close-together) — a convenience, not a semantic frame.
