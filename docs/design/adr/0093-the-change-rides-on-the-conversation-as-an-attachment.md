# ADR-0093: The change rides on the conversation as an attachment the app places, not in its first message

- **Status:** Proposed — 2026-09-23, text by Claude from Anton's return to ADR-0092 §8 after the
  ADR-0091 live run, revised against two cold implementing threads' findings (PR #2161).
  **Discharges ADR-0092 §8** (the deferred snapshot carrier) and **amends ADR-0091 §4 by
  reference** (§5 below). Acceptance alone starts nothing; each slice gets its own issue and
  an explicit go.
- **Feature:** Propose (ADR-0091 §4) carries the source's before and after as placed context
  that every turn of the conversation sees, instead of two XML renders pre-filled into the
  writer's first message.
- **Relates to:** ADR-0091 §1 (the fold that defines the before-state at a layer) and §4 (the
  Propose message, amended here), ADR-0092 §5 (placement, dedup by id, tiers) and §8 (the
  constraints this design starts from), ADR-0087 (the snapshot store: one lane's file, keyed
  by entity), ADR-0086 (a declared entry is never dropped), ADR-0084 (cache tiers), ADR-0057
  §3 (`context_items` as the explicit route — named, never given a producer), ADR-0060 §5/§6
  (the volatility hint; the preview mirrors the send), ADR-0076 (the Context door), ADR-0071
  (what owes a migration), #1958 (the conversation-history window).
- **Words used here.** The *source*, the *baseline* and the *dependent* keep ADR-0091's
  meanings. An *attachment* is a piece of context the **app** puts on a conversation when it
  opens it, persisted with the chat and placed on every send; it is outside the prompt's
  vocabulary, which is what separates it from a *pick* (`use()`). *The change* is the source
  at its baseline (the *before*) and the source as it is (the *after*). A *before element* is
  the one XML element the before renders to; its *key* is the string that names it wherever a
  placed thing is named by a string. The *door* is the Context door; its *tier row* is the
  root-level "stable lore" / "volatile lore" row, and its *tier panel* is the list that row
  drills into.
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
  left it; neither half of the attachment joins it. The extractor reads the transcript, not
  the source.
- **Not compare mode in the chat, and not a snapshot of the dependent.** The dependent arrives
  live through the built-in's `use(e)`, as today.
- **Not auto-send.** The writer sends; ADR-0091 §5 is untouched. A one-line question is one
  keystroke.

## Decision

### 1 — An attachment is a `context_items` item of kind `change`, and a save cannot wipe it

`ChatSessionContextItem` (`backend/app/models/ai.py`) is "a context attachment carried with the
chat across turns" by its own docstring, is persisted on every chat, and has never had a
producer in the app: `create_chat_session` (`backend/app/services/project/chats.py`) writes
`context_items=[]` unconditionally, and the frontend echoes `[]` on its two saves
(`openChatFromPromptEntry` in `chatSessions.svelte.ts`, `currentChatSessionPayload` in
`ChatBodyView.svelte`). Tests construct items of the other kinds, so the widening is additive.
It gains one field and one kind:

- `kind: "change"`, `id` = the source's entity id, `snapshot_id` = the owning-lane baseline
  snapshot id, with the same tri-state as `ChangeMessage.baseline_snapshot_id`
  (`backend/app/models/annotations.py`): `""` means the whole entry is the change, so there is
  no before, and the item is still attached, for the after. `title` and `entry_type` are
  filled by Propose from the lore roster, empty when the source is not in it.
- `CreateChatSessionRequest` gains `context_items`, and `create_chat_session` persists what it
  is given.
- **`SaveChatSessionRequest.context_items` becomes "None means preserve"** — the rule
  `used_node_ids`, `used_node_hints` and `lore_enabled` already follow — instead of a list
  defaulting to `[]` that `save_chat_session` writes through. Today a save that omits the field
  erases the attachment, and the frontend's two echoes send exactly that. Both echoes are
  changed to send the chat's own items, but the backend rule is the guarantee: a third save
  site written later cannot repeat the wipe. (`subject` and `staged_set` use a different
  fallback, an empty string falling back to the persisted value; the picks' None-preserve is
  the right one for a list, where `[]` is a value.)

