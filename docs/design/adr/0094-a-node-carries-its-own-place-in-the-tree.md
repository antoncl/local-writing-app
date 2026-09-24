# ADR-0094: A node carries its own place in the tree, and a container is named by its level

- **Status:** Draft — awaiting review. Text by Claude from a design conversation with Anton
  Lauridsen on 2026-09-24 (#217), revised against two cold implementing threads (one per
  slice group) before review. Acceptance alone starts nothing; each slice gets its own issue
  and an explicit go.
- **Feature:** the manuscript and research trees are stored on the nodes themselves. A node's
  file says which container it sits in and where among its siblings, so the separate structure
  files go away, a change made to the files outside the app shows in the tree, and a move writes
  one file. A container is named, typed and numbered by its **level**, from a per-project list
  the author edits, instead of by which of two built-in types it happens to be.
- **Relates to:** ADR-0037 §4 and Amendment 2 (containment is a relation; `rank` is the sibling
  order and becomes explicit when the structure files go — this ADR is that step), ADR-0029
  (stored / intrinsic / computed by authorship), ADR-0028 (Nest guards), ADR-0079 (the narration
  cascade walks ancestry), ADR-0048 §3 (the plot board projects the manuscript's containers —
  amended by reference in §9), ADR-0040 (the node index and its snapshot) and #2170 (the
  mid-session refresh), ADR-0043 and ADR-0087 (snapshots, the session boundary, byte-exact
  restore — narrowed in §6), ADR-0045 (scope), ADR-0071 and ADR-0082 §6 (the migration ladder
  and `ChainMigration`), ADR-0074 (context picks). Closes #217. Fixes the tree half of #2172.
- **Words used here.** A *tree* is the manuscript or the research tree. A *container* is a node
  that can hold nodes; a *leaf* is a scene or a note. *Placement* is a node's `parent` and
  `rank` together. A *sibling group* is the nodes that share a `parent`. A container's *level*
  is its depth among containers, counted from 1 at the top. The *level list* is a tree's
  ordered list of level entries (§7). The *honoured parent* is the parent the tree actually
  places a node under, after §5's rules.
- **Verified against `05e79c0d` (2026-09-24).** Symbols first, line numbers second.

## Problem

`manuscript.structure.yaml` and `research.structure.yaml` hold the two trees: which node sits
in which container, and in what order. That makes them the one place the tree lives, and it has
four costs.

