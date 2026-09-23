# ADR-0093: The change rides on the conversation as an attachment the app places, not in its first message

- **Status:** Proposed — 2026-09-23, text by Claude from Anton's return to ADR-0092 §8 after the
  ADR-0091 live run. **Discharges ADR-0092 §8** (the deferred snapshot carrier) and **amends
  ADR-0091 §4 by reference** (§5 below). Acceptance alone starts nothing; each slice gets its
  own issue and an explicit go.
- **Feature:** Propose (ADR-0091 §4) carries the source's before and after as placed context
  that every turn of the conversation sees, instead of two XML renders pre-filled into the
  writer's first message.
- **Relates to:** ADR-0091 §1 (the fold that defines the before-state at a layer) and §4 (the
  Propose message, amended here), ADR-0092 §5 (placement, dedup by id, tiers) and §8 (the
  constraints this design starts from), ADR-0087 (the snapshot store: one lane's file, keyed
  by entity), ADR-0086 (a declared entry is never dropped), ADR-0084 (cache tiers), ADR-0057
  §3 (`context_items` as the explicit route — named, never given a producer), ADR-0060 §6
  (the preview mirrors the send), ADR-0076 (the Context door), ADR-0071 (what owes a
  migration), #1958 (the conversation-history window).
- **Words used here.** The *source*, the *baseline* and the *dependent* keep ADR-0091's
  meanings. An *attachment* is a piece of context the **app** puts on a conversation when it
  opens it, persisted with the chat and placed on every send; it is outside the prompt's
  vocabulary, which is what separates it from a *pick* (`use()`). *The change* is the source
  at its baseline (the *before*) and the source as it is (the *after*). A *before element* is
  the one XML element the before renders to. The *door* is the Context door.
- **Verified against `8ba42ddc` (2026-09-23).** Symbols first, line numbers second.

## Problem

ADR-0091 §4 made the first user message the carrier of the change: `change_message`
(`backend/app/services/project/change_propagation.py`) renders the source at its baseline and
as it is, both through the lore XML the model already reads, and pre-fills them into the
composer with one question under them. The first live run, and Anton's reading of it, found
two costs in that carrier, and one of them is a defect.

- **The history window drops the change first.** `fit_history_window`
  (`backend/app/services/ai/history_budget.py`) keeps the newest whole rounds that fit the
  assistant's `ai_history_budget_tokens` and drops the oldest. The round holding the change is
  round one. A writer with a history budget set who follows a change through enough turns
  loses the change silently, while the system role still says the first message shows it.
  The model then answers from its memory of a message it no longer has.
- **The composer is not the place for two XML renders.** Propose opens a conversation and asks
  the writer to press Send on a wall of `<character …>` elements. The writer's first act in a
  conversation the app opened for them is to scroll past what the app put there. And the two
  renders are conversation turns, which no tier caches: they are re-sent on every turn as the
  largest part of it.

Since ADR-0092 §7.1 the built-in is pick-only, so the names in that message no longer journal
anything; what remains is the carrier itself. ADR-0092 §8 deferred a carrier shaped as
`use(node, snapshot=id)` and recorded the constraints any design must meet. On return Anton
closed the shape: **no Jinja access to snapshots.** A writer cannot type a snapshot id, so a
word only the app could fill would be a word a prompt author cannot use honestly. That moves
the placement from the template to the app, and it turns out the chat already has a slot for
exactly that.

## Intent

**The change is an attachment on the conversation.** The app places it when Propose opens the
conversation; the send carries it on every turn, the before in the stable tier; the door
shows it; the first message is the question. No prompt learns a new word.

## Anti-goals

- **Not a prompt vocabulary word.** No `use(node, snapshot=)`, no `entry(x, snapshot=)`, no
  snapshot input type. This is Anton's call, not a deferral: a prompt has no honest way to
  name a snapshot, and a hidden app-seeded input would make the built-in a prompt nobody could
  author.
- **Not a revival of the manual picker.** `context_items` gets its first producer and its
  first placed kind. The `lore`, `manuscript`, `snippet` and `preset` kinds keep exactly what
  they have today, which is nothing on the send path (ADR-0086 §Problem left them outside its
  decision; nothing has asked for them since).
