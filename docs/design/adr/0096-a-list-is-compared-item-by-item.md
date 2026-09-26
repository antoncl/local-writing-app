# ADR-0096: A list is compared item by item, and its group declares what identifies an item

- **Status:** Proposed — 2026-09-26. Text by Claude from a conversation with Anton on 2026-09-26,
  which started from screenshots of a plotline review ("The Girl in the Ghost") where the
  proposed beats could not be read and the current beats were one flattened string (#2266).
  Anton's review of the first draft asked for three things this version is built on: one engine
  for the proposal review and the snapshot compare; identity declared in the schema rather than
  inferred from a member's name; and a matcher for lists without ids. Revised against cold
  implementing threads before review.
- **Feature:** any `list` field is compared one item at a time, with the body's own flip, wherever
  two versions of an entry are compared: the AI proposal review, and the snapshot compare. Items
  are matched first by the identity their group declares, then — for whatever identity leaves
  unmatched, which is everything in a list without identity — by aligning them the way the body
  aligns paragraphs. Unchanged items stay quiet, a changed item shows only what changed, and each
  change is adopted or declined on its own.
- **Amends:** ADR-0046 §2 and slice 3b ("structured → atomic `FieldDiff` flip, adopted whole") for
  `list` fields; ADR-0044 §F ("fields flip, and never interleave") for `list` fields in the
  snapshot compare. **Settles:** the per-item review that ADR-0048 §6 deferred to its S2 mockup
  (`docs/design/mockups/0048-ordered-list-field.html`) and that #698 left as a follow-up
  (`entryProposal.svelte.ts:53-54`); #2270 (which lists get ids); #2266. **Relates to:** ADR-0044
  §I, §J and Amendment 4 (the flip and its one verb); ADR-0089 (a reference-keyed list's key is
  its identity); ADR-0071 (no migration is needed, §2); #2265 (an unchanged field does not flip);
  #2255 (ids the save mints reach the draft).
- **Words used here.**
  - *L* is the **live** list — what the entry holds now, the warm side. *O* is the **other**
    list — the AI's proposal or the snapshot's value, the cool side. Adopting takes O's side.
  - A *pairing* matches one item of L with one item of O.
  - A *unit* is one thing the author adopts or declines, as a region is in the body.
  - An item's *identity member* is the member its group declares as identity (§1). An item's
    *title member* is its group's first `text` member other than the identity member; a group
    without one names its items by position ("Item 3").
  - A *scalar list* (`item_type`) stores bare values; the resolver gives it one synthetic member
    keyed `value` (`schema_inheritance.py:370-380`). Here each of its items is treated as a record
    with that one member, which is also its title.
- **Verified against `73f86e42` (2026-09-26).** Symbols first, line numbers second.

## Problem

Two versions of an entry are compared in two places, and both treat a list as one value.

- **The AI proposal review.** `EntryProposalController.structuredFlips`
  (`frontend/src/lib/stores/entryProposal.svelte.ts:183`) makes one `{was, now}` flip per field,
  and `commit()` writes the proposed list whole when that flip is adopted. The flip renders as
  `RailFlipCandidate` (`RailFieldRow.svelte:177`): the proposed list drawn read-only by
  `ListValueEditor`, whose rows cannot expand while read-only (`ListValueEditor.svelte:272`), over
  a "Current: …" line that joins every member of every item with " · " (`flipCurrentHint`,
  `lib/rail/fieldRowModel.ts:313`).
- **The snapshot compare.** `fieldDiffs` (`frontend/src/lib/utils/snapshotDiff.ts:780`) flips a
  differing list as one tinted value, and the rail gets no way to adopt it (`snapshotCompare`,
  `NodeEditor.svelte:312`, passes no `resolve`). The body's regions can be restored one by one; a
  list can only come back with a whole-snapshot restore.

For a beat list that fails three ways. The proposal cannot be read: a beat is mostly prose, shown
as one truncated line. The current value cannot be read: seven beats become one paragraph that
includes `true` for `required` and the raw ids. And the change cannot be found or chosen: nothing
says which beat changed or which sentence, and the only choice is all the beats or none.

Underneath sits a second problem: **nothing declares what identifies an item.** Three places
each decide it their own way:

- the AI path treats any list whose group has a member keyed `id` as having identity
  (`_id_bearing_list_field_ids`, `backend/app/services/ai/extraction.py:264`);
- the save mints ids only for two fields named in code, `_BEAT_LIST_FIELDS = ("beats",
  "instance_beats")` (`backend/app/services/project/plot.py:91`), and only on plot saves;
- the item editors show the `id` as an ordinary editable row (`BodyItemRows.svelte`, via
  `bodySections.ts:128-135`).

So a user's own list with an `id` member loses the id of every item the AI adds, and nothing
mints a new one (#2270).

## Intent

Wherever two versions of an entry are compared, a list is compared item by item with the body's
gestures and the body's flip, so the author can see and choose exactly what changed. What an item
*is* — its identity — is declared once, in the schema, and every path reads that declaration.

## Anti-goals

- **Not a beat feature.** Nothing keys on a field name or a plot kind. The rules are §1's and
  §3's, and they hold for any `list` field.
- **Not a new matcher.** Identity pairs first, and for an AI proposal the backend has already
  reconciled it (`reconcile_list_identity`, `backend/app/services/ai/list_identity.py`). What
  identity leaves unpaired aligns with the body's own alignment (§3), extracted, not
  reimplemented. No position-only matching; no second similarity rule.
- **Not a new kind of flip.** Every unit renders and adopts through the body's run machinery,
  `renderDiffRuns` and `adoptRegion` (`frontend/src/lib/utils/diffRuns.ts`). A unit that is not
  prose becomes a region built from display text (§6); it is not a toggle.
- **Not editing in a comparison.** No typing and no drag (ADR-0044 §I). An item is adopted or
  declined, never rewritten or moved by hand.
- **Not a re-diff.** L, O, the pairing and the units are captured once per comparison and
  re-projected locally as the author adopts (ADR-0044 Amendment 4).
- **Not a per-field button.** The proposal review's trigger stays the brainstorm's commit
  (ADR-0046 §5).
- **Not a compare view for new kinds.** Plotlines, cards, arcs and templates have snapshots on the
  backend but no compare view in the editor (`NodeEditor.svelte:227-229` limits it to scenes and
  lore). Giving them one is separate work; this ADR makes lists compare per item wherever a
  compare view exists.
- **Not a migration.** §2 says why none is needed.

## User journey (definition of done)

**A proposal.** The author has a plotline with seven beats. In its brainstorm chat they ask the
AI to sharpen the midpoint and add an aftermath beat, then press Propose. The review opens:

1. Under the body's flip sits a section headed **Specialized beats**. Five beats read as one quiet
   line each, the title alone. **Midpoint reversal** is open: under it, **Guidance** with the
   rewritten sentence tinted inline exactly as the body tints a change. A new beat,
   **Aftermath**, sits after **Resolution** as one cool block showing its title and prose.
2. In *Both* the author clicks the guidance change; it settles on the AI's wording. They leave
   **Aftermath** alone. *Current* shows the seven beats as they are; *Proposed* shows the eight
   the AI wrote.
3. They press **Done**. One save. The file has seven beats in their old order, the midpoint's
   guidance is the AI's, every id is unchanged, and the pane is clean afterwards.

**Accept all** would have saved the AI's eight beats. **Reject all** saves nothing.

**A snapshot.** A lore entry has a list of rumours, one line each, with no identity. The author
parks on last week's snapshot. The rail row for **Rumours** no longer flips; under the body's
compare sits a **Rumours** section: two rumours unchanged, one reworded since (its words tinted),
one the author has since deleted (a cool block). They click the deleted rumour; it comes back, at
its old place. The pane saves as it does after restoring a body region.

## Decision

### 1. A group declares its items' identity

A group gains one attribute, `identity`, naming one of its `text` members:

```yaml
groups:
  plot_beat:
    name: Beat
    identity: id
    members: [...]
```

- **Declared, resolved, validated.** `MetadataGroupDefinition` (`backend/app/models/schema.py:340`)
  gains `identity: str | None = None`. The resolver stamps it onto every list field using the
  group as `item_identity`, as it stamps `item_members` (`_stamp_list_item_members`,
  `schema_inheritance.py:351`), and it joins `RESOLVER_STAMPED_FIELD_KEYS` (`:29`) so it is never
  persisted on a field. The validator reports an `identity` that names no member, or a member that
  is not `text`. The layered merge needs nothing new: groups merge per key, so a layer that
  redefines a group's members inherits `identity` unless it clears it.
- **Kept in step with the members.** Renaming the identity member in the Groups dialog renames
  `identity` with it, and removing the member clears `identity`, in the same write
  (`upsert_metadata_group` → `_reconcile_group_member_data`, `schema_groups.py:98-123`).
- **Authorable.** The Groups dialog (`GroupsManagerDialog.svelte`) offers the choice: none, or one
  of the group's `text` members. A user's own group can declare identity exactly as a built-in one
  does.
- **Built-ins.** `plot_beat` and `plot_instance_beat` (`default_schema.py:95`, `:114`) declare
  `identity: id`.
- **Declared identity wins over ADR-0089's inference.** ADR-0089 infers a reference-keyed list
  from its shape — exactly one `entity_ref` member (`keyedListKeyMember`,
  `lib/editor-core/keyedList.ts:16`; `keyed_list_key`, `metadata_refs.py:105`) — and that key is
  its identity here. A group that *declares* identity is never reference-keyed, whatever its
  members: a beat that gains a point-of-view character is still one beat per id, not one beat per
  character. This amends ADR-0089 §1 for groups that declare identity; groups that declare none
  keep its inference unchanged.
- **The identity member is machine-owned.** Wherever items are edited — `BodyItemRows`,
  `ListValueEditor`'s rows and collapsed summary, `BodyListSection`'s title — it is neither shown
  nor editable, never chosen as the title member, and not counted when `ListValueEditor` picks its
  layout from the number of members (`:87-89`). It is never a unit in a comparison.
- **Only a declaration counts.** Today the AI path reconciles any group with a member keyed `id`
  (#2243). After this, it reconciles only groups that declare identity; a user group with an `id`
  member it never declared is an ordinary text member. The built-in groups with an `id` member
  are exactly the two that declare it.

### 2. The save mints identity, for every kind

One schema-aware step replaces `_ensure_beat_identity` (`plot.py:404`): for every list field whose
group declares identity, give each item without a value — or whose value repeats an earlier
item's — a fresh opaque id. It keeps what `_ensure_beat_identity` guarantees today: an item that
has an id keeps it, so an edit never changes it.

- **Where: every save that writes an entry's own file from submitted metadata.** Scene save; lore
  owned save, fork and create; the plot folder save, create and template save (today's three
  `_ensure_beat_identity` call sites, `plot.py:232`, `:362`, `:1076`); research
  (`save_research_note`, which does not call `_normalise_metadata`); prompt owned save;
  assistant; tag; project node. Not inside `_validate_entry_metadata` (`metadata_values.py:198`),
  which also runs when a project is read, so minting there would write during validation.
- **Not on an override save.** A list other than a reference-keyed one cannot be overridden at
  all: its difference from the base is refused with 422 (`_scalar_override_row`,
  `overrides.py:736-751`). Minting a descendant's submission would *create* that difference —
  the base's items may not have ids yet — and fail every save of the entry from that layer. Ids
  are minted only where the list is owned.
- **Not where stored bytes are written back.** Promotion and snapshot restore write metadata that
  was already saved; mutation sets and chats write their own rows. None of them mint.
- **Which schema.** The schema the entry's file is authored against — the owning layer's, as the
  lore save validates it (`_schema_as_authored`, `lore.py:365`). If a descendant layer declares
  identity for a group its ancestor does not, the ancestor's entries are not minted; a comparison
  seen from the descendant then pairs those items by §3's leftover alignment.
- **Format.** Existing ids never change. New ids stay opaque — nothing parses them; the only code
  that builds one is the minting itself (`plot.py:459`). The two plot groups keep today's `beat_`
  prefix and title salt; any other group's ids use `item_` and its title member.
- **What it returns.** The step reports what it minted per field, as `_ensure_beat_identity` does
  today. The plot save's `plot_beats_saved` trace (#2260, `plot.py:361`, `:389-394`) keeps reading
  that for the beat fields and stays a beat trace.
- **Every reader switches to the declaration.** `_BEAT_LIST_FIELDS` goes. The AI path's
  `_id_bearing_list_field_ids` reads `item_identity`, and its title matching reads the title
  member instead of a hardcoded `title` (`list_identity.py:44`). The frontend's post-save
  stamping (`adoptSavedBeatIds`, `withStampedBeatIds`, `lib/plot/beatRoster.ts`) takes each
  field's identity key from the schema instead of `BEAT_LIST_FIELDS` and a hardcoded `.id`; its
  caller in `editorPanes.svelte.ts` passes the schema it already holds. The plot board's
  beat-specific readers (`beat_links` healing, `plot_board.py`) keep using `instance_beats` and
  `id` by name: they are about beats, not about identity.
- **No migration.** Built-in groups are not stored in projects: a new project's schema layer is
  empty (`_empty_metadata_schema`, `lifecycle.py:308`) and the defaults are read from code. Beat
  ids have been minted on every plot save since #779. A user's list gains ids the next time its
  entry is saved, which is the minting point anyway — and ADR-0071 forbids a document migration
  from reading the schema, so a backfill could not be one.

### 3. Pairing

The same function serves every comparison. It takes L, O and the field's definition.

**With identity** (declared, or ADR-0089's key), first by identity:

- an item of O pairs with the item of L that has the same identity value;
- a value repeated on either side pairs its first occurrence only — the first-wins rule
  `_index_stored_by_id` uses. Repeats are possible only in a file the save has not touched since,
  or in an old snapshot.

Then **the leftovers align** — the items of O and of L that did not pair, whether they lack a
value or carry one the other side lacks — by the alignment below, applied to the leftovers in
their own order. Items still unpaired after that are **additions** (O) and **removals** (L).

Aligning the leftovers covers a side whose items have no ids yet: a snapshot taken before a
group declared identity, an entry not saved since, an item added in the draft and not yet
autosaved. Without it, each of those would read as "remove everything, add everything". For a
proposal, the leftovers are items the backend's reconcile could not match by id or title; if the
alignment pairs two of them, the item keeps L's id, so a beat the AI retitled and rewrote keeps
its id and its card links.

**Without identity**, every item is a leftover. Items align the way the body aligns paragraphs
(`diffRuns`, `snapshotDiff.ts:465`), each item rendered to a comparison string:

- the string is the item's non-empty member values in declared order, one per line, as display
  text, leaving out the identity member and any value equal to its member's default. Member names
  are not included. So two short, unrelated items do not look alike merely because both have an
  empty note and the default `required`;
- exact equal strings anchor, by the same `SequenceMatcher` the body uses;
- inside each span between anchors, the body's greedy pass (`alignBlocks`, `:479`) pairs an item
  with a rewrite of itself (`isARewriteOf`, `:520`: at least half its words shared, looking up to
  four items ahead) as **edited**. Where the body falls back to showing a pair stacked
  (`stackedPair`), an item becomes one removal and one addition.

These functions are extracted from `snapshotDiff.ts` to operate on indices rather than markdown
blocks, and `diffRuns` is rebuilt on them. Its parity corpus against the Python twin
(`diffRuns.fixtures.json`, `test_diff_fixtures_are_current`) must stay green, which proves the
extraction changed nothing for the body. The item alignment itself has no backend consumer and no
Python twin.

**Member comparison.** A paired item's members are compared over the item group's declared
members except the identity member. An absent value reads as the member's default (`required`
defaults to true). A `long_text` member is compared after `normalizeReviewMarkdown`; any other
member with `sameRenderedValue`. A paired item with no differing member is **unchanged**;
otherwise it is **edited**. Keys outside the declared members are not compared.

**Captured once**, keyed on the node and the comparison (the proposal, or the parked snapshot),
the way `RevisionFlip` captures its runs with `untrack`. The live metadata moves during a
comparison — adopted fields merge into it before a save, a failed save keeps the review open — and
re-pairing against it would count an adopted addition twice.

The capture happens only once NodeEditor's node sync has run for that node (`loadedSceneId`
equals the node id, set at `NodeEditor.svelte:~708`) and the schema is loaded. Before that, the
controller already has the new node id but still the previous node's metadata
(`NodeEditor.svelte:499-507` runs first), and a capture would read the wrong list.

### 4. Units

Every unit is a region settled with the body's single verb, `adoptRegion` (ADR-0044 Amendment 4),
and its rule decides the outcome: **a unit is adopted when `adoptRegion` returns a body, that is,
when O's side survives.** So clicking a change's cool side adopts it, and clicking its warm side
keeps L's value. Clicking an addition includes it. Clicking a removal removes the item, since O's
side of a removal is empty; a removal left alone is kept. A unit never clicked counts as declined.
A settled unit stays settled for the rest of the comparison.

| Unit | Key | Settles to |
|---|---|---|
| a differing `long_text` member of an edited item | `(field, L index, member)`; its regions settle one by one | the region-resolved text |
| a differing other member of an edited item | `(field, L index, member)` | O's value or L's |
| an addition | `(field, "add", O index)` | included or left out |
| a removal | `(field, "remove", L index)` | removed or kept |
| the order, when paired items appear in a different relative order in O than in L | `(field, "order")` | O's order or L's |

Units are keyed by position within L and O, which the capture fixes; identity values may be
absent or repeated. Alignment pairs in order, so a list without identity never has an order unit.

A list with no units — equal, or different only cosmetically or by an absent default — shows
nothing and is not written, as #2265 does for other fields.

### 5. The sequence and the saved list

Both what is shown and what is saved come from one sequence, built in this order:

1. **Paired items**, in O's order if the order unit is adopted or there is none, else in L's.
2. **Removals**, one at a time in L's order, each placed immediately after the nearest item before
   it in L that is already in the sequence, or first if there is none.
3. **Additions**, one at a time in O's order, each placed immediately after the nearest item
   before it in O that is already in the sequence, or first if there is none. When an addition
   and a removal follow the same item, the addition comes first.

With the order declined, an included addition therefore sits after the item that precedes it in
O — the closest L's order can come to where O put it.

The saved list is that sequence without the additions left out and the removals removed. Each
paired item starts from its L object — identity and any undeclared keys included — with every
adopted member unit written over it.

Two invariants pin this, and they are its tests. They hold for any pairing, so a poor alignment
can group changes badly but cannot corrupt what is saved:

- **Every unit declined gives L exactly.** With the order in L's, step 2 rebuilds L around the
  paired items, and no addition is kept.
- **Every unit adopted gives a list that renders the same as O**, compared as §3 compares members.
  With the order in O's, step 3 rebuilds O around the paired items, and every removal is gone. It
  is not byte-identical: a member with no unit keeps L's text, and a paired item keeps L's
  identity.

When the saved list renders the same as L, the field is not written.

### 6. Rendering

A section per list field that has units, headed with the field's name, in the comparison's flip
stack after the body (and, in a proposal, after the `long_text` flips). In *Both* it shows the §5
sequence; adopting the order unit moves the rows once, to O's order. The field has no flip row in
the rail or the front matter. Where the rail shows its index row (lists as body sections), that
row's click does nothing during the comparison, since the body sections it would focus are hidden.

- **Unchanged item:** one quiet line, its title.
- **Edited item:** its L title, then each unit under its member's name. A changed title is itself
  one of those units. A `long_text` member is a run-diff of that member (`reviewBodyProposal`).
  Any other member is one region: a stacked run of L's display text and a stacked run of O's.
  Members without a unit are not shown.
- **Addition:** one stacked cool region holding the whole item, so it is adopted as one unit.
  **Removal:** the same, warm.
- **Order:** one stacked region at the head of the section: the paired items' titles in O's order
  over the same titles in L's. Once settled, the region is removed, since the rows below already
  show the result.

These are the body's tints for a change, an insertion and a deletion, and no glyphs (ADR-0044 §J).

**Run text.** Every run is rendered as markdown (`renderDiffRuns`), so the text is built, not
passed through:

- a member's display text comes from its definition: the default applied to an absent value, a
  boolean as "Yes" / "No", a select as its option's label, a reference as its target's title (the
  resolution `flipCurrentHint` already does, `fieldRowModel.ts:313-331`), an empty value as "—".
  It is markdown-escaped, since a title like "1. Setup" or "# x" would otherwise render as a list
  or a heading. A reference-keyed item's title is its key's target title;
- a whole item is its escaped title in bold, then each non-empty member under its escaped name —
  prose members as the markdown they already are, other members as escaped display text;
- the order is two numbered lists of escaped titles.

**Views.** The two-sided view applies here as to the body. L's side shows every item in L's order,
members at L's values, no additions. O's side shows every item in O's order, members at O's
values, no removals. A settled unit shows its settled value in every view, as a settled body
region does. Adoption exists only in *Both*.

**Where the list cannot be written, nothing is adopted.** A list other than a reference-keyed one
cannot be overridden (§2), so on an entry seen at a descendant layer — a proposal on an inherited
entry, or a snapshot parked at an override layer — the section shows the same comparison with no
region clickable, and the list is never written.

### 7. In the proposal review

- **Where.** `EntryRevisionReview.svelte`'s flip stack, after the body and `long_text` flips.
- **Which fields.** Every proposed `list` field leaves `structuredFlips`. An entry type whose body
  shape mounts no review overlay (`EditorBodyHost.svelte`: the overlay exists for prose and code
  bodies only) keeps the atomic flip for its lists. That flip draws both sides as rows with the
  read-only `FieldValueEditor` its proposed side already uses, instead of the "Current: …" line
  (#2266), and a read-only `ListValueEditor` lets its rows expand — expanding is reading, not
  editing (today it cannot, `ListValueEditor.svelte:271-283`).
- **Accept all** adopts every unit, so it saves the §5 list with every unit adopted: O's content,
  with each paired item keeping L's identity. Writing O verbatim instead would drop the ids of
  items paired by alignment, and Accept all would then keep fewer card links than clicking
  through every change. **Reject all** is `abandon()` and writes nothing. An adopted list goes into
  `commit()`'s `fields` and is saved in the one PUT (ADR-0046 §1).
- **The chrome follows.** `hasReview` counts a list with units, so a proposal that changes only
  beats still freezes the entry and opens the review. The view control (`hasProse`,
  `EntryRevisionReview.svelte:84`) appears when there is a list section. The hint stops saying "in
  the details panel" when every structured change is in the review (`:132`). The replace-mode path
  (`acceptFields`) clears the list state as it clears `adoptedStructured`.

### 8. In the snapshot compare

- **Where.** Wherever the compare view exists today (scenes and lore). The compare has no flip
  stack: its overlay is one rendered block (`ReadOnlyBodyOverlay`) with `frontMatter` and
  `appendix` slots, so the list sections go in its `appendix`, after the body. Like the overlay
  itself, they show on the Body tab only (`EditorBodyHost.svelte:449`).
- **Sides.** L is the live metadata the strip reads when it parks (`readLive`,
  `snapshotStrip.svelte.ts:378`), O the parked snapshot's — both captured at park time, as the
  body's runs are.
- **Which fields.** Every differing `list` field leaves the rail's `compare.fields`. Other fields
  keep today's passive flip.
- **Adopting** restores the snapshot's side of one unit. The composed list is written into the
  pane's metadata as any field edit is (`metadata = next; emitChange()`, as the proposal's
  `onAdoptFields` does; the parked editor is read-only to typing, not to this) and saves through
  the pane's autosave, as adopting a body region writes the buffer and saves through it
  (`SnapshotStripController.adopt`, `:468`). A list adopt takes the strip's `busy` gate, as body
  adopts, restores and pins do, so it cannot race them. This is the first field-level adopt in
  the snapshot compare, and it exists only for lists.
- The compare's own views apply: *Now* is L's side, *Snapshot* O's.

## Why

- **Why items, not the whole list.** A list is several things. The author's question is "what
  changed in my beats", and only a per-item view answers it. The atomic rule was argued for single
  values and never for this shape.
- **Why one engine.** The proposal review and the snapshot compare already share the body's
  engine and its gesture. A list compared one way in one place and another way in the other would
  teach two meanings for the same tint.
- **Why declared identity.** Identity decides whether two versions of an item are the same item;
  that is too much to infer from a member happening to be named `id`, and the three places that
  inferred it disagreed.
- **Why identity first, then alignment.** Ids are certain, and for a proposal they agree with the
  backend's reconcile, so identity decides every pair it can. What identity leaves unpaired —
  everything, for a list without identity — aligns by the body's own answer to "which paragraph
  became which". The §5 invariants make a poor pairing harmless to the saved list, and an
  alignment that pairs a retitled beat keeps its id.
- **Why not position alone.** One item inserted near the top shifts everything after it, so every
  later item reads as edited, each against its neighbour's text.
- **Why the order is a unit.** Without it, declining everything could still reorder the list.
- **Why one sequence for display and save.** Otherwise the rows could show one order while the
  file saved another.
- **Why a scalar member is a region, not a toggle.** One gesture across the whole comparison: the
  rail's flip toggles, the body's regions settle once, and one item must not do both.
- **Why Accept all is every unit adopted.** It must save the same list as clicking through every
  change. Writing O verbatim would differ exactly where it matters: the ids of items paired by
  alignment.
- **Why no ids on an override save.** A list cannot be overridden; minting a descendant's copy
  would manufacture the difference that makes the save fail.

## Rejected

- **Keep the atomic flip and make it readable.** It fixes reading and leaves choosing.
- **Diff the list as text.** Changes would cross item boundaries, and adopting a region could
  produce text that is not a valid list.
- **Infer identity from a member named `id`.** It is what the code does now, and #2270 is the
  result.
- **Leave identity's leftovers unaligned.** Any side without ids yet — an old snapshot, an entry
  not saved since identity was declared — would read as "remove everything, add everything".
- **A beat-specific component.** It would not serve the next list, and it is the "special enough
  for its own subsystem" drift the node model exists to resist.
- **Derive the pairing from the live metadata.** A failed save would duplicate items.

## Slices

Each lands as its own PR, in order.

**S1 — Identity is declared and minted** (§1, §2; closes #2270). The group attribute, its stamp
and validation, the Groups dialog choice, the built-in declarations, one minting step in every
save path, every reader switched to the declaration, and the identity member hidden in the item
editors.
*Not:* any comparison change. *Done when:* a user-defined group that declares identity gets ids
minted on a lore save and on a scene save; saving the same entry from a descendant layer still
succeeds and mints nothing; a proposal adding an item to it round-trips with a new id; the beat
lists behave exactly as before; the identity member no longer shows in the editors.

**S2 — The engine, as pure functions** (§3–§5). Pairing (identity and alignment), units, the
sequence and the saved list, with the alignment extracted from `snapshotDiff.ts` and `diffRuns`
rebuilt on it. Nothing calls the new functions yet.
*Not:* any controller or component change. *Done when:* both §5 invariants hold as unit tests over
the Test surface, and the `diffRuns` parity corpus is unchanged and green.

**S3 — The proposal review** (§6, §7). *Not:* editing, dragging, a glyph, a toggle, or anything
keyed on field names. *Done when:* a component test with a seeded proposal walks the proposal
journey, and the journey works in the browser on a copy of a real plotline, checked against the
saved file.

**S4 — The snapshot compare** (§6, §8). *Not:* a compare view for plot kinds; adopting non-list
fields. *Done when:* the snapshot journey works in the browser on a copy of a real lore entry.

## Test surface

- Identity: a group declaring it gets ids on every save path in §2; an override save mints
  nothing and still succeeds; an existing id never changes; a repeated id is re-minted; the
  validator reports a missing or non-`text` identity member; renaming the identity member renames
  `identity`, removing it clears `identity`; a group declaring identity with one `entity_ref`
  member is not reference-keyed.
- Pairing with identity: kept, edited, added (no value / unknown value), removed, a repeated value
  in L and in O; leftovers aligned — an O without ids against an L with ids pairs by content, and
  a retitled, rewritten item keeps L's id.
- Pairing by alignment: an unchanged list; one item reworded; one inserted at the top (no other
  item reads as edited); one deleted; two unrelated lists of short items with empty and default
  members (all removals and additions); a scalar list.
- Members: an absent value against its default is unchanged; cosmetic markdown is unchanged; a key
  outside the declared members is ignored; the identity member never forms a unit.
- Sequence: adjacent additions (`L=[a,b]`, `O=[a,n1,n2,b]`); adjacent removals (`L=[a,r1,r2,b]`);
  an addition and a removal after the same item; both first (`L=[r,a]`, `O=[n,a]`); a reorder with
  an addition and a removal (`L=[a,r,b]`, `O=[b,n,a]`) under every combination of settled units.
- Both invariants over all of the above, for both pairings.
- A unit never clicked counts as declined; clicking a removal removes the item.
- A list with no units shows no section and is not written.
- Accept all saves the same list as adopting every unit one by one.
- At an override layer the section shows and nothing is adoptable.
- In the snapshot compare, a list adopt waits for the strip's `busy` gate.
- Run text: a title such as "1. Setup" renders as text; a boolean member reads "Yes" / "No"; an
  absent value reads as its default.
- A failed save keeps the pairing, and a retry saves no duplicate; switching the pane between two
  nodes captures each node's own list.
- `diffRuns` parity corpus unchanged.

## Open

- **The plot kinds' compare view.** Plot nodes have snapshots but no compare view; when they gain
  one, their lists compare per item by §8 with nothing further to decide here.
