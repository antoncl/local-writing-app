# ADR-0003: Cumulative, position-granular resolution in manuscript order

- Status: Accepted — 0.4.0 planning, 2026-07-01
- Feature: #33 mid-scene lore mutations · Doc: `docs/design/mid-scene-lore-mutations.md` §2

## Decision
Effective state resolves **cumulatively in manuscript order** (act → chapter → scene, then prose
position within the scene). Resolution takes a **`(scene, position)`** pair. A record is live at
that point if its start is at or before it and its end (if any) is strictly after it; per field the
**latest-started live record wins**.

## Why / rejected alternative
Scene-granular-inclusive resolution (the v1 draft's recommendation) computes effective state as of
end-of-scene. It's simpler, but a `replace_selection` generation positioned *before* a mid-scene
marker would wrongly see the *post*-marker value — the exact future-leak the feature exists to
prevent. Position-granular is correct.

Threading a position through every AI caller is the real cost, so v1 **bounds it**: only
`replace_selection` has a genuine cursor and passes a live offset; `append_to_body`, roleplay,
preview, and the timeline resolve at **end-of-scene**, which is their natural position, not a
compromise.

## Consequences
- The mutations index stores each marker's **intra-scene offset**, not just scene order.
- The resolver seam (`_format_lore_block`, ADR-0006) is `(scene, position)`-aware.
- A marker's location in the prose is meaningful: prose before it sees the old value, after it the
  new. This is what the inline pill visualises.