- **Not a change to detection, the budget, the reach, or the tier rules.** The before is one
  more element the existing rules place; ADR-0092 §§3–5 stand as written.
- **Not on the commit turn.** The commit's `used` turn places the picks alone, as ADR-0092 §7.1
  left it; the extractor reads the transcript, not the source.
- **Not compare mode in the chat, and not a snapshot of the dependent.** The dependent arrives
  live through the built-in's `use(e)`, as today.
- **Not auto-send.** The writer sends; ADR-0091 §5 is untouched. A one-line question is one
  keystroke.

## Decision

### 1 — An attachment is a `context_items` item of kind `change`

`ChatSessionContextItem` (`backend/app/models/ai.py`) is "a context attachment carried with the
chat across turns" by its own docstring, is persisted on every chat, and has never had a
producer: `create_chat_session` (`backend/app/services/project/chats.py`) writes
`context_items=[]` unconditionally, and the frontend echoes `[]` on its two saves
(`chatSessions.svelte.ts`, `ChatBodyView.svelte`). It gains one field and one kind:

- `kind: "change"`, `id` = the source's entity id, `snapshot_id` = the owning-lane baseline
  snapshot id, with the same tri-state as `ChangeMessage.baseline_snapshot_id`
  (`backend/app/models/annotations.py`): `""` means the whole entry is the change, so there is
  no before. `title` and `entry_type` are filled as for the other kinds.
- `CreateChatSessionRequest` gains `context_items`, and `create_chat_session` persists what it
  is given. Every save already carries the list; the two frontend echoes send the chat's own
  items instead of `[]`, so a per-turn save never drops the attachment (the same echo rule
  `subject` and `staged_set` follow).

Why the existing slot and not a new field: the thing being stored is what the slot was made
for, and a new list beside a producer-less one leaves a dead field next to a live one.

### 2 — What the send places: the after joins the picks, the before is its own element

`expand_and_prepare_chat_blocks` and `_lore_cache_blocks` (`backend/app/services/ai/chat.py`)
place each `change` item as two halves, flag on or off, the way ADR-0092 §7.1 places picks:

- **The after** is the source's live id, unioned into the declared picks handed to the
  selector. It is keyed by id like every pick, so every consumer of a placed id works
  unchanged: it dedupes with a template's own `use()` of the same entry, `never` applies, the
  budget never drops it, `_tier_lore_ids` tiers it by revision, the door's `edited` signal
  (`chat_changed_picks`, `chats.py`) reports it, and detection skips it as already in context
  (`picked_ids`, `chat.py`, which already reads `context_items`).