Why the existing slot and not a new field: the thing being stored is what the slot was made
for, and a new list beside a producer-less one leaves a dead field next to a live one.

### 2 — What the send places: the after joins the picks, the before is its own element

`expand_and_prepare_chat_blocks` and `_lore_cache_blocks` (`backend/app/services/ai/chat.py`)
place each `change` item as two halves, and an attachment opens placement the way picks do
(ADR-0092 §7.1): flag on or off, and with no `use()` pick at all — a fork of the built-in
whose template dropped `use(e)` still carries the change (Journey 6). The gate's docstring
says so.

- **The after** is the source's live id, canonicalised through the index like any pick and
  unioned into the declared picks handed to the selector. It is keyed by id like every pick,
  so every consumer of a placed id that reads the selector's output works unchanged: it
  dedupes with a template's own `use()` of the same entry, `never` applies, the budget never
  drops it, `_tier_lore_ids` tiers it by revision. **Two consumers read `context_items`
  directly, and both filter on `kind == "lore"`:** detection's already-in-context exclusion
  (`picked_ids` in `expand_and_prepare_chat_blocks`) and the door's `edited` signal
  (`chat_changed_picks`, `chats.py`). Both widen to include `change`; without that the after
  is re-journaled as auto-added on a flag-on fork and never marked edited.
