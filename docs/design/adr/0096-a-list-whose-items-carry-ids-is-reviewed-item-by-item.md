# ADR-0096: A list whose items carry ids is reviewed item by item

- **Status:** Proposed — 2026-09-26. Text by Claude from a conversation with Anton on 2026-09-26,
  which started from screenshots of a plotline review ("The Girl in the Ghost") where the
  proposed beats could not be read and the current beats were one flattened string (#2266).
  Revised against a cold implementing thread before review.
- **Feature:** in the AI proposal review, a list whose items carry ids — today a plotline's or
  arc's `instance_beats` and a template's `beats` — is reviewed one item at a time, inside the
  review and with the body's own flip. Unchanged items stay quiet, a changed item shows only what
  changed, and each change is adopted or declined on its own.
- **Amends:** ADR-0046 §2 and slice 3b ("structured → atomic `FieldDiff` flip, adopted whole"),
  for these lists only. **Settles:** the per-item review that ADR-0048 §6 deferred to its S2
  mockup (`docs/design/mockups/0048-ordered-list-field.html`) and that #698 left as a follow-up
  (`entryProposal.svelte.ts:53-54`). **Relates to:** ADR-0044 §F, §I, §J and Amendment 4 (the
  flip and its one verb); ADR-0089 (reference-keyed lists, out of scope); #2265 (an unchanged
  field does not flip); #2255 (ids the save mints reach the draft); #2270 (which lists get ids).
- **Words used here.**
  - An *item list* is defined in §1.
  - *C* is the current list and *P* the proposed list, as the review received it.
  - A *pairing* matches one item of C with one item of P.
  - A *unit* is one thing the author adopts or declines, as a region is in the body.
  - An item's *title member* is its group's first `text` member other than `id`. A group without
    one has no title member, and its items are named by position ("Item 3").
- **Verified against `73f86e42` (2026-09-26).** Symbols first, line numbers second.

## Problem

The review treats a list field as one value. `EntryProposalController.structuredFlips`
(`frontend/src/lib/stores/entryProposal.svelte.ts:183`) makes one `{was, now}` flip per field, and
`commit()` writes the proposed list whole when that flip is adopted. The flip renders in the rail
or the review's front matter as `RailFlipCandidate` (`RailFieldRow.svelte:177`): the proposed list
drawn read-only by `ListValueEditor`, whose rows cannot expand while read-only
(`ListValueEditor.svelte:272`), over a "Current: …" line that joins every member of every item
with " · " (`flipCurrentHint`, `lib/rail/fieldRowModel.ts:313`).

For a beat list that fails three ways:

- **The proposal cannot be read.** A beat is mostly prose — function, guidance, specifics — and
  the review shows one truncated line per beat.
- **The current value cannot be read.** Seven beats become one paragraph that includes `true` for
  `required` and the raw ids.
- **The change cannot be found or chosen.** Nothing says which beat the AI touched or which
  sentence it rewrote, and the only choice is all the beats or none.

ADR-0046 made structured fields atomic for single values: "there is no prose to run-diff on a
`select`" (§2), after ADR-0044 §F's "a field value is atomic — it resolves in one blink". Neither
considered a list whose items are prose-bearing records. The body gets region-by-region adoption;
the beats, which are also prose, get none.

## Intent

Review a beat list with the body's gestures and the body's flip, one beat at a time, so the author
can see and choose exactly what the AI changed. What is saved is unchanged in kind: one patch,
one save, nothing written before adopt.

## Anti-goals

- **Not a beat widget.** Nothing keys on the field names `beats` / `instance_beats` or on a plot
  kind. The rule is §1's.
- **Not a new matcher.** Items pair by `id` only. The backend reconciled P's ids against the
  stored list — by id, then by title (`reconcile_list_identity`,
  `backend/app/services/ai/list_identity.py`) — before the review sees the patch. The 0048
  mockup's "position-with-content-similarity" matching is not built.
- **Not a new kind of flip.** Every unit renders and adopts through the body's run machinery —
  `renderDiffRuns` and `adoptRegion` (`frontend/src/lib/utils/diffRuns.ts`). A unit that is not
  prose becomes a region built from display text (§5); it is not a toggle.
- **Not editing in the review.** No typing and no drag (ADR-0044 §I). An item cannot be
  reordered, retitled or rewritten here, only adopted or declined.
