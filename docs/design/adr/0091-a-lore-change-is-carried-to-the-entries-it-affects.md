# ADR-0091: A lore change is carried to the entries it affects; the app finds them and drafts, the writer decides

- **Status:** Proposed — 2026-09-22; text by Claude from Anton's dogfooding of ADR-0090 the
  same day. **Supersedes ADR-0090** and its four amendments, which stay in the tree as history.
  The code ADR-0090 shipped (PRs #2118, #2120, #2122, #2123, #2127, #2128, #2130) stays; §Slices
  says what of it this ADR keeps unchanged, what it changes, and what it adds.
- **Feature:** keeping related lore entries consistent when one of them changes (#2131, #2132,
  #2133 are the open defects this ADR absorbs; the slices get their own issues).
- **Relates to:** ADR-0046 (an AI lore edit is a reviewable patch the writer adopts — the stance
  extended to dependents), ADR-0075 (the name matcher that finds prose mentions), ADR-0085 (the
  search corpus the matcher runs over), ADR-0081 (references at any depth — the reverse index),
  ADR-0089 (relationship items — a declared dependency needs no new field), ADR-0087 (a snapshot
  freezes one layer's file — the baseline), ADR-0088 (compare mode — how the baseline is
  shown), ADR-0051 (a node owns its conversations — Propose opens one), ADR-0039 (layer
  overrides — the save a review ends in follows them), ADR-0001/0006 (story-time markers and the
  resolver — why a scene's view of an entry is never a dependent and its markers are), ADR-0063
  (a commit runs a previewable extractor — how a proposed body lands), #66 (the mutation-set
  sibling, out of scope).
- **Words used here.** The *source* is the entry that changed. A *dependent* is a node that may
  need to follow: a lore entry or a scene. A *candidate* is a dependent the app proposes before
  the writer decides. A *review item* is the todo written for a candidate the writer keeps. The
  *baseline* is the snapshot the change is measured from. *Propagate* is the writer's action.
  *Prose* means an entry's body and its `long_text` fields together. A *mutation* keeps
  ADR-0001's meaning, a story-time record a scene holds about a lore field; propagation is an
  edit-time concern and never touches one.
- **Verified against `e65e2a6a` (2026-09-22).** Symbols first, line numbers second.

## Problem

A writer changes one lore entry and the change is not local. The note on the Ashford business
gains two paragraphs: the retreat was ordered, not a rout, and Marek carried the order. Marek's
entry still says he was broken to sergeant for cowardice; the City Guard's entry still lists
the retreat among its disgraces; the tavern's entry still has the regulars calling him the
deserter. The writer knows some of these follow-ups and forgets others, and the forgotten ones
surface months later as contradictions in the prose or in what the AI is told.

Almost all of that change is body text, and almost all of its consequences are body text in
other entries. Fields change too — a rank, a posting, an alias — and a field change has its own
dependents: the entries whose reference fields point at the source, and the scenes that hold a
story-time marker on the changed field. But the ordinary case is a note whose prose changed and
whose consequences are for the prose of the entries it talks about and the entries that talk
about it. Any design that treats fields as the change and prose as the noisy tail has the
problem backwards.

The tree has, since ADR-0090, most of the machinery and the wrong model of the change:

- **Propagate exists and finds candidates by route.** `ChangeCandidatesMixin.change_candidates`
  (`backend/app/services/project/change_candidates.py`) reads the node index, the mutation index
  and the search corpus and returns `(node, reasons)` for four routes; `_add_mention_reasons`
  scans prose for the source's names in one direction only, and the docstring of §2 in ADR-0090
  says the other direction "is not counted".
- **The confirm surface exists and starts with prose unticked.** `PropagateController`
  (`frontend/src/lib/stores/propagate.svelte.ts`, `#applyDefaultKept`) ticks the declared and
  marker groups and leaves every mention unticked, whatever changed. On a body-only change that
  is nothing ticked and a disabled Confirm; the first live pass read it as "the feature
  disregards the body".
- **The review item, the baseline and Propose exist and carry a body change end to end.**
  `TodoItem.source` (`backend/app/models/annotations.py`), the propagation-origin snapshot
  (`newest_snapshot_with_origin`, `backend/app/services/project/scene_snapshots.py`),
  `todoActions.proposeFromReviewItem` (`frontend/src/lib/stores/todoActions.svelte.ts`) with
  the pre-filled message from `change_message`
  (`backend/app/services/project/change_propagation.py`), and the ADR-0046 commit. Run on a
  body-only change with a mention kept by hand, under two models and two prompts, the
  dependent's body came back as a patch the writer could adopt. The chain works; the item is
  what never gets created.
- **The pane is not yet the writer's tool.** Reference values print as ids (#2133), the two
  columns cannot be resized, a pane opened right after a confirm shows a bare zero, and on a
  layered project the "since" choice moves only the owning lane (#2131).

## Intent

When the writer has settled a change to an entry, the app finds every entry and scene whose
prose or fields may need to follow — the entries the source talks about, the entries that talk
about the source, the entries bound to it by a reference, the scenes holding a marker on a
changed field — and shows them beside the change, with the ones the change can actually reach
already kept. Confirming writes one review item per kept candidate. A review item opens the
dependent beside what changed. From it the writer edits by hand, opens the mutation dialog, or
asks the AI, which opens a conversation whose one job is to say what in this entry must follow
and to draft exactly that; the draft is reviewed and adopted as ADR-0046 reviews and adopts. The
app never writes a dependent on its own.

## Anti-goals

- **Not automatic edits.** No path writes a dependent except the save the writer commits after
  a diff. Not with undo, not "obvious" cases, not renames.
- **Not save-time detection.** The trigger is the writer's action, once, when the change is
  settled. Detection on every save is the adjacent plausible path and is forbidden.
- **Not a rules engine.** No declared "when X changes, do Y to Z". A declared dependency, where
  the writer wants one, is an ordinary reference field, and the app reads it as one route.
- **Not a mutation.** Propagation never creates, edits or closes a mutation. A marker on the
  changed field is a candidate; the decision is made in the mutation dialog, by the writer.
- **Not a pointer model, not stamp provenance.** #66 keeps its own storage decision.
- **Not a new node kind.** A review item is a todo with a home and a source.
- **Not a batch.** Propose is one conversation per review item. A "follow every kept item at
  once" run would open as many conversations as items and is deferred until a writer asks for
  it with a real propagation in hand; its shape is not sketched here.
- **Not retrieval.** Detection is the reverse index plus the name matcher. A better detector is
  a later decision.
- **Not a fields-first model of the change.** Prose is the ordinary change and the ordinary
  consequence; fields and markers are the special case. This is the premise ADR-0090 had
  inverted, and it is named here so no later thread re-inverts it.

## Decision

### 1 — The trigger is the writer's, and it measures from a baseline

An entry has a **Propagate** action. Running it builds the candidate set (§2) against a
*baseline*: the newest snapshot of the source that a previous propagation captured, or, when
there is none, the whole entry treated as the change. Confirming does two things and nothing
else: it writes one review item per kept candidate (§3), and it captures a snapshot of the
source through ADR-0087's store, marked as a propagation baseline by the sidecar's `origin`.
The read half and the write half are two endpoints (`GET .../change-candidates`,
`POST .../propagate`), so the preview costs nothing.

**What "the source changed" means at a layer.** The change at the open layer L is the set of
files that compose the source at L: the owning layer's file and every override delta between
the owner and L. Each file is measured against its own baseline in its own snapshot lane; no
fold is ever compared to a file. A delta's change is its rows, field by field; the owning file
contributes the body, since deltas have no body. `changed_fields` is the union; `body_changed`
is the owning file's. Confirm captures every composing file in its own lane. The response
carries one `layers` entry per composing file.

**"Since".** The pane offers the owning lane's snapshots as the baseline choice. A chosen
since applies to every lane: the owning file is measured against the chosen snapshot, and each
delta against its newest snapshot, of any origin, captured at or before the chosen one — a
delta with none counts as whole. The whole-entry choice applies to every lane. (ADR-0090
Amendment 3 moved only the owning lane; that is #2131.)

### 2 — Five routes, prose first; the diff decides what starts kept

The candidate set is computed on the backend from the search corpus, the node index and the
mutation index. Candidates are lore entries at any layer and the open book's own scenes. A node
found by more than one route appears once with every reason. Nothing is cut; the writer reads
the list.

- **`mentions_source`** — the candidate's prose names the source's title or an alias, found
  with the ADR-0075 matcher over the ADR-0085 corpus. This is how "her father the captain"
  reaches Ilse, and how the tavern's "the deserter" reaches the tavern.
- **`mentioned_by_source`** — the source's prose names the candidate's title or an alias, same
  matcher, same corpus, lore entries only. A note is *about* the entries it names; when the
  note changes they are the first to need following. (ADR-0090 excluded this direction, which
  is why a changed note found nothing but its declared references.)
- **`references_source`** — a reference-bearing field of the candidate, at any depth, points at
  the source. A relationship item under ADR-0089 arrives here with its field named.
- **`referenced_by_source`** — a reference field of the source points at the candidate.
- **`mutates_source`** — a scene holds a marker targeting the source, with the marker's field
  named. The one route that knows *which* field.

A reason carries its route, its field where it has one, and for a marker whether that field is
in the diff. The echo rule stands: a candidate whose reference field resolves to the source's
own title does not also count as a textual mention of it.

**What starts kept follows the diff, not the route.** The pane groups candidates as *prose*
(both mention routes), *declared* (both reference routes) and *markers*:

- the body changed, or the whole entry is the change → prose and declared start kept, and
  markers on any field start kept;
- only fields changed → declared start kept, markers on a changed field start kept, markers on
  an untouched field and prose start unkept;
- both → everything starts kept.

The pane states the rule it applied in one line ("the body changed: entries it names and
entries that name it start kept"). Ranking within the list is by group in the order above,
then title. ADR-0090's "mentions ranked last, folded and unticked whatever changed" is
withdrawn.

### 3 — A review item is a todo with a home and a source

Unchanged from ADR-0090 §3 and Amendment 2, stated once. `TodoItem` has a `node` scope with
`node_id` for a lore dependent and a `source` block `{node_id, snapshot_id, reason, marker_id?}`;
a scene dependent uses the existing `scene` scope and **no anchor is written** — the marker's
id rides in `source`, and a mention is found live on open. `text` is generated and editable;
`status` is `open` | `done`; dismissing is marking done. `CreateTodoRequest` accepts the same
fields, so a writer can create one by hand. A review item shows wherever todos show, and on the
dependent's own **Review items** tab, a computed collection field like Conversations. Opening
one opens the dependent — a lore entry on its card, a scene scrolled to the marker by id or to
the first mention by name — and opens the source in a second pane parked on the baseline in
compare mode, through a pending-park intent the pane consumes on load.

### 4 — Propose opens a conversation whose job is to follow the change

From a review item, **Propose** opens a conversation on the dependent (ADR-0051) with its first
user message pre-filled: the source before the change and after it, rendered as the AI already
sees a lore entry (`_render_node_xml`, both sides folded across layers), and the question what
here needs to follow. The message stays the carrier of the change: no prompt variable, no
vocabulary registration.

The prompt that opens is a **built-in, `Follow a change`**: `prompt:general`, offered on
`lore:base`, `output.handler: extract_to_node` with visual-diff review, the same inputs and the
same field contract as `Revise entry` (`backend/app/builtin_library/prompts/revise-entry.md`),
and a system role that frames the task — the first message shows a related entry before and
after; name the difference; go through this entry's body and fields and, for each place the
change touches, quote the current wording and give the replacement; change only what the
change warrants; if nothing follows say so; say when the edits are ready to commit; do not
brainstorm alternatives. It is the default because a consequence check is not ideation:
`Revise entry`'s role pulls the model toward developing the entry, and the pre-filled message
then argues with the system prompt. The type's other prompts stay reachable from the tile's
menu. The built-in is a worked example in the public vocabulary, forkable and replaceable by a
writer's own.

What happens next is what happens in any conversation. The commit produces the ADR-0046 patch,
body included; adopting saves through `PUT /api/lore/{entry_id}` with the ordinary layer
routing and marks the item done; declining leaves it open. On a scene dependent the writer
revises the prose or opens the mutation dialog and closes the item by hand.

### 5 — The invariant: the app proposes, the writer writes

Across §1–§4 the only write to a dependent is the save the writer commits after a diff, and no
path creates, edits or closes a mutation. The candidate set is read-only; confirming writes
todos and a snapshot of the *source*; the AI pass produces a patch the writer adopts or
declines. A mechanism that could write a dependent on the app's behalf is outside this ADR,
whatever its safeguards; a thread that adds one has drifted.

### 6 — A missing end is a validation finding, not a silent state

Unchanged from ADR-0090 §6. An item whose dependent is gone is pruned by `repair_project`; an
item whose source is gone is kept and reported by `validate_project`; an item whose baseline
snapshot is gone opens with the whole source as the change. Deleting a source is not a
propagation trigger here.

### 7 — The confirm surface is an editor tab, and this is its settled shape

The surface is a closable tab in the editor region ("Propagate Marek Vell"), an on-demand
region in `workspaceLayout` like the plot board, never a dialog. Its shape, settled by the
first live pass:

- two columns, the candidate list and the source's diff, with a **draggable divider** whose
  position persists per writer; the details rail's inline drag becomes a shared split handle
  rather than a second copy;
- three groups, prose / declared / markers, each foldable, each with all/none, each row
  tickable with its reasons visible; the defaults of §2 applied on open and on every "since"
  change, with the applied rule stated in one line;
- the diff renders **reference values as titles** — tag ids and entity ids resolved through
  the rosters the frontend holds — in the field pills and in the per-item list tint (#2133);
  the body diff as ADR-0088 renders one;
- "since" in the header per §1; a pane opened straight after a confirm reads "nothing has
  changed since the last propagation, just now — pick an earlier snapshot to propagate an
  older change" rather than a bare zero;
- the primary names what it writes and is disabled at nothing kept.

## Why / rejected alternatives

- **Prose as the noisy tail, fields as the change.** Rejected by use: ADR-0090 §2 and §7 ranked
  mentions last and unticked them whatever changed, on the reasoning that a hub character's
  eighty mentions would bury the list. The first live pass showed the opposite failure — a
  changed note found nothing to keep. The burying concern is real and is answered by folding
  and all/none per group, not by unticking the only route a body change can travel.
- **Only who names the source, never whom the source names.** Rejected, same pass. A note's
  prose is about other entries; the direction that matters for a note is outbound. Both are
  kept as separate reasons so the writer can read which way the dependency runs.
- **No built-in prompt.** ADR-0090 deferred one until a writer found the message form
  insufficient. The message form is sufficient; the *prompt* the message lands in is not,
  because an ideation role and a consequence-check message pull in different directions. A
  built-in that frames the task is the smallest fix and is the kind of worked example the
  library exists for. A registered `change` variable stays rejected: nobody loops over the
  change field by field.
- **Detect on save; apply the obvious ones with undo; a `stale` flag on the dependent; a
  `review` node kind; declared rules; a link model shared with #66; a scene's view as a
  dependent; reconciling markers; the frontend's reverse index as the source.** Rejected as in
  ADR-0090 §Why, for the reasons given there; none was reopened by use.
- **Follow every kept item at once.** Deferred, not rejected: it is N conversations, and
  whether the writer wants them opened together or one at a time is unknown until someone has
  carried a real change across ten entries.
- **Roll the shipped code back and rebuild.** Rejected: the skeleton — explicit trigger,
  candidate routes, review item as todo with a source, baseline snapshot, Propose as a
  conversation — carried a body change end to end when the item existed. The document was
  wrong about the change, not the mechanism.

## Consequences

- **Storage:** none beyond ADR-0090's additive fields. A snapshot's `origin`, `TodoItem.source`,
  `scope: node` stay as they are. No migration.
- **API:** `change_candidates` gains the `mentioned_by_source` route and a direction on the
  reason; `layers[].baseline_snapshot_id` follows the chosen since. Nothing removed.
- **Prompt library:** one built-in, `Follow a change`, seeded like the other built-ins.
- **Frontend:** the default-keep rule from the diff, the split handle, title resolution in
  the diff, the post-confirm wording, Propose defaulting to the built-in with the menu behind
  it.
- **Tests:** the outbound mention route with the direction on the reason; the three default
  cases of §2 on the candidate set's `body_changed` / `changed_fields` / `whole_entry`; the
  since rule on a layered fixture (the #2131 probe); the pane rendering titles for a tag list;
  the built-in prompt's lock render registering the body in its contract.
- **Could a user author this?** The review item: yes, by hand. The AI pass: yes, from the
  writer's own prompts; the built-in is a worked example. The detection: no, and it is not
  meant to be.

## Slices

Shipped under ADR-0090 and kept unchanged: the candidate endpoint and the four existing routes,
the review item shape and its tab, the baseline snapshot and its origin, the per-lane measure,
opening an item with the source parked on the baseline, Propose with the pre-filled message,
the editor-tab surface. Each slice below gets its own issue and an explicit go.

1. **S1 — the outbound route and the since rule.** `mentioned_by_source` with the direction on
   the reason, sharing route 4's corpus scan; the chosen since resolving every lane (#2131).
   Backend, with the layered fixture.
2. **S2 — the pane.** Defaults from the diff with the stated rule; the shared split handle and
   the persisted divider; titles for reference values (#2133); the post-confirm wording.
3. **S3 — the built-in and the Propose default.** `Follow a change` seeded into the library;
   Propose opens it, the menu stays behind the tile.

#2132 (an override save silently dropping a changed body) is a fix on its own, outside this
ADR. #66 is not a slice.

## The journey that defines done

1. The writer rewrites the note on the Ashford business: two new paragraphs, the retreat was
   ordered and Marek carried the order. Three saves over an hour. Nothing else happens.
2. Settled, the writer presses Propagate on the note. The pane opens with "the body changed:
   entries it names and entries that name it start kept" and, kept: Marek (the note names
   him), the City Guard (the note names it; its `campaigns` field also points at the note),
   the Weir Tavern (its body says the regulars call Marek the deserter "since Ashford"),
   Chapter 11 (a scene whose prose names the note's title). Unkept, listed: nothing else. The
   diff shows the two new paragraphs. The writer unticks Chapter 11 and confirms.
3. Three review items appear. The note's foot dock shows a new snapshot. Nothing on Marek, the
   Guard or the tavern has changed.
4. The writer opens Marek's item and presses Propose. A conversation opens on Marek from
   `Follow a change`, its first message carrying the note before and after. The model names
   the difference, quotes "broken to sergeant for cowardice", proposes "broken to sergeant for
   an order he carried and could not prove", and says it is ready. The writer commits, edits
   one word in the diff, adopts. Marek saves; the item is done.
5. The tavern's item, the same way; the Guard's item the writer handles by hand, clearing the
   disgrace from the field and saving.
6. A week later Marek's `rank` changes back to captain. Propagate on Marek measures from the
   baseline of that day; the pane opens with "fields changed: rank" and, kept: the Guard's
   roster (references Marek), Chapter 5 (a marker on `rank`); unkept, listed and folded: the
   note, the tavern and nine scenes that name him. The writer keeps the tavern too and
   confirms.
7. In a book that inherits the note from the series, Propagate on the note lists the book's own
   entries and scenes among the candidates; adopting a patch on one saves as the book's
   override. Choosing an older snapshot as since measures the series file against it and the
   book's override delta against its own state at that time.
8. At no point has the app written to Marek, the Guard, the tavern or any scene, and no marker
   was created, changed or closed by anything but the writer.

## History

ADR-0090 was accepted on 2026-09-22 and implemented the same day. It received four amendments
before its first live pass ended: the confirm surface as an editor tab; three premises
corrected against the tree while spec'ing S2; the per-lane measure for layered projects; and,
drafted and withdrawn the same evening, the body-first correction this ADR is instead. Three
of the four came from the author correcting the author's own premises, not from new
information. The first pass on a live project then showed that the document's model of a
change — fields and markers as the change, prose as the tail — was inverted relative to the ask
it answered. Rather than a fifth amendment, this ADR restates the design once, in its final
form, and marks ADR-0090 superseded. Process rule taken from it, recorded here so it outlives
the conversation: an amendment lands only after the thing it amends has been used on live
data, or for a straight defect.
