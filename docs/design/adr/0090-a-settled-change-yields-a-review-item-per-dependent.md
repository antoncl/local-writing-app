# ADR-0090: A settled change yields a review item per dependent; the app proposes and never writes them

- **Status:** Accepted — 2026-09-22, Anton Lauridsen; text drafted by Claude from a design
  conversation, corrected once in that conversation (mutations put on the story-time axis, the
  built-in prompt dropped, the confirm surface named as the one mocked surface), approved in it,
  landed as Accepted in PR #2114. Acceptance alone starts nothing: each slice gets its own issue
  and an explicit go.
- **Feature:** keeping related lore entries consistent when one of them changes (no issue yet;
  this ADR is the artifact the issue will cite).
- **Relates to:** ADR-0046 (an AI lore edit is a reviewable patch the writer adopts — the stance
  this ADR extends to dependents), ADR-0081 (references at any depth — the one traversal the
  reverse index is built from), ADR-0089 (relationships as reference-keyed items — a declared
  dependency needs no new field), ADR-0075 (implicit context — the name matcher that finds prose
  mentions), ADR-0087 (a snapshot freezes the owning layer's file — the baseline a change is
  measured from), ADR-0051 (a node owns its conversations — Propose opens one), ADR-0039 (layer
  overrides — the save a review ends in follows them), ADR-0001/0006 (scene-authoritative markers,
  resolver-mediated lore — why a scene's *view* of an entry is never a dependent, and why its
  markers are), #66 (the mutation-set sibling of this problem, deliberately out of scope),
  ADR-0071 (the migration ladder — this ADR owes none and says why).
- **Words used here.** The *source* is the entry that changed. A *dependent* is a node that may
  need to follow: a lore entry, or a scene. A *candidate* is a dependent the app proposes before
  the writer decides. A *review item* is the todo written for a candidate the writer keeps. The
  *baseline* is the snapshot the change is measured from. *Propagate* is the writer's action; the
  word is used in its plain sense elsewhere in the code and nowhere as a term of art. A
  *mutation* keeps ADR-0001's meaning: a story-time record a scene holds about a lore field.
  Propagation is an edit-time concern; the two never meet except that a marker can be a
  dependent. Nothing here is called a "stale" flag, a "link", or a "rule": each of those names a
  rejected shape (§Why).
- **Verified against `723c2dac` (2026-09-22).** Symbols first, line numbers second; the numbers
  rot, the symbols do not.

## Problem

A writer changes one lore entry and the change is not local. Marek stops being captain of the
guard; the guard's roster still names him, his daughter's entry still calls him "the captain",
and the tavern he drinks at still describes the captain's usual table. The writer knows some of
these follow-ups and forgets others, and the forgotten ones surface months later as contradictions
in the prose or in what the AI is told.

Nothing in the app helps today, and nothing in it hinders. The pieces that would help exist
separately:

- **Who points at whom is indexed, in both directions.** The node index keeps forward edges per
  layer and rebuilds a reverse map in `NodeIndex.rebuild_reverse_edges`
  (`backend/app/services/project/node_index.py:414`, `edges_by_dst` at `:183`) from the single
  occurrence walk ADR-0081 introduced (`ref_members`,
  `backend/app/services/project/metadata_refs.py:86`; `iter_ref_occurrences`, `:168`). Those
  edges are metadata-only. No body is scanned for references into the index.
- **Who mentions whom by name is found, but only for the AI.** ADR-0075's positional matcher
  (`compile_name_matcher` / `scan_name_matcher`, `backend/app/services/ai/name_matcher.py:72` /
  `:101`) and its lore-selection consumers (`_alias_match`,
  `backend/app/services/ai/lore_selection.py:426`; `_scene_prose_ids`, `:555`) find an entry's
  title and aliases in prose and in `long_text` fields, ephemerally, per send.
- **Which scenes hold a mutation on an entry is indexed, by entity and field.** A marker
  targets `(entity, field)` (ADR-0001); `entity_mutations`
  (`backend/app/services/project/lore_mutations.py:545`, behind
  `GET /api/lore/{entity_id}/mutations`, `backend/app/routers/lore.py:64`) lists every marker
  that addresses an entry. A scene's *view* of the entry needs nothing from this ADR: the
  resolver folds the base and the markers as of the scene (ADR-0006), so a base change reaches
  every scene the moment it is saved. What the resolver cannot do is notice that a marker on the
  changed field now contradicts, or repeats, the base it was written against.