- **Not a re-diff.** C, the pairing and the units are captured once per proposal and re-projected
  locally as the author adopts (ADR-0044 Amendment 4).
- **Not a per-field button.** The trigger stays the brainstorm's commit (ADR-0046 §5).
- **Not a backend change.** The patch, the reconcile and the save are unchanged.

## User journey (definition of done)

The author has a plotline with seven beats. In its brainstorm chat they ask the AI to sharpen the
midpoint and add an aftermath beat, then press Propose. The review opens on the plotline:

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

## Decision

### 1. Which lists

A proposed field is an *item list* when all of these hold; otherwise it keeps today's atomic
flip unchanged:

- it is a `type: list` field whose item group declares a member keyed `id` — the rule the AI path
  already uses (`_id_bearing_list_field_ids`, `backend/app/services/ai/extraction.py:264`);
- it is not reference-keyed (`keyedListKeyMember`, `lib/editor-core/keyedList.ts:16`). A
  reference-keyed list is ADR-0089's, and its key wins here as it does for body sections
  (`listHasProseItems`, `lib/editor-core/bodySections.ts:100`);
- every item of C carries a non-empty `id`. Without ids nothing can pair, and the review would
  show "remove everything, add everything". Today only the plot beat lists are given ids on save
  (#2270). An empty C qualifies: every proposed item is then an addition, reviewed one by one;
- the entry's body shape mounts the review overlay (prose or code). An entry type with no body
  has nowhere to show the section, so its lists stay atomic.

An item list is never in `structuredFlips`. One with no units (§3) — equal, or different only
cosmetically or by an absent default — shows nothing and is not written, as #2265 does for other
fields. It must not fall back to the atomic flip, whose plain equality would see a difference.

### 2. Pairing

Captured once per proposal — keyed on the node id and the proposal, the way `RevisionFlip`
captures its runs with `untrack` — and never re-derived from the live metadata. The live metadata
moves during a review: adopted fields merge into it before the save, and a failed save keeps the
review open. Re-pairing against it would count an adopted addition twice.

The capture waits until the metadata the controller holds belongs to that node and the schema is
loaded. The controller learns the node id one tick before its metadata when the pane switches
nodes (`NodeEditor.svelte:499-507` runs before the node sync at `:708`), and a capture in that tick
would read another node's list or an empty one.

- An item of P whose `id` equals an item of C's pairs with it.
- An item of P with no `id`, or an `id` C lacks, is an **addition**. The backend strips an id it
  could not match, so a new item usually arrives without one.
- An item of C that nothing in P pairs with is a **removal**. If C holds a duplicate id, the first
  occurrence pairs and later ones are removals — the first-wins rule `_index_stored_by_id` uses.

Members are compared over the item group's declared members except `id`. An absent value reads
as the member's default (`required` defaults to true), so a stored beat with no `required` key
and a proposed `required: true` are the same. A `long_text` member is compared after
`normalizeReviewMarkdown`; any other member with `sameRenderedValue`. A paired item with no
differing member is **unchanged**; otherwise it is **edited**. Keys outside the declared members
are not reviewed.

### 3. Units and their keys

Every unit is a region settled with the body's single verb, `adoptRegion` (ADR-0044 Amendment 4),
and its rule decides the outcome: **a unit is adopted when `adoptRegion` returns a body, that is,
when the proposal's side survives.** So clicking a change's cool side adopts it, and clicking its
warm side keeps the current value. Clicking an addition includes it. Clicking a removal removes
the item, since the proposal's side of a removal is empty; a removal left alone is kept. A unit
never clicked counts as declined. A settled unit stays settled for the rest of the review, and
Reject all or Close is how to start over, as for the body.

| Unit | Key | Settles to |
|---|---|---|
| a differing `long_text` member of an edited item | `(field, item id, member)`; its regions settle one by one | the region-resolved text |
| a differing other member of an edited item | `(field, item id, member)` | the proposed or the current value |
| an addition | `(field, "add", index in P)` | included or left out |
| a removal | `(field, "remove", index in C)` | removed or kept |
| the order, when the paired items appear in a different relative order in P than in C | `(field, "order")` | P's order or C's |

Additions are keyed by position because they usually have no id. Removals are keyed by position
because a duplicate id in C is shared with the paired first occurrence.

### 4. The sequence and the saved list

Both the display and the save come from one sequence, built in this order:

1. **Paired items**, in P's order if the order unit is adopted or there is none, else in C's.
2. **Removals**, one at a time in C's order, each placed immediately after the nearest item before
   it in C that is already in the sequence, or first if there is none.
3. **Additions**, one at a time in P's order, each placed immediately after the nearest item
   before it in P that is already in the sequence, or first if there is none. When an addition
   and a removal follow the same item, the addition comes first.

With the order declined, an included addition therefore sits after the item that precedes it in
P. That is the closest C's order can come to where the AI put it, and it is intended.

The saved list is that sequence without the additions left out and the removals removed. Each
paired item starts from its current object — `id` and any undeclared keys included — with every
adopted member unit written over it.

Two invariants pin this, and they are its tests:

- **Every unit declined gives C exactly.** With the order in C's, step 2 rebuilds C around the
  paired items, and no addition is kept.
- **Every unit adopted gives a list that renders the same as P**, compared as §2 compares members.
  With the order in P's, step 3 rebuilds P around the paired items, and every removal is gone.
  It is not byte-identical: a member with no unit keeps the current text.

**Accept all** is therefore not "adopt every unit". It writes P verbatim, as Accept all writes a
proposed body today. **Reject all** is `abandon()` and writes nothing. When the saved list renders
the same as C, the field is not written.

Adopted, the saved list goes into `commit()`'s `fields` like any adopted field and is saved in the
one PUT (ADR-0046 §1).

### 5. Rendering

A section in the review overlay's flip stack (`EntryRevisionReview.svelte`), after the body and
the `long_text` flips, one per item list, headed with the field's name. In *Both* it shows the §4
sequence; adopting the order unit moves the rows once, to P's order.

- **Unchanged item:** one quiet line, its title.
- **Edited item:** its current title, then each unit under its member's name. A changed title is
  itself one of those units. A `long_text` member is a run-diff of that member
  (`reviewBodyProposal`). Any other member is one region: a stacked run of the current display
  text and a stacked run of the proposed one. Members without a unit are not shown.
- **Addition:** one stacked cool region holding the whole item, so the item is adopted as one
  unit, not member by member. **Removal:** the same, warm.
- **Order:** one stacked region at the head of the section: the paired items' titles in P's
  order over the same titles in C's. Once settled, the region is removed rather than left as
  plain text, since the rows below already show the result.

These are the body's tints for a change, an insertion and a deletion, and no glyphs (ADR-0044 §J).

**Run text.** Every run is rendered as markdown (`renderDiffRuns`), so the text is built, not
passed through:

- a member's display text comes from its definition: the default applied to an absent value, a
  boolean as "Yes" / "No", a select as its option's label, an empty value as "—". It is
  markdown-escaped, since a title like "1. Setup" or "# x" would otherwise render as a list or a
  heading;
- a whole item is its escaped title in bold, then each non-empty member under its escaped name —
  prose members as the markdown they already are, other members as escaped display text;
- the order is two numbered lists of escaped titles.

**Views.** The Current / Proposed / Both view applies here as to the body. *Current* shows every
item in C's order, members at their current values, no additions. *Proposed* shows every item in
P's order, members at their proposed values, no removals. A settled unit shows its settled value
in every view, as a settled body region does. Adoption exists only in *Both*.

The review's own chrome follows:

- `hasReview` counts an item list with units. A proposal that changes only beats must still
  freeze the entry and open the review.
- The view control (`hasProse`, `EntryRevisionReview.svelte:84`) appears when there is an item
  list, as it does for prose.
- The hint no longer says "in the details panel" when every structured change is in the section
  (`:132`).
- The field has no flip row in the rail or the front matter. Where the rail shows its index row
  (lists as body sections), that row's click does nothing while the review is open, since the
  body sections it would focus are hidden.
- The replace-mode path (`acceptFields`) clears the item-list state as it clears
  `adoptedStructured`.

### 6. The atomic flip's "Current" side

For a list that stays atomic (§1), the "Current: …" line is replaced by the current list drawn
read-only with the same `FieldValueEditor` the proposed side uses (`RailFlipCandidate.svelte`), so
both sides are rows (#2266). Single values keep the one-line caption.

## Why

- **Why items, not the whole list.** A beat list is prose in records. The author's question is
  "what did the AI change in my beats", and only a per-item view answers it. The atomic rule was
  argued for single values and never for this shape.
- **Why pair by id only.** The ids are real: minted on save and never changed by an edit
  (`_ensure_beat_identity`), shown to the model (#2243), and reconciled against the stored list
  before the review sees the patch. A second, similarity-based matcher in the frontend would
  disagree with that reconcile, and the review would show one pairing while the save kept another.
- **Why the order is a unit.** Without it, declining everything could still reorder the beats,
  and the review would write an order the author never chose.
- **Why one sequence for display and save.** If the rows showed one order and the file saved
  another, the review would misstate what Done writes.
- **Why a scalar member is a region, not a toggle.** One gesture across the whole review. The
  rail's flip is a reversible toggle; the body's regions settle once. Mixing them inside one beat
  would give one item two behaviours.
- **Why Accept all bypasses the units.** "Adopt everything" should save what the AI wrote,
  byte for byte, not a reconstruction of it.

## Rejected

- **Keep the atomic flip and make it readable** (render both sides as expandable rows). It fixes
  reading and leaves choosing: the author still takes all beats or none.
- **Diff the list as text** (serialize each item and run-diff the lot). Changes would cross item
  boundaries, and adopting a region could produce text that is not a valid list.
- **Match by position or similarity in the frontend.** See Why; the ids exist.
- **A beat-specific review component.** It would not serve the next item list, and it is the
  "special enough for its own subsystem" drift the node model exists to resist.
- **Derive the pairing from the live metadata.** See §2: a failed save would duplicate items.

## Slices

Each lands as its own PR, in order.

**S1 — The model, as pure functions.** A module that takes C, P and the item group's members and
returns the pairing, the units, the §4 sequence and the saved list for a given set of settled
units. Nothing calls it yet.
*Not:* any controller, component or backend change. *Done when:* both §4 invariants hold as unit
tests, with the cases under Test surface.

**S2 — The review.** The controller captures C and the pairing per proposal, holds the unit
state, counts item lists in `hasReview`, and writes the saved list from `commit()`; Accept all
writes P. The item list leaves `structuredFlips`. The §5 section, view control, hint and index
row. S1 and S2 are separate so that no build ever has a list that is both in `structuredFlips` and
reviewed per item.
*Not:* editing, dragging, a glyph, a toggle, or anything keyed on field names. *Done when:* a
component test with a seeded proposal walks the journey, and the journey works in the browser on
a copy of a real plotline with a seeded proposal, checked against the saved file.

**S3 — The atomic lists' current side** (§6, #2266). *Not:* per-item review of those lists.
*Done when:* an atomic record list's flip shows both sides as rows.

## Test surface

- Pairing: kept, edited, added (no id / unknown id), removed, duplicate id in C.
- Members: an absent value against its default is unchanged; cosmetic markdown is unchanged; a key
  outside the declared members is ignored.
- Sequence: adjacent additions (`C=[a,b]`, `P=[a,n1,n2,b]`); adjacent removals
  (`C=[a,r1,r2,b]`); an addition and a removal after the same item; both first (`C=[r,a]`,
  `P=[n,a]`); an AI reorder with everything declined; a reorder adopted with a removal declined.
- Both invariants over all of the above, and a reorder with an addition and a removal
  (`C=[a,r,b]`, `P=[b,n,a]`) under every combination of settled units.
- A unit never clicked counts as declined; clicking a removal removes the item.
- A list with no units shows no section, is not written and is not an atomic flip; a C item
  without an id makes the list atomic; an empty C reviews every item as an addition; a
  reference-keyed list with an `id` member stays atomic.
- Run text: a title such as "1. Setup" renders as text; a boolean member reads "Yes" / "No"; an
  absent value reads as its default.
- A failed save keeps the pairing, and a retry saves no duplicate. Switching the pane between two
  nodes with proposals captures each node's own list.

## Open

- **Which lists get ids** (#2270). The AI path reconciles any list with an `id` member, while the
  save mints ids only for the two plot beat lists (`_BEAT_LIST_FIELDS`,
  `backend/app/services/project/plot.py:91`). §1's "every item of C carries an id" keeps this ADR
  correct either way. It does not settle which rule is right.
