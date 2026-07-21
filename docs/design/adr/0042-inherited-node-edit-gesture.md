# ADR-0042: The edit gesture on an inherited node — two bounded axes, one rule

- Status: **Accepted** — 2026-07-21 (Anton, PR #351). Designed with him over #308 across two sessions:
  the in-context reach and the bounded authoring layer (§1–§4), **§5 including its no-"between"
  boundary**, and the reach cue (§8 — header strip, entry gate, footer echo, non-sticky L).
- Feature: #7 · Issue: #308 · Gates: #313 (slice D) · #314 (slice E)
- Follows: ADR-0039 (the hierarchy model), ADR-0013 (+ Amendment 1 — **this ADR settles its open
  question**), ADR-0016 (the mutation unit), ADR-0017 (collection deltas authored as list edits),
  ADR-0005 (book as the resolution boundary)
- Governed by: `docs/design/design-language.md` — the marks are settled (#304, PR #320) and this ADR
  consumes them
- Prerequisite landed: **#339** — the layered tag registry (PR #341). ADR-0042 was paused on it
  because a rail that re-targets a write must also re-target the vocabularies constraining that write.

## Context

ADR-0039 settles the *model*: an ancestor-owned node is materialized into the open project, and the
author has three intents — correct the ancestor's canon, diverge this layer only, or stop inheriting.
ADR-0013 settles *time*: stop 0 is editable, later stops are a read-only effective overlay.

Neither settles the **gesture**. Standing in front of one node surface, four writes are expressible,
and the app has no per-pane edit bar to disambiguate them:

1. correct canon at the owning layer (writes an *ancestor's* file — the reach that most needs a tell)
2. override this field for this layer (writes an `overrides/` delta)
3. fork the whole node to here (`⧉`)
4. mutate this field from a point in the manuscript (writes a scene-body carrier marker)

ADR-0013 Amendment 1 made this blocking rather than untidy: once base at stop 0 is a *resolved*
state, stop 0 no longer says which file an edit writes to, so **stop-0 editing on an inherited entry
was undefined and could not ship**.

The co-design requirement in #308 is real. A layer override and a mid-scene mutation are the same
author motion — *"this value is different from here on"* — differing only in the axis. Designing one
alone produces a vocabulary the other then has to contradict.

## Decision

### 1. Two axis pickers, and position is the mode

ADR-0013 already solved this shape once, on the manuscript axis, with one rule: *position is the
mode* — stop 0 means edit, stops ≥ 1 mean view. This ADR adds the second axis and keeps the rule.

- **Manuscript axis** — the existing `MutationScrubber` strip (ADR-0013).
- **Hierarchy axis** — a **layer picker in the metadata rail**, selecting the *authoring layer* **L**.
  It docks as a **strip in the editor header** (`.editor-header`), the structural counterpart to the
  scrubber docked at the card's foot — two axes, two strips.

**The picker is not in the metadata rail**, though slice D reserved that space for owning-level
indication. Two reasons, and the first is decisive: the rail **collapses to a tab**, so a rail-borne
mode indicator can be dismissed by the very gesture that hides the fields — and ADR-0013's scope is
total, so title and body write to L as well; an author editing the *body* with a collapsed rail would
have no indication at all. The division is therefore **rail = provenance** (`ti-versions`, the level
pill — where this value came *from*) and **header = mode** (where the next keystroke *goes*).

Four writes, three controls — two axis pickers plus `⧉` — and none of them per-field. **Rest position
on both axes is local and safe** (stop 0; L = the open project). The inattentive path therefore
produces the *contained* write, and only a deliberate act reaches past it. That is the bar,
structurally, before any visual treatment is chosen.

### 2. The authoring layer L is bounded

    node's owning layer  ≤  L  ≤  open project

A node owned at *series*, opened from a *book*, offers {series, book}. The picker cannot select
*universe*, because the node has no representation there to write into. For a node owned by the open
project the range is degenerate and no picker appears.

- **L == the node's owning layer** → an ordinary write to that layer's file. *This is "correct
  canon"*, and it needs no separate affordance.
- **L below the owning layer** → an **overlay delta** at L: the `overrides/` record ADR-0039 already
  specifies. *This is "override this layer".*

So intents 1 and 2 are not two affordances. **They are the same write at two picker positions.**
Intent 3 (`⧉` fork) remains a button and, per the design language, must never also be a state mark.

### 3. The bound is on the write target — never on what a picker may see

The candidate sets feeding the surface at L — reference pickers, the tag vocabulary, the field
roster — resolve the **full ancestor chain up to L** (`base → L`). Universe-level values are offered
at every picker position.

Truncation removes the layers **below** L, not above it: a series-targeted write must not be able to
reference a value that exists only in the book. One consequence per vocabulary:

- **Schema** — render the rail through the schema resolved *as of L*
  (`_read_metadata_schema_through_path`). The merge is additive with no tombstones, so an ancestor's
  key set is a subset of the descendant's and the roster can only *shrink* as L rises — it can never
  offer a field the target layer cannot store. But a descendant may override an inherited field's
  `type` or `picker_config`, so resolving as-of-L is required, not cosmetic.
- **References** — a reference may only point at **L's layer or above** (rank-monotonic). The data is
  already on the wire (`source_layer_id`); the pickers simply do not read it yet (#334).
- **Tags** — the registry is layered as of #339; the visible vocabulary at L is the union `base → L`.

**The invariant this produces, without a check:** author at L and the value lands at L, while any
newly-registered name registers at L — so *a name is always asserted at or above the layer holding the
value that uses it*. Upward-dangling vocabulary becomes unconstructable rather than something to
validate against.

### 4. The two axes form an **L**, not a grid

Book is the resolution boundary (ADR-0005) and an ancestor level has no manuscript, so **selecting an
ancestor collapses the time axis to stop 0**. Stops ≥ 1 exist only at `L = open project`. The
reachable set is an L-shape, and no cell is undefined.

Switching L **flushes the editable buffer first**, reusing ADR-0013's scrub-entry discipline.

### 5. A stop is a unit; editing at a stop edits that unit

This is the mutation-edit-in-place half, and it needs no new storage, endpoint, or vocabulary.

ADR-0016 already made the **mutation unit** the single authoring object, and ADR-0013 already made
**one scrubber stop per unit**. A stop therefore *names a container that already exists*:

- editing a field that changes at stop N → edits **that unit's row** for the field;
- editing a field that does not change at stop N → **adds a row to that unit**, exactly as the unit
  dialog does today;
- `PATCH` / `DELETE /scenes/{id}/mutations/{marker_id}` already address rows, and a row edit inside a
  carrier rewrites the carrier through the existing marker-rewrite spine.

**There is no "between" — this is not a limitation awaiting closure.** The scrub coordinate is an
**integer index over units** (`0 = base`, `i ≥ 1 = as of units[i-1]` — `MutationScrubber`'s
`index: number`, `scrub.scrubTo(index)`), not a position on a continuum. ADR-0013 made the stops
discrete because effective state is constant between markers and there is nothing to interpolate. So a
"position between stops" is not something the card declines to edit; it is not expressible on this
axis at all.

> ⚠ **Implementers: do not read this as an invitation to add intermediate positions.** Authoring at an
> arbitrary manuscript point requires a **prose cursor**, which the card does not have and must not
> acquire — ADR-0003 makes position live only where a caller has one, and ADR-0001 anchors a marker to
> the prose position where the change happens (narrative position *is* file position). A card-side
> "insert a mutation somewhere in Chapter 7" would have to invent that position, and inventing it is
> exactly what Model A was chosen to avoid.

**New** mutation points are therefore authored in the prose, where the position exists. The card edits
the units that exist; it does not create positions.

### 6. The one rule both axes obey

> **A picker position names a container. An edit writes into the container that position names, and
> every container reachable at L belongs to L.**

At `L = book`, stop 0 writes the book's override delta and stop 5 writes a book scene's carrier —
both book-local. At `L = series`, stop 0 writes the series' own file, and there are no other stops.
This is what makes four writes one gesture instead of four controls.

It also **keeps #66 shut**. Every position resolves to exactly **one** target file, named before the
write commits. Edit-once-propagate-to-N stays deferred on its own cost grounds, and the stamp
semantics of the three mutation edit surfaces are untouched.

### 7. Divergence below the owning layer is authored as a delta

A below-owning-layer edit is an `overrides/` delta, and for collection fields it is **authored by the
ADR-0017 gesture** rather than by asking the author to compile ops:

1. baseline is the **effective** value at L, never base — a base baseline double-counts inherited adds;
2. editing an existing delta **excludes its own rows** from the baseline (`exclude=`), or the diff
   counts itself;
3. `+item` / `−item` transparency chips while editing, so the records that will be stored are visible;
4. **never infer `replace`** on a disjoint set — always plain adds/removes, so a layer that clears an
   inherited list keeps receiving later ancestor additions.

Tags are an ordinary collection field here. Nothing about them is special at the value level; the
*registry* is a separate concern, settled by #339.

### 8. The bar: gate on entry, state throughout, echo on every write

**There is no save-time gate, because there is no save.** Lore entries autosave — a 6 s debounce in
`AutosaveScheduler` (`editor-core/autosave.ts`, `editorPanes.svelte.ts:88`) covering every node kind,
with no Save button, no `Ctrl+S`, and no per-field PATCH (a metadata edit folds into the whole-entry
PUT). A confirm at write time would therefore fire seconds after typing stops, repeatedly. This also
*raises* the stakes: writes are silent and continuous, so the persistent cue is the only thing between
the author and an unnoticed ancestor write.

Four parts, none of them a frame — a border present for the whole of an intentional edit stops being
seen:

- **Gate on entry.** Switching L upward raises one confirm naming the layer and its blast radius,
  through the existing `confirmService` (`stores/confirmService.svelte.ts`). ⚠ It supports
  `dontShowAgainKey`; **this gate must not use it.** Suppressing it reconstructs precisely the silent
  ancestor write it exists to prevent.
- **State throughout.** While `L ≠ open project` the header strip carries the `--warn` family
  (`--warn-soft` ground, `--warn-border`) and **states the target in words** —
  `EDITING AT · Honorverse (series) — changes reach every book` — in the caps-label recipe. Words, not
  a tint: the strip occupies layout and cannot be tuned out, and it names the thing at risk.
  `--danger` is deliberately not used; it is spoken for by destructive actions, and editing canon is
  far-reaching, not destructive.
- **Echo on every write.** The status footer already reports "Unsaved changes" / "Saved"; when
  `L ≠ open project` it reads **"Saved to series"**. This makes each silent autosave visible at the
  moment it happens — the proportional replacement for the impossible save-time gate.
- **L is non-sticky.** It resets to the open project when the pane closes or the author switches
  entries. This costs a fluent multi-entry canon-fixing session — accepted, because the alternative
  failure is setting L, forgetting, and writing upward unaware, which is the same unlabelled wrong
  state this ADR exists to prevent.

At rest (`L = open project`) none of this shows: overriding within your own book is the ordinary case
and earns no alarm.

Marks are consumed, not chosen (#304 / PR #320): `ti-versions` = overridden at this layer, `⤳` =
mutated, `ti-arrow-bar-to-right` = interval ends here; provenance **leads** the value and mutation
**trails** it, so a field that is both reads `[versions] Captain ⤳`.

### 9. What this settles, and what it deliberately does not touch

- **Settles ADR-0013 Amendment 1.** Stop-0 editing on an inherited entry may ship: at `L = owning
  layer` it writes that layer's file; below it, an override delta. Amendment 1's "the layer axis does
  not scrub" is superseded — it *does* now select, on the write side only.
- **Does not overturn ADR-0039's descendant-wins override composition.** ADR-0039 flagged this as the
  one semantic 0042 might revisit; it does not. Layers are totally ordered by rank and the delta
  vocabulary is unchanged.
- **Read-side layer scrubbing stays deferred.** "Show me this entry as the *series* sees it" is a
  Views 2.0 concern (ADR-0039). The picker here is a **write-target selector**; it does not re-render
  the card as another layer would see it.

## Why / rejected alternatives

**Navigation-only — "to correct canon, go where the canon lives."** The first design, and cheap:
slices B/C already ship level-opening and a breadcrumb, so direct-edit would collapse into travel with
no new control at all. **Rejected on the failure it does not prevent.** The author who does not want
to travel still makes the local edit intending to fix it later, and the resulting override is
*indistinguishable from a deliberate divergence*. Forcing navigation does not stop the wrong state —
it guarantees the wrong state is unlabelled. Availability in context, with a bar, is what keeps the
intent recoverable.

**Per-field control triplets** (edit / override / fork on every row). Precisely the outcome #308 named
as the thing to avoid: four writes becoming four bolted-on controls on an already dense surface.

**A carve-out: allow in-place ancestor editing only for schema-defined scalar fields, and require
navigation for reference and tag fields.** Tempting while #339 was outstanding, since those are
exactly the fields whose value space is layer-dependent. **Rejected:** partial editability surprises
the author only at the moment it bites, after they have formed the belief that the surface is uniform.
The boundary is invisible until it is violated.

**Deriving the write target from the node's owning layer.** Rejected: an inherited entry sitting at the
picker's rest position would derive *ancestor* and write upward while the author is explicitly standing
at the book. The target is carried from the picker, never inferred from the node.

**An explicit "history mode" / "canon mode" toggle.** Rejected for the reason ADR-0013 rejected its
twin: the picker's rest position already carries the mode, so a toggle is redundant state that can
disagree with it.

## Consequences

- **Slice D (#313)** gains the picker, but **in the editor header, not the rail** (§1) — the rail
  keeps provenance only, since it collapses. It also owns the entry confirm, the `--warn` header
  state, the footer echo, and non-sticky L (§8).
- **The status footer becomes layer-aware** (`"Saved to series"`), which is the only per-write signal
  autosave permits.
- **Slice E (#314)** gains the ADR-0017 authoring rules for deltas, and must close the **split-target
  save**: `save_lore_entry` resolves through `_path_for_node_id` to the *ancestor's* path while tag
  registration defaults to the open project, so one save of an inherited entry currently writes its
  content upward and its registry record locally. Two halves of one defect.
- **`_strip_dangling_references` must stop self-healing.** Under hierarchies "missing" also means
  "exists, but below my layer"; silently clearing the field damages an ancestor's file shared by every
  sibling book. It becomes a validation error, not a repair.
- **The scrubber is conditioned on L** — hidden, or collapsed to stop 0, whenever L ≠ the open project
  (§4). `NodeEditor` already owns the scrub state to hang that off.
- **No new mutation storage, endpoint, or grammar.** §5 rides ADR-0016's carrier and the existing
  row-addressed routes; the frontend work is making the read-only overlay editable at a stop.
- **The picker needs the layer roster on the wire** — the chain with ranks, which #334 provides.
- **Still open, and small:** the exact visual of the rail treatment is #313's to render within the
  design language. This ADR fixes only its register, and the requirement that a gate accompany it.
