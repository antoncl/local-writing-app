# ADR-0089: A list row qualifies a reference, is keyed by its target, and follows the mutation rules

- **Status:** Proposed (2026-09-20). Replaces the shape sketched on #2012 (a `relation` kind).
- **Feature:** relationships and "who knows what when" as metadata (#2012, section B3 of the
  metadata-material epic #2005).
- **Relates to:** ADR-0081 (references at any depth — the row shape and the one traversal),
  ADR-0009 (**amends** — a fourth collection class), ADR-0017 (**amends** — the diff is by key),
  ADR-0001/0003/0010 (markers, cumulative resolution, close), ADR-0013 and ADR-0042 §5 (the
  scrubber as review and edit surface), ADR-0039 (layer overrides), ADR-0086 (the lore budget and
  `named` expansion), ADR-0082 (tags as nodes — the precedent the rejected node shape leaned on).
- **Verified against `342be0ce` (2026-09-20).** Symbols first, line numbers second; the numbers
  rot, the symbols do not.

## Problem

A list of people on a character carries a word per person: brother, rival, the only witness. The
word changes as the story does. A mystery writer keeps a second list of the same shape: which
character knows which fact, from which chapter. Reading Chapter 14, the writer and the AI should
both see "Tomas: brother, reconciled", not the base value and not the ending.

The shape already exists. A `list` field with an `item_group` holds rows whose members may be a
reference (`LIST_ITEM_GROUP_MEMBER_TYPES`, `backend/app/models/schema.py:31`), ADR-0081 made
those references first-class for indexing, scrubbing and rendering, and its consequences section
names "a relationship group `{target: entity_ref, kind: select}`" as the shape it unlocks. Two
things stop at the field boundary:

- **A mutation cannot name a row.** The marker's target is `(entity, field key)`; the field
  token admits dots but nothing splits them (`MUTATION_MARKER_PATTERN`,
  `backend/app/services/project/lore_mutations.py:72`; `_validate_scene_mutations`, `:364`). A
  `list` field is not a collection type (`COLLECTION_FIELD_TYPES`, `:102`), a replace marker's
  string is rejected by `_validate_list_field_value`
  (`backend/app/services/project/metadata_values.py:352`), and the authoring dialog leaves `list`
  fields out of its roster for exactly that reason (`buildFieldOptions`,
  `frontend/src/components/editor/body/MutationFieldRows.svelte:66`, "per-item mutation ops for
  lists are a follow-up").
- **A layer override cannot hold a row either.** An override row is the same string-valued
  triple (`MutationSetRow`, `backend/app/models/entries.py:947`), so a book editing a list on a
  series-owned entry gets a 422 (`_scalar_override_row`,
  `backend/app/services/project/overrides.py:428`), the fold ignores any non-empty list row
  (`_apply_override_row`, `:338`), and promotion refuses a row that points at a book-only entry
  because it cannot stay behind as an override (`_blocked_nested_refs`,
  `backend/app/services/project/promotion.py:163`).

Both are the same gap: no way to name a row inside a list.

## Intent

Let a reference in a list carry members that change over the story, using the mutation machinery
the app already has, one level down. A row is addressed the way its key already identifies it,
nothing new is written to disk, and the row's target reaches the prompt inside the owner's own
lore block.

## Anti-goals

- **Not a `relation` node kind.** No kind whitelist entry, no per-relation entry the lore
  budget can drop, no tab that is a query over a kind. The row lives in the owner's metadata.
- **Not a note string on a reference entry.** A string beside an id cannot be addressed by a
  marker, and it would appear on tags, which use the same reference-list type.
- **Not a row id on disk.** The key is the target. An editor may key rows transiently while a list
  is being edited; that is not storage.
- **Not a stored reverse edge, and not a built-in direction.** `knows` on the character and
  `known_by` on the note are both authorable; the field name carries the direction; the app does
  not sync one to the other. The other direction is the References computed field.
- **Not a new widget.** A row is never displayed as a thing of its own. The display is the
  reference-list tab: the row's target is the NodeRow, the row's members are its detail.
- **Not a second traversal.** The reference index, scrub and the AI hop keep consuming the ADR-0081
  traversal. The index describes time 0, as it does for a flat list gained by mutation today.

## Decision

### 1 — The shape is a group-shaped list with one reference member as its key

A qualified reference is an ordinary `list` field whose `item_group` has exactly one `entity_ref`
member and any scalar members. The author writes it through the public schema surface:

```yaml
groups:
  - id: relationship
    members:
      - { key: to,    name: Who,   type: entity_ref, picker_config: { kinds: [lore] } }
      - { key: kind,  name: Kind,  type: select, options: [kinship, rivalry, debt, witness] }
      - { key: state, name: State, type: text }
types:
  - name: character
    fields:
      - { name: relationships, type: list, item_group: relationship }
```

The reference member is the row's key. A group may declare one `select` member as part of the
key as well, so that two rows toward the same person of different kinds can coexist; the
attribute that declares it is implementation's. Without it, one row per target per field.

**The key never changes.** Changing who a row points at, or a keyed kind, is a different row:
remove and add. Every other member may change. The save compares submitted rows to stored rows
by key and refuses a changed key member; the tab's editor disables key members on a saved row.

### 2 — Rows follow the mutation rules: time 0 on the lore page, markers for everything after

The rows saved on the lore page are the base. Any change from a point in the manuscript on is a
scene marker, with the existing grammar and url-encoding:

| Writer's intent | Marker | `field` token | `value` |
|---|---|---|---|
| A row starts here: "she gains a rival", "he learns the letter is forged" | `op=add` | the list field | the whole row, url-encoded |
| A member changes: "reconciled", "now he suspects it was Mara" | `op=replace` | `relationships.<target>.state` (with `.<kind>` before the member when kind is keyed) | the member's value |
| A row ends here: "the debt is forgotten", "retracted testimony" | `op=remove` | the list field | the row's key |

Interval close (ADR-0010) applies to any of the three records. Whole-list `replace` is rejected
by the validator for a group-shaped list; it is the grammar's default op and would erase every
row from that point, and it has no story use.

The validator gains one check, next to the entity-existence check it mirrors: a `replace` or
`remove` must name a row that exists at that position, in the base or as a live `add`. A
`replace` placed before its row's `add` validates as dangling, as a mutation on a deleted entity
does. A `replace` on a removed row is live but ineffective, shown on the timeline and warned.

### 3 — Resolution is the existing rule, one level down

`_live_records_by_field` groups live records by the marker's field string and takes the
latest-started as the replace winner (`backend/app/services/project/lore_mutations.py:719`).
With the dotted path as that string, each member of each row is its own resolution key, so a
member changing across the book, a closed change reverting to the prior value, and two changes in
one scene all resolve as scalar fields do today. Rows resolve as a collection keyed by the row key
(base rows, plus live adds, minus live removes, remove-wins), so "add, remove, add again" is sound:
a remove ends that key from its position, and a later add of the same key is a new row.

A group-shaped list is a **fourth collection class** for the validator and resolver (this amends
ADR-0009's "only three"): `add` and `remove` carry a row, `replace` addresses a member.

### 4 — The mutation dialog diffs by key, and a stop is edited where it shows

ADR-0017 stands: the writer edits the list, the dialog diffs old to new and writes the records.
For a group-shaped list the diff is by row key, and it writes three record shapes: a new row is an
`add`, a missing row a `remove`, a changed member a `replace` on the member path. The dialog is
the way a stop comes into being.

The dialog passes the cursor position as the baseline position. Today it resolves at end of
scene (PR #74's recorded deviation from ADR-0017); with row keys that deviation can offer a row
created later in the same scene and then emit a `remove` that kills it, so the deviation ends
with this work.

Reviewing and editing a stop that already exists is the scrubber. ADR-0013 makes the card show
effective values at a stop; ADR-0042 §5 rules that editing at a stop edits that stop's unit. The
tab scrubbed to Chapter 12 shows the Chapter 12 rows and is where Tomas's state is changed to
reconciled. §5 is ruled and not yet built (`editorReadOnly` still parks the card above stop 0,
`frontend/src/components/editor/NodeEditor.svelte:880`); this work builds it for lists.

### 5 — One row grammar for markers and overrides

An override row is the same triple as a marker row, so the grammar in §2 is also the override
grammar. A book adds a row to a series-owned character as an `add` override, changes a member as
a `replace` on the member path, drops one as a `remove`. Composition is per row key, descendant
wins. This lifts the #698 v1 refusal in `_scalar_override_row` and lets promotion leave a row that
points at an origin-local entry behind as the origin's override, the way it already leaves a
top-level reference behind, so `_blocked_nested_refs` no longer needs to refuse.

### 6 — Display: the reference-list tab, the row as the target row's detail

A list whose rows point at a node renders as a list of those nodes' rows: the reference-list tab
(`ReferenceListTab.svelte`, a NodeList of NodeRows) with the row's other members as the detail
line NodeRow already supports (`detail`, `frontend/src/components/widgets/NodeRow.svelte:41`) and
the tab does not yet pass (`refRow`, `ReferenceListTab.svelte:332`). The peek and navigation are
the target's. The mutation mark sits on the detail when a member's effective value is not the
base. Rows are keyed and removed by row key, never by target alone.

The tab's write contract becomes rows, not ids: at stop 0 the row's members are edited in place
and saved as base; at a later stop per §4. The rail shows such a field as an index row, as it
shows a reference list today. A group that also carries a `long_text` member shows its first line
in the detail and the rest when the row expands; it does not fall back to repeating sections.

The other direction is the References computed field, which lists the entries pointing at a node.
It gains **which field** the reference sits in, so a view can show "referenced through `knows`"
apart from "referenced through `cast`", with the row's members as the detail. ADR-0081 deferred
member-level granularity "until a consumer needs it"; this is the consumer. Today the graph
payload flattens fields (`reference_graph`, `backend/app/services/project/references.py:1047`;
`ReferenceGraphResponse.refs: dict[str, list[str]]`, `backend/app/models/annotations.py:166`),
the frontend inverts it to `Map<targetId, Set<referrerId>>` (`buildReferenceIndex`,
`frontend/src/lib/views/referenceIndex.ts:59`), and the store's refresh gate is a second
top-level-only walk (`forwardRefsOf`, `referenceIndex.ts:24`) that misses a change inside a row.
All four change together.

### 7 — The prompt: the owner's own rows, one line each

An entry's lore block renders the entry's own rows with their effective members, one line per
row, the reference member as the target's name with its id as an attribute and **no target
summary** (the target's own block carries it when in context). This replaces the JSON dump
`_render_field_element` uses for `list` values today (`backend/app/services/ai/lore_block.py:319`)
for any group-shaped list, and it means a 30-row list costs 30 lines, not 30 node reads. The
overlay of live records happens per row member before render.

**An entry's block carries only its own rows.** What Tomas holds toward Mara is in his block and
reaches the prompt when he is in context. With only Mara in context the AI writes from her side,
which is the point of view it should have. The lore block never runs a reverse query.

### 8 — The structural hop consumes the one traversal, keeping its kind filter

`_collect_lore_refs_from_metadata` (`backend/app/services/ai/helpers.py:727`) reads top-level
strings and flat lists with a `lore_` prefix and never descends into a row, so a reference an
author puts inside a group member today is rendered and scrubbed but never fans into context. It
converges on `iter_ref_occurrences` (`backend/app/services/project/metadata_refs.py:94`) keeping
the `lore_` filter, at all three call sites (`offer_structural_hop`,
`backend/app/services/ai/lore_selection.py:306`, and the two scene-seed sites). This is a
standalone fix, filed on its own, and it is gated exactly as the hop is today: not walked under
`named` expansion, `manual_only` targets subtracted, dropped first under the lore budget
(ADR-0086). The prompt claim this ADR relies on is §7, not the hop.

### 9 — Deleting a target drops the row

Delete-purge writes `""` into a purged reference occurrence (`_purge_metadata_refs`,
`backend/app/services/project/metadata_values.py:911`), which would leave a row with no key. For a
group-shaped list the occurrence on the key member drops the row instead. Markers addressing the
dropped row then validate as dangling per §2. A row gained by a marker is not in the index and is
not scrubbed, as a flat-list member gained by a marker is not today; the validator is where a
deleted target is caught.

## Why / rejected alternatives

- **A `relation` node kind** (#2012's sketch; the steelman: body-less, picker-minted, expected
  in the hundreds, the profile ADR-0082 used to justify `tag`). Everything this ADR builds for rows
  is free for a node: two-part addressing, the picker, close, sets, the timeline, `_new_id`,
  snapshots, promotion. It loses on the two things that matter to the writer and the AI. Each
  stance becomes its own inferred entry, which the budget drops first, instead of a line inside the
  point-of-view character's declared block. And it is two nodes per pair, with a tab that is a
  query over a kind rather than a field. The epic recorded the rejection as "AI-context join +
  lore baggage" (#2005); this ADR gives the reasons in full so the node is not re-derived.
- **A note string on the reference entry.** Unaddressable by a marker; leaks onto tags.
- **A minted row id on disk.** Fails three ways: a server-minted id churns under autosave, which
  keeps the draft and never adopts saved metadata (`editorPanes.svelte.ts`, the "Keep the pane's
  current draft-* fields" branch); a marker-born id is re-minted when the creating unit is
  re-edited, because rows reuse an id only on unchanged `(op, value)`
  (`frontend/src/lib/editor-core/mutationListEdit.ts:72`); and a pre-id snapshot restored later
  re-mints every id on the way out. The target is already the identity the writer means.
- **Qualifier as separate reference-list fields** (`allies`, `rivals`, …), grouped by a view.
  Works today at zero code, and is the baseline this ADR must beat: it has no per-target state and
  explodes when kinds and states multiply.
- **Knowledge as a plain `knows: entity_ref_list` with `add` and close.** Arrival, retraction
  and the mark are shipped; it loses only `how` and `state`. It is the degenerate case of §1 with
  no scalar members, and remains authorable.
- **A relation the hop passes through** (a node kind the traversal treats as transparent). A
  special case in the one traversal for one kind.
- **Mutation-only relations, no base rows** (the reserved `knower=` scope generalised,
  `docs/design/mid-scene-lore-mutations.md` §3.2, never implemented). Puts world facts in prose
  files and loses lore-page authoring. The reserved scope is retired by this ADR; a knowledge row
  covers it.
- **Storing the qualifier on the target** (Tomas carries `regarded_by_mara`). Wrong owner,
  schema explosion.
- **A paired "incoming" line inside the owner's tab, and a built-in "known by".** A backlink drawn
  inside a field's own rendering, nowhere else in the app; both dissolve into the References
  field with field granularity.

## Consequences

- **Amends ADR-0009**: group-shaped lists are a fourth collection class (`add`/`remove` carry a
  row, `replace` a member, whole-list replace rejected). **Amends ADR-0017**: the diff is by row
  key. **Consumes ADR-0081's deferral** of member-level reference granularity.
- **Lifts #698 v1's list-override refusal and ADR-0081 §4's promotion refusal** through one row
  grammar. Existing lists are already in the final shape: **no migration**.
- The reference index, References field and delete-scrub describe **time 0**. Rows gained by
  markers appear on the scrubbed card and in the prompt, not in the index. This is today's rule
  for flat lists gained by markers, stated rather than changed.
- The `knower=` grammar slot reserved in the mutations design is retired.
- Mutation sets carry `(field, op, value)` rows with no entity; a set can `add` a row and cannot
  address one by key, and applying it twice adds the row twice. Stated, not fixed.
- Two bugs exist today independent of this ADR and are filed separately: the hop collector's
  missing descent (§8, #2066) and the reference store's refresh gate (§6, #2067).

## Slices

1. **S0 — the hop descends** (standalone bug, #2066). `_collect_lore_refs_from_metadata` consumes
   the traversal with the `lore_` filter kept; a parity test with a reference inside a group member.
2. **S1 — grammar, validator, resolver.** The dotted path, the fourth collection class, the
   row-exists check, whole-list replace rejected, `effective_state` returning structured rows.
3. **S2 — override rows.** The same grammar in `_scalar_override_row` / `_apply_override_row`;
   `_blocked_nested_refs` retired; promotion leaves a row behind as the origin's override.
4. **S3 — the tab.** Detail line from the row, keyed by row key, members editable at stop 0, the
   write contract as rows; the mutation dialog's list rows diffed by key at the cursor; scrub-drop.
5. **S4 — the prompt.** One line per row in the lore block, per-row overlay before render.
6. **S5 — editing at a stop** for lists (ADR-0042 §5), the tab scrubbed to a stop as its editor.
7. **S6 — References with field granularity.** Edge identity, graph payload, frontend index and
   refresh gate, and the view detail from the row.

S1 and S2 are the data model. S3 through S6 are surfaces on shipped widgets. Nothing starts on
this ADR's "Proposed" status.

## The journey that defines done

1. On Mara's page the writer adds a row in Relationships: Tomas, kinship, "estranged". Nothing
   but those three values is written.
2. Writing Chapter 12, the writer runs `/mutate`, picks Mara → Relationships → Tomas → State,
   types "reconciled". A ⤳ pill lands in the prose at the point of change.
3. Opening Chapter 14, Mara's Relationships tab shows the row "Tomas Vell" with the detail
   "kinship · reconciled ⤳". Scrubbing Mara's card to Chapter 3 shows "estranged" with no mark;
   scrubbing to Chapter 12 and editing the detail edits the Chapter 12 marker.
4. Tomas's Relationships tab shows his own row for Mara, "kinship · wary". Neither is a copy of
   the other; Mara's stance is edited on Mara's page only.
5. A chat at Chapter 14 with Mara in context reads, inside her block, "Tomas Vell: kinship,
   reconciled". The same chat at Chapter 3 reads "estranged". Tomas's own block is there when he
   is in context, and not otherwise.
6. Writing Chapter 9 of the mystery, the writer runs `/mutate` on the inspector → Knows and adds a
   row: "Peter has no alibi", how: deduced. The row appears in the inspector's Knows tab from
   Chapter 9 on, marked ⤳ Ch. 9, and is absent when Chapter 3 is open.
7. On the note "Peter has no alibi", the References field lists the characters whose base rows
   point at it, with each row's kind and state as the detail.
8. Deleting Tomas drops Mara's row for him; the Chapter 12 marker validates as dangling.
9. In a book that inherits Mara from the series, the writer adds a row for a book-only character.
   It is saved as the book's override, folds into Mara's tab in the book, and promoting Mara to
   the series leaves that row behind at the book.
