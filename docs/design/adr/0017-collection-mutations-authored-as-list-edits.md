# ADR-0017: Collection mutations are authored as list edits, diffed against the effective baseline

- Status: Accepted — 0.4.0 authoring rework, 2026-07-02
- Feature: #33 mid-scene lore mutations · Doc: `mutation-unit-authoring.md` §3 · Issue: #71
- Layers over: ADR-0009 (storage/resolution unchanged) · Uses: ADR-0003 (position-granular
  effective state)

## Decision
Collection fields (`multi_select`, `tags`, `entity_ref_list`) drop the add/remove **op selector**
in the authoring UI. A collection row in the mutation dialog presents **the field's own widget**
seeded with the **effective value at the authoring position**; the author edits the list; the
dialog **diffs membership** old → new and emits the same `op=add`/`op=remove` records that are
hand-authored today, into the unit being authored (ADR-0016). A live `+item`/`−item` chip strip
previews the derived records while editing.

- **Baseline = effective, never base**: `effective_state(entity, scene, pos=cursor)`; `/mutate`
  flushes the scene first (`flushSceneIfDirty`) so the index is current. When re-editing an
  existing unit, the baseline **excludes the unit's own rows** (`GET …/effective` gains
  `exclude=<row-ids>`) so the diff cannot count itself.
- **Membership only** — effective collections render base-order-then-adds; reorder is not
  representable and the diff ignores order.
- No auto-inference of `op=replace` when the new set is disjoint; always plain adds/removes.
  Grammar keeps `op=replace` on collections (hand-authoring in Markdown stays the escape hatch).
  Text/long_text Replace/Append (amended ADR-0009) and scalar rows are unchanged.

## Why / rejected alternative
Set operations are the wrong altitude for an author — they make the human compile the diff the
machine can compute. Because the diff emits exactly the records ADR-0009 already defines,
resolution, close semantics (ADR-0010), validation (ADR-0007), and every existing marker keep
working unchanged; this is pure authoring UX.

Rejected **base-value baseline**: double-counts every earlier live mutation (the diff would
re-add items an earlier mutation already added). Rejected **auto-replace when disjoint**: it
silently changes the record shape (one replace vs N adds/removes), which changes what a later
`close` can target — predictability of the stored records wins. Rejected keeping the op selector
as an "advanced" mode: two authoring paths to the same records is exactly the dual-dialog
confusion the #62 rework just removed.

## Consequences
- The dialog needs the effective baseline per (entity, field) — one fetch per unit, plus the
  `exclude` param on the effective endpoint.
- Preview chips keep the delta visible: the author still *authors* add/remove records, the widget
  just compiles them.
- If the author clears the whole list, the emitted records are N removes (one per live/base
  member) — correct under remove-wins, and each remains individually closeable.