- **The before** exists when `snapshot_id` is set: one element in the **stable lore block**,
  produced by **one reader, `render_baseline_element(source_id, snapshot_id)` on the
  change-propagation mixin**, extracted from what `change_message` does today —
  `read_snapshot` on the owning lane, `_fold_propagation_baseline_metadata` for every delta
  lane's own baseline under ADR-0091 §1's since rule, `_render_node_xml` for the element. It
  returns the entry id, the snapshot id, the capture time, the title (the live roster's,
  falling back to the snapshot's) and the XML. `change_message` calls it until S2 removes
  the render from the message. This is the fold ADR-0092 §8 asked for, and it is one
  traversal, not a second; it runs once per send and once per estimate, uncached, which is
  the cost of every pick's render too.
  - The element carries the entry's `id` plus `snapshot="<snapshot id>"` and
    `captured="<captured_at>"` (the renderer takes extra attributes for exactly this), so the
    model joins before and after by id and can tell them apart; the system role names the
    attribute (§4).
  - **Its key is the string `"<entry_id>@<snapshot_id>"`, spelled by one function.** The
    session baseline, the persisted `seen_revisions` and the preview's `entry_xml` are all
    string-keyed maps; the key lives in them beside node ids and never inside the tier's id
    list, so the before cannot dedupe into the after (ADR-0092 §8, Anton's catch) and no
    consumer that reads the id list ever meets it. `seen_revisions`' docstring says it now
    holds these keys; `chat_changed_picks` iterates picks, so it never reads one as a node.
  - **Its tier follows the rule `use(node, "stable")` follows** (ADR-0060 §5, the `"stable"`
    branch of `_tier_lore_ids`): stable from the first turn, volatile for the one turn after
    its bytes change, then stable again. Its revision is the hash of its rendered bytes,
    checked against the session baseline under its key. ADR-0092 §8 is right that it is not
    stable by construction — the renderer resolves reference titles and summaries live, so a
    rename anywhere the source points re-tiers the before once — which is why the check is
    by bytes and not "never".
  - Befores are placed first in the block that holds them, key-sorted, then the live
    elements, so the model reads before then after. An element, not a wire block: provider
    breakpoints stay capped (ADR-0084). Several `change` items are honoured generically:
    afters deduped by id, befores by key.
  - A source under the `never` policy loses both halves, silently, as a `never` pick does.
  - A before the reader cannot produce — the snapshot thinned away, the lane gone, the source
    deleted — places nothing and adds **one entry to the preview's `warnings`**, which the
    composer's estimate already shows in the meta line (the channel the `use_lore()` notice
    rides, ADR-0092 §7.2). The send has no warnings channel and gains none: it places what it
    can and never fails on a missing before.
- **The preview mirrors it.** `AIPreviewRequest` gains `context_items`, the same model, and
  `_preview_lore_tiers` (`backend/app/services/ai/preview.py`) places both halves the same way
  against its throwaway session, the after joining `picked_ids` for the mirror's detection
  too, so the turn-0 door is honest before the first send (ADR-0060 §6). `lore_enabled` stays
  the slot's value: an attachment-only chat reports it false with tier rows present, the
  ADR-0092 §7.1 signal.

### 3 — The door shows the before as its own row, drilled from the block it came with

`PreviewCacheBlock` (`backend/app/models/ai.py`) keeps `entry_ids` as node ids — the door's
`titleFor` (`ChatBodyView.svelte`) resolves those through the rosters and must never see a
key — and gains an additive `snapshots` list, one item per before element on the block, on
whichever tier block holds it: `{entry_id, snapshot_id, captured_at, title, key}`, with the
element's XML in `entry_xml` under that same `key`. The block carries the key so the door
never spells it. S1 fills the list on the send path and the preview alike.

The door is two levels: a **tier row** at the root, a **tier panel** under it. The tier row's
count names the before: "N entries · 1 earlier state", so a turn-one stable block holding
only a before does not read "0 entries". The tier panel lists each before first, labelled with
the roster title (falling back to the item's) and "as of ⟨time⟩" from `relativeTime`
(`frontend/src/lib/utils/relativeTime.ts`; the since selector's own helpers take a whole
`Snapshot` and do not apply), drillable to the XML under its key. **The drill reads the
block's `entry_xml`, never the live per-entry route** (`/api/chats/{id}/lore-xml/{entry_id}`
renders the entry as it is, which would show the after under the before's row). The `edited`
list never names a before: nothing edits a snapshot.

### 4 — Propose attaches the change; the built-in's template does not change

`GET /api/lore/{id}/change-message` keeps its shape. `source_id` and `baseline_snapshot_id`
already say what to attach; `text` shrinks to the question and the endpoint renders no XML
at all:

- with a baseline: "⟨Source⟩ changed since the last propagation. What in this entry needs to
  follow from that change? Propose only what the change warrants; if nothing follows, say so."
- without: "⟨Source⟩ is the source of a change; there is no earlier baseline, so the entry as
  it stands is in your context. What in this entry needs to follow from it? Propose only what
  the entry warrants; if nothing follows, say so."

`proposeFromReviewItem` (`todoActions.svelte.ts`) creates the chat with the attachment in
`context_items` — `openChatFromPromptEntry` takes it as an option and passes it to the create
and to its inputs-echo save in the same change, since that save runs a moment after the
create on every Propose — and holds the question for the composer exactly as it holds the
message today (`composerPrefills`). The chat's three preview requests carry the items: the
lock render (`lockPromptTemplate`, `promptTemplateLock.ts`), the estimate
(`ChatEstimateController`, `chatEstimate.svelte.ts`) and the per-turn payload. **"New chat
with this setup"** (`newChatWithSetup`, `ChatBodyView.svelte`) copies the attachment with the
prompt, inputs and assistant: the change is part of the setup.

`Follow a change` (`backend/app/builtin_library/prompts/follow-a-change.md`) declares no new
input and calls nothing new: `use(e)` and its includes stay. Its system role changes wording,
not moves: the related entry that changed is in the model's context; its state before the
change is the element carrying a `snapshot` attribute, its current state the element for the
same entry carrying none; when there is no earlier state, only the current one is there; if
neither is there, ask for the entry before anything else. The rest of the role, and every
phrase the built-in tests pin, stays word for word. A writer's fork or replacement gets the
change too, because it rides on the conversation and not on the prompt. That is the one place
a writer's own prompt meets a snapshot, and it needs no word for it. A fork made before this
ships keeps the old sentence about the first message, and nothing migrates Library forks:
that fork's model asks for the entry once and the writer edits the fork.

### 5 — What this amends and what it discharges

ADR-0091 §4's "the message stays the carrier of the change: no prompt variable, no vocabulary
registration" becomes: **the conversation carries the change as an attachment the app places;
the message is the question; still no prompt variable and no vocabulary registration.** The
rest of §4 stands.

ADR-0092 §8's constraints, and where each lands: *dedup* → the before's string key beside the
id list (§2); *storage* → a persisted `context_items` item a save cannot wipe (§1); *layers* →
the shared reader folds by ADR-0091 §1 (§2); *identity* → the item carries the entity id
beside the snapshot id (§1); *not stable by construction* → revision by rendered bytes under
the stable-hint rule (§2); *not a wire block* → an element in the stable tier with its own
door row (§2, §3); *ADR-0091 §4* → amended above. The one thing §8 sketched and this ADR does
not build is the prompt word.

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
- **Keep `context_items` a plain list on the save request and rely on the echoes.** Rejected
  by the cold review: the per-turn save in `ChatBodyView` has no unit test, and one future
  save site that omits the field wipes the attachment silently. None-preserve is the rule the
  picks already follow.
- **The base per-revision tier rule for the before.** Rejected: a cold session baseline is
  empty, so the base rule makes the before volatile on the first turn, and every turn one
  Propose conversation would re-write it. The stable-hint rule is the one whose meaning
  matches: stable unless seen and changed.
- **Give the `lore` item kind placement semantics while here.** Not here: ADR-0086 left the
  manual picker outside its decision and no surface produces one; a decision with no consumer
  is the ADR-0005 pattern.
- **A warnings channel on the send.** Rejected: the send's response and its stream carry the
  fit reports and nothing else; the estimate runs before every send and its `warnings` already
  reach the meta line. One channel, already read.
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
  `SaveChatSessionRequest.context_items` becomes None-preserve; `PreviewCacheBlock` gains
  `snapshots`; the change-message response keeps its fields and its `text` shrinks to the
  question; the before element reaches the provider's system blocks inside the stable lore
  block with `snapshot` and `captured` attributes; a missing before is one preview warning.
- **Send path:** `render_baseline_element` extracted from `change_message`; the renderer
  takes extra attributes; `_lore_cache_blocks` and `_budgeted_lore_tiers` learn the
  attachment's two halves and the before's tier; the gate opens on an attachment as on a pick;
  the two `kind == "lore"` filters widen; the commit turn ignores it.
- **Frontend:** Propose creates the chat with the attachment; the create option and the
  inputs-echo save land together; the per-turn payload, the lock render and the estimate
  carry the items; "New chat with this setup" copies them; the door gains the count and the
  before row; `composerPrefills` is unchanged.
- **Built-ins:** `Follow a change`'s role text as §4; its template body unchanged; pre-existing
  forks keep their old sentence.
- **Docs:** `docs/ai-context.md` ("What the AI sees") gains the attachment beside picks and
  automatic lore and the "as of" row under the door's stable tier, and the guides bundle is
  regenerated; ADR-0091 §4 and ADR-0092 §8 get a one-line amendment note pointing here, and
  their README entries say so; the vocabulary reference is untouched, since no word was added.
- **Tests:** create persists the attachment, a save that omits the field preserves it and a
  save that sends the list replaces it; a send places both halves (a wire test: the before
  element, with its `snapshot` attribute, reaches the provider's system blocks in the stable
  tier, the after in a tier by revision); the before never dedupes into the after when the
  template also `use()`s the source; an attachment alone, flag off and no picks, still places;
  a missing snapshot warns on the preview and the send goes; a before whose rendered bytes
  change (rename an entry the source points at) re-tiers once and settles; after a send
  `seen_revisions` holds the key and `chat_changed_picks` reports the after when the source is
  edited and never the before; the commit turn carries neither half; the preview mirror
  carries both halves with `lore_enabled` false and the key in `entry_xml`; a conversation
  windowed past round one still carries the change in its system blocks; the door's tier row
  counts the earlier state, its panel lists the before row with "as of", and the drill shows
  the block's XML (a mount test, the pane displays data); the three preview requests carry the
  items; Propose creates with the attachment, with `""` too, and holds the question; the
  built-in body pins the `snapshot` attribute and no longer says the first message shows the
  entry. Backend tests near the file-size guard (`test_ai_preview.py`, `test_ai_helpers.py`)
  take none of these; the attachment's send tests go beside the lore cache-block tests.
- **Could a user author this?** A writer's own prompt, opened from Propose, gets the change
  without a word for it. A writer cannot attach a snapshot to a conversation they open by
  hand, and that is the anti-goal, not a gap.

## Slices

1. **S1 — the attachment and the send.** §1 and §2 with the preview mirror, the shared
   reader, the block's `snapshots` list and the API fields; every backend test above.
   Backend only; `change_message` still renders, through the reader.
2. **S2 — Propose, the door and the built-in.** §3's door and §4: the create option and the
   echo together, the three preview requests, "New chat with this setup", the shrunk message,
   the role text, the docs and the amendment notes.

One lane, S1 first: S2's rows, key and role text name what S1 defines. Between the two, a
Propose chat still carries the message and no attachment, so nothing regresses in the gap.

## The journey that defines done

1. The writer presses Propose on The Implant's review item. A conversation opens from `Follow
   a change`; the composer holds one line, the question. The door's stable row reads "0
   entries · 1 earlier state" and its volatile row holds The Implant and the dependent;
   drilling the stable row shows The Implant as of the baseline's time, and drilling that
   shows the before element with its `snapshot` attribute.
2. The writer sends. The model names the difference and quotes the one sentence in the
   dependent that must change. The meta line shows the fit and nothing left out; on the
   next turn the after and the dependent have settled into the stable block beside the
   before.
3. Ten turns on, with a history budget set, the first round has left the window. The door
   still shows the earlier state; the model still answers against the change.
4. The writer edits The Implant mid-conversation. The door marks the after as edited; the next
   turn re-sends it volatile, then it settles. The before row does not move.
5. The writer renames an entry The Implant's fields point at. The before's bytes change; it
   rides volatile for one turn and settles; its row never says edited.
6. The baseline snapshot is thinned away. The estimate's meta line carries the warning; the
   next turn places the live source alone, and the send goes.
7. The writer forks `Follow a change` under its own title and drops `use(e)` from the fork by
   mistake. Propose opens the fork; the change is there anyway, because it rides on the
   conversation.
8. The writer chooses "New chat with this setup" from the Propose conversation. The new chat
   carries the change too.

## History

Written when Anton returned to ADR-0092 §8 with two findings from the live run — the history
window drops the change first, and a composer full of XML is not something to ask a writer to
send — and one closed door: no Jinja access to snapshots. The §8 shape, `use(node,
snapshot=)`, went with the door; the constraints under it stood, and each has a home above. The
slot for an app-placed attachment turned out to exist already, persisted on every chat, with a
docstring describing this feature and no producer for it since ADR-0057 named it. Two cold
implementing threads planned the slices from the first draft: they found that the two
consumers reading `context_items` filter on kind, that the send has no warnings channel, that
a save omitting the list wiped it, that the key had no string form, that the base tier rule
would make the before volatile on turn one against the journey's own word, that the door is
two levels deep, that the since selector's time helpers take a whole snapshot, and that three
preview requests and "New chat with this setup" had to carry the items. Each is in the text
now.
