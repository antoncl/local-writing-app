# ADR-0091: A lore change is carried to the entries it affects; the app finds them and drafts, the writer decides

- **Status:** Accepted — 2026-09-23, Anton Lauridsen; text by Claude from Anton's dogfooding of
  ADR-0090 on 2026-09-22, revised against three cold implementing threads' findings before
  acceptance (PR #2134). **Supersedes ADR-0090** and its four amendments, which stay in the
  tree as history. Acceptance alone starts nothing: each slice gets its own issue and an
  explicit go.
  The code ADR-0090 shipped (PRs #2118, #2120, #2122, #2123, #2127, #2128, #2130) stays; §Slices
  says what of it this ADR keeps unchanged, what it changes, and what it adds.
- **Amended by:** ADR-0093 (§4, the carrier).
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
  scans prose for the source's names in one direction only, and ADR-0090 §2 counted the
  source's own declared references as its only outgoing route.
- **The confirm surface exists and starts with prose unticked.** `PropagateController`
  (`frontend/src/lib/stores/propagate.svelte.ts`, `#applyDefaultKept`) ticks the declared and
  marker groups and leaves every mention unticked, whatever changed. On a body-only change
  nothing the body reaches is ticked: a note with no reference pointing at it opens with
  nothing kept and a disabled Confirm; the first live pass read it as "the feature disregards
  the body".
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
  columns cannot be resized, a pane opened right after a confirm shows "0 fields, since just
  now" beside a fully ticked list and a live Confirm, and on a layered project the "since"
  choice moves only the owning lane (#2131).

## Intent

When the writer has settled a change to an entry, the app finds every entry and scene whose
prose or fields may need to follow — the entries the source talks about, the entries that talk
about the source, the entries bound to it by a reference, the scenes holding a marker on a
changed field — and shows them beside the change, with the declared ones and the ones the
change reaches already kept. Confirming writes one review item per kept candidate. A review item opens the
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
is the owning file's. Confirm captures every composing file in its own lane, **the delta lanes
first and the owning file last**, so that the owning snapshot's time is at or after every
delta snapshot of the same confirm (a confirm that fails midway leaves the old owning
baseline, which still pairs with the old delta baselines). The response carries one `layers`
entry per lane measured: each composing file, and each lane whose delta has been removed since
its baseline, which counts its baseline's fields as changed.

**"Since".** The pane offers the owning lane's snapshots as the baseline choice. Whatever
resolved the owning baseline — the writer's pick or the default — that snapshot sets the
measure for every lane: the owning file is measured against it, and each delta lane against
its newest snapshot, of any origin, captured at or before it; a delta lane with none counts as
whole, and a removed-delta lane with none is not a change. A thinned session-boundary
snapshot counts like any other: the resolution is recomputed on every read and a review item
stores only the owning id. The whole-entry choice applies to every lane. The Propose message's
*before* side (§4) resolves the delta lanes by the same rule from the item's owning snapshot.
(ADR-0090 Amendment 3 moved only the owning lane and folded the message's before side from the
newest propagation snapshot regardless; that is #2131.)

### 2 — Five routes, both directions of prose among them; the diff decides what starts kept

The candidate set is computed on the backend from the search corpus, the node index and the
mutation index. Candidates are lore entries at any layer and the open book's own scenes. A node
found by more than one route appears once with every reason. Nothing is cut; the writer reads
the list.

- **`mentions_source`** — the candidate's prose names the source's title or an alias, found
  with the ADR-0075 matcher over the ADR-0085 corpus. This is how "her father the captain"
  reaches Ilse, and how the tavern's "the deserter" reaches the tavern.
- **`mentioned_by_source`** — the source's prose names the candidate's title or an alias, same
  matcher, same corpus, lore entries only. The names matched are every candidate's title and
  aliases as the folded entry has them; story-time names from markers do not widen this
  direction (a note is not read as of any scene). A name two entries share finds both. A note
  is *about* the entries it names; when the note changes they are the first to need following.
  (ADR-0090 excluded this direction, and pinned the exclusion in a test — "a mention FROM the
  source must not make Rumour a candidate" — which S1 inverts.)
- **`references_source`** — a reference-bearing field of the candidate, at any depth, points at
  the source. A relationship item under ADR-0089 arrives here with its field named.
- **`referenced_by_source`** — a reference field of the source points at the candidate.
- **`mutates_source`** — a scene holds a marker targeting the source, with the marker's field
  named. The one route that knows *which* field.

A reason carries its route, its field where it has one (empty for both mention routes), and
for a marker whether that field is in the diff; the route *is* the direction, as it is for the
two reference routes — no other field is added. Within a candidate the reasons keep their
shipped order, declared, marker, mention in, mention out, and the first one is what the review
item's `source.reason` records; §2's group order is the pane's, not the reason's. The echo rule
is the same in both directions and is a property of what is scanned, not a filter: only prose
is scanned — the body and the `long_text` fields — so a reference value that the corpus
carries as a resolved title (the City Guard's `captain` reading "Marek Vell", Marek's
`posting` reading "Watch Barracks") is never a textual mention. No `context_policy` filter
applies in either direction; a `never` entry is still a dependent.

**What starts kept follows the diff, not the route.** The pane groups candidates from their
reasons — the wire's `tier` stays as shipped and the pane ignores it — as *declared* (a
reference route among the reasons), else *markers* (a marker route), else *mentions* (a
mention route in either direction); a node with several reasons lands in the first group its
reasons reach, in that order. Within declared and mentions, rows sort by title; within
markers, a scene with a marker on a changed field sorts before one whose markers are all on
untouched fields, then by title. The default depends only on the diff:

- **fields changed, body unchanged** — declared and markers start kept and unfolded; mentions
  start unkept and folded;
- **the body changed** (with or without fields), **or the whole entry is the change** —
  every group starts kept and unfolded;
- **nothing changed** — no changed field, the body unchanged, not the whole entry, and no
  lane whole (a delta created since the baseline is a change even with no field named); the
  ordinary case is a pane opened straight after a confirm — nothing starts kept, every group
  starts folded, Confirm is disabled, and the pane says so (§7).

Declared and markers start kept whenever there is a change because they are few, specific and
cheap to untick; mentions follow the body because prose is the only thing a body change can
reach. The defaults and fold states are re-applied on open and on every "since" change, the
writer's own folds included — a since change is a new question. The pane states what it did in
one line, in one grammar, *what changed: what starts kept*: "The body changed: entries it names
and that name it start kept, with the declared rows and the markers." / "The body and 2 fields
changed (rank, aliases): everything listed starts kept." / "Fields changed (rank, aliases):
declared rows and markers start kept; mentions are folded." (more than three fields reads
"rank, aliases and 2 more") / "No baseline: the whole entry counts as the change; everything
listed starts kept." ADR-0090's "mentions folded and unticked whatever changed" is
withdrawn; its declared-and-markers-ticked default stands. The shipped tests that pin the
withdrawn rule flip rather than get patched.

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

> **Amended by ADR-0093 (2026-09-23):** the prompt places the change with
> `use(node, snapshot=id)` from two hidden inputs Propose seeds; the message is the question.
> Still no prompt variable, the one vocabulary change is a keyword on a call that exists.

From a review item, **Propose** opens a conversation on the dependent (ADR-0051) with its first
user message pre-filled: the source before the change and after it, rendered as the AI already
sees a lore entry (`_render_node_xml`, both sides folded across layers), and the question what
here needs to follow. The message stays the carrier of the change: no prompt variable, no
vocabulary registration.

The prompt that opens is a **built-in, `Follow a change`**, a file in the read-only Library
layer beside `revise-entry.md` (`backend/app/builtin_library/prompts/`): nothing seeds it, no
manifest, migration or vocabulary entry is involved, and the persisted node index picks a new
Library file up on its next rebuild. Its shape: `prompt:general`, offered on `lore:base`,
`output.handler: extract_to_node` with visual-diff review, the same field contract as
`Revise entry` (every proposable field, the body included) and the same hidden `entry_type`
input, but its `entry` input **required** — this prompt has no create mode. That one word is
load-bearing: the Lore pane's "Draft <type>" picks the first committing prompt offered on the
type, and by title this built-in sorts before `Revise entry`; so create resolution skips any
committing prompt whose `entry` is required, which is the principled rule (a create launch has
no entry to give) rather than a name special-case.

The system role is normative in its moves, not its wording: the first message shows a related
entry as it changed — before and after, or, when no earlier version exists, as it now stands;
if the first message shows no such entry, ask for it before anything else (the prompt is
offered on the type, so ＋New can launch it without a change); name the difference, only the
difference; go through this entry's body and fields and, for each place the change touches,
quote the current wording and give the replacement; change only what the change warrants; if
nothing follows, say so and stop; say when the edits are ready to commit; do not brainstorm
alternatives or suggest improvements beyond the change; hold each revision to about the
current length of the field or body, the anchor every built-in that commits a body carries.
On the seeded project both `Revise entry` and this role produced the right body edit under
two models; the difference was discipline — the ideation role evaluated every field on the way
and drafted at length, this one named the difference, quoted, replaced and stopped — and a
default that opens without a menu. That is why it is the default, not because the message
form failed. The built-in is a Library node like every other, forkable and replaceable by a
writer's own.

**How Propose finds it.** By title, project-owned first, then the Library's: the same
shadowing rule includes-by-title already use, so a fork (which keeps the title) or a
replacement the writer authors under that title takes over, and a renamed fork drops out. The
review item's tile becomes two trailing buttons: the primary opens the default; a second opens
the menu of every prompt offered on the type. When no prompt of that title is offered — the
writer hid the built-in, or the type does not reach `lore:base` — the tile is the menu alone,
as shipped; when nothing is offered it is disabled, as shipped. Never a silent fallback to
whichever prompt sorts first. Propose exists on the dependent's Review items tab, lore entries
only; a scene review item opens the scene and has no Propose, as shipped.

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

The surface is a closable tab in the editor region, an on-demand region in `workspaceLayout`
like the plot board, never a dialog. The tab reads "Propagate" (a region's title is static);
the pane's heading names the source. Its shape, settled by the first live pass:

- two columns, the candidate list and the source's diff, with a **draggable divider**: the
  list column's width in pixels, clamped to a minimum and maximum, persisted like the details
  rail's width (browser local storage, keyed by project, loaded with the project), a default
  near the shipped 5:4 split; under the pane's narrow breakpoint the columns stack and the
  divider is hidden. The rail's inline drag (`EditorRail.svelte`, `startResize` /
  `onResizeMove` / `endResize`) becomes a shared **split handle** widget that owns the gesture
  — document-level mousemove and mouseup, as AGENTS.md requires for pane drags — the accent
  stripe and the `separator` role with its orientation, while each host keeps its own clamp and
  persistence in the callbacks. The rail is its first consumer and this pane its second; the
  shell's `WorkspaceNode` splitter and the mutation dialog's resize are two more copies that
  may adopt it later and are not in scope. Keyboard resizing is not in scope.
- three groups, **Declared / Markers / Mentions**, each foldable, each with the tri-state
  header row PickTree already gives the pane (the shipped "all/none"), each row tickable with
  its reasons visible; §2's defaults, fold states and rule line;
- the diff renders **reference values as titles** (#2133): a value is a reference when
  today's schema types its field so — `entity_ref`, `entity_ref_list`, a tag field, or a
  group member of those types — never by the shape of the id; the resolver is the same
  roster recipe the metadata panel uses (structure, lore, prompts, assistants, plotlines,
  tags); an id no roster knows renders as the id. The list diff keeps the id as the compare
  key and carries the title as a label, so two references sharing a title stay two pills. The
  rail's own compare already renders through the field rows and is untouched. The body diff
  as ADR-0088 renders one;
- "since" in the header per §1. In the nothing-changed state of §2 the diff column reads
  "Nothing has changed since the last propagation, <age> — pick an earlier snapshot to
  propagate an older change", where the age is the baseline's **capture** time (not the
  strip's content-written time, which is the file's last save and can predate the confirm by
  hours — a deliberate exception to `notchWhen`'s rule, and the since-selector's labels take
  the same exception);
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
  insufficient. The message form is sufficient — it carried the change under an ideation
  prompt too — so the built-in is not a fix but a default: Propose should open on a role
  written for the task rather than on a menu, and the library exists for exactly this kind of
  worked example. A registered `change` variable stays rejected: nobody loops over the change
  field by field.
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

- **Storage:** none beyond ADR-0090's additive fields, plus one new legal value,
  `mentioned_by_source`, in `TodoSource.reason` on disk. A snapshot's `origin`,
  `TodoItem.source`, `scope: node` stay as they are. No migration.
- **API:** `change_candidates` gains the `mentioned_by_source` route value;
  `layers[].baseline_snapshot_id` follows the resolved owning baseline in every lane, which
  touches the delta diff, the removed-lane diff and the message's before-fold, and reverses
  confirm's capture order. The `tier` field stays as shipped (`declared` /
  `marker_untouched` / `mention`, an outbound-only candidate landing in `mention`); the pane
  groups from the reasons (§7), so no wire change waits on S2. Nothing removed.
- **Prompt library:** one built-in file, `Follow a change`, in the Library layer; the shipped
  built-in enumerations in the tests (offer-on, disposition, the length anchor, the
  relevant-lore wiring) gain its title.
- **Frontend:** the grouping and defaults from the diff, the split handle, title resolution in
  the diff, the nothing-changed state, the Propose default found by title with the menu as a
  second button, and create resolution skipping committing prompts that require an entry.
- **Tests:** the outbound mention route, its echo mirror (a resolved reference value is not a
  mention) and a shared alias finding both entries; confirm capturing deltas before the owner;
  the since rule on a layered fixture (the #2131 probe) and on the message's before side; the
  three default states of §2 from `body_changed` / `changed_fields` / `whole_entry` and the
  group precedence for a multi-route node; the rule line's strings; a characterisation test of
  the rail's drag before it is extracted; the pane rendering titles for a tag list with two
  same-titled ids staying two pills; the built-in's rendered contract registering the body
  (the existing built-in contract test, extended); the Propose default by title with an owned
  prompt shadowing the Library's, a hidden built-in leaving the menu alone, and the Lore pane's
  Draft still resolving to `Revise entry`.
- **Could a user author this?** The review item: yes, by hand. The AI pass: yes, from the
  writer's own prompts; the built-in is a worked example. The detection: no, and it is not
  meant to be.

## Slices

Shipped under ADR-0090 and kept unchanged: the candidate endpoint and the four existing routes,
the review item shape and its tab, the baseline snapshot and its origin, the per-lane measure,
opening an item with the source parked on the baseline, Propose with the pre-filled message,
the editor-tab surface. Each slice below gets its own issue and an explicit go.

1. **S1 — the outbound route and the since rule.** `mentioned_by_source`: one corpus read,
   the source's own corpus entry scanned for a matcher compiled from every candidate's names
   (route 4's loop runs the other way — the shareable parts are the corpus read, the prose
   filter and the matcher, not the loop); the resolved baseline setting the measure in every
   lane, with confirm capturing deltas before the owner (#2131). Backend with the layered
   fixture, plus the frontend route union and its reason phrase, which fail type-checking
   without the new member.
2. **S2 — the pane.** After S1 (the pane needs the new route's phrase and journey step 2 has
   no candidates without it). Grouping from reasons and the defaults from the diff with the
   rule line; the shared split handle and the persisted divider; titles for reference values
   (#2133); the nothing-changed state. `App.svelte` is within forty lines of the size guard's
   fail: the divider's store loads beside the rail's, one line there and nothing more.
3. **S3 — the built-in and the Propose default.** The `Follow a change` file in the Library
   layer with its tests; the default found by title; the two-button tile; create resolution
   skipping entry-required committing prompts. Before merge, a restart on an existing project
   confirms the Prompts pane lists the new Library prompt without a cache wipe.

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
   `Follow a change`, its composer pre-filled with the note before and after; the writer
   sends. The model names
   the difference, quotes "broken to sergeant for cowardice", proposes "broken to sergeant for
   an order he carried and could not prove", and says it is ready. The writer commits, edits
   one word in the diff, adopts. Marek saves; the item is done.
5. The tavern's item, the same way; the Guard's item the writer handles by hand, clearing the
   disgrace from the field and saving.
6. A week later Marek's `rank` changes back to captain. Propagate on Marek measures from the
   baseline of that day; the pane opens with "fields changed: rank" and, kept: the Guard's
   roster (references Marek), Chapter 5 (a marker on `rank`, the changed field) and Chapter 11
   (a marker on his `whereabouts`, untouched, listed after Chapter 5); folded and unkept: the
   note, the tavern and nine scenes that name him. The writer unticks Chapter 11, keeps the
   tavern too, and confirms.
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
