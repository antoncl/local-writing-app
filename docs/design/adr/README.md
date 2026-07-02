# Architecture Decision Records

One decision per file (MADR-lite: decision · why/rejected-alternative · consequences). The *why*,
especially the rejected alternative, is the load-bearing part — it's what decays from memory.

## 0.4.0 — Mid-scene lore mutations (#33)
Design docs: [`../mid-scene-lore-mutations.md`](../mid-scene-lore-mutations.md) (v1.0 spine) ·
[`../mid-scene-lore-mutations-v1.1.md`](../mid-scene-lore-mutations-v1.1.md) (v1.1)

### v1.0
- [0001](0001-mutations-as-scene-body-markers.md) — Mutations as self-contained scene-body markers (Model A)
- [0002](0002-independent-interval-model.md) — Independent-interval model — no stack, no frames
- [0003](0003-position-granular-resolution.md) — Cumulative, position-granular resolution in manuscript order
- [0004](0004-every-field-mutable.md) — Every field is mutable — no `mutable` flag
- [0005](0005-book-as-resolution-boundary.md) — Book as the resolution boundary
- [0006](0006-resolver-mediated-context.md) — Lore context resolver-mediated at the `_format_lore_block` formatter
- [0007](0007-mutation-value-is-a-field-value.md) — A mutation value is a field value — validated
- [0008](0008-mutable-names-segment-the-matcher.md) — Mutable names segment the implicit-context matcher (v1.1+; **amended** in v1.1 → per-resolution-scene)

### v1.1
- [0009](0009-collection-add-remove-and-list-contract.md) — Collection add/remove ops; `effective_state` returns typed lists (#58; **amended** — `add` also appends on text/long_text)
- [0010](0010-interval-close-marker.md) — Interval close is a separate close-marker (#59)
- [0011](0011-transformation-sets-are-a-node-kind.md) — Mutation sets are a first-class Node kind (#62; **amended** — renamed from "transformation set")
- [0012](0012-scene-ref-resolution-input.md) — Resolution scene is a `scene_ref` prompt input (#60)
- [0015](0015-user-nameable-mutations.md) — Mutations carry an optional user name — a label, not a frame (#65)

### v1.1 — the time-sensitive lore entry
Design doc: [`../time-sensitive-lore-entry.md`](../time-sensitive-lore-entry.md)
- [0013](0013-time-travel-aware-lore-entry.md) — Lore entry is time-travel-aware; whole-card read-only effective overlay (#64)
- [0014](0014-mutations-version-cross-pane-signal.md) — `mutationsVersion` cross-pane freshness signal (#63)

### Authoring rework — the mutation unit
Design doc: [`../mutation-unit-authoring.md`](../mutation-unit-authoring.md)
- [0016](0016-mutation-unit-carrier-marker.md) — The mutation unit: one carrier marker, one pill; rows keep their own lifetimes (#69, #70; amends 0001/0010, subsumes 0015 `group=`)
- [0017](0017-collection-mutations-authored-as-list-edits.md) — Collection mutations authored as list edits, diffed against the effective baseline (#71)