- **An AI edit to an entry is already a reviewable patch.** ADR-0046's chat commits a whole-entry
  patch, parsed by `parse_entry_patch_json` (`backend/app/services/ai/entry_patch.py:131`),
  validated per field by `ProjectService.validate_ai_entry_patch`
  (`backend/app/services/project/metadata_values.py:470`), extracted by
  `run_entry_patch_extraction` (`backend/app/services/ai/extraction.py:253`) behind
  `POST /api/ai/entry-patch/{node_id}` and `.../extract` (`backend/app/routers/ai.py:801`,
  `:829`). The adopted result is written by the ordinary save, `PUT /api/lore/{entry_id}`
  (`save_lore_entry`, `backend/app/services/project/lore.py:184`), which routes by authoring
  layer. Nothing server-side ever applies a patch. A prompt asks to be offered this way with
  `output.handler: extract_to_node` plus a `commit` block (`prompt_disposition`,
  `backend/app/services/project/prompt_disposition.py:60`).
- **A todo is the app's unit of deferred work, and nothing mints one.** `TodoItem`
  (`backend/app/models/annotations.py:8`) carries `id`, `text`, `status`, `scope`
  (`project` | `scene`), `scene_id`, `anchor_id`. `TodosMixin.create_todo`
  (`backend/app/services/project/todos.py:28`) is the only place one is built, from a user
  request. The automatic paths only prune (`lifecycle.py:1225`, orphaned scene anchors).
- **A node's history is a snapshot store that is already kind-neutral.** ADR-0087 made the
  `(root, node_id, path)` byte-copy plus sidecar work for any authored node; `capture_snapshot`
  (`backend/app/services/project/scene_snapshots.py:514`) takes `kind`, and
  `maybe_capture_session_boundary` (`:621`) already photographs the pre-save state on a session
  gap.

The gap is the middle: nothing turns "this entry changed" into "these entries may need to
follow", and nothing keeps that list across a session. The name matcher runs only when a chat is
sent; the reverse index answers only delete guards, cascades and the `tagged:` selector; the
todo list holds only what the writer typed.

## Intent

When the writer has settled a change to an entry, the app finds the entries and scenes that may
need to follow, shows them, and writes one review item for each the writer keeps. A review item
opens the dependent beside what changed in the source. From a review item the writer edits by
hand, opens the mutation dialog, or asks the AI in an ordinary conversation; a patch the AI
proposes is reviewed and adopted exactly as ADR-0046 already reviews and adopts. The app never writes a dependent on its own. That last sentence is the
decision; everything else is how it is reached with parts the app already has.

## Anti-goals

- **Not automatic edits.** No path in this ADR writes to a dependent entry except the ordinary
  save the writer commits after seeing a diff. Not with undo, not "obvious" cases, not renames.
  Whether a change in Marek's entry means anything for Ilse's is a judgement, and the app does
  not have it.
- **Not save-time detection.** The trigger is the writer's action, once, when the change is
  settled. A hub entry saved twenty times in a session would otherwise write twenty rounds of
  candidates, and the writer would mute the feature within the week. Detection on every save is
  the adjacent plausible path; it is forbidden here.
- **Not a rules engine.** No declared "when X changes, do Y to Z". A user cannot reasonably
  author those, and the judgement is not rule-shaped. A declared dependency, where the writer
  wants one, is an ordinary reference field on the dependent, which ADR-0089 already made
  authorable; the app reads it as one candidate route among three.
- **Not a mutation.** Propagation never creates, edits or closes a mutation. A marker on the
  changed field is a *candidate*, because the scene holding it is where the writer decides
  whether the story-time change still stands; the decision is made in the mutation dialog as
  ever, from the review item, by the writer. An app that "reconciled" markers against the new
  base would be writing story time from edit time, and that is the adjacent plausible path this
  bullet forbids.
- **Not a pointer model, not stamp provenance.** #66 (edit a mutation set once, propagate to
  every application) is the sibling problem, and the mechanism decided here is its non-pointer
  answer: a change to a set would yield review items on the scenes where it was applied. It is
  named as a second consumer and nothing more. Whether a stamped marker should remember which
  set it came from is #66's own storage decision, post-1.0, and this ADR does not pre-empt it.
