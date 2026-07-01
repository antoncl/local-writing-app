# Architecture Decision Records

One decision per file (MADR-lite: decision · why/rejected-alternative · consequences). The *why*,
especially the rejected alternative, is the load-bearing part — it's what decays from memory.

## 0.4.0 — Mid-scene lore mutations (#33)
Design doc: [`../mid-scene-lore-mutations.md`](../mid-scene-lore-mutations.md)

- [0001](0001-mutations-as-scene-body-markers.md) — Mutations as self-contained scene-body markers (Model A)
- [0002](0002-independent-interval-model.md) — Independent-interval model — no stack, no frames
- [0003](0003-position-granular-resolution.md) — Cumulative, position-granular resolution in manuscript order
- [0004](0004-every-field-mutable.md) — Every field is mutable — no `mutable` flag
- [0005](0005-book-as-resolution-boundary.md) — Book as the resolution boundary
- [0006](0006-resolver-mediated-context.md) — Lore context resolver-mediated at the `_format_lore_block` formatter
- [0007](0007-mutation-value-is-a-field-value.md) — A mutation value is a field value — validated
- [0008](0008-mutable-names-segment-the-matcher.md) — Mutable names segment the implicit-context matcher (v1.1+)
