# ADR-0093: A prompt places an entry as it was at a snapshot with `use(node, snapshot=id)`, and Propose's message shrinks to the question

- **Status:** Accepted — 2026-09-23, Anton Lauridsen; text by Claude from Anton's return to
  ADR-0092 §8 after the ADR-0091 live run. Revised twice before acceptance: against two cold
  implementing threads' findings on a first shape, and then to Anton's decision on the
  producer (PR #2161).
  **Discharges ADR-0092 §8** (the deferred snapshot carrier) and **amends ADR-0091 §4 by
  reference** (§5 below). Acceptance alone starts nothing; each slice gets its own issue and
  an explicit go.
- **Feature:** Propose (ADR-0091 §4) carries the source's before and after as placed context
  that every turn of the conversation sees, instead of two XML renders pre-filled into the
  writer's first message; and a prompt author decides that in the prompt's own text.
- **Relates to:** ADR-0091 §1 (the fold that defines the before-state at a layer) and §4 (the
  Propose message, amended here), ADR-0092 §2 (the three words a prompt has), §5 (placement,
  dedup by id, tiers) and §8 (the constraints this design starts from), ADR-0060 §2/§5/§6
  (`use()`, the volatility hint, the preview mirrors the send), ADR-0087 (the snapshot store:
  one lane's file, keyed by entity), ADR-0086 (a declared entry is never dropped), ADR-0084
  (cache tiers), ADR-0067 Amendment 1 (a hidden, caller-seeded input — the pattern the two new
  inputs follow), ADR-0076 (the Context door), ADR-0071 (what owes a migration), #1958 (the
  conversation-history window).
- **Words used here.** The *source*, the *baseline* and the *dependent* keep ADR-0091's
  meanings. *The change* is the source at its baseline (the *before*) and the source as it is
  (the *after*). A *pick* is an entry a prompt names with `use()` (ADR-0092); a *snapshot
  pick* is an entry a prompt names with `use(node, snapshot=id)`. A *before element* is the
  one XML element a snapshot pick renders to; its *key* is the string that names it wherever
  a placed thing is named by a string. The *door* is the Context door; its *tier row* is the
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
`use(node, snapshot=id)` and recorded the constraints any design must meet.

A first draft of this ADR took a different shape: the app would attach the change to the
conversation when Propose opened it, with no call in the prompt. Anton weighed it against the
one criterion that decides it — **a writer must be able to override and customize this
prompt** — and under that shape every prompt Propose launches gets the change whether its
text says so or not, and no prompt can decline or move it: an invisible constant, the kind of
hidden mechanism the "could a user author this?" gate exists to catch. So the producer is the
prompt. The line that places the change is in the prompt's text, and a fork keeps, moves or
deletes it.

## Intent

**A prompt places an entry as it was at a snapshot the way it places the entry as it is.**
`use(node, snapshot=id)` names it; the send carries it on every turn, in the stable tier; the
door shows it; `Follow a change` calls it with two hidden inputs Propose seeds, and its first
message is the question. The template never reads a snapshot's content: it names what to
place, and the app places it.

## Anti-goals

- **Not Jinja access to snapshots.** No `entry(node, snapshot=)` or any call that hands a
  template a snapshot's content as a value. Placing is not reading: `use()` records an id and
  emits nothing, and the render never touches the store.
- **Not a snapshot picker.** No input type that lists an entry's snapshots for a writer to
  choose from. The baseline reaches the prompt the way `entry_type` does (ADR-0067 Amendment
  1): a hidden input the launching surface seeds. A prompt opened by ＋New has none, and the
  role's "ask for it" branch covers that as today.
- **Not an attachment the app places.** The first draft's shape, rejected under §Why.
- **Not a change to detection, the budget, the reach, or the tier rules.** The before is one
  more element the existing rules place; ADR-0092 §§3–5 stand as written.
- **Not on the commit turn.** The commit's `used` turn places the picks alone, as ADR-0092 §7.1
  left it; a snapshot pick does not join it. The extractor reads the transcript, not the
  source.
- **Not compare mode in the chat, and not a snapshot of the dependent.** The dependent arrives
  live through the built-in's `use(e)`, as today.
- **Not auto-send.** The writer sends; ADR-0091 §5 is untouched. A one-line question is one
  keystroke.

## Decision

### 1 — `use(node, snapshot=id)`: one keyword on the call a prompt already has

`use()` (`_use` in `backend/app/services/ai/helpers.py`) gains a keyword-only `snapshot`
argument. `use(node, snapshot=id)` records the pair `(entry id, snapshot id)` into a
per-render slot beside the picks and hints (`used_nodes_slot`, `used_hints_slot`) and emits
nothing, like every `use()` call. Its rules:

- `node` must resolve to **one** entry, the way `entry()` resolves one; a snapshot belongs to
  one entity. A single-select `context_pick` reaches the template as a one-element list
  (`seedPickInput`, the bind layer), and that resolves to its one entry as `entry()` takes
  it; a value resolving to several entries, or to none, records nothing and adds one
  `warnings` entry to the render. An empty `snapshot` — `""`, `None`, or a Jinja undefined,
  because the environment is `StrictUndefined` and a text input left empty is dropped from
  the render's inputs by `inputValuesFromDrafts` (`promptResolution.ts`) — is the plain
  `use(node)`: `""` means the whole entry, as `ChangeMessage.baseline_snapshot_id`
  (`backend/app/models/annotations.py`) and the review item's source block spell it, so a
  template can pass a seeded baseline straight through and get the live entry when there is
  none. Resolution at render is by shape, not existence, as for every `use()`: a well-formed
  id that names nothing passes here and becomes a missing before at the send (§2). A snapshot
  pick records the pair only; it does not add the entry to the picks — the after is the
  template's own `use(node)`.
- The volatility hint is accepted and ignored on a snapshot pick: its tier rule is fixed (§2).
- The render does not consult the store. The id is data; whether the snapshot exists is the
  send's and the preview's question (§2), and the estimate that runs at the lock answers it at
  once.
- **Persistence follows the picks exactly.** `RenderedTemplate` carries `used_snapshots`, a
  list of `{entry_id, snapshot_id}`, beside `used_node_ids` and `used_node_hints`; the
  preview response returns it; the lock reads it from that response (`lockPromptTemplate`
  in `promptTemplateLock.ts` reads the other two there) and `ChatBodyView.svelte` hydrates
  it from the chat and echoes it on every save through its one payload builder;
  `SaveChatSessionRequest` and `ChatSession` (`backend/app/models/ai.py`) carry it under the
  same "None means preserve" rule, so a save that omits it cannot wipe it. One additive,
  defaulted field, as `used_node_hints` was.
- **Vocabulary.** The `use()` row in `docs/prompts/reference.md` (the gate-enforced surface,
  ADR-0060) gains the keyword and one sentence on what it does; the generated manifest, the
  guides bundle (the reference is bundled into the guides, and both generators are gates) and
  the editor's completion follow from the row. No new name is registered, so the gate's name
  check is untouched.

### 2 — What the send places: the before is its own element in the stable block

`expand_and_prepare_chat_blocks` and `_lore_cache_blocks` (`backend/app/services/ai/chat.py`)
place the chat's `used_snapshots` beside its picks, and a snapshot pick opens placement the
way a pick does (ADR-0092 §7.1): flag on or off, and with no live pick at all — the gate's
"has picks" counts both lists, and its docstring says so.

- **The after** is nothing new: the built-in `use()`s the live source as an ordinary pick, and
  every consumer of a placed id works as it does for any pick.
- **The before** is one element in the **stable lore block**, produced by **one reader,
  `render_baseline_element(source_id, snapshot_id)` on the change-propagation mixin**,
  extracted from what `change_message` does today — `read_snapshot` on the owning lane,
  `_fold_propagation_baseline_metadata` for every delta lane's own baseline under ADR-0091 §1's
  since rule, `_render_node_xml` for the element. It canonicalises the id through the index,
  and returns the entry id, the snapshot id, the capture time, the title (the live roster's,
  falling back to the snapshot's) and the XML. `change_message` calls it until S2 removes the
  render from the message. This is the fold ADR-0092 §8 asked for, and it is one traversal,
  not a second; it runs once per send and once per estimate, uncached, which is the cost of
  every pick's render too.
  - The element carries the entry's `id` plus `snapshot="<snapshot id>"` and
    `captured="<captured_at>"` (the renderer gains an extra-attributes parameter for exactly
    this; today it emits `id`, `name` and `aliases` only), so the model joins before and after
    by id and can tell them apart; the system role names the attribute (§4).
  - **Its key is the string `"<entry_id>@<snapshot_id>"`, spelled by one function.** The
    session baseline, the persisted `seen_revisions` and the preview's `entry_xml` are all
    string-keyed maps; the key lives in them beside node ids and never inside the tier's id
    list, so the before cannot dedupe into the after (ADR-0092 §8, Anton's catch) and no
    consumer that reads the id list ever meets it. The tier result carries befores in fields
    of their own, never in the entry pair lists that become `entry_ids`. `seen_revisions`'
    docstring says it now holds these keys; `chat_changed_picks` (`chats.py`) iterates picks,
    so it never reads one as a node and never marks a before edited.
  - **Its tier follows the rule `use(node, "stable")` follows** (ADR-0060 §5, the `"stable"`
    branch of `_tier_lore_ids`), in a tiering step of its own, since that function reads
    nodes by id and a key is not a node: stable from the first turn, volatile for the one
    turn after its bytes change, then stable again. Its revision is the hash of its rendered
    bytes, checked against the session baseline under its key. ADR-0092 §8 is right that it is not
    stable by construction — the renderer resolves reference titles and summaries live, so a
    rename anywhere the source points re-tiers the before once — which is why the check is
    by bytes and not "never".
  - Befores are placed first in the block that holds them, key-sorted, then the live
    elements, so the model reads before then after. An element, not a wire block: provider
    breakpoints stay capped (ADR-0084). Several snapshot picks are honoured generically,
    deduped by key.
  - A source under the `never` policy loses its before as it loses its pick, silently.
  - A before the reader cannot produce — the snapshot thinned away, the lane gone, the source
    deleted — places nothing and adds **one entry to the preview's `warnings`**, which the
    composer's estimate already shows in the meta line (the channel the `use_lore()` notice
    rides, ADR-0092 §7.2). The send has no warnings channel and gains none: it places what it
    can and never fails on a missing before.
- **The preview mirrors it.** `_preview_lore_tiers` (`backend/app/services/ai/preview.py`)
  reads `rendered.used_snapshots` and places the befores the same way against its throwaway
  session, so the turn-0 door is honest before the first send (ADR-0060 §6). `lore_enabled`
  stays the slot's value: a prompt with picks and snapshot picks and no `auto_lore()` reports
  it false with tier rows present, the ADR-0092 §7.1 signal.

### 3 — The door shows the before as its own row, drilled from the block it came with

`PreviewCacheBlock` (`backend/app/models/ai.py`) keeps `entry_ids` as node ids — the door's
`titleFor` (`ChatBodyView.svelte`) resolves those through the rosters and must never see a
key — and gains an additive `snapshots` list, one item per before element on the block, on
whichever tier block holds it: `{entry_id, snapshot_id, captured_at, title, key}`, with the
element's XML in `entry_xml` under that same `key`. The block carries the key so the door
never spells it. S1 fills the list on the preview, the only place a block model exists; the
send's blocks are text and tier, and the door reads the estimate's preview.

The door is two levels: a **tier row** at the root, a **tier panel** under it. The tier row's
count names the before: "N entries · 1 earlier state", so a turn-one stable block holding
only a before does not read "0 entries". The tier panel lists each before first, labelled with
the roster title (falling back to the item's) and "as of ⟨time⟩" from `relativeTime`
(`frontend/src/lib/utils/relativeTime.ts`; the since selector's own helpers take a whole
`Snapshot` and do not apply), drillable to the XML under its key. **The drill reads the
block's `entry_xml`, never the live per-entry route** (`/api/chats/{id}/lore-xml/{entry_id}`
renders the entry as it is, which would show the after under the before's row). The `edited`
list never names a before: nothing edits a snapshot.

### 4 — `Follow a change` places the change with two hidden inputs Propose seeds

`Follow a change` (`backend/app/builtin_library/prompts/follow-a-change.md`) declares two
inputs, both `hidden: true` and not required, on the pattern `Impersonate`'s `as_of` and this
prompt's own `entry_type` already follow: **`source`**, a single-select `context_pick` over
lore, and **`baseline`**, a text holding the owning-lane baseline snapshot id, `""` for the
whole entry. Its template places the change in two lines beside the `use(e)` it has:

```jinja
{% if inputs.source is defined and inputs.source %}{% do use(inputs.source) %}{% do use(inputs.source, snapshot=inputs.baseline|default("")) %}{% endif %}
```

The first call is the after, an ordinary pick; the second is the before, or the same pick
again when `baseline` is empty, which dedupes by id. The guards are the ones `Impersonate`'s
`as_of` line already carries, and they are load-bearing: the environment is
`StrictUndefined`, an empty text input is dropped from the render's inputs, and a raw render
of the built-in (the field-contract test renders it with `entry` and `entry_type` alone)
supplies neither input. A writer who forks the prompt sees both
lines and keeps, moves or deletes them; a writer's own prompt gets the change by declaring the
same two input names. Its system role changes wording, not moves: the related entry that
changed is in the model's context; its state before the change is the element carrying a
`snapshot` attribute, its current state the element for the same entry carrying none; when
there is no earlier state, only the current one is there; if neither is there, ask for the
entry before anything else. The rest of the role, and every phrase the built-in tests pin,
stays word for word. A fork made before this ships keeps the old sentence about the first
message and no placing lines, and nothing migrates Library forks: that fork's model asks for
the entry once and the writer edits the fork.

**Propose seeds them from the review item, not from the endpoint.** The Review items tab
seeds the inputs (`seedConversationInputs`, `chatInputs.ts`) before `proposeFromReviewItem`
(`todoActions.svelte.ts`) fetches the change message, and the item's `source` block already
holds both values (ADR-0091 §3): `source` through `seedPickInput` from `source.node_id`,
titled from the lore roster; `baseline` from `source.snapshot_id`, `""` included; each only
when the prompt declares the input. A thinned baseline therefore still opens the
conversation, and the estimate's warning says what is missing (§2). `GET
/api/lore/{id}/change-message` keeps its shape, renders no XML at all, and supplies the
question alone; its `text` becomes:

- with a baseline: "⟨Source⟩ changed since the last propagation. What in this entry needs to
  follow from that change? Propose only what the change warrants; if nothing follows, say so."
- without: "⟨Source⟩ is the source of a change; there is no earlier baseline, so the entry as
  it stands is in your context. What in this entry needs to follow from it? Propose only what
  the entry warrants; if nothing follows, say so."

The composer holds the question exactly as it holds the message today (`composerPrefills`).
The inputs ride with the chat, so "New chat with this setup" carries the change with the rest
of the setup, and a chat opened by ＋New from the type has neither input and the role asks.

### 5 — What this amends and what it discharges

ADR-0091 §4's "the message stays the carrier of the change: no prompt variable, no vocabulary
registration" becomes: **the prompt places the change with `use(node, snapshot=id)` from two
hidden inputs Propose seeds; the message is the question; no prompt variable, and the one
vocabulary change is a keyword on a call that exists.** The rest of §4 stands.

ADR-0092 §2's "the three words a prompt has" gains nothing: `use()` is still the one word for
placing, and it now places at a time as well as now. §8's constraints, and where each lands:
*dedup* → the before's string key beside the id list (§2); *storage* → `used_snapshots`
captured at the lock render, None-preserve (§1); *layers* → the shared reader folds by
ADR-0091 §1 (§2); *identity* → the pair is recorded together, and a bare snapshot id is never
a key (§1); *not stable by construction* → revision by rendered bytes under the stable-hint
rule (§2); *not a wire block* → an element in the stable tier with its own door row (§2, §3);
*ADR-0091 §4* → amended above.

## Why / rejected alternatives

- **The app attaches the change to the conversation with no call in the prompt** (the first
  draft: a `context_items` item of kind `change`, placed at create). Rejected on the criterion
  that decides this ADR: a writer must be able to override and customize the prompt, and
  under that shape no prompt can decline, move or see the change in its own text. The cold
  reviews of that draft also found that the save request wiped the list, that two consumers
  filtered `context_items` by kind, and that three preview requests had to learn to carry it;
  none of that exists on the pick path, which the lock render already persists.
- **`entry(node, snapshot=id)`, a value the template can print.** Rejected: that is Jinja
  access to snapshot content, Anton's closed door, and nothing needs it. The role names the
  attribute; it does not quote the before.
- **A snapshot input type.** Rejected: a writer choosing a snapshot from a list is a feature
  carrying this one, and the hidden seeded input is the house pattern for a value only the
  launching surface knows (`entry_type`, `as_of`).
- **A composite id through the pick list.** Rejected: the pick list is read as node ids by the
  selector, the fit, the tiering, the session baseline, the door, the fit report and the
  matcher's exclusion; §8 named this and the first draft of ADR-0092 fell into it.
- **The base per-revision tier rule for the before.** Rejected: a cold session baseline is
  empty, so the base rule makes the before volatile on the first turn, and every turn one
  Propose conversation would re-write it. The stable-hint rule is the one whose meaning
  matches: stable unless seen and changed.
- **Check the snapshot exists at render time.** Rejected: the render would read the store,
  which is the access the anti-goal forbids, and the estimate that runs at the lock reports
  the same warning a moment later through the channel that already exists.
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
  shape was not, and the shape changed twice on return.

## Consequences

- **Storage:** one additive, defaulted `used_snapshots` list on the chat; chats persisted
  before read unchanged. Precedent: `seen_revisions` (#1635) and `used_node_hints` (ADR-0060
  §5) were added the same way with no migration. ADR-0071's ladder is for a shape a reader
  must convert; there is none here.
- **API / wire:** the preview response carries `used_snapshots` and `PreviewCacheBlock` gains
  `snapshots`; `SaveChatSessionRequest` and `ChatSession` carry `used_snapshots` None-preserve;
  the change-message response keeps its fields and its `text` shrinks to the question; the
  before element reaches the provider's system blocks inside the stable lore block with
  `snapshot` and `captured` attributes; a missing before, a list, or an unresolvable node is
  one preview warning.
- **Prompt vocabulary:** the `use()` row gains the keyword; the manifest and the completion
  regenerate from it; no new name.
- **Send path:** `render_baseline_element` extracted from `change_message`; the renderer
  takes extra attributes; `_lore_cache_blocks` and `_budgeted_lore_tiers` learn the snapshot
  picks and the before's tier; the gate counts them as picks; the commit turn ignores them.
  The fit report does not count a before: `LoreFit` is id-keyed and the budget never touches
  a declared thing; the estimate's block token count includes its bytes. `change_message`'s
  before block gains the two attributes in S1, the one visible change before S2.
- **Frontend:** the lock (`promptTemplateLock.ts`) captures `used_snapshots`, `ChatBodyView`
  hydrates it and every save echoes it beside the other two lists; the seeder fills `source`
  and `baseline` from the review item; the door gains the count and the before row, "N
  earlier states" when several; `composerPrefills` is unchanged.
- **Built-ins:** `Follow a change` gains the two hidden inputs and the two placing lines; its
  role text as §4; pre-existing forks keep their old sentence and place nothing.
- **Docs:** `docs/ai-context.md` ("What the AI sees") gains the snapshot pick beside picks
  and automatic lore and the "as of" row under the door's stable tier, and the guides bundle
  is regenerated; ADR-0091 §4 and ADR-0092 §8 get a one-line amendment note pointing here,
  and their README entries say so.
- **Tests:** `use(node, snapshot=id)` records the pair and emits nothing, ignores the hint,
  treats `""` and an undefined as a plain pick, resolves a one-element list, and warns on
  several entries or an unresolvable node; the lock render
  returns `used_snapshots` and a save that omits it preserves it; a send places the before
  (a wire test: the element, with its `snapshot` attribute, reaches the provider's system
  blocks in the stable tier) and the after as a pick; the before never dedupes into the after;
  a snapshot pick alone, flag off, still places; a missing snapshot warns on the preview and
  the send goes; a before whose rendered bytes change (rename an entry the source points at)
  re-tiers once and settles; after a send `seen_revisions` holds the key and
  `chat_changed_picks` never names the before; the commit turn carries no before; the preview
  mirror carries it with `lore_enabled` false and the key in `entry_xml`; a conversation
  windowed past round one still carries the change in its system blocks; the door's tier row
  counts the earlier state, its panel lists the before row with "as of", and the drill shows
  the block's XML (a mount test, the pane displays data); the seeder fills both inputs from the
  item, and `""` too; Propose holds the question; the built-in's pinned input set grows to
  four, its body pins the two guarded placing calls and the `snapshot` attribute and no longer
  says the first message shows the entry, and the field-contract test's raw render of it
  still passes; the vocabulary
  gate and generator on the changed row. Backend tests near the file-size guard
  (`test_ai_helpers.py` at six lines under the cap, `test_ai_preview.py`) take none of these.
- **Could a user author this?** Yes, and that is the point: a writer's prompt calls
  `use(inputs.source, snapshot=inputs.baseline)` where they can read it, and Propose fills the
  two inputs the way it fills `entry_type`.

## Slices

1. **S1 — the call, the capture and the send.** §1 and §2 with the preview mirror, the shared
   reader, the block's `snapshots` list, the vocabulary row and its generated artifacts, and
   every backend test above. Backend, the reference, the manifest and the guides bundle;
   `change_message` still renders, through the reader. Until S2 the frontend does not echo `used_snapshots`, so no
   chat persists one and nothing changes for a writer.
2. **S2 — the lock echo, the seeder, the door and the built-in.** §3 and §4: the capture and
   the save echo, the two seeded inputs, the shrunk message, the role text and the placing
   lines, the docs and the amendment notes.

One lane, S1 first: S2's rows, key and role text name what S1 defines.

## The journey that defines done

1. The writer presses Propose on The Implant's review item. A conversation opens from `Follow
   a change`; the composer holds one line, the question. The door's stable row reads "0
   entries · 1 earlier state" and its volatile row holds The Implant and the dependent;
   drilling the stable row shows The Implant as of the baseline's time, and drilling that
   shows the before element with its `snapshot` attribute. Both seeded inputs are hidden, so
   the door's locked inputs show neither; the rows are where the change is seen.
2. The writer sends. The model names the difference and quotes the one sentence in the
   dependent that must change. The meta line shows the fit and nothing left out; on the next
   turn the after and the dependent have settled into the stable block beside the before.
3. Ten turns on, with a history budget set, the first round has left the window. The door
   still shows the earlier state; the model still answers against the change.
4. The writer edits The Implant mid-conversation. The door marks the after as edited; the next
   turn re-sends it volatile, then it settles. The before row does not move.
5. The writer renames an entry The Implant's fields point at. The before's bytes change; it
   rides volatile for one turn and settles; its row never says edited.
6. The baseline snapshot is thinned away. The estimate's meta line carries the warning; the
   next turn places the live source alone, and the send goes.
7. The writer forks `Follow a change` under its own title and deletes the line that places the
   before, wanting only the entry as it is. Propose opens the fork; the door shows no earlier
   state, and the role they rewrote says what to do with the current one.
8. The writer opens `Follow a change` from ＋New on a character with no review item. Neither
   input is seeded, nothing extra is placed, and the model asks for the entry that changed.

## History

Written when Anton returned to ADR-0092 §8 with two findings from the live run — the history
window drops the change first, and a composer full of XML is not something to ask a writer to
send. The first draft placed the change as an attachment the app put on the conversation,
with no call in the prompt, on the reading that a writer cannot type a snapshot id. Two cold
implementing threads planned its slices and found the seams that shape survived on: a save
that wiped the attachment, two consumers filtering the slot by kind, the key with no string
form, the base tier rule making the before volatile on turn one, the door's two levels, three
preview requests to teach. Anton then weighed the two producers against the criterion that a
writer must be able to override and customize the prompt, and chose the call: the line that
places the change belongs in the prompt's text, and the two inputs it reads are seeded the
way `entry_type` already is. `entry(node, snapshot=)` stays out, because placing is not
reading. The findings that were about placement, not about the producer, are in the text
above. Two more cold threads planned the slices of this text before acceptance and found:
the verbatim placing line raised under the strict environment on the whole-entry path and
on a raw render; the seeder runs before the change-message fetch, so the baseline seeds from
the review item; a single-select pick is a one-element list; both hidden inputs are hidden
from the door; the send has no block model; the tier function reads nodes by id; the tier
result needed fields of its own; the guides bundle regenerates from the row too. Each is in
the text now.