- **Not a new node kind.** A review item is a todo with two more fields. It shows where todos
  show. A "review" kind would be the chat-as-node mistake in reverse: a special subsystem for
  what an existing node already models. The one new surface is the confirm step (§7); everything
  else composes shipped widgets.
- **Not a built-in prompt, not a prompt variable.** The AI pass is an ordinary conversation on
  the dependent with the change in its first message. The only thing the model needs that it
  cannot get today is the source *before* the change, and that is text. A structured `change`
  variable that a prompt could loop over is deferred until a writer hand-authors such a prompt
  and finds the message form insufficient; its shape is not sketched here.
- **Not retrieval.** Candidate detection is the reverse index plus the name matcher. A better
  detector is a later decision, as ADR-0086 said of lore selection.

## Decision

### 1 — The trigger is the writer's, and it measures from a baseline snapshot

An entry gains a **Propagate** action. Running it builds the candidate set (§2) against a
*baseline*: the newest snapshot of the source that a previous propagation captured, or, when
there is none, the whole entry treated as the change. The writer sees the candidates with their
reasons and the source diff, unticks what does not apply, and confirms. Confirming does two
things and nothing else: it writes one review item per kept candidate (§3), and it captures a
snapshot of the source through ADR-0087's store (`_capture` with `retention="kept"`), marked as
a propagation baseline by one additive, optional sidecar field naming its origin. The next
Propagate measures from that snapshot.

The baseline is a snapshot rather than a stored diff because the snapshot store is the app's
one notion of "the file as it was", it is already kind-neutral, and a snapshot the writer can
see in the foot dock (ADR-0088) is a baseline the writer can reason about. The origin field is
what lets the app find the right one without the writer choosing; the writer may still pick any
snapshot as the "since" when the default is wrong.

No candidate is written before the writer confirms. The read-only half (build the set, show it)
and the write half (items plus baseline) are two endpoints, so the preview costs nothing.

### 2 — Four candidate routes, each a named reason, built on the backend

The candidate set is computed by the backend from the node index and the mutation index, never
from the frontend's copy of the reference graph. Each candidate carries the route that found
it:

- **`references_source`** — the candidate has a reference-bearing field, at any depth, whose
  value is the source (`edges_by_dst`, canonicalised through tag merges as the index already
  does). A relationship item under ADR-0089 arrives by this route, with its field named.
- **`referenced_by_source`** — the source has a reference to the candidate (`edges_by_src`). The
  entry Marek's `posting` field points at is as likely to need a follow-up as the entries
  pointing at Marek.
- **`mutates_source`** — the candidate is a scene holding a marker that targets the source
  (`entity_mutations`), with the marker's field named. This is the one route that knows *which*
  field: a marker on a field the diff changed ranks with the declared routes above; a marker on
  an untouched field is listed after them. The candidate is the scene; the review item's anchor
  is the marker (§3).
- **`mentions_source`** — the candidate's body or a `long_text` field names the source's title or
  an alias, found with the same compiled matcher the AI path uses, over lore entries and scenes
  alike. The text scanned is the ADR-0085 search corpus (`CorpusEntry.body` and
  `metadata_values`, `backend/app/services/project/search_corpus.py:22`), which the node-index
  lifecycle already maintains for every node — a Propagate opens no files. This is the route
  that catches "her father the captain"; it is also the noisy one, and it ranks last.

Candidates are the lore entries of the index winner view at any layer, and the open book's own
scenes — scenes are book-scoped and never inherited (ADR-0039/0040), so there is no layer walk
for them. A node reachable by more than one route appears **once**, lists every route, and
ranks by the first. The source itself is not a
candidate, and neither is an entry the source merely names in its own prose: the question is
who depends on the source, and the source's declared references are the only outgoing route
counted. The set is a list of `(node, reasons)` and nothing else; no score, no threshold.
Ranking exists so the writer reads the declared ones first, not so the app can cut the list;
how the mention group is kept from burying the rest is the confirm surface's job (§7).

### 3 — A review item is a todo with a home and a source