- **The tree and the files disagree, and nothing reconciles them.** A scene deleted outside the
  app stays in the Draft tree, because the yaml still lists it; opening it says the scene does
  not exist, and only Verify reports it (`_validate_structure_references`,
  `backend/app/services/project/lifecycle.py:1046`). A scene file dropped into `scenes/` is in
  no tree at all until the Import documents dialog adopts it (`list_loose_scenes`,
  `manuscript.py:373`; `ImportDocumentsModal.svelte`, #635). #2170 made the index catch up with
  the disk when the window regains focus; the trees cannot, because they are not in the index.
- **Two id spaces for one node.** A tree node has its own `node_…` id beside the id of the file
  behind it (`create_structure_node`, `manuscript.py:312`, mints both). An act or chapter is
  referenced by its tree id, a scene by its file id, and the frontend bridges the two
  (`structureToEvalNodes`, `frontend/src/lib/views/structureNodes.ts:21`, carries the file id
  as `ref_id`). Container tree ids are persisted in views' collapse state, the plot board's
  saved sizes, chats' context picks and reference fields.
- **The title is stored twice.** The yaml keeps a copy of each title, and three paths keep it in
  step with the file: rename, save, and snapshot restore (`_update_scene_title_in_structure`,
  `manuscript.py:626`; `_heal_after_restore`, `scene_snapshots.py:826`).
- **Research topics exist only in the yaml.** A topic has no file (`create_research_node`,
  `research.py:65`, writes one only when the type has a body), so it cannot be opened, carry
  metadata, or be referenced the way an act can.

ADR-0037 §4 settled that containment is a relation, `(parent, child, rank)`, and that the
structure files are its current storage, to be replaced by references stored on the nodes with
no change to any view spec. Amendment 2 kept `rank` positional until that step, because a bare
set of references has no order.

Separately, the manuscript's containers are two built-in types, `manuscript:act` and
`manuscript:chapter` (`default_entry_types.py:26-42`), with the same fields. Nothing but their
names tells them apart, and code that asks "is this a container" or "is this a scene" keeps its
own list of names or tests an exact name (`TreeStructureService._CONTAINER_TYPES`,
`tree_structure.py:299`; `CONTAINER_TYPES`, `frontend/src/lib/utils/manuscriptPickTree.ts:49`;
`NodePicker.svelte:304`; `_is_leaf_node`, `manuscript.py:614`). So an empty user-defined
container counts as a scene, and a user-defined scene type counts as a container on the plot
board. A third level — a sequence inside a chapter — needs a third type and a third entry in
each list. And `manuscript_structure.container_types` in `project.yaml`, written for every new
project (`_default_project_yaml`, `lifecycle.py:306`), is read by nothing.

## Intent

**A node's file says where the node sits; the tree is built from the files.** A move writes one
file. A file added, moved or removed outside the app is in the right place in the tree the next
time the app looks. A container is named, created and numbered by its level, from a list the
author edits; a new project has one container type.

## Anti-goals

- **No structure file kept as an index, cache or fallback.** The node files are the only place
  placement is stored. The node index already caches what is read from them.
- **No change to any view spec.** ADR-0037's conformance suite
  (`frontend/src/lib/views/adr0037.conformance.test.ts`) passes unchanged; the containment
  Nest joins on `parent` as it does today.
- **No tree that spans the inherits chain.** Both trees stay per project, as today. A research
  note inherited from an ancestor project has no place in the open project's tree, as today
  (`save_research_note`, `research.py:301-308`, records that tree inheritance is not planned).
- **No per-node level setting.** A container's level is its depth.
- **Not a live level name in titles.** The level name is used where a container is created,
  outlined and drawn (§7); a container's title is what its author wrote, and renaming a level
  retitles nothing.
- **No third kind of tree node.** A tree has containers and leaves, nothing else; a level is a
  name and a type for a container, not a new kind.
- **No linked list.** A node does not name its neighbour (§Why).
- **Not undo for tree operations.** None exists today; this ADR does not build it.
- **Not a new import flow.** The loose-scene import retires (§5); nothing replaces it.

## Decision

### 1 — Placement is two front-matter keys on the node's file

A node in a tree carries its placement at the top level of its front matter, beside `id`,
`title` and `entry_type`:

```yaml
---
id: manuscript_46008a817a
title: The Landing
entry_type: manuscript:scene
parent: manuscript_9c01f3aa20
rank: 3
---
```

- **`parent`** is the id of the container the node sits in. Absent means the top of the tree.
- **`rank`** is a number. Siblings are shown in ascending `rank`.

**Placement is not a schema field.** Neither key is declared in any schema, shown as a rail
row, or read as a reference: a scene is not a backlink of its chapter. The keys live outside
`metadata`, so they cannot collide with a metadata field. Views see placement through the
computed `parent` the tree already supplies to the containment Nest (§3); a user field named
`parent` or `rank` applied to a tree kind is refused at schema save, because the view layer
would shadow it — which is the clobbering noted on #217, where `structureToEvalNodes`
overwrote a user field named `parent`. A field of that name on another kind is untouched.
**`children` is computed**, as ADR-0037 §4 has it.

**Every write of a node file keeps the placement on disk.** The typed writers
(`_write_scene_file`, `project_service.py:623`; `_write_research_note_file`, `research.py:248`)
write a fixed set of keys today; each re-reads `parent` and `rank` from the file at write time
and writes them back. Placement is never taken from the client's payload: an editor pane
never sends it, so a pane opened before a move cannot move the node back when it saves. Only a
placement (§2) changes placement.

### 2 — Sibling order: a number between the neighbours

A placement computes the new node's `rank` from its neighbours in the target sibling group,
excluding the node itself:

- **between two siblings:** the shortest decimal strictly between their ranks, nearest the
  midpoint, rounding half up — between 2 and 3 it is 2.5, between 2 and 2.5 it is 2.3, then
  2.2, 2.1, 2.05;
- **first:** the first sibling's rank minus 1;
- **last, or an empty group:** the last sibling's rank plus 1, or 1.

Ranks are computed in decimal arithmetic and written as the shortest decimal string; binary
floats would write `0.30000000000000004`. A `rank` that is not a number (a string, a boolean)
reads as missing.

Reading the order:

- **Ties sort by id.** Two nodes with the same rank (a sync-conflict merge, a hand edit) are
  ordered by id, so the order is total and stable.
- **A missing rank sorts after every ranked sibling**, ties by id.

**Renumbering.** A placement renumbers the target sibling group when no rank fits: the value
between the neighbours would need more than six decimal places, the two neighbours share a rank,
or a neighbour has no rank. The renumber covers the whole group as it currently stands —
**including the node being placed, if it is already in the group** — and assigns fresh ranks
above the group's current highest (1 upward when no sibling has a rank), writing from the last
sibling backwards; then the node is placed:

```
before:        A=1  B=1.000001  C=1.000002  D=2
write D → 6:   A=1  B=1.000001  C=1.000002  D=6
write C → 5:   A=1  B=1.000001  C=5         D=6
write B → 4:   A=1  B=4         C=5         D=6
write A → 3:   A=3  B=4         C=5         D=6
```

Every intermediate state is in the right order, so a crash part-way through a renumber leaves
the tree correct. Leaving the moving node out would break that: with A=1, B=1, C=2, moving C
between A and B and renumbering only A and B above 2 passes through A, C, B. Renumbering happens
only inside a placement. Nothing renumbers on open, on refresh or on read; a group whose ranks
are untidy but sort correctly is left alone.

**The backend owns ranks.** The frontend sends the intent it sends today — this node, under this
parent (the synthetic `"root"` for the top level), at this position, counted with the node
removed from its old place — and the backend resolves the neighbours, computes the rank,
renumbers when it must, and writes. A placement that would leave the node where it is writes
nothing. `"root"` is accepted as a target and never written to a file. A person editing a file
by hand may write any number; the tie and missing-rank rules cover whatever they write.

**When tree undo is built**, a move's inverse is relative — back under its old parent, after its
old previous sibling — not "restore the old rank", because a renumber may have moved the
siblings the old rank sat between.

### 3 — The tree is read from the node index

The index already reads every node file's front matter. `NodeIndexEntry`
(`backend/app/services/project/node_index.py:26`) gains `parent` and `rank`; the change-gate
signature (`_index_signature_from_memo`, `references.py:719`) gains both, so a move is a change
the memo patches and a move made outside the app is a change #2170's refresh reports; and the
index snapshot (`node_index_snapshot.serialize` and its rehydrate) carries both, or a warm open
would load every entry unplaced.

The tree is built from the index: the open project's nodes of the tree's kind, grouped by
honoured parent, each group in rank order under the synthetic root. Each built node carries the
file's `entry_type` as its `type`, and the builder stamps its level. `TreeStructureService`
keeps its read interface — `walk`, the visitors, `collect`, `find_node`, `find_parent`,
`collect_descendant_scene_ids_ordered` — over the built tree instead of the parsed yaml, so the
consumers that walk the manuscript (the narration cascade, `story_so_far`, `full_outline`,
`full_text`, the counters, context-pick expansion, mutation order, the plot board, search
breadcrumbs, seeding cards) keep calling what they call today. Its write methods (`insert_node`,
`extract_node`, `remove_node_by_id`, `write`) retire: every write is a write to a node file.

The frontend's containment Nest joins on the **honoured** parent, projected from the built tree
by `structureToEvalNodes` as today — not on the raw front-matter value, under which a node with
a broken `parent` would be neither a root nor anyone's child and would vanish from Draft.

### 4 — One id per node

A tree node's id is its file's id. The `node_…` id space retires. `StructureDocument` keeps its
shape (a root with nested children); a node's `id` is the file id, and `scene_id` carries the
same value, so the frontend's `scene_id` readers keep working. Removing the duplicate field is
its own change.

A context pick of a container's id means its scenes, as a pick of its tree id does today
(`_container_node_for_pick`, `ai/preview.py:411`). A pick that named the container's file id
meant the container's own node; that meaning goes, because the two ids are now one.

The v12 migration (§10) rewrites persisted `node_…` ids to the file ids they stood for.

### 5 — What the files say is the tree

- **A file added outside the app** sits where its `parent` and `rank` put it; with neither, at
  the end of the top level. The Import documents dialog, its menu entry, and
  `list_loose_scenes` / `import_loose_scenes` with their routes retire: a file in `scenes/` is
  always in the tree, so there is nothing to adopt.
- **A node deleted outside the app** is not in the tree. #2170's refresh reports it, and an open
  pane on it closes.
- **A placement the tree cannot honour** puts the node at the top level, keeping its own
  children, and Verify warns, naming the node and the reason:
  - `parent` names no node of the open project, a node of another kind, or a leaf;
  - `parent` forms a cycle — every node on the cycle goes to the top level.

  So a chapter deleted outside the app leaves its scenes at the top level with a warning each;
  nothing is deleted or lost.
- **A container deeper than its tree's level list** (§7) — from a hand edit or from shortening
  the list — stays where it is, is named by the
  list's last entry, and Verify warns. The app never produces one: creation offers no level
  beyond the list, and a move that would push the moved node or any container below it past
  the list is refused.

ADR-0028 §D's cycle guard in Nest stays as it is; the rules above mean the Draft and Research
defaults never reach it.

### 6 — Placement is not content

Placement is where a node is, not what it says. Three things that read a node's file as
content ignore it:

- **The save revision.** `save_scene` and `save_research_note` reject a save whose base revision
  differs from the file's (`manuscript.py:544`, `research.py:291`). The revision is computed
  over the file with `parent` and `rank` removed, so a move or a renumber of its siblings does
  not make an open pane's next save a conflict.
- **The session boundary.** `maybe_capture_session_boundary` (`scene_snapshots.py`) reads the
  file's modification time as the last save. A placement write is not a save; the boundary
  rule counts authored saves only, so dragging a scene does not suppress the next session's
  snapshot.
- **Snapshot restore.** Restore writes the snapshot's content with the node's **current**
  `parent` and `rank` (`restore_snapshot`, `scene_snapshots.py:747`, writes the snapshot's
  bytes wholesale today). Restoring a scene's text never moves the scene. This narrows ADR-0043's
  byte-exact restore: the restored file is the snapshot's bytes except for the two placement
  keys. The title re-sync into the structure yaml (`_heal_after_restore`) retires with the yaml.

### 7 — The level list names, types and numbers containers

Each tree has one **container type** and one **leaf type**: `manuscript:container` and
`manuscript:scene`; `research:container` and `research:note`. The research container is named
by its role, as the manuscript's is; "Topic" is a level name, as "Act" is. "Is this a container" is `is_a` the
container type; "is this a leaf" is `is_a` the leaf type. The name lists and exact tests
retire — `_CONTAINER_TYPES`, the frontend `CONTAINER_TYPES`, NodePicker's act/chapter filter,
`_is_leaf_node`, `treeHelpers.isLeafNode`, the `=== config.leafType` tests in
`StructureTree.svelte`, and the exact tests in `research.py`, `ai/preview.py`,
`realizeLocations.ts` and `refResolve.ts`. A container with no children is still a container;
a user-defined scene type is still a scene.

`manuscript:container` carries the fields `manuscript:act` and `manuscript:chapter` carry today
(`pov_mode`, `pov`, `tense`) and the display template `{title} {number}`. `research:container`
carries what `research:topic` carries today, minus `opens_in: tree_container`: a research
container is a file and opens like any node. A new project's schema has no other container type
in either tree. Research types must be authorable as manuscript ones are; today the schema's
entry-type upsert rejects every save of a research type, built-in edits included
(`_resolve_upsert_entry_type_id`, `services/project/schema.py:324`), which is bug #2174 and is
fixed on its own, ahead of S2.

**The level list.** Each tree's list lives in `project.yaml`, replacing
`manuscript_structure.container_types`:

```yaml
manuscript_structure:
  levels:
    - name: Act
    - name: Chapter
      numbering: continuous
research_structure:
  levels:
    - name: Topic
```

An entry has:

- **`name`** — what a container at that level is called when it is created, outlined and drawn.
- **`type`** — optional; the entry type a new container at that level is created as. Default:
  the tree's container type. It must be `is_a` the container type.
- **`numbering`** — `restart` (default) or `continuous`; see Numbering.

A new project's lists are `[Act, Chapter]` and `[Topic]`, on the container types. The author
edits both lists in the project settings (the breadcrumb, beside the inherits declaration). The
backend validates a list: names non-blank, types that exist and are `is_a` the tree's container
type, at least one entry. Names may repeat — a research tree two topics deep is
`[Topic, Topic]`. Removing or reordering entries that containers sit at is
refused unless confirmed, and the refusal names how many containers would be named by a
different entry or fall past the end of the list. A list is per project; a book does not
inherit its series' list.

**Creating.** Inside a container at level *n*, the tree offers "New ⟨name⟩" for the (*n*+1)th
entry, creating its `type`, plus that type's concrete sub-types by their own names; at the top,
the same for the first entry; inside a container at the last level, no container at all. Scenes
and notes can be created in any container. A new container is auto-titled from its level name
(`nextAutoName`, `StructureTree.svelte:185`, titles one from its type name today), or from its
sub-type's name for a sub-type.

**Naming.** The level name is used for the create label, a new container's auto-title,
`full_outline`'s `level` attribute, and the plot board. Everywhere a node's type would be shown
as a label on the node itself — the tree's delete tooltip, the NodePicker's chips, the
metadata panel's type header — a container shows its level name. The schema panes show the
type's own name ("Container").

**Numbering.** `{number}` on a container counts the containers **at the same level** that show a
number (their display template contains `{number}`), in reading order:

- **`restart`** — among the containers at that level under the same parent: Act 2's chapters are
  Chapter 1, Chapter 2.
- **`continuous`** — among every container at that level in the tree: Act 2's chapters continue
  as Chapter 3, Chapter 4.

For the top level the two are the same. A container whose display template has no `{number}`
is not counted, so a Prologue sub-type with template `{title}` beside the acts does not take
"Act 1". Scenes keep the `number` field's own `scope` (`default_schema.py:674`); the counter's
container branch (`_counter_among_siblings`, `computed_metadata.py:245`; `_ManuscriptOrdinal`,
`:30`), which counts by exact entry type today, counts by level.

**What the AI sees.** `full_outline` names each container's element by its entry type's key as
today (`<container>`, `<act>` for a migrated project, `<prologue>` for a sub-type) and adds a
`level` attribute with the level name; the outline node gains `level` for templates; the
vocabulary reference (`docs/prompts/reference.md`) gains the row.

### 8 — Existing projects keep their act, chapter and topic types

The v13 migration (§10) does not fold `manuscript:act`, `manuscript:chapter` or `research:topic`
into the container types. It makes the first two sub-types of `manuscript:container` and the
third a sub-type of `research:container`, and binds each to the levels it occupies:

```yaml
manuscript_structure:
  levels:
    - name: Act
      type: manuscript:act
    - name: Chapter
      type: manuscript:chapter
research_structure:
  levels:
    - name: Topic
      type: research:topic
```

So an existing project keeps every customisation of those types, its prompts offered on
`manuscript:chapter` still appear, a template testing `is_a('manuscript:chapter')` or
`is_a('research:topic')` still matches, old snapshots restore to a type that still exists, and
"New Chapter" still creates a chapter. The three stop being built-ins: v13 writes their
definitions into the schema of each layer that uses them (§10).

### 9 — The plot board nests one box per level

The board already projects every container at any depth (`_PlotBoardLayout`,
`plot_board.py:45`). The frontend layout draws two tiers and styles the top one as the act
(`plotBoardLayout.ts:337-340`; `PlotContainerNode.svelte:25`). It lays containers out
recursively instead: a container draws a box when it holds cards at any depth, a top-level
container always does, each box is headed by the container's display title and styled by its
level, and cards sit in their scene's innermost container, as today. The projection gains each
container's level. This amends ADR-0048 §3's "columns are projected from the manuscript
structure (acts/chapters)" by reference: they are projected from the levels.

### 10 — Migration

Two steps, one per slice, each a `ChainMigration` (ADR-0082 §6) run per layer of the declared
chain, outermost first, each layer backed up. Every project folder in a chain has its own trees,
and v13 writes schemas an ancestor may own. Neither step can report through
`migrations_applied` (a chain step returns nothing and an ancestor's result is only logged), so
what a step could not place is reported by Verify, through §5's warnings.

**v12 — placement onto the files.** For each tree file of the layer:

1. Map each tree node to a file id. A node with a file maps to it. A research topic, or a
   container with no file, gets a new file in its tree's leaf folder (`scenes/`,
   `research/notes/`) with its title, its type and an id minted the way that tree's files are
   minted — **derived deterministically from its `node_…` id**, so a migration re-run after a
   crash rewrites the same file instead of minting a duplicate.
2. Write each node's `parent` (its container's file id, none at the top) and `rank` (1, 2, 3 …
   per sibling group, in yaml order) into its file. The file's own title and type stand; the
   yaml's copies are dropped. (A research node the yaml calls `type: note`, #2172, takes the
   `research:note` its file already says.)
