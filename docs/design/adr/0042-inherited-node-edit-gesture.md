# ADR-0042: The edit gesture on an inherited node (direct edit / override / fork / mutate-in-place)

- Status: **Draft — not yet written.** Placeholder recording scope and why it is separate.
- Feature: #7 (gates slices D and E) · Follows: ADR-0039 (the model) · *Will settle* ADR-0013's stop-0 edit target (recorded in its Amendment 1, which ADR-0039 raised)
- Blocked on: **#308** (mutation edit-in-place, co-designed) — the only remaining blocker
- Marks: **settled** (#304, ADR-0030 / `design-language.md`) — see *Marks are decided* below
- Gates: #313 (slice D) · #314 (slice E)

## Scope

ADR-0039 settles the *model*: an ancestor-owned node is materialized into the open project, and the
author has three intents — correct the ancestor's canon (direct edit), diverge this layer only
(per-field override), or stop inheriting (fork). ADR-0013 settles *time*: stop 0 is editable, later
stops are a read-only effective overlay.

What neither settles is the **gesture**: standing in front of one node surface, how does the author
say which of those they mean? Today that surface has no per-pane edit bar, and the same field row must
be able to express:

- correct canon at the owning layer (writes an ancestor's file — the reach that most needs a tell)
- override this field for this layer (writes an `overrides/` Node)
- fork the whole node to here (`⧉` — the *affordance*; never a state mark on the forked node)
- mutate this field from a point in the manuscript (existing mutation authoring)

These are four writes to the same visual surface, and they must not become four bolted-on controls.

## Why this is a separate ADR

Because it must be co-designed with **mutation edit-in-place**, which is incoming and unscoped. Layer
override and mid-scene mutation are the same author motion — "this value is different from here on" —
differing only in the axis (hierarchy vs manuscript position). Designing the layer gesture first would
almost certainly produce a vocabulary the mutation gesture then has to contradict.

House precedent for splitting UX conformance from the model: ADR-0038.

## Marks are decided — this ADR consumes them, it does not choose them

Settled by #304 and recorded in `design-language.md` (PR #320), so the gesture work starts with a
vocabulary rather than a question:

- **The closed lexicon governs affordances; value annotations are a second vocabulary** drawn from the
  curated Tabler set. That split is why `⤳` was never in the lexicon — it annotates a value, it is not
  a control — and it is the rule this ADR must respect when it adds controls.
- `⤳` — mutated (grandfathered into the lexicon as-is).
- `ti-arrow-bar-to-right` — mutation interval ends here, replacing the banned `⤳✕` compound.
- `ti-versions` — overridden at this layer.
- **Position carries meaning:** provenance *leads* the value, mutation *trails* it. A gesture surface
  must not disturb that ordering, because it is what lets a field carry both marks legibly.
- **A mark is never both an annotation and an affordance.** `⧉` is the fork *button*; it must not also
  mark a forked node.

What remains open is only how the author *chooses* between the four writes — not how the result is
displayed.

## Before this can be written

1. **#308** — the mutation edit-in-place design it must be co-designed with. This is now the sole
   blocker.