`TodoItem` gains a third scope, `node`, with `node_id` naming a lore dependent, and an
optional `source` block: `{node_id, snapshot_id, reason, marker_id?}`. A scene dependent needs
no new scope: it uses the existing `scene` scope and `scene_id`, and **no anchor is written** —
a todo anchor is an HTML-comment range inside the scene body (`TODO_ANCHOR_PATTERN`,
`backend/app/services/project/scene_todos.py:19`), and writing one would be the app writing
the dependent. Instead the `source` block carries the marker's client-minted `marker_id`
(`MutationMarker`, `backend/app/models/annotations.py:59`) for the `mutates_source` route, and
nothing for a mention; opening the item locates the marker by id, or re-runs the matcher for
the first mention, live. `anchor_id` stays what it is today: the writer's own anchor, never the
app's. `text` is generated ("Follow up on Marek Vell's change") and stays editable. `status` is the existing `open` | `done`. Dismissing a wrong candidate is marking it
done; deleting it is deleting a todo. Nothing else is new on the model. `CreateTodoRequest`
accepts the same fields, so a writer can create a review item by hand against any node, with or
without a source. That is the authorable path the app's own items use, and it is why the review
item is a todo and not a kind.

A review item shows wherever todos show. Opening one opens the dependent — a lore entry on its
card, a scene scrolled to the marker or the first mention — and opens the source in a second pane parked on the baseline
snapshot in compare mode: ADR-0088's foot dock doing what it already does, read-only, with
nothing new drawn. The load-bearing part is that the writer never has to go and find what
changed.