3. Resolve what the yaml allowed and the new rules do not: a node listed twice keeps its first
   position; a leaf whose file is missing is dropped from the tree (references to it dangle, as
   today's purge would leave them); children under a leaf are placed under the leaf's parent,
   right after it.
4. Rewrite persisted `node_…` ids to the file ids they stood for, in the layer's own files:
   views' `ui.collapsed` placement keys and specs, `plot-board.md` `layout.sizes`, chats'
   persisted context picks, prompt input defaults, and reference values in node metadata
   (overrides included).
5. Delete the tree file. It stops being a required file (`_validate_required_files`,
   `lifecycle.py:1018`); new projects are created without one.

**v13 — levels.** For each layer:

1. Where the layer's node files or schema use `manuscript:act`, `manuscript:chapter` or
   `research:topic`, write their full definitions into the layer's `metadata.schema.yaml` —
   name, icon (`stack-2`, `book` for act and chapter), `kind`, `parent` (`manuscript:container`
   or `research:container`), and the layer's own customisation of them, which today is a partial
   overlay on a built-in and could not stand alone. The built-ins no longer define them.
2. Seed the level lists from the layer's trees: for each depth, an entry named after the type
   most containers at that depth have (ties by reading order), with that type. A manuscript gets
   at least `[Act, Chapter]` on their types, so a book with only acts keeps "New Chapter"; a
   research tree gets at least `[Topic]` on `research:topic`, and one more `Topic` entry for each
   depth its topics already nest to, so no existing topic falls past the list. Remove
   `container_types`.

Nothing else is rewritten: every stored type name still names a type that exists.

**Accepted limits of the id rewrite.** A `node_…` id stored in an ancestor layer's file, or
inside a snapshot taken before v12, is not rewritten: the ancestor migrates without reading its
descendants' trees, and snapshots are outside the migration. Such an id no longer resolves and
is dropped on read, as a dangling reference is today — a stale collapse key re-expands, a stale
pick is skipped.

## Why / rejected alternatives

- **A linked list (`after: <sibling id>`).** Order stored as relationships between files. A move
  rewrites up to three files (the node, its old successor, its new successor), which cannot be
  atomic together; a crash between them leaves two nodes claiming one predecessor or a chain
  pointing at a node that moved. A file deleted outside the app breaks the chain for everything
  after it; a sync-conflict merge forks it; a hand edit can make a loop. Each needs a repair
  rule, and the repair needs a fallback order, which is a sort key — so the list ends up
  carrying a rank anyway. A number is a property of one file: damage stays in that file, and the
  worst case is one node out of place.
- **Plain integer positions.** A move rewrites every sibling after the insertion point.
- **String keys (`"a0"`, `"a0V"`).** They never run out of room, but a person cannot write one
  without knowing how they sort. A number can be written by hand in any editor ("could a user
  author this?").
- **The exact midpoint.** Files fill with `2.0009765625`. The shortest decimal keeps them
  readable, and the renumber threshold is set by readability, far inside the arithmetic's range.
- **Renumbering 1, 2, 3 … in place, or without the moving node.** A crash part-way leaves the
  order wrong. Renumbering upward from above the highest, last sibling first, the mover
  included, is correct at every step.
- **Placement as schema fields.** Field ids are one global namespace and the intrinsic category
  is stamped by key across the schema, so declaring `parent`/`rank` would reserve them on every
  kind — a lore field called `rank` would collide — and an `entity_ref` `parent` would make
  every scene a backlink of its chapter. Placement needs no field machinery: it is written by
  one path and read by the tree.
- **Taking placement from the save payload.** A pane holds the placement it opened with; saving
  it would move a node back after a drag.
- **Keeping the structure file as a derived index.** A second copy of what the files say, with
  the reconciliation problem this ADR removes; the node index is already the derived copy.
- **Folding act and chapter into the container type.** A customised act loses its
  customisation or survives as a sub-type that "New Act" does not create; numbering shifts
  where a book mixes types at one depth; prompts offered on `manuscript:chapter`, picker
  allowlists and old snapshots name a type that no longer exists. Binding the existing types to
  levels changes nothing a book already has.
- **Keeping act and chapter as built-ins for new projects.** Every "is this a container" test
  then needs a list, a third level needs a third type, and a container's level is decided by
  the type the author picked rather than where it sits.
- **Numbering by type, or by the `number` field's scope.** One container type spans the levels,
  so counting by type would number acts and chapters as one sequence, and a field scope is one
  setting for every level; the numbering mode belongs to the level.
- **A per-node level field.** Depth already says it; a field could disagree with the depth.
- **A live level name in the display.** Authored titles ("The Beginning") would give way to the
  level name wherever the base template used it.
- **Keeping `research:topic` as research's container type.** "Topic" is what a research
  container is called, the way "Act" is what a manuscript container is called; naming the type
  after one level's name is the act/chapter mistake in a smaller tree.
- **One migration step for both slices.** Two steps let each slice ship whole; each runs once per
  project.

## Consequences

- **A move is one file write** (plus, rarely, a renumber of that sibling group). A rename is one
  file write. The title is stored once.
- **Files are the truth for the tree too.** Git, sync tools and a text editor can move a scene.
  #2170's refresh makes the tree follow them.
- **ADR-0045's concurrent-open hazard for the structure document** (two opens overwriting each
  other's tree file) goes away with the file.
- **Backend:** `TreeStructureService` becomes a read-only builder over the index; the manuscript
  and research mixins' create/move/rename/delete become node-file writes plus placement;
  `move_lore_note_to_research` writes placement; new-project creation writes no tree file;
  `_update_scene_title_in_structure`, `_update_research_title_in_structure`, the loose-scene
  methods and routes, and the unused `_is_scene_id` helper (`ai/helpers.py:852`) retire.
- **Frontend:** the id bridge in `structureToEvalNodes` collapses (`id` and `ref_id` are one
  value, which also fixes hand-picked view matching against scene ids, `evaluateView.ts:793`);
  the Import documents entry and modal retire; the create menu reads the level list; project
  settings edit it; the plot board draws any depth.
- **Validation** gains §5's warnings and loses "Structure references missing scene".
- **A book that mixes types at one level renumbers**, because numbering follows the level: a
  numbered chapter among the acts is counted with them. The fix is a sub-type whose template has
  no `{number}`.
- **New projects' AI outline** reads `<container level="Act">`; a user template that tests a
  container's type by name must test `level` instead. No built-in does.
- **Research containers become ordinary nodes:** openable, with fields, and sub-typable through
  the schema panes.
- **Docs:** `docs/getting-started.md` (walks the author through Act → Chapter → Scene),
  `docs/schema-yaml-howto.md` (the container sub-typing section, already stale),
  `docs/prompts/helpers.md` (the structure yaml walk, `.entry_type` values),
  `docs/prompts/reference.md`, and `docs/research-strategy.md`, `docs/project-brief.md`,
  `docs/metadata-strategy.md` where they describe the structure files.
- **Tests:** about thirty backend and a dozen frontend test files build trees through the yaml
  or name the two container types; they move to building trees through placement.

## Slices

1. **S1 — placement on the files.** §1–§6 and v12, with research topics made openable: the keys
   and the write-path rule, rank and renumbering, the index fields, signature and snapshot, the
   tree built from the index, one id space, the loose-scene retirement, placement excluded from
   revision, session boundary and restore, the §5 warnings except the level one, and the
   frontend changes one id space needs. It cannot be split further: the id space cannot switch
   in halves.
2. **S2 — the level list.** §7, §8 and v13: the container type, the `is_a` tests, the level list,
   its validation and its editor, the create menu, auto-titles, level labels, numbering by
   level, `full_outline`, §5's level warning and the refused deep move, the docs.
3. **S3 — the plot board by level.** §9.

One lane, in order: S2's levels are depths in S1's tree, and S3 draws S2's levels.

## The journey that defines done

1. The author opens a book made before this change. It migrates. The Draft tree reads exactly as
   before — Act 1, Chapter 1, the same scenes in the same order — and so do the plot board and a
   chat whose context picks included Act One.
2. They drag Chapter 3 above Chapter 2. In the project folder one file changed, by one line:
   Chapter 3's `rank`. Chapter 3 was open in a pane; they keep typing, and it saves without a
   conflict.
3. In Explorer they delete a scene, then switch back to the app. The scene is gone from the
   Draft tree; no row says it is missing. They delete a chapter's file; its scenes appear at the
   top level, and Verify names each one and why.
4. They copy a scene file into `scenes/` with `parent:` set to a chapter's id and switch back. It
   is at the end of that chapter.
5. In project settings they add "Sequence" after "Chapter". Creating inside a chapter now offers
   "New Sequence"; the new container is titled "Sequence", shown as "Sequence 1"; the plot board
   draws it as a box inside the chapter. Creating inside a sequence offers scenes, not
   containers, and dragging a chapter that holds sequences into another chapter is refused.
6. They set Chapter to continuous. Act 2's chapters read Chapter 3, Chapter 4.
7. They try to remove "Sequence" while sequences exist, and are told how many first.
8. They add a Prologue sub-type whose template is `{title}` and put one before Act 1. The acts
   are still Act 1, Act 2.
9. A new project offers "New Act" at the top and "New Chapter" inside an act; its schema has one
   container type.
10. In Research they open a topic itself: it is a file, with its own fields. A new project's
    research tree offers notes, not topics, inside a topic; adding a second "Topic" entry to its
    level list lets topics nest one deeper. An existing project whose topics already nest keeps
    them nested.
11. They restore an old snapshot of a scene they have since moved to another chapter. The text
    goes back; the scene stays where it is.

## History

Written from a design conversation on 2026-09-24 that started at the scene half of #2170's
deletion work: a scene deleted outside the app left a dead row in the Draft tree, because the
tree lives in a file the index does not read. Anton pointed at #217 and noted it does away with
the structure files for research too. Sibling order was weighed as a linked list (Anton's first
idea) against a number between the neighbours; the comparison under outside edits, merges and
crashes decided it, and Anton asked for a renumbering mechanism, which became §2's upward,
last-first renumber. Anton then observed that with the tree on the files, acts and chapters need
not be types, and that a level list would name them — with the UI never offering a level beyond
the list, and the plot board nesting by level. A pass over the code corrected four assumptions:
the Import documents dialog is the loose-scene import; research drag-and-drop already works;
snapshot restore rewrites front matter wholesale; container tree ids are persisted in views, the
plot board, chats and reference fields. Two cold implementing threads then planned the slices.
The first found that every typed save drops unknown front-matter keys, that a move would turn
an open pane's next save into a conflict and suppress the session snapshot, that the index
snapshot must carry placement, that a renumber which skips the moving node is not crash-safe,
and that placement declared as schema fields would reserve the names on every kind. The second
found that folding act and chapter into one type loses customisations and renumbers mixed
books; Anton chose to let a level name its type, new projects born with the container type only
and existing books keeping act and chapter as its sub-types; set numbering per level with his
two modes, restart and continuous; and agreed that titles stay as written. On research he
settled that the tree has two kinds of node, a container and a note — the research equivalent of
the scene — and that the container's type is `research:container`, calling the `research:topic`
name a long-standing bug; research takes the manuscript's level list as it is.