- **The before** exists when `snapshot_id` is set: one element in the **stable lore block**,
  rendered by the reader `change_message` uses today — `read_snapshot` on the owning lane,
  `_fold_propagation_baseline_metadata` for every delta lane's own baseline under ADR-0091 §1's
  since rule, `_render_node_xml` for the element — extracted into one function both call.
  This is the fold ADR-0092 §8 asked for, and it is one traversal, not a second.
  - The element carries the entry's `id` plus `snapshot="<snapshot id>"` and
    `captured="<captured_at>"`, so the model joins before and after by id and can tell them
    apart; the system role names the attribute (§4).
  - Its key is `(entry_id, snapshot_id)`. It lives beside the tier's id list, never inside the
    id-keyed set, so the before cannot dedupe into the after (ADR-0092 §8, Anton's catch) and
    no id-keyed consumer ever meets a key it cannot read as a node.
  - Its revision is the hash of its rendered bytes, checked against the same session baseline
    (`AISession`, `backend/app/services/ai/sessions.py`) under that composite key. ADR-0092 §8
    is right that it is not stable by construction — the renderer resolves reference titles
    live — so a before whose bytes changed goes volatile for one turn and settles again, the
    rule every block follows.
  - It is placed before the live elements in the stable block, so the model reads before then
    after. It is an element, not a wire block: provider breakpoints stay capped (ADR-0084).
  - A snapshot the store no longer holds (thinned, or the lane deleted) places no before and
    adds one `warnings` entry to the preview and the send's report; a send never fails on it.
- **The preview mirrors it.** `AIPreviewRequest` gains `context_items` (the frontend holds the
  chat it previews for), and `_preview_lore_tiers` (`backend/app/services/ai/preview.py`)
  places both halves the same way against its throwaway session, so the turn-0 door is honest
  before the first send (ADR-0060 §6).

### 3 — The door shows the before as its own row

`PreviewCacheBlock` (`backend/app/models/ai.py`) keeps `entry_ids` as node ids — the door's
`titleFor` (`ChatBodyView.svelte`) resolves those through the rosters and must never see a
composite key — and gains an additive `snapshots` list, one item per before element on the
block: `{entry_id, snapshot_id, captured_at, title}`, with the element's XML in `entry_xml`
under the composite key. The door lists each as a drillable row labelled with the roster title
and the capture time, the same relative-time helpers the Propagate since selector uses
(`snapshotTime.ts`, `relativeTime.ts`), and drills to its XML like an entry. The `edited` list
never names a before: nothing edits a snapshot.

### 4 — Propose attaches the change; the built-in's template does not change

`GET /api/lore/{id}/change-message` keeps its shape. `source_id` and `baseline_snapshot_id`
already say what to attach; `text` shrinks to the question — "⟨Source⟩ changed since the last
propagation. What in this entry needs to follow from that change? Propose only what the change
warrants; if nothing follows, say so." — and its no-baseline variant. `proposeFromReviewItem`
(`todoActions.svelte.ts`) creates the chat with the attachment in `context_items` and holds
the question for the composer exactly as it holds the message today (`composerPrefills`).

`Follow a change` (`backend/app/builtin_library/prompts/follow-a-change.md`) declares no new
input and calls nothing new: `use(e)` and its includes stay. Its system role changes wording,
not moves: the related entry that changed is in the model's context, its state before the
change carrying a `snapshot` attribute and its current state carrying none; when there is no
earlier state, the current one alone; if neither is there, ask before anything else. A
writer's fork or replacement gets the change too, because it rides on the conversation and not
on the prompt. That is the one place a writer's own prompt meets a snapshot, and it needs no
word for it.

### 5 — What this amends and what it discharges

ADR-0091 §4's "the message stays the carrier of the change: no prompt variable, no vocabulary
registration" becomes: **the conversation carries the change as an attachment the app places;
the message is the question; still no prompt variable and no vocabulary registration.** The
rest of §4 stands.

ADR-0092 §8's constraints, and where each lands: *dedup* → the before's composite key beside
the id list (§2); *storage* → a persisted `context_items` item (§1); *layers* → the shared
reader folds by ADR-0091 §1 (§2); *identity* → the item carries the entity id beside the
snapshot id (§1); *not stable by construction* → revision by rendered bytes (§2); *not a wire
block* → an element in the stable tier with its own door row (§2, §3); *ADR-0091 §4* →
amended above. The one thing §8 sketched and this ADR does not build is the prompt word.

## Why / rejected alternatives

- **`use(node, snapshot=id)`, ADR-0092 §8's shape.** Rejected by Anton: no Jinja access to
  snapshots. A prompt cannot fill it, so the built-in would need a hidden input the app seeds,
  which is a prompt no writer could author; and a snapshot input type to make it authorable is
  a second feature carrying the first.
- **A composite id through the pick list.** Rejected: the pick list is read as node ids by the
  selector, the fit, the tiering, the session baseline, the door, the fit report and the
  matcher's exclusion; §8 named this and the first draft of ADR-0092 fell into it.
- **A new field beside `context_items`.** Rejected: the slot exists, is persisted on every
  chat, and describes this exact thing; a second list would leave the first dead.
- **Give the `lore` item kind placement semantics while here.** Not here: ADR-0086 left the
  manual picker outside its decision and no surface produces one; a decision with no consumer
  is the ADR-0005 pattern.
- **Keep the message and pin round one in the history window.** Rejected: the composer wall
  and the per-turn re-send stay, and the window gains a special case for one prompt.
- **Auto-send the first message.** Rejected: the writer sends (ADR-0091 §5), and a prefilled
  one-line question costs one keystroke.
- **Freeze the after too.** Rejected: the after is the entry as it is; a writer who edits the
  source mid-conversation should be answered about the entry as it now stands, and a live pick
  already tiers correctly when that happens.
- **Decide this inside ADR-0092.** Already rejected there: the constraints were recorded, the
  shape was not, and the shape changed on return.

## Consequences

- **Storage:** one additive, defaulted field on an existing item model and one new value for
  its `kind`; chats persisted before read unchanged. Precedent: `seen_revisions` (#1635) and
  `used_node_hints` (ADR-0060 §5) were added the same way with no migration. ADR-0071's ladder
  is for a shape a reader must convert; there is none here.
- **API / wire:** `CreateChatSessionRequest` and `AIPreviewRequest` gain `context_items`;
  `PreviewCacheBlock` gains `snapshots`; the change-message response keeps its fields and its
  `text` shrinks to the question; the before element reaches the provider's system blocks
  inside the stable lore block with `snapshot` and `captured` attributes.
- **Send path:** the shared baseline reader extracted from `change_message`;
  `_lore_cache_blocks` and `_budgeted_lore_tiers` learn the attachment's two halves; the
  commit turn ignores it.
- **Frontend:** Propose creates the chat with the attachment; the two `context_items: []`
  echoes echo the chat's items; the door gains the before row; `composerPrefills` is unchanged.
- **Built-ins:** `Follow a change`'s role text as §4; its template body unchanged.
- **Docs:** `docs/ai-context.md` ("What the AI sees") gains the attachment beside picks and
  automatic lore; ADR-0091 §4 and ADR-0092 §8 get a one-line amendment note pointing here; the
  vocabulary reference is untouched, since no word was added.
- **Tests:** create persists the attachment and a save echoes it; a send places both halves
  (a wire test: the before element, with its `snapshot` attribute, reaches the provider's
  system blocks in the stable tier, the after in a tier by revision); the before never dedupes
  into the after when the template also `use()`s the source; a missing snapshot warns and
  sends; a before whose rendered bytes change re-tiers once; the preview mirror carries both
  halves with `lore_enabled` false; a conversation windowed past round one still carries the
  change; the door lists the before row and drills to its XML; Propose creates with the
  attachment and holds the question; the built-in body.
- **Could a user author this?** A writer's own prompt, opened from Propose, gets the change
  without a word for it. A writer cannot attach a snapshot to a conversation they open by
  hand, and that is the anti-goal, not a gap.

## Slices

1. **S1 — the attachment and the send.** §1 and §2 with the preview mirror and the shared
   reader; the API fields; the tests above the door's. Backend only.
2. **S2 — Propose, the door and the built-in.** §3 and §4; the frontend echoes; the role text;
   the docs; the amendment notes on ADR-0091 and ADR-0092.

One lane, S1 first: S2's rows and role text name attributes S1 defines.

## The journey that defines done

1. The writer presses Propose on The Implant's review item. A conversation opens from `Follow
   a change`; the composer holds one line, the question. The door shows three rows: The
   Implant as of the baseline's time (stable), The Implant (volatile on the first turn), and
   the dependent.
2. The writer sends. The model names the difference and quotes the one sentence in the
   dependent that must change. The meta line shows the fit and nothing left out.
3. Ten turns on, with a history budget set, the first round has left the window. The door
   still shows the before row; the model still answers against the change.
4. The writer edits The Implant mid-conversation. The door marks the after as edited; the next
   turn re-sends it volatile, then it settles. The before row never changes.
5. The baseline snapshot is thinned away. The next turn places the live source alone, the meta
   line carries the warning, and the send goes.
6. The writer forks `Follow a change` under its own title. Propose opens the fork; the change
   is there, and the fork's template never mentions it.

## History

Written when Anton returned to ADR-0092 §8 with two findings from the live run — the history
window drops the change first, and a composer full of XML is not something to ask a writer to
send — and one closed door: no Jinja access to snapshots. The §8 shape, `use(node,
snapshot=)`, went with the door; the constraints under it stood, and each has a home above. The
slot for an app-placed attachment turned out to exist already, persisted on every chat, with a
docstring describing this feature and no producer for it since ADR-0057 named it.
