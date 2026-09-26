# ADR-0095: A mutation is a node, and the scene holds its anchor

- **Status:** Accepted — 2026-09-25, Anton Lauridsen (PR #2230). Text by Claude from a design
  conversation with Anton on 2026-09-25 (#2229), which started from an audit of the whole mutation
  feature. Revised against two cold implementing threads (backend with migration; frontend with
  editing at a stop) before review. Anton gave the go for the slices at acceptance, one lane, in
  order.
- **Feature:** what a mid-scene change says moves out of the scene's prose into a mutation set
  node. The prose keeps a one-line anchor at the point where the change happens. Placing a set,
  editing a change at a scrubbed stop, renaming a field, deleting an entry and linking one change
  into several scenes all become edits to ordinary node files.
- **Supersedes:** ADR-0001 (the storage model: Model A → the Model B it rejected, reconsidered in
  §Why). **Amends:**
  - ADR-0010 and ADR-0016: the close and carrier grammars (§1).
  - ADR-0011: a template stays a stamp; an entity's set is placed by reference (§2, §6).
  - ADR-0013 and ADR-0088: a stop at or after the first is no longer read-only as a whole (§8).
  - ADR-0042 §5: the rule stands; its mechanism becomes a set save (§8).
  - ADR-0055 §3: deleting the subject deletes its sets instead of purging the pin (§9).
  - ADR-0055 §5: placement is derived, not a flag (§2).
  - ADR-0078 §7: a placed set can now be unplaced (§10).
  - ADR-0089 Amendment 2: its "not scrub-time editing" anti-goal is decided here (§8).

  **Relates to:**
  - ADR-0002, ADR-0003, ADR-0009 and ADR-0089 §3: resolution, unchanged (§5).
  - ADR-0039 and ADR-0089 §5: overrides share the row shape.
  - ADR-0043: restore (§11).
  - ADR-0071 and ADR-0082 §6: the migration ladder (§12).

  Closes #2229, #2222 and #66.
- **Words used here.**
  - A *mutation* is one field change: a row `(field, op, value)`.
  - A *mutation set* is a node holding rows, usually for one entity.
  - A *mutation anchor* is the one-line comment in a scene that says "this set takes effect here";
    the editor shows it as the ⤳ pill.
  - A *close anchor* ends an anchor's changes.
  - A *template* is a set with no entity. A *staged* set has an entity and no anchor. An *active*
    set has one anchor or more. A *linked* set has more than one.
  - The *mutations index* is the derived per-entity index built by `build_mutations_index`.
- **Verified against `f67bb70f` (2026-09-25).** Symbols first, line numbers second.

## Problem

ADR-0001 stores each change as a self-contained comment in the scene body: entity, field, value
and id, all inline (`MUTATION_CARRIER_PATTERN`, `backend/app/services/project/lore_mutations.py:97`).
Mutation sets arrived later as separate nodes (ADR-0011). A set is applied by copying its rows into
a new inline marker (`applySet`, `MutationAuthoringForm.svelte:276`). An audit of the feature on
2026-09-25 traced its open problems to that split.

- **A placed set cannot say where it is placed.**
  - Placing a pinned set copies its rows into the prose and writes `placed: true` on the set
    (`place_mutation_set_entry`, `mutation_sets.py:129`). The marker keeps no link back to the set.
  - Nothing clears the flag. Deleting the pill leaves the set "placed", hidden from the picker,
    forever.
  - Promotion refuses a placed set with "unplace it before promoting"
    (`_partition_mutation_set_promotion`, `promotion.py:769`, message at `:794`), and no unplace
    exists.
- **A change can stop working without anyone noticing.**
  - Renaming or deleting a field rewrites the `metadata` key of scene and lore files only
    (`_rename_entry_metadata_key`, `schema.py:1001`, over `_entry_markdown_paths`,
    `project_service.py:241`). A marker's `field=` and a set's `rows[].field` are left naming a
    field that no longer exists.
  - Deleting an entry purges references in front matter (`_purge_references_to`,
    `metadata_values.py:1056`) but not the markers that change it.
  - Each case turns into a warning in Verify, and the change silently stops applying.
- **Editing at a stop edits the scene file.**
  - ADR-0042 §5 says a stop is a unit and editing at a stop edits that unit. Built for relationship
    lists (#2074), that edit rewrites the scene's markdown (`rewrite_mutation_unit`,
    `lore_mutations.py:949`). The request carries no base revision.
  - The frontend flushes the scene, writes, then replaces the open draft with the server's copy
    (`rewriteUnitFromItems`, `mutationStopEdit.ts:56`). Anything typed in the scene while that runs
    is at risk.
  - Extending it to every field type (#2222) extends that risk.
- **Two lifecycles share one kind.** A template is a stamp; a pinned set is staged, then "placed"
  by a flag. They sit in one pane under three names ("Mutations", "Reusable mutations", "mutation
  sets") and behave differently in ways the pane does not show.
- **One change in several places is out of reach.** The werewolf's "Full moon" has to be stamped
  anew each time, and a correction has to be made in every copy (#66). ADR-0001 kept this out
  because it needs a pointer, and pointers were the model it rejected.

The app has also changed since ADR-0001:
- Almost everything is a node.
- References are purged when their target is deleted, and cascade where a node cannot outlive its
  subject. A chat is deleted with its `subject` (`_chats_with_subject_in`,
  `metadata_values.py:1040`).
- Todos already use an anchor in the prose pointing at data kept elsewhere (`TODO_ANCHOR_PATTERN`,
  `scene_todos.py:19`).
- A mutation set is already a node with rows, an entity pin and a staged state.

## Intent

**The set says what changes; the prose says where.** Each fact has one home.

- A change is a node that can be listed, validated, referenced, renamed with its field and deleted
  with its entry.
- The scene keeps only the position, which only the prose can hold.
- Editing a change never writes the scene.
- One set can be anchored in several places, and then it is one change in several places.

## Anti-goals

- **No position stored outside the prose.** A set never records a scene or an offset. Position is
  the anchor's place in the text (ADR-0001, ADR-0003), and moving prose moves it.
- **No copy of the set's values in the anchor**, not even as a comment for human readers. A copy
  goes stale, and that is the second source of truth ADR-0001 warned about.
- **No new kind.** The set is the existing `mutation_set` kind.
- **No change to what a scene resolves to.** Combine rules, intervals, positions, the book
  boundary, keyed items, `effective_state`'s answers and every AI path stay as they are (§5). The
  migration preserves them exactly (§12).
- **No link the writer did not choose.** A set is linked only through the Link choice (§6).
  - Copying prose copies the set, and applying a template copies the template.
  - No path, including paste, migration and restore, leaves two anchors on one set without that
    choice (§3, §7, §11, §12).
- **No anchor across layers.** An anchor names a set in its own project (§10).
- **Prose editing never deletes a node.** Deleting a pill, a paragraph or a scene removes anchors;
  a set is deleted only where nodes are deleted (§7).
- **Not undo for set edits.** Metadata edits have no undo today (`UndoCaretaker` is used only by the
  view designer and the plot board); this ADR does not add it. See Consequences.
- **Not #73.** Closing one appended fragment can still change what a later fragment means.
- **No new view, search or filter over mutations.** Sets become ordinary nodes; nothing new is built
  on that here.

## Decision

### 1 — The anchor and the close anchor

A scene holds one line per anchor, where the change takes effect:

```
<!-- mutate:set=<set-id>;id=<anchor-id> -->
```

and one line where a change ends:

```
<!-- mutate:close;ref=<anchor-id>[;row=<row-id>];id=<close-id> -->
```

- **Closes.** A close without `row=` ends every row of that anchor's set. With `row=`, it ends that
  one row, as a close on a row id does today (`_resolve_closes`, `lore_mutations.py:508`).
- **A row close names its anchor too**, because a linked set's row takes effect at several anchors
  and each has its own interval.
- **Where anchors live.** Anchors live only in manuscript scene bodies, the one place `/mutate` is
  offered today. An anchor pasted into any other prose body (lore, research, prompts) is dropped
  on paste.
- **Retired grammar.** The single-line marker and the multi-row carrier retire.
- **The pill.** It is one TipTap atom per anchor, as it is one per unit today. Its label is the
  set's title, or, for an untitled set, a label made from its rows the way an unnamed unit is
  labelled today. The label follows the set: editing the set relabels every pill that anchors it,
  without touching the document.

### 2 — One kind, three states, read from the anchors

A mutation set is the `mutation_set` node it is today (`default_entry_types.py:191`), with its
entity pin in `metadata.target_entity` (ADR-0055 §3). Its title is optional. Its state comes from
its pin and its anchors, not from a stored flag:

| State | Entity pin | Anchors |
|---|---|---|
| Template | none | none |
| Staged | set | none |
| Active | set | one or more |

- **Templates.** A template is never anchored; it is copied (§6).
- **A pin that names an entry that does not exist** keeps the set out of the template list. The set
  contributes nothing and Verify reports it. A missing pin is a template; a dead pin is not.
- **The mutations index counts a set's anchors** over every scene file in the project, whether or
  not the scene is in the manuscript tree. The tree order is used only for resolution. A set
  anchored in a scene that is out of the tree is still active, so it cannot be promoted or
  deleted as staged and break that scene when it is put back.
- **The set carries its anchors and state as computed metadata**, so the pane, the card and
  promotion read the same answer.
- **Retired:** `placed` is removed from the file, from `MutationSetEntry` and from its summary;
  `place_mutation_set_entry` and its route go.
- **Cost.** Listing sets now needs the anchor scan, so the per-scene scan is cached by the scene's
  revision rather than re-read on every call.

### 3 — Identity

- **Row ids.** A row has an `id`, unique within its set and stable for the row's life. A copied set
  keeps its rows' ids; the anchor id tells the copies apart. Override rows carry no id: a lore save
  regenerates them (`overrides.py`, the diff to override rows), and nothing addresses one.
- **A resolved record is one row at one anchor**, identified by `(anchor id, row id)`. Everything
  that keys on a record keys on the pair: closes, `exclude`, the change-candidate dedupe, and the
  scrubber's stops. Today these key on the row id alone. `exclude=` carries record ids today
  (`effective_state`, `lore_mutations.py:625`); it now carries anchor ids.
- **An id that points at an old unit or row still resolves.**
  - A unit id is an anchor id (§12).
  - A row id finds the anchor whose set holds that row. When a review item or a todo reveals a row
    of a linked set, the reveal uses the anchor in the open scene, else the first in manuscript
    order.
- **An anchor whose set resolves only in another layer is missing** (§10).
- **Anchor ids are unique in the project.**
  - The editor keeps them unique on paste (§7) and restore keeps them unique (§11).
  - A duplicate can still arrive another way: a scene file copied outside the app, a hand edit,
    or a sync conflict.
  - Then the first anchor in manuscript order resolves. Each later one contributes nothing and
    shows as a duplicate pill, because records keyed by the pair would otherwise collide.
  - Verify reports it. Deleting the pill, or copying its set from the pill, fixes it.

### 4 — Validation

Saving a set checks its rows against the pinned entity's type, or a template's
`target_entry_type`. Rows that fail are refused. The checks are:
- the field exists for the type and is one a mutation can target;
- the op suits the field's type;
- the value is valid for the field;
- the row ids are unique.

These are the position-free checks the marker validator already makes
(`lore_mutation_validation.py`). Today set rows are not validated at all, and `op` is any string
(`MutationSetRow`, `models/entries.py:981`).

The checks that need a position stay in Verify, where they run per anchor. One example: a keyed
item's `replace` needs the item to exist at that point (`_item_keys_before`). A set has no
position, or has several.

Migration and restore write sets without these checks (§11, §12). A set that already fails
validation keeps its rows, and Verify reports them. The writer can save it again once the rows are
fixed or removed.

### 5 — Resolution reads anchors and joins the sets

`build_mutations_index` walks the scenes in manuscript order as it does now, collecting anchors
and closes with their positions. For each anchor it reads the set from the open project. Each row
at each anchor becomes one record, exactly as a carrier row is one record today.

From there nothing changes:
- the fold and `effective_state`;
- `live_mutations`;
- the scrubber's stops;
- `effective_names`;
- the snapshot witness;
- `entry()` and `original()` in templates;
- the lore block sent to the AI.

An anchor that repeats an earlier anchor's id contributes nothing and shows as a duplicate (§3).

An anchor also contributes nothing, shows as a missing pill and is reported by Verify when its set:
- is missing;
- is in another layer;
- has no pin;
- has a dead pin.

### 6 — Authoring in the prose

- **`/mutate` creates the set when the dialog is confirmed.** It creates a set pinned to the chosen
  entity, with the dialog's rows and an optional name as its title, then inserts the anchor at the
  cursor. If the insert is undone, or the scene is discarded, the set stays and is staged.
- **Editing through the pill saves the set.**
  - The scene is not written.
  - The dialog's baseline is the state at the pill without this anchor.
  - The pill dialog cannot change a set's entity. A change to someone else is a new pill.
- **Applying a saved set** first saves any open scene with unsaved changes, so every set's state is
  current. It then offers what fits the chosen entity:
  - a **template** for its type. Its rows are copied into a new set pinned to the entity, and that
    set is anchored. The template is untouched, as today;
  - the entity's **staged** sets. That set is anchored and becomes active;
  - the entity's **active** sets, with two choices. **Link** anchors the same set again, so it is
    linked. **Copy** anchors a copy.
- **A set from an ancestor layer is copied into the open project** before it is anchored (§10). The
  ancestor's set, and anything that references it, is unchanged.
- **A linked set says so wherever it is edited.** The pill shows how many places it has, and the
  pill dialog and the stop editor name them.
- **"Save as a reusable set"** in the dialog copies the rows into a new template, as today.

A conversation still stages a set and never places it (ADR-0055 §7). When the chat refines a set
that is already active, the refinement applies wherever the set is anchored; the writer still chose
every position.

### 7 — Copy, cut, and deleting prose

- **Copied prose gets copied sets.**
  - An anchor pasted from a copy gets a new anchor id and a new set holding a copy of the original
    set's rows.
  - Until that set is saved, the pasted anchor names no set. If it cannot be saved, the anchor
    stays missing. A copied anchor never names the original set, not even while the copy is in
    flight, because an autosave in that moment would write a link.
  - Rows that no longer validate (§4) are left out of the copy, and the writer is told which.
  - A close pasted with its anchor is pointed at the new anchor, as today's paste de-duplication
    does (`dedupeMutationIds`, `mutationNodes.ts:98`).
- **Cut prose keeps its anchors.**
  - The app records a cut when it happens. The first paste of that cut keeps its anchors, even when
    the scene it was cut from has not saved yet. Later pastes of the same cut are copies.
  - Dragging prose within the editor is a cut.
  - Content pasted from outside the app is a copy when its anchor id already exists in the project.
- **Deleting a pill, a paragraph or a scene removes anchors only.**
  - A set whose last anchor is gone is staged. It shows under Mutation sets on its entity's card,
    where it can be deleted, and it is offered in `/mutate`'s apply picker to be placed again.
  - The card does not place: it has no prose position (ADR-0042 §5).
  - Restoring a deleted scene brings its anchors back, and the sets are active again.
- **The pill dialog's Delete removes the anchor.** A set is deleted from the card or the Mutations
  pane, like any node.

### 8 — Editing at a stop edits the set

ADR-0042 §5 stands: a stop is an anchor, and editing at a stop edits that anchor's set.
- A field the set changes edits its row.
- A field the set does not change adds a row to the set.
- New positions are still created only in the prose.

The difference is the write: a stop edit saves the set file, never the scene, so it cannot collide
with prose being typed. This settles #2222 and ADR-0089 Amendment 2's open decision.

**What is editable at a stop.** Every field a mutation can target (§4) is editable at a stop, in
the header, the rail and the list tabs, including the detail-line segments.
- Computed fields stay read-only.
- A field that is read-only because of its layer stays read-only.
- The body is not editable at a stop (below).

This replaces ADR-0013's and ADR-0088's whole-card read-only stop.

**How each field type edits:**
- **Scalar, select, reference and number fields, and the title,** show their usual control with the
  effective value. Saving writes the row as a `replace`, with the same commit gestures the rail
  uses.
- **A collection or keyed list** edits as a list and is diffed against the state without this set,
  as the stop editor does for keyed lists today (`mutationStopEdit.ts`). The diff becomes the
  set's rows for that field.
  - For a linked set, "without this set" excludes **every** anchor of the set. Otherwise an item
    the set adds would already be present from its earlier anchor, and the diff would drop it
    everywhere.
- **A text field with an `add` row** edits that row's appended text, not the effective whole.
  Without one, editing the field adds an `add` row rather than replacing the text, so earlier
  fragments are never overwritten. *(Replaced by Amendment 1: a short `text` field edits as a
  scalar; a `long_text` field is read-only at a stop.)*
- **An edit that equals the value without this set removes the row.** A set may have no rows; it
  then contributes nothing.
- **The body stays a read-only overlay at a stop.** The overlay shows base text plus appended
  fragments, and typing into it cannot say which fragment it changes. Body rows are edited in the
  pill dialog.

**The rest of the stop's behaviour:**
- **A linked set's stop names every place the edit will apply** in its caption, before the first
  keystroke.
- **The scrubber stays on its stop** when the mutations index refreshes: after a stop edit, after a
  scene autosave, after a set change elsewhere. It keys on the anchor id, and falls back to base
  only when that anchor is gone. Today any refresh returns the card to base.
- **The dock's keys need focus in the dock at an editable stop**, as they do at base. ←, → and Esc
  typed in a field or a popover edit that field; they do not scrub. ADR-0088 §4's "the read-only
  overlay frees the whole keyboard" no longer holds.
- **A title edit at a stop refreshes the effective names** the scene matcher uses, as any
  mutations change does.

### 9 — Deleting entries and changing the schema

- **Deleting an entry deletes the sets pinned to it,** the way it deletes chats whose subject it
  was (#1078).
  - The delete warns first and names the sets and how many scenes anchor them (ADR-0089 §9's rule).
  - This replaces ADR-0055 §3's purge of the pin, which would have turned an active set into a
    template.
  - The sets' anchors are left in the prose, shown as missing pills and listed by Verify. The
    writer deletes them like text.
- **Deleting a set purges references to it,** including a chat's `staged_set`.
  - Today the file is deleted and the chat's reference is left dangling (`delete_mutation_set_entry`,
    `mutation_sets.py:153`).
  - Deleting an active set warns with the number of scenes that anchor it.
- **Renaming a field renames it in rows; deleting a field removes its rows.**
  - This covers every set and every override in the layers the rename reaches, alongside the
    `metadata` keys it rewrites today.
  - An option rename rewrites row values the same way.
  - Overrides have the same gap today. It is fixed here because both use the same row.

### 10 — A set lives in the project whose scenes anchor it

An anchor names a set in the open project. `index.by_id` also holds ancestor nodes, so the lookup
must check that the set is in the open project. An anchor whose set is only found in another layer
is missing.

Placing a template or a staged set from an ancestor layer copies it into the open project first
(§6). Promotion (ADR-0078 §7) moves a template or a staged set as today and refuses an active one.
The message says to remove it from the scenes that anchor it, which is now something the writer can
do.

### 11 — Snapshots

Restoring a scene snapshot writes its bytes back as today (`restore_snapshot`,
`scene_snapshots.py:779`). The anchors come back and point at the sets as they are now. A set
deleted since then shows as missing. ADR-0043 already says a restore brings back prose, not world
state.

**A restored anchor whose id now exists in another scene** is re-minted and given a copy of its
set. This is the case where the anchor was cut from this scene into another after the snapshot.
- The copy keeps every row. Restore writes without validation (§4), so what the restored scene
  resolves to is not changed by the restore.
- Verify reports any row that fails.

**A snapshot taken before §12's migration holds inline markers.**
- The migration does not reach snapshots. They upgrade through the document-only sub-ladder
  (`migrate_document`, `migrations.py:1177`), which cannot create files.
- So `restore_snapshot`'s branch for an older schema version converts the body with §12's rules
  before writing it, and writes any set it needs through the same index-write path every node
  save uses, so the new pills resolve at once.
- The conversion derives ids exactly as §12 does, including step 3's per-scene ids for a unit id
  repeated across scenes.
  - It tries the set derived from this scene and the unit id first, then the one derived from the
    unit id alone.
  - A marker whose set the migration already created therefore becomes that set's anchor again,
    under the same anchor id.
  - A marker whose set no longer exists recreates it from the marker.
  - The re-mint rule above applies only after this lookup.
- A restore to a book-override layer does not touch scene bodies and is not affected.

A set is an authored node, so it has its own version history (ADR-0087).

### 12 — Migration

One `ChainMigration` step (ADR-0082 §6), the next on the ladder (v14 at the time of writing), run
per layer, outermost first, each layer backed up. It reads entry titles and types across the chain,
because a scene's markers can change an entry that belongs to an ancestor layer.

The steps write sets first, then scenes, then flags, and each step does nothing to input that is
already migrated. A re-run after a crash therefore finishes the job instead of duplicating it. Set
files are named after their set id, so a re-run overwrites a set instead of adding a second file.

1. **Rows get ids.** Every set row in the layer gets an id, derived from the set's id and the row's
   index.
2. **Markers become sets and anchors** (layers with scenes, every scene file, in or out of the
   tree).
   - Each unit becomes a set pinned to its entity. It takes the entity's type as
     `target_entry_type`, the unit's rows with their row ids, and the unit's name as its title;
     an unnamed unit gives an untitled set.
   - The set's id is derived deterministically from the unit id. The unit becomes an anchor whose
     id is the unit id.
   - A unit whose entity no longer exists keeps the dead id as its pin (§2).
3. **A unit id found in more than one scene is a copy.** Prose copied between scenes kept its
   marker ids, because today's paste de-duplication works within one document only.
   - The first occurrence in manuscript order keeps the id.
   - Each later occurrence gets an anchor id and a set id derived from its scene and the unit id.
     So each copy is its own set, not a link.
4. **Legacy `group=` markers stay one set per marker,** each anchored where the marker was. Merging
   them would move rows to one position and change resolution. The group name becomes each set's
   title.
5. **Closes are rewritten** so they end exactly what they end today:
   - A close on a unit id refers to that anchor.
   - A close on a row id becomes `ref=<that row's anchor>;row=<row id>`.
   - A close on a `group=` id becomes one close per member anchor, at the same position.
   - A close whose id is repeated across scenes (step 3) becomes one close per occurrence it ends
     today.
6. **Placed sets are matched.**
   - A set with `placed: true` in the open layer is matched against the sets from step 2 with the
     same entity and the same rows.
   - On exactly one match, the step-2 set is kept, and it takes the placed set's title if it has
     none. Every reference to the placed set in the layer is rewritten to the step-2 set, the
     chat's `staged_set` included. The placed set's file is then deleted. This keeps the row ids
     that closes, reviews and todos point at, and the unit-derived id that restore relies on.
   - Without exactly one match, the placed set keeps its content and becomes staged, visible on
     its entity's card.
   - A placed set in an ancestor layer is not matched: that layer migrates before the book is
     read. It becomes staged where it lives.
   - `placed` is dropped from every set in every layer.

Legacy markers anywhere but a scene body are left as text; the index never read them.

## Why / rejected alternatives

ADR-0001 rejected this model for three reasons. Each is answered here.

- **"A second source of truth."** Nothing is stored twice: the set holds what changes and the
  anchor holds where. What remains is keeping the two sides joined, and the anti-goals keep them
  from overlapping (no position in the set, no values in the anchor).
- **"It splits position from data and fights resolution by position."** Resolution already walks the
  prose for positions. It now also looks each set up by id (§5), and positions are unchanged.
- **"Orphans when scenes move or are deleted."** A move carries the anchor with the prose. A delete
  leaves a set with no anchor, and in the staged/active lifecycle ADR-0055 added, that is the
  staged state, not an orphan.

Other options considered:

- **Keep Model A and add `set=` provenance to the marker.**
  - It makes placement derivable and fixes the stuck flag.
  - It leaves everything else: renames still rewrite prose, stop edits still write the scene,
    linking still needs a pointer, and a set's rows and a marker's rows stay two copies of the same
    thing.
- **A new `mutation` kind beside `mutation_set`.**
  - It would have exactly the set's storage shape: rows plus an entity.
  - ADR-0011's own test for a new kind is a different storage shape, and this fails it.
- **The set stores its scene and offset.** An offset changes with every keystroke above it, and the
  set file would have to be rewritten as the author types. Position has to live in the text.
- **Readable values in the anchor** (`⤳ rank → Captain` beside the ids).
  - It would help someone reading the `.md` outside the app.
  - But it is a copy of the rows that goes stale on the first set edit, and no code may trust it.
  - The set file is the readable record: its title and rows are plain YAML.
- **Delete a set when its last anchor goes, as todo anchors do.** `_remove_missing_scene_todo_anchors`
  (`scene_todos.py:61`) drops a todo whose anchor is gone. Doing the same for sets breaks three
  things:
  - A cut in one scene, saved before the paste in another, would delete the set the paste still
    needs.
  - Ctrl+Z after an autosave would bring back an anchor to a deleted set.
  - A chat's staged set would disappear when its pill was deleted.
  
  A todo has none of these lives; a set has all three.
- **Pasting always links, or always copies.**
  - Always linking makes a copied paragraph change when the original's set is edited, with no
    gesture that said so.
  - Always copying makes a cut-and-paste, which is a move, leave a staged leftover behind.
  - Following cut and copy is what every editor already teaches. It has to be tracked by the app
    at cut time, because the saved scene still holds the cut anchor until its autosave.
- **Merging `group=` markers into one set per group.** It would move rows to one position and
  change what the scene resolves to.
- **Keeping the placed set on a match and dropping the step-2 set.**
  - The placed set's rows have ids derived in step 1, not the row ids closes and reviews point at.
  - A restore would derive the step-2 set's id, find nothing, and create a duplicate.
- **Validating every row check on save.** Keyed-item checks need a position, and a set has none or
  several. Refusing them on save would block the migration's own output and chat staging.
- **Anchors to a set in an ancestor layer.**
  - Two books anchoring one series set would be a change shared across books, which ADR-0005 and
    ADR-0039 keep out of scope.
  - Promotion would move a set that anchors in another book.
- **Keeping the body editable at a stop.** The overlay shows base text with appended fragments, and a
  keystroke in it cannot be assigned to a fragment.

## Consequences

- **A scene file is less readable on its own.** Outside the app, a scene shows `set=` and an id
  where it used to show the entity, field and value. ADR-0016 called the files "the human-readable
  source of truth"; for mutations, the set file now is. This is the main cost of the decision.
- **A pill edit is no longer undone with Ctrl+Z.**
  - Today the pill dialog changes the TipTap document, so editor history reverts it
    (`applyMutationUnitDraft`, `mutationNodes.ts:201`).
  - After this change it saves a node, like a rail edit, and like a rail edit it has no undo.
  - Removing or re-inserting a pill is still prose and still undoable.
- **Deleted pills leave staged sets.** A writer who deletes pills by typing will collect staged
  sets on their entities' cards. They are visible and deletable, and they are what makes cut,
  paste and undo safe.
- **One change can live in several places** (#66), by choice, with the count shown wherever it is
  edited.
- **Stop edits never touch the scene** (#2222). `rewrite_mutation_unit`, its route, and the
  `PATCH`/`DELETE` single-marker routes and their unused frontend wrappers retire.
- **The file count grows by one set per change**, under `mutation-sets/`, the way each lore entry
  is already one file.
- **Backend:**
  - the grammar in `lore_mutations.py` shrinks to anchor and close; the legacy patterns move beside
    the migration, which with restore is their only reader;
  - the index joins anchors with sets and keys records by `(anchor, row)`;
  - set save validates rows;
  - the rename, delete and purge paths gain rows and sets, and the entry delete cascades to its
    sets;
  - `placed` and `place_mutation_set_entry` retire;
  - restore converts legacy markers;
  - Verify gains missing, other-layer, unpinned and dead-pinned anchors, duplicate anchor ids and
    unresolved closes;
  - the migration step.
- **Frontend:**
  - the pill round-trips an anchor and renders its label from the set, so a set edit relabels it
    without a document change;
  - `/mutate` and the pill dialog save sets;
  - paste follows cut and copy, with the cut recorded when it happens;
  - the apply picker flushes open scenes and offers Copy, with Link from S4;
  - the stop editor saves sets, covers every targetable field, and keeps its stop across
    refreshes;
  - the dock's keys need focus at an editable stop;
  - the Mutations pane shows each set's state and places;
  - the card lists staged sets with Delete and points to `/mutate` for placing.
- **Docs:** `docs/mutations.md` and the in-app guide (`guides.ts`, regenerated) describe sets,
  anchors, linking and editing at a stop. The guide's "slide back to the start to edit" goes.
  `CLAUDE.md`'s vocabulary line stays true: a mutation set is staged until placed, then active.
- **Tests:**
  - The resolution tests keep their assertions and build their fixtures through sets and anchors.
  - The migration: single-line, carrier, `group=`, repeated unit ids across scenes, row and group
    closes, a placed-set match and non-match, a dead entity, a re-run after a partial run.
  - Restore of a pre-migration snapshot, with its set present and deleted, and of a snapshot whose
    anchor was since cut elsewhere.
  - Copy against cut, including a paste before the source scene saved.
  - Rename and delete reaching rows, and the entry-delete cascade.
  - A linked set's list edit, and the scrubber keeping its stop across a refresh.

## Slices

1. **S1 — sets and anchors.** §1–§7 and §10–§12, with the apply picker's active sets offered as
   Copy only. It cannot be split: the prose format switches at once, in the backend and the editor
   together.
2. **S2 — editing at a stop.** §8, closing #2222.
3. **S3 — deletes and schema changes.** §9.
4. **S4 — linking.** Link in the apply picker and the linked-set tells in §6 and §8, closing #66.
5. **S5 — the set's home.** The Mutations pane shows template, staged and active with places; the
   card lists and deletes staged sets.

One lane, in order. S2 to S5 each build on S1's sets, and S4's tells appear in the stop editor S2
builds.

## The journey that defines done

1. **Migration.**
   - The author opens a book made before this change, and it migrates.
   - Every pill reads as before.
   - The lore card scrubs through the same stops with the same values.
   - A conversation that staged and placed Mira's first change still names that set, and the set
     is the one anchored in Chapter 3.
   - A paragraph they once copied from Chapter 2 into Chapter 6 has two pills that are two sets.
2. **Creating a change.** In Chapter 5 they type `/mutate`, pick Honor, set rank to Captain and
   name it "Promotion". In the project folder there is one new file in `mutation-sets/` and one new
   comment line in the scene.
3. **Editing at a stop while typing.** On Honor's card they scrub to "Promotion" and change rank to
   Commodore in the rail, while Chapter 5 is open with unsaved typing.
   - The typing is not lost, and the scene file has not changed.
   - The card is still at the Promotion stop, and it reads Commodore.
4. **A list item at a stop.** At the same stop they click a segment of Honor's Connections item for
   Kyria and type "owes her". The stop shows it with ⤳; stop 0 does not.
5. **Deleting and undoing a pill.** They backspace over the Promotion pill. Honor's card lists
   "Promotion" as staged. Ctrl+Z brings the pill back, and it is active again.
6. **Copying prose.** They copy the paragraph holding the pill into Chapter 9 and change the copy's
   rank to Admiral. Chapter 5's stop still says Commodore.
7. **Cutting prose.** They cut a paragraph with a pill from Chapter 2 and paste it into Chapter 4
   straight away. Nothing is left staged, and the stop moved to Chapter 4.
8. **Linking.** Mira's "Full moon" is active in Chapter 3. In Chapter 7 they apply it again and
   choose Link.
   - The pill reads "Full moon · 2 places".
   - At the Chapter 7 stop, the caption names Chapter 3 before they type.
   - They change her eye colour and add "silver" to her weaknesses. Both stops show the new
     colour, and "silver" is still added at Chapter 3.
9. **Renaming a field.** In the schema they rename `rank` to `service_rank`. Honor's stops still
   change it.
10. **Deleting an entry.** They delete a minor character. The warning names two sets in three
    scenes. Afterwards those pills show as missing, and Verify lists them.
11. **Restoring snapshots.**
    - They restore a snapshot of Chapter 5 from before the migration. Its changes come back as
      pills that open their sets.
    - They restore Chapter 2 from before the cut in step 7. Its pill comes back as a copy, and
      Chapter 4's pill is unchanged.
12. **Promotion.** They promote a staged set to the series. An active one is refused with a message
    that says how to unplace it, and removing its pills makes it promotable.

## History

Written on 2026-09-25, while parking #2222. Anton asked for an all-round audit of mutations before
building editing at a stop. The audit found the design sound and well tested, but its open problems
clustered in three places: the stored `placed` flag, renames and deletes that do not reach markers,
and stop edits that write the scene.

Anton then asked whether a mutation should be a node that the scene only references. That is
ADR-0001's rejected Model B, and its three objections were re-examined against the app as it now
is. A check of the code against a first outline found four things:
- set rows have no ids;
- the field rename walks only scene and lore metadata;
- migrations do not reach snapshots, hence §11's conversion on restore;
- todo anchors already follow this pattern, with the opposite orphan rule, hence the rejected
  alternative.

Two cold implementing threads then planned S1 to S2 from the draft. The backend thread found:
- repeated unit ids across scenes, which the migration would have turned into links;
- the need for `(anchor, row)` record identity;
- that a placed set kept on a match would strand row ids and defeat restore;
- that merging `group=` markers moves positions;
- that save validation cannot be positional;
- that the node index does not see anchors;
- that an ancestor set would resolve through `by_id`.

The frontend thread found:
- that a cut is invisible in saved files until autosave;
- that a copy must never name the original even briefly;
- that a linked set's list diff must exclude all its anchors;
- that the scrubber returned to base on every refresh;
- that a dock key would scrub the card away mid-edit;
- four drifted citations.

Each is decided above.

## Amendment 1 — Text fields at a stop (2026-09-26)

Accepted by Anton on 2026-09-26, during S2 (PR #2237). It replaces §8's text-field rule.

### The problem
Building S2 showed that the append rule fails both kinds of text field.
- **Short text.** At a stop, a short text field's control opened empty, because the set had no row
  for it, and whatever the writer typed was appended. Changing Erik's pronouns from "He/Him" to
  "She/Her" at a stop produced "He/Him She/Her". That is right for accumulating prose, and wrong
  for a pronoun, a rank or a label.
- **Long text.** The rail's `long_text` editor is always live and has no separate display state.
  At a stop it could show only the fragment this set appends, or nothing. The card then said a
  field was blank at that point in the story when it was not, which breaks the scrubber's promise
  of showing what is true there.

### The decision
- **A short `text` field edits at a stop like any other scalar.** Its control shows the effective
  value. Saving writes one `replace` row, which is removed when it equals the value without the
  set.
- **A `long_text` field is not editable at a stop.** It shows the full effective value, read-only,
  the way the body does. Its rows, `replace` or `add`, are edited in the change's dialog.

Appending stays available where it belongs, for long prose, and is authored where the fragment
has a place to be seen: the `/mutate` and pill dialog. The card never has to show a fragment in
place of a value.

### Not in scope
Resolution is unchanged: `add` rows on text fields still append exactly as §5 and ADR-0009 say. No
migration, and no backend change.
