# ADR-0089: A relationship is a list item keyed by its reference, and it follows the mutation rules

- **Status:** Proposed (2026-09-20). Replaces the shape sketched on #2012 (a `relation` kind).
- **Feature:** relationships and "who knows what when" as metadata (#2012, section B3 of the
  metadata-material epic #2005).
- **Relates to:** ADR-0081 (references at any depth — the item shape and the one traversal),
  ADR-0009 (**amends** — a third live collection class with per-key resolution), ADR-0017
  (**amends** — the diff is by key, at the dialog's position), ADR-0001/0003/0010 (markers,
  cumulative resolution, close), ADR-0013 and ADR-0042 §5 (the scrubber as review and edit
  surface), ADR-0039 (layer overrides), ADR-0086 (the lore budget and `named` expansion),
  ADR-0082 (tags as nodes — the precedent the rejected node shape leaned on).
- **Words used here.** An *item* is one entry of a `list` field (the schema's word: `item_group`,
  `item_members`). A *record* is one `(field, op, value)` triple, whether it lives in a scene
  marker (ADR-0016) or in a layer override. A *NodeRow* is the widget. The word "row" is avoided.
- **Verified against `342be0ce` (2026-09-20).** Symbols first, line numbers second; the numbers
  rot, the symbols do not.

## Problem

A list of people on a character carries a word per person: brother, rival, the only witness. The
word changes as the story does. A mystery writer keeps a second list of the same shape: which
character knows which fact, from which chapter. Reading Chapter 14, the writer and the AI should
both see "Tomas: brother, reconciled", not the base value and not the ending.

The shape already exists. A `list` field with an `item_group` holds items whose members may be a
reference (`LIST_ITEM_GROUP_MEMBER_TYPES`, `backend/app/models/schema.py:31`), ADR-0081 made
those references first-class for indexing, scrubbing and rendering, and its Consequences name
"a relationship group `{target: entity_ref, kind: select}`" as the shape it unlocks. Two things
stop at the field boundary:

- **A mutation cannot name an item.** The marker's target is `(entity, field key)`; the field
  token admits dots but nothing splits them (`MUTATION_MARKER_PATTERN`,
  `backend/app/services/project/lore_mutations.py:72`; `_validate_scene_mutations`, `:364`). A
  `list` field is not a collection type (`COLLECTION_FIELD_TYPES`, `:102`), a replace marker's
  string is rejected by `_validate_list_field_value`
  (`backend/app/services/project/metadata_values.py:352`), and the authoring dialog leaves `list`
  fields out of its roster for exactly that reason (`buildFieldOptions`,
  `frontend/src/components/editor/body/MutationFieldRows.svelte:66`, "per-item mutation ops for
  lists are a follow-up").
- **A layer override cannot hold an item either.** An override record is the same string-valued
  triple (`MutationSetRow`, `backend/app/models/entries.py:947`), so a book editing a list on a
  series-owned entry gets a 422 (`_scalar_override_row`,
  `backend/app/services/project/overrides.py:428`), the fold ignores any non-empty list record
  (`_apply_override_row`, `:338`), and promotion refuses an item that points at a book-only entry
  because it cannot stay behind as an override (`_blocked_nested_refs`,
  `backend/app/services/project/promotion.py:163`).

Both are the same gap: no way to name an item inside a list.

## Intent

Let a reference in a list carry members that change over the story, using the mutation machinery
the app already has, one level down. An item is addressed by the reference it already holds, no
new storage shape is introduced, and the item's target reaches the prompt inside the owner's own
lore block.

## Anti-goals

- **Not a `relation` node kind.** No kind whitelist entry, no per-relation entry the lore
  budget can drop, no tab that is a query over a kind. The item lives in the owner's metadata.
- **Not a note string on a reference entry.** A string beside an id cannot be addressed by a
  marker, and it would appear on tags, which use the same reference-list type.
- **Not an item id on disk, and not a per-member `mutable` flag.** The key is the reference
  the item already holds (the mutations design dropped the flag: every field is mutable,
  `docs/design/mid-scene-lore-mutations.md` §3.1).
- **Not a stored reverse edge, and not a built-in direction.** `knows` on the character and
  `known_by` on the note are both authorable; the field name carries the direction; the app does
  not sync one to the other. The other direction is the References computed field.
- **Not a new widget.** An item is never shown as a thing of its own. The display is the
  reference-list tab: the item's target is the NodeRow, the item's members are its detail line.
- **Not a change to flat collections.** ADR-0009's remove-wins stays the rule for
  `multi_select` and `entity_ref_list`; the per-key rule in §3 applies to this class only.
- **Not a second traversal.** The reference index, scrub and the AI hop keep consuming the
  ADR-0081 traversal. The index describes time 0, as it does for a flat list gained by marker.

## Decision

### 1 — The shape: a group-shaped list whose one reference member is the key

A relationship list is an ordinary `list` field whose `item_group` has exactly one `entity_ref`
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

**The reference member is the item's key: one item per target per field.** A key has to be an id,
because it is written into scene bodies and override files: a `select` option value is a free
string (`SelectOption`, `backend/app/models/base.py:8`) that may carry spaces or dots, option
renames rewrite entry front matter only (`_apply_option_value_changes`,
`backend/app/services/project/schema.py:1005`) and never a scene body, and neither reaches group
members. So a second relation kind toward the same person is a second field, or lives in the
state text. Two lists that already hold the same target twice are tolerated on read and shown with
a warning; uniqueness is enforced on write (the save and the marker validator), which is why no
migration is owed.

**The key never changes.** A marker or an override that re-keyed an item mid-book would orphan
every record and every close placed on the old key. Pointing an item at someone else is a
different item: remove and add. Every other member may change. The save compares submitted items
to stored items by key and refuses a changed key member; the tab's editor disables the key
member on a saved item. A key is resolved through the node index's `canonical_id`, so a tag or
entry merged into another (ADR-0082 §5) keeps its records; the merge sweep dedupes two items
that collapse onto one key, first wins.

### 2 — Items follow the mutation rules: time 0 on the lore page, records for everything after

The items saved on the lore page are the base. Any change from a point in the manuscript on is a
scene marker in the existing grammar, url-encoded as every marker value is:

| Writer's intent | Op | `field` token | `value` |
|---|---|---|---|
| An item starts here: "she gains a rival", "he learns the letter is forged" | `add` | the list field | the whole item, url-encoded |
| A member changes: "reconciled", "now he suspects it was Mara" | `replace` | `relationships.<target id>.<member key>` | the member's value |
| An item ends here: "the debt is forgotten", "retracted testimony" | `remove` | the list field | the target id |

Node ids are `<kind>_<hex>` (`ProjectService._new_id`, `backend/app/services/project_service.py:652`)
and member keys are identifiers, so the dotted path fits the field token's class
`[A-Za-z0-9_.-]` unchanged. A mutation value is a field value (ADR-0007): the item an `add`
carries is decoded and validated against the list's `item_members` as a base item is; a
`replace` value is validated as the member's type. Interval close (ADR-0010) applies to any of
the three records.

**Whole-list `replace` is rejected** by the validator for this class. It is the grammar's default
op (the `op=` group is optional, `lore_mutations.py:74`), so a record without an op would
silently erase every item from that point; a structured multi-item value would need an encoding
of its own; and a reset that a story needs ("everyone she knew is gone") is a set of removes.
ADR-0009 keeps `replace` for flat collections.

**One validator check**, next to the entity-existence check it mirrors: a `replace` or `remove`
must name an item that exists at that position, in the base or as a live `add`. A `replace`
placed before its item's `add` validates as dangling, as a mutation on a deleted entity does. A
`replace` on a removed item is live but ineffective, shown on the timeline and warned.

### 3 — Resolution: per key, positional; a third live collection class

`_live_records_by_field` groups live records by the marker's field string and takes the
latest-started as the replace winner (`backend/app/services/project/lore_mutations.py:719`).
With the dotted path as that string, each member of each item is its own resolution key, so a
member changing across the book, a closed change reverting to the prior value, and two changes in
one scene resolve as scalar fields do today.

Presence of an item is **positional per key**, and this is the amendment to ADR-0009: for each
key, the latest-started live `add` or `remove` decides whether the item exists at the position.
Flat collections resolve as sets (`_resolve_collection`, `:766`: base plus live adds minus live
removes, remove-wins, order-blind), which is the only rule available when a value has no
identity; a keyed item has one, so "add, remove, add again" is a fresh item from the second add,
without closing the remove. An `add` of a key resets that key's member records: `replace` records
started before the add do not apply to the new item, the way a whole `replace` resets earlier adds
today (`_last_replace_index`, `:146`). A `replace` on a key with no live item is ineffective (§2).

Group-shaped lists are the **third live collection class** beside `multi_select` and
`entity_ref_list` (ADR-0009's `tags` was retired by ADR-0082): `add` and `remove` carry an item,
`replace` addresses a member.

**The contract of `effective_state` widens.** The response maps the list field id to its folded
items, a list of member maps; member paths never leave the resolver. `EffectiveStateResponse.values`
(`backend/app/models/annotations.py:111`) and its frontend twin widen from
`str | list[str]`, and the four consumers read the new shape: the lore block's overlay
(`_effective_overlay_updates`, `backend/app/services/ai/helpers.py:252`; `_render_node_field_lines`,
`backend/app/services/ai/lore_block.py:257`), the scrubbed card (`loreScrub`,
`frontend/src/lib/stores/loreScrub.svelte.ts`), the mutation dialog's baseline
(`MutationAuthoringForm.svelte:97`), and the ADR-0055 as-of path through the same overlay.

### 4 — The mutation dialog diffs by key at its own position; a stop is edited where it shows

ADR-0017 stands: the writer edits the list as it stands, the dialog diffs old to new and writes
the records. For this class the diff is by key and writes three record shapes: a new item is an
`add`, a missing item a `remove`, a changed member a `replace` on the member path. A re-edited
unit reuses an `add` or `remove` record's id by `(op, key)`, never by `(op, value)` as
`collectionRowsFromEdit` does for flat values (`frontend/src/lib/editor-core/mutationListEdit.ts:72`),
so fixing a typo in an item keeps the record a later close points at. The dialog is the way a
stop comes into being.

**The dialog's baseline is its own insertion position.** Today it resolves at end of scene
(`MutationAuthoringForm.svelte:94`, the deviation PR #74 recorded against ADR-0017 on three
grounds: no editor-cursor-to-markdown-offset mapping, parity with the close picker, and
ADR-0003's bound on threading positions). For keyed items that baseline can offer an item whose
`add` sits later in the same scene and then write a `remove` that kills it, so this class needs
the position. The dialog already knows where it inserts the pill, which is the one place ADR-0003
allows a real offset (the inline handler's `selection` destination); it passes that offset as the
baseline position. This reverses the deviation for the dialog only. The lore card never acquires
a cursor (ADR-0042, "do not read this as an invitation to add intermediate positions").

Reviewing and editing a stop that already exists is the scrubber. ADR-0013 makes the card show
effective values at a stop; ADR-0042 §5 rules that editing at a stop edits that stop's unit. The
tab scrubbed to Chapter 12 shows the Chapter 12 items and is where Tomas's state is changed to
reconciled. §5 is ruled and not yet built (`editorReadOnly` still parks the card above stop 0,
`frontend/src/components/editor/NodeEditor.svelte:880`); this work builds it for lists.

### 5 — One record grammar for markers and overrides

An override record is the same triple as a marker record, so §2's grammar is also the override
grammar. A book adds an item to a series-owned character as an `add` record, changes a member as
a `replace` on the member path, drops one as a `remove`; the book-level save diffs the submitted
list against the folded base by key (`_diff_metadata_to_override_rows`,
`backend/app/services/project/lore.py:348`) and the fold applies records per key, descendant
wins. This lifts the #698 v1 refusal in `_scalar_override_row` and lets promotion leave an item
that points at an origin-local entry behind as the origin's override records, the way it already
leaves a top-level reference behind, so `_blocked_nested_refs` no longer refuses. When promotion
finds the same key at both layers, the origin's differing members stay behind as `replace`
records.

### 6 — Display: the reference-list tab, the item as the target row's detail

A list whose items point at nodes renders as a list of those nodes' rows: the reference-list tab
(`frontend/src/components/editor/body/ReferenceListTab.svelte`, a `ViewNodeList` over NodeRows)
with the item's other members as the detail line NodeRow already supports (`detail`,
`frontend/src/components/widgets/NodeRow.svelte:41`) and the tab does not yet pass (`refRow`,
`ReferenceListTab.svelte:332`). The peek and navigation are the target's. The mutation mark sits
on the detail when a member's effective value is not the base. Items are keyed, and removed, by
target.

**The widget is picked by the key, and that rule takes precedence over the prose gate.** Today
any list with a `long_text` member is a body section (`listHasProseItems`,
`frontend/src/lib/editor-core/bodySections.ts:66`, #2043) and the tab gates admit
`entity_ref_list` only (`listTabFieldIds`, `frontend/src/lib/editor-core/bodyTabs.ts:24`;
`isListIndex`, `frontend/src/lib/rail/fieldRowModel.ts:343`). A list with a reference key member
is a reference-list tab whether or not it carries prose members; the two gates widen to this
shape, and the rail shows the field as an index row as it shows a reference list. A `long_text`
member shows its first line in the detail and its full text in the item's editor.

**The tab's write contract becomes items, not ids.** At stop 0 the item's members are edited in
place in the tab and saved as base; at a later stop per §4.

**The other direction is the References computed field.** The edge already carries the field
(`ReferenceEdge`, `backend/app/services/project/node_index.py:124`, "the field is part of the
edge identity"), and with one item per target per field the edge `(source, field, target)` is
the item, so no new edge identity is needed. What changes is downstream of the edge: the graph
payload flattens fields away (`reference_graph`, `backend/app/services/project/references.py:1047`;
`ReferenceGraphResponse.refs: dict[str, list[str]]`, `backend/app/models/annotations.py:166`), the
frontend inverts it to `Map<targetId, Set<referrerId>>` (`buildReferenceIndex`,
`frontend/src/lib/views/referenceIndex.ts:59`), and the store's refresh gate is a second
top-level-only walk (`forwardRefsOf`, `referenceIndex.ts:24`, #2067). The payload carries the
field, the index keeps it, and a view over References can show "referenced through `knows`"
with the referrer's item members as the detail.

### 7 — The prompt: the owner's own items, one line each

For a list with a reference key member, an entry's lore block renders the entry's own items with
their effective members, one line per item, the reference member as the target's name with its
id as an attribute and **no target summary** (the target's own block carries it when in context).
Other group-shaped lists keep the JSON render `_render_field_element` uses today
(`backend/app/services/ai/lore_block.py:319`); plot beats carry prose members and must not be
flattened. The overlay of live records happens per item member before render.

**An entry's block carries only its own items.** What Tomas holds toward Mara is in his block and
reaches the prompt when he is in context. With only Mara in context the AI writes from her side,
which is the point of view it should have. The lore block never runs a reverse query.

### 8 — The structural hop consumes the one traversal, keeping its kind filter

`_collect_lore_refs_from_metadata` (`backend/app/services/ai/helpers.py:727`) reads top-level
strings and flat lists with a `lore_` prefix and never descends into an item, so a reference an
author puts inside a group member today is rendered and scrubbed but never fans into context
(#2066). It converges on `iter_ref_occurrences`
(`backend/app/services/project/metadata_refs.py:94`) keeping the `lore_` filter, at all three call
sites (`offer_structural_hop`, `backend/app/services/ai/lore_selection.py:306`, and the two
scene-seed sites at `:89` and `:157`). This is a standalone fix, and it is gated as the hop is
today: not walked under `named` expansion, `manual_only` targets subtracted, dropped first under
the lore budget (ADR-0086). The prompt claim this ADR relies on is §7, not the hop.

### 9 — A purged key makes a dangling item; no read path removes an item

Delete-purge and the read-side heal share one value-level visitor (`rewrite_ref_occurrences`,
`backend/app/services/project/metadata_refs.py:120`): purge writes `""` into a purged reference
(`_purge_metadata_refs`, `backend/app/services/project/metadata_values.py:911`), and the heal
blanks any reference that no longer matches the picker and writes the cleaned metadata back on
the next save (`_strip_dangling_references`, `:771`). Dropping the item there would turn a
narrowed `picker_config` into a silent loss of every item's other members. So both keep writing
`""` (ADR-0081 acceptance 4: only the matched reference value changes). An item with a blank key
is a **dangling item**: kept on disk, hidden from the prompt and the index, shown as dangling in
the tab, flagged by validation; records addressing it validate as dangling per §2.

An item gained by a marker is not in the index and is not scrubbed, because the index reads
stored metadata only (`_reference_edges_for_entry`, `backend/app/services/project/references.py:897`),
exactly as a flat-list member gained by a marker is not today; the marker validator is where a
deleted target is caught.

## Why / rejected alternatives

- **A `relation` node kind** (#2012's sketch; the strongest case: body-less, picker-minted,
  expected in the hundreds, the profile ADR-0082 used to justify `tag`). Everything this ADR
  builds for items is free for a node: two-part addressing, the picker, close, sets, the timeline,
  `_new_id`, snapshots, promotion. It loses on the two things that matter to the writer and the
  AI. Each relation becomes its own inferred entry, which the budget drops first, instead of a
  line inside the point-of-view character's declared block. And it is two nodes per pair, with a
  tab that is a query over a kind rather than a field. The brainstorm on #2012 recorded the first
  rejection as two reasons, "AI context" (nothing in prose names "Mara → Tomas", so a relation
  node needs a new join rule) and "lore baggage"; this ADR gives the full case so the node is not
  re-derived.
- **A note string on the reference entry.** Unaddressable by a marker; leaks onto tags.
- **A minted item id on disk.** Fails three ways: a server-minted id re-dirties the pane on every
  autosave, because the dirty check compares the draft, which has no ids, to the saved document,
  which does (`isEditorPaneDirty` in the save branch of `frontend/src/lib/stores/editorPanes.svelte.ts`);
  a marker-born id is re-minted when the creating unit is re-edited, because records reuse an id
  only on unchanged `(op, value)` (`mutationListEdit.ts:72`); a pre-id snapshot restored later
  re-mints every id on the way out. The reference is already the identity the writer means.
- **A keyed `select` beside the reference** (two items toward the same person, different
  kinds). Its option value would be written into scene bodies as part of the key, and option
  values are free strings that renames never chase into markers (§1). Rejected for this ADR; a
  second kind is a second field.
- **One reference-list field per kind** (`allies`, `rivals`, …), grouped by a view. Works today
  at zero code and is the baseline this ADR must beat: no per-target state, and it multiplies
  fields as kinds and states multiply.
- **Knowledge as a plain `knows: entity_ref_list` with `add` and close.** Arrival, retraction
  and the mark are shipped; it loses only `how` and `state`. It is the degenerate case of §1 with
  no scalar members, and remains authorable.
- **A relation the hop passes through** (a node kind the traversal treats as transparent). A
  special case in the one traversal for one kind.
- **Mutation-only relations, no base items** (the reserved `knower=` scope generalised,
  `docs/design/mid-scene-lore-mutations.md` §3.2 and ADR-0001's forward-compatibility list,
  never implemented). Puts world facts in prose files and loses lore-page authoring. The reserved
  scope is retired by this ADR; a knowledge item covers it.
- **Storing the item on the target** (Tomas carries `regarded_by_mara`). Wrong owner, schema
  explosion.
- **A paired "incoming" line inside the owner's tab, and a built-in "known by".** A backlink drawn
  inside a field's own rendering, nowhere else in the app; both dissolve into the References
  field.

## Consequences

- **Amends ADR-0009**: group-shaped lists are a third live collection class with per-key,
  positional presence (`add`/`remove` carry an item, `replace` a member, whole-list replace
  rejected); flat collections keep remove-wins. **Amends ADR-0017**: the diff is by key, and the
  dialog resolves its baseline at its insertion position. **Amends #2043's gate**: a reference key
  member outranks a prose member when picking the widget. **Consumes ADR-0081's deferral** of
  member-level granularity at the payload, not the edge.
- **Lifts #698 v1's list-override refusal and ADR-0081 §4's promotion refusal** through one
  record grammar. Existing lists are already in the final shape: **no migration**; duplicate keys
  are tolerated on read.
- **`effective_state` changes contract** (§3): a list field maps to folded items; four consumers
  named.
- The reference index, References field and delete-scrub describe **time 0**. Items gained by
  markers appear on the scrubbed card and in the prompt, not in the index. This is today's rule
  for flat lists gained by markers, stated rather than changed.
- The `knower=` grammar slot reserved in the mutations design is retired.
- Mutation sets gain the grammar for free: a set record `(relationships.<target>.state, replace,
  reconciled)` addresses an item by key when the set is applied to an entity, which is how an
  ADR-0055 brainstorm would stage a relationship change; an `add` of a key that already exists is
  a no-op on apply.
- Two bugs exist today independent of this ADR: #2066 (§8) and #2067 (§6).

## Slices

1. **S0 — the hop descends** (#2066). `_collect_lore_refs_from_metadata` consumes the traversal
   with the `lore_` filter kept; a parity test with a reference inside a group member.
2. **S1 — grammar, validator, resolver, contract.** The dotted path, the third class with per-key
   presence, the item-exists and key-unchanged checks, uniqueness on write, whole-list replace
   rejected, `canonical_id` on keys, and `effective_state` returning folded items with its four
   consumers updated.
3. **S2 — override records.** The same grammar in `_scalar_override_row` / `_apply_override_row`
   and the by-key diff in `_diff_metadata_to_override_rows`; `_blocked_nested_refs` retired;
   promotion leaves an item behind as the origin's records.
4. **S3 — the tab.** Detail line from the item, keyed by target, members editable at stop 0, the
   write contract as items, the widened gates; the mutation dialog's item rows diffed by key at
   the insertion position with record ids reused by `(op, key)`; dangling items shown as such.
5. **S4 — the prompt.** One line per item for reference-keyed lists, per-item overlay before
   render.
6. **S5 — editing at a stop** for lists (ADR-0042 §5), the tab scrubbed to a stop as its editor.
7. **S6 — References with the field in the payload.** Graph payload, frontend index and refresh
   gate (#2067), and the view detail from the referrer's item.

S1 and S2 are the data model. S3 through S6 are surfaces on shipped widgets. Nothing starts on
this ADR's "Proposed" status.

## The journey that defines done

1. The writer adds the `relationship` group and a `relationships` field to the character type in
   the schema editor, exactly as in §1. No other declaration is needed.
2. On Mara's page the writer adds an item: Tomas, kinship, "estranged". Nothing but those three
   values is written. Trying to add a second item for Tomas is refused; changing the saved item's
   target to Ilse is refused.
3. Writing Chapter 12, the writer runs `/mutate` on Mara, sees Relationships as the list it is at
   that point, and changes Tomas's state to "reconciled". The dialog writes one `replace` record;
   a ⤳ pill lands in the prose at the point of change.
4. Opening Chapter 14, Mara's Relationships tab shows the row "Tomas Vell" with the detail
   "kinship · reconciled ⤳". Scrubbing Mara's card to Chapter 3 shows "estranged" with no mark;
   scrubbing to Chapter 12 and editing the detail edits the Chapter 12 record.
5. In Chapter 19 the writer closes the Chapter 12 record ("reconciled" held until the Weir);
   from Chapter 19 on the detail reads "estranged" again.
6. In Chapter 5 the writer removes Ilse ("the debt is forgotten"); in Chapter 9 adds Ilse again
   ("rival once more"). Chapter 7 shows no Ilse; Chapter 14 shows the Chapter 9 item, with none
   of the pre-Chapter 5 member changes.
7. Later in Chapter 9, after that add, the writer runs `/mutate` at an earlier position in the
   same scene. The list offered does not yet contain Ilse, and nothing the writer does there can
   remove her.
8. Tomas's Relationships tab shows his own item for Mara, "kinship · wary". Neither is a copy of
   the other; Mara's item is edited on Mara's page only.
9. A chat at Chapter 14 with Mara in context reads, inside her block, "Tomas Vell: kinship,
   reconciled". At Chapter 3 it reads "estranged". Tomas's own block is there when he is in
   context, and not otherwise.
10. Writing Chapter 9 of the mystery, the writer runs `/mutate` on the inspector → Knows and adds
    an item: "Peter has no alibi", how: deduced. The item shows from Chapter 9 on, marked ⤳ Ch. 9,
    and is absent when Chapter 3 is open.
11. On the note "Peter has no alibi", the References field lists the characters whose base items
    point at it, with each item's kind and state as the detail.
12. Deleting Tomas leaves Mara's item with a blank target, shown as dangling in the tab and absent
    from the prompt; the Chapter 12 record validates as dangling.
13. In a book that inherits Mara from the series, the writer adds an item for a book-only
    character and changes Tomas's state. Both save as the book's override records, fold into
    Mara's tab in the book, and promoting Mara to the series leaves the book-only item behind at
    the book.
