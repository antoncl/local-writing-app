# ADR-0097: A card lives in a deck, shows its scene once written, and has a place in story time

- **Status:** Proposed — 2026-10-01. Text by Claude from a conversation with Anton on 2026-10-01,
  which started from his dogfooding of the plot board after #2361 made a card's synopsis
  readable. He asked for two things: a named container for cards that are not scenes ("a
  character's backstory"), and for a written card's board text and its scene's summary to stay
  in step. Every decision below was put to him in that conversation and answered; the interaction
  was tried in a mockup (`docs/design/mockups/0097-decks-and-story-time.html`). Revised against a
  cold implementing thread before review.
- **Feature:** #2373 (this record). Implementation issues are filed per slice (§11) after approval.
- **Amends:**
  - ADR-0048 §1 and Goal 3 — cardinality becomes **0..1 card per scene** (was 0..n). One ground of
    ADR-0048's rejected alternatives ("card:scene must be n:1") goes with it.
  - ADR-0048 §3 — cards land "directly (planned, unwritten), or in a backstory lane": built here
    as planned cards and decks. Order becomes story-meaningful and moves onto the card, the
    amendment §3 asks for. The board stops storing card positions, and dragging a box is
    presentation, not a structure move.
  - ADR-0048 anti-goal 4 — narrowed (§8).
  - ADR-0053 — the 0..n cardinality and the #874 container lock it says "stand" (header, §Non-goals)
    are replaced; realize's undo deletes the scene whenever it created it, since the card is now
    always its sole referent.
  - ADR-0080 — the same two "stand" clauses (header, §Non-goals).
  - ADR-0094 §9 — every container draws a box, not only those holding cards (§8).
- **Relates to:** ADR-0094 §1/§2/§6 (the rank rules and the revision exclusion story time reuses);
  ADR-0071 (the v15 migration, §10); ADR-0050 (undo carries ids); #2365 (the Beat sequence layer
  removed, which is how ordering came up); #2362 (card height estimate, untouched).
