# Design: The mutation unit — authoring rework

> Status: **DRAFT for review** · Issues: [#69](https://github.com/antoncl/local-writing-app/issues/69)
> (one carrier marker / one pill), [#70](https://github.com/antoncl/local-writing-app/issues/70)
> (visual frame per unit), [#71](https://github.com/antoncl/local-writing-app/issues/71)
> (collections authored as list edits) · Milestone: 0.4.0
> Part of #33 mid-scene lore mutations. Read `mid-scene-lore-mutations.md` (ADR-0001/0002) and
> `mid-scene-lore-mutations-v1.1.md` (ADR-0009/0010/0015) first. This is the authoring-UX pass
> Anton's first hands-on demanded — it changes how mutations are *written and shown*, never how
> they *resolve*.

## 1. What & why — the unit is not a first-class thing

Three symptoms, one root. Mutating three fields in one `/mutate` gesture mints **three markers →
three sibling pills** (#69), which then read as loose clutter everywhere (#70); and collection
fields force the author to think in set operations instead of editing a list (#71). All three
happen because the thing the writer actually authors — **one change to one entity, touching N
fields** — has no first-class representation. v1.1's `group=` (ADR-0015) ties the members with
string glue but leaves N markers in the file, N pills in the prose, N rows in the timeline.

This pass makes the **mutation unit** the single authoring/presentation object across the whole
surface: one carrier comment in the Markdown, one pill in the prose, one framed row-set in the
dialogs, one row in the timeline, one stop on the #64 scrubber. **Resolution is untouched**: each
`(field, op, value)` row remains an independent record with its own id and its own lifetime —
ADR-0002's "co-occurring ≠ sharing a lifetime" and ADR-0009's set semantics hold verbatim.

## 2. #69 — the carrier marker (ADR-0016)

### Grammar
A unit is **one HTML comment** carrying a head (entity + optional name + unit id) and one `field=`
row per line:

```
<!-- mutate:entity=<lore-id>[;name=<url-encoded>];id=<unit-id>
field=<key>[;op=<op>];value=<url-encoded>;id=<row-id>
field=<key>[;op=<op>];value=<url-encoded>;id=<row-id>
-->
```

- Values and names are already URL-encoded (no raw `;`/newlines), so line-splitting is safe.
- **The v1.1 single-line marker is the degenerate form of this grammar** — head and sole row
  folded into one line — not a legacy case. The writer emits the single-line form for one-row
  units and the carrier for ≥ 2 rows; canonicalization is deterministic (an edit that leaves one
  row degenerates back to single-line). Every existing v1.0/v1.1 marker parses unchanged.
- Multi-line comments read cleanly in the raw Markdown — Model A's files stay human-legible, and
  the authored unit now reads as one thing *in the file*, not just in the UI.

### Rows keep their own ids — lifetime stays per row
The carrier is **authoring/presentation granularity, not lifetime granularity**. Each row carries
its own `id=`; `close;ref=<row-id>` (ADR-0010, unchanged) closes one row, so the werewolf can
learn a clue mid-transform that outlives the transform. New sugar: `close;ref=<unit-id>` ends
*every live row of the unit* at that point — expanded at index time into per-row liveness ends
that merely coincide; one close pill at the close site, still zero shared-lifetime semantics.

### `name=` and `group=`
`name=` lives **once on the head** (it labels the unit — exactly ADR-0015's mnemonic, minus the
per-member duplication). `group=` is **subsumed**: the carrier *is* the group. Legacy `group=`
markers keep parsing; the index maps a shared `group=` to a unit tie so old co-authored sets get
the per-unit surfaces too. New authoring never emits `group=`.

### Index & API (additive)
`MutationMarker` records stay **per row** (`marker_id` = row id) and gain `unit_id` (+
`unit_name`): own id for a standalone single-line marker, the `group=` id for legacy groups, the
head id for carriers. Timeline, scrubber, and the close picker group by `unit_id`. `PATCH`/
`DELETE /scenes/{id}/mutations/{marker_id}` keep addressing rows; a row edit inside a carrier
rewrites the carrier via the marker-rewrite spine.

### Editor
**One TipTap atom node per unit**, rows in node attrs; serialization round-trips the multi-line
comment. Pill label: the name if set; else the sole row's auto-label (`rank → Captain`); else
`N changes`. Clicking the pill opens the unified rows dialog (`MutationDialogShell` +
`MutationFieldRows`) editing the **whole unit** — add/remove/change rows, rename — matching #62's
one-dialog UX. `/mutate` with N rows inserts one unit.

## 3. #71 — collections authored as list edits (ADR-0017)

The add/remove op selector asks the author to compile their own diff. Instead, a collection field
row in `MutationFieldRows` presents **the field's own widget** (`FieldValueEditor` — chips,
reference picker, tag picker) seeded with **the effective value at the authoring position**; the
author just edits the list. On save the dialog **diffs membership** old → new and emits the same
`op=add` / `op=remove` rows the author writes by hand today, into the unit being authored.
**Storage and resolution are byte-identical to ADR-0009** — this is an authoring layer only.

- **Baseline = effective, not base.** `effective_state(entity, scene, pos=cursor)` — a base-value
  baseline would double-count every earlier mutation. Opening `/mutate` flushes the scene first
  (`flushSceneIfDirty`, the GH-#45 spine) so the saved index is current at the cursor.
- **Editing an existing unit:** the baseline must exclude the unit's own rows (else the diff
  counts itself) — `GET …/effective` gains an `exclude=<row-id,…>` query param.
- **Transparency chips:** the row shows a live `+item` / `−item` strip of the derived records as
  the list is edited, so the author sees exactly what will be stored (they are still authoring
  deltas; the widget just does the compiling).
- **Membership only.** Effective collections render base-order-then-adds (ADR-0009); reordering
  is not representable and the diff ignores order.
- **The op selector disappears for collections.** Grammar keeps `op=replace` on collections
  (parses forever; hand-authoring in Markdown remains the escape hatch), but the UI offers only
  the list editor. No auto-inference of `replace` when the new set is disjoint from the baseline —
  always plain adds/removes, so the record shape (and what `close` can later target) is
  predictable. Text/long_text Replace/Append (amended ADR-0009) and scalar rows are unchanged.

## 4. #70 — the frame is the unit (polish; rides ADR-0016, no own ADR)

- **Inline:** with one pill per unit, the pill *is* the frame. Multi-row pills get a count
  affordance (`⤳ Full Moon ·3`); the detail tooltip lists the rows. No adjacent-pill frame is
  built for legacy `group=` siblings — pre-1.0, Anton recreates projects, and the carrier answers
  the need going forward.
- **Dialogs:** each field-change row in `MutationFieldRows` gets a hairline frame (1px
  `var(--divider)`, small radius, inset background) under the entity header — the header + framed
  rows read as the unit. Density-first (widget taxonomy): a frame, not a card explosion.
- **Timeline (rail list):** one `NodeRow` per unit — title = name/auto-label, detail =
  scene · field list. **Scrubber (#64): one stop per unit** (stops get fewer and more meaningful;
  tooltip lists the rows changing there). Close picker: units first, rows expandable.

## 5. Scope & build order

**In:** carrier grammar + index `unit_id` + unit-close expansion; unit pill + round-trip + whole-
unit dialog; collection list-edit authoring (flush-first effective baseline, `exclude` param,
diff + chips); per-unit frames across dialog/timeline/scrubber/close-picker.
**Out:** #66 linked mutations (v2), #73 dependency-aware closes (v2), reorder support, any
resolution-semantics change.

**Build order** (one slice per commit, gates every commit): (1) backend grammar + index — carrier
parse/render, `unit_id`, `close;ref=unit` expansion, legacy `group=`→unit mapping; (2) editor —
unit pill node, serialization round-trip, whole-unit dialog edit, `/mutate` emits units;
(3) #71 — effective-baseline fetch + `exclude` param + membership diff + preview chips; (4) #70 —
frames + per-unit grouping on timeline/scrubber/close-picker. (2) depends on (1); (3)/(4) are
independent after (2).

## 6. ADRs
- **0016** — The **mutation unit**: one carrier marker and one pill per authored change; rows keep
  their own ids and lifetimes (amends ADR-0001 grammar, extends ADR-0010 close-ref, subsumes
  ADR-0015 `group=`).
- **0017** — Collection mutations are authored as **list edits diffed against the effective
  baseline** at the cursor; storage/resolution stay ADR-0009.