The rail of an entry that has open review items lists them, in the existing rail section order
(after Backlinks and Conversations, before the empty-field fold, per #2037). That is a list of
NodeRows over todos, not a new widget.

### 4 — The AI pass is an ordinary conversation with the change as its first message

From a review item, **Propose** opens a conversation on the dependent (ADR-0051), from any
prompt the Conversations menu already offers on that node's type, with its first user message
pre-filled: the source before the change and after it, rendered as the AI already sees a lore
entry, and one question — what here needs to follow. The baseline rendering reads the
snapshot's bytes through the store's `read_snapshot`; nothing new is parsed and nothing is added
to the prompt vocabulary. The message is what the model can count on. The source's current
entry will usually arrive as well, because the message names it and ADR-0075 journals a
user-message mention, but that is *inferred* lore and ADR-0086's budget may drop it; nothing
here relies on it.

What happens next is what happens in any conversation. On a lore dependent, a prompt that
commits (`extract_to_node` with a `commit` block) produces the ADR-0046 patch, reviewed as
ADR-0046 reviews it; adopting saves through `PUT /api/lore/{entry_id}` with the ordinary layer
routing and marks the review item done, declining leaves it open. On a scene dependent, the
writer revises the prose or opens the mutation dialog as ever, and closes the item by hand.

### 5 — The invariant: the app proposes, the writer writes

Across §1–§4 the only write to a dependent is the save the writer commits after a diff, and no
path creates, edits or closes a mutation. The candidate set is read-only; confirming writes
todos and a snapshot of the *source*; the AI pass produces a patch the writer adopts or
declines. This is the same fails-closed rule as AI permissions and ADR-0046: a mechanism that
could write a dependent on the app's behalf is outside this ADR, whatever its safeguards, and a
later thread that adds one has drifted.

### 6 — A missing end is a validation finding, not a silent state

A review item whose dependent no longer exists is removed. Today's reconciliation
(`lifecycle.py:1225`) walks scene anchor comments only; the `node`-scoped case is new code in
the same pass, keyed on the dependent's id resolving in the index, and the ADR says so here so
that no slice assumes it exists. A review item whose source no longer exists keeps its item and is reported by `validate_project`
(`ProjectValidation`, `backend/app/models/project.py:306`) like a dangling anchor: the change
that made the item is still real, and the writer decides. A review item whose baseline snapshot
was deleted opens with the whole source as the change. Deleting a source is not itself a
propagation trigger in this ADR; ADR-0089 §9's orphan warning covers the referential side, and
"deletion as a change" is a later decision.

### 7 — The confirm surface is the one new surface, and it is mocked before it is built

Everything else in this ADR composes shipped widgets: review items are NodeRows over todos in
the todo pane and the entry rail; opening one is a card or a scene plus a second pane in
compare mode; Propose starts a conversation; Propagate is a menu entry. The confirm step is
new: the candidates, tickable, each with its reasons visible, grouped by route with the mention
group collapsed by default, and the source's diff beside them. It is also the surface that
decides whether the feature is used, because it is where a hub character's eighty prose
mentions land. That is the legibility problem ADR-0044 and ADR-0087 met with a live mockup, and
this ADR follows them: [`../mockups/0090-propagate-confirm.html`](../mockups/0090-propagate-confirm.html)
is built and iterated with Anton before S2 starts, and the layout it settles is not restated
here. What the ADR fixes is only the list above: a tick per candidate, reasons visible, the
mention group folded, the diff in view.

## Why / rejected alternatives

- **Detect on save, silently accumulate.** Rejected for noise, and because it moves the decision
  point from "this change is settled" to "a keystroke landed". Every hub entry would generate
  candidates continuously; the writer would learn to ignore the list, and a mechanism that is
  ignored is worse than none. The explicit action also gives a natural baseline (§1) for free.
- **Apply the obvious ones automatically, with undo.** Rejected: it contradicts ADR-0046's
  stance and the AI-permission rule, and "obvious" is not a category the app can hold. A rename
  looks obvious until the daughter's entry quotes the old name in dialogue on purpose. Undo is a
  command pattern here, not a snapshot, and would have to model every field write the automatic
  pass made; the review item costs one dismissed todo instead.
- **A `stale` / `needs_review` flag on the dependent's front matter.** Rejected because it is a
  write to the dependent by the app, which §5 forbids, and because it lives in the wrong file:
  the fact is "the source changed since", which belongs with a pointer to the source and its
  baseline, not with the dependent. It would also be one more thing the index, search corpus,
  snapshot diff and prompt renderer have to know to ignore.
- **A `review` node kind.** Rejected: a todo already is the app's index of deferred work
  (the TODO-as-node-index decision), and two optional fields make it carry a home and a source.
  A kind would need a folder, an editor, a rail, a prompt renderer's opinion and a migration.
- **Declared propagation rules.** Rejected: a rule a writer would actually write ("when Marek's
  rank changes, update the roster") is exactly the review item the app writes for them, and the
  general form is unauthorable. A declared dependency, where the writer wants one, is an ordinary
  reference field already.
- **A link or pointer model, shared with #66.** Rejected here, per #66's own warning: a
  dependent that remembers its source stops being self-authoritative. The review-item mechanism
  is what makes #66 answerable *without* that; the stamp-provenance question stays with #66.
- **A scene's view of the entry as a dependent.** Rejected because it is not one: the resolver
  folds the base and the markers as of every scene (ADR-0006), so a base change is already
  everywhere the moment it is saved. What survives as a real dependency is a marker on the
  changed field, which the resolver cannot judge, and prose that states the old fact. Those are
  the two scene routes in §2. The tempting reading is that mutations already *are* the answer
  for scenes; they are the answer for story time, and this ADR is about edit time.
- **Reconciling markers against the new base.** Rejected: a marker is story time (ADR-0001),
  and whether a chapter-five promotion still stands after a base demotion is a plot decision,
  not a diff. The app can point at the marker; it cannot resolve it.
- **A built-in prompt and a registered `change` variable.** Rejected for now: the before-state
  fits in the first message, every prompt already offered on the type then works unchanged, and
  a vocabulary addition plus a built-in is a mechanism with no author asking for it. Deferred,
  not sketched.
- **The frontend's reverse index as the candidate source.** Rejected: it is a second copy that
  has drifted before (#2067) and the AI path's matcher lives on the backend; one traversal.

## Consequences

- **Storage:** `TodoItem` gains `scope: "node"`, `node_id`, `source` (with its optional
  `marker_id`); the snapshot sidecar gains an optional origin. No scene body is touched. All additive and optional, so **no migration**, on the same footing as
  ADR-0086's three optional fields. A `todo.yaml` from before this ADR reads unchanged.
- **API:** two lore endpoints, a read-only candidate set and a confirm; `CreateTodoRequest`
  widened; the existing entry-patch, mutation and conversation endpoints unchanged.
- **Prompt vocabulary and built-ins:** none.
- **Frontend:** the Propagate action; the confirm surface from the mockup; review items
  rendered where todos are, plus the rail list; opening an item parks the source in compare
  mode in a second pane; Propose from an item with the pre-filled message.
- **Validation:** one new finding class (item with a missing source).
- **Tests:** candidate routes with a fixture that exercises each route and the union, including
  a marker on a changed field ranking above one on an untouched field; the baseline default
  with none / one / several propagations; the invariant, asserted as "no write to a dependent's
  file and no marker created, changed or closed across propagate, confirm and propose"; a mount
  test that review items render where todos do; a test that the pre-filled message carries the
  baseline rendering, not the current one, as *before*.
- **Could a user author this?** The review item: yes, by hand, through the widened create
  request. The AI pass: yes, it is a conversation from the prompts the writer already has. The
  detection: no, and it is not meant to be, any more than backlinks are; it is a read over the
  indexes.

## Slices

1. **S1 — the candidate set.** The four routes on the backend, the read-only endpoint, the
   fixture and route tests. No UI beyond a list to look at.
2. **S2 — review items.** The todo shape, the confirm endpoint with the baseline snapshot and
   its origin field, the Propagate action and the confirm surface as the mockup settled it,
   review items in the todo pane and the rail, opening an item with the source parked in
   compare mode, the validation finding, the invariant test.
3. **S3 — Propose.** The pre-filled conversation from a review item, adopt marks done, the
   before-rendering test.

The mockup (§7) is not a slice; it is built and agreed before S2 starts. S1 and S2 are the
mechanism and are useful without S3. Acceptance alone starts nothing; each slice gets its own
issue and an explicit go. #66 is not a slice.

## The journey that defines done

1. The writer demotes Marek: on his entry, `rank` goes from captain to sergeant and the body
   gains a paragraph on why. Three saves over an hour. Nothing else happens.
2. Settled, the writer presses Propagate on Marek. The confirm surface shows, declared first:
   the City Guard (references Marek in its `captain` field), Ilse (a relationship item pointing
   at Marek, and, listed as her second reason, her body's "her father the captain"), the Watch
   Barracks (Marek's `posting` field points at it), and Chapter 5 (a marker on Marek's `rank`,
   the field that changed, where the story promotes him). After them, Chapter 11 (a marker on
   Marek's `whereabouts`, untouched by the change). Folded under "mentions": the Weir Tavern and
   fourteen scenes; Ilse is not repeated there. Beside the list, Marek at the last propagation
   against Marek now. The writer unfolds the mentions,
   keeps Chapter 9 ("the captain's usual table"), unticks the rest and Chapter 11, and confirms.
3. Five review items appear: three on lore entries, two on scenes, the Chapter 5 one carrying
   the marker's id. Marek's foot dock shows a new snapshot. Nothing on the City Guard, Ilse, the
   Barracks, Chapter 5 or Chapter 9 has changed — not even an anchor comment.
4. The writer opens the City Guard's item. The entry opens, and Marek opens beside it parked on
   the baseline in compare mode. The writer clears the `captain` field by hand, saves, and marks
   the item done.
5. The writer opens Ilse's item and presses Propose. A conversation opens on Ilse, from the
   revise-entities prompt the writer already uses, its first message carrying Marek before and
   after and the question. The model proposes a patch: the relationship item's state and one
   sentence in the body. The writer sees the diff, edits the sentence, adopts. Ilse saves; the
   item is done.
6. The Barracks item the writer marks done unchanged after reading it: the posting still holds.
7. The Chapter 5 item opens the scene scrolled to the marker, found by its id. The promotion still stands in the story;
   the writer leaves the marker as it is and closes the item. Had it needed changing, the
   mutation dialog would have been the tool, and the writer's hand the one on it.
8. The Chapter 9 item opens the scene scrolled to the first mention, found live. The writer rewrites the sentence and
   closes the item.
9. A week later Marek's `aliases` gain "the Sergeant". Propagate measures from the snapshot
   taken in step 2, not from Marek's creation, and offers only what that change touches.
10. In a book that inherits Marek from the series, Propagate on Marek lists the book's own
    entries and scenes among the candidates; adopting a patch on one saves as the book's
    override, and a patch on an inherited dependent asks for the layer the way any save of it
    does.
11. Deleting Marek later leaves Ilse's open review item in place and lists it under project
    validation with the orphaned relationship item, until the writer closes it.
12. At no point in 1–11 has the app written to the City Guard, Ilse, the Barracks or either
    scene, and no marker was created, changed or closed by anything but the writer. Every
    change was a save the writer made after a diff.