- **Words used here.**
  - A **deck** is a named, plot-only container of cards (`plot:deck`): "Mara's backstory",
    "Ideas". It is not a manuscript container and creates nothing in the manuscript until it is
    realized (§7). *Not* "group": that word is the schema's field groups (`item_group`,
    `GroupsManagerDialog`).
  - A **written** card has a scene (`metadata.scene`). An **unwritten** card has none.
  - A **planned** card is an unwritten card placed inside a manuscript container (§6): it has a
    position among the scenes there, and no scene.
  - A card's **home deck** is its `plot_deck` field. A written card keeps it; it is where the card
    returns when its scene is detached.
  - **Story time** is the order in which things happen in the story's world — "the fire" happens
    before "Mara arrives", however late the fire is told. *Not* "timeline" or "chronology": those
    words are the mutation timeline and the snapshot time axis (ADR-0088).
  - **Manuscript order** is the order scenes are read in (ADR-0094's tree order).
  - A **box** is the rectangle a deck or a manuscript container draws on the board.
  - A card's **place** is where it shows: its scene's container, its planned container, its home
    deck, or the loose area.
- **Verified against `da9a9e4c` (2026-10-01).** Symbols first, line numbers second.

## Problem

The board cannot hold what a writer plans before they write it, and once it is written the board
and the manuscript describe the same scene twice.

1. **Unwritten cards have nowhere to go.** A card's box is its scene's innermost container: the
   projection maps scene → container (`_board_container_map`, `plot_board.py:269`;
   `read_plot_board_projection` `:161`, container chosen at `:231`) and a card with no scene is
   "homeless", gridded below every box (`buildBoardNodes`, `plotBoardLayout.ts:417`, homeless
   bucket `:432-438`, laid out `:499-505`). ADR-0048 §3 planned "directly (planned, unwritten), or
   in a backstory lane"; neither was built. Backstory, alternatives and ideas sit in one unnamed
   heap.
2. **Order means nothing.** Cards inside a box come in **title order**: the backend lists plot
   nodes sorted by `(title.lower(), id)` (`_list_plot_folder_nodes`, `plot.py:205`) and
   `buildBoardNodes` keeps that order (`:429`). A dragged card keeps its stored position
   (`readBoardPositions`, `plotBoardLayout.ts:702`), so position is a pile, not a sequence. The
   removed Beat sequence layer (#2365) was the only ordering a writer was offered, and it could not
   be set.
3. **Two texts for one scene.** Realize copies only the title (`realize_card`, `plot.py:745`). The
   card's body stays "the plan" and the scene's `summary` (`default_schema.py:233`, on
   `manuscript:base`) starts empty. Nothing connects them afterwards, in either direction:
   `plot*.py` never reads `summary`. "Summarize scene" (`builtin_library/prompts/summarize-scene.md`)
   writes a summary the board never shows.
4. **Several cards per scene makes (3) unanswerable.** ADR-0048 §1 allows 0..n cards per scene
   (`default_entry_types.py:298-299`; only realize's 409 at `plot.py:757-761` limits the other
   direction). One summary cannot be the synopsis of three cards.

## Goals

1. **Name a place for unwritten cards.** A writer makes a deck, names it, puts cards in it, nests
   decks, and sees each deck as a box on the board.
2. **One kind of box.** A deck and a chapter look and behave alike on the board. A chapter is a
   deck that has been *realized*, the same way a scene is a card that has been realized.
3. **Try a card in a chapter without writing it.** Dropping an unwritten card into a chapter plans
   it there; the writer can move it around freely. A scene is created only on an explicit
   *Write as scene*.
4. **One text per written card.** Once a card has a scene, the card shows the scene's title and
   summary, and editing either on the board edits the scene.
5. **Three orders, each set where it lives.** Story time (set by the writer, relative), cause (the
   existing causal links), manuscript order (the tree). Inside a deck cards read in story time;
   inside a chapter, in manuscript order.
6. **Catch a cause that happens after its effect.**

## Anti-goals

1. **Not a time engine.** Story time is a relative order — before and after. No dates, durations,
   calendars or "Day 3" values, and no `date` field type. Invented calendars and "years earlier"
   do not fit a time value; they fit before and after.
2. **Not free placement of cards.** Cards flow in order inside a box; only top-level boxes,
   plotlines and arcs are positioned freely. A card is never dragged to an x/y that means nothing.
3. **Not arrows for order.** Story time is set by reordering, never by drawing edges. No story-time
   edge layer in this ADR.
4. **Scenes still grow no planning fields** (ADR-0048 anti-goal 1). The sync writes the scene's own
   `title` and `summary`, fields every scene already has. Planned positions and decks live on the
   card and the deck, never on a scene or a container.
5. **Placing is not writing.** No drop, drag or deck realize ever creates a scene. Only *Write as
   scene* does.
6. **No silent loss of a synopsis.** No step — migration, attach, detach — discards a card's text
   or a scene's summary without the writer choosing it.
7. **Not a second container system in the manuscript.** A deck is a plot node; it becomes a
   manuscript container only through realize (§7), and the manuscript never learns decks exist.
8. **Not `plot` as a tree kind.** Decks nest through a reference, not ADR-0094 placement (§2 says
   why).

## Decision

### 1. One card per scene

A scene is realized by **at most one card**; a card by at most one scene. Every write that can give
a card a scene — realize, attach (§4), create-with-id (undo restore), snapshot restore — refuses or
drops a scene another card already holds: realize and attach answer 409, the shape of realize's
existing refusal (`plot.py:757-761`); a restore keeps the card and drops its `scene`, with a
warning. Seed-from-manuscript already adds at most one card per uncarded scene
(`seed_cards_from_manuscript`, `plot.py:772`) and is unchanged.

The card's `scene` field becomes **endpoint-owned**: a card save keeps the value on disk and
ignores the client's, so the only ways to set or clear it are realize, attach and detach. Today the
rail's generic `scene` picker (`default_schema.py:588`) is the only attach UI; it becomes a
read-only link, and the board gains an Attach picker (S2) that offers only scenes no card holds.

ADR-0048 Goal 3 ("a climax that pays off three threads is three cards, one scene") survives as
**one card, several beats**: `beat_links` already holds any number of `{plotline, beat_id}` items
across plotlines (`plot_beat_link`, `default_schema.py:142`). What goes is three separate synopses
for one scene; with one summary per scene that was never going to stay true.

*Rejected: keeping 0..n and syncing only single-card scenes.* It makes the sync rule depend on a
count the writer cannot see, and a second card attached later would silently stop a working sync.

### 2. A deck is a plot node, and decks nest by reference

`plot:deck` is a new entry type under `plot:base`: a title, a body (its synopsis), and two
optional references:

- `plot_deck` — its parent deck (`entity_ref` to `plot:deck`). Absent = top level. A save that
  would make a deck its own ancestor is refused (422).
- `realized_container` — the manuscript container it is realized as (`entity_ref` to
  `manuscript:container`), §7. At most one deck per container, refused like §1. Endpoint-owned
  like a card's `scene`.

A card gains `plot_deck` (`entity_ref` to `plot:deck`), its home deck, editable in the rail. The
names carry a prefix because a field id is shared by every entry type, and `deck` or `container`
would collide with a writer's own fields. Decks live in `plot/` like every plot node.

Deleting a deck deletes only the deck: the existing reference purge (`_purge_references_to`,
`metadata_values.py:1105`, run by `_delete_plot_folder_node`) clears it from its cards and child
decks, so its cards fall to the loose area and its child decks to the top level. No card is ever
deleted with a deck.

*Why a reference and not ADR-0094 placement:* placement's `rank` orders **siblings** under one
parent (`build_tree`, `tree_build.py:95`), and story time orders **every card across every deck**
(§5). Making `plot` a tree kind (`TREE_KINDS`, `placement.py:35`) would give each card a sibling
rank that means nothing, beside the story-time rank that does — two orders on one card, one of them
noise.

### 3. A written card shows its scene

While a card has a scene, **the card's displayed title and synopsis are the scene's `title` and
`summary`.** One reader produces them. Today the board projection (`read_plot_board_projection`,
`plot_board.py:242`) and the board's AI context packet (`plot_context.py:287`, "Project one
admitted card for the AI") read `card.body`; both move to the reader.

The card **node** is unchanged: `read_card` and `CardEntry` still carry the card's own title and
body, so `entry(card)` in a prompt, search, and undo snapshots all see the card's own text.
While the card is written that text is **frozen**:

- `save_card` refuses a title or body change on a written card (422), so a stale client, a
  plotline reassignment that resends the body, an AI commit, or a search Replace cannot write text
  nobody sees. Search's Replace skips a written card's body.
- The card's editor shows its own body read-only, labelled as the synopsis from before it was
  written, with a link to the scene — so a plan that differed from the summary stays readable.
- Editing a written card's title or synopsis on the board goes through one endpoint,
  `PUT /api/plot/cards/{id}/text` with `{title?, synopsis?}`, which writes the **scene** through
  its own save and rename paths (rename: `rename_structure_node`, `manuscript.py:236`). On an
  unwritten card the same endpoint writes the card. The board's undo for that edit records the
  scene's before and after, not the card's.

The moments text moves:

| Event | Title | Synopsis |
| --- | --- | --- |
| **Write as scene** (realize) | the scene takes the card's (as today) | the new scene's `summary` is the card's body |
| **Attach**, scene summary empty | the card shows the scene's | the summary becomes the card's body |
| **Attach**, both non-empty and different | the card shows the scene's | the writer chooses: keep the scene's summary, or use the card's synopsis |
| **Detach**, card body empty or equal | the card takes the scene's | the card's body becomes the summary |
| **Detach**, both non-empty and different | the card takes the scene's | the writer chooses: keep the card's old synopsis, or take the summary |

The same rule holds for a realized deck (§7): its box shows the container's title and summary, and
the deck's own text is frozen while it is realized.

*Rejected: copying once at realize and never again.* That is the drift the writer reported.
*Rejected: `CardEntry.body` becoming the summary.* Every client that resends the body on an
unrelated save would write a stale summary over a fresh one.
*Rejected: the scene reading the card.* It puts the plan into the manuscript's data path (anti-goal
4) and breaks a scene with no card.

### 4. The card endpoints

| Endpoint | Body | Does |
| --- | --- | --- |
| `POST /api/plot/cards/{id}/attach` | `{scene_id, text?: "scene" \| "card"}` | §1's check, §3's text rule; clears planned fields |
| `POST /api/plot/cards/{id}/detach` | `{text?: "card" \| "scene"}` | clears `scene`, §3's text rule |
| `POST /api/plot/cards/{id}/realize` | `{parent_id?}` (existing) | §3's text rule; from a planned card, §6 |
| `PUT /api/plot/cards/{id}/text` | `{title?, synopsis?}` | §3 |
| `POST /api/plot/cards/{id}/place` | `{to, story?}` | §5, §6 |

`text` is required only when §3 says the writer chooses. When it is missing there, attach and detach
answer 409 with `code: "text_choice_required"` and both texts, and the board asks. Every endpoint
returns the card's `CardEntry`. Detach becomes a backend operation; today it is a frontend metadata
save (`detachCardScene`, `stores/plotBoard.ts:189`).

`place` is the one write for where a card shows and where it sits in story time:

- `to` is one of `{deck: id}`, `{loose: true}`, `{planned_in: id, planned_after: id | null}`, or
  absent (story time only, the Story time view).
- `story` is `{after_id}` or `{before_id}` — the neighbour the card lands next to. A drop at the
  start of a box sends `before_id` of the box's first card, so it lands before that card and not
  at the start of the whole story.
- A written card accepts only story time; any `to` is a 409 ("it shows by its scene").

`CreateCardRequest` gains the same optional `to`, so a card created in a deck or a chapter is
placed there, right after the last card of that place in story time (or at the end of story time
when the place is empty).

### 5. Story time is a rank on the card, kept like placement

A card's story time is `story_rank`, a number in a **top-level front-matter key outside
`metadata`**, as ADR-0094 §1 keeps `parent` and `rank`. It is not a schema field, has no rail row,
and is handled like placement:

- **Owned by the backend.** A card save keeps the value on disk and never takes the client's;
  `place` is the only writer. Create-with-id (undo restore of a deleted card) may carry the rank it
  had, so undo puts the card back where it was.
- **Not content.** It is excluded from the save revision, as `content_without_placement`
  (`placement.py:60`) excludes `parent`/`rank`, so a story-time move — or a renumber that touches
  every card — never turns an open card pane's next save into a 409. A snapshot restore keeps the
  card's current rank.
- **Ordered by the ADR-0094 §2 rules.** Ascending rank, ties by id, missing rank last
  (`rank_sort_key`, `placement.py:144`); a new rank is the shortest decimal between the neighbours
  (`rank_between`, `placement.py:165`); when none fits, the layer's cards are renumbered upward.

**Layers.** Plot is a layered kind (`node_families.py:49`), so a book's board shows inherited
cards. Story time ranks **the cards the open layer owns**. Inherited cards cannot be moved in story
time from a descendant layer (their files are not this layer's to write), and a renumber never
touches them. In every story-time sequence they read **after** the open layer's own cards, nearest
layer first, each layer in its own order. That is an honest limit, not a design: ordering an
inherited card among a book's cards needs a per-layer order, which this ADR does not add.

Where order shows:

| Place | Cards read in |
| --- | --- |
| a deck | story time |
| the loose area | story time |
| a manuscript container | manuscript order, planned cards among the scenes (§6) |
| the Story time view (§8) | story time, every card |

*Why a number and not "after card X" links:* a chain breaks when a card is deleted and needs a walk
to sort; a rank sorts directly, and the renumbering rule is already written and tested.

### 6. A planned card has a position in a container, and no scene

An unwritten card gains two optional, endpoint-owned references, hidden from the rail:

- `planned_in` — the manuscript container it is planned in (`entity_ref` to `manuscript:container`).
- `planned_after` — the scene it follows there (`entity_ref` to `manuscript:scene`). Absent = first
  in the container.

A planned card shows in `planned_in`'s box, right after `planned_after`. Several planned cards
after the same scene read in story time among themselves, so a drop between two of them also sets
story time between them (`place` with both `to` and `story`). If `planned_after` is not currently a
child of `planned_in` — the scene moved, or was deleted and the purge cleared it — the card shows
first in the container: never lost, never hidden.

**Write as scene** on a planned card creates the scene in `planned_in`, right after
`planned_after`, through the existing create and move paths (`create_structure_node`,
`manuscript.py:249`; `move_structure_node`, `:229`), sets `scene`, applies §3's text rule and clears
both planned fields. Then every other planned card that was after the same scene **and** later in
story time is re-anchored after the new scene, so writing cards one by one never reverses the order
the writer set. On an unwritten card that is not planned, Write as scene keeps today's behaviour
(realize with an optional `parent_id`).

### 7. A deck is realized into a manuscript container

**Realize as \<level name\>** on a deck creates a manuscript container titled as the deck, whose
`summary` is the deck's body, and sets the deck's `realized_container`. It is created under the
parent deck's container when the parent is realized, otherwise at the top of the manuscript; a
level the project's level list does not allow there is refused (ADR-0094 §7's bound on creation).
Then:

- every unwritten card whose home deck is this deck becomes **planned** in the new container, in
  story-time order. **No scene is created** (anti-goal 5).
- written cards are untouched; they already show by their scenes.
- child decks stay decks and show inside the new container's box.

**Detach** on a realized deck clears `realized_container`; the container stays in the manuscript,
and its planned cards stay planned in it. The deck's text follows §3's detach row.

### 8. The board: boxes are placed, cards flow

- **Every manuscript container draws a box**, at every depth, whether or not it holds cards — an
  empty chapter must be something a card can be dropped into. (ADR-0094 §9 said a top-level
  container always draws; the code draws only containers holding cards.)
- **A deck's box** nests inside its parent deck's box, or inside its parent's container box when
  the parent is realized. A box shows its title and the first two lines of its synopsis.
- **Inside a box**, child boxes come first (containers in manuscript order, then decks by title),
  then cards in the place's order (§5).
- **Positions.** Only top-level boxes, plotlines and arcs are positioned, freely, keyed by node id
  in `plot:board`'s `layout.positions` (`PlotBoardLayout`, `plotBoardTypes.ts:201`). A new
  top-level box lands at a free spot (`freeSpotNear`, `plotBoardLayout.ts`). Nested boxes do not
  drag. Dragging a box is presentation; it never moves the manuscript. Boxes size to their
  contents: `layout.sizes` (#878) retires, and card positions already stored are ignored and dropped
  on the next layout write.
- **The loose area** holds unwritten cards with no home deck and no plan, and written cards whose
  scene sits directly under the manuscript root.
- **Drag a card between two cards** — an insertion bar shows where it lands — and the board calls
  `place`:
  - into a deck or the loose area: an unwritten card takes that home deck (or none) and the story
    time between its new neighbours there. A written card is refused with a line saying it shows by
    its scene.
  - into a manuscript container: an unwritten card becomes planned there, after the nearest
    preceding scene in the box. A written card moves its scene to that position: a real structure
    move through `move_structure_node`.
- **Card menu:** Earlier in story time · Later in story time · Place after… (a card picker) · Attach
  scene… or Write as scene (unwritten) · Detach scene (written). Drag is never the only way to set
  an order.
- **Deck menu:** New card · New deck inside · Realize as \<level name\> (or Detach) · Rename ·
  Delete.
- **The Story time view** is a second view of the board, chosen by a Board | Story time toggle. It
  shows every card in one wrapping sequence in story time, each with its place (scene number, deck,
  or "Planned in …"). Dragging there changes only story time.
- **The late-cause flag.** A causal link whose cause comes after its effect in story time marks the
  effect card ("Cause is later") and the edge. It **replaces** both checks that compare manuscript
  order today: the board's `outOfOrder` (`buildBoardEdges`, `plotBoardEdges.ts:118`, causal layer
  `:151-187`) and the `causal_inversion` diagnostic (`_causal_inversions`, `plot_diagnostics.py:51`,
  "the payoff is read before its setup"). Telling a cause after its effect is an ordinary technique
  — a mystery does nothing else — while a cause *happening* after its effect is almost always a
  mistake.

ADR-0048 anti-goal 4 ("No timeline engine, for now") is narrowed, not dropped: story time is an
order, not an engine, and the lanes-and-columns grid stays out.

### 9. What the board stores

`plot:board` keeps the viewport and the positions of top-level boxes, plotlines and arcs. It stores
no card position and no order: story time is on the card (§5), manuscript order is the tree, home
decks and planned positions are on the card (§2, §6).

### 10. Migration v15

A `RootMigration` (`migrations.py:97`), `CURRENT_VERSION` 14 → 15 (`:66`), run per layer on the
layer's own files:

1. **One card per scene.** For each scene held by more than one of the layer's cards, the card
   whose id sorts first keeps it; the others lose `scene` and become unwritten. Nothing is deleted,
   and every card keeps its body.
2. **Seed story time.** `story_rank` = 1..n over the layer's cards: written cards in manuscript
   order (the v12+ `parent` and `rank` on disk), then unwritten cards by `(title.lower(), id)` —
   today's board listing order, so nothing jumps.
3. **Seed the summary.** For each written card whose scene's `summary` is empty and whose body is
   not, the summary becomes the body. Where both are non-empty and differ, both are left as they
   are: the board shows the summary, the card's editor still shows its old synopsis (§3), and
   detach asks. Without the seed, every synopsis written before this ADR would vanish from the
   board.

`plot_deck`, `planned_in`, `planned_after` and `realized_container` are new optional fields and need
nothing. A snapshot from before v15 is restored through §1's check.

### 11. Slices, in order

Each slice is one PR; one lane.

**S1 — One card per scene, and story rank (backend).** §1's checks and endpoint-owned `scene`; §5's
key, ownership, revision exclusion, layer rule; `place` with story only; §10. *Done when:* attaching
a scene another card holds is refused; an existing project opens at v15 with every card ranked, and
every written card whose scene had no summary still shows its synopsis. *Not:* any board change.

**S2 — A written card shows its scene.** §3 and §4's attach, detach and text endpoints; the board's
Attach picker; the rail's `scene` read-only. *Done when:* the writer runs "Summarize scene" and the
card on the board shows the new summary; edits the synopsis on the card and sees it in the scene's
rail; reassigns the card's plotline without the summary changing; detaches and the card still reads
the same. *Not:* changing the card's layout.

**S3 — Story time.** §8's Story time view, the card menu's story-time items, Place after…, the
late-cause flag replacing `outOfOrder` and `causal_inversion`. *Done when:* the writer opens Story
time, drags a flashback card before the arrival card, switches back to the board, and the
late-cause flag on a mis-ordered link disappears once the cause is dragged before its effect. *Not:*
a story-time edge layer; dates.

**S4 — Decks.** §2; §8's boxes for decks and every container, flowing cards, drag between cards in
decks and the loose area, the deck menu (minus realize). The new entry type joins the per-type plot
dispatches: `_read_plot_node` (`node_ops.py:120`), `_read_by_kind` (`ai/entry_ref.py:101`),
`_replace_dispatch_for` (`search_replace.py:325`), `PLOT_ROOTS` (`stores/editorPaneOpen.ts:474`),
`paneDocType` (`stores/editorPaneReconcile.ts:59`), `PlotBoardRevealKind` (`stores/plotlines.ts:18`),
`treeActions.svelte.ts:106`, and `_list_plot_folder_nodes` (`plot.py:175`). *Done when:* the writer
makes "Mara's backstory", drags three cards into it in the order they happened, nests "Childhood"
inside it from the deck's rail, and reloads to find all of it as they left it. *Not:* drag-to-nest
boxes; realize.

**S5 — Planned cards.** §6; §8's drag into a container; Write as scene from a planned card with the
re-anchoring; a written card's drag moving its scene. *Done when:* the writer drags an idea into an
empty Chapter 2, then into Chapter 3, writes two planned cards in Chapter 3 one after the other, and
finds both scenes in Chapter 3 in the order the cards showed, each with its card's synopsis as its
summary. *Not:* creating a scene on drop.

**S6 — Realize a deck.** §7. *Done when:* the writer realizes "Act 3 ideas" as an act and finds an
act of that name in the manuscript, with the deck's cards planned in it and no scenes created.
*Not:* realizing the deck's cards.

## Consequences

- The board stops being a canvas of cards and becomes a canvas of boxes holding ordered cards.
  Cards dragged into place before this ADR lose their positions and flow; the overlap #2361's
  larger cards caused goes with them.
- Writers who used several cards on one scene lose that shape; v15 detaches the extras and changes
  nothing else about them. No project the author knows of uses it.
- Story time on a book board cannot interleave inherited cards with the book's own (§5). If series
  planning needs that, it is its own decision.
- Story time is story data, so a later AI-context or diagnostics change can read it; nothing in this
  ADR adds it to the AI packet.
- The `plot` kind keeps a flat folder. A deck tree is walked by following `plot_deck` links, not by
  the ADR-0094 tree builder.

## Open

- Whether a box's synopsis expands in place or opens the deck's editor is a detail for S4's
  eyeball, not a decision here.
